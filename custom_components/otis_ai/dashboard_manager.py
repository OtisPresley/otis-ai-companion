"""Lovelace Dashboard Manager & Professional Dashboard Generator for Otis AI Companion."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
import yaml

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
        media_cards = (
            self._generate_template_config("media_studio", "Media Studio", capability_map)["views"][0]["cards"]
            if capability_map
            else [
                {
                    "type": "markdown",
                    "content": (
                        "## 🎵 Whole-Home Media & Matrix Audio\n"
                        "Control upstream streaming bridges, route audio across Matrix Amp room zones, and manage Theater displays."
                    ),
                }
            ]
        )
        views.append({
            "title": "Media Studio",
            "path": "media",
            "icon": "mdi:speaker-multiple",
            "subview": True,
            "badges": [],
            "cards": media_cards,
        })

        # 2. Security Center Subview
        security_cards = (
            self._generate_template_config("security_center", "Security Center", capability_map)["views"][0]["cards"]
            if capability_map
            else [
                {
                    "type": "markdown",
                    "content": (
                        "## 🛡️ Security, Locks & Perimeter Center\n"
                        "Live status and controls for alarm panels, smart locks, garage doors, occupancy sensors, and perimeter cameras."
                    ),
                }
            ]
        )
        views.append({
            "title": "Security Center",
            "path": "security",
            "icon": "mdi:shield-home",
            "subview": True,
            "badges": [],
            "cards": security_cards,
        })

        # 3. Climate & Pool Subview
        climate_cards = (
            self._generate_template_config("climate_energy", "Climate & Pool", capability_map)["views"][0]["cards"]
            if capability_map
            else [
                {
                    "type": "markdown",
                    "content": (
                        "## 🌡️ Climate, Pool & Comfort Operations\n"
                        "Unified environmental controls for HVAC thermostats, ceiling fans, pool telemetry, and SleepNumber comfort."
                    ),
                }
            ]
        )
        views.append({
            "title": "Climate & Pool",
            "path": "climate",
            "icon": "mdi:thermostat-box",
            "subview": True,
            "badges": [],
            "cards": climate_cards,
        })

        # 4. Floor Plan Subview
        floorplan_yaml = capability_map.get("floorplan", {}).get("lovelace_yaml") if capability_map else None
        floorplan_cards: list[dict[str, Any]] = []
        if floorplan_yaml:
            try:
                fp_parsed = yaml.safe_load(floorplan_yaml)
                if isinstance(fp_parsed, dict):
                    floorplan_cards.append(fp_parsed)
            except Exception as err:
                _LOGGER.debug("Error parsing floorplan lovelace yaml: %s", err)
        if not floorplan_cards:
            floorplan_cards.append({
                "type": "markdown",
                "content": (
                    "## 🗺️ Architectural Vector Floor Plan Studio\n"
                    "Interactive spatial floor plan with live glowing entity badges and inspection drawers.\n\n"
                    "👉 Use the **Floor Plan** tab on the **AI Command Center** to record or upload a video walkthrough."
                ),
            })
        views.append({
            "title": "Floor Plan Studio",
            "path": "floorplan",
            "icon": "mdi:floor-plan",
            "subview": True,
            "badges": [],
            "cards": floorplan_cards,
        })

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

        return {
            "existing_dashboards": existing_dashboards,
            "referenced_entities_count": len(referenced_entities),
            "proposals": proposals,
        }

    async def async_create_professional_dashboard(
        self, payload: dict[str, Any], capability_map: dict[str, Any]
    ) -> dict[str, Any]:
        """Generate and register a professional multi-view Lovelace dashboard from a template."""
        dash_id = payload.get("dashboard_id", "otis_pro_dashboard")
        url_path = payload.get("url_path", "otis-pro-dashboard")
        title = payload.get("dashboard_title") or payload.get("title") or "Otis Pro"
        icon = payload.get("icon", "mdi:view-dashboard-variant")
        require_admin = bool(payload.get("require_admin", False))
        template = payload.get("template", "media_studio")

        config = self._generate_template_config(template, title, capability_map)
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

    def _generate_template_config(
        self, template: str, title: str, capability_map: dict[str, Any]
    ) -> dict[str, Any]:
        """Build professional-grade Lovelace view/card definitions using verified active entities only."""
        entities = capability_map.get("entities", [])
        media_topo = capability_map.get("media_topology", {})
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

        if template == "media_studio":
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

            cards: list[dict[str, Any]] = [
                {
                    "type": "markdown",
                    "content": (
                        "## 🎵 Whole-Home Matrix Audio & Cinema Studio\n"
                        "Control upstream input bridges, route audio across Matrix Amp room zones, and manage Theater displays."
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
                    "title": "Matrix Amp Room Speaker Zones",
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
                    "columns": 2,
                    "square": False,
                    "cards": [{"type": "tile", "entity": tv} for tv in tvs[:6]],
                })
            return {
                "title": title,
                "views": [
                    {
                        "title": "Media Studio",
                        "path": "default_view",
                        "icon": "mdi:speaker-multiple",
                        "cards": cards,
                    }
                ],
            }

        if template == "security_center":
            alarms = _filter_valid(sec_topo.get("alarm_panels", []))
            locks = _filter_valid(sec_topo.get("locks", []))
            garages = _filter_valid(sec_topo.get("garage_covers", []))
            cameras = _filter_valid(sec_topo.get("cameras", []))
            beds = _filter_valid(sec_topo.get("bed_occupancy_sensors", []))
            persons = _filter_valid(sec_topo.get("persons", []))
            contacts = _filter_valid(sec_topo.get("perimeter_contact_sensors", []))

            cards = [
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
                    "columns": 2,
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
                    "columns": 2,
                    "square": False,
                    "cards": [
                        {"type": "picture-entity", "entity": cam, "camera_view": "auto"}
                        for cam in cameras[:6]
                    ],
                })
            return {
                "title": title,
                "views": [
                    {
                        "title": "Security Center",
                        "path": "default_view",
                        "icon": "mdi:shield-home",
                        "cards": cards,
                    }
                ],
            }

        # Default: climate_energy
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
        cards = [
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
                "columns": 2,
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
                "columns": 2,
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
        return {
            "title": title,
            "views": [
                {
                    "title": "Climate & Pool",
                    "path": "default_view",
                    "icon": "mdi:thermostat-box",
                    "cards": cards,
                }
            ],
        }
