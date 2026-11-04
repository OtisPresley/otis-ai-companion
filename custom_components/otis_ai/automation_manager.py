"""Automation and script manager for Otis AI Companion."""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

import yaml
from homeassistant.core import HomeAssistant
from homeassistant.util import yaml as yaml_util

_LOGGER = logging.getLogger(__name__)


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
    """Manages reading and writing to automations.yaml and scripts.yaml."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.automations_path = hass.config.path("automations.yaml")
        self.scripts_path = hass.config.path("scripts.yaml")

    def _read_yaml_file(self, path: str) -> Any:
        """Read a YAML file from disk (blocking)."""
        if not os.path.exists(path):
            return [] if "automations" in path else {}
        try:
            return yaml_util.load_yaml(path)
        except Exception as err:
            _LOGGER.error("Error reading YAML file %s: %s", path, err)
            return [] if "automations" in path else {}

    def _write_yaml_file(self, path: str, data: Any) -> None:
        """Write a YAML file to disk (blocking)."""
        try:
            yaml_util.save_yaml(path, data)
        except Exception as err:
            _LOGGER.error("Error writing YAML file %s: %s", path, err)
            raise

    async def async_read_automations(self) -> list[dict[str, Any]]:
        """Read all automations from automations.yaml."""
        res = await self.hass.async_add_executor_job(self._read_yaml_file, self.automations_path)
        if not isinstance(res, list):
            return []
        return res

    async def async_read_scripts(self) -> dict[str, Any]:
        """Read all scripts from scripts.yaml."""
        res = await self.hass.async_add_executor_job(self._read_yaml_file, self.scripts_path)
        if not isinstance(res, dict):
            return {}
        return res

    async def async_write_automation(self, automation_data: dict[str, Any]) -> str:
        """Add or update an automation in automations.yaml."""
        automations = await self.async_read_automations()
        
        # Clean temporary internal keys
        clean_data = {k: v for k, v in automation_data.items() if not str(k).startswith("_")}
        target_id = clean_data.get("id")
        target_alias = clean_data.get("alias")

        # Find existing automation by ID or by exact alias
        index = -1
        for i, auto in enumerate(automations):
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
            existing_ids = {str(a.get("id")) for a in automations if isinstance(a, dict) and a.get("id")}
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
            automations[index] = clean_data
            _LOGGER.debug("Updated existing automation %s ('%s')", target_id, target_alias)
        else:
            automations.append(clean_data)
            _LOGGER.debug("Appended new automation %s ('%s')", target_id, target_alias)

        await self.hass.async_add_executor_job(self._write_yaml_file, self.automations_path, automations)
        return str(target_id)

    async def async_write_script(self, script_key: str, script_data: dict[str, Any]) -> None:
        """Add or update a script in scripts.yaml."""
        scripts = await self.async_read_scripts()
        scripts[script_key] = script_data
        _LOGGER.debug("Updated script %s", script_key)
        await self.hass.async_add_executor_job(self._write_yaml_file, self.scripts_path, scripts)

    async def async_write_blueprint(self, blueprint_subpath: str, blueprint_content: str | dict[str, Any]) -> str:
        """Write or update a blueprint in /config/blueprints/automation/<blueprint_subpath>."""
        if not hasattr(self.hass, "config") or not hasattr(self.hass.config, "path"):
            raise ValueError("Home Assistant config path is not available")

        # Sanitize path to prevent directory traversal
        clean_subpath = os.path.normpath(blueprint_subpath.lstrip("/")).replace("\\", "/")
        if clean_subpath.startswith("../") or clean_subpath.startswith("..") or clean_subpath.startswith("/"):
            raise ValueError(f"Invalid blueprint path: {blueprint_subpath}")

        bp_full_path = self.hass.config.path("blueprints", "automation", clean_subpath)

        def _write_bp() -> None:
            os.makedirs(os.path.dirname(bp_full_path), exist_ok=True)
            if isinstance(blueprint_content, str):
                with open(bp_full_path, "w", encoding="utf-8") as f:
                    f.write(blueprint_content)
            else:
                with open(bp_full_path, "w", encoding="utf-8") as f:
                    yaml.dump(blueprint_content, f, default_flow_style=False, sort_keys=False)

        await self.hass.async_add_executor_job(_write_bp)
        _LOGGER.info("Successfully wrote blueprint file: %s", bp_full_path)
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
        """Improve or patch an existing automation in automations.yaml while preserving !include/structure."""
        target_id = str(payload.get("automation_id") or "")
        target_alias = str(payload.get("alias") or "")
        new_mode = payload.get("mode")
        replace_map: dict[str, str] = payload.get("replace_map") or {}
        replacement_auto = payload.get("replacement_automation")

        def _apply_replace_in_node(node: Any, replace_map: dict[str, str], parent_key: str = "") -> Any:
            """Recursively apply replace_map only to safe values within a single automation."""
            protected_keys = {"path", "action", "service", "platform", "domain", "type", "subtype", "id"}
            if isinstance(node, dict):
                out = {}
                for k, v in node.items():
                    if k == "use_blueprint" and isinstance(v, dict):
                        bp = dict(v)
                        if "input" in bp:
                            bp["input"] = _apply_replace_in_node(bp["input"], replace_map, "input")
                        out[k] = bp
                    elif k in protected_keys and isinstance(v, str):
                        out[k] = v
                    else:
                        out[k] = _apply_replace_in_node(v, replace_map, k)
                return out
            if isinstance(node, list):
                return [_apply_replace_in_node(item, replace_map, parent_key) for item in node]
            if isinstance(node, str):
                updated = node
                for old_str, new_str in replace_map.items():
                    if old_str and old_str in updated:
                        updated = updated.replace(old_str, new_str)
                return updated
            return node

        def _patch_sync() -> tuple[bool, str]:
            if not os.path.exists(self.automations_path):
                return False, "automations.yaml not found"

            # Apply replace_map scoped strictly to the target automation block and safe lines only
            if replace_map:
                with open(self.automations_path, "r", encoding="utf-8") as f:
                    raw_text = f.read()
                lines = raw_text.splitlines(keepends=True)
                starts = [idx for idx, ln in enumerate(lines) if ln.startswith("- id:")]
                block_range: tuple[int, int] | None = None
                if starts and (target_id or target_alias):
                    for pos, s_idx in enumerate(starts):
                        e_idx = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
                        block_str = "".join(lines[s_idx:e_idx])
                        if (
                            target_id
                            and (
                                f"- id: '{target_id}'" in lines[s_idx]
                                or f'- id: "{target_id}"' in lines[s_idx]
                                or f"- id: {target_id}" in lines[s_idx]
                            )
                        ) or (target_alias and f"alias: {target_alias}" in block_str):
                            block_range = (s_idx, e_idx)
                            break
                s_bound, e_bound = block_range if block_range else (0, len(lines))
                protected_prefixes = ("path:", "action:", "service:", "trigger:", "- trigger:", "condition:", "- condition:")
                changed = False
                for idx in range(s_bound, e_bound):
                    stripped = lines[idx].strip()
                    if any(stripped.startswith(p) for p in protected_prefixes):
                        continue
                    new_line = lines[idx]
                    for old_str, new_str in replace_map.items():
                        if old_str and old_str in new_line:
                            new_line = new_line.replace(old_str, new_str)
                    if new_line != lines[idx]:
                        lines[idx] = new_line
                        changed = True
                # Also handle multi-line wrapped strings inside the block (e.g. 'Loading\n        ...')
                block_text = "".join(lines[s_bound:e_bound])
                new_block_text = block_text
                for old_str, new_str in replace_map.items():
                    parts = old_str.split()
                    if len(parts) >= 2:
                        pat = r"\s+".join(re.escape(p) for p in parts)
                        new_block_text = re.sub(pat, new_str, new_block_text)
                if new_block_text != block_text:
                    lines[s_bound:e_bound] = new_block_text.splitlines(keepends=True)
                    changed = True
                if changed:
                    with open(self.automations_path, "w", encoding="utf-8") as f:
                        f.writelines(lines)
                if not new_mode and not isinstance(replacement_auto, dict):
                    return True, target_alias or target_id

            automations = self._read_yaml_file(self.automations_path)
            if not isinstance(automations, list):
                return bool(replace_map), target_alias or target_id

            matched_idx = -1
            for i, auto in enumerate(automations):
                if not isinstance(auto, dict):
                    continue
                if (target_id and str(auto.get("id")) == target_id) or (
                    target_alias and str(auto.get("alias", "")).lower() == target_alias.lower()
                ):
                    matched_idx = i
                    break

            if matched_idx < 0:
                if replace_map:
                    return True, target_alias or target_id
                return False, f"Automation '{target_alias or target_id}' not found"

            current = automations[matched_idx]
            label = current.get("alias") or current.get("id") or target_id
            if isinstance(replacement_auto, dict):
                merged = dict(replacement_auto)
                if current.get("id"):
                    merged["id"] = current["id"]
                automations[matched_idx] = merged
            else:
                if replace_map:
                    current = _apply_replace_in_node(current, replace_map)
                if new_mode and "use_blueprint" not in current:
                    current["mode"] = new_mode
                    if new_mode in ("queued", "parallel") and "max" not in current:
                        current["max"] = 10
                automations[matched_idx] = current

            self._write_yaml_file(self.automations_path, automations)
            return True, str(label)

        ok, msg = await self.hass.async_add_executor_job(_patch_sync)
        if ok:
            await self.async_reload_automations()
            return {"success": True, "message": f"Improved automation '{msg}' and reloaded automations!"}
        return {"success": False, "error": msg}

    async def async_optimize_system_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Safely patch configuration.yaml (preserving !secret and !include tags) and apply runtime settings."""
        config_path = self.hass.config.path("configuration.yaml")
        opt_type = payload.get("optimization_type", "recorder_commit_interval")

        def _patch_config_sync() -> tuple[bool, str]:
            if not os.path.exists(config_path):
                return False, "configuration.yaml not found"
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()

            if opt_type == "recorder_commit_interval":
                if "commit_interval:" in content:
                    return True, "recorder.commit_interval is already configured in configuration.yaml"
                if "recorder:" in content:
                    updated = content.replace(
                        "recorder:\n",
                        "recorder:\n  commit_interval: 30        # batch DB writes every 30s to reduce I/O & lock contention\n",
                        1,
                    )
                else:
                    updated = (
                        content.rstrip()
                        + "\n\nrecorder:\n  commit_interval: 30\n  purge_keep_days: 10\n  auto_purge: true\n"
                    )
                with open(config_path, "w", encoding="utf-8") as f:
                    f.write(updated)
                return True, "Added 'commit_interval: 30' to recorder in configuration.yaml!"

            if opt_type == "suppress_recorder_32kb_log_filter":
                filter_line = '      - "Event data for call_service exceed maximum size"'
                if "Event data for call_service exceed maximum size" in content:
                    return True, "Recorder 32KB log filter is already present in configuration.yaml"
                if "  filters:\n" in content:
                    updated = content.replace(
                        "  filters:\n",
                        "  filters:\n    homeassistant.components.recorder.db_schema:\n"
                        + filter_line
                        + "\n",
                        1,
                    )
                    with open(config_path, "w", encoding="utf-8") as f:
                        f.write(updated)
                    return True, "Added recorder.db_schema 32KB warning filter to logger in configuration.yaml!"
            return False, f"Unknown optimization_type: {opt_type}"

        ok, msg = await self.hass.async_add_executor_job(_patch_config_sync)
        return {"success": ok, "message": msg if ok else None, "error": None if ok else msg}
