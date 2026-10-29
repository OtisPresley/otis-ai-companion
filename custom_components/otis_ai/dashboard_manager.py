"""Lovelace Dashboard Manager & Professional Dashboard Generator for Otis AI Companion."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

OTIS_DASHBOARD_ID = "otis_ai"
OTIS_DASHBOARD_URL_PATH = "otis-ai"
OTIS_DASHBOARD_TITLE = "Otis AI"
OTIS_DASHBOARD_ICON = "mdi:robot-outline"


class DashboardManager:
    """Manages automatic creation of the Admin-only Otis AI dashboard and pro-grade custom dashboards."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the Dashboard Manager."""
        self.hass = hass

    def _storage_dir(self) -> str | None:
        """Return the path to Home Assistant's .storage directory if available."""
        if hasattr(self.hass, "config") and hasattr(self.hass.config, "path"):
            try:
                p = self.hass.config.path(".storage")
                if isinstance(p, str):
                    return p
            except Exception:
                pass
        return None

    async def async_ensure_admin_companion_dashboard(
        self, capability_map: dict[str, Any] | None = None
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
        dashboard_config = self._build_otis_companion_dashboard_config(capability_map)
        return await self._async_register_and_save_dashboard(
            item=item,
            dashboard_config=dashboard_config,
            overwrite_config=True,
        )

    def _build_otis_companion_dashboard_config(
        self, capability_map: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Build the Lovelace config for the Admin-only Otis AI Companion Command Center with Hub-and-Spoke subviews."""
        views: list[dict[str, Any]] = [
            {
                "title": "AI Command Center",
                "path": "default_view",
                "icon": "mdi:robot-outline",
                "type": "panel",
                "panel": True,
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

        # 1. Media Studio Subview (subview: true keeps top tabs clean while giving HA native back navigation)
        media_cards = self._build_media_view_cards(capability_map)
        views.append({
            "title": "Media Studio",
            "path": "media",
            "icon": "mdi:speaker-multiple",
            "subview": True,
            "badges": [],
            "cards": media_cards,
        })

        # 2. Security Center Subview
        security_cards = self._build_security_view_cards(capability_map)
        views.append({
            "title": "Security Center",
            "path": "security",
            "icon": "mdi:shield-home",
            "subview": True,
            "badges": [],
            "cards": security_cards,
        })

        # 3. Climate & Pool Subview
        climate_cards = self._build_climate_view_cards(capability_map)
        views.append({
            "title": "Climate & Pool",
            "path": "climate",
            "icon": "mdi:thermostat-box",
            "subview": True,
            "badges": [],
            "cards": climate_cards,
        })

        # 4. Floor Plan Subview (Full-width Interactive Studio Canvas)
        floorplan_cards: list[dict[str, Any]] = [
            {
                "type": "custom:otis-companion-card",
                "mode": "floorplan_studio",
                "default_tab": "floorplan",
                "show_stats": False,
                "show_suggestions": False,
                "show_chat": False,
                "title": "Architectural Vector Floor Plan Studio",
            }
        ]
        views.append({
            "title": "Floor Plan Studio",
            "path": "floorplan",
            "icon": "mdi:floor-plan",
            "subview": True,
            "type": "panel",
            "panel": True,
            "badges": [],
            "cards": floorplan_cards,
        })

        # 5. Dynamic Area / Room Subviews (/otis-ai/area_<slug>)
        if capability_map:
            areas_map = capability_map.get("areas", {})
            entities_list = capability_map.get("entities", [])
            valid_eids = {
                e["entity_id"]
                for e in entities_list
                if e.get("entity_id")
                and not e.get("disabled_by")
                and not e.get("hidden_by")
                and e.get("state") not in ("unknown", "unavailable", None, "")
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

                room_view = self._build_room_subview(aid, ainfo, room_entities, valid_eids)
                if room_view:
                    views.append(room_view)

        return {
            "title": OTIS_DASHBOARD_TITLE,
            "views": views,
        }

    async def _async_register_and_save_dashboard(
        self,
        item: dict[str, Any],
        dashboard_config: dict[str, Any],
        overwrite_config: bool = True,
    ) -> dict[str, Any]:
        """Persist dashboard metadata in lovelace_dashboards, write lovelace.<id>, and register live HA panel."""
        storage_dir = self._storage_dir()
        dash_id = item["id"]
        url_path = item["url_path"]

        if storage_dir:
            res = self.hass.async_add_executor_job(
                self._write_dashboard_storage_sync,
                storage_dir,
                item,
                dashboard_config,
                overwrite_config,
            )
            if hasattr(res, "__await__"):
                await res
            else:
                self._write_dashboard_storage_sync(
                    storage_dir, item, dashboard_config, overwrite_config
                )

        # Register live in Home Assistant's lovelace runtime and frontend panel if running
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
                    try:
                        await lovelace_data.dashboards[url_path].async_save(dashboard_config)
                    except Exception as save_err:
                        _LOGGER.debug("LovelaceStorage.async_save skipped: %s", save_err)

            # Sync with Home Assistant's in-memory DashboardsCollection so UI Settings > Dashboards can edit/delete
            if hasattr(self.hass, "data") and isinstance(self.hass.data, dict):
                ws_api = self.hass.data.get("websocket_api")
                if isinstance(ws_api, dict):
                    list_handler = ws_api.get("lovelace/dashboards/list")
                    if isinstance(list_handler, tuple) and list_handler:
                        ws_obj = getattr(list_handler[0], "__self__", None)
                        storage_col = getattr(ws_obj, "storage_collection", None)
                        if storage_col is not None and hasattr(storage_col, "data") and isinstance(storage_col.data, dict):
                            storage_col.data[dash_id] = dict(item)
                            if hasattr(storage_col, "_async_schedule_save"):
                                storage_col._async_schedule_save()

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
            _LOGGER.debug("Live Lovelace panel registration handled via storage fallback: %s", err)

        return {
            "success": True,
            "id": dash_id,
            "url_path": url_path,
            "title": item.get("title"),
            "require_admin": bool(item.get("require_admin", True)),
        }

    def _write_dashboard_storage_sync(
        self,
        storage_dir: str,
        item: dict[str, Any],
        dashboard_config: dict[str, Any],
        overwrite_config: bool,
    ) -> None:
        """Synchronously update .storage/lovelace_dashboards and .storage/lovelace.<id>."""
        os.makedirs(storage_dir, exist_ok=True)
        dashboards_file = os.path.join(storage_dir, "lovelace_dashboards")

        dash_store: dict[str, Any] = {
            "version": 1,
            "minor_version": 1,
            "key": "lovelace_dashboards",
            "data": {"items": []},
        }
        if os.path.exists(dashboards_file):
            try:
                with open(dashboards_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict) and isinstance(loaded.get("data"), dict):
                    dash_store = loaded
            except Exception as err:
                _LOGGER.warning("Could not parse lovelace_dashboards: %s", err)

        items: list[dict[str, Any]] = dash_store.setdefault("data", {}).setdefault("items", [])
        existing_idx = next(
            (
                i
                for i, d in enumerate(items)
                if d.get("id") == item["id"] or d.get("url_path") == item["url_path"]
            ),
            None,
        )
        if existing_idx is not None:
            # Ensure require_admin and metadata stay enforced for Otis AI dashboard
            items[existing_idx] = {**items[existing_idx], **item}
        else:
            items.append(dict(item))

        with open(dashboards_file, "w", encoding="utf-8") as f:
            json.dump(dash_store, f, indent=2)

        config_file = os.path.join(storage_dir, f"lovelace.{item['id']}")
        if overwrite_config or not os.path.exists(config_file):
            config_payload = {
                "version": 1,
                "minor_version": 1,
                "key": f"lovelace.{item['id']}",
                "data": {"config": dashboard_config},
            }
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config_payload, f, indent=2)

    async def async_analyze_dashboard_gaps(
        self, capability_map: dict[str, Any]
    ) -> dict[str, Any]:
        """Inspect existing Lovelace dashboards and identify control gaps for professional dashboards."""
        storage_dir = self._storage_dir()
        if not storage_dir:
            return {"existing_dashboards": [], "referenced_entities": set(), "proposals": []}

        res = self.hass.async_add_executor_job(
            self._analyze_dashboard_gaps_sync, storage_dir, capability_map
        )
        if hasattr(res, "__await__"):
            out = await res
            if isinstance(out, dict):
                return out
        return self._analyze_dashboard_gaps_sync(storage_dir, capability_map)

    def _analyze_dashboard_gaps_sync(
        self, storage_dir: str, capability_map: dict[str, Any]
    ) -> dict[str, Any]:
        """Synchronously inspect .storage/lovelace* files to detect control gaps."""
        dashboards_file = os.path.join(storage_dir, "lovelace_dashboards")
        existing_dashboards: list[dict[str, Any]] = []
        if os.path.exists(dashboards_file):
            try:
                with open(dashboards_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                existing_dashboards = data.get("data", {}).get("items", [])
            except Exception:
                existing_dashboards = []

        existing_url_paths = {d.get("url_path", "") for d in existing_dashboards}
        existing_ids = {d.get("id", "") for d in existing_dashboards}
        existing_titles_lower = {str(d.get("title", "")).lower() for d in existing_dashboards}

        # Collect all entity_ids referenced across all existing lovelace.* files
        referenced_entities: set[str] = set()
        try:
            for fname in os.listdir(storage_dir):
                if not fname.startswith("lovelace.") or fname.endswith(".bak"):
                    continue
                fpath = os.path.join(storage_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        raw = f.read()
                    for match in re.findall(r"\b[a-z_]+\.[a-z0-9_]+\b", raw):
                        referenced_entities.add(match)
                except Exception:
                    continue
        except Exception:
            pass

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
                "title": "Create Pro Dashboard: Climate, Pool & Comfort Operations",
                "dashboard_title": "Climate & Pool",
                "icon": "mdi:thermostat-box",
                "require_admin": False,
                "priority": "medium",
                "description": (
                    f"Detected {len(climates)} climate zones/pool heaters and {len(fans)} fans without a dedicated "
                    "environmental dashboard. Generates a professional Climate, SleepNumber & Pool control dashboard."
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

        config = self._generate_template_config(template, title, capability_map, url_path=url_path)
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

    def _build_room_subview(
        self,
        area_id: str,
        area_info: dict[str, Any],
        room_entities: list[dict[str, Any]],
        valid_eids: set[str] | None = None,
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

        room_cards: list[dict[str, Any]] = [
            {
                "type": "markdown",
                "content": f"## 📍 {area_name}\nRoom controls and live telemetry for {area_name}.",
            }
        ]

        # 1. Lighting & Power
        lights = [e["entity_id"] for e in active_entities if e.get("domain") == "light"]
        switches = [
            e["entity_id"]
            for e in active_entities
            if e.get("domain") == "switch"
            and not any(k in e.get("entity_id", "").lower() for k in ("pool", "spa", "pump", "heater", "thermostat"))
        ]
        if lights:
            room_cards.append({
                "type": "grid",
                "title": "Lighting",
                "columns": min(2, len(lights)),
                "square": False,
                "cards": [
                    {
                        "type": "tile",
                        "entity": eid,
                        "features": [{"type": "light-brightness"}],
                    }
                    for eid in lights
                ],
            })
        if switches:
            room_cards.append({
                "type": "grid",
                "title": "Power & Outlets",
                "columns": min(2, len(switches)),
                "square": False,
                "cards": [{"type": "tile", "entity": eid} for eid in switches],
            })

        # 2. Media & Audio
        media_players = [e["entity_id"] for e in active_entities if e.get("domain") == "media_player"]
        if media_players:
            room_cards.append({
                "type": "grid",
                "title": "Media & Audio",
                "columns": min(2, len(media_players)),
                "square": False,
                "cards": [
                    {
                        "type": "tile",
                        "entity": eid,
                        "features": [{"type": "media-player-volume-slider"}],
                    }
                    for eid in media_players
                ],
            })

        # 3. Climate & Comfort
        climates = [e["entity_id"] for e in active_entities if e.get("domain") == "climate"]
        fans = [e["entity_id"] for e in active_entities if e.get("domain") in ("fan", "humidifier")]
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
            for c_eid in climates:
                room_cards.append({
                    "type": "thermostat",
                    "entity": c_eid,
                    "features": [{"type": "climate-hvac-modes"}],
                })
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

        # 4. Access & Sensors
        locks = [e["entity_id"] for e in active_entities if e.get("domain") == "lock"]
        covers = [e["entity_id"] for e in active_entities if e.get("domain") == "cover"]
        cameras = [e["entity_id"] for e in active_entities if e.get("domain") == "camera"]
        sec_sensors = [
            e["entity_id"]
            for e in active_entities
            if e["entity_id"] not in climate_sensors
            and e.get("domain") in ("binary_sensor", "sensor")
        ]
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
        if cameras:
            room_cards.append({
                "type": "grid",
                "title": "Cameras",
                "columns": min(2, len(cameras)),
                "square": False,
                "cards": [
                    {"type": "picture-entity", "entity": c_eid, "camera_view": "auto"}
                    for c_eid in cameras[:4]
                ],
            })
        if sec_sensors:
            room_cards.append({
                "type": "entities",
                "title": "Occupancy & Sensors",
                "state_color": True,
                "entities": sec_sensors[:8],
            })

        return {
            "title": area_name,
            "path": f"area_{slug}",
            "icon": "mdi:door-open",
            "subview": True,
            "badges": [],
            "cards": room_cards,
        }

    def _build_media_view_cards(self, capability_map: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Build cards for Media Studio subview or standalone dashboard."""
        if not capability_map:
            return [
                {
                    "type": "markdown",
                    "content": (
                        "## 🎵 Whole-Home Media & Matrix Audio\n"
                        "Control upstream streaming bridges, route audio across Matrix Amp room zones, and manage Theater displays."
                    ),
                }
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

        # Fallback: if no matrix amp or streamers detected, include all discovered media players
        all_mps = _filter_valid([e["entity_id"] for e in entities if e.get("domain") == "media_player"])
        if not matrix_zones and all_mps:
            matrix_zones = [m for m in all_mps if m not in tvs and m not in streamers]

        cards: list[dict[str, Any]] = [
            {
                "type": "markdown",
                "content": (
                    "## 🎵 Whole-Home Media & Matrix Audio\n"
                    "Control upstream input bridges, route audio across room speaker zones, and manage Theater displays."
                ),
            }
        ]

        if streamers:
            cards.append({
                "type": "grid",
                "title": "Upstream Audio Streamers & Bridges",
                "columns": min(2, len(streamers)),
                "square": False,
                "cards": [{"type": "media-control", "entity": s} for s in streamers[:4]],
            })

        if matrix_zones:
            cards.append({
                "type": "grid",
                "title": "Room Speaker & Amplifier Zones",
                "columns": 2,
                "square": False,
                "cards": [
                    {
                        "type": "tile",
                        "entity": zid,
                        "features": [{"type": "media-player-volume-slider"}],
                    }
                    for zid in matrix_zones
                ],
            })

        if helpers:
            cards.append({
                "type": "entities",
                "title": "Audio Source & Speaker Routing Controls",
                "state_color": True,
                "entities": helpers[:10],
            })

        if tvs:
            cards.append({
                "type": "grid",
                "title": "Cinema & Room Displays",
                "columns": min(2, len(tvs)),
                "square": False,
                "cards": [{"type": "tile", "entity": tv} for tv in tvs[:6]],
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

    def _build_security_view_cards(self, capability_map: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Build cards for Security Center subview or standalone dashboard."""
        if not capability_map:
            return [
                {
                    "type": "markdown",
                    "content": (
                        "## 🛡️ Security, Locks & Perimeter Center\n"
                        "Live status and controls for alarm panels, smart locks, garage doors, occupancy sensors, and perimeter cameras."
                    ),
                }
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

        cards: list[dict[str, Any]] = [
            {
                "type": "markdown",
                "content": (
                    "## 🛡️ Security, Locks & Perimeter Command Center\n"
                    "Live control of alarm panels, smart locks, garage doors, occupancy sensors, and perimeter cameras."
                ),
            }
        ]

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
                    {"type": "picture-entity", "entity": cam, "camera_view": "auto"}
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

    def _build_climate_view_cards(self, capability_map: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Build cards for Climate & Pool subview or standalone dashboard."""
        if not capability_map:
            return [
                {
                    "type": "markdown",
                    "content": (
                        "## 🌡️ Climate, Pool & Comfort Operations\n"
                        "Unified environmental controls for HVAC thermostats, ceiling fans, pool telemetry, and SleepNumber comfort."
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
        pool_ents = _filter_valid([
            e["entity_id"]
            for e in entities
            if e.get("domain") in ("sensor", "binary_sensor", "switch", "light")
            and any(k in e.get("entity_id", "").lower() for k in ("pentair", "pool", "waterguru", "spa"))
            and "pre_release" not in e.get("entity_id", "").lower()
        ])
        sleep_ents = _filter_valid([
            e["entity_id"]
            for e in entities
            if e.get("domain") in ("select", "number", "sensor", "binary_sensor")
            and "sleepnumber" in e.get("entity_id", "").lower()
        ])

        cards: list[dict[str, Any]] = [
            {
                "type": "markdown",
                "content": (
                    "## 🌡️ Climate, Pool & Comfort Operations\n"
                    "Unified environmental controls for HVAC thermostats, ceiling fans, pool & water telemetry, and SleepNumber comfort."
                ),
            }
        ]

        if climates:
            cards.append({
                "type": "grid",
                "title": "HVAC Thermostats & Pool Heat",
                "columns": min(2, len(climates)),
                "square": False,
                "cards": [
                    {
                        "type": "thermostat",
                        "entity": c,
                        "features": [{"type": "climate-hvac-modes"}],
                    }
                    for c in climates[:4]
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

        if pool_ents:
            cards.append({
                "type": "entities",
                "title": "Pool Equipment & Water Chemistry Telemetry",
                "state_color": True,
                "entities": pool_ents[:10],
            })

        if sleep_ents:
            cards.append({
                "type": "entities",
                "title": "SleepNumber Bed Climate, Firmness & Occupancy",
                "state_color": True,
                "entities": sleep_ents[:10],
            })

        if not climates and not fans and not pool_ents and not sleep_ents:
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
    ) -> dict[str, Any]:
        """Build professional-grade Lovelace Hub-and-Spoke view/card definitions using verified active entities only."""
        if not url_path:
            url_path = f"otis-{template.replace('_', '-')}"

        dash_url = url_path.strip("/")

        if template == "whole_home":
            areas_map = capability_map.get("areas", {})
            entities_list = capability_map.get("entities", [])
            valid_eids = {
                e["entity_id"]
                for e in entities_list
                if e.get("entity_id")
                and not e.get("disabled_by")
                and not e.get("hidden_by")
                and e.get("state") not in ("unknown", "unavailable", None, "")
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

                room_view = self._build_room_subview(aid, ainfo, room_entities, valid_eids)
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
                and e.get("state") not in ("unknown", "unavailable", None, "")
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

            # Spoke 1: Speaker Zones
            zones_cards: list[dict[str, Any]] = [
                {
                    "type": "markdown",
                    "content": "## 🔊 Matrix & Speaker Zones\nIndependent volume and source selection for every room zone.",
                }
            ]
            if matrix_zones:
                zones_cards.append({
                    "type": "grid",
                    "title": "Speaker Zones",
                    "columns": 2,
                    "square": False,
                    "cards": [
                        {
                            "type": "tile",
                            "entity": zid,
                            "features": [{"type": "media-player-volume-slider"}],
                        }
                        for zid in matrix_zones
                    ],
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
                streamers_cards.append({
                    "type": "grid",
                    "title": "Audio Streamers",
                    "columns": min(2, len(streamers)),
                    "square": False,
                    "cards": [{"type": "media-control", "entity": s} for s in streamers[:6]],
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
                cinema_cards.append({
                    "type": "grid",
                    "title": "Displays & TVs",
                    "columns": min(2, len(tvs)),
                    "square": False,
                    "cards": [{"type": "tile", "entity": tv} for tv in tvs[:8]],
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
            if streamers:
                hub_cards.append({
                    "type": "grid",
                    "title": "Active Upstream Streamers",
                    "columns": min(2, len(streamers)),
                    "square": False,
                    "cards": [{"type": "media-control", "entity": s} for s in streamers[:2]],
                })
            if matrix_zones:
                hub_cards.append({
                    "type": "grid",
                    "title": "Primary Speaker Zones",
                    "columns": 2,
                    "square": False,
                    "cards": [
                        {
                            "type": "tile",
                            "entity": zid,
                            "features": [{"type": "media-player-volume-slider"}],
                        }
                        for zid in matrix_zones[:4]
                    ],
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
        sleep_ents = _filter_valid([
            e["entity_id"]
            for e in entities
            if e.get("domain") in ("select", "number", "sensor", "binary_sensor")
            and "sleepnumber" in e.get("entity_id", "").lower()
        ])

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
