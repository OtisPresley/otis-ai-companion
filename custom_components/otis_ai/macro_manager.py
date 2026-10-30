"""Otis Dynamic Macro Orchestrator & Multi-Step Assist Pipelines.

Provides atomic multi-step sequence execution, pre-flight safety checks,
automatic prior state snapshotting, and 1-click state rollback.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

CRITICAL_SERVICES = {
    "lock.unlock",
    "alarm_control_panel.alarm_disarm",
    "cover.open_cover",
}

SAFE_DOMAINS = {
    "light",
    "media_player",
    "climate",
    "switch",
    "cover",
    "lock",
    "fan",
    "scene",
    "script",
    "alarm_control_panel",
}


class MacroManager:
    """Orchestrates multi-step smart home macros with atomic snapshots and rollback."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the macro manager."""
        self.hass = hass
        self._history: list[dict[str, Any]] = []
        self._pending_macros: dict[str, dict[str, Any]] = {}

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the execution history of macros."""
        return self._history[-limit:]

    def get_pending_macro(self, macro_id: str) -> dict[str, Any] | None:
        """Retrieve a pending macro waiting for confirmation."""
        return self._pending_macros.get(macro_id)

    def cancel_pending_macro(self, macro_id: str) -> bool:
        """Cancel a pending macro."""
        if macro_id in self._pending_macros:
            del self._pending_macros[macro_id]
            return True
        return False

    def inspect_safety(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        """Perform pre-flight safety check on proposed macro steps."""
        critical_steps: list[dict[str, Any]] = []
        warnings: list[str] = []

        for idx, step in enumerate(steps, start=1):
            domain = step.get("domain", "")
            service = step.get("service", "")
            full_call = f"{domain}.{service}".lower()
            label = step.get("name") or step.get("label") or f"{full_call} step {idx}"

            if full_call in CRITICAL_SERVICES:
                critical_steps.append({"step_index": idx, "label": label, "call": full_call})
                if full_call == "lock.unlock":
                    warnings.append(f"⚠️ Step {idx} unlocks physical entry deadbolt(s).")
                elif full_call == "alarm_control_panel.alarm_disarm":
                    warnings.append(f"⚠️ Step {idx} disarms the security alarm system.")
                elif full_call == "cover.open_cover":
                    warnings.append(f"⚠️ Step {idx} opens exterior barrier/garage covers.")

        requires_confirmation = len(critical_steps) > 0
        return {
            "requires_confirmation": requires_confirmation,
            "critical_steps": critical_steps,
            "safety_warnings": warnings,
        }

    def _extract_target_entities(self, step: dict[str, Any]) -> list[str]:
        """Extract entity_ids targeted by a step."""
        entities: list[str] = []
        target = step.get("target") or {}
        if isinstance(target, dict):
            target_eid = target.get("entity_id")
            if isinstance(target_eid, list):
                entities.extend(target_eid)
            elif isinstance(target_eid, str):
                entities.append(target_eid)

        step_eid = step.get("entity_id")
        if isinstance(step_eid, list):
            entities.extend(step_eid)
        elif isinstance(step_eid, str) and step_eid not in entities:
            entities.append(step_eid)

        data = step.get("data") or {}
        if isinstance(data, dict) and "entity_id" in data:
            d_eid = data["entity_id"]
            if isinstance(d_eid, list):
                for e in d_eid:
                    if e not in entities:
                        entities.append(e)
            elif isinstance(d_eid, str) and d_eid not in entities:
                entities.append(d_eid)

        return entities

    def _capture_snapshot(self, steps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Capture atomic snapshot of entity states before macro execution."""
        snapshot: dict[str, dict[str, Any]] = {}
        for step in steps:
            target_entities = self._extract_target_entities(step)
            for eid in target_entities:
                if eid in snapshot:
                    continue
                state_obj = self.hass.states.get(eid)
                if state_obj:
                    snapshot[eid] = {
                        "state": state_obj.state,
                        "attributes": dict(state_obj.attributes),
                    }
        return snapshot

    def _normalize_step(self, step: dict[str, Any], index: int) -> dict[str, Any]:
        """Normalize flexible step representations into canonical format."""
        domain = step.get("domain", "")
        service = step.get("service", "")

        if not domain and "." in service:
            parts = service.split(".", 1)
            domain = parts[0]
            service = parts[1]
        elif not domain and "call" in step and "." in step["call"]:
            parts = step["call"].split(".", 1)
            domain = parts[0]
            service = parts[1]

        target = step.get("target") or {}
        if not target and step.get("entity_id"):
            target = {"entity_id": step["entity_id"]}

        data = step.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        name = step.get("name") or step.get("label")
        if not name:
            eids = self._extract_target_entities({"target": target, "entity_id": step.get("entity_id"), "data": data})
            target_label = ", ".join(eids) if eids else "system"
            name = f"{domain}.{service} ({target_label})"

        return {
            "step_index": index,
            "name": name,
            "domain": domain,
            "service": service,
            "target": target,
            "data": data,
        }

    async def async_execute_macro(
        self,
        macro_name: str,
        steps: list[dict[str, Any]],
        confirmed: bool = False,
        macro_id: str | None = None,
        context: Any = None,
    ) -> dict[str, Any]:
        """Execute a multi-step macro pipeline with atomic snapshotting and safety checks."""
        if not steps:
            return {
                "success": False,
                "error": "No steps provided in macro pipeline.",
            }

        macro_id = macro_id or f"macro_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        normalized_steps = [self._normalize_step(s, i) for i, s in enumerate(steps, start=1)]

        # Pre-flight safety check
        safety = self.inspect_safety(normalized_steps)
        if safety["requires_confirmation"] and not confirmed:
            self._pending_macros[macro_id] = {
                "macro_id": macro_id,
                "name": macro_name,
                "steps": normalized_steps,
                "timestamp": time.time(),
                "safety": safety,
            }
            return {
                "success": False,
                "status": "requires_confirmation",
                "macro_id": macro_id,
                "name": macro_name,
                "steps": normalized_steps,
                "critical_steps": safety["critical_steps"],
                "safety_warnings": safety["safety_warnings"],
                "prompt": (
                    f"⚠️ Macro '{macro_name}' contains {len(safety['critical_steps'])} critical security/access step(s):\n"
                    + "\n".join(f"• {w}" for w in safety["safety_warnings"])
                    + "\n\nConfirm execution by saying 'yes' or 'confirm', or 'cancel'."
                ),
            }

        # Clear from pending if executing
        self._pending_macros.pop(macro_id, None)

        # 1. Capture atomic state snapshot prior to executing
        snapshot = self._capture_snapshot(normalized_steps)
        _LOGGER.debug(
            "Otis Macro Orchestrator: Captured snapshot for %d entities before running '%s'",
            len(snapshot),
            macro_name,
        )

        # 2. Execute steps sequentially
        executed_details: list[dict[str, Any]] = []
        all_success = True

        for step in normalized_steps:
            domain = step["domain"]
            service = step["service"]
            target = step["target"]
            service_data = dict(step.get("data") or {})

            # Merge target into service_data if appropriate for async_call
            call_kwargs: dict[str, Any] = {"domain": domain, "service": service, "blocking": True}
            if context is not None:
                call_kwargs["context"] = context

            merged_data = dict(service_data)
            if target:
                if "entity_id" in target and "entity_id" not in merged_data:
                    merged_data["entity_id"] = target["entity_id"]
                if "area_id" in target and "area_id" not in merged_data:
                    merged_data["area_id"] = target["area_id"]
                if "device_id" in target and "device_id" not in merged_data:
                    merged_data["device_id"] = target["device_id"]

            call_kwargs["service_data"] = merged_data

            try:
                await self.hass.services.async_call(**call_kwargs)
                executed_details.append({
                    "step_index": step["step_index"],
                    "name": step["name"],
                    "domain": domain,
                    "service": service,
                    "status": "success",
                })
            except Exception as err:
                _LOGGER.error("Otis Macro error on step '%s': %s", step["name"], err)
                all_success = False
                executed_details.append({
                    "step_index": step["step_index"],
                    "name": step["name"],
                    "domain": domain,
                    "service": service,
                    "status": "failed",
                    "error": str(err),
                })

        record = {
            "macro_id": macro_id,
            "name": macro_name,
            "timestamp": time.time(),
            "steps_total": len(normalized_steps),
            "steps_executed": len([d for d in executed_details if d["status"] == "success"]),
            "snapshot": snapshot,
            "status": "executed" if all_success else "partial_failure",
            "details": executed_details,
        }
        self._history.append(record)

        return {
            "success": all_success,
            "macro_id": macro_id,
            "name": macro_name,
            "steps_executed": record["steps_executed"],
            "steps_total": record["steps_total"],
            "snapshot_entities_count": len(snapshot),
            "details": executed_details,
            "summary": (
                f"✅ Executed macro '{macro_name}' ({record['steps_executed']}/{record['steps_total']} steps succeeded)."
                if all_success
                else f"⚠️ Macro '{macro_name}' partially executed with {len(normalized_steps) - record['steps_executed']} errors."
            ),
        }

    async def async_rollback_macro(self, macro_id: str | None = None) -> dict[str, Any]:
        """Roll back an executed macro by restoring entities to their snapshotted states."""
        if not self._history:
            return {
                "success": False,
                "error": "No executed macros available in history to roll back.",
            }

        target_record: dict[str, Any] | None = None
        if macro_id:
            for rec in reversed(self._history):
                if rec.get("macro_id") == macro_id:
                    target_record = rec
                    break
            if not target_record:
                return {
                    "success": False,
                    "error": f"Macro execution record '{macro_id}' not found.",
                }
        else:
            # Pick latest non-rolled-back macro
            for rec in reversed(self._history):
                if rec.get("status") in ("executed", "partial_failure"):
                    target_record = rec
                    break
            if not target_record:
                target_record = self._history[-1]

        if target_record.get("status") == "rolled_back":
            return {
                "success": False,
                "error": f"Macro '{target_record.get('name')}' has already been rolled back.",
            }

        snapshot = target_record.get("snapshot") or {}
        if not snapshot:
            return {
                "success": False,
                "error": f"No state snapshot found for macro '{target_record.get('name')}'.",
            }

        restored_entities: list[str] = []
        restore_errors: list[dict[str, Any]] = []

        for entity_id, snap in snapshot.items():
            domain = entity_id.split(".", 1)[0]
            prev_state = snap.get("state")
            prev_attrs = snap.get("attributes") or {}

            try:
                if domain == "light":
                    if prev_state == "off":
                        await self.hass.services.async_call("light", "turn_off", {"entity_id": entity_id}, blocking=True)
                    else:
                        svc_data: dict[str, Any] = {"entity_id": entity_id}
                        if "brightness" in prev_attrs and prev_attrs["brightness"] is not None:
                            svc_data["brightness"] = prev_attrs["brightness"]
                        if "color_temp" in prev_attrs and prev_attrs["color_temp"] is not None:
                            svc_data["color_temp"] = prev_attrs["color_temp"]
                        elif "rgb_color" in prev_attrs and prev_attrs["rgb_color"] is not None:
                            svc_data["rgb_color"] = prev_attrs["rgb_color"]
                        await self.hass.services.async_call("light", "turn_on", svc_data, blocking=True)

                elif domain == "climate":
                    if "temperature" in prev_attrs and prev_attrs["temperature"] is not None:
                        await self.hass.services.async_call(
                            "climate",
                            "set_temperature",
                            {"entity_id": entity_id, "temperature": prev_attrs["temperature"]},
                            blocking=True,
                        )
                    if prev_state and prev_state not in ("unavailable", "unknown"):
                        await self.hass.services.async_call(
                            "climate",
                            "set_hvac_mode",
                            {"entity_id": entity_id, "hvac_mode": prev_state},
                            blocking=True,
                        )

                elif domain == "media_player":
                    if prev_state == "off":
                        await self.hass.services.async_call("media_player", "turn_off", {"entity_id": entity_id}, blocking=True)
                    else:
                        if prev_state in ("playing", "paused", "idle", "on"):
                            await self.hass.services.async_call("media_player", "turn_on", {"entity_id": entity_id}, blocking=True)
                            if "source" in prev_attrs and prev_attrs["source"]:
                                await self.hass.services.async_call(
                                    "media_player",
                                    "select_source",
                                    {"entity_id": entity_id, "source": prev_attrs["source"]},
                                    blocking=True,
                                )
                            if "volume_level" in prev_attrs and prev_attrs["volume_level"] is not None:
                                await self.hass.services.async_call(
                                    "media_player",
                                    "volume_set",
                                    {"entity_id": entity_id, "volume_level": prev_attrs["volume_level"]},
                                    blocking=True,
                                )

                elif domain == "cover":
                    curr_pos = prev_attrs.get("current_position")
                    if curr_pos is not None:
                        await self.hass.services.async_call(
                            "cover",
                            "set_cover_position",
                            {"entity_id": entity_id, "position": curr_pos},
                            blocking=True,
                        )
                    elif prev_state == "closed":
                        await self.hass.services.async_call("cover", "close_cover", {"entity_id": entity_id}, blocking=True)
                    elif prev_state == "open":
                        await self.hass.services.async_call("cover", "open_cover", {"entity_id": entity_id}, blocking=True)

                elif domain == "lock":
                    if prev_state == "locked":
                        await self.hass.services.async_call("lock", "lock", {"entity_id": entity_id}, blocking=True)
                    elif prev_state == "unlocked":
                        await self.hass.services.async_call("lock", "unlock", {"entity_id": entity_id}, blocking=True)

                elif domain == "switch":
                    if prev_state == "on":
                        await self.hass.services.async_call("switch", "turn_on", {"entity_id": entity_id}, blocking=True)
                    else:
                        await self.hass.services.async_call("switch", "turn_off", {"entity_id": entity_id}, blocking=True)

                else:
                    # Generic fallback
                    if prev_state == "on":
                        await self.hass.services.async_call("homeassistant", "turn_on", {"entity_id": entity_id}, blocking=True)
                    elif prev_state == "off":
                        await self.hass.services.async_call("homeassistant", "turn_off", {"entity_id": entity_id}, blocking=True)

                restored_entities.append(entity_id)
            except Exception as r_err:
                _LOGGER.error("Error restoring entity %s during rollback: %s", entity_id, r_err)
                restore_errors.append({"entity_id": entity_id, "error": str(r_err)})

        target_record["status"] = "rolled_back"
        target_record["rollback_ts"] = time.time()
        target_record["restored_entities"] = restored_entities

        return {
            "success": len(restore_errors) == 0,
            "macro_id": target_record.get("macro_id"),
            "name": target_record.get("name"),
            "restored_count": len(restored_entities),
            "restored_entities": restored_entities,
            "errors": restore_errors,
            "message": (
                f"↺ Successfully rolled back macro '{target_record.get('name')}' ({len(restored_entities)} entities restored)."
                if len(restore_errors) == 0
                else f"⚠️ Rolled back macro '{target_record.get('name')}' with {len(restore_errors)} errors."
            ),
        }

    def build_smart_macro(
        self,
        template_name: str,
        capability_map: dict[str, Any] | None = None,
        area_name: str | None = None,
    ) -> dict[str, Any]:
        """Synthesize a dynamic multi-step macro tailored to home hardware topology."""
        template_slug = template_name.lower().strip()
        all_states = self.hass.states.async_all() if hasattr(self.hass.states, "async_all") else []

        # Categorize active entities
        lights = [s.entity_id for s in all_states if s.entity_id.startswith("light.") and s.state != "unavailable"]
        climates = [s.entity_id for s in all_states if s.entity_id.startswith("climate.") and s.state != "unavailable"]
        media_players = [s.entity_id for s in all_states if s.entity_id.startswith("media_player.") and s.state != "unavailable"]
        locks = [s.entity_id for s in all_states if s.entity_id.startswith("lock.") and s.state != "unavailable"]
        covers = [s.entity_id for s in all_states if s.entity_id.startswith("cover.") and s.state != "unavailable"]
        alarms = [s.entity_id for s in all_states if s.entity_id.startswith("alarm_control_panel.") and s.state != "unavailable"]

        media_topo = (capability_map or {}).get("media_topology", {})
        tv_cinemas = [p["entity_id"] for p in media_topo.get("tv_cinema_players", []) if "entity_id" in p]
        matrix_zones = [z["entity_id"] for z in media_topo.get("matrix_zones", []) if "entity_id" in z]
        matrix_inputs = [i.get("matched_source") for i in media_topo.get("matrix_input_players", []) if i.get("matched_source")]

        steps: list[dict[str, Any]] = []
        display_name = template_name.replace("_", " ").title()

        if any(w in template_slug for w in ("movie", "cinema", "theater")):
            display_name = "Movie Night Mode"

            # 1. Dim media/living room lights
            target_lights: list[str] = []
            if area_name:
                area_clean = area_name.lower().replace(" ", "_")
                target_lights = [lt for lt in lights if area_clean in lt]
            if not target_lights:
                target_lights = [lt for lt in lights if any(k in lt for k in ("living", "media", "theater", "tv", "cinema", "great_room"))]
            if not target_lights and lights:
                target_lights = lights[:2]

            if target_lights:
                steps.append({
                    "name": f"Dim Lighting in Entertainment Zone ({len(target_lights)} lights to 15%)",
                    "domain": "light",
                    "service": "turn_on",
                    "target": {"entity_id": target_lights},
                    "data": {"brightness_pct": 15},
                })

            # 2. Select TV / HDMI Matrix source
            target_tv = tv_cinemas[0] if tv_cinemas else (
                next((m for m in media_players if any(k in m for k in ("tv", "cinema", "living", "theater"))), None)
            )
            if target_tv:
                source_choice = matrix_inputs[0] if matrix_inputs else "Apple TV"
                steps.append({
                    "name": f"Power On Cinema Display & Select '{source_choice}'",
                    "domain": "media_player",
                    "service": "select_source",
                    "target": {"entity_id": target_tv},
                    "data": {"source": source_choice},
                })

            # 3. Lower comfort climate for viewing
            if climates:
                target_clim = climates[0]
                steps.append({
                    "name": "Adjust Climate Comfort to 68°F",
                    "domain": "climate",
                    "service": "set_temperature",
                    "target": {"entity_id": target_clim},
                    "data": {"temperature": 68},
                })

            # 4. Set AVR / Audio volume
            target_audio = matrix_zones[0] if matrix_zones else (
                next((m for m in media_players if any(k in m for k in ("avr", "receiver", "amp", "soundbar", "great_room"))), None)
            )
            if target_audio:
                steps.append({
                    "name": "Set Soundbar / AVR Volume to 45%",
                    "domain": "media_player",
                    "service": "volume_set",
                    "target": {"entity_id": target_audio},
                    "data": {"volume_level": 0.45},
                })

            # 5. Close shades/blinds in area
            room_covers = [c for c in covers if any(k in c for k in ("living", "media", "theater", "blind", "shade"))]
            if room_covers:
                steps.append({
                    "name": f"Close Window Blinds ({len(room_covers)} covers)",
                    "domain": "cover",
                    "service": "close_cover",
                    "target": {"entity_id": room_covers},
                })

        elif any(w in template_slug for w in ("bedtime", "goodnight", "sleep")):
            display_name = "Goodnight Routine"

            # 1. Turn off common area lights
            common_lights = [lt for lt in lights if not any(k in lt for k in ("bed", "night", "master_bed"))]
            if not common_lights and lights:
                common_lights = lights
            if common_lights:
                steps.append({
                    "name": f"Extinguish Living & Common Lighting ({len(common_lights)} lights)",
                    "domain": "light",
                    "service": "turn_off",
                    "target": {"entity_id": common_lights},
                })

            # 2. Lock perimeter deadbolts
            if locks:
                steps.append({
                    "name": f"Engage Security Deadbolts ({len(locks)} locks)",
                    "domain": "lock",
                    "service": "lock",
                    "target": {"entity_id": locks},
                })

            # 3. Close exterior garage doors
            garage_covers = [c for c in covers if "garage" in c]
            if garage_covers:
                steps.append({
                    "name": f"Close Garage Exterior Doors ({len(garage_covers)} covers)",
                    "domain": "cover",
                    "service": "close_cover",
                    "target": {"entity_id": garage_covers},
                })

            # 4. Set Night Climate
            if climates:
                steps.append({
                    "name": "Set Night Comfort Temperature to 66°F",
                    "domain": "climate",
                    "service": "set_temperature",
                    "target": {"entity_id": climates[0]},
                    "data": {"temperature": 66},
                })

            # 5. Turn off all active media players
            if media_players:
                steps.append({
                    "name": f"Power Down Active Media Zones ({len(media_players)} players)",
                    "domain": "media_player",
                    "service": "turn_off",
                    "target": {"entity_id": media_players},
                })

            # 6. Arm Security Alarm in Home/Night mode
            if alarms:
                steps.append({
                    "name": "Arm Perimeter Alarm (Night Mode)",
                    "domain": "alarm_control_panel",
                    "service": "alarm_arm_home",
                    "target": {"entity_id": alarms[0]},
                })

        elif any(w in template_slug for w in ("party", "entertain", "social")):
            display_name = "Entertain & Party Mode"

            # 1. Turn on multi-zone matrix audio
            target_zones = matrix_zones if matrix_zones else media_players[:3]
            if target_zones:
                streamer = matrix_inputs[0] if matrix_inputs else "Bridge Streamer"
                steps.append({
                    "name": f"Broadcast Matrix Audio across {len(target_zones)} Zones (Source: '{streamer}')",
                    "domain": "media_player",
                    "service": "turn_on",
                    "target": {"entity_id": target_zones},
                })
                steps.append({
                    "name": "Set Multi-Room Ambient Volume to 35%",
                    "domain": "media_player",
                    "service": "volume_set",
                    "target": {"entity_id": target_zones},
                    "data": {"volume_level": 0.35},
                })

            # 2. Warm ambient lighting
            if lights:
                steps.append({
                    "name": f"Set Warm Social Ambience ({len(lights[:4])} lights to 70%)",
                    "domain": "light",
                    "service": "turn_on",
                    "target": {"entity_id": lights[:4]},
                    "data": {"brightness_pct": 70, "color_temp": 370},
                })

        elif any(w in template_slug for w in ("away", "lockdown", "leave")):
            display_name = "Away & Lockdown Mode"

            if lights:
                steps.append({
                    "name": f"Extinguish All Lighting ({len(lights)} lights)",
                    "domain": "light",
                    "service": "turn_off",
                    "target": {"entity_id": lights},
                })

            if locks:
                steps.append({
                    "name": f"Secure All Deadbolts ({len(locks)} locks)",
                    "domain": "lock",
                    "service": "lock",
                    "target": {"entity_id": locks},
                })

            garage_covers = [c for c in covers if "garage" in c]
            if garage_covers:
                steps.append({
                    "name": f"Close Garage Doors ({len(garage_covers)} covers)",
                    "domain": "cover",
                    "service": "close_cover",
                    "target": {"entity_id": garage_covers},
                })

            if media_players:
                steps.append({
                    "name": f"Power Down All Media ({len(media_players)} players)",
                    "domain": "media_player",
                    "service": "turn_off",
                    "target": {"entity_id": media_players},
                })

            if alarms:
                steps.append({
                    "name": "Arm Perimeter Alarm (Away Mode)",
                    "domain": "alarm_control_panel",
                    "service": "alarm_arm_away",
                    "target": {"entity_id": alarms[0]},
                })

        elif any(w in template_slug for w in ("welcome", "arrive", "arrival")):
            display_name = "Welcome Home Arrival"

            # Note: contains unlock/disarm steps which will trigger pre-flight safety check
            entry_lights = [lt for lt in lights if any(k in lt for k in ("entry", "foyer", "porch", "hall", "living"))]
            if not entry_lights and lights:
                entry_lights = lights[:2]
            if entry_lights:
                steps.append({
                    "name": f"Illuminate Entryway & Living Pathway ({len(entry_lights)} lights)",
                    "domain": "light",
                    "service": "turn_on",
                    "target": {"entity_id": entry_lights},
                    "data": {"brightness_pct": 80},
                })

            if climates:
                steps.append({
                    "name": "Restore Comfort Climate to 70°F",
                    "domain": "climate",
                    "service": "set_temperature",
                    "target": {"entity_id": climates[0]},
                    "data": {"temperature": 70},
                })

            front_lock = next((lk for lk in locks if any(k in lk for k in ("front", "entry", "main"))), None)
            if front_lock:
                steps.append({
                    "name": f"Unlock Entry Door ({front_lock})",
                    "domain": "lock",
                    "service": "unlock",
                    "target": {"entity_id": front_lock},
                })

            if alarms:
                steps.append({
                    "name": "Disarm Security Alarm System",
                    "domain": "alarm_control_panel",
                    "service": "alarm_disarm",
                    "target": {"entity_id": alarms[0]},
                })

        return {
            "name": display_name,
            "template": template_slug,
            "steps": steps,
        }
