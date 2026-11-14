"""Modular & Self-Optimizing Assist Co-Pilot Engine for Otis AI Companion."""

from __future__ import annotations

import copy
from datetime import datetime, UTC
from difflib import SequenceMatcher
import hashlib
import json
import logging
import re
from typing import Any

import yaml

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

COPILOT_CONFIG_STORAGE_VERSION = 1
COPILOT_CONFIG_STORAGE_KEY = f"{DOMAIN}.copilot_config"

COPILOT_MEMORY_STORAGE_VERSION = 1
COPILOT_MEMORY_STORAGE_KEY = f"{DOMAIN}.copilot_memory"

MAX_LEARNED_FACTS = 50
MAX_OPTIMIZATION_HISTORY = 50


class _NoAliasSafeDumper(yaml.SafeDumper):
    """YAML SafeDumper that never emits &id001 / *id001 anchors."""

    def ignore_aliases(self, data: Any) -> bool:
        """Disable YAML aliases."""
        return True


DEFAULT_PROMPT_RULES: dict[str, dict[str, Any]] = {
    "sun_elevation_grounding": {
        "enabled": True,
        "text": (
            "Sun & Solar Elevation Grounding: Home Assistant natively tracks sun position via `sun.sun` "
            "(with `attribute: elevation` and `azimuth`) and `sensor.sun_solar_elevation` "
            "(disabled by default in the Sun integration). Always use `condition: numeric_state` with "
            "`entity_id: sensor.sun_solar_elevation` (if enabled) or `entity_id: sun.sun` + "
            "`attribute: elevation` (e.g., `below: 4`). NEVER claim Home Assistant lacks sun elevation support."
        ),
    },
    "automation_delivery": {
        "enabled": True,
        "text": (
            "Automation Delivery: Supply a single clean Home Assistant YAML block "
            "(`alias:`, `triggers:`, `conditions:`, `actions:`) so the UI can render the 1-click "
            "**Deploy & Enable Automation** button."
        ),
    },
}

DEFAULT_CONDITION_TEMPLATES: dict[str, dict[str, Any]] = {
    "sun_elevation_below": {
        "condition": "numeric_state",
        "entity_id": "sun.sun",
        "attribute": "elevation",
        "below": 4,
    },
    "sun_elevation_above": {
        "condition": "numeric_state",
        "entity_id": "sun.sun",
        "attribute": "elevation",
        "above": 0,
    },
    "after_sunset": {
        "condition": "sun",
        "after": "sunset",
    },
}

_CONFIRMATION_WORDS = {
    "yes",
    "y",
    "apply",
    "confirm",
    "go ahead",
    "do it",
    "deploy",
    "deploy it",
    "apply it",
}
_REJECTION_WORDS = {"no", "n", "cancel", "don't", "stop", "reject"}
_REJECTION_PHRASES = (
    "cancel",
    "don't",
    "dont",
    "abort",
    "discard",
    "nevermind",
    "do not deploy",
    "don't deploy",
)
_CRITIQUE_WORDS = (
    "why",
    "supposed",
    "should",
    "how",
    "what",
    "instead",
    "change",
    "update",
    "modify",
    "missing",
    "ignored",
    "wrong",
    "incorrect",
    "didn't",
    "did not",
    "wasn't",
    "not considered",
)
_CONFIRMATION_PHRASES = (
    "deploy",
    "apply",
    "confirm",
    "go ahead",
    "do it",
    "yes",
    "create it",
    "set it up",
    "add it",
    "deploy it",
    "deploy this",
    "deploy automation",
    "create this",
    "create automation",
)

_UNHANDLED_CONDITION_KEYWORDS = (
    "lux",
    "illuminance",
    "brightness",
    "between ",
    "weekday",
    "weekend",
    "nobody home",
    "everyone away",
    "guest",
    "temperature",
    "humidity",
    "door ",
    "window ",
    "media_player",
    "tv ",
    "television",
)

