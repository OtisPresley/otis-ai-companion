"""Lovelace Dashboard Manager & Professional Dashboard Generator for Otis AI Companion."""
from __future__ import annotations

import copy
import json
import logging
import os
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)

from .const import (
    DOMAIN,
    CONF_CAMERA_STREAM_STRATEGY,
    DEFAULT_CAMERA_STREAM_STRATEGY,
    COMMAND_CENTER_DASHBOARD_ICON,
    COMMAND_CENTER_DASHBOARD_ID,
    COMMAND_CENTER_DASHBOARD_TITLE,
    COMMAND_CENTER_DASHBOARD_URL_PATH,
    resolve_otis_entity_id,
)
from .floorplan_parser import (
    compute_room_center_pin_positions,
    select_intelligent_room_controls,
)
from .vision_manager import get_canonical_camera_key, stream_priority

_LOGGER = logging.getLogger(__name__)

OTIS_DASHBOARD_ID = "otis_ai"
OTIS_DASHBOARD_URL_PATH = "otis-ai"
OTIS_DASHBOARD_TITLE = "Otis AI"
OTIS_DASHBOARD_ICON = "mdi:robot-outline"


class DashboardManager:
    """Manages automatic creation of the Admin-only Otis AI dashboard and pro-grade custom dashboards."""

    def __init__(
        self,
        hass: HomeAssistant,
        floorplan_parser: Any = None,
        rules_manager: Any = None,
    ) -> None:
        """Initialize the Dashboard Manager."""
        self.hass = hass
        self.floorplan_parser = floorplan_parser
        self.rules_manager = rules_manager
        self._cached_installed_cards: set[str] = set()
        self._managed_dashboards: dict[str, dict[str, Any]] = {}

    def get_camera_stream_strategy(self) -> str:
        """Retrieve configured camera stream strategy from config entry."""
        try:
            if hasattr(self.hass, "data") and DOMAIN in self.hass.data:
                for entry_val in self.hass.data[DOMAIN].values():
                    if isinstance(entry_val, dict):
                        data = entry_val.get("data", {})
                        if CONF_CAMERA_STREAM_STRATEGY in data:
                            return data[CONF_CAMERA_STREAM_STRATEGY]
        except Exception:
            pass
        return DEFAULT_CAMERA_STREAM_STRATEGY

    def _get_user_rules(self) -> dict[str, Any]:
        """Fetch current user behavioral and dashboard rules safely."""
        if self.rules_manager and hasattr(self.rules_manager, "get_rules"):
            try:
                return self.rules_manager.get_rules()
            except Exception:
                pass
        if hasattr(self.hass, "data") and isinstance(self.hass.data, dict):
            for entry_val in self.hass.data.values():
                if isinstance(entry_val, dict) and "rules_manager" in entry_val:
                    rm = entry_val["rules_manager"]
                    if hasattr(rm, "get_rules"):
                        try:
                            return rm.get_rules()
                        except Exception:
                            pass
        return {}

    def _get_active_switch_as_x_targets(self, entity_iter: Any) -> set[str]:
        """Return set of switch entity_ids and registry UUIDs that have an active switch_as_x wrapper."""
        active_wrapper_config_entries: set[str] = set()
        for ent_item in entity_iter:
            if getattr(ent_item, "platform", None) == "switch_as_x" and getattr(ent_item, "disabled_by", None) is None:
                ce_id = getattr(ent_item, "config_entry_id", None)
                if ce_id:
                    active_wrapper_config_entries.add(str(ce_id))

        active_targets: set[str] = set()
        if hasattr(self, "hass") and self.hass and hasattr(self.hass, "config_entries"):
            try:
                for ce in self.hass.config_entries.async_entries("switch_as_x"):
                    if getattr(ce, "disabled_by", None) is None and (
                        not active_wrapper_config_entries or ce.entry_id in active_wrapper_config_entries
                    ):
                        target_eid = (getattr(ce, "options", None) or {}).get("entity_id") or (
                            getattr(ce, "data", None) or {}
                        ).get("entity_id")
                        if target_eid:
                            active_targets.add(str(target_eid))
            except Exception:
                pass
        return active_targets

    def _resolve_effective_hidden_by(self, entry: Any, active_switch_as_x_targets: set[str]) -> Any:
        """Recover switches with orphaned hidden_by='integration' and deduplicate switches with active switch_as_x wrappers."""
        raw_hidden = getattr(entry, "hidden_by", None)
        domain = getattr(entry, "domain", None) or str(getattr(entry, "entity_id", "")).split(".")[0]
        if domain == "switch":
            eid = str(getattr(entry, "entity_id", "") or "")
            ent_uuid = str(getattr(entry, "id", "") or "")
            has_wrapper = eid in active_switch_as_x_targets or (bool(ent_uuid) and ent_uuid in active_switch_as_x_targets)
            if raw_hidden is not None and str(raw_hidden).lower().endswith("integration") and not has_wrapper:
                return None
            if raw_hidden is None and has_wrapper:
                return "integration"
        return raw_hidden

    def _storage_dir(self) -> str | None:
        """Return the path to Home Assistant's .storage directory if available."""
        if hasattr(self.hass, "config") and hasattr(self.hass.config, "path"):
            try:
                p = self.hass.config.path(".storage")
                if isinstance(p, str) and "MagicMock" not in p:
                    return p
            except Exception:
                pass
        return None

    def _get_dashboards_collection(self) -> Any:
        """Retrieve Home Assistant's DashboardsCollection from websocket_api handlers or lovelace data."""
        if hasattr(self.hass, "data") and isinstance(self.hass.data, dict):
            ws_api = self.hass.data.get("websocket_api")
            if isinstance(ws_api, dict):
                for cmd in ("lovelace/dashboards/list", "lovelace/dashboards/create", "lovelace/dashboards/update"):
                    handler = ws_api.get(cmd)
                    if isinstance(handler, tuple) and handler:
                        ws_obj = getattr(handler[0], "__self__", None)
                        storage_col = getattr(ws_obj, "storage_collection", None)
                        if storage_col is not None:
                            return storage_col
        return None

    def _dashboard_file_exists(self, dash_id: str) -> bool:
        """Check if dashboard storage file exists on disk."""
        storage_dir = self._storage_dir()
        if not storage_dir:
            return False
        return os.path.exists(os.path.join(storage_dir, f"lovelace.{dash_id}"))

    async def _async_dashboard_file_exists(self, dash_id: str) -> bool:
        """Check if dashboard storage file exists on disk non-blockingly."""
        # 1. Check in memory lovelace data
        if hasattr(self.hass, "data") and isinstance(self.hass.data, dict):
            ll_data = self.hass.data.get("lovelace")
            if ll_data is not None and hasattr(ll_data, "dashboards") and isinstance(ll_data.dashboards, dict):
                if dash_id in ll_data.dashboards or dash_id.replace("_", "-") in ll_data.dashboards:
                    return True
        # 2. Check dashboards collection
        storage_col = self._get_dashboards_collection()
        if storage_col is not None and hasattr(storage_col, "data") and isinstance(storage_col.data, dict):
            for k, v in storage_col.data.items():
                if k == dash_id or (isinstance(v, dict) and (v.get("id") == dash_id or v.get("url_path") == dash_id.replace("_", "-"))):
                    return True
        if hasattr(self.hass, "async_add_executor_job"):
            try:
                return await self.hass.async_add_executor_job(self._dashboard_file_exists, dash_id)
            except Exception:
                return False
        return self._dashboard_file_exists(dash_id)

    async def _async_inspect_lovelace_resources(self) -> set[str]:
        """Read Lovelace resources via Home Assistant collection or Store to detect installed cards."""
        detected = set()
        items = []
        if hasattr(self.hass, "data") and isinstance(self.hass.data, dict):
            ll_data = self.hass.data.get("lovelace")
            if ll_data is not None and hasattr(ll_data, "resources"):
                res_col = getattr(ll_data, "resources", None)
                if res_col is not None:
                    if hasattr(res_col, "async_items"):
                        try:
                            items = await res_col.async_items()
                        except Exception:
                            items = getattr(res_col, "data", [])
                    else:
                        items = getattr(res_col, "data", [])
        if not items:
            try:
                store = Store(self.hass, 1, "lovelace_resources")
                data = await store.async_load()
                if isinstance(data, dict):
                    items = data.get("items", []) or data.get("data", {}).get("items", [])
            except Exception as err:
                _LOGGER.debug("Could not inspect lovelace resources store: %s", err)

        if isinstance(items, (list, tuple)):
            for item in items:
                if isinstance(item, dict):
                    url = str(item.get("url", "")).lower()
                    if "mini-media-player" in url:
                        detected.add("custom:mini-media-player")
                    if "universal-remote-card" in url:
                        detected.add("custom:universal-remote-card")
                    if "mushroom" in url:
                        detected.add("custom:mushroom-media-player-card")
                    if "bubble-card" in url:
                        detected.add("custom:bubble-card")
                    if "snmp-network-manager-card" in url:
                        detected.add("custom:snmp-network-manager-card")
                    if "snmp-switch-manager-card" in url:
                        detected.add("custom:snmp-switch-manager-card")
                    if "advanced-camera-card" in url:
                        detected.add("custom:advanced-camera-card")
                    if "xiaomi-vacuum-map-card" in url:
                        detected.add("custom:xiaomi-vacuum-map-card")
        return detected

    def _inspect_lovelace_resources_sync(self) -> set[str]:
        """Fallback to empty set if async inspection was skipped."""
        return set()

    async def async_get_available_custom_cards(self, active_integrations: list[Any] | None = None) -> set[str]:
        """Detect custom Lovelace cards registered in Lovelace resources or bundled with active integrations."""
        cards: set[str] = set()
        try:
            cards = await self._async_inspect_lovelace_resources()
        except Exception:
            cards = self._inspect_lovelace_resources_sync()

        # Also detect cards bundled with active integrations
        if active_integrations:
            active_domains = {
                str(i.get("domain", "") if isinstance(i, dict) else i).lower()
                for i in active_integrations
            }
            if "snmp_network_manager" in active_domains:
                cards.add("custom:snmp-network-manager-card")
            if "snmp_switch_manager" in active_domains:
                cards.add("custom:snmp-switch-manager-card")

        self._cached_installed_cards.update(cards)
        return cards

    async def async_ensure_admin_companion_dashboard(
        self, capability_map: dict[str, Any] | None = None, force_regenerate: bool = False
    ) -> dict[str, Any]:
        """Automatically create and register the Owner/Admin-only Otis AI Companion dashboard with Hub-and-Spoke subviews."""
        item = {
            "id": OTIS_DASHBOARD_ID,
            "url_path": OTIS_DASHBOARD_URL_PATH,
            "title": OTIS_DASHBOARD_TITLE,
            "icon": OTIS_DASHBOARD_ICON,
            "require_admin": True,
            "show_in_sidebar": True,
            "mode": "storage",
        }
        installed_cards = await self.async_get_available_custom_cards(
            capability_map.get("integrations", []) if capability_map else None
        )
        svg_stat = await self._async_get_floorplan_svg_stat()
        dashboard_config = self._build_otis_companion_dashboard_config(
            capability_map, installed_cards=installed_cards, svg_stat=svg_stat
        )
        file_exists = await self._async_dashboard_file_exists(OTIS_DASHBOARD_ID)
        overwrite = True if (force_regenerate or capability_map or not file_exists) else False
        return await self._async_register_and_save_dashboard(
            item=item,
            dashboard_config=dashboard_config,
            overwrite_config=overwrite,
            force_regenerate=force_regenerate,
        )

    async def async_ensure_user_command_center_dashboard(
        self, capability_map: dict[str, Any] | None = None, force_regenerate: bool = False
    ) -> dict[str, Any]:
        """Automatically create and register the User role Command Center dashboard accessible to all users."""
        item = {
            "id": COMMAND_CENTER_DASHBOARD_ID,
            "url_path": COMMAND_CENTER_DASHBOARD_URL_PATH,
            "title": COMMAND_CENTER_DASHBOARD_TITLE,
            "icon": COMMAND_CENTER_DASHBOARD_ICON,
            "require_admin": False,
            "show_in_sidebar": True,
            "mode": "storage",
        }
        installed_cards = await self.async_get_available_custom_cards(
            capability_map.get("integrations", []) if capability_map else None
        )
        svg_stat = await self._async_get_floorplan_svg_stat()
        dashboard_config = self._build_user_command_center_dashboard_config(
            capability_map, installed_cards=installed_cards, svg_stat=svg_stat
        )
        file_exists = await self._async_dashboard_file_exists(COMMAND_CENTER_DASHBOARD_ID)
        overwrite = True if (force_regenerate or capability_map or not file_exists) else False
        return await self._async_register_and_save_dashboard(
            item=item,
            dashboard_config=dashboard_config,
            overwrite_config=overwrite,
            force_regenerate=force_regenerate,
        )

    # Alias for backward compatibility
    async_ensure_command_center_dashboard = async_ensure_user_command_center_dashboard

    def _build_people_and_pets_section(
        self,
        user_rules: dict[str, Any],
        entities_list: list[dict[str, Any]],
        layout_style: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Build a People & Pets presence section using profile pictures and live status."""
        ignored_set = {
            str(x).strip().lower()
            for x in (user_rules.get("ignored_persons") or [])
            if x
        }
        profiles = user_rules.get("person_profiles") or {}

        person_candidates: list[dict[str, Any]] = []
        seen_eids: set[str] = set()

        def _consider(eid: str, state: str, attrs: dict[str, Any]) -> None:
            if not eid or not eid.startswith("person.") or eid in seen_eids:
                return
            seen_eids.add(eid)
            eid_low = eid.lower()
            if eid_low in ignored_set:
                return
            prof = profiles.get(eid) or profiles.get(eid_low) or {}
            if isinstance(prof, dict) and prof.get("entity_type") == "ignored":
                return
            pic = attrs.get("entity_picture")
            trackers = attrs.get("device_trackers") or []
            samples = int(prof.get("samples", 0) or 0) if isinstance(prof, dict) else 0
            # Skip untracked placeholder accounts with no image and no profile samples
            if not pic and not trackers and samples < 1:
                return
            # Skip guest/ephemeral accounts with no image when primary residents/pets exist
            person_candidates.append({
                "entity_id": eid,
                "state": str(state or "unknown").lower(),
                "has_pic": bool(pic),
                "has_trackers": bool(trackers),
                "samples": samples,
            })

        for e in entities_list:
            eid = str(e.get("entity_id") or "")
            if eid.startswith("person.") and not e.get("disabled_by") and not e.get("hidden_by"):
                attrs = dict(e.get("attributes") or {})
                if hasattr(self, "hass") and self.hass and hasattr(self.hass, "states"):
                    st = self.hass.states.get(eid)
                    if st:
                        attrs = {**attrs, **dict(st.attributes)}
                        _consider(eid, st.state, attrs)
                        continue
                _consider(eid, str(e.get("state") or "unknown"), attrs)

        if hasattr(self, "hass") and self.hass and hasattr(self.hass, "states"):
            for st in self.hass.states.async_all("person"):
                _consider(st.entity_id, st.state, dict(st.attributes))

        if not person_candidates:
            return None, None

        # If we have profiled/pictured residents or pets, filter out unpictured unknown placeholders
        has_primary = any(p["has_pic"] or p["samples"] >= 2 for p in person_candidates)
        if has_primary:
            filtered = [
                p for p in person_candidates
                if p["has_pic"] or p["samples"] >= 2 or p["state"] == "home"
            ]
            if filtered:
                person_candidates = filtered

        person_candidates.sort(
            key=lambda p: (
                0 if p["has_pic"] else 1,
                0 if p["state"] == "home" else 1,
                -p["samples"],
                p["entity_id"],
            )
        )
        person_eids = [p["entity_id"] for p in person_candidates[:8]]

        tile_cards = [
            {
                "type": "tile",
                "entity": eid,
                "show_entity_picture": True,
            }
            for eid in person_eids
        ]
        section_obj = {
            "type": "grid",
            "cards": [
                {
                    "type": "heading",
                    "heading": "People & Pets",
                    "icon": "mdi:account-group",
                    "heading_style": "title",
                },
                {
                    "type": "grid",
                    "columns": 2 if len(tile_cards) <= 4 else 3,
                    "square": False,
                    "cards": tile_cards,
                },
            ],
        }
        traditional_card = {
            "type": "glance",
            "title": "People & Pets",
            "show_name": True,
            "show_state": True,
            "entities": person_eids,
        } if not self._is_sections_layout(layout_style) else {
            "type": "grid",
            "title": "People & Pets",
            "columns": 2 if len(tile_cards) <= 4 else 3,
            "square": False,
            "cards": tile_cards,
        }
        return section_obj, traditional_card

    def _has_pool_entities(self, capability_map: dict[str, Any] | None) -> bool:
        """Return True if any active pool/spa/water-chemistry entities are present in capability_map."""
        if not capability_map:
            return False
        entities = capability_map.get("entities", [])
        valid_eids = {
            e["entity_id"]
            for e in entities
            if e.get("entity_id")
            and not e.get("disabled_by")
            and not e.get("hidden_by")
        }
        grouped = self._classify_pool_and_spa_entities(entities, valid_eids)
        return any(grouped.values())

    def _classify_pool_and_spa_entities(
        self,
        entities: list[dict[str, Any]],
        valid_eids: set[str],
    ) -> dict[str, list[str]]:
        """Dynamically classify pool chemistry, chlorinator, pool equipment, and spa entities."""
        grouped: dict[str, list[str]] = {
            "chemistry": [],
            "chemistry_alerts": [],
            "chlorinator": [],
            "pool_climates": [],
            "pool_equipment": [],
            "spa_climates": [],
            "spa_controls": [],
        }
        allowed_domains = {
            "sensor",
            "binary_sensor",
            "switch",
            "light",
            "climate",
            "number",
            "select",
            "vacuum",
            "button",
            "time",
        }
        ignore_substrings = (
            "pre_release",
            "crawl_space",
            "workspace",
            "free_space",
            "used_space",
            "account_used_space",
            "otis_spatial",
            "ap_",
        )
        chemistry_keywords = (
            "waterguru",
            "iopool",
            "sutro",
            "free_chlorine",
            "total_chlorine",
            "alkalinity",
            "calcium_hardness",
            "total_hardness",
            "cyanuric",
            "stabilizer",
            "saturation_index",
            "skimmer_flow",
            "water_temperature",
            "pool_status",
            "cassette",
            "orp",
        )
        chlorinator_keywords = (
            "chlorinat",
            "salt_level",
            "chlorinator_salt",
            "super_chlorin",
            "orp_setpoint",
            "sanitizer",
        )
        spa_keywords = (
            "spaclient",
            "hot_tub",
            "jacuzzi",
            "filter_cycle",
            "heat_mode",
            "hold_mode",
            "standby_mode",
            "temperature_range",
            "last_known_fault",
        )
        pool_platforms = {
            "screenlogic",
            "pentair",
            "hayward",
            "omnilogic",
            "jandy",
            "iaqualink",
            "aqualink",
            "waterguru",
            "iopool",
            "sutro",
            "mydolphin_plus",
            "spaclient",
            "balboa",
            "gecko",
            "intex_spa",
        }
        pool_device_ids = {
            e.get("device_id")
            for e in entities
            if e.get("device_id") and str(e.get("platform", "")).lower() in pool_platforms
        }
        pool_equip_keywords = (
            "pentair",
            "hayward",
            "jandy",
            "screenlogic",
            "poolio",
            "pool",
        )

        for e in entities:
            eid = str(e.get("entity_id") or "")
            domain = str(e.get("domain") or (eid.split(".", 1)[0] if "." in eid else ""))
            if not eid or eid not in valid_eids or domain not in allowed_domains:
                continue
            eid_low = eid.lower()
            name_low = str(e.get("name") or e.get("friendly_name") or "").lower()
            plat_low = str(e.get("platform") or "").lower()
            dev_id = e.get("device_id")
            is_pool_platform = plat_low in pool_platforms or (bool(dev_id) and dev_id in pool_device_ids)
            combined = f"{eid_low} {name_low}"
            if not is_pool_platform and any(bad in combined for bad in ignore_substrings):
                continue

            attrs = e.get("attributes") or {}
            dc = str(e.get("device_class") or attrs.get("device_class") or "").lower()
            unit = str(e.get("unit_of_measurement") or attrs.get("unit_of_measurement") or "").lower()

            # Normalize 'space' out before checking 'spa' token
            spa_check = combined.replace("space", "")
            is_spa = (
                bool(re.search(r"\bspa\b|_spa\b|\bspa_", spa_check))
                or any(k in combined for k in spa_keywords)
            )
            is_chlorinator = any(k in combined for k in chlorinator_keywords)
            is_chemistry = (
                dc == "ph"
                or any(k in combined for k in chemistry_keywords)
                or (unit == "ppm" and any(k in combined for k in ("chlorine", "alkalinity", "hardness", "cyanuric", "pool")))
            ) and not is_chlorinator

            if is_spa and not is_chemistry and not is_chlorinator:
                if domain == "climate":
                    grouped["spa_climates"].append(eid)
                else:
                    grouped["spa_controls"].append(eid)
            elif is_chlorinator:
                grouped["chlorinator"].append(eid)
            elif is_chemistry:
                if "alert" in combined or "cassette" in combined or "battery" in combined or "signal" in combined or domain == "button" or "last_measurement" in combined:
                    grouped["chemistry_alerts"].append(eid)
                else:
                    grouped["chemistry"].append(eid)
            elif is_pool_platform or any(k in combined for k in pool_equip_keywords):
                if domain == "climate":
                    grouped["pool_climates"].append(eid)
                else:
                    grouped["pool_equipment"].append(eid)

        def _sort_by_rank(eids: list[str], rank_rules: tuple[tuple[str, ...], ...]) -> list[str]:
            def _key(eid: str) -> tuple[int, str]:
                low = eid.lower()
                for idx, tokens in enumerate(rank_rules):
                    if any(t in low for t in tokens):
                        return (idx, low)
                return (len(rank_rules), low)
            return sorted(eids, key=_key)

        grouped["chemistry"] = _sort_by_rank(
            grouped["chemistry"],
            (
                ("_status", "pool_status"),
                ("water_temperature", "water_temp"),
                ("_ph",),
                ("free_chlorine",),
                ("total_chlorine",),
                ("total_alkalinity", "alkalinity"),
                ("calcium_hardness",),
                ("total_hardness",),
                ("cyanuric", "stabilizer"),
                ("skimmer_flow",),
            ),
        )
        grouped["chemistry_alerts"] = _sort_by_rank(
            grouped["chemistry_alerts"],
            (
                ("_alert",),
                ("last_measurement",),
                ("cassette_remaining", "cassette_days"),
                ("battery",),
                ("signal",),
                ("manual_measurement", "replace_cassette"),
            ),
        )
        grouped["chlorinator"] = _sort_by_rank(
            grouped["chlorinator"],
            (
                ("chlorinator_setpoint", "chlorinator_output"),
                ("chlorinator",),
                ("salt",),
                ("super_chlorin",),
            ),
        )
        grouped["pool_equipment"] = _sort_by_rank(
            grouped["pool_equipment"],
            (
                ("_pool", "high_speed", "low_speed", "pool_pump", "pool_low_speed", "pool_high_speed"),
                ("bubbler", "fountain", "waterfall", "feature", "blower"),
                ("light", "color", "led_mode", "led_intensity"),
                ("vacuum", "poolio"),
                ("watts", "gpm", "rpm"),
                ("air_temperature",),
                ("chemistry_alarm", "freeze_mode", "delay", "active_alert"),
            ),
        )
        grouped["spa_controls"] = _sort_by_rank(
            grouped["spa_controls"],
            (
                ("pump_1",),
                ("pump_2",),
                ("light",),
                ("heat_mode",),
                ("hold_mode",),
                ("standby_mode",),
                ("temperature_range",),
                ("last_known_fault",),
                ("filter_cycle_1_status", "filter_cycle_2_status"),
                ("filter_cycle",),
            ),
        )

        return grouped

    def _get_active_studios(self, capability_map: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Return active Studio definitions with dynamic names based on discovered integrations."""
        if not capability_map:
            return [
                {"key": "floorplan", "name": "Floor Plan", "path": "floorplan", "icon": "mdi:floor-plan", "is_panel": True},
                {"key": "energy", "name": "Energy Studio", "path": "energy", "icon": "mdi:lightning-bolt"},
                {"key": "media", "name": "Media Studio", "path": "media", "icon": "mdi:speaker-multiple"},
                {"key": "security", "name": "Security Center", "path": "security", "icon": "mdi:shield-home"},
                {"key": "climate", "name": "Climate", "path": "climate", "icon": "mdi:thermostat-box"},
            ]

        entities = [
            e for e in capability_map.get("entities", [])
            if e.get("entity_id")
            and not e.get("disabled_by")
            and not e.get("hidden_by")
            and e.get("state") not in ("unknown", "unavailable", None, "")
        ]
        media_topo = capability_map.get("media_topology", {})
        sec_topo = capability_map.get("security_topology", {})
        energy_topo = capability_map.get("energy_topology", {})

        has_energy = bool(
            energy_topo.get("tariff")
            or energy_topo.get("solar")
            or energy_topo.get("total_power_w", 0) > 0
            or any(
                (e.get("domain") == "sensor" and (e["entity_id"].endswith("_power") or e["entity_id"].endswith("_energy")))
                or e.get("attributes", {}).get("unit_of_measurement") in ("W", "kW", "Wh", "kWh")
                or "battery" in e["entity_id"]
                or "ups" in e["entity_id"]
                for e in entities
            )
        )
        has_media = bool(
            media_topo.get("matrix_zones")
            or media_topo.get("input_streamers")
            or media_topo.get("tv_cinema_zones")
            or any(e.get("domain") == "media_player" for e in entities)
        )
        has_security = bool(
            sec_topo.get("alarm_panels")
            or sec_topo.get("locks")
            or sec_topo.get("cameras")
            or sec_topo.get("garage_covers")
            or any(e.get("domain") in ("alarm_control_panel", "lock", "camera") for e in entities)
        )
        has_pool = self._has_pool_entities(capability_map)
        has_climate = bool(
            has_pool
            or any(
                e.get("domain") in ("climate", "fan")
                or "sleepnumber" in str(e.get("entity_id", "")).lower()
                for e in entities
            )
        )

        studios: list[dict[str, Any]] = [
            {"key": "floorplan", "name": "Floor Plan", "path": "floorplan", "icon": "mdi:floor-plan", "is_panel": True}
        ]
        if has_energy:
            studios.append({"key": "energy", "name": "Energy Studio", "path": "energy", "icon": "mdi:lightning-bolt"})
        if has_media:
            studios.append({"key": "media", "name": "Media Studio", "path": "media", "icon": "mdi:speaker-multiple"})
        if has_security:
            studios.append({"key": "security", "name": "Security Center", "path": "security", "icon": "mdi:shield-home"})
        if has_climate:
            studios.append({
                "key": "climate",
                "name": "Climate & Pool" if has_pool else "Climate",
                "path": "climate",
                "icon": "mdi:thermostat-box",
            })
        return studios

    @staticmethod
    def _is_sections_layout(layout_style: str | None) -> bool:
        """Return True if layout_style uses Lovelace sections (modern_sections or compact)."""
        return str(layout_style or "modern_sections").lower() in ("modern_sections", "compact")

    @staticmethod
    def _resolve_nav_grid_params(nav_style: str | None) -> tuple[int, bool, str | None]:
        """Return (columns, square, icon_height) for a given navigation_style."""
        style = str(nav_style or "sleek_buttons").lower()
        if style == "standard_grid":
            return 3, True, "44px"
        if style == "compact_pills":
            return 4, False, "20px"
        return 2, False, "34px"

    def _apply_view_layout(
        self,
        view: dict[str, Any],
        cards: list[dict[str, Any]],
        layout_style: str | None,
        sections: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Apply modern_sections, compact, or classic layout structure to a Lovelace view."""
        view["cards"] = cards
        norm_layout = str(layout_style or "modern_sections").lower()
        if self._is_sections_layout(norm_layout):
            view["type"] = "sections"
            view["max_columns"] = 4 if norm_layout == "compact" else 3
            if norm_layout == "compact":
                view["dense_section_placement"] = True
            view["sections"] = sections if sections is not None else self._convert_cards_to_sections(cards)
        return view

    def _build_studio_navigation_card(
        self,
        dashboard_url_path: str = COMMAND_CENTER_DASHBOARD_URL_PATH,
        nav_style: str = "sleek_buttons",
        capability_map: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build responsive studio navigation buttons matching user's navigation_style."""
        button_cols, button_square, icon_height = self._resolve_nav_grid_params(nav_style)
        nav_buttons = [
            {
                "type": "button",
                "name": "Overview",
                "icon": "mdi:view-dashboard",
                **({"icon_height": icon_height} if icon_height else {}),
                "tap_action": {"action": "navigate", "navigation_path": f"/{dashboard_url_path}"},
            },
        ]
        for st in self._get_active_studios(capability_map):
            nav_buttons.append({
                "type": "button",
                "name": st["name"],
                "icon": st["icon"],
                **({"icon_height": icon_height} if icon_height else {}),
                "tap_action": {"action": "navigate", "navigation_path": f"/{dashboard_url_path}/{st['path']}"},
            })
        return {
            "type": "grid",
            "title": "Studio Navigation",
            "columns": button_cols,
            "square": button_square,
            "cards": nav_buttons,
        }

    def _convert_cards_to_sections(self, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert a list of Lovelace cards into modern responsive section objects."""
        sections: list[dict[str, Any]] = []
        i = 0
        n = len(cards)
        while i < n:
            card = cards[i]
            if not isinstance(card, dict):
                i += 1
                continue
            c_type = card.get("type", "")
            title = card.get("title")

            # Keep navigation grids intact so their columns, square, and icon_height settings are honored in sections views
            if c_type == "grid" and any(k in (title or "").lower() for k in ("nav", "studio", "navigation")):
                sec_cards: list[dict[str, Any]] = []
                if title:
                    sec_cards.append({
                        "type": "heading",
                        "heading": title,
                        "heading_style": "title",
                    })
                nav_grid = dict(card)
                nav_grid.pop("title", None)
                nav_grid["grid_options"] = {"columns": 12}
                sec_cards.append(nav_grid)
                sec_obj: dict[str, Any] = {
                    "type": "grid",
                    "cards": sec_cards,
                }
                if int(card.get("columns", 2) or 2) >= 3:
                    sec_obj["column_span"] = 2
                sections.append(sec_obj)
                i += 1
                continue

            if c_type == "grid":
                sec_cards = []
                if title:
                    sec_cards.append({
                        "type": "heading",
                        "heading": title,
                        "heading_style": "title",
                    })
                grid_cards = card.get("cards", [])
                sec_cards.extend(grid_cards)
                sec_obj: dict[str, Any] = {
                    "type": "grid",
                    "cards": sec_cards,
                }
                if any(isinstance(c, dict) and c.get("type") in ("picture-entity", "picture-elements") for c in grid_cards):
                    sec_obj["column_span"] = 2
                sections.append(sec_obj)
            elif c_type in ("entities", "media-control", "alarm-panel", "thermostat", "picture-elements", "picture-entity"):
                sec_cards = []
                card_copy = dict(card)
                if title:
                    sec_cards.append({
                        "type": "heading",
                        "heading": title,
                        "heading_style": "title",
                    })
                    card_copy.pop("title", None)
                sec_cards.append(card_copy)
                sec_obj = {
                    "type": "grid",
                    "cards": sec_cards,
                }
                if c_type in ("picture-entity", "picture-elements"):
                    sec_obj["column_span"] = 2
                sections.append(sec_obj)
            elif c_type == "markdown":
                sections.append({
                    "type": "grid",
                    "cards": [card],
                })
            else:
                sec_obj = {
                    "type": "grid",
                    "cards": [card],
                }
                if c_type == "custom:otis-companion-card" and card.get("mode") in ("media_studio", "floorplan_studio", "floorplan_control"):
                    sec_obj["column_span"] = 2
                elif c_type == "grid" and card.get("title") in ("Studio Navigation", "Room Navigation") and int(card.get("columns", 2) or 2) >= 3:
                    sec_obj["column_span"] = 2
                sections.append(sec_obj)
            i += 1
        return sections

    def _build_studio_view(
        self,
        title: str,
        path: str,
        icon: str,
        cards: list[dict[str, Any]],
        layout_style: str = "modern_sections",
        is_panel: bool = False,
    ) -> dict[str, Any]:
        """Wrap studio cards into a structured Lovelace subview adhering to layout_style."""
        view: dict[str, Any] = {
            "title": title,
            "path": path,
            "icon": icon,
            "subview": True,
            "theme": self._get_user_rules().get("theme") or "otis_generate_midnight_slate",
            "badges": [],
            "cards": cards,
        }
        if is_panel:
            view["type"] = "panel"
            view["panel"] = True
        else:
            self._apply_view_layout(view, cards, layout_style)
        return view

    def _build_user_command_center_dashboard_config(
        self,
        capability_map: dict[str, Any] | None = None,
        installed_cards: set[str] | None = None,
        svg_stat: tuple[bool, int] | None = None,
    ) -> dict[str, Any]:
        """Build the Lovelace config for the Non-Admin User Command Center dashboard."""
        areas_map = capability_map.get("areas", {}) if capability_map else {}
        entities_list = capability_map.get("entities", []) if capability_map else []

        if not areas_map and not entities_list and hasattr(self, "hass") and self.hass:
            try:
                area_reg = ar.async_get(self.hass)
                device_reg = dr.async_get(self.hass)
                entity_reg = er.async_get(self.hass)
                raw_devices = getattr(device_reg, "devices", {})
                device_iter = list(raw_devices.values() if isinstance(raw_devices, dict) else raw_devices)
                dev_areas = {d.id: d.area_id for d in device_iter}
                dev_models = {d.id: getattr(d, "model", None) for d in device_iter}
                areas_map = {a.id: {"name": a.name, "entities": []} for a in area_reg.async_list_areas()}
                raw_entities = getattr(entity_reg, "entities", {})
                entity_iter = list(raw_entities.values() if isinstance(raw_entities, dict) else raw_entities)
                active_switch_targets = self._get_active_switch_as_x_targets(entity_iter)
                for entry in entity_iter:
                    eff_hidden = self._resolve_effective_hidden_by(entry, active_switch_targets)
                    if entry.disabled_by or eff_hidden:
                        continue
                    aid = entry.area_id or dev_areas.get(entry.device_id)
                    st = self.hass.states.get(entry.entity_id) if hasattr(self.hass, "states") else None
                    e_state = st.state if st else "unknown"
                    e_info = {
                        "entity_id": entry.entity_id,
                        "name": entry.name or entry.original_name,
                        "domain": getattr(entry, "domain", None) or entry.entity_id.split(".")[0],
                        "platform": getattr(entry, "platform", None),
                        "device_id": getattr(entry, "device_id", None),
                        "device_model": dev_models.get(getattr(entry, "device_id", None)),
                        "area_id": aid,
                        "disabled_by": entry.disabled_by,
                        "hidden_by": eff_hidden,
                        "state": e_state,
                    }
                    entities_list.append(e_info)
                    if aid and aid in areas_map:
                        areas_map[aid]["entities"].append(entry.entity_id)
            except Exception as reg_err:
                _LOGGER.debug("Could not read registries for user command center fallback: %s", reg_err)

        valid_eids = {
            e["entity_id"]
            for e in entities_list
            if e.get("entity_id")
            and not e.get("disabled_by")
            and not e.get("hidden_by")
            and (e.get("state") not in ("unknown", "unavailable", None, "") or e.get("recovered_orphaned_hide"))
        }
        entities_by_id = {e["entity_id"]: e for e in entities_list}
        entities_by_area: dict[str, list[dict[str, Any]]] = {}
        for e in entities_list:
            aid = e.get("area_id")
            if aid:
                entities_by_area.setdefault(aid, []).append(e)

        active_areas = []
        for aid, ainfo in sorted(areas_map.items(), key=lambda kv: str(kv[1].get("name", kv[0])).lower()):
            room_entities = list(entities_by_area.get(aid, []))
            if not room_entities and ainfo.get("entities"):
                for eid in ainfo["entities"]:
                    if eid in entities_by_id:
                        room_entities.append(entities_by_id[eid])
            has_active = any(
                not e.get("disabled_by") and not e.get("hidden_by") and e.get("entity_id") in valid_eids
                for e in room_entities
            )
            has_entities = any(
                not e.get("disabled_by") and not e.get("hidden_by")
                for e in room_entities
            )
            if has_active or has_entities:
                slug = self._slugify(aid)
                active_areas.append({
                    "id": aid,
                    "name": ainfo.get("name") or aid.replace("_", " ").title(),
                    "slug": slug,
                    "entities": room_entities,
                })

        # Main Home View for Users
        user_rules = self._get_user_rules()
        layout_style = user_rules.get("dashboard_layout", "modern_sections")
        cal_view = user_rules.get("calendar_view", "listDay")
        content_focus = user_rules.get("primary_content_focus", "balanced")
        nav_style = user_rules.get("navigation_style", "sleek_buttons")
        button_cols, button_square, icon_height = self._resolve_nav_grid_params(nav_style)
        initial_cal = "dayGridMonth" if cal_view == "month" else ("listDay" if cal_view == "listDay" else cal_view)

        active_studios = self._get_active_studios(capability_map)
        studio_buttons = [
            {
                "type": "button",
                "name": st["name"],
                "icon": st["icon"],
                **({"icon_height": icon_height} if icon_height else {}),
                "tap_action": {"action": "navigate", "navigation_path": f"/{COMMAND_CENTER_DASHBOARD_URL_PATH}/{st['path']}"},
            }
            for st in active_studios
        ]

        # Weather & Calendar Glance cards
        weather_eid = next(
            (e["entity_id"] for e in entities_list if str(e.get("entity_id", "")).startswith("weather.")),
            None,
        )
        if not weather_eid and hasattr(self, "hass") and self.hass and hasattr(self.hass, "states"):
            weather_eid = next(
                (s.entity_id for s in self.hass.states.async_all("weather")), None
            )

        calendar_eids = [
            e["entity_id"] for e in entities_list if str(e.get("entity_id", "")).startswith("calendar.")
        ][:3]
        if not calendar_eids and hasattr(self, "hass") and self.hass and hasattr(self.hass, "states"):
            calendar_eids = [s.entity_id for s in self.hass.states.async_all("calendar")][:3]

        glance_cards = []
        if weather_eid:
            glance_cards.append({
                "type": "weather-forecast",
                "entity": weather_eid,
                "show_current": True,
                "show_forecast": True,
                "forecast_type": "daily",
            })
        if calendar_eids:
            glance_cards.append({
                "type": "calendar",
                "entities": calendar_eids,
                "initial_view": initial_cal,
            })

        room_buttons = [
            {
                "type": "button",
                "name": area["name"],
                "icon": self._get_room_icon(area["name"], area["id"]),
                **({"icon_height": icon_height} if icon_height else {}),
                "tap_action": {"action": "navigate", "navigation_path": f"/command-center/area_{area['slug']}"},
            }
            for area in active_areas
        ]

        # Individual Sections
        studios_sec: dict[str, Any] = {
            "type": "grid",
            **({"column_span": 2} if button_cols >= 3 else {}),
            "cards": [
                {
                    "type": "heading",
                    "heading": "Studios",
                    "icon": "mdi:view-dashboard-outline",
                    "heading_style": "title",
                },
                {
                    "type": "grid",
                    "columns": button_cols,
                    "square": button_square,
                    "cards": studio_buttons,
                },
            ],
        }

        glance_sec = {
            "type": "grid",
            "cards": [
                {
                    "type": "heading",
                    "heading": "Schedule & Glance",
                    "icon": "mdi:calendar-clock",
                    "heading_style": "title",
                },
                *glance_cards,
            ],
        }

        rooms_sec: dict[str, Any] = {
            "type": "grid",
            **({"column_span": 2} if button_cols >= 3 else {}),
            "cards": [
                {
                    "type": "heading",
                    "heading": "Rooms",
                    "icon": "mdi:home-outline",
                    "heading_style": "title",
                },
                {
                    "type": "grid",
                    "columns": button_cols,
                    "square": button_square,
                    "cards": room_buttons,
                },
            ],
        }

        # Order sections strictly according to primary_content_focus
        # Contextual Presence-Based Room Cards (Active Rooms)
        presence_enabled = user_rules.get("presence_room_cards", True)
        active_room_cards = (
            self._build_contextual_presence_room_cards(
                active_areas, entities_by_area, valid_eids, dashboard_url_path=COMMAND_CENTER_DASHBOARD_URL_PATH
            )
            if presence_enabled
            else []
        )
        active_rooms_sec = None
        if active_room_cards:
            active_rooms_sec = {
                "type": "grid",
                "cards": [
                    {
                        "type": "conditional",
                        "conditions": [
                            {
                                "condition": "state",
                                "entity": "binary_sensor.otis_active_occupancy",
                                "state": "on",
                            }
                        ],
                        "card": {
                            "type": "heading",
                            "heading": "Active Rooms",
                            "icon": "mdi:motion-sensor",
                            "heading_style": "title",
                        },
                    },
                    *active_room_cards,
                ],
            }

        people_sec, people_trad_card = self._build_people_and_pets_section(
            user_rules, entities_list, layout_style
        )

        # Order sections strictly respecting primary_content_focus
        if content_focus == "glance_first":
            # Schedule & Weather First -> People & Pets -> Active Rooms (if occupied) -> Studios -> Rooms
            sections = [glance_sec]
            if people_sec:
                sections.append(people_sec)
            if active_rooms_sec:
                sections.append(active_rooms_sec)
            sections.extend([studios_sec, rooms_sec])
        elif content_focus == "studios_first":
            # Studios First -> People & Pets -> Active Rooms -> Rooms -> Schedule & Weather
            sections = [studios_sec]
            if people_sec:
                sections.append(people_sec)
            if active_rooms_sec:
                sections.append(active_rooms_sec)
            sections.extend([rooms_sec, glance_sec])
        else:  # "balanced"
            # Studios Launchpad -> People & Pets -> Schedule & Weather -> Active Rooms -> Rooms
            sections = [studios_sec]
            if people_sec:
                sections.append(people_sec)
            sections.append(glance_sec)
            if active_rooms_sec:
                sections.append(active_rooms_sec)
            sections.append(rooms_sec)

        # Traditional cards list (clean fallback and for tools expecting view.cards)
        active_rooms_card = (
            {
                "type": "grid",
                "title": "Active Rooms",
                "columns": 1,
                "square": False,
                "cards": active_room_cards,
            }
            if active_room_cards
            else None
        )

        markdown_card = {
            "type": "markdown",
            "content": "# 🏠 Home Command Center\nSelect a studio or room below for full interactive control.",
        }
        studios_card = {
            "type": "grid",
            "title": "Studios",
            "columns": button_cols,
            "square": button_square,
            "cards": studio_buttons,
        }
        glance_card = {
            "type": "grid",
            "title": "Glance & Schedule",
            "columns": len(glance_cards),
            "square": False,
            "cards": glance_cards,
        } if glance_cards else None
        rooms_card = {
            "type": "grid",
            "title": "Rooms",
            "columns": button_cols,
            "square": button_square,
            "cards": room_buttons,
        } if room_buttons else None

        home_cards = [markdown_card]
        if content_focus == "glance_first":
            if glance_card:
                home_cards.append(glance_card)
            if people_trad_card:
                home_cards.append(people_trad_card)
            if active_rooms_card:
                home_cards.append(active_rooms_card)
            home_cards.append(studios_card)
            if rooms_card:
                home_cards.append(rooms_card)
        elif content_focus == "studios_first":
            home_cards.append(studios_card)
            if people_trad_card:
                home_cards.append(people_trad_card)
            if active_rooms_card:
                home_cards.append(active_rooms_card)
            if rooms_card:
                home_cards.append(rooms_card)
            if glance_card:
                home_cards.append(glance_card)
        else:  # "balanced"
            home_cards.append(studios_card)
            if people_trad_card:
                home_cards.append(people_trad_card)
            if glance_card:
                home_cards.append(glance_card)
            if active_rooms_card:
                home_cards.append(active_rooms_card)
            if rooms_card:
                home_cards.append(rooms_card)

        home_view: dict[str, Any] = {
            "title": "Home",
            "path": "home",
            "icon": "mdi:home-variant-outline",
            "theme": user_rules.get("theme") or "otis_generate_midnight_slate",
            "badges": [],
        }
        self._apply_view_layout(home_view, home_cards, layout_style, sections=sections)

        views: list[dict[str, Any]] = [home_view]
        for st in active_studios:
            s_key = st["key"]
            if s_key == "floorplan":
                if svg_stat is None:
                    svg_stat = self._get_floorplan_svg_stat_sync()
                s_cards = self._build_floorplan_view_cards(
                    capability_map, dashboard_url_path=COMMAND_CENTER_DASHBOARD_URL_PATH, svg_stat=svg_stat
                )
                views.append(
                    self._build_studio_view(
                        st["name"], st["path"], st["icon"], s_cards, layout_style=layout_style, is_panel=True
                    )
                )
            elif s_key == "energy":
                s_cards = self._build_energy_view_cards(
                    capability_map, dashboard_url_path=COMMAND_CENTER_DASHBOARD_URL_PATH, nav_style=nav_style
                )
                views.append(self._build_studio_view(st["name"], st["path"], st["icon"], s_cards, layout_style=layout_style))
            elif s_key == "media":
                s_cards = self._build_media_view_cards(
                    capability_map,
                    dashboard_url_path=COMMAND_CENTER_DASHBOARD_URL_PATH,
                    nav_style=nav_style,
                    installed_cards=installed_cards,
                )
                views.append(self._build_studio_view(st["name"], st["path"], st["icon"], s_cards, layout_style=layout_style))
            elif s_key == "security":
                s_cards = self._build_security_view_cards(
                    capability_map, dashboard_url_path=COMMAND_CENTER_DASHBOARD_URL_PATH, nav_style=nav_style
                )
                views.append(self._build_studio_view(st["name"], st["path"], st["icon"], s_cards, layout_style=layout_style))
            elif s_key == "climate":
                s_cards = self._build_climate_view_cards(
                    capability_map, dashboard_url_path=COMMAND_CENTER_DASHBOARD_URL_PATH, nav_style=nav_style, layout_style=layout_style
                )
                views.append(self._build_studio_view(st["name"], st["path"], st["icon"], s_cards, layout_style=layout_style))

        for area in active_areas:
            rview = self._build_room_subview(
                area["id"],
                {"name": area["name"]},
                area["entities"],
                valid_eids,
                layout_style=layout_style,
                nav_style=nav_style,
                dashboard_url_path=COMMAND_CENTER_DASHBOARD_URL_PATH,
                capability_map=capability_map,
            )
            if rview:
                views.append(rview)

        return {
            "title": "Command Center",
            "theme": user_rules.get("theme") or "otis_generate_midnight_slate",
            "views": views,
        }

    def _build_otis_companion_dashboard_config(
        self,
        capability_map: dict[str, Any] | None = None,
        installed_cards: set[str] | None = None,
        svg_stat: tuple[bool, int] | None = None,
    ) -> dict[str, Any]:
        """Build the Lovelace config for the Admin-only Otis AI Companion Command Center with Hub-and-Spoke subviews."""
        user_rules = self._get_user_rules()
        layout_style = user_rules.get("dashboard_layout", "modern_sections")
        nav_style = user_rules.get("navigation_style", "sleek_buttons")

        views: list[dict[str, Any]] = [
            {
                "title": "AI Command Center",
                "path": "default_view",
                "icon": "mdi:robot-outline",
                "type": "panel",
                "panel": True,
                "theme": user_rules.get("theme") or "otis_generate_midnight_slate",
                "badges": [],
                "cards": [
                    {
                        "type": "custom:otis-companion-card",
                        "title": "Otis AI Companion",
                        "theme_preset": "ha_native",
                        "show_chat": True,
                        "show_suggestions": True,
                        "show_stats": True,
                        "max_suggestions": 8,
                    }
                ],
            }
        ]

        for st in self._get_active_studios(capability_map):
            s_key = st["key"]
            if s_key == "floorplan":
                if svg_stat is None:
                    svg_stat = self._get_floorplan_svg_stat_sync()
                s_cards = self._build_floorplan_view_cards(
                    capability_map, dashboard_url_path=OTIS_DASHBOARD_URL_PATH, svg_stat=svg_stat
                )
                views.append(
                    self._build_studio_view(
                        st["name"], st["path"], st["icon"], s_cards, layout_style=layout_style, is_panel=True
                    )
                )
            elif s_key == "energy":
                s_cards = self._build_energy_view_cards(
                    capability_map, dashboard_url_path=OTIS_DASHBOARD_URL_PATH, nav_style=nav_style
                )
                views.append(self._build_studio_view(st["name"], st["path"], st["icon"], s_cards, layout_style=layout_style))
            elif s_key == "media":
                s_cards = self._build_media_view_cards(
                    capability_map,
                    dashboard_url_path=OTIS_DASHBOARD_URL_PATH,
                    nav_style=nav_style,
                    installed_cards=installed_cards,
                )
                views.append(self._build_studio_view(st["name"], st["path"], st["icon"], s_cards, layout_style=layout_style))
            elif s_key == "security":
                s_cards = self._build_security_view_cards(
                    capability_map, dashboard_url_path=OTIS_DASHBOARD_URL_PATH, nav_style=nav_style
                )
                views.append(self._build_studio_view(st["name"], st["path"], st["icon"], s_cards, layout_style=layout_style))
            elif s_key == "climate":
                s_cards = self._build_climate_view_cards(
                    capability_map, dashboard_url_path=OTIS_DASHBOARD_URL_PATH, nav_style=nav_style, layout_style=layout_style
                )
                views.append(self._build_studio_view(st["name"], st["path"], st["icon"], s_cards, layout_style=layout_style))

        # 6. Dynamic Area / Room Subviews (/otis-ai/area_<slug>)
        areas_map = capability_map.get("areas", {}) if capability_map else {}
        entities_list = capability_map.get("entities", []) if capability_map else []
        if not areas_map and not entities_list and hasattr(self, "hass") and self.hass:
            try:
                area_reg = ar.async_get(self.hass)
                device_reg = dr.async_get(self.hass)
                entity_reg = er.async_get(self.hass)
                raw_devices = getattr(device_reg, "devices", {})
                device_iter = list(raw_devices.values() if isinstance(raw_devices, dict) else raw_devices)
                dev_areas = {d.id: d.area_id for d in device_iter}
                dev_models = {d.id: getattr(d, "model", None) for d in device_iter}
                areas_map = {a.id: {"name": a.name, "entities": []} for a in area_reg.async_list_areas()}
                raw_entities = getattr(entity_reg, "entities", {})
                entity_iter = list(raw_entities.values() if isinstance(raw_entities, dict) else raw_entities)
                active_switch_targets = self._get_active_switch_as_x_targets(entity_iter)
                for entry in entity_iter:
                    eff_hidden = self._resolve_effective_hidden_by(entry, active_switch_targets)
                    if entry.disabled_by or eff_hidden:
                        continue
                    aid = entry.area_id or dev_areas.get(entry.device_id)
                    st = self.hass.states.get(entry.entity_id) if hasattr(self.hass, "states") else None
                    e_state = st.state if st else "unknown"
                    e_info = {
                        "entity_id": entry.entity_id,
                        "name": entry.name or entry.original_name,
                        "domain": getattr(entry, "domain", None) or entry.entity_id.split(".")[0],
                        "platform": getattr(entry, "platform", None),
                        "device_id": getattr(entry, "device_id", None),
                        "device_model": dev_models.get(getattr(entry, "device_id", None)),
                        "area_id": aid,
                        "disabled_by": entry.disabled_by,
                        "hidden_by": eff_hidden,
                        "state": e_state,
                    }
                    entities_list.append(e_info)
                    if aid and aid in areas_map:
                        areas_map[aid]["entities"].append(entry.entity_id)
            except Exception as reg_err:
                _LOGGER.debug("Could not read registries for companion dashboard fallback: %s", reg_err)

        if areas_map or entities_list:
            valid_eids = {
                e["entity_id"]
                for e in entities_list
                if e.get("entity_id")
                and not e.get("disabled_by")
                and not e.get("hidden_by")
                and (e.get("state") not in ("unknown", "unavailable", None, "") or e.get("recovered_orphaned_hide"))
            }
            entities_by_id = {e["entity_id"]: e for e in entities_list}
            entities_by_area: dict[str, list[dict[str, Any]]] = {}
            for e in entities_list:
                aid = e.get("area_id")
                if aid:
                    entities_by_area.setdefault(aid, []).append(e)

            sorted_areas = sorted(
                areas_map.items(),
                key=lambda kv: str(kv[1].get("name", kv[0])).lower(),
            )
            for aid, ainfo in sorted_areas:
                room_entities = list(entities_by_area.get(aid, []))
                if not room_entities and ainfo.get("entities"):
                    for eid in ainfo["entities"]:
                        if eid in entities_by_id:
                            room_entities.append(entities_by_id[eid])

                room_view = self._build_room_subview(
                    aid,
                    ainfo,
                    room_entities,
                    valid_eids,
                    layout_style=layout_style,
                    nav_style=nav_style,
                    dashboard_url_path=OTIS_DASHBOARD_URL_PATH,
                    capability_map=capability_map,
                )
                if room_view:
                    views.append(room_view)

        return {
            "title": OTIS_DASHBOARD_TITLE,
            "theme": user_rules.get("theme") or "otis_generate_midnight_slate",
            "views": views,
        }

    async def _async_merge_dashboard_config_preserving_user_views(
        self,
        dash_id: str,
        new_config: dict[str, Any],
        force_regenerate: bool = False,
    ) -> dict[str, Any]:
        """Preserve user-customized Home view (view 0) and custom user subviews across updates via executor."""
        storage_dir = self._storage_dir()
        if not storage_dir:
            return new_config
        if hasattr(self.hass, "async_add_executor_job"):
            try:
                return await self.hass.async_add_executor_job(
                    self._merge_dashboard_config_preserving_user_views,
                    storage_dir,
                    dash_id,
                    new_config,
                    force_regenerate,
                )
            except Exception:
                pass
        return self._merge_dashboard_config_preserving_user_views(
            storage_dir, dash_id, new_config, force_regenerate
        )

    def _merge_dashboard_config_preserving_user_views(
        self,
        storage_dir: str | None,
        dash_id: str,
        new_config: dict[str, Any],
        force_regenerate: bool = False,
    ) -> dict[str, Any]:
        """Preserve user-customized Home view (view 0) and custom user subviews across updates, while syncing studios and rooms."""
        if not storage_dir:
            return new_config

        config_file = os.path.join(storage_dir, f"lovelace.{dash_id}")
        existing_views: list[dict[str, Any]] = []
        if os.path.exists(config_file):
            try:
                with open(config_file, encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    existing_data = json.loads(content)
                    if isinstance(existing_data, dict):
                        existing_cfg = existing_data.get("data", {}).get("config") or existing_data.get("config")
                        if isinstance(existing_cfg, dict):
                            existing_views = list(existing_cfg.get("views", []))
            except Exception as err:
                _LOGGER.debug("Could not read existing config for %s: %s", dash_id, err)

        # 1. When updating Command Center, sync customized Studio and Room subviews from the Admin (lovelace.otis_ai) dashboard if present
        if dash_id == COMMAND_CENTER_DASHBOARD_ID and not force_regenerate:
            admin_file = os.path.join(storage_dir, f"lovelace.{OTIS_DASHBOARD_ID}")
            if os.path.exists(admin_file):
                try:
                    with open(admin_file, encoding="utf-8") as af:
                        admin_content = af.read().strip()
                    if admin_content:
                        admin_data = json.loads(admin_content)
                        admin_cfg = admin_data.get("data", {}).get("config", {}) or admin_data.get("config", {})
                        admin_views = admin_cfg.get("views", [])
                        admin_views_by_path = {
                            v.get("path"): v
                            for v in admin_views
                            if v.get("path") and v.get("path") != "default_view"
                        }

                        def _rewrite_to_command_center(obj: Any) -> Any:
                            if isinstance(obj, str):
                                return obj.replace(
                                    f"/{OTIS_DASHBOARD_URL_PATH}/",
                                    f"/{COMMAND_CENTER_DASHBOARD_URL_PATH}/",
                                )
                            elif isinstance(obj, dict):
                                return {k: _rewrite_to_command_center(v) for k, v in obj.items()}
                            elif isinstance(obj, list):
                                return [_rewrite_to_command_center(elem) for elem in obj]
                            return obj

                        synced_views = []
                        for nv in new_config.get("views", []):
                            vpath = nv.get("path")
                            if vpath in admin_views_by_path:
                                cloned_view = _rewrite_to_command_center(
                                    copy.deepcopy(admin_views_by_path[vpath])
                                )
                                synced_views.append(cloned_view)
                            else:
                                synced_views.append(nv)
                        new_config = dict(new_config)
                        new_config["views"] = synced_views
                except Exception as sync_err:
                    _LOGGER.debug(
                        "Could not inherit admin studio/room customizations for command-center: %s",
                        sync_err,
                    )

        if not existing_views:
            return new_config

        try:
            new_views = list(new_config.get("views", []))
            existing_home_view = existing_views[0] if existing_views else None

            if existing_home_view and new_views:
                if dash_id == COMMAND_CENTER_DASHBOARD_ID:
                    # For Command Center home view:
                    # Keep user's custom cards while always syncing the updated Studios, Glance & Schedule, and Rooms grids
                    fresh_cards = new_views[0].get("cards", [])
                    fresh_titles = {c.get("title") for c in fresh_cards}
                    merged_home_cards = list(fresh_cards)

                    # Preserve existing core sections if new_config is missing them (e.g. during offline startup)
                    for ex_card in existing_home_view.get("cards", []):
                        if not isinstance(ex_card, dict):
                            continue
                        c_title = ex_card.get("title")
                        if c_title in ("Glance & Schedule", "Rooms") and c_title not in fresh_titles and not force_regenerate:
                            merged_home_cards.append(ex_card)
                        elif c_title not in ("Studios", "Glance & Schedule", "Rooms", "Active Rooms"):
                            if not (ex_card.get("type") == "markdown" and "Home Command Center" in str(ex_card.get("content", ""))):
                                if not (ex_card.get("type") == "grid" and any(b.get("name") == "Floor Plan" for b in ex_card.get("cards", []))):
                                    merged_home_cards.append(ex_card)

                    merged_home = dict(existing_home_view)
                    if "theme" in new_views[0] and ("theme" not in merged_home or force_regenerate):
                        merged_home["theme"] = new_views[0]["theme"]
                    if new_views[0].get("type") == "sections" and "sections" in new_views[0]:
                        merged_home["type"] = "sections"
                        merged_home["max_columns"] = new_views[0].get("max_columns", 3)
                        merged_home["sections"] = list(new_views[0]["sections"])
                    else:
                        merged_home.pop("type", None)
                        merged_home.pop("sections", None)
                        merged_home.pop("max_columns", None)
                    merged_home["cards"] = merged_home_cards
                    new_views[0] = merged_home
                else:
                    # For Admin dashboard: preserve user's customized Otis AI Companion card settings in view 0
                    new_views[0] = existing_home_view
            elif existing_home_view:
                new_views = [existing_home_view]

            # Helper to merge a freshly generated view into an existing view, preserving all user card customizations
            def _merge_view_preserving_cards(ex_v: dict[str, Any], fresh_v: dict[str, Any]) -> dict[str, Any]:
                def _c_key(c: Any) -> str:
                    if not isinstance(c, dict):
                        return str(c)
                    if c.get("type") == "custom:otis-companion-card":
                        return f"custom:otis-companion-card::{c.get('mode') or ''}::{c.get('area_id') or ''}"
                    return f"{c.get('type')}::{c.get('title') or c.get('name') or ''}::{c.get('entity', '')}"

                if force_regenerate:
                    # Start with fresh view topology (updated cameras, clean high-draw lists, navigation)
                    # while preserving user-configured custom cards and manually added cards/sections.
                    merged_v = copy.deepcopy(fresh_v)

                    # Collect user-customized cards from both existing cards and sections
                    ex_custom_by_type_ent: dict[str, dict[str, Any]] = {}
                    ex_custom_by_type: dict[str, dict[str, Any]] = {}

                    def _collect_existing(card_list: list[Any]) -> None:
                        for c in card_list:
                            if not isinstance(c, dict):
                                continue
                            ct = str(c.get("type", ""))
                            if ct == "heading":
                                continue
                            if ct in ("grid", "vertical-stack", "horizontal-stack") and isinstance(c.get("cards"), list):
                                _collect_existing(c["cards"])
                            if ct.startswith("custom:") or ct in ("media-control", "thermostat", "alarm-panel"):
                                ent = str(c.get("entity", ""))
                                key = f"{ct}::{ent}"
                                prev = ex_custom_by_type_ent.get(key)
                                if prev is None or len(c) > len(prev):
                                    ex_custom_by_type_ent[key] = c
                                prev_t = ex_custom_by_type.get(ct)
                                if prev_t is None or len(c) > len(prev_t):
                                    ex_custom_by_type[ct] = c

                    _collect_existing(ex_v.get("cards", []))
                    for sec in ex_v.get("sections", []):
                        if isinstance(sec, dict):
                            _collect_existing(sec.get("cards", []))

                    def _restore_custom_configs(card_list: list[Any]) -> list[Any]:
                        out = []
                        for c in card_list:
                            if not isinstance(c, dict):
                                out.append(c)
                                continue
                            ct = str(c.get("type", ""))
                            ent = str(c.get("entity", ""))
                            if f"{ct}::{ent}" in ex_custom_by_type_ent:
                                out.append(copy.deepcopy(ex_custom_by_type_ent[f"{ct}::{ent}"]))
                            elif ct.startswith("custom:") and not ent and ct in ex_custom_by_type:
                                out.append(copy.deepcopy(ex_custom_by_type[ct]))
                            elif ct in ("grid", "vertical-stack", "horizontal-stack") and isinstance(c.get("cards"), list):
                                c_copy = dict(c)
                                c_copy["cards"] = _restore_custom_configs(c["cards"])
                                out.append(c_copy)
                            else:
                                out.append(c)
                        return out

                    if "cards" in merged_v and isinstance(merged_v["cards"], list):
                        merged_v["cards"] = _restore_custom_configs(merged_v["cards"])
                    if "sections" in merged_v and isinstance(merged_v["sections"], list):
                        for sec in merged_v["sections"]:
                            if isinstance(sec, dict) and isinstance(sec.get("cards"), list):
                                sec["cards"] = _restore_custom_configs(sec["cards"])
                    return merged_v

                merged_v = dict(ex_v)
                for prop in ("title", "icon", "theme", "type", "sections", "max_columns", "subview", "visible"):
                    if prop in ex_v:
                        merged_v[prop] = ex_v[prop]
                    elif prop in fresh_v:
                        merged_v[prop] = fresh_v[prop]

                def _is_obsolete(c: Any) -> bool:
                    if not isinstance(c, dict):
                        return False
                    return c.get("type") == "markdown" and "Room controls and live telemetry" in str(c.get("content", ""))

                ex_cards: list[Any] = []
                seen_otis_cards: set[str] = set()
                for c in ex_v.get("cards", []):
                    if _is_obsolete(c):
                        continue
                    if isinstance(c, dict) and c.get("type") == "custom:otis-companion-card":
                        ok = _c_key(c)
                        if ok in seen_otis_cards:
                            continue
                        seen_otis_cards.add(ok)
                    ex_cards.append(c)
                fresh_cards = [c for c in fresh_v.get("cards", []) if not _is_obsolete(c)]
                if not ex_cards:
                    merged_v["cards"] = fresh_cards
                    if merged_v.get("type") == "sections":
                        merged_v["sections"] = self._convert_cards_to_sections(fresh_cards)
                    return merged_v

                ex_keys = {_c_key(c) for c in ex_cards}
                merged_cards = list(ex_cards)

                # Add any freshly generated cards for new integrations/entities that didn't exist in existing view
                for fc in fresh_cards:
                    if not isinstance(fc, dict):
                        continue
                    fc_key = _c_key(fc)
                    fc_type_title = f"{fc.get('type')}::{fc.get('title') or fc.get('name') or ''}"
                    has_match = (fc_key in ex_keys) or any(
                        fc_type_title == f"{ec.get('type')}::{ec.get('title') or ec.get('name') or ''}"
                        for ec in ex_cards
                        if isinstance(ec, dict) and (fc.get("title") or fc.get("name"))
                    )
                    if not has_match:
                        merged_cards.append(fc)

                merged_v["cards"] = merged_cards
                if merged_v.get("type") == "sections" and fresh_cards:
                    merged_v["sections"] = self._convert_cards_to_sections(merged_cards)
                elif "sections" in merged_v and isinstance(merged_v["sections"], list):
                    for sec in merged_v["sections"]:
                        if isinstance(sec, dict) and isinstance(sec.get("cards"), list):
                            sec["cards"] = [c for c in sec["cards"] if not _is_obsolete(c)]
                return merged_v

            # Merge Studio and Room subviews preserving user customizations
            existing_subviews_by_path = {
                str(v.get("path", "")): v
                for v in existing_views[1:]
                if v.get("path")
            }

            for idx in range(1, len(new_views)):
                nv = new_views[idx]
                vpath = str(nv.get("path", ""))
                if vpath and vpath in existing_subviews_by_path:
                    new_views[idx] = _merge_view_preserving_cards(existing_subviews_by_path[vpath], nv)

            # Preserve any custom user-created subviews not generated by Otis AI
            for ex_v in existing_views[1:]:
                v_path = str(ex_v.get("path", ""))
                if not v_path:
                    continue
                if not any(str(nv.get("path", "")) == v_path for nv in new_views):
                    new_views.append(ex_v)

            merged = dict(new_config)
            if "theme" in new_config and ("theme" not in merged or force_regenerate):
                merged["theme"] = new_config["theme"]
            merged["views"] = new_views
            return merged
        except Exception as err:
            _LOGGER.debug("Could not merge existing dashboard views for %s: %s", dash_id, err)
            return new_config

    async def _async_register_and_save_dashboard(
        self,
        item: dict[str, Any],
        dashboard_config: dict[str, Any],
        overwrite_config: bool = True,
        force_regenerate: bool = False,
    ) -> dict[str, Any]:
        """Persist dashboard metadata via DashboardsCollection + LovelaceStorage and register live HA panel."""
        dash_id = item["id"]
        url_path = item["url_path"]
        self._managed_dashboards[url_path] = dict(item)

        # Preserve user's card settings in view 0 before saving
        merged_dashboard_config = await self._async_merge_dashboard_config_preserving_user_views(
            dash_id, dashboard_config, force_regenerate
        )

        # 1. Update or create dashboard in official DashboardsCollection
        storage_col = self._get_dashboards_collection()
        if storage_col is not None:
            try:
                col_data = getattr(storage_col, "data", {})
                existing_key = None
                if isinstance(col_data, dict):
                    for k, v in col_data.items():
                        if k == dash_id or (isinstance(v, dict) and (v.get("id") == dash_id or v.get("url_path") == url_path)):
                            existing_key = k
                            break
                if existing_key is not None:
                    if hasattr(storage_col, "async_update_item"):
                        await storage_col.async_update_item(existing_key, {
                            "title": item.get("title", url_path),
                            "icon": item.get("icon", "mdi:view-dashboard"),
                            "require_admin": bool(item.get("require_admin", True)),
                            "show_in_sidebar": bool(item.get("show_in_sidebar", True)),
                        })
                    elif hasattr(storage_col, "data") and isinstance(storage_col.data, dict):
                        storage_col.data[existing_key] = {**storage_col.data[existing_key], **item}
                        if hasattr(storage_col, "_async_schedule_save"):
                            storage_col._async_schedule_save()
                else:
                    if hasattr(storage_col, "async_create_item"):
                        await storage_col.async_create_item({
                            "url_path": url_path,
                            "title": item.get("title", url_path),
                            "icon": item.get("icon", "mdi:view-dashboard"),
                            "require_admin": bool(item.get("require_admin", True)),
                            "show_in_sidebar": bool(item.get("show_in_sidebar", True)),
                            "mode": "storage",
                        })
                    elif hasattr(storage_col, "data") and isinstance(storage_col.data, dict):
                        storage_col.data[dash_id] = dict(item)
                        if hasattr(storage_col, "_async_schedule_save"):
                            storage_col._async_schedule_save()
            except Exception as col_err:
                _LOGGER.debug("DashboardsCollection update handled: %s", col_err)

        # 2. Save dashboard configuration via LovelaceStorage or Store
        saved_via_lovelace = False
        try:
            from homeassistant.components import frontend
            from homeassistant.components.lovelace import dashboard as ll_dashboard

            lovelace_data = None
            if hasattr(self.hass, "data") and isinstance(self.hass.data, dict):
                for k, v in self.hass.data.items():
                    if str(k) == "lovelace" or getattr(v, "dashboards", None) is not None:
                        if hasattr(v, "dashboards") and isinstance(v.dashboards, dict):
                            lovelace_data = v
                            break

            if lovelace_data is not None:
                if url_path not in lovelace_data.dashboards:
                    lovelace_data.dashboards[url_path] = ll_dashboard.LovelaceStorage(
                        self.hass, item
                    )
                else:
                    lovelace_data.dashboards[url_path].config = item

                if overwrite_config:
                    current_cfg = getattr(lovelace_data.dashboards[url_path], "config", None)
                    is_changed = True
                    try:
                        cur_str = json.dumps(current_cfg, sort_keys=True) if current_cfg else ""
                        new_str = json.dumps(merged_dashboard_config, sort_keys=True)
                        if cur_str and cur_str == new_str:
                            is_changed = False
                    except Exception:
                        pass

                    if is_changed:
                        try:
                            await lovelace_data.dashboards[url_path].async_save(merged_dashboard_config)
                            saved_via_lovelace = True
                        except Exception as save_err:
                            _LOGGER.debug("LovelaceStorage.async_save skipped: %s", save_err)
                        try:
                            self.hass.bus.async_fire("lovelace_updated", {"url_path": url_path})
                        except Exception:
                            pass

            if hasattr(frontend, "async_register_built_in_panel"):
                frontend.async_register_built_in_panel(
                    self.hass,
                    "lovelace",
                    frontend_url_path=url_path,
                    require_admin=bool(item.get("require_admin", True)),
                    show_in_sidebar=bool(item.get("show_in_sidebar", True)),
                    sidebar_title=item.get("title", url_path),
                    sidebar_icon=item.get("icon", "mdi:view-dashboard"),
                    config={"mode": "storage"},
                    update=True,
                )
        except Exception as err:
            _LOGGER.debug("Live Lovelace panel registration handled: %s", err)

        if not saved_via_lovelace and overwrite_config:
            # Direct Store save fallback when Lovelace component is not in memory
            try:
                cfg_store = Store(self.hass, 1, f"lovelace.{dash_id}")
                await cfg_store.async_save({"config": merged_dashboard_config})
            except Exception as store_err:
                _LOGGER.debug("Fallback Store save for lovelace.%s: %s", dash_id, store_err)

        return {
            "success": True,
            "id": dash_id,
            "url_path": url_path,
            "title": item.get("title"),
            "require_admin": bool(item.get("require_admin", True)),
        }

    async def async_analyze_dashboard_gaps(
        self, capability_map: dict[str, Any]
    ) -> dict[str, Any]:
        """Inspect existing Lovelace dashboards via collection and memory to identify control gaps."""
        existing_dashboards: list[dict[str, Any]] = []

        storage_col = self._get_dashboards_collection()
        if storage_col is not None and hasattr(storage_col, "data") and isinstance(storage_col.data, dict):
            for _k, v in storage_col.data.items():
                if isinstance(v, dict):
                    existing_dashboards.append(v)

        if hasattr(self.hass, "data") and isinstance(self.hass.data, dict):
            ll_data = self.hass.data.get("lovelace")
            if ll_data is not None and hasattr(ll_data, "dashboards") and isinstance(ll_data.dashboards, dict):
                for dash_obj in ll_data.dashboards.values():
                    cfg = getattr(dash_obj, "config", None)
                    if isinstance(cfg, dict) and cfg not in existing_dashboards:
                        existing_dashboards.append(cfg)

        for m_cfg in self._managed_dashboards.values():
            if m_cfg not in existing_dashboards:
                existing_dashboards.append(m_cfg)

        existing_url_paths = {d.get("url_path", "") for d in existing_dashboards}
        existing_ids = {d.get("id", "") for d in existing_dashboards}
        existing_titles_lower = {str(d.get("title", "")).lower() for d in existing_dashboards}

        referenced_entities: set[str] = set()
        if hasattr(self.hass, "data") and isinstance(self.hass.data, dict):
            ll_data = self.hass.data.get("lovelace")
            if ll_data is not None and hasattr(ll_data, "dashboards") and isinstance(ll_data.dashboards, dict):
                for dash_obj in ll_data.dashboards.values():
                    d_data = getattr(dash_obj, "_data", None)
                    if isinstance(d_data, dict):
                        for match in re.findall(r"\b[a-z_]+\.[a-z0-9_]+\b", json.dumps(d_data)):
                            referenced_entities.add(match)

        proposals: list[dict[str, Any]] = []
        entities = capability_map.get("entities", [])
        media_topo = capability_map.get("media_topology", {})
        sec_topo = capability_map.get("security_topology", {})

        # 1. Whole-Home Matrix Audio & Cinema Studio Dashboard
        matrix_zones = media_topo.get("matrix_zones", [])
        if (
            media_topo.get("matrix_amp_detected")
            and "otis-media-studio" not in existing_url_paths
            and "otis_media_studio" not in existing_ids
            and not any("media studio" in t or "matrix audio" in t for t in existing_titles_lower)
        ):
            uncontrolled_zones = [
                z["entity_id"]
                for z in matrix_zones
                if z["entity_id"] not in referenced_entities
            ]
            proposals.append({
                "id": "pro_dashboard_matrix_media_studio",
                "dashboard_id": "otis_media_studio",
                "url_path": "otis-media-studio",
                "title": "Create Pro Dashboard: Whole-Home Matrix Audio & Cinema Studio",
                "dashboard_title": "Media Studio",
                "icon": "mdi:speaker-multiple",
                "require_admin": False,
                "priority": "high" if uncontrolled_zones else "medium",
                "description": (
                    f"Detected {len(matrix_zones)} Control4 Matrix Amp zones, upstream streamer bridges, and "
                    f"Cinema displays without a dedicated multi-zone audio routing dashboard. Creates a professional "
                    "Media Studio dashboard with room zone sliders, bridge source pickers, and Theater controls."
                ),
                "template": "media_studio",
            })

        # 2. Unified Security, Locks, Cameras & Watchdog Command Center Dashboard
        locks = sec_topo.get("locks", [])
        alarm_panels = sec_topo.get("alarm_panels", [])
        cameras = sec_topo.get("cameras", [])
        if (
            (alarm_panels or locks or cameras)
            and "otis-security-center" not in existing_url_paths
            and "otis_security_center" not in existing_ids
            and not any("security" in t for t in existing_titles_lower)
        ):
            proposals.append({
                "id": "pro_dashboard_security_command",
                "dashboard_id": "otis_security_center",
                "url_path": "otis-security-center",
                "title": "Create Pro Dashboard: Security, Locks & Perimeter Command Center",
                "dashboard_title": "Security Center",
                "icon": "mdi:shield-home",
                "require_admin": True,
                "priority": "medium",
                "description": (
                    f"Fills a dashboard control gap for your {len(alarm_panels)} alarm panel(s), {len(locks)} smart locks, "
                    f"{len(sec_topo.get('garage_covers', []))} garage doors, and {len(cameras)} cameras with an Admin-protected "
                    "Security & Perimeter Command Center."
                ),
                "template": "security_center",
            })

        # 3. Climate, Pool & Energy Operations Dashboard
        climates = [e["entity_id"] for e in entities if e.get("domain") == "climate"]
        fans = [e["entity_id"] for e in entities if e.get("domain") == "fan"]
        has_pool_for_pro = self._has_pool_entities(capability_map)
        climate_pro_title = "Climate & Pool" if has_pool_for_pro else "Climate"
        if (
            len(climates) >= 2
            and "otis-climate-energy" not in existing_url_paths
            and "otis_climate_energy" not in existing_ids
            and not any("climate" in t or "pool" in t for t in existing_titles_lower)
        ):
            proposals.append({
                "id": "pro_dashboard_climate_pool_energy",
                "dashboard_id": "otis_climate_energy",
                "url_path": "otis-climate-energy",
                "title": f"Create Pro Dashboard: {climate_pro_title} & Comfort Operations",
                "dashboard_title": climate_pro_title,
                "icon": "mdi:thermostat-box",
                "require_admin": False,
                "priority": "medium",
                "description": (
                    f"Detected {len(climates)} climate zones{'/pool heaters' if has_pool_for_pro else ''} and {len(fans)} fans without a dedicated "
                    f"environmental dashboard. Generates a professional {climate_pro_title} control dashboard."
                ),
                "template": "climate_energy",
            })

        # 4. Whole-Home Multi-Room Hub Dashboard
        areas_map = capability_map.get("areas", {})
        active_areas = [
            aid
            for aid, ainfo in areas_map.items()
            if any(e.get("area_id") == aid for e in entities) or ainfo.get("entities")
        ]
        if (
            len(active_areas) >= 3
            and "otis-whole-home" not in existing_url_paths
            and "otis_whole_home" not in existing_ids
            and not any("whole home" in t or "rooms" in t for t in existing_titles_lower)
        ):
            proposals.append({
                "id": "pro_dashboard_whole_home_hub",
                "dashboard_id": "otis_whole_home",
                "url_path": "otis-whole-home",
                "title": "Create Pro Dashboard: Whole-Home Multi-Room Hub",
                "dashboard_title": "Whole Home",
                "icon": "mdi:home-group",
                "require_admin": False,
                "priority": "medium",
                "description": (
                    f"Detected {len(active_areas)} active rooms and areas. Creates a unified Whole-Home Multi-Room "
                    "Hub with room navigation cards and dedicated room subviews for lighting, climate, media, and sensors."
                ),
                "template": "whole_home",
            })

        return {
            "existing_dashboards": existing_dashboards,
            "referenced_entities_count": len(referenced_entities),
            "proposals": proposals,
        }

    async def async_create_professional_dashboard(
        self, payload: dict[str, Any], capability_map: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate and register a professional multi-view Lovelace dashboard from a template."""
        url_path = payload.get("url_path", "otis-pro-dashboard")
        dash_id = payload.get("dashboard_id") or url_path.replace("-", "_")
        title = payload.get("dashboard_title") or payload.get("title") or "Otis Pro"
        icon = payload.get("icon", "mdi:view-dashboard-variant")
        require_admin = bool(payload.get("require_admin", False))
        template = payload.get("template", "media_studio")

        installed_cards = await self.async_get_available_custom_cards(
            capability_map.get("integrations", []) if capability_map else None
        )
        config = self._generate_template_config(
            template, title, capability_map, url_path=url_path, installed_cards=installed_cards
        )
        item = {
            "id": dash_id,
            "url_path": url_path,
            "title": title,
            "icon": icon,
            "require_admin": require_admin,
            "show_in_sidebar": True,
            "mode": "storage",
        }
        return await self._async_register_and_save_dashboard(
            item=item,
            dashboard_config=config,
            overwrite_config=True,
        )

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert text to URL/path-safe slug."""
        s = re.sub(r"[^a-zA-Z0-9_]+", "_", text.lower()).strip("_")
        return s or "room"

    def _get_room_icon(self, area_name: str, area_id: str) -> str:
        """Return a contextual MDI icon for a given room name or area ID."""
        key = f"{area_name} {area_id}".lower()
        if any(w in key for w in ("office", "study", "desk", "work")):
            return "mdi:desk"
        if any(w in key for w in ("theater", "cinema", "media")):
            return "mdi:theater"
        if any(w in key for w in ("backyard", "patio", "deck", "yard", "garden")):
            return "mdi:tree"
        if any(w in key for w in ("frontyard", "driveway", "porch")):
            return "mdi:home-export-outline"
        if any(w in key for w in ("master bath",)):
            return "mdi:shower-head"
        if any(w in key for w in ("bath", "restroom", "powder", "shower")):
            return "mdi:shower"
        if any(w in key for w in ("gym", "fitness", "workout")):
            return "mdi:dumbbell"
        if any(w in key for w in ("garage", "workshop")):
            return "mdi:garage"
        if any(w in key for w in ("great room", "living", "family", "lounge")):
            return "mdi:sofa"
        if any(w in key for w in ("master", "bed", "guest")):
            return "mdi:bed"
        if any(w in key for w in ("kitchen",)):
            return "mdi:countertop"
        if any(w in key for w in ("dining",)):
            return "mdi:silverware-fork-knife"
        if any(w in key for w in ("laundry", "mudroom")):
            return "mdi:washing-machine"
        if any(w in key for w in ("hallway", "corridor", "hall")):
            return "mdi:wall-sconce-flat"
        if any(w in key for w in ("foyer", "entry")):
            return "mdi:door"
        if any(w in key for w in ("pool", "spa")):
            return "mdi:pool"
        if any(w in key for w in ("closet", "wardrobe")):
            return "mdi:wardrobe"
        return "mdi:door-open"

    def _build_contextual_presence_room_cards(
        self,
        active_areas: list[dict[str, Any]],
        entities_by_area: dict[str, list[dict[str, Any]]],
        valid_eids: set[str],
        dashboard_url_path: str = COMMAND_CENTER_DASHBOARD_URL_PATH,
    ) -> list[dict[str, Any]]:
        """Build dynamic Lovelace conditional room cards that elevate active/occupied rooms to the top."""
        conditional_cards: list[dict[str, Any]] = []

        for area in active_areas:
            aid = area["id"]
            slug = area["slug"]
            aname = area["name"]
            room_entities = list(entities_by_area.get(aid, []))
            if not room_entities and area.get("entities"):
                room_entities = list(area["entities"])

            # Check for presence or motion sensor in this room
            presence_eids = [
                e["entity_id"]
                for e in room_entities
                if e.get("entity_id")
                and (
                    e["entity_id"].startswith("binary_sensor.")
                    and any(
                        k in e["entity_id"].lower()
                        for k in ("motion", "occupancy", "presence", "mmwave", "radar", "fp1", "fp2", "screek")
                    )
                )
            ]

            # Also check if fused presence sensor exists in live state machine
            fused_presence_eid = f"binary_sensor.otis_presence_{slug}"
            has_fused = False
            if hasattr(self, "hass") and self.hass and hasattr(self.hass, "states"):
                st = self.hass.states.get(fused_presence_eid)
                if st is not None and not hasattr(st, "_mock_return_value") and hasattr(st, "state") and getattr(st, "state", None) in ("on", "off"):
                    has_fused = True

            if not presence_eids and not has_fused:
                continue

            # Target presence condition entity (prefer fused sensor, fallback to native)
            target_presence_eid = fused_presence_eid if has_fused else presence_eids[0]

            # Select high-utility room controls (primary light, media, climate, fan)
            control_ents = self._select_intelligent_room_controls(
                room_entities,
                valid_eids,
                area_name=aname,
                area_id=aid,
                max_controls=2,
            )

            control_cards = []
            for c_info in control_ents:
                c_eid = c_info.get("entity") or c_info.get("entity_id")
                if not c_eid:
                    continue
                c_dom = c_info.get("domain", c_eid.split(".")[0] if c_eid else "")
                if c_dom == "light":
                    control_cards.append({
                        "type": "tile",
                        "entity": c_eid,
                        "features": [{"type": "light-brightness"}],
                    })
                elif c_dom == "climate":
                    control_cards.append({
                        "type": "tile",
                        "entity": c_eid,
                    })
                elif c_dom in ("media_player", "fan", "switch", "cover", "lock"):
                    control_cards.append({
                        "type": "tile",
                        "entity": c_eid,
                    })

            room_icon = self._get_room_icon(aname, aid)
            inner_cards: list[dict[str, Any]] = [
                {
                    "type": "heading",
                    "heading": f"{aname}",
                    "icon": room_icon,
                    "heading_style": "subtitle",
                    "tap_action": {
                        "action": "navigate",
                        "navigation_path": f"/{dashboard_url_path}/area_{slug}",
                    },
                }
            ]

            if control_cards:
                inner_cards.append({
                    "type": "grid",
                    "columns": min(2, len(control_cards)),
                    "square": False,
                    "cards": control_cards,
                })

            inner_cards.append({
                "type": "button",
                "name": f"Full {aname} Controls →",
                "icon": "mdi:arrow-right-circle-outline",
                "tap_action": {
                    "action": "navigate",
                    "navigation_path": f"/{dashboard_url_path}/area_{slug}",
                },
            })

            conditional_cards.append({
                "type": "conditional",
                "conditions": [
                    {
                        "condition": "state",
                        "entity": target_presence_eid,
                        "state": "on",
                    }
                ],
                "card": {
                    "type": "vertical-stack",
                    "cards": inner_cards,
                },
            })

        return conditional_cards

    def _select_intelligent_room_controls(
        self,
        room_ents: list[dict[str, Any]],
        valid_eids: set[str],
        area_name: str = "",
        area_id: str = "",
        max_controls: int = 3,
    ) -> list[dict[str, Any]]:
        """Select up to max_controls high-utility, diverse controllable devices for a room on the interactive floor plan."""
        return select_intelligent_room_controls(
            room_ents,
            valid_eids,
            area_name=area_name,
            area_id=area_id,
            max_controls=max_controls,
        )

    def _get_floorplan_svg_stat_sync(self) -> tuple[bool, int]:
        """Check if floorplan SVG exists on disk and return mtime synchronously."""
        if hasattr(self.hass, "config") and hasattr(self.hass.config, "path"):
            try:
                svg_path = self.hass.config.path(f".storage/{DOMAIN}/media/otis_floorplan.svg")
                if os.path.exists(svg_path):
                    return True, int(os.path.getmtime(svg_path))
            except Exception:
                return True, 1
        return False, 0

    async def _async_get_floorplan_svg_stat(self) -> tuple[bool, int]:
        """Check if floorplan SVG exists on disk non-blockingly via executor."""
        if hasattr(self.hass, "async_add_executor_job"):
            try:
                return await self.hass.async_add_executor_job(self._get_floorplan_svg_stat_sync)
            except Exception:
                return False, 0
        return self._get_floorplan_svg_stat_sync()

    def _build_floorplan_view_cards(
        self,
        capability_map: dict[str, Any] | None,
        dashboard_url_path: str = "otis-ai",
        svg_stat: tuple[bool, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Build interactive picture-elements view cards for Floor Plan subview."""
        # 1. Determine if SVG floor plan exists in .storage/otis_ai/media/ and record mtime for cache busting
        if isinstance(svg_stat, (tuple, list)) and len(svg_stat) == 2:
            svg_exists, svg_mtime = svg_stat
        else:
            svg_exists, svg_mtime = self._get_floorplan_svg_stat_sync()

        elements: list[dict[str, Any]] = []

        # Retrieve floorplan parser
        parser = getattr(self, "floorplan_parser", None)
        if parser is None and hasattr(self.hass, "data") and isinstance(self.hass.data, dict):
            otis_data = self.hass.data.get("otis_ai")
            if isinstance(otis_data, dict):
                for v in otis_data.values():
                    if isinstance(v, dict) and "floorplan_parser" in v:
                        parser = v["floorplan_parser"]
                        break
        if parser is None:
            try:
                from .floorplan_parser import FloorplanParser
                parser = FloorplanParser(self.hass)
            except Exception:
                parser = None

        areas_map: dict[str, Any] = {}
        entities_list: list[dict[str, Any]] = []
        if capability_map:
            areas_map = dict(capability_map.get("areas", {}))
            entities_list = list(capability_map.get("entities", []))

        # Fallback to Home Assistant registries if areas_map is empty
        if not areas_map:
            try:
                from homeassistant.helpers import area_registry as ar_helper
                reg = ar_helper.async_get(self.hass)
                for area_entry in reg.async_list_areas():
                    areas_map[area_entry.id] = {
                        "name": area_entry.name,
                        "entities": [],
                    }
            except Exception:
                pass

        valid_eids = {
            e["entity_id"]
            for e in entities_list
            if e.get("entity_id")
            and not e.get("disabled_by")
            and not e.get("hidden_by")
            and (e.get("state") not in ("unknown", "unavailable", None, "") or e.get("recovered_orphaned_hide"))
        }
        entities_by_area: dict[str, list[dict[str, Any]]] = {}
        for e in entities_list:
            aid = e.get("area_id")
            if aid:
                entities_by_area.setdefault(aid, []).append(e)

        layout_by_zone = None
        if parser and areas_map:
            try:
                from .floorplan_parser import classify_area_zone
                zones: dict[str, list[dict[str, Any]]] = {"main": [], "upper": [], "outdoor": []}
                for aid, ainfo in areas_map.items():
                    zt = classify_area_zone(aid, ainfo.get("name", aid))
                    zones[zt].append({
                        "id": aid,
                        "name": ainfo.get("name", aid),
                        "entities": ainfo.get("entities", []),
                        "adjacent_areas": [],
                    })
                layout_by_zone = parser._calculate_orthogonal_layout(zones)
            except Exception as calc_err:
                _LOGGER.debug("Could not calculate layout for picture-elements: %s", calc_err)

        if layout_by_zone and parser:
            try:
                canvas_h = float(parser._get_canvas_height(layout_by_zone))
                deleted_rooms = set()
                if hasattr(parser, "_metadata") and isinstance(parser._metadata, dict):
                    deleted_rooms = set(parser._metadata.get("deleted_rooms", []))

                # Check custom badge coordinates from metadata
                custom_badges_map: dict[str, dict[str, float]] = {}
                deleted_badges_set: set[str] = set()
                if hasattr(parser, "_metadata") and isinstance(parser._metadata, dict):
                    c_layout = parser._metadata.get("custom_layout", {})
                    if isinstance(c_layout, dict) and "badges" in c_layout:
                        for cb in c_layout["badges"]:
                            if isinstance(cb, dict) and cb.get("entity_id"):
                                if cb.get("delete") or cb.get("deleted"):
                                    deleted_badges_set.add(cb["entity_id"])
                                elif "x" in cb and "y" in cb:
                                    custom_badges_map[cb["entity_id"]] = {
                                        "x": float(cb["x"]),
                                        "y": float(cb["y"]),
                                    }

                for _zone, rooms in layout_by_zone.items():
                    for r in rooms:
                        aid = r.get("id")
                        if aid in deleted_rooms:
                            continue

                        room_ents = entities_by_area.get(aid, [])
                        rx = float(r.get("x", 0))
                        ry = float(r.get("y", 0))
                        rw = float(r.get("width", 200))
                        rh = float(r.get("height", 140))
                        slug = self._slugify(aid)
                        rname = str(r.get("name") or aid)
                        is_container = bool(r.get("container_bounds") or r.get("parent_container"))
                        header_y = ry + 34 if is_container else ry + 22

                        # 1. Clickable Room Header Hotspot (navigates directly to room view)
                        est_w = min(max(len(rname) * 9 + 16, 65), int(rw - 48))
                        header_center_x = rx + 14 + (est_w / 2.0)
                        header_center_y = header_y - 6.0
                        elements.append({
                            "type": "image",
                            "image": "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='1' height='1'/>",
                            "title": f"View {rname}",
                            "style": {
                                "top": f"{round(header_center_y / canvas_h * 100, 2)}%",
                                "left": f"{round(header_center_x / 1300.0 * 100, 2)}%",
                                "width": f"{est_w}px",
                                "height": "24px",
                                "cursor": "pointer",
                                "transform": "translate(-50%, -50%)",
                                "-webkit-tap-highlight-color": "transparent",
                            },
                            "tap_action": {
                                "action": "navigate",
                                "navigation_path": f"/{dashboard_url_path}/area_{slug}",
                            },
                        })

                        # 2. Room Navigation Icon (Top-right of room, inset safely from borders & container banners)
                        room_icon = self._get_room_icon(rname, aid)
                        nav_top_y = ry + 38 if is_container else ry + 22
                        nav_left_x = rx + rw - 32
                        elements.append({
                            "type": "icon",
                            "icon": room_icon,
                            "title": rname,
                            "style": {
                                "top": f"{round(nav_top_y / canvas_h * 100, 1)}%",
                                "left": f"{round(nav_left_x / 1300.0 * 100, 1)}%",
                                "color": "#94a3b8",
                                "cursor": "pointer",
                                "pointer-events": "auto",
                                "--mdc-icon-size": "18px",
                            },
                            "tap_action": {
                                "action": "navigate",
                                "navigation_path": f"/{dashboard_url_path}/area_{slug}",
                            },
                        })

                        # 3. Intelligent Entity Controls situated from the center of the room (avoiding text)
                        sub_zones_count = len(r.get("sub_zones") or [])
                        max_ctrls, _ = compute_room_center_pin_positions(
                            rx, ry, rw, rh,
                            count=0,
                            sub_zones_count=sub_zones_count,
                            has_container=is_container,
                        )
                        ctrl_items = self._select_intelligent_room_controls(
                            room_ents,
                            valid_eids,
                            area_name=rname,
                            area_id=aid,
                            max_controls=max_ctrls,
                        )

                        if ctrl_items:
                            visible_ctrls = [c for c in ctrl_items if c["entity"] not in deleted_badges_set]
                            _, center_positions = compute_room_center_pin_positions(
                                rx, ry, rw, rh,
                                count=len(visible_ctrls),
                                sub_zones_count=sub_zones_count,
                                has_container=is_container,
                            )

                            for ctrl, (cx, cy) in zip(visible_ctrls, center_positions, strict=False):
                                eid = ctrl["entity"]
                                if eid in custom_badges_map:
                                    item_left_pct = round(custom_badges_map[eid]["x"] / 1300.0 * 100, 1)
                                    item_top_pct = round(custom_badges_map[eid]["y"] / canvas_h * 100, 1)
                                else:
                                    item_left_pct = round(cx / 1300.0 * 100, 1)
                                    item_top_pct = round(cy / canvas_h * 100, 1)
                                elements.append({
                                    "type": "state-icon",
                                    "entity": eid,
                                    "style": {
                                        "top": f"{item_top_pct}%",
                                        "left": f"{item_left_pct}%",
                                        "--paper-item-icon-active-color": ctrl["color"],
                                        "cursor": "pointer",
                                    },
                                    "tap_action": {"action": ctrl["action"]},
                                })

                # Also include any user-added custom badges that were not in default room controls
                seen_eids = {e.get("entity") for e in elements if e.get("type") == "state-icon"}
                cfg_badge_map = {
                    "light": {"color": "#38bdf8", "action": "toggle"},
                    "switch": {"color": "#a855f7", "action": "toggle"},
                    "media_player": {"color": "#ec4899", "action": "more-info"},
                    "fan": {"color": "#06b6d4", "action": "toggle"},
                    "climate": {"color": "#f97316", "action": "more-info"},
                    "cover": {"color": "#eab308", "action": "toggle"},
                    "lock": {"color": "#10b981", "action": "more-info"},
                    "vacuum": {"color": "#8b5cf6", "action": "more-info"},
                }
                for cb_eid, cb_pos in custom_badges_map.items():
                    if cb_eid not in seen_eids and cb_eid not in deleted_badges_set:
                        cb_left_pct = round(cb_pos["x"] / 1300.0 * 100, 1)
                        cb_top_pct = round(cb_pos["y"] / canvas_h * 100, 1)
                        cb_dom = cb_eid.split(".")[0] if "." in cb_eid else "unknown"
                        cb_color = cfg_badge_map.get(cb_dom, {}).get("color", "#38bdf8")
                        cb_action = cfg_badge_map.get(cb_dom, {}).get("action", "toggle")
                        elements.append({
                            "type": "state-icon",
                            "entity": cb_eid,
                            "style": {
                                "top": f"{cb_top_pct}%",
                                "left": f"{cb_left_pct}%",
                                "--paper-item-icon-active-color": cb_color,
                                "cursor": "pointer",
                            },
                            "tap_action": {"action": cb_action},
                        })
            except Exception as elem_err:
                _LOGGER.debug("Could not build picture-elements room badges: %s", elem_err)

        if not svg_exists:
            return [
                {
                    "type": "markdown",
                    "content": (
                        "## 🗺️ Interactive Architectural Floor Plan\n\n"
                        "Floor plan blueprint not yet generated. Admins can record or upload a video walkthrough "
                        "or generate instantly from Home Assistant areas under the Otis AI Companion card to activate interactive room control."
                    ),
                }
            ]

        user_rules = self._get_user_rules() if hasattr(self, "_get_user_rules") else {}
        if user_rules.get("floorplan_3d") or user_rules.get("floorplan_view_mode") == "3d":
            card_cfg: dict[str, Any] = {
                "type": "custom:otis-companion-card",
                "mode": "floorplan_control",
                "view_mode": "3d",
                "title": "Interactive Floor Plan",
            }
            if "floorplan_azimuth" in user_rules:
                card_cfg["floorplan_azimuth"] = user_rules["floorplan_azimuth"]
            if "floorplan_pitch" in user_rules:
                card_cfg["floorplan_pitch"] = user_rules["floorplan_pitch"]
            if "floorplan_wall_height" in user_rules:
                card_cfg["floorplan_wall_height"] = user_rules["floorplan_wall_height"]
            if "floorplan_walls_enabled" in user_rules:
                card_cfg["floorplan_walls_enabled"] = user_rules["floorplan_walls_enabled"]
            if "floorplan_zone" in user_rules:
                card_cfg["floorplan_zone"] = user_rules["floorplan_zone"]
            if "floorplan_scale" in user_rules:
                card_cfg["floorplan_scale"] = user_rules["floorplan_scale"]
            return [card_cfg]

        image_url = f"/api/otis_ai/media/otis_floorplan.svg?v={svg_mtime}" if svg_mtime else "/api/otis_ai/media/otis_floorplan.svg"
        return [
            {
                "type": "picture-elements",
                "image": image_url,
                "title": "Interactive Floor Plan",
                "elements": elements,
            }
        ]

    def _build_room_subview(
        self,
        area_id: str,
        area_info: dict[str, Any],
        room_entities: list[dict[str, Any]],
        valid_eids: set[str] | None = None,
        layout_style: str | None = None,
        nav_style: str | None = None,
        dashboard_url_path: str = COMMAND_CENTER_DASHBOARD_URL_PATH,
        capability_map: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Build a categorized Room Subview for an area containing active entities."""
        active_entities = [
            e
            for e in room_entities
            if not e.get("disabled_by")
            and not e.get("hidden_by")
            and (valid_eids is None or e.get("entity_id") in valid_eids)
        ]
        if not active_entities:
            return None

        area_name = area_info.get("name") or area_id.replace("_", " ").title()
        slug = self._slugify(area_id)

        user_rules = self._get_user_rules() if (layout_style is None or nav_style is None) else {}
        if layout_style is None:
            layout_style = user_rules.get("dashboard_layout", "modern_sections")
        if nav_style is None:
            nav_style = user_rules.get("navigation_style", "sleek_buttons")

        nav_grid_card = self._build_studio_navigation_card(
            dashboard_url_path=dashboard_url_path,
            nav_style=nav_style,
            capability_map=capability_map,
        )

        room_cards: list[dict[str, Any]] = [
            nav_grid_card,
            {
                "type": "custom:otis-companion-card",
                "mode": "room_view",
                "area_id": area_id,
                "title": f"📍 {area_name}",
            },
        ]

        # 1. Lighting & Semantic Switch Classification
        CAMERA_CONFIG_KEYWORDS = (
            "detect", "motion", "recording", "snapshot", "audio_detection", "infrared",
            "siren", "email_on_event", "ftp_upload", "push_notification", "review_alert",
            "auto_track", "night_vision", "record_audio", "ptz", "hdr", "doorbell_ring",
            "pir_", "smart_detection", "record", "push", "email", "ftp", "review",
            "snapshots", "recordings",
        )
        NETWORK_INFRA_KEYWORDS = (
            "snmp", "switch-", "switch_", "port_", "poe_", "nat_", "filter_rule",
            "service_", "firewall", "router", "gateway", "vlan", "poe", "ethernet",
            "managed_switch", "interface_", "nat_outbound", "filter_rules", "_igc",
            "_lo0", "_tun_", "_gi1_", "_vl", "amazon_kids", "customized_cleaning",
            "auto_dust_collecting", "cleaning_sequence", "super_sleep_pause_mode",
            "no_command_mode", "fan_sleep_mode", "auto_off_enabled", "auto_update_enabled",
        )
        POOL_HVAC_KEYWORDS = (
            "pool", "_spa", "spa_", " spa", "spa ", "pump", "heater", "thermostat",
            "chlorinator", "bubbler", "waterfall", "blower", "cleaner", "filter_cycle",
            "heat_mode", "standby_mode", "hold_mode", "spa_temp", "pool_temp",
            "temperature_range", "spaclient",
        )
        LED_KEYWORDS = ("_led", "ap_", "indicator", "keypad_light", "status_led")
        FAN_SWITCH_KEYWORDS = ("_fan", "fan_", " fan", "fan ", "exhaust", "vent", "ventilat", "blower_fan")
        LIGHT_SWITCH_KEYWORDS = (
            "_light", "light_", " light", "light ", "lamp", "flood", "sconce",
            "chandelier", "lantern", "vanity", "pendant", "recessed", "can_light",
            "porch", "deck_kitchen", "crawl_space", "pathway", "exterior_light",
        )
        WALL_SWITCH_MODELS = ("KS200", "KS205", "HS200", "HS210", "HS220", "KS220", "KS230")
        OUTLET_APPLIANCE_KEYWORDS = (
            "outlet", "plug", "receptacle", "socket", "power_strip", "coffee",
            "melter", "tree", "fireplace", "processor_power", "amp_power", "cubed_ice",
            "fridge", "appliance", "charger",
        )

        lights: list[str] = []
        for e in active_entities:
            if e.get("domain") != "light":
                continue
            if e.get("entity_category") in ("config", "diagnostic"):
                continue
            eid = e.get("entity_id", "").lower()
            name = str(e.get("name") or "").lower()
            if any(k in eid for k in ("_led", "ap_", "status_led", "indicator", "keypad_light", "button_light")) or any(k in name for k in ("led", "indicator")):
                if any(x in eid for x in ("ap_", "poolio", "indicator", "status_led", "keypad")) or any(x in name for x in ("ap ", "poolio", "indicator")):
                    continue
            if "fan speed" in name or (name == "fan" and "light" not in name):
                continue
            lights.append(e["entity_id"])

        switches: list[str] = []
        pool_switches: list[str] = []
        fan_switches: list[str] = []
        for e in active_entities:
            if e.get("domain") != "switch":
                continue
            if e.get("entity_category") in ("config", "diagnostic"):
                continue
            eid = e.get("entity_id", "").lower()
            name = str(e.get("name") or "").lower()
            dev_model = str(e.get("device_model") or "").upper()
            combined = f"{eid} {name}"

            # Check for pool/spa switches (exclude 'space' so crawl_space/workspace never match '_spa')
            combined_pool_check = combined.replace("crawl_space", "").replace("workspace", "").replace("space", "")
            if any(k in combined_pool_check for k in POOL_HVAC_KEYWORDS) and not any(k in combined for k in NETWORK_INFRA_KEYWORDS):
                pool_switches.append(e["entity_id"])
                continue

            if any(k in combined for k in CAMERA_CONFIG_KEYWORDS):
                continue
            if any(k in combined for k in NETWORK_INFRA_KEYWORDS):
                continue
            if any(k in combined for k in LED_KEYWORDS):
                continue

            # Semantically classify fan/exhaust/ventilation switches
            if any(k in combined for k in FAN_SWITCH_KEYWORDS):
                fan_switches.append(e["entity_id"])
                continue

            # Semantically classify lighting switches (_light, lamp, flood, sconce, or wall switch model not marked as outlet)
            is_light_switch = any(k in combined for k in LIGHT_SWITCH_KEYWORDS) or (
                any(dev_model.startswith(m) for m in WALL_SWITCH_MODELS)
                and not any(k in combined for k in OUTLET_APPLIANCE_KEYWORDS)
            )
            if is_light_switch and not any(k in combined for k in ("outlet", "plug", "receptacle")):
                if e["entity_id"] not in lights:
                    lights.append(e["entity_id"])
                continue

            switches.append(e["entity_id"])

        if lights:
            light_cards: list[dict[str, Any]] = []
            for eid in lights:
                if eid.startswith("light."):
                    light_cards.append({
                        "type": "tile",
                        "entity": eid,
                        "features": [{"type": "light-brightness"}],
                    })
                else:
                    light_cards.append({
                        "type": "tile",
                        "entity": eid,
                    })
            room_cards.append({
                "type": "grid",
                "title": "Lighting",
                "columns": min(2, len(light_cards)),
                "square": False,
                "cards": light_cards,
            })

        # 2. Power & Outlets
        if switches:
            room_cards.append({
                "type": "grid",
                "title": "Power & Outlets",
                "columns": min(2, len(switches[:24])),
                "square": False,
                "cards": [{"type": "tile", "entity": eid} for eid in switches[:24]],
            })

        if pool_switches:
            room_cards.append({
                "type": "grid",
                "title": "Pool & Spa Controls",
                "columns": min(2, len(pool_switches[:16])),
                "square": False,
                "cards": [{"type": "tile", "entity": eid} for eid in pool_switches[:16]],
            })

        # 3. Media & Audio (Prominent primary media-control card + compact secondary audio zones)
        media_players = [e["entity_id"] for e in active_entities if e.get("domain") == "media_player"]
        if media_players:
            primary_player = None
            for eid in media_players:
                ent = next((x for x in active_entities if x["entity_id"] == eid), None)
                if ent and ent.get("state") in ("playing", "paused"):
                    primary_player = eid
                    break
            if not primary_player:
                for eid in media_players:
                    if any(k in eid.lower() for k in ("tv", "display", "projector", "receiver", "avr", "amplifier", "soundbar", "theater", "cinema")):
                        primary_player = eid
                        break
            if not primary_player and media_players:
                primary_player = media_players[0]

            secondary_players = [m for m in media_players if m != primary_player][:4]

            # Primary prominent player card
            room_cards.append({
                "type": "media-control",
                "entity": primary_player,
                "title": "Media & Audio",
            })

            # Secondary audio zones
            if secondary_players:
                room_cards.append({
                    "type": "grid",
                    "title": "Other Audio Zones",
                    "columns": min(2, len(secondary_players)),
                    "square": False,
                    "cards": [
                        {
                            "type": "tile",
                            "entity": eid,
                        }
                        for eid in secondary_players
                    ],
                })

        # 4. Climate & Comfort
        climates = [e["entity_id"] for e in active_entities if e.get("domain") == "climate"]
        fans = [e["entity_id"] for e in active_entities if e.get("domain") in ("fan", "humidifier")]
        for f_sw in fan_switches:
            if f_sw not in fans:
                fans.append(f_sw)
        climate_sensors = [
            e["entity_id"]
            for e in active_entities
            if e.get("domain") in ("sensor", "binary_sensor")
            and (
                str((e.get("attributes") or {}).get("device_class", "")).lower()
                in ("temperature", "humidity", "carbon_monoxide", "carbon_dioxide", "pm25", "aqi", "moisture")
                or any(
                    k in e.get("entity_id", "").lower()
                    for k in ("temp", "humidity", "climate", "air_quality", "co2", "aqi")
                )
            )
        ]
        if climates:
            c_cards: list[dict[str, Any]] = []
            is_sections = self._is_sections_layout(layout_style)
            for c_eid in climates:
                if is_sections:
                    c_cards.append({
                        "type": "tile",
                        "entity": c_eid,
                        "features": [
                            {"type": "target-temperature"},
                            {"type": "climate-hvac-modes"},
                        ],
                    })
                else:
                    c_cards.append({
                        "type": "thermostat",
                        "entity": c_eid,
                        "features": [{"type": "climate-hvac-modes"}],
                    })
            if is_sections:
                room_cards.append({
                    "type": "grid",
                    "title": "Climate & Thermostats",
                    "columns": min(2, len(c_cards)),
                    "square": False,
                    "cards": c_cards,
                })
            else:
                room_cards.extend(c_cards)
        if fans:
            room_cards.append({
                "type": "grid",
                "title": "Fans & Air Comfort",
                "columns": min(2, len(fans)),
                "square": False,
                "cards": [{"type": "tile", "entity": eid} for eid in fans],
            })
        if climate_sensors:
            room_cards.append({
                "type": "entities",
                "title": "Environmental Telemetry",
                "state_color": True,
                "entities": climate_sensors[:8],
            })

        # 5. Access & Covers
        locks = [e["entity_id"] for e in active_entities if e.get("domain") == "lock"]
        covers = [e["entity_id"] for e in active_entities if e.get("domain") == "cover"]
        if locks or covers:
            access_tiles: list[dict[str, Any]] = []
            for l_eid in locks:
                access_tiles.append({
                    "type": "tile",
                    "entity": l_eid,
                    "features": [{"type": "lock-commands"}],
                })
            for cov_eid in covers:
                access_tiles.append({
                    "type": "tile",
                    "entity": cov_eid,
                    "features": [{"type": "cover-open-close"}],
                })
            room_cards.append({
                "type": "grid",
                "title": "Access & Covers",
                "columns": min(2, len(access_tiles)),
                "square": False,
                "cards": access_tiles,
            })

        # 6. Cameras (Filter out vacuum cleaning maps and deduplicate multi-stream RTSP cameras)
        VACUUM_MAP_KEYWORDS = ("map", "saved_map", "current_map", "cleaning_map", "vacuum", "floorplan")
        raw_cameras = [e for e in active_entities if e.get("domain") == "camera"]
        camera_groups: dict[str, list[dict[str, Any]]] = {}

        for c in raw_cameras:
            eid = c.get("entity_id", "").lower()
            name = str(c.get("name") or "").lower()
            combined = f"{eid} {name}"
            # Skip vacuum navigation map cameras generically
            if any(k in combined for k in VACUUM_MAP_KEYWORDS):
                continue
            if c.get("device_class") == "map":
                continue

            # Group streams belonging to the same physical camera
            group_key = get_canonical_camera_key(eid)
            camera_groups.setdefault(group_key, []).append(c)

        # Expand camera groups across all system cameras sharing the same canonical key
        # so that if only a secondary/still camera (e.g. Frigate) was assigned to this area,
        # the preferred live stream (e.g. Reolink fluent substream) is selected.
        if camera_groups and hasattr(self, "hass") and self.hass and hasattr(self.hass, "states"):
            try:
                all_cam_states = self.hass.states.async_all("camera")
                for st in all_cam_states:
                    cam_eid = st.entity_id
                    cam_eid_lower = cam_eid.lower()
                    if any(k in cam_eid_lower for k in VACUUM_MAP_KEYWORDS):
                        continue
                    ckey = get_canonical_camera_key(cam_eid_lower)
                    if ckey in camera_groups:
                        if not any(c.get("entity_id", "").lower() == cam_eid_lower for c in camera_groups[ckey]):
                            camera_groups[ckey].append({
                                "entity_id": cam_eid,
                                "name": st.attributes.get("friendly_name", "") if st.attributes else "",
                                "domain": "camera",
                            })
            except Exception:
                pass

        deduped_cameras: list[str] = []
        strategy = self.get_camera_stream_strategy()
        for _gkey, cams in camera_groups.items():
            cams.sort(key=lambda x: stream_priority(
                x.get("entity_id", ""),
                str(x.get("name") or ""),
                strategy=strategy,
                platform=x.get("platform"),
            ))
            deduped_cameras.append(cams[0]["entity_id"])

        if deduped_cameras:
            room_cards.append({
                "type": "grid",
                "title": "Cameras",
                "columns": min(2, len(deduped_cameras[:4])),
                "square": False,
                "cards": [
                    {
                        "type": "picture-entity",
                        "entity": c_eid,
                        "camera_view": "auto",
                        "layout_options": {
                            "grid_columns": 2,
                            "grid_rows": "auto",
                        },
                    }
                    for c_eid in deduped_cameras[:4]
                ],
            })

        # 7. Occupancy & Sensors (Filter out AI object counts, AP connectivity drops, and UPS timer noise)
        EXCLUDE_SENSOR_KEYWORDS = (
            "_count", "person_count", "dog_count", "all_count", "vehicle_count",
            "active_count", "object_count", "sound_level", "noise_level",
            "disconnected", "connection_status", "ping", "latency", "packet",
            "uptime", "shutdown_delay", "reboot_timer", "battery_runtime",
            "ap-", "load_reboot", "ups_shutdown",
        )
        sec_sensors: list[str] = []
        for e in active_entities:
            if e["entity_id"] in climate_sensors:
                continue
            if e.get("entity_category") in ("config", "diagnostic"):
                continue
            if e.get("domain") not in ("binary_sensor", "sensor"):
                continue
            eid = e.get("entity_id", "").lower()
            name = str(e.get("name") or "").lower()
            combined = f"{eid} {name}"

            if any(k in combined for k in EXCLUDE_SENSOR_KEYWORDS):
                continue

            dev_cls = str(e.get("device_class") or (e.get("attributes") or {}).get("device_class") or "").lower()
            is_occupancy_or_perimeter = (
                e.get("domain") == "binary_sensor"
                and (
                    dev_cls in ("motion", "occupancy", "presence", "door", "window", "opening", "garage_door", "lock", "vibration", "tamper", "smoke", "gas", "moisture")
                    or any(k in combined for k in ("motion", "occupancy", "presence", "door", "window", "opening", "contact", "vibration", "front_door"))
                )
            )
            if is_occupancy_or_perimeter:
                sec_sensors.append(e["entity_id"])
            elif e.get("domain") == "binary_sensor" and not dev_cls:
                if not any(k in combined for k in ("status", "update", "state")):
                    sec_sensors.append(e["entity_id"])

        if sec_sensors:
            room_cards.append({
                "type": "entities",
                "title": "Occupancy & Sensors",
                "state_color": True,
                "entities": sec_sensors[:8],
            })

        room_icon = self._get_room_icon(area_name, area_id)
        room_view: dict[str, Any] = {
            "title": area_name,
            "path": f"area_{slug}",
            "icon": room_icon,
            "subview": True,
            "theme": user_rules.get("theme") or "otis_generate_midnight_slate",
            "badges": [],
        }
        return self._apply_view_layout(room_view, room_cards, layout_style)

    def _build_media_view_cards(
        self,
        capability_map: dict[str, Any] | None,
        dashboard_url_path: str = COMMAND_CENTER_DASHBOARD_URL_PATH,
        nav_style: str | None = None,
        installed_cards: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Build cards for Media Studio subview or standalone dashboard."""
        if nav_style is None:
            nav_style = self._get_user_rules().get("navigation_style", "sleek_buttons")
        nav_card = self._build_studio_navigation_card(
            dashboard_url_path=dashboard_url_path, nav_style=nav_style, capability_map=capability_map
        )
        follow_switch_eid = resolve_otis_entity_id(getattr(self, "hass", None), "switch", "audio_follow")
        spatial_sensor_eid = resolve_otis_entity_id(getattr(self, "hass", None), "sensor", "spatial_migration")

        if not capability_map:
            return [
                nav_card,
                {
                    "type": "markdown",
                    "content": (
                        "## 🎵 Whole-Home Media & Matrix Audio\n"
                        "Control upstream streaming bridges, route audio across Matrix Amp room zones, and manage Theater displays."
                    ),
                },
                {
                    "type": "entities",
                    "title": "Autonomous Spatial Audio Follow-Me",
                    "show_header_toggle": False,
                    "entities": [
                        {
                            "entity": follow_switch_eid,
                            "name": "Room-to-Room Audio Follow-Me",
                            "icon": "mdi:cast-connected",
                        },
                        {
                            "entity": spatial_sensor_eid,
                            "name": "Current Audio Follow State",
                            "icon": "mdi:transit-connection-variant",
                        },
                    ],
                },
            ]

        entities = capability_map.get("entities", [])
        media_topo = capability_map.get("media_topology", {})
        valid_eids = {
            e["entity_id"]
            for e in entities
            if e.get("entity_id")
            and not e.get("disabled_by")
            and not e.get("hidden_by")
            and e.get("state") not in ("unknown", "unavailable", None, "")
        }

        def _filter_valid(eid_list: list[str]) -> list[str]:
            if not valid_eids:
                return eid_list
            return [eid for eid in eid_list if eid in valid_eids]

        matrix_zones = _filter_valid([z["entity_id"] if isinstance(z, dict) else str(z) for z in media_topo.get("matrix_zones", [])])
        streamers = _filter_valid([s["entity_id"] if isinstance(s, dict) else str(s) for s in media_topo.get("input_streamers", [])])
        tvs = _filter_valid([
            t["entity_id"] if isinstance(t, dict) else str(t)
            for t in media_topo.get("tv_cinema_zones", [])
            if not any(z in (t.get("entity_id", "") if isinstance(t, dict) else str(t)).lower() for z in ("_zone_3", "_zone_4", "_zone3", "_zone4"))
        ])
        helpers = _filter_valid([
            e["entity_id"]
            for e in entities
            if e.get("entity_id", "").startswith("input_select.media_")
            or e.get("entity_id", "").endswith("_speakers")
        ])

        # Fallback: if no matrix amp or streamers detected, include all discovered media players
        all_mps = _filter_valid([e["entity_id"] for e in entities if e.get("domain") == "media_player"])
        if not matrix_zones and all_mps:
            matrix_zones = [m for m in all_mps if m not in tvs and m not in streamers]

        # Auto-detect available custom Lovelace cards
        detected_cards = installed_cards if installed_cards is not None else self._cached_installed_cards
        has_mmp = "custom:mini-media-player" in detected_cards
        has_remote = "custom:universal-remote-card" in detected_cards

        cards: list[dict[str, Any]] = [
            nav_card,
            {
                "type": "markdown",
                "content": (
                    "## 🎵 Whole-Home Media & Matrix Audio\n"
                    "Control upstream input bridges, route audio across room speaker zones, and manage Theater displays."
                ),
            },
            {
                "type": "entities",
                "title": "Autonomous Spatial Audio Follow-Me",
                "show_header_toggle": False,
                "entities": [
                    {
                        "entity": follow_switch_eid,
                        "name": "Room-to-Room Audio Follow-Me",
                        "icon": "mdi:cast-connected",
                    },
                    {
                        "entity": spatial_sensor_eid,
                        "name": "Current Audio Follow State",
                        "icon": "mdi:transit-connection-variant",
                    },
                ],
            },
        ]

        # 1. Otis Media Studio & Source-to-Zone Matrix Controller (Primary all-in-one matrix, streaming player & zone routing interface)
        cards.append({
            "type": "custom:otis-companion-card",
            "mode": "media_studio",
            "title": "Media Studio & Source-to-Zone Router",
        })

        # 2. Cinema & Room Displays
        if tvs:
            tv_cards = []
            for idx, tv in enumerate(tvs[:6]):
                if idx == 0 and has_remote:
                    tv_cards.append({
                        "type": "custom:universal-remote-card",
                        "entity": tv,
                    })
                elif has_mmp:
                    tv_cards.append({
                        "type": "custom:mini-media-player",
                        "entity": tv,
                        "artwork": "cover",
                        "source": "full",
                    })
                else:
                    tv_cards.append({"type": "tile", "entity": tv})

            cards.append({
                "type": "grid",
                "title": "Cinema & Room Displays",
                "columns": min(2, len(tv_cards)),
                "square": False,
                "cards": tv_cards,
            })

        if not streamers and not matrix_zones and not tvs and not helpers:
            cards.append({
                "type": "markdown",
                "content": (
                    "No media player entities or speakers currently discovered.\n\n"
                    "Once media players, streamers, or displays are added to Home Assistant, "
                    "Otis will automatically configure your soundstage here."
                ),
            })

        return cards

    def _build_energy_view_cards(
        self,
        capability_map: dict[str, Any] | None,
        dashboard_url_path: str = COMMAND_CENTER_DASHBOARD_URL_PATH,
        nav_style: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build cards for Energy Studio subview."""
        if nav_style is None:
            nav_style = self._get_user_rules().get("navigation_style", "sleek_buttons")
        nav_card = self._build_studio_navigation_card(
            dashboard_url_path=dashboard_url_path, nav_style=nav_style, capability_map=capability_map
        )

        if not capability_map:
            return [
                nav_card,
                {
                    "type": "markdown",
                    "content": "⚡ **Energy Studio**: Live telemetry and power sensors will populate when Home Assistant finishes discovery.",
                }
            ]

        energy_topo = capability_map.get("energy_topology", {})
        tariff = energy_topo.get("tariff", {})
        solar = energy_topo.get("solar", {})
        total_w = energy_topo.get("total_power_w", 0)

        entities_list = capability_map.get("entities", [])

        power_eids = [
            e["entity_id"] for e in entities_list
            if (e.get("domain") == "sensor" and e["entity_id"].endswith("_power"))
            or e.get("attributes", {}).get("unit_of_measurement") in ("W", "kW")
        ]
        energy_eids = [
            e["entity_id"] for e in entities_list
            if (e.get("domain") == "sensor" and e["entity_id"].endswith("_energy"))
            or e.get("attributes", {}).get("unit_of_measurement") in ("kWh", "Wh")
        ]
        battery_eids = [
            e["entity_id"] for e in entities_list
            if "battery" in e["entity_id"] or "ups" in e["entity_id"]
        ]
        exclude_power_words = {
            "led", "auto_update", "auto_off", "pre_release", "do_not_disturb",
            "shuffle", "repeat", "amazon_kids", "filter_rule", "carpet_boost",
            "phone", "tablet", "watch", "laptop", "mobile", "wearos", "beacon",
            "ibeacon", "card", "lamp", "hades", "cassette", "allow", "config",
            "bypass", "reset", "diagnostic", "no_command_mode",
        }
        high_draw_tokens = {
            "pump", "compressor", "hvac", "dehumidifier", "evse", "wallbox",
            "pool", "spa", "dryer", "dishwasher", "oven", "stove", "boiler",
        }
        controllable_power_eids: list[str] = []
        for e in entities_list:
            eid = str(e.get("entity_id", ""))
            eid_lower = eid.lower()
            domain = e.get("domain") or eid_lower.split(".", 1)[0]
            if domain not in ("switch", "climate", "water_heater"):
                continue
            tokens = set(re.split(r"[^a-z0-9]+", eid_lower))
            if any(ex in tokens or ex in eid_lower for ex in exclude_power_words):
                continue
            if domain in ("climate", "water_heater"):
                controllable_power_eids.append(eid)
            elif tokens & high_draw_tokens:
                controllable_power_eids.append(eid)
            elif "heater" in tokens and "theater" not in tokens:
                controllable_power_eids.append(eid)
            elif "ev_charger" in eid_lower or "car_charger" in eid_lower:
                controllable_power_eids.append(eid)
            elif any(k in eid_lower for k in ("amp_power", "amplifier_power", "processor_power")):
                controllable_power_eids.append(eid)

        has_solar = solar.get("has_solar_system", False) or solar.get("production_w", 0) > 0
        solar_line = (
            f"• **Solar & Inverter Status**: Production `{solar.get('production_w', 0)} W` | Sun Elevation `{solar.get('solar_elevation_deg', 0)}°`"
            if has_solar
            else f"• **Sun & Solar Position**: Sun Elevation `{solar.get('solar_elevation_deg', 0)}°`"
        )

        cards: list[dict[str, Any]] = [
            nav_card,
            {
                "type": "markdown",
                "content": (
                    f"## ⚡ Otis Energy & Predictive Load Orchestrator\n"
                    f"• **Live Power Consumption**: `{total_w} W` monitored across active sub-circuits.\n"
                    f"• **Grid Tariff Period**: `{tariff.get('period', 'standard').upper()}` ({tariff.get('peak_window_description', 'Time-Of-Use')}) — "
                    f"`{tariff.get('hours_until_change', 0)}h` until next rate window change.\n"
                    f"{solar_line}"
                ),
            },
            {
                "type": "custom:otis-companion-card",
                "mode": "energy",
                "title": "⚡ Energy, Solar & Grid Studio",
            },
            {
                "type": "grid",
                "title": "⚡ Dynamic Load Shedding & Rate Controls",
                "columns": 2,
                "square": False,
                "cards": [
                    {
                        "type": "button",
                        "name": "Shed Non-Essential Loads",
                        "icon": "mdi:transmission-tower-export",
                        "tap_action": {
                            "action": "call-service",
                            "service": "otis_ai.load_shed",
                            "data": {"tier": 1},
                        },
                    },
                    {
                        "type": "button",
                        "name": "Restore Shedded Loads",
                        "icon": "mdi:restore",
                        "tap_action": {
                            "action": "call-service",
                            "service": "otis_ai.restore_shed_loads",
                        },
                    },
                ],
            },
        ]

        if power_eids:
            cards.append({
                "type": "entities",
                "title": "🔌 Live Power Monitoring Circuits",
                "state_color": True,
                "entities": power_eids[:12],
            })

        if controllable_power_eids:
            cards.append({
                "type": "entities",
                "title": "🎛️ High-Draw Controllable Circuits & Appliances",
                "state_color": True,
                "entities": controllable_power_eids[:8],
            })

        if battery_eids:
            cards.append({
                "type": "entities",
                "title": "🔋 Battery Storage & UPS Status",
                "state_color": True,
                "entities": battery_eids[:8],
            })

        if energy_eids:
            cards.append({
                "type": "entities",
                "title": "📊 Cumulative Energy Meters (kWh)",
                "state_color": True,
                "entities": energy_eids[:8],
            })

        return cards

    def _build_security_view_cards(
        self,
        capability_map: dict[str, Any] | None,
        dashboard_url_path: str = COMMAND_CENTER_DASHBOARD_URL_PATH,
        nav_style: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build cards for Security Center subview or standalone dashboard."""
        if nav_style is None:
            nav_style = self._get_user_rules().get("navigation_style", "sleek_buttons")
        nav_card = self._build_studio_navigation_card(
            dashboard_url_path=dashboard_url_path, nav_style=nav_style, capability_map=capability_map
        )
        voice_switch_eid = resolve_otis_entity_id(getattr(self, "hass", None), "switch", "voice_announcements")
        sentinel_sensor_eid = resolve_otis_entity_id(getattr(self, "hass", None), "sensor", "perimeter_sentinel")

        if not capability_map:
            return [
                nav_card,
                {
                    "type": "markdown",
                    "content": (
                        "## 🛡️ Security, Locks & Perimeter Center\n"
                        "Live status and controls for alarm panels, smart locks, garage doors, occupancy sensors, and perimeter cameras."
                    ),
                },
                {
                    "type": "entities",
                    "title": "Proactive Security Voice Announcements",
                    "show_header_toggle": False,
                    "entities": [
                        {
                            "entity": voice_switch_eid,
                            "name": "Spoken Security Announcements",
                            "icon": "mdi:volume-high",
                        },
                        {
                            "entity": sentinel_sensor_eid,
                            "name": "Perimeter Sentinel Status",
                            "icon": "mdi:shield-search",
                        },
                    ],
                },
            ]

        entities = capability_map.get("entities", [])
        sec_topo = capability_map.get("security_topology", {})
        valid_eids = {
            e["entity_id"]
            for e in entities
            if e.get("entity_id")
            and not e.get("disabled_by")
            and not e.get("hidden_by")
            and e.get("state") not in ("unknown", "unavailable", None, "")
        }

        def _filter_valid(eid_list: list[str]) -> list[str]:
            if not valid_eids:
                return eid_list
            return [eid for eid in eid_list if eid in valid_eids]

        alarms = _filter_valid(sec_topo.get("alarm_panels", []))
        locks = _filter_valid(sec_topo.get("locks", []))
        garages = _filter_valid(sec_topo.get("garage_covers", []))
        cameras = _filter_valid(sec_topo.get("cameras", []))
        beds = _filter_valid(sec_topo.get("bed_occupancy_sensors", []))
        persons = _filter_valid(sec_topo.get("persons", []))
        contacts = _filter_valid(sec_topo.get("perimeter_contact_sensors", []))

        # Fallback to direct entities if sec_topo lists were empty
        if not locks:
            locks = _filter_valid([e["entity_id"] for e in entities if e.get("domain") == "lock"])
        if not cameras:
            cameras = _filter_valid([e["entity_id"] for e in entities if e.get("domain") == "camera"])

        # Deduplicate cameras to ensure only one optimal stream per physical camera
        cam_groups: dict[str, list[str]] = {}
        for c_eid in cameras:
            ckey = get_canonical_camera_key(c_eid)
            cam_groups.setdefault(ckey, []).append(c_eid)
        deduped_sec_cameras = []
        strategy = self.get_camera_stream_strategy()
        for c_list in cam_groups.values():
            c_list.sort(key=lambda x: stream_priority(x, x, strategy=strategy))
            deduped_sec_cameras.append(c_list[0])
        cameras = deduped_sec_cameras

        cards: list[dict[str, Any]] = [
            nav_card,
            {
                "type": "markdown",
                "content": (
                    "## 🛡️ Security, Locks & Perimeter Command Center\n"
                    "Live control of alarm panels, smart locks, garage doors, occupancy sensors, and perimeter cameras."
                ),
            },
            {
                "type": "entities",
                "title": "Proactive Security Voice Announcements",
                "show_header_toggle": False,
                "entities": [
                    {
                        "entity": voice_switch_eid,
                        "name": "Spoken Security Announcements",
                        "icon": "mdi:volume-high",
                    },
                    {
                        "entity": sentinel_sensor_eid,
                        "name": "Perimeter Sentinel Status",
                        "icon": "mdi:shield-search",
                    },
                ],
            },
            {
                "type": "custom:otis-companion-card",
                "mode": "security",
                "title": "🛡️ Security, Locks & Perimeter Center",
            },
        ]

        vision_topo = capability_map.get("vision_topology", {})
        pres_summary = vision_topo.get("presence", {})
        if pres_summary and pres_summary.get("rooms"):
            occ_rooms = pres_summary.get("occupied_areas", [])
            likely_rooms = pres_summary.get("likely_areas", [])
            vacant_count = pres_summary.get("vacant_count", 0)
            status_text = (
                f"**Occupied ({len(occ_rooms)}):** {', '.join(occ_rooms) if occ_rooms else 'None'}  \n"
                f"**Likely Occupied ({len(likely_rooms)}):** {', '.join(likely_rooms) if likely_rooms else 'None'}  \n"
                f"**Vacant Rooms:** {vacant_count} &nbsp;|&nbsp; **Household Present:** {'Yes' if pres_summary.get('household_present') else 'No'}"
            )
            cards.append({
                "type": "markdown",
                "title": "👁️ Multi-Sensor Room Presence Intelligence",
                "content": status_text,
            })

        if alarms:
            cards.extend([{"type": "alarm-panel", "entity": a} for a in alarms[:2]])

        if locks or garages:
            sec_tiles: list[dict[str, Any]] = []
            for l_eid in locks[:6]:
                sec_tiles.append({
                    "type": "tile",
                    "entity": l_eid,
                    "features": [{"type": "lock-commands"}],
                })
            for g_eid in garages[:4]:
                sec_tiles.append({
                    "type": "tile",
                    "entity": g_eid,
                    "features": [{"type": "cover-open-close"}],
                })
            cards.append({
                "type": "grid",
                "title": "Smart Locks & Garage Doors",
                "columns": min(2, len(sec_tiles)),
                "square": False,
                "cards": sec_tiles,
            })

        if persons or beds:
            cards.append({
                "type": "entities",
                "title": "Resident Presence & Bed Occupancy",
                "state_color": True,
                "entities": (persons + beds)[:8],
            })

        if contacts:
            cards.append({
                "type": "entities",
                "title": "Perimeter Doors & Entry Sensors",
                "state_color": True,
                "entities": contacts[:8],
            })

        if cameras:
            cards.append({
                "type": "grid",
                "title": "Live Perimeter Cameras",
                "columns": min(2, len(cameras)),
                "square": False,
                "cards": [
                    {
                        "type": "picture-entity",
                        "entity": cam,
                        "camera_view": "auto",
                        "layout_options": {
                            "grid_columns": 2,
                            "grid_rows": "auto",
                        },
                    }
                    for cam in cameras[:6]
                ],
            })

        if not alarms and not locks and not garages and not cameras and not persons and not beds and not contacts:
            cards.append({
                "type": "markdown",
                "content": (
                    "No security devices, locks, or cameras currently discovered.\n\n"
                    "Once security integrations are added, Otis will automatically configure controls here."
                ),
            })

        return cards

    def _build_climate_view_cards(
        self,
        capability_map: dict[str, Any] | None,
        dashboard_url_path: str = COMMAND_CENTER_DASHBOARD_URL_PATH,
        nav_style: str | None = None,
        layout_style: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build cards for Climate & Pool subview or standalone dashboard."""
        if nav_style is None:
            nav_style = self._get_user_rules().get("navigation_style", "sleek_buttons")
        if layout_style is None:
            layout_style = self._get_user_rules().get("dashboard_layout", "modern_sections")
        nav_card = self._build_studio_navigation_card(
            dashboard_url_path=dashboard_url_path, nav_style=nav_style, capability_map=capability_map
        )

        if not capability_map:
            return [
                nav_card,
                {
                    "type": "markdown",
                    "content": (
                        "## 🌡️ Climate & Comfort Operations\n"
                        "Unified environmental controls for HVAC thermostats, ceiling fans, and home comfort."
                    ),
                }
            ]

        entities = capability_map.get("entities", [])
        valid_eids = {
            e["entity_id"]
            for e in entities
            if e.get("entity_id")
            and not e.get("disabled_by")
            and not e.get("hidden_by")
            and e.get("state") not in ("unknown", "unavailable", None, "")
        }

        def _filter_valid(eid_list: list[str]) -> list[str]:
            if not valid_eids:
                return eid_list
            return [eid for eid in eid_list if eid in valid_eids]

        climates = _filter_valid([e["entity_id"] for e in entities if e.get("domain") == "climate"])
        fans = _filter_valid([e["entity_id"] for e in entities if e.get("domain") == "fan"])
        valid_pool_eids = set(_filter_valid([e["entity_id"] for e in entities if e.get("entity_id")]))
        pool_grouped = self._classify_pool_and_spa_entities(entities, valid_pool_eids)
        sleep_platforms = {"sleepiq", "eight_sleep"}
        sleep_device_ids = {
            e.get("device_id")
            for e in entities
            if e.get("device_id") and str(e.get("platform", "")).lower() in sleep_platforms
        }
        sleep_controls = list(dict.fromkeys(_filter_valid([
            e["entity_id"]
            for e in entities
            if (
                str(e.get("platform", "")).lower() in sleep_platforms
                or (e.get("device_id") and e.get("device_id") in sleep_device_ids)
                or (not e.get("platform") and "sleepnumber" in e.get("entity_id", "").lower())
            )
            and e.get("domain") in ("select", "number", "switch", "light", "button")
            and str(e.get("entity_category") or "").lower() != "diagnostic"
        ])))
        sleep_ents = sleep_controls

        has_pool = any(pool_grouped.values())
        has_sleep = bool(sleep_ents)
        climate_title = "Climate & Pool" if has_pool else "Climate"
        desc_parts = ["HVAC thermostats", "ceiling fans"]
        if has_pool:
            desc_parts.append("pool chemistry, chlorinator, equipment & spa")
        if has_sleep:
            desc_parts.append("SleepNumber comfort")
        desc_text = ", ".join(desc_parts[:-1]) + f", and {desc_parts[-1]}"

        cards: list[dict[str, Any]] = [
            nav_card,
            {
                "type": "markdown",
                "content": (
                    f"## 🌡️ {climate_title} & Comfort Operations\n"
                    f"Unified environmental controls for {desc_text}."
                ),
            },
            {
                "type": "custom:otis-companion-card",
                "mode": "climate",
                "title": f"🌡️ {climate_title} Studio",
            },
        ]

        spa_climate_set = set(pool_grouped["spa_climates"])
        pool_climate_set = set(pool_grouped["pool_climates"])
        hvac_climates = [
            c for c in climates
            if c not in spa_climate_set
            and c not in pool_climate_set
            and not any(k in c.lower() for k in ("pool", "spa", "pentair"))
        ]
        pool_climates = pool_grouped["pool_climates"] or [
            c for c in climates if c not in spa_climate_set and any(k in c.lower() for k in ("pool", "pentair"))
        ]
        spa_climates = pool_grouped["spa_climates"]

        is_sections = self._is_sections_layout(layout_style)
        if hvac_climates:
            if is_sections:
                cards.append({
                    "type": "grid",
                    "title": "HVAC Thermostats & Dual-Setpoints",
                    "columns": min(2, len(hvac_climates)),
                    "square": False,
                    "cards": [
                        {
                            "type": "tile",
                            "entity": c,
                            "features": [
                                {"type": "target-temperature"},
                                {"type": "climate-hvac-modes"},
                            ],
                        }
                        for c in hvac_climates[:6]
                    ],
                })
            else:
                cards.append({
                    "type": "grid",
                    "title": "HVAC Thermostats",
                    "columns": min(2, len(hvac_climates)),
                    "square": False,
                    "cards": [
                        {
                            "type": "thermostat",
                            "entity": c,
                            "features": [{"type": "climate-hvac-modes"}],
                        }
                        for c in hvac_climates[:4]
                    ],
                })

        if fans:
            cards.append({
                "type": "grid",
                "title": "Ceiling & Ventilation Fans",
                "columns": min(2, len(fans)),
                "square": False,
                "cards": [{"type": "tile", "entity": f} for f in fans[:6]],
            })

        if pool_climates:
            cards.append({
                "type": "grid",
                "title": "Pool Heater & Water Temperature",
                "columns": min(2, len(pool_climates)),
                "square": False,
                "cards": [
                    {
                        "type": "tile" if is_sections else "thermostat",
                        "entity": c,
                        "features": [
                            {"type": "target-temperature"},
                            {"type": "climate-hvac-modes"},
                        ] if is_sections else [{"type": "climate-hvac-modes"}],
                    }
                    for c in pool_climates[:4]
                ],
            })

        if pool_grouped["chemistry"]:
            cards.append({
                "type": "grid",
                "title": "Pool Water Chemistry",
                "columns": min(3, len(pool_grouped["chemistry"])),
                "square": False,
                "cards": [
                    {"type": "tile", "entity": eid}
                    for eid in pool_grouped["chemistry"][:12]
                ],
            })

        if pool_grouped["chemistry_alerts"]:
            cards.append({
                "type": "entities",
                "title": "Water Chemistry Alerts & Sensor Maintenance",
                "state_color": True,
                "entities": pool_grouped["chemistry_alerts"][:12],
            })

        if pool_grouped["chlorinator"]:
            cards.append({
                "type": "entities",
                "title": "Chlorinator & Sanitization",
                "state_color": True,
                "entities": pool_grouped["chlorinator"][:10],
            })

        if pool_grouped["pool_equipment"]:
            controllable_domains = ("switch", "light", "select", "vacuum", "button")
            pool_controls = list(dict.fromkeys(
                eid for eid in pool_grouped["pool_equipment"]
                if eid.split(".", 1)[0] in controllable_domains
            ))
            pool_telemetry = list(dict.fromkeys(
                eid for eid in pool_grouped["pool_equipment"]
                if eid.split(".", 1)[0] not in controllable_domains
            ))
            if pool_controls:
                cards.append({
                    "type": "entities",
                    "title": "Pool Pump, Lights & Features",
                    "state_color": True,
                    "entities": pool_controls,
                })
            if pool_telemetry:
                cards.append({
                    "type": "entities",
                    "title": "Pool Pump & Cleaner Telemetry",
                    "state_color": True,
                    "entities": pool_telemetry[:14],
                })

        if spa_climates or pool_grouped["spa_controls"]:
            if spa_climates:
                cards.append({
                    "type": "grid",
                    "title": "Spa & Hot Tub Temperature",
                    "columns": min(2, len(spa_climates)),
                    "square": False,
                    "cards": [
                        {
                            "type": "tile" if layout_style == "modern_sections" else "thermostat",
                            "entity": c,
                            "features": [
                                {"type": "target-temperature"},
                                {"type": "climate-hvac-modes"},
                            ] if layout_style == "modern_sections" else [{"type": "climate-hvac-modes"}],
                        }
                        for c in spa_climates[:2]
                    ],
                })
            if pool_grouped["spa_controls"]:
                cards.append({
                    "type": "entities",
                    "title": "Spa Pumps, Modes & Filter Cycles",
                    "state_color": True,
                    "entities": pool_grouped["spa_controls"][:16],
                })

        if sleep_controls:
            cards.append({
                "type": "entities",
                "title": "SleepNumber Bed Controls",
                "state_color": True,
                "entities": sleep_controls,
            })

        if not climates and not fans and not has_pool and not sleep_ents:
            cards.append({
                "type": "markdown",
                "content": (
                    "No climate thermostats, fans, or pool devices currently discovered.\n\n"
                    "Once environmental controls are connected, Otis will automatically configure them here."
                ),
            })

        return cards

    def _generate_template_config(
        self,
        template: str,
        title: str,
        capability_map: dict[str, Any],
        url_path: str = "",
        installed_cards: set[str] | None = None,
    ) -> dict[str, Any]:
        """Build professional-grade Lovelace Hub-and-Spoke view/card definitions using verified active entities only."""
        if not url_path:
            url_path = f"otis-{template.replace('_', '-')}"

        dash_url = url_path.strip("/")
        user_rules = self._get_user_rules()
        layout_style = user_rules.get("dashboard_layout", "modern_sections")
        nav_style = user_rules.get("navigation_style", "sleek_buttons")

        if template == "whole_home":
            areas_map = capability_map.get("areas", {})
            entities_list = capability_map.get("entities", [])
            valid_eids = {
                e["entity_id"]
                for e in entities_list
                if e.get("entity_id")
                and not e.get("disabled_by")
                and not e.get("hidden_by")
                and (e.get("state") not in ("unknown", "unavailable", None, "") or e.get("recovered_orphaned_hide"))
            }
            entities_by_id = {e["entity_id"]: e for e in entities_list}
            entities_by_area: dict[str, list[dict[str, Any]]] = {}
            for e in entities_list:
                aid = e.get("area_id")
                if aid:
                    entities_by_area.setdefault(aid, []).append(e)

            room_views: list[dict[str, Any]] = []
            nav_buttons: list[dict[str, Any]] = []

            sorted_areas = sorted(
                areas_map.items(),
                key=lambda kv: str(kv[1].get("name", kv[0])).lower(),
            )
            for aid, ainfo in sorted_areas:
                room_entities = list(entities_by_area.get(aid, []))
                if not room_entities and ainfo.get("entities"):
                    for eid in ainfo["entities"]:
                        if eid in entities_by_id:
                            room_entities.append(entities_by_id[eid])

                room_view = self._build_room_subview(
                    aid,
                    ainfo,
                    room_entities,
                    valid_eids,
                    layout_style=layout_style,
                    nav_style=nav_style,
                    dashboard_url_path=dash_url,
                )
                if room_view:
                    room_views.append(room_view)
                    aname = ainfo.get("name") or aid.replace("_", " ").title()
                    aslug = self._slugify(aid)
                    nav_buttons.append({
                        "type": "button",
                        "name": aname,
                        "icon": "mdi:door-open",
                        "tap_action": {
                            "action": "navigate",
                            "navigation_path": f"/{dash_url}/area_{aslug}",
                        },
                    })

            hub_cards: list[dict[str, Any]] = [
                {
                    "type": "markdown",
                    "content": (
                        f"## 🏡 {title}\n"
                        "Central Whole-Home Hub: select any room below for full lighting, media, climate, and security controls."
                    ),
                }
            ]
            if nav_buttons:
                hub_cards.append({
                    "type": "grid",
                    "title": "Rooms & Living Areas",
                    "columns": min(3, len(nav_buttons)),
                    "square": False,
                    "cards": nav_buttons,
                })
            else:
                hub_cards.append({
                    "type": "markdown",
                    "content": "No registered areas with active entities discovered yet.",
                })

            hub_view = {
                "title": title,
                "path": "default_view",
                "icon": "mdi:home-group",
                "cards": hub_cards,
            }
            return {
                "title": title,
                "views": [hub_view] + room_views,
            }

        if template == "media_studio":
            entities = capability_map.get("entities", [])
            media_topo = capability_map.get("media_topology", {})
            valid_eids = {
                e["entity_id"]
                for e in entities
                if e.get("entity_id")
                and not e.get("disabled_by")
                and not e.get("hidden_by")
                and (e.get("state") not in ("unknown", "unavailable", None, "") or e.get("recovered_orphaned_hide"))
            }

            def _filter_valid(eid_list: list[str]) -> list[str]:
                if not valid_eids:
                    return eid_list
                return [eid for eid in eid_list if eid in valid_eids]

            matrix_zones = _filter_valid([z["entity_id"] for z in media_topo.get("matrix_zones", [])])
            streamers = _filter_valid([s["entity_id"] for s in media_topo.get("input_streamers", [])])
            tvs = _filter_valid([
                t["entity_id"]
                for t in media_topo.get("tv_cinema_zones", [])
                if not any(z in t.get("entity_id", "").lower() for z in ("_zone_3", "_zone_4", "_zone3", "_zone4"))
            ])
            helpers = _filter_valid([
                e["entity_id"]
                for e in entities
                if e.get("entity_id", "").startswith("input_select.media_")
                or e.get("entity_id", "").endswith("_speakers")
            ])
            all_mps = _filter_valid([e["entity_id"] for e in entities if e.get("domain") == "media_player"])
            if not matrix_zones and all_mps:
                matrix_zones = [m for m in all_mps if m not in tvs and m not in streamers]

            detected_cards = installed_cards if installed_cards is not None else self._cached_installed_cards
            has_mmp = "custom:mini-media-player" in detected_cards
            has_remote = "custom:universal-remote-card" in detected_cards
            has_mushroom = "custom:mushroom-media-player-card" in detected_cards

            # Spoke 1: Speaker Zones
            zones_cards: list[dict[str, Any]] = [
                {
                    "type": "markdown",
                    "content": "## 🔊 Matrix & Speaker Zones\nIndependent volume, source selection, and power management for every room zone.",
                }
            ]
            zones_cards.append({
                "type": "custom:otis-companion-card",
                "mode": "media_studio",
                "title": "Media Studio & Source-to-Zone Router",
            })

            if matrix_zones:
                zone_cards = []
                for zid in matrix_zones:
                    if has_mmp:
                        zone_cards.append({
                            "type": "custom:mini-media-player",
                            "entity": zid,
                            "artwork": "cover",
                            "source": "full",
                            "sound_mode": "full",
                            "group": False,
                            "volume_stateless": False,
                        })
                    else:
                        zone_cards.append({
                            "type": "tile",
                            "entity": zid,
                            "features": [{"type": "media-player-volume-slider"}],
                        })

                zones_cards.append({
                    "type": "grid",
                    "title": "Speaker Zones",
                    "columns": 2,
                    "square": False,
                    "cards": zone_cards,
                })
            else:
                zones_cards.append({
                    "type": "markdown",
                    "content": "No active speaker zones currently discovered.",
                })

            zones_view = {
                "title": "Speaker Zones",
                "path": "zones",
                "icon": "mdi:speaker",
                "subview": True,
                "badges": [],
                "cards": zones_cards,
            }

            # Spoke 2: Upstream Streamers & Bridges
            streamers_cards: list[dict[str, Any]] = [
                {
                    "type": "markdown",
                    "content": "## 📻 Streamers & Audio Bridges\nUpstream streaming inputs feeding the whole-home matrix amplifier.",
                }
            ]
            if streamers:
                streamer_cards = []
                for s in streamers[:6]:
                    if has_mmp:
                        streamer_cards.append({
                            "type": "custom:mini-media-player",
                            "entity": s,
                            "artwork": "cover",
                            "source": "full",
                            "sound_mode": "full",
                            "info": "short",
                        })
                    elif has_mushroom:
                        streamer_cards.append({
                            "type": "custom:mushroom-media-player-card",
                            "entity": s,
                            "use_media_artwork": True,
                            "show_volume_level": True,
                        })
                    else:
                        streamer_cards.append({"type": "media-control", "entity": s})

                streamers_cards.append({
                    "type": "grid",
                    "title": "Audio Streamers",
                    "columns": min(2, len(streamer_cards)),
                    "square": False,
                    "cards": streamer_cards,
                })
            if helpers:
                streamers_cards.append({
                    "type": "entities",
                    "title": "Audio Routing Selectors",
                    "state_color": True,
                    "entities": helpers[:10],
                })
            if not streamers and not helpers:
                streamers_cards.append({
                    "type": "markdown",
                    "content": "No upstream streamers or routing helpers currently discovered.",
                })

            streamers_view = {
                "title": "Streamers & Bridges",
                "path": "streamers",
                "icon": "mdi:cast-audio",
                "subview": True,
                "badges": [],
                "cards": streamers_cards,
            }

            # Spoke 3: Cinema & Room Displays
            cinema_cards: list[dict[str, Any]] = [
                {
                    "type": "markdown",
                    "content": "## 📺 Cinema & Room Displays\nManage Home Theaters, media room screens, and smart TVs.",
                }
            ]
            if tvs:
                tv_cards = []
                for idx, tv in enumerate(tvs[:8]):
                    if idx == 0 and has_remote:
                        tv_cards.append({
                            "type": "custom:universal-remote-card",
                            "entity": tv,
                        })
                    elif has_mmp:
                        tv_cards.append({
                            "type": "custom:mini-media-player",
                            "entity": tv,
                            "artwork": "cover",
                            "source": "full",
                        })
                    else:
                        tv_cards.append({"type": "tile", "entity": tv})

                cinema_cards.append({
                    "type": "grid",
                    "title": "Displays & TVs",
                    "columns": min(2, len(tv_cards)),
                    "square": False,
                    "cards": tv_cards,
                })
            else:
                cinema_cards.append({
                    "type": "markdown",
                    "content": "No cinema displays or smart TVs currently discovered.",
                })

            cinema_view = {
                "title": "Cinema & Displays",
                "path": "cinema",
                "icon": "mdi:television",
                "subview": True,
                "badges": [],
                "cards": cinema_cards,
            }

            # Central Hub View
            hub_nav_cards = [
                {
                    "type": "button",
                    "name": "Speaker Zones",
                    "icon": "mdi:speaker",
                    "tap_action": {"action": "navigate", "navigation_path": f"/{dash_url}/zones"},
                },
                {
                    "type": "button",
                    "name": "Streamers & Bridges",
                    "icon": "mdi:cast-audio",
                    "tap_action": {"action": "navigate", "navigation_path": f"/{dash_url}/streamers"},
                },
                {
                    "type": "button",
                    "name": "Cinema & Displays",
                    "icon": "mdi:television",
                    "tap_action": {"action": "navigate", "navigation_path": f"/{dash_url}/cinema"},
                },
            ]
            hub_cards = [
                {
                    "type": "markdown",
                    "content": (
                        f"## 🎵 {title}\n"
                        "Central Whole-Home Media Hub: route audio across Matrix Amp zones, control streamers, and manage cinema displays."
                    ),
                },
                {
                    "type": "grid",
                    "title": "Studio Navigation",
                    "columns": 3,
                    "square": False,
                    "cards": hub_nav_cards,
                },
            ]

            hub_cards.append({
                "type": "custom:otis-companion-card",
                "mode": "media_studio",
                "title": "Media Studio & Source-to-Zone Router",
            })

            if streamers:
                hub_streamer_cards = []
                for s in streamers[:2]:
                    if has_mmp:
                        hub_streamer_cards.append({
                            "type": "custom:mini-media-player",
                            "entity": s,
                            "artwork": "cover",
                            "source": "full",
                            "sound_mode": "full",
                            "info": "short",
                        })
                    else:
                        hub_streamer_cards.append({"type": "media-control", "entity": s})

                hub_cards.append({
                    "type": "grid",
                    "title": "Active Upstream Streamers",
                    "columns": min(2, len(hub_streamer_cards)),
                    "square": False,
                    "cards": hub_streamer_cards,
                })

            if matrix_zones:
                hub_zone_cards = []
                for zid in matrix_zones[:4]:
                    if has_mmp:
                        hub_zone_cards.append({
                            "type": "custom:mini-media-player",
                            "entity": zid,
                            "artwork": "cover",
                            "source": "full",
                            "sound_mode": "full",
                            "group": False,
                            "volume_stateless": False,
                        })
                    else:
                        hub_zone_cards.append({
                            "type": "tile",
                            "entity": zid,
                            "features": [{"type": "media-player-volume-slider"}],
                        })

                hub_cards.append({
                    "type": "grid",
                    "title": "Primary Speaker Zones",
                    "columns": 2,
                    "square": False,
                    "cards": hub_zone_cards,
                })

            hub_view = {
                "title": title,
                "path": "default_view",
                "icon": "mdi:speaker-multiple",
                "cards": hub_cards,
            }

            return {
                "title": title,
                "views": [hub_view, zones_view, streamers_view, cinema_view],
            }

        if template == "security_center":
            entities = capability_map.get("entities", [])
            sec_topo = capability_map.get("security_topology", {})
            valid_eids = {
                e["entity_id"]
                for e in entities
                if e.get("entity_id")
                and not e.get("disabled_by")
                and not e.get("hidden_by")
                and (e.get("state") not in ("unknown", "unavailable", None, "") or e.get("recovered_orphaned_hide"))
            }

            def _filter_valid(eid_list: list[str]) -> list[str]:
                if not valid_eids:
                    return eid_list
                return [eid for eid in eid_list if eid in valid_eids]

            alarms = _filter_valid(sec_topo.get("alarm_panels", []))
            locks = _filter_valid(sec_topo.get("locks", []))
            garages = _filter_valid(sec_topo.get("garage_covers", []))
            cameras = _filter_valid(sec_topo.get("cameras", []))
            beds = _filter_valid(sec_topo.get("bed_occupancy_sensors", []))
            persons = _filter_valid(sec_topo.get("persons", []))
            contacts = _filter_valid(sec_topo.get("perimeter_contact_sensors", []))

            if not locks:
                locks = _filter_valid([e["entity_id"] for e in entities if e.get("domain") == "lock"])
            if not cameras:
                cameras = _filter_valid([e["entity_id"] for e in entities if e.get("domain") == "camera"])

            # Spoke 1: Cameras
            cam_cards: list[dict[str, Any]] = [
                {
                    "type": "markdown",
                    "content": "## 📹 Perimeter Cameras\nLive video feeds from security and perimeter cameras.",
                }
            ]
            if cameras:
                cam_cards.append({
                    "type": "grid",
                    "title": "Perimeter Cameras",
                    "columns": min(2, len(cameras)),
                    "square": False,
                    "cards": [
                        {"type": "picture-entity", "entity": cam, "camera_view": "auto"}
                        for cam in cameras
                    ],
                })
            else:
                cam_cards.append({
                    "type": "markdown",
                    "content": "No live perimeter cameras currently discovered.",
                })

            cameras_view = {
                "title": "Perimeter Cameras",
                "path": "cameras",
                "icon": "mdi:cctv",
                "subview": True,
                "badges": [],
                "cards": cam_cards,
            }

            # Spoke 2: Access & Locks
            access_cards: list[dict[str, Any]] = [
                {
                    "type": "markdown",
                    "content": "## 🔐 Locks & Entryways\nSmart door locks, garage doors, and motorized access points.",
                }
            ]
            if locks or garages:
                sec_tiles = []
                for l_eid in locks:
                    sec_tiles.append({
                        "type": "tile",
                        "entity": l_eid,
                        "features": [{"type": "lock-commands"}],
                    })
                for g_eid in garages:
                    sec_tiles.append({
                        "type": "tile",
                        "entity": g_eid,
                        "features": [{"type": "cover-open-close"}],
                    })
                access_cards.append({
                    "type": "grid",
                    "title": "Smart Locks & Garage Doors",
                    "columns": min(2, len(sec_tiles)),
                    "square": False,
                    "cards": sec_tiles,
                })
            else:
                access_cards.append({
                    "type": "markdown",
                    "content": "No smart locks or garage doors currently discovered.",
                })

            access_view = {
                "title": "Locks & Entryways",
                "path": "access",
                "icon": "mdi:lock",
                "subview": True,
                "badges": [],
                "cards": access_cards,
            }

            # Spoke 3: Sensors & Presence
            sensors_cards: list[dict[str, Any]] = [
                {
                    "type": "markdown",
                    "content": "## 👁️ Sensors & Presence\nResident presence, bed occupancy telemetry, and perimeter entry sensors.",
                }
            ]
            if persons or beds:
                sensors_cards.append({
                    "type": "entities",
                    "title": "Resident Presence & Bed Occupancy",
                    "state_color": True,
                    "entities": (persons + beds)[:10],
                })
            if contacts:
                sensors_cards.append({
                    "type": "entities",
                    "title": "Perimeter Doors & Windows",
                    "state_color": True,
                    "entities": contacts[:10],
                })
            if not persons and not beds and not contacts:
                sensors_cards.append({
                    "type": "markdown",
                    "content": "No presence or perimeter sensors currently discovered.",
                })

            sensors_view = {
                "title": "Sensors & Presence",
                "path": "sensors",
                "icon": "mdi:motion-sensor",
                "subview": True,
                "badges": [],
                "cards": sensors_cards,
            }

            # Hub View
            hub_nav_cards = [
                {
                    "type": "button",
                    "name": "Live Cameras",
                    "icon": "mdi:cctv",
                    "tap_action": {"action": "navigate", "navigation_path": f"/{dash_url}/cameras"},
                },
                {
                    "type": "button",
                    "name": "Locks & Access",
                    "icon": "mdi:lock",
                    "tap_action": {"action": "navigate", "navigation_path": f"/{dash_url}/access"},
                },
                {
                    "type": "button",
                    "name": "Sensors & Presence",
                    "icon": "mdi:motion-sensor",
                    "tap_action": {"action": "navigate", "navigation_path": f"/{dash_url}/sensors"},
                },
            ]
            hub_cards = [
                {
                    "type": "markdown",
                    "content": (
                        f"## 🛡️ {title}\n"
                        "Central Security & Perimeter Hub: arm/disarm alarms, manage smart locks, and monitor cameras."
                    ),
                },
                {
                    "type": "grid",
                    "title": "Security Navigation",
                    "columns": 3,
                    "square": False,
                    "cards": hub_nav_cards,
                },
            ]
            if alarms:
                hub_cards.extend([{"type": "alarm-panel", "entity": a} for a in alarms[:2]])
            if locks or garages:
                quick_sec_tiles = []
                for l_eid in locks[:4]:
                    quick_sec_tiles.append({
                        "type": "tile",
                        "entity": l_eid,
                        "features": [{"type": "lock-commands"}],
                    })
                for g_eid in garages[:2]:
                    quick_sec_tiles.append({
                        "type": "tile",
                        "entity": g_eid,
                        "features": [{"type": "cover-open-close"}],
                    })
                hub_cards.append({
                    "type": "grid",
                    "title": "Primary Entryways & Locks",
                    "columns": min(2, len(quick_sec_tiles)),
                    "square": False,
                    "cards": quick_sec_tiles,
                })

            hub_view = {
                "title": title,
                "path": "default_view",
                "icon": "mdi:shield-home",
                "cards": hub_cards,
            }

            return {
                "title": title,
                "views": [hub_view, cameras_view, access_view, sensors_view],
            }

        # Default: climate_energy
        entities = capability_map.get("entities", [])
        valid_eids = {
            e["entity_id"]
            for e in entities
            if e.get("entity_id")
            and not e.get("disabled_by")
            and not e.get("hidden_by")
            and e.get("state") not in ("unknown", "unavailable", None, "")
        }

        def _filter_valid(eid_list: list[str]) -> list[str]:
            if not valid_eids:
                return eid_list
            return [eid for eid in eid_list if eid in valid_eids]

        climates = _filter_valid([e["entity_id"] for e in entities if e.get("domain") == "climate"])
        fans = _filter_valid([e["entity_id"] for e in entities if e.get("domain") == "fan"])
        pool_ents = _filter_valid([
            e["entity_id"]
            for e in entities
            if e.get("domain") in ("sensor", "binary_sensor", "switch", "light")
            and any(k in e.get("entity_id", "").lower() for k in ("pentair", "pool", "waterguru", "spa"))
            and "pre_release" not in e.get("entity_id", "").lower()
        ])
        sleep_platforms = {"sleepiq", "eight_sleep"}
        sleep_device_ids = {
            e.get("device_id")
            for e in entities
            if e.get("device_id") and str(e.get("platform", "")).lower() in sleep_platforms
        }
        sleep_controls = list(dict.fromkeys(_filter_valid([
            e["entity_id"]
            for e in entities
            if (
                str(e.get("platform", "")).lower() in sleep_platforms
                or (e.get("device_id") and e.get("device_id") in sleep_device_ids)
                or (not e.get("platform") and "sleepnumber" in e.get("entity_id", "").lower())
            )
            and e.get("domain") in ("select", "number", "switch", "light", "button")
            and str(e.get("entity_category") or "").lower() != "diagnostic"
        ])))
        sleep_ents = sleep_controls

        # Spoke 1: HVAC Thermostats
        hvac_cards: list[dict[str, Any]] = [
            {
                "type": "markdown",
                "content": "## 🌡️ HVAC Thermostats\nPrecision temperature management and HVAC mode selection.",
            }
        ]
        if climates:
            hvac_cards.append({
                "type": "grid",
                "title": "Thermostats",
                "columns": min(2, len(climates)),
                "square": False,
                "cards": [
                    {
                        "type": "thermostat",
                        "entity": c,
                        "features": [{"type": "climate-hvac-modes"}],
                    }
                    for c in climates
                ],
            })
        else:
            hvac_cards.append({
                "type": "markdown",
                "content": "No climate thermostats currently discovered.",
            })

        hvac_view = {
            "title": "HVAC Thermostats",
            "path": "hvac",
            "icon": "mdi:thermostat",
            "subview": True,
            "badges": [],
            "cards": hvac_cards,
        }

        # Spoke 2: Pool & Spa
        pool_cards: list[dict[str, Any]] = [
            {
                "type": "markdown",
                "content": "## 🏊 Pool & Spa Operations\nPool pump automation, water heaters, and chemistry telemetry.",
            }
        ]
        if pool_ents:
            pool_cards.append({
                "type": "entities",
                "title": "Pool Telemetry & Controls",
                "state_color": True,
                "entities": pool_ents[:12],
            })
        else:
            pool_cards.append({
                "type": "markdown",
                "content": "No pool or spa equipment currently discovered.",
            })

        pool_view = {
            "title": "Pool & Spa",
            "path": "pool",
            "icon": "mdi:pool",
            "subview": True,
            "badges": [],
            "cards": pool_cards,
        }

        # Spoke 3: Comfort & Fans
        comfort_cards: list[dict[str, Any]] = [
            {
                "type": "markdown",
                "content": "## 💨 Fans & Bed Comfort\nCeiling fan speed controls and SleepNumber mattress firmness adjustments.",
            }
        ]
        if fans:
            comfort_cards.append({
                "type": "grid",
                "title": "Ceiling & Ventilation Fans",
                "columns": min(2, len(fans)),
                "square": False,
                "cards": [{"type": "tile", "entity": f} for f in fans],
            })
        if sleep_ents:
            comfort_cards.append({
                "type": "entities",
                "title": "SleepNumber Bed Telemetry",
                "state_color": True,
                "entities": sleep_ents[:12],
            })
        if not fans and not sleep_ents:
            comfort_cards.append({
                "type": "markdown",
                "content": "No fans or SleepNumber comfort devices currently discovered.",
            })

        comfort_view = {
            "title": "Fans & Comfort",
            "path": "comfort",
            "icon": "mdi:fan",
            "subview": True,
            "badges": [],
            "cards": comfort_cards,
        }

        # Central Hub View
        hub_nav_cards = [
            {
                "type": "button",
                "name": "HVAC Thermostats",
                "icon": "mdi:thermostat",
                "tap_action": {"action": "navigate", "navigation_path": f"/{dash_url}/hvac"},
            },
            {
                "type": "button",
                "name": "Pool & Spa",
                "icon": "mdi:pool",
                "tap_action": {"action": "navigate", "navigation_path": f"/{dash_url}/pool"},
            },
            {
                "type": "button",
                "name": "Fans & Comfort",
                "icon": "mdi:fan",
                "tap_action": {"action": "navigate", "navigation_path": f"/{dash_url}/comfort"},
            },
        ]
        hub_cards = [
            {
                "type": "markdown",
                "content": (
                    f"## 🌡️ {title}\n"
                    "Central Climate & Comfort Hub: adjust home temperatures, manage pool automation, and tune comfort."
                ),
            },
            {
                "type": "grid",
                "title": "Climate Navigation",
                "columns": 3,
                "square": False,
                "cards": hub_nav_cards,
            },
        ]
        if climates:
            hub_cards.append({
                "type": "grid",
                "title": "Primary Thermostats",
                "columns": min(2, len(climates)),
                "square": False,
                "cards": [
                    {
                        "type": "thermostat",
                        "entity": c,
                        "features": [{"type": "climate-hvac-modes"}],
                    }
                    for c in climates[:2]
                ],
            })
        if fans:
            hub_cards.append({
                "type": "grid",
                "title": "Quick Fan Controls",
                "columns": min(2, len(fans)),
                "square": False,
                "cards": [{"type": "tile", "entity": f} for f in fans[:4]],
            })

        hub_view = {
            "title": title,
            "path": "default_view",
            "icon": "mdi:thermostat-box",
            "cards": hub_cards,
        }

        return {
            "title": title,
            "views": [hub_view, hvac_view, pool_view, comfort_view],
        }
