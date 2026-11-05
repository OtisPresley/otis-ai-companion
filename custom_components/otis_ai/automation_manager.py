"""Automation and script manager for Otis AI Companion."""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import yaml as yaml_util

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY_AUTOMATIONS = "otis_ai_automations"
STORAGE_KEY_SCRIPTS = "otis_ai_scripts"
STORAGE_KEY_BLUEPRINTS = "otis_ai_blueprints"


def _read_blueprint_snippet(full_path: str, max_lines: int = 120) -> str | None:
    """Read snippet of a blueprint file synchronously in executor."""
    if not os.path.exists(full_path):
        return None
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as bpf:
            bp_lines = bpf.read().splitlines()
            bp_snippet = "\n".join(bp_lines[:max_lines])
            if len(bp_lines) > max_lines:
                bp_snippet += "\n# ... [blueprint sequence truncated]"
            return bp_snippet
    except Exception as bpe:
        _LOGGER.debug("Could not read blueprint file %s: %s", full_path, bpe)
        return None


class AutomationManager:
    """Manages reading user automations/scripts and managing integration configurations via .storage."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.automations_path = hass.config.path("automations.yaml")
        self.scripts_path = hass.config.path("scripts.yaml")
        self._auto_store: Store[list[dict[str, Any]]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_AUTOMATIONS
        )
        self._script_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_SCRIPTS
        )
        self._bp_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_BLUEPRINTS
        )

    def _read_yaml_file(self, path: str) -> Any:
        """Read a YAML file from disk (blocking, read-only)."""
        if not os.path.exists(path):
            return [] if "automations" in path else {}
        try:
            res = yaml_util.load_yaml(path)
            if isinstance(res, (list, dict)):
                return res
        except Exception as err:
            _LOGGER.debug("Error loading YAML via yaml_util %s: %s", path, err)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                res = yaml.safe_load(f)
                if isinstance(res, (list, dict)):
                    return res
        except Exception as err:
            _LOGGER.error("Error reading YAML file %s: %s", path, err)
        return [] if "automations" in path else {}

    async def async_read_automations(self) -> list[dict[str, Any]]:
        """Read all automations from automations.yaml and Otis managed store."""
        user_autos = await self.hass.async_add_executor_job(self._read_yaml_file, self.automations_path)
        if not isinstance(user_autos, list):
            user_autos = []
        try:
            stored_autos = await self._auto_store.async_load()
        except Exception as err:
            _LOGGER.debug("Could not load stored automations: %s", err)
            stored_autos = []
        if not isinstance(stored_autos, list):
            stored_autos = []

        merged = list(user_autos)
        user_ids = {str(a.get("id")) for a in user_autos if isinstance(a, dict) and a.get("id")}
        for sa in stored_autos:
            if isinstance(sa, dict) and str(sa.get("id")) not in user_ids:
                merged.append(sa)
        return merged

    async def async_read_scripts(self) -> dict[str, Any]:
        """Read all scripts from scripts.yaml and Otis managed store."""
        user_scripts = await self.hass.async_add_executor_job(self._read_yaml_file, self.scripts_path)
        if not isinstance(user_scripts, dict):
            user_scripts = {}
        try:
            stored_scripts = await self._script_store.async_load()
        except Exception as err:
            _LOGGER.debug("Could not load stored scripts: %s", err)
            stored_scripts = {}
        if isinstance(stored_scripts, dict):
            merged = dict(user_scripts)
            merged.update(stored_scripts)
            return merged
        return user_scripts

    async def async_write_automation(self, automation_data: dict[str, Any]) -> str:
        """Add or update an integration-managed automation in the otis_ai_automations store (zero user YAML writes)."""
        # Clean temporary internal keys
        clean_data = {k: v for k, v in automation_data.items() if not str(k).startswith("_")}
        target_id = clean_data.get("id")
        target_alias = clean_data.get("alias")

        stored_autos = await self._auto_store.async_load()
        if not isinstance(stored_autos, list):
            stored_autos = []

        # Find existing automation by ID or by exact alias in store
        index = -1
        for i, auto in enumerate(stored_autos):
            if not isinstance(auto, dict):
                continue
            if target_id and str(auto.get("id")) == str(target_id):
                index = i
                break
            if target_alias and auto.get("alias") == target_alias:
                index = i
                if not target_id and auto.get("id"):
                    target_id = auto.get("id")
                    clean_data["id"] = target_id
                break

        if not target_id:
            all_known = await self.async_read_automations()
            existing_ids = {str(a.get("id")) for a in all_known if isinstance(a, dict) and a.get("id")}
            base_id = str(int(time.time()))
            candidate_id = base_id
            suffix = 1
            while candidate_id in existing_ids:
                candidate_id = f"{base_id}_{suffix}"
                suffix += 1
            target_id = candidate_id
            clean_data["id"] = target_id
            automation_data["id"] = target_id
            _LOGGER.debug("Generated unique ID for automation: %s", target_id)
        else:
            automation_data["id"] = target_id

        if index >= 0:
            stored_autos[index] = clean_data
            _LOGGER.debug("Updated existing stored automation %s ('%s')", target_id, target_alias)
        else:
            stored_autos.append(clean_data)
            _LOGGER.debug("Appended new stored automation %s ('%s')", target_id, target_alias)

        await self._auto_store.async_save(stored_autos)
        _LOGGER.info("Saved automation %s to otis_ai_automations store (zero user YAML writes)", target_id)
        return str(target_id)

    async def async_write_script(self, script_key: str, script_data: dict[str, Any]) -> None:
        """Add or update an integration-managed script in the otis_ai_scripts store (zero user YAML writes)."""
        stored_scripts = await self._script_store.async_load()
        if not isinstance(stored_scripts, dict):
            stored_scripts = {}
        clean_data = {k: v for k, v in script_data.items() if not str(k).startswith("_")}
        stored_scripts[script_key] = clean_data
        await self._script_store.async_save(stored_scripts)
        _LOGGER.info("Saved script %s to otis_ai_scripts store (zero user YAML writes)", script_key)

    async def async_write_blueprint(self, blueprint_subpath: str, blueprint_content: str | dict[str, Any]) -> str:
        """Add or update an integration-managed blueprint in the otis_ai_blueprints store (zero user YAML writes)."""
        # Sanitize path to prevent directory traversal
        clean_subpath = os.path.normpath(blueprint_subpath.lstrip("/")).replace("\\", "/")
        if clean_subpath.startswith("../") or clean_subpath.startswith("..") or clean_subpath.startswith("/"):
            raise ValueError(f"Invalid blueprint path: {blueprint_subpath}")

        stored_bps = await self._bp_store.async_load()
        if not isinstance(stored_bps, dict):
            stored_bps = {}
        stored_bps[clean_subpath] = blueprint_content
        await self._bp_store.async_save(stored_bps)
        _LOGGER.info("Saved blueprint %s to otis_ai_blueprints store (zero user YAML writes)", clean_subpath)
        return clean_subpath

    async def async_reload_automations(self) -> bool:
        """Trigger a reload of the automation integration."""
        _LOGGER.debug("Reloading Home Assistant automations...")
        try:
            await self.hass.services.async_call("automation", "reload")
            return True
        except Exception as err:
            _LOGGER.error("Failed to reload automations: %s", err)
            return False

    async def async_reload_scripts(self) -> bool:
        """Trigger a reload of the script integration."""
        _LOGGER.debug("Reloading Home Assistant scripts...")
        try:
            await self.hass.services.async_call("script", "reload")
            return True
        except Exception as err:
            _LOGGER.error("Failed to reload scripts: %s", err)
            return False

    async def async_reload_blueprints(self) -> bool:
        """Trigger a reload of blueprints in Home Assistant."""
        _LOGGER.debug("Reloading Home Assistant blueprints...")
        try:
            if self.hass.services.has_service("blueprint", "reload"):
                await self.hass.services.async_call("blueprint", "reload")
            return True
        except Exception as err:
            _LOGGER.debug("Blueprint reload service call note: %s", err)
            return False

    async def async_cross_reference(
        self,
        text: str,
        max_matches: int = 8,
    ) -> dict[str, Any]:
        """Scan automations.yaml and scripts.yaml for mentioned entities or topics and return matching YAML blocks."""
        if not text:
            return {"matches": []}

        # 1. Extract potential entity IDs from text (e.g. input_boolean.guest_mode, light.living_room)
        entity_matches = re.findall(r"\b[a-z_]+[a-z0-9_]*\.[a-z0-9_]+\b", text.lower())

        # 2. Extract potential domain keywords / phrases (e.g. 'guest mode', 'adaptive inside lights')
        text_lower = text.lower()
        phrases = set(entity_matches)
        for em in entity_matches:
            parts = em.split(".", 1)
            if len(parts) == 2:
                phrases.add(parts[1])
                phrases.add(parts[1].replace("_", " "))

        # Also search for multi-word phrases from text if keywords present
        for candidate in (
            "guest mode", "guest", "climate", "thermostat", "downstairs", "upstairs",
            "adaptive lights", "adaptive inside lights", "lights off at bed", "guest lock code",
            "vacation mode", "away mode", "sleep mode", "bedtime", "lock code", "schlage"
        ):
            if candidate in text_lower:
                phrases.add(candidate)

        # Salient words (length >= 4)
        stopwords = {"what", "does", "when", "turn", "turns", "with", "from", "that", "this", "have", "please", "about", "show", "tell", "check"}
        words = [w for w in re.findall(r"\b[a-z]{4,}\b", text_lower) if w not in stopwords]

        if not phrases and not words:
            return {"matches": []}

        automations = await self.async_read_automations()
        scripts = await self.async_read_scripts()

        scored_matches: list[tuple[float, dict[str, Any]]] = []

        # Check automations
        for auto in automations:
            if not isinstance(auto, dict):
                continue
            auto_id = str(auto.get("id", ""))
            alias = str(auto.get("alias", ""))

            try:
                dumped = yaml.dump(auto, sort_keys=False, default_flow_style=False)
            except Exception:
                dumped = str(auto)
            dumped_lower = dumped.lower()
            alias_lower = alias.lower()

            score = 0.0
            matched_terms = []

            for em in entity_matches:
                if em in dumped_lower:
                    score += 100.0
                    matched_terms.append(em)

            for p in phrases:
                if p in alias_lower:
                    score += 50.0
                    matched_terms.append(p)
                elif p in dumped_lower and p not in entity_matches:
                    score += 25.0
                    matched_terms.append(p)

            for w in words:
                if w in alias_lower:
                    score += 10.0
                    matched_terms.append(w)

            # If user query is asking about whole-home guest mode, also include primary climate & bedtime automations
            if ("guest" in text_lower or "guest_mode" in text_lower):
                if "climate: thermostat" in alias_lower:
                    score += 40.0
                    matched_terms.append("climate_coordinator")

            if score > 0:
                lines = dumped.splitlines()
                truncated = False
                # If explicitly named or high-relevance match, preserve up to 250 lines so full actions/conditions are visible
                max_lines = 250 if (score >= 40.0 or (alias and alias.lower() in text_lower)) else 70
                if len(lines) > max_lines:
                    dumped = "\n".join(lines[:max_lines]) + "\n  # ... [additional actions truncated for brevity]"
                    truncated = True

                blueprint_info = auto.get("use_blueprint")
                blueprint_path = ""
                blueprint_file_content = None
                if isinstance(blueprint_info, dict):
                    blueprint_path = str(blueprint_info.get("path") or "")
                elif isinstance(blueprint_info, str):
                    blueprint_path = blueprint_info

                if blueprint_path and hasattr(self.hass, "config") and hasattr(self.hass.config, "path"):
                    bp_full_path = self.hass.config.path("blueprints", "automation", blueprint_path)
                    blueprint_file_content = await self.hass.async_add_executor_job(
                        _read_blueprint_snippet, bp_full_path, 120
                    )

                match_payload = {
                    "type": "automation",
                    "id": auto_id,
                    "name": alias or auto_id,
                    "score": score,
                    "matched_terms": list(set(matched_terms)),
                    "yaml": dumped,
                    "truncated": truncated,
                }
                if blueprint_path:
                    match_payload["uses_blueprint"] = True
                    match_payload["blueprint_path"] = blueprint_path
                    if blueprint_file_content:
                        match_payload["blueprint_yaml"] = blueprint_file_content

                scored_matches.append((score, match_payload))

        # Check scripts
        for s_key, s_data in scripts.items():
            if not isinstance(s_data, dict):
                continue
            alias = str(s_data.get("alias", s_key))
            try:
                dumped = yaml.dump({s_key: s_data}, sort_keys=False, default_flow_style=False)
            except Exception:
                dumped = str({s_key: s_data})
            dumped_lower = dumped.lower()
            alias_lower = alias.lower()

            score = 0.0
            matched_terms = []

            for em in entity_matches:
                if em in dumped_lower or em == f"script.{s_key}":
                    score += 100.0
                    matched_terms.append(em)

            for p in phrases:
                if p in alias_lower or p == s_key:
                    score += 50.0
                    matched_terms.append(p)
                elif p in dumped_lower and p not in entity_matches:
                    score += 25.0
                    matched_terms.append(p)

            for w in words:
                if w in alias_lower or w in s_key:
                    score += 10.0
                    matched_terms.append(w)

            if score > 0:
                lines = dumped.splitlines()
                truncated = False
                max_lines = 250 if (score >= 40.0 or (alias and alias.lower() in text_lower)) else 70
                if len(lines) > max_lines:
                    dumped = "\n".join(lines[:max_lines]) + "\n  # ... [additional sequence steps truncated for brevity]"
                    truncated = True
                scored_matches.append((
                    score,
                    {
                        "type": "script",
                        "id": s_key,
                        "name": alias,
                        "score": score,
                        "matched_terms": list(set(matched_terms)),
                        "yaml": dumped,
                        "truncated": truncated,
                    }
                ))

        scored_matches.sort(key=lambda x: x[0], reverse=True)
        top_matches = [item for _, item in scored_matches[:max_matches]]

        # Scan recent logs if the user is asking about errors, setup failures, or broken automations
        recent_log_errors = []
        if any(k in text_lower for k in ("fail", "failed", "error", "setup", "broken", "bug", "traceback", "fix")):
            log_path = self.hass.config.path("home-assistant.log")
            def _read_recent_log_errors() -> list[str]:
                if not os.path.exists(log_path):
                    return []
                errs = []
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as lf:
                        recent_lines = lf.readlines()[-150:]
                        capturing = False
                        current_err = []
                        for line in recent_lines:
                            if "ERROR" in line or "The automation" in line:
                                capturing = True
                                current_err.append(line.strip())
                            elif capturing:
                                if re.match(r"^\d{4}-\d{2}-\d{2}", line):
                                    capturing = False
                                    if current_err:
                                        errs.append("\n".join(current_err[:10]))
                                        current_err = []
                                else:
                                    current_err.append(line.strip())
                        if current_err:
                            errs.append("\n".join(current_err[:10]))
                except Exception as log_e:
                    _LOGGER.debug("Could not read home-assistant.log: %s", log_e)
                return errs[-3:]

            try:
                recent_log_errors = await self.hass.async_add_executor_job(_read_recent_log_errors)
            except Exception as log_err:
                _LOGGER.debug("Could not inspect home-assistant.log for errors: %s", log_err)

        return {"matches": top_matches, "recent_log_errors": recent_log_errors}

    async def async_improve_automation(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Generate improved automation YAML without modifying user YAML files on disk."""
        target_id = str(payload.get("automation_id") or "")
        target_alias = str(payload.get("alias") or "")
        new_mode = payload.get("mode")
        replace_map: dict[str, str] = payload.get("replace_map") or {}
        replacement_auto = payload.get("replacement_automation")

        def _apply_replace_in_node(node: Any, r_map: dict[str, str], parent_key: str = "") -> Any:
            protected_keys = {"path", "action", "service", "platform", "domain", "type", "subtype", "id"}
            if isinstance(node, dict):
                out = {}
                for k, v in node.items():
                    if k == "use_blueprint" and isinstance(v, dict):
                        bp = dict(v)
                        if "input" in bp:
                            bp["input"] = _apply_replace_in_node(bp["input"], r_map, "input")
                        out[k] = bp
                    elif k in protected_keys and isinstance(v, str):
                        out[k] = v
                    else:
                        out[k] = _apply_replace_in_node(v, r_map, k)
                return out
            if isinstance(node, list):
                return [_apply_replace_in_node(item, r_map, parent_key) for item in node]
            if isinstance(node, str):
                updated = node
                for old_str, new_str in r_map.items():
                    if old_str and old_str in updated:
                        updated = updated.replace(old_str, new_str)
                return updated
            return node

        automations = await self.async_read_automations()
        matched = None
        for auto in automations:
            if not isinstance(auto, dict):
                continue
            if (target_id and str(auto.get("id")) == target_id) or (
                target_alias and str(auto.get("alias", "")).lower() == target_alias.lower()
            ):
                matched = dict(auto)
                break

        if not matched and not replacement_auto:
            return {
                "success": False,
                "error": f"Automation '{target_alias or target_id}' not found",
            }

        label = (
            (matched.get("alias") if matched else None)
            or (matched.get("id") if matched else None)
            or target_alias
            or target_id
            or "Automation"
        )
        if isinstance(replacement_auto, dict):
            final_auto = dict(replacement_auto)
            if matched and matched.get("id") and not final_auto.get("id"):
                final_auto["id"] = matched["id"]
        else:
            final_auto = dict(matched) if matched else {}
            if replace_map:
                final_auto = _apply_replace_in_node(final_auto, replace_map)
            if new_mode and "use_blueprint" not in final_auto:
                final_auto["mode"] = new_mode
                if new_mode in ("queued", "parallel") and "max" not in final_auto:
                    final_auto["max"] = 10

        # Generate clean YAML formatted string for user review / GUI application
        formatted_yaml = yaml.dump(final_auto, default_flow_style=False, sort_keys=False)

        # Update integration store if this automation exists in otis_ai_automations
        try:
            stored_autos = await self._auto_store.async_load()
            if isinstance(stored_autos, list):
                for i, sa in enumerate(stored_autos):
                    if isinstance(sa, dict) and (
                        (target_id and str(sa.get("id")) == target_id)
                        or (target_alias and str(sa.get("alias", "")).lower() == target_alias.lower())
                    ):
                        stored_autos[i] = final_auto
                        await self._auto_store.async_save(stored_autos)
                        break
        except Exception as store_err:
            _LOGGER.debug("Could not update store for improved automation: %s", store_err)

        return {
            "success": True,
            "action": "show_yaml",
            "title": f"Improved Automation: {label}",
            "message": f"Generated improved configuration for '{label}'. Copy this YAML into your Home Assistant Automation Editor (Settings -> Automations & Scenes).",
            "yaml": formatted_yaml,
            "automation": final_auto,
        }

    async def async_optimize_system_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Provide safe system configuration optimization recommendations without modifying configuration.yaml."""
        opt_type = payload.get("optimization_type", "recorder_commit_interval")

        if opt_type == "recorder_commit_interval":
            snippet = (
                "recorder:\n"
                "  commit_interval: 30        # batch DB writes every 30s to reduce disk I/O & lock contention\n"
                "  purge_keep_days: 10\n"
                "  auto_purge: true\n"
            )
            return {
                "success": True,
                "action": "show_yaml",
                "title": "Recorder Commit Interval Optimization",
                "message": "Add this snippet to your configuration.yaml to batch SQLite/PostgreSQL writes every 30s and reduce disk I/O.",
                "yaml": snippet,
                "instructions": "Copy and add this block under configuration.yaml, then restart Home Assistant.",
            }

        if opt_type == "suppress_recorder_32kb_log_filter":
            snippet = (
                "logger:\n"
                "  default: info\n"
                "  filters:\n"
                "    homeassistant.components.recorder.db_schema:\n"
                '      - "Event data for call_service exceed maximum size"\n'
            )
            return {
                "success": True,
                "action": "show_yaml",
                "title": "Suppress Recorder 32KB Log Warnings",
                "message": "Add this logger filter to your configuration.yaml to suppress noisy 32KB call_service warnings in the log.",
                "yaml": snippet,
                "instructions": "Copy and add this block under logger in configuration.yaml, then reload logger settings or restart.",
            }

        return {
            "success": False,
            "error": f"Unknown optimization_type: {opt_type}",
        }