_SUN_ELEVATION_PATTERN = re.compile(
    r"(?:sun\s*elevation|solar\s*elevation|elevation)\s*(?:is\s*)?"
    r"(below|under|less than|<|above|over|greater than|>)\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def classify_confirmation_intent(user_text: str) -> dict[str, bool]:
    """Strictly classify whether user_text is a confirmation, rejection, or critique/question."""
    lowered = str(user_text or "").strip().lower()
    critique_or_question = "?" in lowered or any(w in lowered for w in _CRITIQUE_WORDS)
    is_rejection = lowered in _REJECTION_WORDS or any(k in lowered for k in _REJECTION_PHRASES)
    is_confirmation = (
        not is_rejection
        and not critique_or_question
        and (
            lowered in _CONFIRMATION_WORDS
            or (
                len(lowered.split()) <= 12
                and any(k in lowered for k in _CONFIRMATION_PHRASES)
            )
        )
    )
    return {
        "is_confirmation": is_confirmation,
        "is_rejection": is_rejection,
        "is_critique_or_question": critique_or_question,
    }


def has_unhandled_conditions(user_lower: str, *, allow_media: bool = False) -> bool:
    """Return True if the user prompt asks for conditions outside the deterministic fast-path."""
    media_keys = {"media_player", "tv ", "television"}
    return any(
        k in user_lower
        for k in _UNHANDLED_CONDITION_KEYWORDS
        if not (allow_media and k in media_keys)
    )


def _compile_spec_trigger(trig: dict[str, Any]) -> dict[str, Any]:
    """Normalize a JSON trigger spec dict into modern Home Assistant trigger YAML."""
    t_type = str(trig.get("trigger") or trig.get("type") or trig.get("platform") or "state").strip()
    out: dict[str, Any] = {"trigger": t_type}
    for k in ("id", "entity_id", "to", "from", "above", "below", "at", "for", "attribute", "event", "event_type", "value_template"):
        if k in trig and trig[k] is not None:
            out[k] = trig[k]
    return out


def _compile_spec_condition(cond: dict[str, Any]) -> dict[str, Any]:
    """Normalize a JSON condition spec dict into modern Home Assistant condition YAML."""
    c_type = str(cond.get("condition") or cond.get("type") or "state").strip()
    if c_type == "binary_sensor":
        c_type = "state"
    if c_type == "state" and ("above" in cond or "below" in cond):
        c_type = "numeric_state"
    if "not_equal_to" in cond and "entity_id" in cond:
        return {
            "condition": "not",
            "conditions": [{"condition": "state", "entity_id": cond["entity_id"], "state": cond["not_equal_to"]}],
        }
    out: dict[str, Any] = {"condition": c_type}
    if c_type in ("or", "and", "not") and isinstance(cond.get("conditions"), list):
        out["conditions"] = [_compile_spec_condition(c) for c in cond["conditions"] if isinstance(c, dict)]
        return out
    for k in ("id", "entity_id", "state", "above", "below", "after", "before", "attribute", "value_template"):
        if k in cond and cond[k] is not None:
            out[k] = cond[k]
    return out


def _compile_spec_action(act: dict[str, Any]) -> dict[str, Any]:
    """Normalize a JSON action spec dict into modern Home Assistant action YAML."""
    if "choose" in act and isinstance(act["choose"], list):
        compiled_choices = []
        for br in act["choose"]:
            if isinstance(br, dict):
                compiled_choices.append({
                    "conditions": [_compile_spec_condition(c) for c in (br.get("conditions") or []) if isinstance(c, dict)],
                    "sequence": [_compile_spec_action(a) for a in (br.get("sequence") or br.get("actions") or []) if isinstance(a, dict)],
                })
        res: dict[str, Any] = {"choose": compiled_choices}
        if isinstance(act.get("default"), list) and act["default"]:
            res["default"] = [_compile_spec_action(a) for a in act["default"] if isinstance(a, dict)]
        return res

    svc = str(act.get("action") or act.get("service") or "").strip()
    if not svc:
        return dict(act)
    out: dict[str, Any] = {"action": svc}
    eid = act.get("entity_id") or act.get("target_entity_id")
    target = act.get("target")
    if isinstance(target, dict) and target:
        out["target"] = dict(target)
    elif eid is not None:
        out["target"] = {"entity_id": eid}
    data = act.get("data")
    if isinstance(data, dict) and data:
        out["data"] = dict(data)
    else:
        extra_data = {
            k: v
            for k, v in act.items()
            if k not in ("action", "service", "entity_id", "target_entity_id", "target", "data") and v is not None
        }
        if extra_data:
            out["data"] = extra_data
    return out


def compile_automation_spec_to_yaml(spec: dict[str, Any]) -> dict[str, Any]:
    """Deterministically compile a structured JSON automation spec into modern Home Assistant YAML."""
    mode_val = str(spec.get("mode") or "single").strip().lower()
    if mode_val not in ("single", "restart", "queued", "parallel"):
        mode_val = "single"

    compiled: dict[str, Any] = {
        "alias": str(spec.get("alias") or "Otis Automation").strip(),
        "description": str(spec.get("description") or "").strip(),
        "triggers": [
            _compile_spec_trigger(t) for t in (spec.get("triggers") or spec.get("trigger") or []) if isinstance(t, dict)
        ],
        "conditions": [
            _compile_spec_condition(c) for c in (spec.get("conditions") or spec.get("condition") or []) if isinstance(c, dict)
        ],
    }

    branches = spec.get("branches") or spec.get("choose")
    if isinstance(branches, list) and branches:
        choose_list = []
        for br in branches:
            if not isinstance(br, dict):
                continue
            br_conds = br.get("conditions") or br.get("when") or []
            br_acts = br.get("actions") or br.get("sequence") or br.get("then") or []
            choose_list.append({
                "conditions": [_compile_spec_condition(c) for c in br_conds if isinstance(c, dict)],
                "sequence": [_compile_spec_action(a) for a in br_acts if isinstance(a, dict)],
            })
        choose_block: dict[str, Any] = {"choose": choose_list}
        default_acts = spec.get("default") or spec.get("else") or []
        if isinstance(default_acts, list) and default_acts:
            choose_block["default"] = [_compile_spec_action(a) for a in default_acts if isinstance(a, dict)]
        compiled["actions"] = [choose_block]
    else:
        raw_acts = spec.get("actions") or spec.get("action") or []
        compiled["actions"] = [_compile_spec_action(a) for a in raw_acts if isinstance(a, dict)]

    compiled["mode"] = mode_val
    return compiled


def compile_json_automation_blocks(speech: str) -> str:
    """Convert any ```json / ```automation_spec automation blocks into verified Home Assistant ```yaml blocks."""
    if not speech or "```" not in speech:
        return speech

    def _replace_json_block(match: re.Match) -> str:
        raw_json = match.group(1).strip()
        try:
            parsed = json.loads(raw_json)
        except Exception:
            return match.group(0)
        if not isinstance(parsed, dict) or "alias" not in parsed:
            return match.group(0)
        if not any(k in parsed for k in ("triggers", "trigger", "branches", "choose", "actions", "action")):
            return match.group(0)
        compiled = compile_automation_spec_to_yaml(parsed)
        yaml_str = yaml.dump(compiled, Dumper=_NoAliasSafeDumper, sort_keys=False, default_flow_style=False).strip()
        return f"```yaml\n{yaml_str}\n```"

    return re.sub(r"```(?:json|automation_spec)\s*\n(.*?)```", _replace_json_block, speech, flags=re.DOTALL)


NON_ENV_SENSOR_TOKENS = (
    "_battery",
    "_voltage",
    "_linkquality",
    "_rssi",
    "_lqi",
    "_power",
    "_energy",
    "_offset",
    "_calibration",
    "_threshold",
    "_target",
    "_setpoint",
    "_min",
    "_max",
    "_alarm",
    "_status",
    "_tamper",
    "_problem",
)


def is_valid_env_sensor(eid: str, metric: str | None = None, device_class: str = "") -> bool:
    """Return True if a sensor entity ID is a genuine ambient/environmental reading (not battery/diagnostic)."""
    e_low = (eid or "").strip().lower()
    dc_low = (device_class or "").strip().lower()
    if not e_low.startswith("sensor."):
        return False
    if any(tok in e_low for tok in NON_ENV_SENSOR_TOKENS):
        return False
    if dc_low in ("battery", "voltage", "signal_strength", "power", "energy", "current", "timestamp"):
        return False
    if metric == "temperature":
        if dc_low and dc_low != "temperature":
            return False
        if any(other in e_low for other in ("humidity", "illuminance", "lux", "pressure", "dew_point", "heat_index")):
            return False
        return dc_low == "temperature" or bool(re.search(r"(?:^|[._])(?:temp|temperature)(?:$|[._])", e_low))
    if metric == "humidity":
        if dc_low and dc_low != "humidity":
            return False
        if any(other in e_low for other in ("illuminance", "lux", "pressure")):
            return False
        return dc_low == "humidity" or "humidity" in e_low
    if metric == "illuminance":
        if dc_low and dc_low != "illuminance":
            return False
        return dc_low == "illuminance" or any(k in e_low for k in ("illuminance", "lux"))
    return dc_low in ("temperature", "humidity", "illuminance") or bool(
        re.search(r"(?:^|[._])(?:temp|temperature|humidity|illuminance|lux)(?:$|[._])", e_low)
    )


def try_synthesize_room_fan_automation(
    user_text: str,
    target_room_context: str,
    learned_facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Deterministically synthesize a multi-threshold room fan automation when room entities and thresholds are unambiguous."""
    text = (user_text or "").strip()
    low = text.lower()
    if not target_room_context or "fan" not in low:
        return None
    if not any(v in low for v in ("create ", "write ", "make ", "build ", "generate ")) or "automation" not in low:
        return None

    # Extract room name and verified entities from target_room_context
    room_match = re.search(r"VERIFIED ENTITIES IN TARGET ROOM \(([^—\n)]+)", target_room_context)
    room_name = room_match.group(1).strip() if room_match else "Room"

    def _first_entity(prefix: str, line_prefix: str, predicate: Any = None) -> str | None:
        m = re.search(rf"{re.escape(line_prefix)}:\s*(.+)", target_room_context)
        if not m:
            return None
        for part in m.group(1).split(","):
            cand = part.strip().split()[0]
            if cand.startswith(prefix) and (predicate is None or predicate(cand)):
                return cand
        return None

    fan_eid = _first_entity("fan.", "  - Fans")
    temp_eid = _first_entity(
        "sensor.",
        "  - Temperature/Environment Sensors",
        lambda e: is_valid_env_sensor(e, metric="temperature"),
    )
    occ_eid = _first_entity("binary_sensor.", "  - Occupancy/Motion Sensors")
    if not fan_eid or not temp_eid:
        return None

    speed_map = {"low": 33, "medium": 66, "med": 66, "high": 100}
    # Match clauses pairing a speed keyword with an above/over threshold in either order
    above_rules: list[tuple[float, int]] = []
    clauses = re.split(r"[,;.]|\bthen\b", low)
    for clause in clauses:
        speed_m = re.search(r"\b(low|medium|med|high)\b", clause)
        above_m = re.search(r"\b(?:above|over|exceeds?|greater than|>)\s*(\d+(?:\.\d+)?)", clause)
        if speed_m and above_m:
            thr = float(above_m.group(1))
            thr_val: int | float = int(thr) if thr.is_integer() else thr
            above_rules.append((thr_val, speed_map[speed_m.group(1)]))

    if not above_rules:
        return None

    # Sort descending so choose: evaluates the highest temperature threshold first (e.g. >72 before >70)
    above_rules.sort(key=lambda x: x[0], reverse=True)

    below_m = re.search(r"\b(?:below|under|falls below|drops below|less than|<)\s*(\d+(?:\.\d+)?)", low)
    below_val: int | float | None = None
    if below_m:
        b_num = float(below_m.group(1))
        below_val = int(b_num) if b_num.is_integer() else b_num

    requires_occ = bool(occ_eid and any(k in low for k in ("occupied", "occupancy", "unoccupied", "presence", "motion")))

    triggers: list[dict[str, Any]] = []
    if requires_occ and occ_eid:
        triggers.append({"type": "state", "entity_id": occ_eid})
    for thr_val, _ in sorted(above_rules, key=lambda x: x[0]):
        triggers.append({"type": "numeric_state", "entity_id": temp_eid, "above": thr_val})
    if below_val is not None:
        triggers.append({"type": "numeric_state", "entity_id": temp_eid, "below": below_val})

    branches: list[dict[str, Any]] = []
    for thr_val, pct in above_rules:
        conds: list[dict[str, Any]] = []
        if requires_occ and occ_eid:
            conds.append({"type": "state", "entity_id": occ_eid, "state": "on"})
        conds.append({"type": "numeric_state", "entity_id": temp_eid, "above": thr_val})
        branches.append({
            "conditions": conds,
            "actions": [{"action": "fan.set_percentage", "entity_id": fan_eid, "data": {"percentage": pct}}],
        })

    mode_val = "single"
    for fact in learned_facts or []:
        if "mode: restart" in str(fact.get("fact", "")).lower():
            mode_val = "restart"
            break

    spec = {
        "alias": f"{room_name} Fan Control",
        "description": f"Automatically controls the {room_name} fan based on temperature"
        + (" and occupancy." if requires_occ else "."),
        "mode": mode_val,
        "triggers": triggers,
        "conditions": [],
        "branches": branches,
        "default": [{"action": "fan.turn_off", "entity_id": fan_eid}],
    }
    compiled = compile_automation_spec_to_yaml(spec)
    yaml_str = yaml.dump(compiled, Dumper=_NoAliasSafeDumper, sort_keys=False, default_flow_style=False).strip()
    return {
        "alias": compiled["alias"],
        "yaml_data": compiled,
        "yaml_str": yaml_str,
    }


def _extract_verified_room_entities(target_room_context: str) -> tuple[str, dict[str, list[str]]]:
    """Extract room name and verified entity IDs grouped by domain from target_room_context."""
    room_match = re.search(r"VERIFIED ENTITIES IN TARGET ROOM \(([^—\n)]+)", target_room_context or "")
    room_name = room_match.group(1).strip() if room_match else "Room"
    by_domain: dict[str, list[str]] = {}
    for line in (target_room_context or "").splitlines():
        if ":" not in line or not line.strip().startswith("- "):
            continue
        _, rhs = line.split(":", 1)
        for part in rhs.split(","):
            cand = part.strip().split()[0] if part.strip() else ""
            if "." in cand and re.match(r"^[a-z_]+\.[a-z0-9_]+$", cand):
                dom = cand.split(".", 1)[0]
                bucket = by_domain.setdefault(dom, [])
                if cand not in bucket:
                    bucket.append(cand)
    return room_name, by_domain


def try_synthesize_room_lighting_automation(
    user_text: str,
    target_room_context: str,
    learned_facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Deterministically synthesize a room occupancy/motion lighting automation when room entities are unambiguous."""
    text = (user_text or "").strip()
    low = text.lower()
    if not target_room_context or "fan" in low:
        return None
    if not any(v in low for v in ("create ", "write ", "make ", "build ", "generate ")) or "automation" not in low:
        return None
    if not any(k in low for k in ("light", "lights", "lighting", "lamp")):
        return None
    if not any(k in low for k in ("occupied", "occupancy", "unoccupied", "motion", "presence", "detected", "vacant")):
        return None
    if has_unhandled_conditions(low):
        return None

    room_name, by_domain = _extract_verified_room_entities(target_room_context)
    occ_eids = [
        e for e in by_domain.get("binary_sensor", [])
        if any(k in e for k in ("occupancy", "motion", "presence", "person"))
        and not any(bad in e for bad in ("_all_occupancy", "_dog_occupancy", "_pet", "_vehicle", "_battery", "_tamper", "_problem"))
    ]
    light_eids = by_domain.get("light", [])
    if not occ_eids or not light_eids:
        return None

    # Parse optional off-delay duration (e.g. "5 minutes after", "30 seconds after")
    off_for: dict[str, int] | None = None
    dur_m = re.search(r"\b(\d+)\s*(minute|minutes|min|mins|second|seconds|sec|secs|hour|hours|hr|hrs)\b", low)
    if dur_m:
        qty = max(1, int(dur_m.group(1)))
        unit = dur_m.group(2)
        if unit.startswith("sec"):
            off_for = {"seconds": qty}
        elif unit.startswith(("hour", "hr")):
            off_for = {"hours": qty}
        else:
            off_for = {"minutes": qty}

    occ_target: str | list[str] = occ_eids[0] if len(occ_eids) == 1 else occ_eids
    light_target: str | list[str] = light_eids[0] if len(light_eids) == 1 else light_eids

    off_trigger: dict[str, Any] = {
        "type": "state",
        "entity_id": occ_target,
        "to": "off",
        "id": "motion_cleared",
    }
    if off_for:
        off_trigger["for"] = off_for

    mode_val = "restart"
    for fact in learned_facts or []:
        f_low = str(fact.get("fact", "")).lower()
        if "mode: single" in f_low:
            mode_val = "single"
            break

    spec = {
        "alias": f"{room_name}: Motion & Occupancy Lighting",
        "description": (
            f"Turns on {room_name} lighting when occupancy is detected and turns it off "
            + (f"{list(off_for.values())[0]} {list(off_for.keys())[0]} after becoming unoccupied." if off_for else "when unoccupied.")
        ),
        "mode": mode_val,
        "triggers": [
            {"type": "state", "entity_id": occ_target, "to": "on", "id": "motion_detected"},
            off_trigger,
        ],
        "conditions": [],
        "branches": [
            {
                "conditions": [{"type": "trigger", "id": "motion_detected"}],
                "actions": [{"action": "light.turn_on", "entity_id": light_target}],
            },
            {
                "conditions": [{"type": "trigger", "id": "motion_cleared"}],
                "actions": [{"action": "light.turn_off", "entity_id": light_target}],
            },
        ],
    }
    compiled = compile_automation_spec_to_yaml(spec)
    yaml_str = yaml.dump(compiled, Dumper=_NoAliasSafeDumper, sort_keys=False, default_flow_style=False).strip()
    return {
        "alias": compiled["alias"],
        "yaml_data": compiled,
        "yaml_str": yaml_str,
    }


def is_explanatory_query(user_text: str) -> bool:
    """Return True when the user is asking for an explanation/comparison/example rather than creating an automation."""
    u_low = (user_text or "").strip().lower()
    if not u_low:
        return False
    return (
        any(
            k in u_low
            for k in (
                "explain ",
                "difference between",
                "what is the difference",
                "how do ",
                "how does ",
                "compare ",
            )
        )
        and not any(
            v in u_low
            for v in (
                "create ",
                "make ",
                "write ",
                "build ",
                "generate ",
                "deploy ",
                "enable ",
                "add ",
            )
        )
    )


def validate_and_upgrade_assistant_response(
    hass: HomeAssistant | None,
    speech: str,
    target_room_context: str = "",
    user_text: str = "",
) -> tuple[str, list[str], int]:
    """Ensure consistent response quality across all agents, auto-upgrade deprecated YAML syntax, and detect hallucinations."""
    if not speech:
        return speech, [], 0

    notes: list[str] = []
    penalty = 0
    upgraded = compile_json_automation_blocks(speech)
    explanatory = is_explanatory_query(user_text)

    # 1. Auto-upgrade deprecated YAML keys & unwrap nested automation:/script: inside ```yaml ... ``` blocks
    def _upgrade_yaml_block(match: re.Match) -> str:
        nonlocal penalty
        block = match.group(1)
        orig_block = block
        # Unwrap top-level automation: or script: wrapper if present
        if re.match(r"^\s*(?:automation|automations|script|scripts):\s*\n", block):
            lines_in = block.splitlines()
            unwrapped_lines: list[str] = []
            in_wrapper = False
            for ln in lines_in:
                if re.match(r"^\s*(?:automation|automations|script|scripts):\s*$", ln):
                    in_wrapper = True
                    continue
                if in_wrapper:
                    unwrapped_lines.append(re.sub(r"^  ", "", ln))
                else:
                    unwrapped_lines.append(ln)
            block = "\n".join(unwrapped_lines)
            penalty += 1

        # Upgrade top-level trigger:/condition:/action: to triggers:/conditions:/actions:
        block = re.sub(r"(?m)^trigger:(\s*(?:\[\])?)\s*$", r"triggers:\1", block)
        block = re.sub(r"(?m)^condition:(\s*(?:\[\])?)\s*$", r"conditions:\1", block)
        block = re.sub(r"(?m)^action:(\s*(?:\[\])?)\s*$", r"actions:\1", block)
        # Upgrade invalid mode values (e.g. mode: auto or mode: immediate -> mode: single)
        block = re.sub(r"(?m)^mode:\s*(?:auto|immediate)\s*$", "mode: single", block)
        # Upgrade "- platform:" to "- trigger:" inside triggers
        if re.search(r"(?m)^\s*-\s*platform:\s+", block):
            block = re.sub(r"(?m)^(\s*-\s*)platform:(\s+)", r"\1trigger:\2", block)
            notes.append("Always use modern 'trigger:' instead of deprecated 'platform:' inside automation triggers.")
            penalty += 1
        # Upgrade invalid "- trigger: presence" to "- trigger: state"
        if re.search(r"(?m)^\s*-\s*trigger:\s*presence\s*$", block):
            block = re.sub(r"(?m)^(\s*-\s*trigger:\s*)presence\s*$", r"\1state", block)
            block = re.sub(r"(?m)^(\s*)presence:\s*true\s*$", r'\1to: "on"', block)
            penalty += 1
        # Upgrade invalid "- trigger: condition.state" inside conditions to "- condition: state"
        block = re.sub(r"(?m)^(\s*-\s*)trigger:\s*condition\.state\s*$", r"\1condition: state", block)
        # Upgrade "service:" to "action:" inside action steps
        if re.search(r"(?m)^\s*-?\s*service:\s+[a-z0-9_]+\.[a-z0-9_]+", block):
            block = re.sub(r"(?m)^(\s*-?\s*)service:(\s+[a-z0-9_]+\.[a-z0-9_]+)", r"\1action:\2", block)
            notes.append(
                "Always use modern 'action: domain.service' instead of deprecated 'service:' in Home Assistant automations and scripts."
            )
            penalty += 1
        # Upgrade hallucinated "- action: hold" + "hold_time: Xm" to valid HA "- delay:"
        if re.search(r"(?m)^\s*-\s*action:\s*hold\b", block):
            block = re.sub(
                r"(?m)^(\s*)-\s*action:\s*hold\s*\n(?:\1\s+(?:target|entity_id):.*\n(?:\1\s+entity_id:.*\n)?)?\1\s+hold_time:\s*['\"]?(\d+)\s*m(?:in(?:utes?)?)?['\"]?\s*$",
                r"\1- delay:\n\1    minutes: \2",
                block,
            )
            block = re.sub(r"(?m)^(\s*)-\s*action:\s*hold\s*$", r"\1- delay:\n\1    minutes: 5", block)
            notes.append("Use valid Home Assistant '- delay: {minutes: N}' instead of non-existent 'action: hold'.")
            penalty += 1
        if block != orig_block:
            return f"```yaml\n{block.strip()}\n```"
        return match.group(0)

    if "```yaml" in upgraded and not explanatory:
        upgraded = re.sub(r"```yaml\s*(.*?)```", _upgrade_yaml_block, upgraded, flags=re.DOTALL)

    # 2. Check for hallucinated entity_ids inside YAML blocks against hass.states and strip invalid YAML blocks
    # Skip for explanatory queries so illustrative syntax examples (e.g. light.living_room) are preserved.
    if not explanatory and hass is not None and hasattr(hass, "states") and hasattr(hass.states, "async_entity_ids"):
        try:
            raw_ids = hass.states.async_entity_ids()
            existing_eids = {str(e).lower() for e in raw_ids} if isinstance(raw_ids, (list, tuple, set)) else set()
            if existing_eids and "```yaml" in upgraded:
                entity_domains = (
                    "light",
                    "switch",
                    "climate",
                    "media_player",
                    "lock",
                    "cover",
                    "binary_sensor",
                    "sensor",
                    "alarm_control_panel",
                    "camera",
                    "fan",
                    "vacuum",
                    "siren",
                    "person",
                    "input_boolean",
                )
                hallucinated_in_yaml: list[str] = []
                reg_entities: dict[str, Any] = {}
                try:
                    ent_reg = er.async_get(hass)
                    raw_reg = getattr(ent_reg, "entities", None)
                    if isinstance(raw_reg, dict):
                        reg_entities = {str(k).lower(): v for k, v in raw_reg.items()}
                except Exception:
                    reg_entities = {}

                def _is_hidden(eid: str) -> bool:
                    entry = reg_entities.get(eid)
                    return bool(entry is not None and getattr(entry, "hidden_by", None) is not None)

                def _is_disabled(eid: str) -> bool:
                    entry = reg_entities.get(eid)
                    return bool(entry is not None and getattr(entry, "disabled_by", None) is not None)

                def _filter_hallucinated_yaml(match: re.Match) -> str:
                    nonlocal penalty
                    yb = match.group(1)
                    block_missing: list[str] = []
                    block_disabled: list[str] = []
                    block_hidden_only: list[str] = []
                    domain_corrections: list[tuple[str, str]] = []
                    service_suffixes = {
                        "turn_on",
                        "turn_off",
                        "toggle",
                        "set_percentage",
                        "increase_speed",
                        "decrease_speed",
                        "oscillate",
                        "set_preset_mode",
                        "set_direction",
                        "set_temperature",
                        "set_hvac_mode",
                        "set_fan_mode",
                        "set_swing_mode",
                        "set_position",
                        "set_tilt_position",
                        "select_source",
                        "select_option",
                        "volume_set",
                        "media_play",
                        "media_pause",
                        "media_stop",
                        "play_media",
                        "lock",
                        "unlock",
                        "open_cover",
                        "close_cover",
                        "stop_cover",
                        "arm_away",
                        "arm_home",
                        "arm_night",
                        "disarm",
                        "speak",
                        "create",
                        "reload",
                        "press",
                        "set_value",
                        "send_message",
                        "trigger",
                        "sun",
                        "state",
                    }
                    # Build lookup of object_id -> matching active entity_ids for unambiguous domain auto-correction
                    obj_id_matches: dict[str, list[str]] = {}
                    for eid in existing_eids:
                        if "." in eid:
                            e_dom, e_obj = eid.split(".", 1)
                            if e_dom in entity_domains and not _is_disabled(eid):
                                obj_id_matches.setdefault(e_obj, []).append(eid)

                    _, room_entities_by_domain = _extract_verified_room_entities(target_room_context)

                    def _resolve_room_entity(cand_dom: str, cand_obj: str) -> str | None:
                        if not room_entities_by_domain:
                            return None
                        if any(cand_obj.startswith(p) or p in cand_obj for p in ("some_", "example_", "your_", "placeholder", "dummy")):
                            return None
                        room_cands = [
                            e for e in room_entities_by_domain.get(cand_dom, [])
                            if e in existing_eids and not _is_disabled(e)
                        ]
                        if not room_cands:
                            return None
                        cand_tokens = {t for t in cand_obj.split("_") if len(t) > 1}
                        occ_tokens = {"occupancy", "occupied", "motion", "presence", "person"}
                        is_occ_cand = bool(cand_tokens & occ_tokens)
                        if len(room_cands) == 1:
                            only = room_cands[0]
                            if cand_dom == "binary_sensor" and is_occ_cand and not any(k in only for k in occ_tokens):
                                return None
                            return only
                        scored: list[tuple[int, int, str]] = []
                        for rc in room_cands:
                            rc_obj = rc.split(".", 1)[1]
                            rc_tokens = {t for t in rc_obj.split("_") if len(t) > 1}
                            overlap = len(cand_tokens & rc_tokens)
                            if is_occ_cand and any(k in rc_obj for k in occ_tokens):
                                overlap += 2
                            if overlap > 0:
                                vis_bonus = 1 if not _is_hidden(rc) else 0
                                scored.append((overlap, vis_bonus, rc))
                        if not scored:
                            return None
                        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
                        return scored[0][2]

                    for m in re.finditer(r"\b([a-z_]+\.[a-z0-9_]+)\b", yb, re.IGNORECASE):
                        cand_eid = m.group(1).lower()
                        dom, obj_id = cand_eid.split(".", 1)
                        # Skip service calls (explicitly following action:/service: or known service suffixes)
                        line_prefix = yb[: m.start()].splitlines()[-1] if yb[: m.start()] else ""
                        if obj_id in service_suffixes or re.search(r"\b(?:action|service)\s*:\s*$", line_prefix):
                            continue
                        if dom not in entity_domains:
                            continue

                        alt_all = [e for e in obj_id_matches.get(obj_id, []) if e != cand_eid]
                        alt_visible = [e for e in alt_all if not _is_hidden(e)]

                        if cand_eid not in existing_eids:
                            # Prefer visible & enabled alternative, then single active alternative, then room-scoped resolution
                            chosen_alt = (
                                alt_visible[0]
                                if len(alt_visible) == 1
                                else (alt_all[0] if len(alt_all) == 1 and not alt_visible else None)
                            )
                            if not chosen_alt:
                                chosen_alt = _resolve_room_entity(dom, obj_id)
                            if chosen_alt:
                                new_dom = chosen_alt.split(".", 1)[0]
                                yb = re.sub(rf"\b{re.escape(m.group(1))}\b", chosen_alt, yb)
                                domain_corrections.append((dom, new_dom))
                                continue
                            if _is_disabled(cand_eid):
                                if cand_eid not in block_disabled:
                                    block_disabled.append(cand_eid)
                                continue
                            if cand_eid not in block_missing:
                                block_missing.append(cand_eid)
                            if cand_eid not in hallucinated_in_yaml:
                                hallucinated_in_yaml.append(cand_eid)
                        elif _is_hidden(cand_eid):
                            # Entity exists but is hidden: prefer a visible alternative with the same object_id
                            if len(alt_visible) == 1:
                                chosen_alt = alt_visible[0]
                                new_dom = chosen_alt.split(".", 1)[0]
                                yb = re.sub(rf"\b{re.escape(m.group(1))}\b", chosen_alt, yb)
                                domain_corrections.append((dom, new_dom))
                            elif cand_eid not in block_hidden_only:
                                block_hidden_only.append(cand_eid)

                    if domain_corrections and not block_missing and not block_disabled:
                        # Update matching generic service calls (turn_on/turn_off/toggle) if no entity of old_dom remains
                        remaining_domains = {
                            em.group(1).lower().split(".", 1)[0]
                            for em in re.finditer(r"\b([a-z_]+\.[a-z0-9_]+)\b", yb, re.IGNORECASE)
                            if em.group(1).lower().split(".", 1)[1] not in service_suffixes
                        }
                        for old_dom, new_dom in domain_corrections:
                            if old_dom not in remaining_domains:
                                for svc in ("turn_on", "turn_off", "toggle"):
                                    yb = re.sub(rf"\b{re.escape(old_dom)}\.{svc}\b", f"{new_dom}.{svc}", yb)

                    if block_missing or block_disabled:
                        for meid in block_missing:
                            notes.append(
                                f"Entity '{meid}' does not exist on this Home Assistant instance; always verify entity IDs against Active Entities or ask the user for clarification."
                            )
                            penalty += 2
                        for deid in block_disabled:
                            notes.append(
                                f"Entity '{deid}' is currently disabled in Home Assistant with no enabled alternative."
                            )
                            penalty += 1
                        parts: list[str] = []
                        if block_missing:
                            missing_str = ", ".join(f"`{e}`" for e in block_missing)
                            parts.append(
                                f"referenced non-existent entity ID(s): {missing_str}"
                            )
                        if block_disabled:
                            disabled_str = ", ".join(f"`{e}`" for e in block_disabled)
                            parts.append(
                                f"referenced disabled entity ID(s) with no alternative: {disabled_str} (enable them in Home Assistant Settings → Devices & Services → Entities to use them)"
                            )
                        return f"\n*(⚠️ Removed draft YAML block because it {'; and '.join(parts)}.)*\n"

                    # Validate parsed YAML structure for hallucinated HA keys/values
                    invalid_syntax_reasons: list[str] = []
                    top_keys = re.findall(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:", yb, re.MULTILINE)
                    dup_top_keys = [k for k in dict.fromkeys(top_keys) if top_keys.count(k) > 1]
                    if dup_top_keys:
                        invalid_syntax_reasons.append(
                            "duplicate top-level key(s): " + ", ".join(f"`{k}:`" for k in dup_top_keys)
                        )
                    try:
                        parsed_yb = yaml.safe_load(yb)
                    except yaml.YAMLError as yerr:
                        parsed_yb = None
                        err_line = str(yerr).splitlines()[0] if str(yerr) else "malformed YAML"
                        invalid_syntax_reasons.append(f"invalid YAML syntax ({err_line})")
                    except Exception:
                        parsed_yb = None
                    if isinstance(parsed_yb, dict):
                        def _scan_invalid_ha_yaml(node: Any) -> None:
                            if isinstance(node, dict):
                                if "when" in node and ("action" in node or "service" in node or "then" in node or "sequence" in node):
                                    invalid_syntax_reasons.append("unsupported `when:`/`then:` key (use `- choose:` with `conditions:` and `sequence:`)")
                                if "then" in node and "when" not in node:
                                    invalid_syntax_reasons.append("unsupported `then:` key (use `sequence:`)")
                                if "else" in node:
                                    invalid_syntax_reasons.append("unsupported `else:` key inside `choose:` (use `default:`)")
                                if "target_entity_id" in node:
                                    invalid_syntax_reasons.append("unsupported `target_entity_id:` key (use `target:` with `entity_id:`)")
                                if "attribute_or_state" in node:
                                    invalid_syntax_reasons.append("unsupported `attribute_or_state:` key")
                                if "between_range" in node:
                                    invalid_syntax_reasons.append("unsupported `between_range:` key (use `above:` and `below:`)")
                                if "not_equal_to" in node:
                                    invalid_syntax_reasons.append("unsupported `not_equal_to:` key (use `state: \"off\"` or `condition: not`)")
                                if "between" in node and node.get("condition") == "numeric_state":
                                    invalid_syntax_reasons.append("unsupported `between:` key in `numeric_state` (use `above:` and `below:`)")
                                if node.get("condition") == "numeric_state" and "above" not in node and "below" not in node:
                                    invalid_syntax_reasons.append("`condition: numeric_state` is missing `above:` or `below:`")
                                if "sequence" in node and isinstance(node["sequence"], list) and len(node["sequence"]) == 0:
                                    invalid_syntax_reasons.append("empty `sequence: []` inside `choose:` branch")
                                if node.get("condition") == "binary_sensor":
                                    invalid_syntax_reasons.append("unsupported `condition: binary_sensor` (use `condition: state`)")
                                if node.get("condition") == "state":
                                    if "above" in node or "below" in node:
                                        invalid_syntax_reasons.append("`above:`/`below:` used with `condition: state` (use `condition: numeric_state`)")
                                    elif "state" not in node:
                                        invalid_syntax_reasons.append("`condition: state` is missing required `state:` key")
                                if node.get("trigger") == "event" and isinstance(node.get("event_type"), str) and "." in node["event_type"]:
                                    invalid_syntax_reasons.append(f"invalid event trigger `{node['event_type']}` (use `trigger: state` with `entity_id:`)")
                                act_val = node.get("action") or node.get("service")
                                if isinstance(act_val, str) and act_val.startswith("fan."):
                                    for container_key in ("target", "data"):
                                        sub = node.get(container_key)
                                        if isinstance(sub, dict) and "entity_id" in sub:
                                            t_eids = sub["entity_id"] if isinstance(sub["entity_id"], list) else [sub["entity_id"]]
                                            for teid in t_eids:
                                                if isinstance(teid, str) and teid.startswith(("light.", "switch.")):
                                                    invalid_syntax_reasons.append(
                                                        f"`{act_val}` cannot target `{teid}` (use the room's `fan.*` entity)"
                                                    )
                                if "device_id" in node and isinstance(node["device_id"], str):
                                    invalid_syntax_reasons.append(f"unverified `device_id: {node['device_id']}` (use `entity_id:` instead)")
                                if "entity_id" in node:
                                    e_val = node["entity_id"]
                                    e_items = e_val if isinstance(e_val, list) else [e_val]
                                    for item in e_items:
                                        if isinstance(item, str) and "." not in item and not item.startswith(("!", "{{")):
                                            invalid_syntax_reasons.append(f"invalid `entity_id: {item}` (missing domain prefix)")
                                for v in node.values():
                                    _scan_invalid_ha_yaml(v)
                            elif isinstance(node, list):
                                for item in node:
                                    _scan_invalid_ha_yaml(item)

                        _scan_invalid_ha_yaml(parsed_yb)

                    if invalid_syntax_reasons:
                        dedup_reasons = list(dict.fromkeys(invalid_syntax_reasons))
                        for r in dedup_reasons:
                            notes.append(f"Invalid Home Assistant YAML syntax: {r}")
                            penalty += 2
                        return (
                            "\n*(⚠️ Removed draft YAML block because it contained invalid Home Assistant syntax: "
                            + "; ".join(dedup_reasons)
                            + ".)*\n"
                        )

                    rendered = f"```yaml\n{yb.strip()}\n```" if domain_corrections else match.group(0)
                    if block_hidden_only:
                        hidden_str = ", ".join(f"`{e}`" for e in block_hidden_only)
                        rendered += (
                            f"\n\n> ⚠️ **Note:** {hidden_str} is currently **hidden** in Home Assistant "
                            "with no visible alternative. It will still function in automations, or you can unhide it under Settings → Devices & Services → Entities."
                        )
                    return rendered

                upgraded = re.sub(r"```yaml\s*(.*?)```", _filter_hallucinated_yaml, upgraded, flags=re.DOTALL)
        except Exception:
            pass

    # 3. Strip numbered or inline manual automations.yaml / configuration.yaml / UI click-through instructions
    upgraded = re.sub(
        r"(?is)to\s+deploy\s+this\s+automation,\s+you\s+can\s+follow\s+these\s+steps:.*?(?=\n\nWould you like|\Z)",
        "",
        upgraded,
    )
    upgraded = re.sub(
        r"(?is)(?:^|\n)(?:#{1,4}\s*|\*\*)?steps\s+to\s+(?:create|add|set\s+up)\s+the\s+automation:?\*?\*?.*?(?=\n\n(?:Explanation|Would you like)|\Z)",
        "",
        upgraded,
    )
    upgraded = re.sub(
        r"(?im)^.*you can add this configuration to your\s+`?automation`?\s+section in your\s+`?configuration\.yaml`?.*$",
        "",
        upgraded,
    ).strip()

    return upgraded, list(dict.fromkeys(notes)), penalty


class CopilotEngine:
    """Modular, self-optimizing Assist Co-Pilot engine backed by HA .storage."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the CopilotEngine with HA Store instances."""
        self.hass = hass
        self._config_store = Store(hass, COPILOT_CONFIG_STORAGE_VERSION, COPILOT_CONFIG_STORAGE_KEY)
        self._memory_store = Store(hass, COPILOT_MEMORY_STORAGE_VERSION, COPILOT_MEMORY_STORAGE_KEY)
        self._loaded = False
        self._config: dict[str, Any] = {
            "prompt_rules": copy.deepcopy(DEFAULT_PROMPT_RULES),
            "entity_aliases": {},
            "condition_templates": copy.deepcopy(DEFAULT_CONDITION_TEMPLATES),
        }
        self._memory: dict[str, Any] = {
            "learned_facts": [],
            "optimization_history": [],
        }

    async def async_load(self) -> None:
        """Load copilot_config and copilot_memory from .storage."""
        if self._loaded:
            return
        try:
            cfg = await self._config_store.async_load()
            if isinstance(cfg, dict):
                rules = copy.deepcopy(DEFAULT_PROMPT_RULES)
                if isinstance(cfg.get("prompt_rules"), dict):
                    rules.update(cfg["prompt_rules"])
                templates = copy.deepcopy(DEFAULT_CONDITION_TEMPLATES)
                if isinstance(cfg.get("condition_templates"), dict):
                    templates.update(cfg["condition_templates"])
                aliases = dict(cfg.get("entity_aliases") or {})
                self._config = {
                    "prompt_rules": rules,
                    "entity_aliases": aliases,
                    "condition_templates": templates,
                }
        except Exception as err:
            _LOGGER.debug("Could not load copilot_config: %s", err)

        try:
            mem = await self._memory_store.async_load()
            if isinstance(mem, dict):
                self._memory = {
                    "learned_facts": list(mem.get("learned_facts") or [])[-MAX_LEARNED_FACTS:],
                    "optimization_history": list(mem.get("optimization_history") or [])[-MAX_OPTIMIZATION_HISTORY:],
                }
        except Exception as err:
            _LOGGER.debug("Could not load copilot_memory: %s", err)

        self._loaded = True

    async def _async_save_config(self) -> None:
        """Persist copilot_config to .storage."""
        await self._config_store.async_save(self._config)

    async def _async_save_memory(self) -> None:
        """Persist copilot_memory to .storage."""
        self._memory["learned_facts"] = self._memory["learned_facts"][-MAX_LEARNED_FACTS:]
        self._memory["optimization_history"] = self._memory["optimization_history"][-MAX_OPTIMIZATION_HISTORY:]
        await self._memory_store.async_save(self._memory)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _make_fact_id(fact_text: str) -> str:
        digest = hashlib.sha256(fact_text.strip().lower().encode("utf-8")).hexdigest()[:12]
        return f"fact_{digest}"

    def _record_optimization_event(self, action: str, detail: str) -> None:
        self._memory.setdefault("optimization_history", []).append({
            "timestamp": self._now_iso(),
            "action": action,
            "detail": detail,
        })

    # ------------------------------------------------------------------
    # Runtime Self-Optimization Tools
    # ------------------------------------------------------------------

    async def async_tune_prompt_rule(
        self,
        rule_key: str,
        rule_text: str,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Create or update a runtime-tunable prompt rule in copilot_config."""
        await self.async_load()
        clean_key = re.sub(r"[^a-z0-9_]", "_", str(rule_key).strip().lower()).strip("_")
        if not clean_key:
            raise ValueError("rule_key must contain alphanumeric characters")
        clean_text = str(rule_text or "").strip()
        if not clean_text:
            raise ValueError("rule_text cannot be empty")
        entry = {
            "enabled": bool(enabled),
            "text": clean_text,
            "updated_at": self._now_iso(),
        }
        self._config["prompt_rules"][clean_key] = entry
        self._record_optimization_event("tune_prompt_rule", f"{clean_key} (enabled={bool(enabled)})")
        await self._async_save_config()
        await self._async_save_memory()
        return {"rule_key": clean_key, **entry}

    async def async_set_entity_alias(self, alias: str, entity_id: str) -> dict[str, str]:
        """Bind a natural-language alias to a canonical Home Assistant entity_id."""
        await self.async_load()
        clean_alias = str(alias or "").strip().lower()
        clean_eid = str(entity_id or "").strip().lower()
        if not clean_alias or "." not in clean_eid:
            raise ValueError("Both a non-empty alias and a valid entity_id (domain.object_id) are required")
        self._config["entity_aliases"][clean_alias] = clean_eid
        self._record_optimization_event("set_entity_alias", f"'{clean_alias}' -> '{clean_eid}'")
        await self._async_save_config()
        await self._async_save_memory()
        return {"alias": clean_alias, "entity_id": clean_eid}

    async def async_set_condition_template(
        self,
        template_key: str,
        template_dict: dict[str, Any],
    ) -> dict[str, Any]:
        """Store or update a reusable Home Assistant condition template in copilot_config."""
        await self.async_load()
        clean_key = re.sub(r"[^a-z0-9_]", "_", str(template_key).strip().lower()).strip("_")
        if not clean_key or not isinstance(template_dict, dict) or not template_dict:
            raise ValueError("Valid template_key and non-empty template_dict are required")
        self._config["condition_templates"][clean_key] = copy.deepcopy(template_dict)
        self._record_optimization_event("set_condition_template", clean_key)
        await self._async_save_config()
        await self._async_save_memory()
        return {"template_key": clean_key, "template": copy.deepcopy(template_dict)}

    async def async_record_learned_fact(
        self,
        fact: str,
        category: str = "user_correction",
        entities: list[str] | None = None,
        source: str = "user_correction",
    ) -> dict[str, Any]:
        """Persist a verified learned fact in copilot_memory (deduplicated by normalized text)."""
        await self.async_load()
        clean_fact = str(fact or "").strip()
        if not clean_fact:
            raise ValueError("fact cannot be empty")
        if not clean_fact.endswith("."):
            clean_fact += "."
        fact_id = self._make_fact_id(clean_fact)
        now = self._now_iso()
        clean_entities = sorted({str(e).strip().lower() for e in (entities or []) if "." in str(e)})

        for existing in self._memory["learned_facts"]:
            existing_fact = existing.get("fact", "").strip()
            existing_lower = existing_fact.lower()
            new_lower = clean_fact.lower()
            if existing.get("id") == fact_id or existing_lower == new_lower:
                existing["enabled"] = True
                existing["updated_at"] = now
                if clean_entities:
                    existing["entities"] = sorted(set(existing.get("entities") or []) | set(clean_entities))
                await self._async_save_memory()
                return dict(existing)

            same_cat = existing.get("category") == category
            sim = SequenceMatcher(None, existing_lower, new_lower).ratio()
            existing_ents = set(existing.get("entities") or [])
            shared_ents = bool(clean_entities and existing_ents and (existing_ents & set(clean_entities)))
            if (same_cat and sim >= 0.72) or (same_cat and shared_ents and (category == "entity_status" or sim >= 0.5)):
                # Expand / update existing rule instead of creating a near-duplicate
                if len(clean_fact) >= len(existing_fact):
                    existing["fact"] = clean_fact
                elif clean_fact.rstrip(".") not in existing_fact:
                    existing["fact"] = f"{existing_fact.rstrip('.')} ({clean_fact.rstrip('.')})."
                existing["id"] = self._make_fact_id(existing["fact"])
                existing["enabled"] = True
                existing["updated_at"] = now
                if clean_entities:
                    existing["entities"] = sorted(existing_ents | set(clean_entities))
                self._record_optimization_event("update_learned_fact", f"{existing['id']}: {existing['fact'][:80]}")
                await self._async_save_memory()
                return dict(existing)

        record = {
            "id": fact_id,
            "fact": clean_fact,
            "category": category,
            "source": source,
            "entities": clean_entities,
            "enabled": True,
            "created_at": now,
            "updated_at": now,
            "applied_count": 0,
        }
        self._memory["learned_facts"].append(record)
        self._record_optimization_event("record_learned_fact", f"{fact_id}: {clean_fact[:80]}")
        await self._async_save_memory()
        return dict(record)

    async def async_remove_learned_fact(self, fact_id: str) -> bool:
        """Remove a learned fact by ID from copilot_memory."""
        await self.async_load()
        before = len(self._memory["learned_facts"])
        self._memory["learned_facts"] = [
            f for f in self._memory["learned_facts"] if f.get("id") != fact_id
        ]
        if len(self._memory["learned_facts"]) < before:
            self._record_optimization_event("remove_learned_fact", fact_id)
            await self._async_save_memory()
            return True
        return False

    def get_active_learned_facts(self) -> list[dict[str, Any]]:
        """Return all enabled learned facts."""
        return [f for f in self._memory.get("learned_facts", []) if f.get("enabled", True)]

    def get_copilot_state(self) -> dict[str, Any]:
        """Return a snapshot of copilot_config and copilot_memory."""
        return {
            "config": copy.deepcopy(self._config),
            "learned_facts": copy.deepcopy(self._memory.get("learned_facts", [])),
            "optimization_history": copy.deepcopy(self._memory.get("optimization_history", [])[-15:]),
        }

    # ------------------------------------------------------------------
    # User Correction Capture
    # ------------------------------------------------------------------

    async def async_capture_user_correction(
        self,
        user_text: str,
        assistant_text: str = "",
        hass: HomeAssistant | None = None,
    ) -> list[dict[str, Any]]:
        """Detect user corrections (entity status, entity replacement, YAML preferences) and persist as learned facts."""
        await self.async_load()
        u_clean = str(user_text or "").strip()
        if not u_clean or len(u_clean) > 400:
            return []

        captured: list[dict[str, Any]] = []
        u_lower = u_clean.lower()
        mentioned_entities = re.findall(r"\b([a-z_]+\.[a-z0-9_]+)\b", u_lower)

        # 1. Entity enabled/disabled correction
        disabled_match = re.search(
            r"\b([a-z_]+\.[a-z0-9_]+)\b\s+(?:is\s+)?(?:disabled|unavailable|not enabled|turned off in integration)",
            u_lower,
        )
        enabled_match = re.search(
            r"\b([a-z_]+\.[a-z0-9_]+)\b\s+(?:is\s+)?(?:enabled|available|active now)",
            u_lower,
        )
        if disabled_match:
            eid = disabled_match.group(1)
            fact_str = f"Entity `{eid}` is disabled on this Home Assistant instance; do not reference it unless re-enabled"
            captured.append(
                await self.async_record_learned_fact(
                    fact_str,
                    category="entity_status",
                    entities=[eid],
                    source="user_correction",
                )
            )
        elif enabled_match:
            eid = enabled_match.group(1)
            fact_str = f"Entity `{eid}` is enabled and available on this Home Assistant instance"
            captured.append(
                await self.async_record_learned_fact(
                    fact_str,
                    category="entity_status",
                    entities=[eid],
                    source="user_correction",
                )
            )

        # 2. Explicit entity replacement ("use X instead of Y" / "don't use Y, use X")
        instead_match = re.search(
            r"use\s+`?([a-z_]+\.[a-z0-9_]+)`?\s+instead\s+of\s+`?([a-z_]+\.[a-z0-9_]+)`?",
            u_lower,
        )
        if instead_match:
            preferred, avoided = instead_match.group(1), instead_match.group(2)
            fact_str = f"Prefer `{preferred}` instead of `{avoided}` in automations and conditions"
            captured.append(
                await self.async_record_learned_fact(
                    fact_str,
                    category="entity_preference",
                    entities=[preferred, avoided],
                    source="user_correction",
                )
            )

        # 3. YAML / style / general user correction patterns (skip pure follow-up questions like "Why didn't you include a delay?")
        correction_patterns = (
            r"(?:please\s+)?remember\s+(?:that\s+)?(.+)",
            r"(?:actually|correction)[,:]\s+(.+)",
            r"from\s+now\s+on[,:]?\s+(.+)",
            r"(?:always|never|do\s+not|don't)\s+(?:use|include|prefer|put|generate|add|touch)\s+(.+)",
        )
        if not captured:
            for pat in correction_patterns:
                if re.search(pat, u_lower):
                    sentence = u_clean[0].upper() + u_clean[1:]
                    cat = "yaml_preference" if any(
                        kw in u_lower for kw in ("yaml", "trigger", "condition", "action", "mode:", "attribute", "elevation", "entity")
                    ) else "user_correction"
                    captured.append(
                        await self.async_record_learned_fact(
                            sentence,
                            category=cat,
                            entities=mentioned_entities,
                            source="user_correction",
                        )
                    )
                    break

        return captured

    # ------------------------------------------------------------------
    # Condition Parsing & Deterministic Automation Synthesis
    # ------------------------------------------------------------------

    def parse_sun_elevation_condition(self, user_lower: str) -> dict[str, Any] | None:
        """Parse sun/solar elevation condition from user_lower using live HA state and learned facts."""
        elev_match = _SUN_ELEVATION_PATTERN.search(user_lower)
        if not elev_match:
            return None

        op_str = elev_match.group(1).lower()
        elev_val = float(elev_match.group(2))
        elev_val_num: int | float = int(elev_val) if elev_val.is_integer() else elev_val
        bound_key = "below" if op_str in ("below", "under", "less than", "<") else "above"

        # Check learned facts for explicit disablement of sensor.sun_solar_elevation
        solar_sensor_disabled = any(
            "sensor.sun_solar_elevation" in (f.get("entities") or [])
            and "disabled" in str(f.get("fact", "")).lower()
            for f in self.get_active_learned_facts()
        )

        solar_state = (
            self.hass.states.get("sensor.sun_solar_elevation")
            if (not solar_sensor_disabled and hasattr(self.hass, "states"))
            else None
        )
        if solar_state is not None and solar_state.state not in ("unavailable", "unknown"):
            return {
                "condition": "numeric_state",
                "entity_id": "sensor.sun_solar_elevation",
                bound_key: elev_val_num,
            }

        tpl_key = "sun_elevation_below" if bound_key == "below" else "sun_elevation_above"
        base_tpl = copy.deepcopy(self._config.get("condition_templates", {}).get(tpl_key))
        if isinstance(base_tpl, dict) and base_tpl.get("condition"):
            base_tpl.pop("below", None)
            base_tpl.pop("above", None)
            base_tpl[bound_key] = elev_val_num
            return base_tpl

        return {
            "condition": "numeric_state",
            "entity_id": "sun.sun",
            "attribute": "elevation",
            bound_key: elev_val_num,
        }

    def build_occupancy_lighting_automation(
        self,
        room_name: str,
        room_lights: list[str],
        room_occ_sensors: list[str],
        user_lower: str,
    ) -> tuple[dict[str, Any], str]:
        """Synthesize a modern HA occupancy/lighting automation dict and YAML string."""
        wants_after_sunset = any(k in user_lower for k in ("after sunset", "sunset", "night", "dark", "below_horizon"))
        off_mins_match = re.search(r"(\d+)\s*(?:minute|minutes|min|mins)\b", user_lower)
        off_minutes = int(off_mins_match.group(1)) if off_mins_match else None
        sun_elev_cond = self.parse_sun_elevation_condition(user_lower)

        on_trigger: dict[str, Any] = {
            "trigger": "state",
            "entity_id": list(room_occ_sensors) if len(room_occ_sensors) > 1 else room_occ_sensors[0],
            "to": "on",
            "id": "motion_detected",
        }
        triggers_list: list[dict[str, Any]] = [on_trigger]
        if off_minutes is not None:
            triggers_list.append({
                "trigger": "state",
                "entity_id": list(room_occ_sensors) if len(room_occ_sensors) > 1 else room_occ_sensors[0],
                "to": "off",
                "for": {"minutes": off_minutes},
                "id": "motion_cleared",
            })

        conditions_list: list[dict[str, Any]] = []
        if sun_elev_cond is not None and off_minutes is None:
            conditions_list.append(sun_elev_cond)
        if wants_after_sunset and off_minutes is None and sun_elev_cond is None:
            after_sunset_tpl = copy.deepcopy(
                self._config.get("condition_templates", {}).get("after_sunset")
                or {"condition": "sun", "after": "sunset"}
            )
            conditions_list.append(after_sunset_tpl)

        target_lights_val = list(room_lights) if len(room_lights) > 1 else room_lights[0]
        if off_minutes is not None:
            on_conds: list[dict[str, Any]] = [{"condition": "trigger", "id": "motion_detected"}]
            if sun_elev_cond is not None:
                on_conds.append(sun_elev_cond)
            elif wants_after_sunset:
                on_conds.append(
                    copy.deepcopy(
                        self._config.get("condition_templates", {}).get("after_sunset")
                        or {"condition": "sun", "after": "sunset"}
                    )
                )
            actions_list: list[dict[str, Any]] = [
                {
                    "choose": [
                        {
                            "conditions": on_conds,
                            "sequence": [
                                {
                                    "action": "light.turn_on",
                                    "target": {"entity_id": list(room_lights) if len(room_lights) > 1 else room_lights[0]},
                                }
                            ],
                        },
                        {
                            "conditions": [{"condition": "trigger", "id": "motion_cleared"}],
                            "sequence": [
                                {
                                    "action": "light.turn_off",
                                    "target": {"entity_id": list(room_lights) if len(room_lights) > 1 else room_lights[0]},
                                }
                            ],
                        },
                    ]
                }
            ]
        else:
            actions_list = [
                {
                    "action": "light.turn_on",
                    "target": {"entity_id": target_lights_val},
                }
            ]

        alias_suffix = ""
        if sun_elev_cond is not None:
            b_lbl = "Below" if "below" in sun_elev_cond else "Above"
            b_num = sun_elev_cond.get("below", sun_elev_cond.get("above"))
            alias_suffix = f" (Sun Elevation {b_lbl} {b_num}°)"
        elif wants_after_sunset:
            alias_suffix = " After Sunset"
        alias_str = f"{room_name}: Motion & Occupancy Lighting{alias_suffix}"
        desc_parts = [
            f"Turns on {room_name} light ({', '.join(room_lights)}) when motion or person occupancy "
            f"({', '.join(room_occ_sensors)}) is detected"
        ]
        if sun_elev_cond is not None:
            b_lbl = "below" if "below" in sun_elev_cond else "above"
            b_num = sun_elev_cond.get("below", sun_elev_cond.get("above"))
            desc_parts.append(f"and sun elevation ({sun_elev_cond['entity_id']}) is {b_lbl} {b_num}°")
        elif wants_after_sunset:
            desc_parts.append("after sunset")
        if off_minutes is not None:
            desc_parts.append(f"and turns it off after {off_minutes} minutes of no motion")
        desc_str = " ".join(desc_parts) + "."

        auto_yaml_dict: dict[str, Any] = {
            "alias": alias_str,
            "description": desc_str,
            "triggers": triggers_list,
            "conditions": conditions_list,
            "actions": actions_list,
            "mode": "restart",
        }
        dumped_yaml = yaml.dump(auto_yaml_dict, Dumper=_NoAliasSafeDumper, sort_keys=False).strip()
        return auto_yaml_dict, dumped_yaml

    def build_occupancy_media_automation(
        self,
        room_name: str,
        room_tvs: list[str],
        room_occ_sensors: list[str],
        user_lower: str,
    ) -> tuple[dict[str, Any], str]:
        """Synthesize a modern HA occupancy-to-TV/media automation dict and YAML string."""
        sun_elev_cond = self.parse_sun_elevation_condition(user_lower)
        wants_after_sunset = any(k in user_lower for k in ("after sunset", "sunset", "night", "dark", "below_horizon"))
        delay_match = re.search(r"(\d+)\s*(?:minute|minutes|min|mins)\b", user_lower)
        delay_minutes = int(delay_match.group(1)) if delay_match else None

        trigger_entities = list(room_occ_sensors) if len(room_occ_sensors) > 1 else room_occ_sensors[0]
        target_tv = room_tvs[0]

        trigger_dict: dict[str, Any] = {
            "trigger": "state",
            "entity_id": trigger_entities,
            "to": "on",
        }
        if delay_minutes is not None:
            trigger_dict["for"] = {"minutes": delay_minutes}

        conditions_list: list[dict[str, Any]] = []
        if sun_elev_cond is not None:
            conditions_list.append(sun_elev_cond)
        elif wants_after_sunset:
            conditions_list.append(
                copy.deepcopy(
                    self._config.get("condition_templates", {}).get("after_sunset")
                    or {"condition": "sun", "after": "sunset"}
                )
            )

        prefers_restart = any(
            "mode: restart" in str(f.get("fact", "")).lower()
            for f in self.get_active_learned_facts()
        )
        mode_val = "restart" if prefers_restart else "single"

        alias_suffix = f" ({delay_minutes}m Delay)" if delay_minutes is not None else ""
        alias_str = f"{room_name}: Turn On TV When Occupied{alias_suffix}"
        desc_str = (
            f"Turns on {room_name} TV ({target_tv}) when occupancy "
            f"({', '.join(room_occ_sensors)}) is detected"
            + (f" for {delay_minutes} minute(s)." if delay_minutes is not None else ".")
        )
        auto_yaml_dict: dict[str, Any] = {
            "alias": alias_str,
            "description": desc_str,
            "triggers": [trigger_dict],
            "conditions": conditions_list,
            "actions": [
                {
                    "action": "media_player.turn_on",
                    "target": {"entity_id": target_tv},
                }
            ],
            "mode": mode_val,
        }
        dumped_yaml = yaml.dump(auto_yaml_dict, Dumper=_NoAliasSafeDumper, sort_keys=False).strip()
        return auto_yaml_dict, dumped_yaml

    # ------------------------------------------------------------------
    # Prompt Grounding & Learned Fact Injection
    # ------------------------------------------------------------------

    def get_learned_facts_prompt_snippet(self) -> tuple[int, str]:
        """Return (applied_count, prompt_snippet) for active learned facts and runtime aliases."""
        active_facts = self.get_active_learned_facts()
        aliases = self._config.get("entity_aliases") or {}
        lines: list[str] = []

        if active_facts:
            lines.append("VERIFIED LEARNED FACTS & USER CORRECTIONS (MUST OBEY):")
            for fact in active_facts[-15:]:
                lines.append(f"- {fact['fact']}")

        if aliases:
            lines.append("VERIFIED ENTITY ALIASES:")
            for alias, eid in list(aliases.items())[:20]:
                lines.append(f'- "{alias}" -> `{eid}`')

        applied_count = len(active_facts) + len(aliases)
        return applied_count, "\n".join(lines)

    def filter_entities_with_learned_facts(self, entities: list[str]) -> list[str]:
        """Exclude banned/disabled entities and prioritize preferred entities from learned facts."""
        if not entities:
            return entities
        active_facts = self.get_active_learned_facts()
        banned: set[str] = set()
        preferred: list[str] = []
        for fact in active_facts:
            f_low = str(fact.get("fact", "")).lower()
            f_ents = [str(e).lower() for e in (fact.get("entities") or [])]
            if any(k in f_low for k in ("never use", "do not use", "don't use", "is disabled")):
                for e in f_ents:
                    if f"never use {e}" in f_low or f"never use `{e}`" in f_low or f"do not use {e}" in f_low or f"{e}` is disabled" in f_low or f"{e} is disabled" in f_low:
                        banned.add(e)
            if "prefer" in f_low:
                for e in f_ents:
                    if f"prefer {e}" in f_low or f"prefer `{e}`" in f_low:
                        preferred.append(e)
        filtered = [e for e in entities if e.lower() not in banned]
        if not filtered:
            filtered = list(entities)
        if preferred:
            pref_set = set(preferred)
            filtered = [e for e in filtered if e.lower() in pref_set] + [e for e in filtered if e.lower() not in pref_set]
        return filtered

    def get_dynamic_prompt_rules_snippet(self) -> str:
        """Render enabled runtime-tunable prompt rules from copilot_config."""
        rules = self._config.get("prompt_rules") or {}
        lines: list[str] = []
        for rule_cfg in rules.values():
            if isinstance(rule_cfg, dict) and rule_cfg.get("enabled", True) and rule_cfg.get("text"):
                lines.append(f"- {rule_cfg['text']}")
        return "\n".join(lines)

    def build_prompts(
        self,
        *,
        ha_version: str,
        user_text: str,
        rules_snippet: str,
        history_snippet: str,
        matched_yaml_context: str,
        compact_matched_yaml_context: str,
        rag_context: str,
        maturity_summary: str,
        notable_integrations: Any,
        spatial_summary: str,
        climate_summary: str,
        vision_presence_summary: str,
        media_summary: str,
        security_summary: str,
        energy_summary: str,
        area_breakdown_summary: str,
        entity_summary: str,
        detailed_entities: list[Any],
        existing_automations: list[Any],
        existing_scripts: list[Any],
        orphan_summary: str,
        suggestions_summary: str,
        backup_summary: str,
        target_room_context: str = "",
        ha_syntax_reference: str = "",
    ) -> tuple[str, str, int]:
        """Build the full and compact system prompts with runtime rules and learned facts injected."""
        applied_count, learned_snippet = self.get_learned_facts_prompt_snippet()
        dynamic_rules_block = self.get_dynamic_prompt_rules_snippet()
        learned_block = f"\n{learned_snippet}\n" if learned_snippet else ""
        syntax_ref_block = f"\n{ha_syntax_reference.strip()}\n" if ha_syntax_reference and ha_syntax_reference.strip() else ""
        u_low = str(user_text or "").strip().lower()
        is_question_only = (
            "?" in u_low
            and not any(k in u_low for k in ("create ", "build ", "write ", "generate ", "make an automation", "set up "))
        )
        question_directive = (
            "\nQUESTION MODE: The user is asking a question or follow-up clarification. "
            "Answer their question directly and concisely in plain text. "
            "Do NOT re-output unrelated automation YAML blocks from earlier conversation turns unless they asked for updated YAML.\n"
            if is_question_only
            else ""
        )

        prompt = f"""You are the Otis AI Companion, an intelligent, proactive smart home architect, co-pilot, and butler running on Home Assistant {ha_version}.
Your goal is to guide the user from a bare Home Assistant installation to a fully optimized, cohesive, automated smart home—and offer to build and configure everything for them.
Always prioritize native Home Assistant solutions, minimize frontend dependencies, and synthesize right-sized, modular coordinator automations and scripts.

ANTI-HALLUCINATION, ASK-BEFORE-GUESSING & MODERN HA ({ha_version}) PROTOCOL:
- ZERO HALLUCINATION POLICY: Everything you produce MUST be 100% accurate, relevant to this local system, non-deprecated, and up-to-date with Home Assistant {ha_version}. NEVER invent, guess, or hallucinate entity IDs, room names, integrations, services, or attributes that do not exist in the capability map below.
- ASK WHEN UNSURE OR AMBIGUOUS: If the user's request is ambiguous, missing a target room or device, or if you need more information to be 100% sure, STOP and ASK the user a concise clarifying question before generating YAML or executing actions!
- MODERN HA {ha_version} YAML SYNTAX: Always use modern Home Assistant syntax in automations and scripts:
  * Use plural top-level keys `triggers:`, `conditions:`, `actions:`.
  * Inside `triggers:`, use `trigger: state` / `trigger: time` (NEVER deprecated `platform:`).
  * Inside `actions:`, use `action: domain.service` with `target:` and `data:` (NEVER deprecated `service:`).

CONVERSATION DISCIPLINE & FOCUS:
- Stay strictly focused on the user's active goal, topic, and immediate thread.
- If the user is discussing a specific domain (such as Media, Climate, Lighting, or Security), DO NOT switch to unrelated topics.
- Follow up directly on what was discussed in the Recent Conversation History.
- If real automations or scripts are cross-referenced below, inspect their exact triggers, conditions, and actions rather than guessing or hallucinating their logic!

HOME ASSISTANT ARCHITECTURAL GROUNDING:
- Voice Satellites & Assist: Hardware voice satellites (e.g., ESP32-S3 Box, Atom Echo, Wyoming Satellite) connect via the native ESPHome or Wyoming Protocol integrations. Home Assistant DOES NOT have an integration named "Assist Satellite". Pipelines (Wake word, STT, LLM, TTS) are configured in Settings → Voice Assistants. Hardware satellites provide entities in the assist_satellite domain (e.g., assist_satellite.<area>_assistant).
- Command-Line & Package Installation Prohibition: NEVER instruct the user to run Linux/shell terminal commands such as `cd /config`, `git pull`, `pip install`, `apt-get`, `sudo`, or `homeassistant --now-cli`. Modern Home Assistant runs in a managed OS or container environment.
- No Nonexistent YAML Sections: NEVER invent fictional YAML keys such as `voice:`, `speech:`, or `satellite:` in `configuration.yaml`. Voice outputs use `tts.speak` services, and satellites are configured via ESPHome/Wyoming in the UI.
- Polling Anti-Pattern Prohibition: NEVER create or recommend automations with trigger: time_pattern (e.g. minutes: "/5") to check volume or quiet hours! Always use discrete trigger: time triggers (e.g., at: "22:00:00" and at: "08:00:00") or entity state triggers to protect the Home Assistant asyncio event loop.
- Clean System Configuration: NEVER tell the user to create README.md notes, markdown files, or arbitrary files in /config or `/scripts/*.yaml`.
{dynamic_rules_block}

{rules_snippet}
{learned_block}{question_directive}
{history_snippet}{matched_yaml_context}{rag_context}Here is the current capability and architecture map of the home:
- Home Assistant Local Version: {ha_version}
- System Maturity: {maturity_summary}
- Key Integrations: {notable_integrations}
- Spatial Adjacency (Connected Rooms): {spatial_summary}
- Discovered Climate & HVAC Architecture:
{climate_summary}
- Discovered Multi-Modal Vision, Presence & Perimeter:
{vision_presence_summary}
- Discovered Media & Matrix Audio Architecture: {media_summary}
- Discovered Security & Sleep Architecture: {security_summary}
- Discovered Energy & Load Topology: {energy_summary}
- Complete Area & Room Breakdown (Rooms, Adjacencies, Climate & Devices):
{area_breakdown_summary}
- Active Entities: {entity_summary}
- Detailed Control Entities (Actionable): {detailed_entities[:30]}
- Existing Automations: {existing_automations[:15]}
- Existing Scripts: {existing_scripts[:15]}
- Orphaned Entities: {orphan_summary}
- Proactive Recommendations:
{suggestions_summary}

CRITICAL INSTRUCTIONS FOR AUTOMATIONS & SCRIPTS:
1. Autonomous Co-Pilot Deployment & Offer:
   - You are the active, fully integrated smart home co-pilot with autonomous deployment capability. Otis will automatically prompt the user with a 1-click button to deploy and enable any automation, script, or blueprint you propose.
   - NEVER tell the user to manually edit or paste code into `automations.yaml`, `scripts.yaml`, blueprints, or `configuration.yaml`.
   - NEVER tell the user to "do it yourself", "open automations.yaml", "add this to your configuration", or "restart Home Assistant manually".
   - NEVER say "I cannot deploy automations" or claim you lack deployment capabilities. You CAN and DO deploy them via Otis's built-in deployment engine!
   - ALWAYS state that you have drafted the configuration and offer to deploy and enable it immediately for them.

2. GUI-Compatible Automation Format (Visual Automation Editor Ready):
   - Provide all automations strictly in modern Home Assistant {ha_version} GUI YAML format (clean standalone dictionary):
     * Start directly with `alias: "Descriptive Name"` and `description: "Clear explanation"`.
     * Use modern Home Assistant keys: `triggers:`, `conditions:`, `actions:`, and `mode:`.
     * Inside `triggers:`, use `- trigger: state` (never `platform:`). Inside `actions:`, use `- action: domain.service` (never `service:`).
     * DO NOT prefix the block with a list dash (`- id:` or `- alias:`).
     * DO NOT manually define an `id:` field. Otis automatically provisions unique persistent IDs and registers the automation with Home Assistant so it is 100% editable in the GUI Automation Editor (Settings → Automations & Scenes)!
     * Always enclose the automation in its own clean ```yaml ... ``` code block.

3. Script Format & Multi-Item Orchestration:
   - When creating or recommending scripts, provide each script in its own clean ```yaml ... ``` block starting with `alias: "Descriptive Name"`, `sequence:`, `mode:`, etc.
   - If an automation needs to call the script, provide both the script block AND the calling automation block in separate clean ```yaml blocks so Otis can deploy both together.

4. Reason deeply over the home's hardware topology:
   - When a Multi-Zone Matrix Amplifier is present, audio is played on an upstream input streamer and routed to output room zones via `media_player.select_source` + `media_player.volume_set`.
   - When designing security automations, coordinate discovered `alarm_control_panel`, `lock.*`, `cover.*` garage doors, `siren.*`, and presence/occupancy sensors.
   - Query smart lock integrations and available lock code services dynamically based on discovered device capabilities.

5. Complete Spatial, Floor Level & Climate Grounding:
   - Check "Complete Area & Room Breakdown", "Discovered Climate & HVAC Architecture", and "Spatial Adjacency".
   - Always accurately identify room locations, floor levels, adjacent rooms, and corresponding zone thermostats strictly from discovered entities without hallucination.
   - NEVER recommend creating or referencing non-existent room thermostats; strictly adhere to discovered thermostat entity IDs.
   - When analyzing guest or whole-home occupancy modes, cross-reference discovered security lock codes, bedtime schedules, and climate setpoint automations.

6. Blueprint Automation Architecture & Direct Editing Rules:
   - When an automation uses blueprints (`use_blueprint:` with a blueprint path):
     * The automation's logic (triggers, conditions, sequences) lives in the blueprint file (`/config/blueprints/automation/<path>`), NOT in `automations.yaml`!
     * In `automations.yaml`, ONLY the blueprint input parameters (`input:`) can be configured.
     * NEVER inject top-level `triggers:`, `conditions:`, or `actions:` directly into a blueprint automation entry in `automations.yaml`—Home Assistant will reject it and fail setup.
     * When analyzing, fixing, or updating a blueprint, output the corrected blueprint YAML (starting with `blueprint:`) and specify the blueprint subpath for the user to apply! Never claim you cannot edit blueprints, and never force unlinking into standalone automations unless the user explicitly requests to unlink it!

7. Concise, Actionable Responses:
   - Keep conversational commentary brief. If any detail is uncertain, ask the user first; otherwise present the GUI-ready YAML block cleanly for the user to copy and apply in Home Assistant.
{syntax_ref_block}{target_room_context}
User: {user_text}
"""

        compact_system_state = (
            f"{backup_summary}- Notable Integrations: {notable_integrations[:12]}\n"
            f"- Spatial Adjacency: {spatial_summary}\n"
            f"- Climate Architecture:\n{climate_summary}\n"
            if target_room_context
            else (
                f"{backup_summary}- Notable Integrations: {notable_integrations[:15]}\n"
                f"- Spatial Adjacency: {spatial_summary}\n"
                f"- Climate Architecture:\n{climate_summary}\n"
                f"- Room Breakdown:\n{area_breakdown_summary}\n"
                f"- Active Entities: {entity_summary}\n"
                f"- Actionable Control Devices: {detailed_entities[:20]}\n"
            )
        )

        compact_prompt = f"""You are Otis AI, the smart home co-pilot and butler on Home Assistant {ha_version}.
Respond concisely and actionably to the user. Ask a clarifying question if any detail is ambiguous.
ZERO HALLUCINATION RULE: Only use exact entity_ids and rooms listed in System State or VERIFIED ENTITIES IN TARGET ROOM below.
Voice satellites use ESPHome or Wyoming under Settings → Voice Assistants.
Provide automations as a single clean Home Assistant {ha_version} GUI YAML dict starting with alias:, description:, triggers:, conditions:, actions:, mode: (using trigger: state / trigger: numeric_state and action: domain.service, without leading dashes or id:).
For fans, use the room's fan.* entity with action: fan.set_percentage (data: percentage: 33 for low, 66 for medium, 100 for high) and action: fan.turn_off.
For conditional branches in actions:, use - choose: with conditions: (condition: state, or condition: numeric_state with above:/below:) and sequence:, for example:
actions:
  - choose:
      - conditions:
          - condition: state
            entity_id: <verified_occupancy_entity>
            state: "on"
          - condition: numeric_state
            entity_id: <verified_temp_entity>
            above: 70
        sequence:
          - action: fan.set_percentage
            target:
              entity_id: <verified_fan_entity>
            data:
              percentage: 33
When recovering scripts or automations from backups, output the full recovered YAML configuration directly for co-pilot review.
{dynamic_rules_block}
{rules_snippet}
{learned_block}{question_directive}{syntax_ref_block}
System State:
{compact_system_state}
{history_snippet}{compact_matched_yaml_context}{target_room_context}User Request: {user_text}"""

        is_automation_authoring = any(
            k in u_low for k in ("create an automation", "create automation", "write an automation", "automation for", "automate ")
        )
        if target_room_context and is_automation_authoring:
            focused_prompt = f"""You are Otis AI, the smart home co-pilot on Home Assistant {ha_version}.
Create the requested automation using ONLY exact entity_ids from VERIFIED ENTITIES IN TARGET ROOM below.
{learned_block}{syntax_ref_block}
Output ONE ```json automation specification block (Otis compiles it deterministically into modern Home Assistant {ha_version} YAML) followed by a 1-sentence summary.
JSON schema:
{{
  "alias": "Descriptive Name",
  "description": "What it does",
  "mode": "restart",
  "triggers": [
    {{"type": "state", "entity_id": "<occupancy_or_trigger_entity>"}},
    {{"type": "numeric_state", "entity_id": "<temp_entity>", "above": 70}}
  ],
  "conditions": [],
  "branches": [
    {{
      "conditions": [
        {{"type": "state", "entity_id": "<occupancy_entity>", "state": "on"}},
        {{"type": "numeric_state", "entity_id": "<temp_entity>", "above": 72}}
      ],
      "actions": [
        {{"action": "fan.set_percentage", "entity_id": "<fan_entity>", "data": {{"percentage": 66}}}}
      ]
    }}
  ],
  "default": [
    {{"action": "fan.turn_off", "entity_id": "<fan_entity>"}}
  ]
}}
Rules:
- For fans, always use the room's `fan.*` entity (low=33, medium=66, high=100, off=`fan.turn_off`).
- Put higher temperature thresholds (e.g. above 72) BEFORE lower thresholds (e.g. above 70) in `branches` so `choose` matches the highest threshold first.
- Include triggers for every state/threshold that can start or stop the automation (occupancy changes AND temperature thresholds), and put off-conditions (unoccupied or below threshold) cleanly in `branches` or `default`.
{history_snippet}{target_room_context}User Request: {user_text}"""
            return focused_prompt, focused_prompt, applied_count

        return prompt, compact_prompt, applied_count
