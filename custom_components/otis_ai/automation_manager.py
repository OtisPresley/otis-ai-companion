"""Automation and script manager for Otis AI Companion."""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import yaml as yaml_util

_LOGGER = logging.getLogger(__name__)


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
        
        # Ensure the automation has an ID
        auto_id = automation_data.get("id")
        if not auto_id:
            auto_id = str(int(time.time()))
            automation_data["id"] = auto_id
            _LOGGER.debug("Generated new ID for automation: %s", auto_id)

        # Find and replace if it exists, otherwise append
        index = -1
        for i, auto in enumerate(automations):
            if auto.get("id") == auto_id:
                index = i
                break

        if index >= 0:
            automations[index] = automation_data
            _LOGGER.debug("Updated existing automation %s", auto_id)
        else:
            automations.append(automation_data)
            _LOGGER.debug("Appended new automation %s", auto_id)

        await self.hass.async_add_executor_job(self._write_yaml_file, self.automations_path, automations)
        return auto_id

    async def async_write_script(self, script_key: str, script_data: dict[str, Any]) -> None:
        """Add or update a script in scripts.yaml."""
        scripts = await self.async_read_scripts()
        scripts[script_key] = script_data
        _LOGGER.debug("Updated script %s", script_key)
        await self.hass.async_add_executor_job(self._write_yaml_file, self.scripts_path, scripts)

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
