"""The Otis AI Companion custom integration for Home Assistant."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime
from typing import Any, Literal
import yaml

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse
from homeassistant.helpers import (
    area_registry as ar,
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    intent,
)
from homeassistant.components import conversation

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .const import (
    DOMAIN,
    CONF_CONVERSATION_AGENT,
    SERVICE_GET_CAPABILITY_MAP,
    SERVICE_GET_SUGGESTIONS,
    SERVICE_APPLY_SUGGESTION,
    SERVICE_CHAT,
    SERVICE_GET_SPATIAL_MAP,
    SERVICE_UPDATE_SPATIAL_MAP,
    SERVICE_GENERATE_FLOORPLAN,
    SERVICE_UPDATE_FLOORPLAN_LAYOUT,
    SERVICE_GENERATE_THEME,
    SERVICE_APPLY_THEME,
    SERVICE_LIST_THEMES,
    SERVICE_DELETE_THEME,
    SERVICE_RUN_SENTINEL_WATCHDOG,
    SERVICE_REMEDIATE_ANOMALY,
    SERVICE_GET_SENTINEL_TELEMETRY,
    SERVICE_IGNORE_SENTINEL_ALERT,
    SERVICE_CREATE_COMMAND_CENTER,
)
from .automation_manager import AutomationManager
from .dashboard_manager import DashboardManager
from .sentinel_manager import SentinelManager
from .spatial_manager import (
    SpatialGraphManager,
    build_area_lookup_map,
    classify_area_entities,
    is_contact_sensor,
    is_motion_sensor as is_motion_sensor,
    resolve_area_identifier,
)
from .floorplan_parser import FloorplanParser
from .theme_manager import PRESET_THEMES, ThemeManager, slugify_theme_name

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


class OtisWalkthroughUploadView(HomeAssistantView):
    """HTTP view to accept video walkthrough uploads and trigger floor plan parsing."""

    url = "/api/otis_ai/upload_walkthrough"
    name = "api:otis_ai:upload_walkthrough"
    requires_auth = False

    def __init__(
        self,
        hass: HomeAssistant,
        floorplan_parser: FloorplanParser,
        engine: Any,
        spatial_manager: SpatialGraphManager | None = None,
    ) -> None:
        """Initialize the upload view."""
        self.hass = hass
        self.floorplan_parser = floorplan_parser
        self.engine = engine
        self.spatial_manager = spatial_manager or getattr(engine, "spatial_manager", None)
        self._active: bool = False
        self._stage: str = "Idle"
        self._discovered_areas: list[str] = []

    def _set_progress(self, stage: str, discovered: list[str] | None = None, active: bool = True) -> None:
        """Update live walkthrough upload and analysis progress state."""
        self._stage = stage
        if discovered is not None:
            self._discovered_areas = list(discovered)
        self._active = active

    async def get(self, request: web.Request) -> web.Response:
        """Return current walkthrough processing status for live UI progress updates."""
        return web.json_response({
            "active": self._active,
            "stage": self._stage,
            "discovered_areas": list(self._discovered_areas),
        })

    async def post(self, request: web.Request) -> web.Response:
        """Handle uploaded video file(s), overwriting previous uploads to manage disk space."""
        _LOGGER.info("Received video walkthrough upload request")
        upload_dir = self.hass.config.path("www")
        os.makedirs(upload_dir, exist_ok=True)
        self._set_progress("Uploading videos", [], active=True)

        try:
            # Remove any previous walkthrough video/audio files first to manage space on HA
            await self.hass.async_add_executor_job(
                self.floorplan_parser.cleanup_previous_uploads, upload_dir
            )

            saved_videos: list[str] = []
            spoken_order: str | None = None

            def _append_chunk(path: str, data_bytes: bytes, mode: str = "ab") -> None:
                with open(path, mode) as f:
                    f.write(data_bytes)

            if request.content_type.startswith("multipart/"):
                reader = await request.multipart()
                file_idx = 0
                while True:
                    field = await reader.next()
                    if field is None:
                        break
                    if field.name in ("file", "files"):
                        file_idx += 1
                        fname = (
                            "walkthrough_upload.mp4"
                            if file_idx == 1
                            else f"walkthrough_upload_{file_idx}.mp4"
                        )
                        v_dest = os.path.join(upload_dir, fname)
                        await self.hass.async_add_executor_job(_append_chunk, v_dest, b"", "wb")
                        while True:
                            chunk = await field.read_chunk()
                            if not chunk:
                                break
                            await self.hass.async_add_executor_job(_append_chunk, v_dest, chunk, "ab")
                        saved_videos.append(v_dest)
                        _LOGGER.info(
                            "Walkthrough video #%d saved to %s (%d bytes)",
                            file_idx,
                            v_dest,
                            os.path.getsize(v_dest),
                        )
                    elif field.name == "spoken_order":
                        spoken_order = (await field.text()).strip()
            else:
                v_dest = os.path.join(upload_dir, "walkthrough_upload.mp4")
                data = await request.read()
                await self.hass.async_add_executor_job(_append_chunk, v_dest, data, "wb")
                saved_videos.append(v_dest)
                _LOGGER.info(
                    "Walkthrough video saved to %s (%d bytes)",
                    v_dest,
                    os.path.getsize(v_dest),
                )

            self._set_progress("Analyzing videos", [], active=True)

            # Build initial capability map to obtain registered Home Assistant areas
            cap_map = await self.engine.async_build_capability_map()
            areas_dict = cap_map.get("areas", {})
            area_list = [
                {"id": aid, "name": ainfo.get("name", aid)}
                for aid, ainfo in areas_dict.items()
            ]
            area_name_by_id = {aid: ainfo.get("name", aid) for aid, ainfo in areas_dict.items()}

            combined_ordered_areas: list[str] = []
            combined_adjacencies: list[list[str]] = []
            transcripts: list[str] = []
            discovered_names: list[str] = []

            # Extract audio + keyframes and analyze speech callouts & room transitions for each uploaded video
            for idx, v_path in enumerate(saved_videos, start=1):
                audio_mp3 = os.path.join(
                    upload_dir,
                    "walkthrough_audio.mp3" if idx == 1 else f"walkthrough_audio_{idx}.mp3",
                )
                extracted = await self.floorplan_parser.async_extract_audio_from_video(
                    v_path, audio_mp3
                )
                audio_target = audio_mp3
                if not extracted:
                    audio_wav = os.path.join(
                        upload_dir,
                        "walkthrough_audio.wav" if idx == 1 else f"walkthrough_audio_{idx}.wav",
                    )
                    extracted = await self.floorplan_parser.async_extract_audio_from_video(
                        v_path, audio_wav
                    )
                    audio_target = audio_wav

                frame_dir = os.path.join(upload_dir, f"_frames_{idx}")
                frames = await self.floorplan_parser.async_extract_keyframes_from_video(
                    v_path, frame_dir, prefix=f"v{idx}", max_frames=6
                )

                if extracted:
                    analysis = await self.floorplan_parser.async_analyze_walkthrough_audio(
                        audio_target, area_list, frame_paths=frames
                    )
                    if analysis.get("transcript"):
                        transcripts.append(analysis["transcript"])
                    seg_areas = analysis.get("ordered_areas") or []
                    for aid in seg_areas:
                        if aid not in combined_ordered_areas:
                            combined_ordered_areas.append(aid)
                            friendly_name = area_name_by_id.get(aid, aid)
                            if friendly_name not in discovered_names:
                                discovered_names.append(friendly_name)
                            self._set_progress(
                                f"Discovered {friendly_name}", discovered_names, active=True
                            )
                            await asyncio.sleep(0.25)

                    # Add consecutive areas within this video segment as adjacent
                    for i in range(len(seg_areas) - 1):
                        pair = [seg_areas[i], seg_areas[i + 1]]
                        if pair[0] != pair[1] and pair not in combined_adjacencies:
                            combined_adjacencies.append(pair)
                    for pair in analysis.get("adjacencies") or []:
                        if (
                            isinstance(pair, list)
                            and len(pair) == 2
                            and pair[0] != pair[1]
                            and pair not in combined_adjacencies
                        ):
                            combined_adjacencies.append(pair)

                # Clean up temporary extracted frames directory
                if os.path.isdir(frame_dir):
                    await self.hass.async_add_executor_job(shutil.rmtree, frame_dir, True)

            # Update Spatial Adjacency Graph with transitions discovered from the walkthrough
            if self.spatial_manager and combined_adjacencies:
                for a1, a2 in combined_adjacencies:
                    try:
                        await self.spatial_manager.async_update_connection(
                            a1, a2, connected=True, connection_type="door"
                        )
                    except Exception as adj_err:
                        _LOGGER.debug("Could not connect %s <-> %s: %s", a1, a2, adj_err)
                # Refresh capability map so SVG doorways reflect updated adjacencies
                if hasattr(self.engine, "invalidate_cache"):
                    self.engine.invalidate_cache()
                cap_map = await self.engine.async_build_capability_map()

            # Combine user override (if provided) with AI-extracted spoken order
            final_order: list[str] = []
            if spoken_order:
                for item in spoken_order.split(","):
                    if item.strip():
                        final_order.append(item.strip())
            for aid in combined_ordered_areas:
                if aid not in final_order:
                    final_order.append(aid)

            result = await self.floorplan_parser.async_generate_svg_floorplan(
                cap_map,
                video_path=saved_videos[0] if saved_videos else None,
                spoken_order=final_order if final_order else None,
                walkthrough_completed=True,
                transcripts=transcripts,
            )

            if hasattr(self.engine, "invalidate_cache"):
                self.engine.invalidate_cache()
            self._set_progress("Done", discovered_names, active=False)

            return web.json_response({
                "success": True,
                "message": (
                    f"Processed {len(saved_videos)} walkthrough video(s) and generated floor plan!"
                ),
                "videos_processed": len(saved_videos),
                "detected_areas": combined_ordered_areas,
                "detected_area_names": discovered_names,
                "transcripts": transcripts,
                "url": result.get("url"),
                "room_count": result.get("room_count"),
                "zones": result.get("zones"),
                "walkthrough_completed": True,
                "lovelace_yaml": result.get("lovelace_yaml"),
            })
        except Exception as err:
            self._set_progress(f"Error: {err}", [], active=False)
            _LOGGER.error("Failed to process walkthrough video: %s", err)
            return web.json_response({"success": False, "error": str(err)}, status=500)



async def async_register_frontend_paths(hass: HomeAssistant) -> None:
    """Register static path for the Otis Lovelace card."""
    if hasattr(hass, "http"):
        frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
        try:
            from homeassistant.components.http import StaticPathConfig
            await hass.http.async_register_static_paths([
                StaticPathConfig("/otis_ai_card", frontend_path, cache_headers=False)
            ])
        except Exception:
            try:
                hass.http.register_static_path("/otis_ai_card", frontend_path, cache_headers=False)
            except Exception as err:
                _LOGGER.debug("Could not register static path for otis_ai_card: %s", err)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Otis AI Companion integration."""
    await async_register_frontend_paths(hass)
    if DOMAIN in config and not hass.config_entries.async_entries(DOMAIN):
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data=config.get(DOMAIN) or {},
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Otis AI Companion from a config entry."""
    _LOGGER.debug("Setting up Otis AI Companion entry: %s", entry.entry_id)
    _LOGGER.debug("Configured options: %s", entry.data)
    
    await async_register_frontend_paths(hass)
    hass.data.setdefault(DOMAIN, {})
    
    # Initialize the Spatial Graph, Discovery Engine, Automation Manager, Floorplan Parser, Dashboard Manager, Theme Manager, and Sentinel Watchdog
    spatial_manager = SpatialGraphManager(hass)
    floorplan_parser = FloorplanParser(hass)
    automation_manager = AutomationManager(hass)
    dashboard_manager = DashboardManager(hass, floorplan_parser=floorplan_parser)
    theme_manager = ThemeManager(hass)
    sentinel_manager = SentinelManager(hass)
    await asyncio.gather(
        spatial_manager.async_load(),
        floorplan_parser.async_load(),
        dashboard_manager.async_ensure_admin_companion_dashboard(),
        dashboard_manager.async_ensure_user_command_center_dashboard(),
        sentinel_manager.async_load_preferences(),
    )
    engine = DiscoveryEngine(
        hass,
        spatial_manager=spatial_manager,
        floorplan_parser=floorplan_parser,
        dashboard_manager=dashboard_manager,
        theme_manager=theme_manager,
        sentinel_manager=sentinel_manager,
    )

    # Register Walkthrough Upload View
    if hasattr(hass, "http"):
        try:
            hass.http.register_view(
                OtisWalkthroughUploadView(hass, floorplan_parser, engine, spatial_manager=spatial_manager)
            )
        except Exception as err:
            _LOGGER.debug("Could not register walkthrough upload view: %s", err)

    # Register the conversation agent
    agent = OtisAIConversationAgent(
        hass,
        entry,
        engine,
        automation_manager,
        spatial_manager=spatial_manager,
        theme_manager=theme_manager,
        sentinel_manager=sentinel_manager,
    )
    if hasattr(conversation, "async_register_agent"):
        conversation.async_register_agent(hass, agent)
    else:
        conversation.async_set_agent(hass, entry, agent)
    
    hass.data[DOMAIN][entry.entry_id] = {
        "data": {**entry.data, **getattr(entry, "options", {})},
        "engine": engine,
        "agent": agent,
        "automation_manager": automation_manager,
        "spatial_manager": spatial_manager,
        "floorplan_parser": floorplan_parser,
        "dashboard_manager": dashboard_manager,
        "theme_manager": theme_manager,
        "sentinel_manager": sentinel_manager,
    }

    async def _async_update_listener(hass_inst: HomeAssistant, updated_entry: ConfigEntry) -> None:
        """Handle options update without requiring restart."""
        entry_store = hass_inst.data.get(DOMAIN, {}).get(updated_entry.entry_id)
        if entry_store is not None:
            entry_store["data"] = {**updated_entry.data, **getattr(updated_entry, "options", {})}
            eng_inst = entry_store.get("engine")
            if eng_inst and hasattr(eng_inst, "invalidate_cache"):
                eng_inst.invalidate_cache()

    if hasattr(entry, "async_on_unload") and hasattr(entry, "add_update_listener"):
        try:
            entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        except Exception as err:
            _LOGGER.debug("Could not register entry update listener: %s", err)

    def _get_active_managers():
        entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        eng = entry_data.get("engine", engine)
        mgr = entry_data.get("automation_manager", automation_manager)
        s_mgr = entry_data.get("spatial_manager", spatial_manager)
        fp = entry_data.get("floorplan_parser", floorplan_parser)
        tm = entry_data.get("theme_manager", theme_manager)
        sm = entry_data.get("sentinel_manager", sentinel_manager)
        dm = entry_data.get("dashboard_manager", dashboard_manager)
        return eng, mgr, s_mgr, fp, tm, sm, dm

    async def handle_get_capability_map(call) -> ServiceResponse:
        """Handle service call to get the capability map."""
        _LOGGER.debug("Service 'get_capability_map' triggered")
        eng, *_ = _get_active_managers()
        capability_map = await eng.async_build_capability_map()
        capability_map["conversation_agent_id"] = entry.entry_id
        return capability_map

    async def handle_get_suggestions(call) -> ServiceResponse:
        """Handle service call to retrieve proactive suggestions."""
        _LOGGER.debug("Service 'get_suggestions' triggered")
        eng, *_ = _get_active_managers()
        capability_map = await eng.async_build_capability_map()
        return {"suggestions": capability_map.get("proactive_suggestions", [])}

    async def handle_apply_suggestion(call) -> ServiceResponse:
        """Handle service call to apply a proactive suggestion."""
        suggestion_id = call.data.get("suggestion_id")
        _LOGGER.debug("Service 'apply_suggestion' triggered for ID: %s", suggestion_id)
        if not suggestion_id:
            return {"success": False, "error": "Missing suggestion_id parameter"}

        eng, mgr, *_, sm, _ = _get_active_managers()
        target = None
        if hasattr(eng, "get_cached_suggestion") and callable(getattr(eng, "get_cached_suggestion", None)):
            cached = eng.get_cached_suggestion(suggestion_id)
            if isinstance(cached, dict):
                target = cached

        if target is None and not (call.data.get("action_type") and call.data.get("action_payload")):
            capability_map = await eng.async_build_capability_map()
            suggestions = capability_map.get("proactive_suggestions", [])
            target = next((s for s in suggestions if s["id"] == suggestion_id), None)

        action_type = call.data.get("action_type") or (target.get("action_type") if target else None)
        payload = call.data.get("action_payload") or (target.get("action_payload", {}) if target else {})

        if not target and not action_type:
            return {"success": False, "error": f"Suggestion '{suggestion_id}' not found or already resolved"}

        def _invalidate():
            if hasattr(eng, "invalidate_cache") and callable(getattr(eng, "invalidate_cache", None)):
                eng.invalidate_cache()

        if action_type == "remediate_sentinel_anomaly":
            res = await sm.async_remediate_anomaly(
                payload.get("anomaly_id", suggestion_id),
                action=payload.get("action"),
            )
            _invalidate()
            return res

        if action_type in ("ignore_sentinel_alert", "sentinel_alert_actions"):
            aid = payload.get("anomaly_id", suggestion_id)
            cat = payload.get("category")
            if payload.get("all_in_category") and cat:
                await sm.async_ignore_category(cat)
                msg = f"All {cat} alerts muted."
            elif aid:
                await sm.async_ignore_anomaly(aid)
                msg = "Alert muted."
            else:
                msg = "Alert dismissed."
            _invalidate()
            return {"success": True, "message": msg}

        if action_type == "create_automation":
            auto_id = await mgr.async_write_automation(payload)
            await mgr.async_reload_automations()
            _invalidate()
            return {
                "success": True,
                "message": f"Successfully created automation '{payload.get('alias', auto_id)}'",
                "id": auto_id,
            }
        elif action_type == "create_script":
            script_key = (target.get("id") if target else suggestion_id) or "custom_script"
            await mgr.async_write_script(script_key, payload)
            await mgr.async_reload_scripts()
            _invalidate()
            return {
                "success": True,
                "message": f"Successfully created script '{payload.get('alias', script_key)}'",
                "id": script_key,
            }
        elif action_type == "cleanup_orphans":
            entity_reg = er.async_get(hass)
            cleaned = []
            for eid in payload.get("entity_ids", []):
                try:
                    entity_reg.async_remove(eid)
                    cleaned.append(eid)
                except Exception as err:
                    _LOGGER.warning("Could not remove orphaned entity %s: %s", eid, err)
            _invalidate()
            return {
                "success": True,
                "message": f"Cleaned up {len(cleaned)} orphaned entities",
                "cleaned_entities": cleaned,
            }
        elif action_type == "create_package":
            created_scripts = []
            created_autos = []
            raw_scripts = payload.get("scripts") or {}
            if isinstance(raw_scripts, dict):
                script_items = list(raw_scripts.items())
            elif isinstance(raw_scripts, list):
                script_items = []
                for idx, s_data in enumerate(raw_scripts):
                    if isinstance(s_data, dict):
                        alias_slug = re.sub(r"[^a-z0-9_]+", "_", str(s_data.get("alias", f"package_script_{idx}")).lower()).strip("_")
                        script_items.append((alias_slug or f"package_script_{idx}", s_data))
            else:
                script_items = []

            for s_key, s_data in script_items:
                await mgr.async_write_script(s_key, s_data)
                created_scripts.append(s_key)
            if created_scripts:
                await mgr.async_reload_scripts()

            for a_data in payload.get("automations") or []:
                a_id = await mgr.async_write_automation(dict(a_data))
                created_autos.append(a_id)
            if created_autos:
                await mgr.async_reload_automations()

            _invalidate()
            return {
                "success": True,
                "message": (
                    f"Deployed coordinator package ({len(created_scripts)} script(s), "
                    f"{len(created_autos)} automation(s))"
                ),
                "scripts": created_scripts,
                "automations": created_autos,
            }
        elif action_type == "auto_assign_areas":
            device_reg = dr.async_get(hass)
            entity_reg = er.async_get(hass)
            assigned_count = 0
            for item in payload.get("assignments", []):
                dev_id = item.get("device_id")
                ent_id = item.get("entity_id")
                area_id = item.get("area_id")
                if not area_id:
                    continue
                try:
                    if dev_id and hasattr(device_reg, "async_update_device"):
                        device_reg.async_update_device(dev_id, area_id=area_id)
                        assigned_count += 1
                    elif ent_id and hasattr(entity_reg, "async_update_entity"):
                        entity_reg.async_update_entity(ent_id, area_id=area_id)
                        assigned_count += 1
                except Exception as err:
                    _LOGGER.warning("Could not assign area %s to %s: %s", area_id, dev_id or ent_id, err)

            for dev_id, area_id in (payload.get("device_assignments") or {}).items():
                if not dev_id or not area_id:
                    continue
                try:
                    if hasattr(device_reg, "async_update_device"):
                        device_reg.async_update_device(dev_id, area_id=area_id)
                        assigned_count += 1
                except Exception as err:
                    _LOGGER.warning("Could not assign area %s to device %s: %s", area_id, dev_id, err)

            for ent_id, area_id in (payload.get("entity_assignments") or {}).items():
                if not ent_id or not area_id:
                    continue
                try:
                    if hasattr(entity_reg, "async_update_entity"):
                        entity_reg.async_update_entity(ent_id, area_id=area_id)
                        assigned_count += 1
                except Exception as err:
                    _LOGGER.warning("Could not assign area %s to entity %s: %s", area_id, ent_id, err)

            _invalidate()
            return {
                "success": True,
                "message": f"Automatically assigned {assigned_count} device(s)/entities to their matching rooms!",
                "assigned_count": assigned_count,
            }
        elif action_type == "improve_automation":
            res = await mgr.async_improve_automation(payload)
            _invalidate()
            return res
        elif action_type == "optimize_system_config":
            res = await mgr.async_optimize_system_config(payload)
            _invalidate()
            return res
        elif action_type == "create_dashboard":
            entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
            d_mgr = entry_data.get("dashboard_manager", dashboard_manager)
            cap_map = await eng.async_build_capability_map()
            res = await d_mgr.async_create_professional_dashboard(payload, cap_map)
            _invalidate()
            return {
                "success": True,
                "message": (
                    f"Created professional dashboard '{res.get('title')}' at /{res.get('url_path')} "
                    "(added to Home Assistant sidebar)!"
                ),
                "dashboard": res,
            }
        elif action_type == "sync_ha_floors":
            area_reg = ar.async_get(hass)
            synced_areas = 0
            try:
                from homeassistant.helpers import floor_registry as fr
                floor_reg = fr.async_get(hass)
                existing_floors = {
                    f.name.lower(): f.floor_id for f in floor_reg.async_list_floors()
                }
                zone_specs = [
                    ("ground", "Ground Floor", 0, "mdi:home-floor-1"),
                    ("upper", "Upper Level", 1, "mdi:home-floor-2"),
                    ("outdoor", "Outdoor & Perimeter", 0, "mdi:tree"),
                ]
                zone_to_floor_id: dict[str, str] = {}
                for z_key, f_name, level, icon in zone_specs:
                    fid = existing_floors.get(f_name.lower())
                    if not fid and hasattr(floor_reg, "async_create"):
                        created = floor_reg.async_create(f_name, level=level, icon=icon)
                        fid = getattr(created, "floor_id", None)
                    if fid:
                        zone_to_floor_id[z_key] = fid

                for area_entry in list(area_reg.async_list_areas()):
                    z = floorplan_parser._classify_area_zone(area_entry.id, area_entry.name)
                    z_map = "upper" if z == "upper" else ("outdoor" if z == "outdoor" else "ground")
                    target_fid = zone_to_floor_id.get(z_map)
                    if target_fid and getattr(area_entry, "floor_id", None) != target_fid:
                        if hasattr(area_reg, "async_update"):
                            area_reg.async_update(area_entry.id, floor_id=target_fid)
                            synced_areas += 1
            except Exception as err:
                _LOGGER.warning("Could not sync HA floor registry: %s", err)
            _invalidate()
            return {
                "success": True,
                "message": f"Synchronized Home Assistant native Floor Registry across {synced_areas} room(s)!",
                "synced_areas": synced_areas,
            }
        elif action_type == "advisor_guide":
            return {
                "success": True,
                "message": (
                    payload.get("guide_message")
                    or payload.get("guide")
                    or "Recommendation noted! Ask Otis in the Assist Co-Pilot tab for step-by-step setup guidance."
                ),
            }
        elif action_type == "configure_agent":
            return {
                "success": True,
                "message": "Please navigate to Settings > Devices & Services > Otis AI Companion > Configure to set fallback AI agents.",
            }
        elif action_type == "upload_walkthrough":
            return {
                "success": True,
                "action": "open_walkthrough_modal",
                "message": "Ready to upload video walkthrough or generate floor plan.",
            }

        return {"success": False, "error": f"Unsupported action_type '{action_type}'"}

    async def handle_chat(call) -> ServiceResponse:
        """Handle service call to chat directly with Otis AI."""
        text = call.data.get("text")
        if not text:
            return {"response": "Please provide a message to chat with Otis."}

        conv_id = call.data.get("conversation_id")
        user_input_cls = getattr(conversation, "ConversationInput", getattr(conversation, "UserInput", None))
        language = call.data.get("language") or getattr(hass.config, "language", "en")
        try:
            user_input = user_input_cls(
                text=text,
                context=call.context,
                conversation_id=conv_id,
                language=language,
                agent_id=entry.entry_id,
            )
        except TypeError:
            try:
                user_input = user_input_cls(
                    text=text,
                    context=call.context,
                    conversation_id=conv_id,
                    language=language,
                )
            except Exception:
                class SimpleInput:
                    def __init__(self, t, cid, ctx, lang):
                        self.text = t
                        self.conversation_id = cid
                        self.context = ctx
                        self.language = lang
                        self.device_id = None
                user_input = SimpleInput(text, conv_id, call.context, language)

        result = await agent.async_process(user_input)
        speech = ""
        if result and getattr(result, "response", None):
            resp = result.response
            speech = getattr(resp, "speech", {}).get("plain", {}).get("speech", "")
            if not speech and hasattr(resp, "as_dict"):
                resp_dict = resp.as_dict()
                speech = resp_dict.get("speech", {}).get("plain", {}).get("speech", "")

        ret_conv_id = getattr(result, "conversation_id", None) or conv_id
        return {
            "response": speech or "I didn't receive a response from the agent.",
            "conversation_id": ret_conv_id,
        }

    async def handle_get_spatial_map(call) -> ServiceResponse:
        """Handle service call to retrieve the spatial area adjacency graph."""
        _LOGGER.debug("Service 'get_spatial_map' triggered")
        _, _, s_mgr, *_ = _get_active_managers()
        graph = await s_mgr.async_get_graph()
        return graph

    async def handle_update_spatial_map(call) -> ServiceResponse:
        """Handle service call to update an adjacency connection between two areas."""
        area_1 = call.data.get("area_1")
        area_2 = call.data.get("area_2")
        connected = call.data.get("connected", True)
        connection_type = call.data.get("connection_type", "open")
        _LOGGER.debug(
            "Service 'update_spatial_map' triggered: %s <-> %s (connected=%s, type=%s)",
            area_1,
            area_2,
            connected,
            connection_type,
        )

        if not area_1 or not area_2:
            return {"success": False, "error": "Both 'area_1' and 'area_2' are required parameters"}

        try:
            eng, _, s_mgr, *_ = _get_active_managers()
            graph = await s_mgr.async_update_connection(area_1, area_2, connected, connection_type)
            if hasattr(eng, "invalidate_cache"):
                eng.invalidate_cache()
            action_desc = "Connected" if connected else "Disconnected"
            return {
                "success": True,
                "message": f"Successfully {action_desc.lower()} '{area_1}' and '{area_2}'",
                "graph": graph,
            }
        except Exception as err:
            _LOGGER.error("Error updating spatial map: %s", err)
            return {"success": False, "error": str(err)}

    async def handle_generate_floorplan(call) -> ServiceResponse:
        """Handle service call to generate SVG floorplan."""
        _LOGGER.debug("Service 'generate_floorplan' triggered")
        eng, _, _, fp, *_ = _get_active_managers()
        capability_map = await eng.async_build_capability_map()
        video_path = call.data.get("video_path")
        spoken_order = call.data.get("spoken_order")
        theme = call.data.get("theme", "cyberpunk")
        output_path = call.data.get("output_path", "www/otis_floorplan.svg")
        res = await fp.async_generate_svg_floorplan(
            capability_map,
            output_relative_path=output_path,
            theme=theme,
            video_path=video_path,
            spoken_order=spoken_order,
        )
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        return res

    async def handle_update_floorplan_layout(call) -> ServiceResponse:
        """Handle service call to adjust floorplan marker and room layout coordinates."""
        _LOGGER.debug("Service 'update_floorplan_layout' triggered with: %s", call.data)
        eng, _, _, fp, *_ = _get_active_managers()
        badges = call.data.get("badges")
        rooms = call.data.get("rooms")
        svg_path = call.data.get("svg_path", "www/otis_floorplan.svg")
        res = await fp.async_update_floorplan_layout(
            badges=badges,
            rooms=rooms,
            svg_relative_path=svg_path,
        )
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        return res

    async def handle_generate_theme(call) -> ServiceResponse:
        """Handle service call to generate and persist a custom theme."""
        _LOGGER.debug("Service 'generate_theme' triggered with: %s", call.data)
        eng, _, _, _, tm, *_ = _get_active_managers()
        prompt = call.data.get("prompt", "")
        name = call.data.get("name")
        base_palette = call.data.get("base_palette")
        dark_mode = call.data.get("dark_mode")
        border_radius = call.data.get("border_radius")
        glow_effect = call.data.get("glow_effect")
        apply_immediately = call.data.get("apply_immediately", False)

        res = await tm.async_generate_and_save_theme(
            prompt=prompt,
            name=name,
            base_palette=base_palette,
            dark_mode=dark_mode,
            border_radius=border_radius,
            glow_effect=glow_effect,
            apply_immediately=apply_immediately,
        )
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        return res

    async def handle_apply_theme(call) -> ServiceResponse:
        """Handle service call to apply a theme."""
        theme_name = call.data.get("name") or call.data.get("theme_name")
        mode = call.data.get("mode")
        user_id = call.data.get("user_id")
        all_users = call.data.get("all_users", False)
        _LOGGER.debug(
            "Service 'apply_theme' triggered for: %s (mode=%s, user_id=%s, all_users=%s)",
            theme_name,
            mode,
            user_id,
            all_users,
        )
        if not theme_name:
            return {"success": False, "error": "Missing theme 'name' parameter"}
        _, _, _, _, tm, *_ = _get_active_managers()
        ok = await tm.async_apply_theme(theme_name, mode=mode, user_id=user_id, all_users=all_users)
        return {"success": ok, "theme": theme_name}

    async def handle_list_themes(call) -> ServiceResponse:
        """Handle service call to list generated Otis themes."""
        _LOGGER.debug("Service 'list_themes' triggered")
        _, _, _, _, tm, *_ = _get_active_managers()
        themes = await tm.async_list_otis_themes()
        return {"themes": themes, "presets": list(PRESET_THEMES.keys())}

    async def handle_delete_theme(call) -> ServiceResponse:
        """Handle service call to delete an Otis theme."""
        theme_name = call.data.get("name") or call.data.get("theme_name")
        _LOGGER.debug("Service 'delete_theme' triggered for: %s", theme_name)
        if not theme_name:
            return {"success": False, "error": "Missing theme 'name' parameter"}
        eng, _, _, _, tm, *_ = _get_active_managers()
        deleted = await tm.async_delete_theme(theme_name)
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        return {"success": deleted, "theme": theme_name}

    async def handle_run_sentinel_watchdog(call) -> ServiceResponse:
        """Handle service call to run Sentinel watchdog audit."""
        _LOGGER.debug("Service 'run_sentinel_watchdog' triggered")
        eng, *_, sm, _ = _get_active_managers()
        anomalies = await sm.async_scan_all_anomalies()
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        return {"success": True, "anomalies": anomalies, "count": len(anomalies)}

    async def handle_remediate_anomaly(call) -> ServiceResponse:
        """Handle service call to remediate a detected anomaly."""
        anomaly_id = call.data.get("anomaly_id")
        action = call.data.get("action")
        _LOGGER.debug("Service 'remediate_anomaly' triggered for: %s (action=%s)", anomaly_id, action)
        if not anomaly_id:
            return {"success": False, "error": "Missing 'anomaly_id' parameter"}
        eng, *_, sm, _ = _get_active_managers()
        res = await sm.async_remediate_anomaly(anomaly_id, action=action)
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        return res

    async def handle_get_sentinel_telemetry(call) -> ServiceResponse:
        """Handle service call to retrieve Sentinel telemetry."""
        _LOGGER.debug("Service 'get_sentinel_telemetry' triggered")
        *_, sm, _ = _get_active_managers()
        anomalies = sm.get_active_anomalies()
        return {"anomalies": anomalies, "count": len(anomalies)}

    async def handle_ignore_sentinel_alert(call) -> ServiceResponse:
        """Handle service call to ignore a Sentinel alert or entire alert category."""
        anomaly_id = call.data.get("anomaly_id")
        category = call.data.get("category")
        all_in_category = call.data.get("all_in_category", False)
        _LOGGER.debug(
            "Service 'ignore_sentinel_alert' triggered: anomaly_id=%s, category=%s, all=%s",
            anomaly_id,
            category,
            all_in_category,
        )
        eng, *_, sm, _ = _get_active_managers()
        if sm:
            if category:
                await sm.async_ignore_category(category)
            elif anomaly_id:
                await sm.async_ignore_anomaly(anomaly_id)
            if hasattr(sm, "async_scan_all_anomalies"):
                await sm.async_scan_all_anomalies()
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        return {"success": True, "anomaly_id": anomaly_id, "category": category}

    async def handle_create_command_center(call) -> ServiceResponse:
        """Handle service call to create or sync the User role Command Center dashboard."""
        _LOGGER.debug("Service 'create_command_center' triggered")
        eng, *_, dm = _get_active_managers()
        cap_map = await eng.async_get_capability_map() if hasattr(eng, "async_get_capability_map") else {}
        res = await dm.async_ensure_user_command_center_dashboard(cap_map)
        return {"success": True, "dashboard": res}

    _LOGGER.debug("Registering Otis AI services")
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_CAPABILITY_MAP,
        handle_get_capability_map,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SUGGESTIONS,
        handle_get_suggestions,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_APPLY_SUGGESTION,
        handle_apply_suggestion,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CHAT,
        handle_chat,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SPATIAL_MAP,
        handle_get_spatial_map,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_SPATIAL_MAP,
        handle_update_spatial_map,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_FLOORPLAN,
        handle_generate_floorplan,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_FLOORPLAN_LAYOUT,
        handle_update_floorplan_layout,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_THEME,
        handle_generate_theme,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_APPLY_THEME,
        handle_apply_theme,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_THEMES,
        handle_list_themes,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_THEME,
        handle_delete_theme,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RUN_SENTINEL_WATCHDOG,
        handle_run_sentinel_watchdog,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMEDIATE_ANOMALY,
        handle_remediate_anomaly,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SENTINEL_TELEMETRY,
        handle_get_sentinel_telemetry,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_IGNORE_SENTINEL_ALERT,
        handle_ignore_sentinel_alert,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_COMMAND_CENTER,
        handle_create_command_center,
        supports_response=SupportsResponse.OPTIONAL,
    )

    _LOGGER.info("Otis AI Companion entry set up successfully")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Otis AI Companion entry: %s", entry.entry_id)
    if entry.entry_id in hass.data[DOMAIN]:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        agent = entry_data.get("agent")
        if agent:
            _LOGGER.debug("Unregistering conversation agent")
            if hasattr(conversation, "async_unregister_agent"):
                conversation.async_unregister_agent(hass, agent)
            else:
                conversation.async_unset_agent(hass, entry)

    # Remove services if no other entries exist
    if not hass.data[DOMAIN]:
        for srv in (
            SERVICE_GET_CAPABILITY_MAP,
            SERVICE_GET_SUGGESTIONS,
            SERVICE_APPLY_SUGGESTION,
            SERVICE_CHAT,
            SERVICE_GET_SPATIAL_MAP,
            SERVICE_UPDATE_SPATIAL_MAP,
            SERVICE_GENERATE_FLOORPLAN,
            SERVICE_UPDATE_FLOORPLAN_LAYOUT,
        ):
            if hass.services.has_service(DOMAIN, srv):
                _LOGGER.debug("Removing service: %s", srv)
                hass.services.async_remove(DOMAIN, srv)

    _LOGGER.info("Otis AI Companion entry unloaded successfully")
    return True


# Compatibility for older Home Assistant versions
AbstractAgent = getattr(conversation, "AbstractAgent", getattr(conversation, "AbstractConversationAgent", None))


class OtisAIConversationAgent(AbstractAgent):
    """Otis AI Companion conversation agent that intercepts Assist and delegates to the selected LLM."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        engine: DiscoveryEngine,
        automation_manager: AutomationManager,
        spatial_manager: SpatialGraphManager | None = None,
        theme_manager: ThemeManager | None = None,
        sentinel_manager: SentinelManager | None = None,
    ) -> None:
        """Initialize the agent."""
        self.hass = hass
        self.entry = entry
        self.engine = engine
        self.automation_manager = automation_manager
        self.spatial_manager = spatial_manager or SpatialGraphManager(hass)
        self.theme_manager = theme_manager or ThemeManager(hass)
        self.sentinel_manager = sentinel_manager or SentinelManager(hass)

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return a list of supported languages."""
        return ["en"]

    def _create_response(
        self,
        user_input: conversation.UserInput,
        speech: str,
    ) -> conversation.ConversationResult:
        """Create a ConversationResult with a properly initialized IntentResponse."""
        if hasattr(user_input, "create_response"):
            return conversation.ConversationResult(
                response=user_input.create_response(intent_response=None, speech=speech),
                conversation_id=user_input.conversation_id,
            )
        try:
            intent_response = intent.IntentResponse(language=getattr(user_input, "language", "en"))
            intent_response.async_set_speech(speech)
            return conversation.ConversationResult(
                response=intent_response,
                conversation_id=user_input.conversation_id,
            )
        except Exception as err:
            _LOGGER.error("Failed to construct intent response: %s", err)
            return conversation.ConversationResult(
                response=None,
                conversation_id=getattr(user_input, "conversation_id", None),
            )

    async def async_process(
        self, user_input: conversation.UserInput
    ) -> conversation.ConversationResult:
        """Process a sentence and delegate to the selected LLM with capability context."""
        _LOGGER.debug("Processing conversation input: %s", user_input.text)
        
        # Initialize session states
        self.hass.data.setdefault(DOMAIN, {}).setdefault("sessions", {})
        sessions = self.hass.data[DOMAIN]["sessions"]
        conv_id = user_input.conversation_id
        user_text = user_input.text.strip().lower()
        
        confirmations = {"yes", "y", "apply", "confirm", "go ahead", "do it"}
        rejections = {"no", "n", "cancel", "don't", "stop", "reject"}

        # Check for pending wizard confirmation
        if conv_id in sessions and sessions[conv_id].get("pending_yaml"):
            if user_text in confirmations:
                pending = sessions[conv_id].pop("pending_yaml")
                try:
                    if pending["type"] == "automation":
                        auto_id = await self.automation_manager.async_write_automation(pending["yaml_data"])
                        await self.automation_manager.async_reload_automations()
                        speech = f"I have successfully created and enabled the automation '{pending['yaml_data'].get('alias', auto_id)}'!"
                    else:
                        await self.automation_manager.async_write_script(pending["id"], pending["yaml_data"])
                        await self.automation_manager.async_reload_scripts()
                        speech = f"I have successfully created the script '{pending['yaml_data'].get('alias', pending['id'])}'!"
                    if hasattr(self.engine, "invalidate_cache") and callable(getattr(self.engine, "invalidate_cache", None)):
                        self.engine.invalidate_cache()
                    
                    return self._create_response(user_input, speech)
                except Exception as err:
                    _LOGGER.error("Failed to apply pending configuration: %s", err, exc_info=True)
                    return self._create_response(
                        user_input,
                        f"I encountered an error while writing the configuration: {err}. Please check the logs."
                    )
            elif user_text in rejections:
                sessions[conv_id].pop("pending_yaml")
                return self._create_response(
                    user_input,
                    "Okay, I have discarded the proposed configuration."
                )

        # Check for theme styling commands
        if any(w in user_text for w in ("create theme", "generate theme", "new theme", "make theme", "build theme")):
            clean_prompt = re.sub(
                r"^(please\s+)?(can you\s+)?(create|generate|make|build)\s+(a\s+|an\s+)?(custom\s+)?theme\s*(called|named)?\s*",
                "",
                user_input.text,
                flags=re.IGNORECASE,
            ).strip()
            if clean_prompt and self.theme_manager:
                try:
                    res = await self.theme_manager.async_generate_and_save_theme(prompt=clean_prompt, apply_immediately=True)
                    if hasattr(self.engine, "invalidate_cache"):
                        self.engine.invalidate_cache()
                    speech = (
                        f"✨ Created and applied **{res['title']}**!\n\n"
                        f"• Saved to `{res['file_path']}` and reloaded Home Assistant frontend themes.\n"
                        f"• Colors: Primary `{res['preview']['primary']}` | Accent `{res['preview']['accent']}` | Background `{res['preview']['background']}`"
                    )
                    return self._create_response(user_input, speech)
                except Exception as err:
                    _LOGGER.error("Theme generation error: %s", err)
                    return self._create_response(user_input, f"Encountered an issue generating theme: {err}")

        elif any(w in user_text for w in ("apply theme", "switch theme", "set theme", "change theme")):
            target = re.sub(
                r"^(please\s+)?(can you\s+)?(apply|switch|set|change)\s+(to\s+)?(the\s+)?theme\s*",
                "",
                user_input.text,
                flags=re.IGNORECASE,
            ).strip()
            if target and self.theme_manager:
                slug = slugify_theme_name(target)
                key = f"otis_{slug}" if not slug.startswith("otis_") else slug
                ok = await self.theme_manager.async_apply_theme(key)
                if not ok:
                    ok = await self.theme_manager.async_apply_theme(target)
                speech = f"🎨 Switched active theme to **{target}** across Home Assistant." if ok else f"⚠️ Could not apply theme '{target}'."
                return self._create_response(user_input, speech)

        # Check for Otis Sentinel Watchdog commands
        if any(w in user_text for w in ("run sentinel", "sentinel audit", "sentinel scan", "check anomalies", "watchdog scan", "watchdog audit")):
            if self.sentinel_manager:
                anomalies = await self.sentinel_manager.async_scan_all_anomalies()
                if not anomalies:
                    speech = "🛡️ **Otis Sentinel Watchdog: All Systems Nominal**\n\nNo anomalies detected across HVAC, battery health, security perimeter, or integration nodes."
                else:
                    lines = [f"🛡️ **Otis Sentinel Audit: {len(anomalies)} Anomaly Alert(s) Detected**\n"]
                    for a in anomalies[:5]:
                        lines.append(f"• **{a['title']}** [{a.get('severity', 'high').upper()}]: {a['description']}")
                    lines.append("\nUse the **Proactive Feed** in the Companion Card to trigger 1-click self-healing remediation.")
                    speech = "\n".join(lines)
                return self._create_response(user_input, speech)

        # 1. Resolve prioritized AI agent cascade (Primary + Fallbacks)
        options = self.entry.options
        data = self.entry.data
        configured_agent = options.get(CONF_CONVERSATION_AGENT) or data.get(CONF_CONVERSATION_AGENT)

        prioritized_agents = await async_get_prioritized_agents(self.hass, preferred_agent_id=configured_agent)

        if not prioritized_agents:
            _LOGGER.warning("No AI conversation agent discovered or configured for Otis AI Companion")
            return self._create_response(
                user_input,
                "No AI conversation agent is installed or active. Please install an AI integration (such as Google Generative AI, OpenAI, or Ollama) in Settings > Devices & Services to enable Otis AI Companion."
            )

        # 2. Build the capability map
        capability_map = await self.engine.async_build_capability_map()

        # Summarize active entities by domain
        from collections import Counter
        entity_domains = Counter(e['domain'] for e in capability_map['entities'])
        entity_summary = ", ".join(f"{count} {domain}s" for domain, count in sorted(entity_domains.items()))

        # Filter active entities to only include physical control/actionable domains in the detailed list
        CONTROL_DOMAINS = {
            "light", "switch", "media_player", "climate", "lock", "cover", 
            "fan", "vacuum", "scene", "humidifier", "alarm_control_panel",
            "siren", "camera", "person",
        }
        detailed_entities = [
            {"entity_id": e["entity_id"], "area_id": e["area_id"], "state": e["state"]}
            for e in capability_map["entities"]
            if e["domain"] in CONTROL_DOMAINS
        ]

        # Extract existing automations and scripts with their friendly names
        existing_automations = [
            {"entity_id": e["entity_id"], "name": e["name"], "state": e["state"]}
            for e in capability_map["entities"]
            if e["domain"] == "automation"
        ]
        existing_scripts = [
            {"entity_id": e["entity_id"], "name": e["name"], "state": e["state"]}
            for e in capability_map["entities"]
            if e["domain"] == "script"
        ]

        # Summarize orphaned entities
        orphan_domains = Counter(e['domain'] for e in capability_map['orphaned_entities'])
        orphan_summary = ", ".join(f"{count} {domain}s" for domain, count in sorted(orphan_domains.items()))

        # Summarize spatial graph
        spatial_graph = capability_map.get("spatial_graph", {})
        named_adj = spatial_graph.get("named_adjacencies", {})
        spatial_summary = "; ".join(
            f"{area} ↔ [{', '.join(nbrs)}]"
            for area, nbrs in named_adj.items()
            if nbrs
        ) or "None configured"

        # Summarize discovered Media & Matrix Amp topology
        media_topo = capability_map.get("media_topology", {})
        if media_topo.get("matrix_amp_detected"):
            m_zones = [z["entity_id"] for z in media_topo.get("matrix_zones", [])]
            m_sources = media_topo.get("matrix_shared_sources", [])
            m_inputs = [
                f"{p['entity_id']} -> '{p['matched_source']}'"
                for p in media_topo.get("matrix_input_players", [])
            ]
            media_summary = (
                f"Multi-Zone Matrix Amplifier ({media_topo.get('matrix_platform', 'matrix')}) with "
                f"{len(m_zones)} output room zones ({m_zones}), shared inputs {m_sources}, "
                f"upstream input streamers {m_inputs}; TVs/Cinema: "
                f"{[t['entity_id'] for t in media_topo.get('tv_cinema_players', [])]}"
            )
        else:
            media_summary = (
                f"TV/Cinema players: {[t['entity_id'] for t in media_topo.get('tv_cinema_players', [])]}; "
                f"Room speakers: {[s['entity_id'] for s in media_topo.get('standalone_speakers', [])]}"
            )

        # Summarize discovered Security & Presence topology
        sec_topo = capability_map.get("security_topology", {})
        security_summary = (
            f"Alarm Panels: {sec_topo.get('alarm_panels', [])}; "
            f"Locks: {sec_topo.get('locks', [])}; "
            f"Garage Covers: {sec_topo.get('garage_covers', [])}; "
            f"Sirens: {sec_topo.get('sirens', [])}; "
            f"Bed Occupancy Sensors: {sec_topo.get('bed_sensors', [])}; "
            f"Persons: {sec_topo.get('persons', [])}; "
            f"Perimeter Cameras: {sec_topo.get('perimeter_cameras', [])}"
        )

        # Summarize System Maturity
        maturity = capability_map.get("maturity", {})
        maturity_summary = (
            f"Score: {maturity.get('score', 0)}% ({maturity.get('stage', 'Foundational')}) | "
            f"Unassigned Devices: {maturity.get('unassigned_device_count', 0)}"
        )

        # Summarize top proactive suggestions
        suggestions_list = capability_map.get("proactive_suggestions", [])
        suggestions_summary = "\n".join(
            f"- [{s.get('category', 'general').upper()}] {s.get('title')}: {s.get('description')}"
            for s in suggestions_list[:8]
        ) or "None currently pending."

        # 3. Format the prompt wrapping the user's input with the spatial/capability context
        prompt = f"""You are the Otis AI Companion, an intelligent, proactive smart home architect, co-pilot, and butler.
Your goal is to guide the user from a bare Home Assistant installation to a fully optimized, cohesive, automated smart home—and offer to build and configure everything for them.
Always prioritize native Home Assistant solutions, minimize frontend dependencies, and synthesize right-sized, modular coordinator automations and scripts (avoiding thousands of tiny per-entity automations or brittle monoliths).

Here is the current capability and architecture map of the home:
- System Maturity: {maturity_summary}
- Active Integrations: {capability_map['integrations']}
- Areas: {list(capability_map['areas'].keys())}
- Spatial Adjacency (Connected Rooms): {spatial_summary}
- Discovered Media & Matrix Audio Architecture: {media_summary}
- Discovered Security, Presence & Sleep Architecture: {security_summary}
- Active Entities Summary: {entity_summary} (Total: {len(capability_map['entities'])} entities)
- Detailed Control Entities (Actionable): {detailed_entities}
- Existing Automations: {existing_automations}
- Existing Scripts: {existing_scripts}
- Orphaned Entities Summary: {orphan_summary} (Total: {len(capability_map['orphaned_entities'])} orphaned entities)
- Proactive Recommendations:
{suggestions_summary}

Instructions:
1. Reason deeply over the home's hardware topology:
   - When a Multi-Zone Matrix Amplifier (such as Control4) is present, remember that audio is played on an upstream input streamer (e.g. `media_player.bridge`, `media_player.gym_bridge`, or Music Assistant) AND routed to 1 or more output room zones (`media_player.great_room`, `media_player.master`, etc.) via `media_player.select_source` + `media_player.volume_set`.
   - When designing security automations, coordinate `alarm_control_panel` (e.g., Alarmo), `lock.*` deadbolts, `cover.*` garage doors, `siren.*`, `camera.*` snapshots, `person.*` presence, and `sleepnumber`/`in_bed` occupancy sensors into cohesive multi-mode flows (Away, Night/Bedtime, Arrival).
2. Suggest cohesive multi-room coordinator automations, scripts, packages, or dashboard updates rather than fragmented single-device rules.
3. Review "Existing Automations" and "Existing Scripts" so you never duplicate existing rules—enhance them or fill architectural gaps.
4. Offer to clean up orphaned entities, assign unassigned devices to areas, and recommend high-value integrations/addons when relevant.
5. Keep your responses concise, structured, and actionable.
6. Use the Spatial Adjacency topology for room transition queries, pathway lighting automations, and tracking movements between connected rooms.

User: {user_input.text}
"""

        # 4. Delegate to the AI agent pool with automatic transparent failover
        result = None
        last_error_msg = None

        for idx, agent_id in enumerate(prioritized_agents):
            is_primary = (idx == 0)
            role_label = "Primary" if is_primary else f"Failover #{idx}"
            _LOGGER.debug("Attempting conversation with %s AI agent: %s", role_label, agent_id)

            try:
                attempt_result = await conversation.async_converse(
                    hass=self.hass,
                    text=prompt,
                    conversation_id=user_input.conversation_id,
                    context=user_input.context,
                    language=user_input.language,
                    agent_id=agent_id,
                    device_id=user_input.device_id,
                )

                speech_text = attempt_result.response.speech.get("plain", {}).get("speech", "")
                if is_provider_error(speech_text):
                    _LOGGER.warning(
                        "%s AI agent '%s' returned provider error: %s. Transparently failing over to next agent...",
                        role_label, agent_id, speech_text[:140]
                    )
                    last_error_msg = speech_text
                    continue

                _LOGGER.info("AI agent '%s' (%s) responded successfully", agent_id, role_label)
                result = attempt_result
                break
            except Exception as err:
                _LOGGER.warning(
                    "%s AI agent '%s' raised exception: %s. Transparently failing over...",
                    role_label, agent_id, err
                )
                last_error_msg = str(err)
                continue

        if result is None:
            _LOGGER.error("All %d configured AI agents failed. Last error: %s", len(prioritized_agents), last_error_msg)
            return self._create_response(
                user_input,
                "All available AI services are currently experiencing high demand or downtime. Please try again in a moment."
            )

        # Check for proposed YAML blocks in the response
        try:
            speech_text = result.response.speech.get("plain", {}).get("speech", "")
            if speech_text:
                yaml_blocks = re.findall(r"```(?:yaml)?\n(.*?)```", speech_text, re.DOTALL)
                for block in yaml_blocks:
                    try:
                        parsed = yaml.safe_load(block)
                        if isinstance(parsed, dict):
                            if "trigger" in parsed or "action" in parsed:
                                sessions[conv_id] = {
                                    "pending_yaml": {
                                        "type": "automation",
                                        "yaml_data": parsed
                                    }
                                }
                                _LOGGER.debug("Stored pending automation: %s", parsed)
                                confirm_text = "\n\nWould you like me to create and enable this automation in your Home Assistant? Say 'yes' or 'apply' to confirm, or 'no' to cancel."
                                result.response.speech["plain"]["speech"] += confirm_text
                                break
                            elif "sequence" in parsed:
                                alias = parsed.get("alias", "custom_script")
                                script_key = re.sub(r"\W+", "_", alias.lower()).strip("_")
                                sessions[conv_id] = {
                                    "pending_yaml": {
                                        "type": "script",
                                        "id": script_key,
                                        "yaml_data": parsed
                                    }
                                }
                                _LOGGER.debug("Stored pending script: %s with key %s", parsed, script_key)
                                confirm_text = f"\n\nWould you like me to create this script '{script_key}' in your Home Assistant? Say 'yes' or 'apply' to confirm, or 'no' to cancel."
                                result.response.speech["plain"]["speech"] += confirm_text
                                break
                    except Exception as yaml_err:
                        _LOGGER.debug("Failed to parse YAML block: %s", yaml_err)
        except Exception as parse_err:
            _LOGGER.error("Error parsing LLM response for YAML: %s", parse_err)

        return result
ERROR_SIGNATURES = [
    "Sorry, I had a problem getting a response from",
    '"code": 503',
    '"code": 429',
    '"status": "UNAVAILABLE"',
    '"status": "RESOURCE_EXHAUSTED"',
    "high demand",
    "spikes in demand are usually temporary",
    "rate limit reached",
    "quota exceeded",
    "exceeded your current quota",
    "insufficient funds",
    "no credits remaining",
    "check your plan and billing details",
    "model is overloaded",
    "service temporarily unavailable",
]


def is_provider_error(speech: str) -> bool:
    """Detect if the LLM agent returned a provider error string instead of a valid conversation response."""
    if not speech:
        return True
    speech_lower = speech.lower()
    return any(sig.lower() in speech_lower for sig in ERROR_SIGNATURES)


async def async_get_prioritized_agents(hass: HomeAssistant, preferred_agent_id: str | None = None) -> list[str]:
    """Return an ordered list of conversation agent IDs for primary + failover cascade.
    
    1. If preferred_agent_id is provided, place it first as primary.
    2. If not, inspect Settings > System > AI (.storage/ai_task) and match with discovered agents.
    3. If none found, first discovered agent is primary.
    4. All other discovered agents follow as the failover cascade pool.
    """
    from .config_flow import _get_agents, async_get_system_ai_preferred_agent

    agents = _get_agents(hass)
    discovered_ids = [getattr(a, "id", str(a)) for a in agents if getattr(a, "id", str(a)) is not None]

    prioritized = []

    # 1. User explicit choice has top priority
    if preferred_agent_id:
        prioritized.append(preferred_agent_id)
    elif hass is not None:
        # 2. Check Settings > System > AI
        system_primary = await async_get_system_ai_preferred_agent(hass, agents)
        if system_primary and system_primary in discovered_ids:
            prioritized.append(system_primary)

    # 3. Add any remaining discovered agents as failover pool
    for aid in discovered_ids:
        if aid not in prioritized:
            prioritized.append(aid)

    return prioritized


def cluster_sequences_to_routines(
    rows: list[tuple[str, str, float]],
    window_seconds: float = 300.0,
    min_occurrences: int = 2,
    entity_area_map: dict[str, str] | None = None,
    adjacencies: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Cluster recurring temporal sequences of state transitions into habit routine proposals.

    Args:
        rows: List of (entity_id, state, timestamp) tuples sorted by timestamp.
        window_seconds: Maximum time window between trigger and subsequent action events.
        min_occurrences: Minimum times the sequence must occur across distinct episodes/days.
        entity_area_map: Optional mapping of entity_id -> area_id for spatial coherence filtering.
        adjacencies: Optional mapping of area_id -> list of adjacent area_ids.

    Returns:
        List of routine proposals containing name, trigger, actions, and confidence.
    """
    if not rows:
        return []

    sorted_rows = sorted(rows, key=lambda x: x[2])
    episodes: list[list[tuple[str, str, float]]] = []
    current_episode: list[tuple[str, str, float]] = []

    for item in sorted_rows:
        if not current_episode:
            current_episode.append(item)
        else:
            prev_ts = current_episode[-1][2]
            if item[2] - prev_ts <= window_seconds:
                current_episode.append(item)
            else:
                if len(current_episode) >= 2:
                    episodes.append(current_episode)
                current_episode = [item]
    if len(current_episode) >= 2:
        episodes.append(current_episode)

    if not episodes:
        return []

    actuator_domains = {"light", "switch", "media_player", "select", "fan", "cover", "lock", "climate"}
    rear_tokens = {"backyard", "back_deck", "back_door", "pool", "spa", "patio"}
    front_tokens = {"frontdoor", "front_door", "frontyard", "driveway", "foyer", "entry", "porch"}

    def _is_spatially_coherent(trig_eid: str, act_eid: str) -> bool:
        t_low = trig_eid.lower()
        a_low = act_eid.lower()
        # Never pair rear/backyard sensors with front/driveway entities (or vice versa)
        if (any(rt in t_low for rt in rear_tokens) and any(ft in a_low for ft in front_tokens)) or (
            any(ft in t_low for ft in front_tokens) and any(rt in a_low for rt in rear_tokens)
        ):
            return False
        if entity_area_map:
            t_area = entity_area_map.get(trig_eid)
            a_area = entity_area_map.get(act_eid)
            if t_area and a_area and t_area != a_area:
                if adjacencies and a_area not in (adjacencies.get(t_area) or []):
                    return False
        return True

    pattern_counts: dict[tuple, list[float]] = {}
    pattern_actions: dict[tuple, list[dict[str, str]]] = {}

    for ep in episodes:
        trigger_entity, trigger_state, trigger_ts = ep[0]
        if not trigger_entity.startswith("binary_sensor."):
            continue
        actions = []
        seen_entities = {trigger_entity}
        for act_entity, act_state, _ in ep[1:]:
            if act_entity not in seen_entities and _is_spatially_coherent(trigger_entity, act_entity):
                seen_entities.add(act_entity)
                actions.append({"entity_id": act_entity, "state": act_state})

        # Require at least one controllable actuator in the sequence (never propose sensor-only sequences)
        actuator_actions = [
            a for a in actions if a["entity_id"].split(".", 1)[0] in actuator_domains
        ]
        if not actuator_actions:
            continue

        actions_tuple = tuple((a["entity_id"], a["state"]) for a in actions)
        pat_key = (trigger_entity, trigger_state, actions_tuple)

        if pat_key not in pattern_counts:
            pattern_counts[pat_key] = []
            pattern_actions[pat_key] = actions
        pattern_counts[pat_key].append(trigger_ts)

    proposals = []
    for (trigger_entity, trigger_state, _), timestamps in pattern_counts.items():
        if len(timestamps) < min_occurrences:
            continue

        actions = pattern_actions[(trigger_entity, trigger_state, _)]
        actuator_actions = [
            a for a in actions if a["entity_id"].split(".", 1)[0] in actuator_domains
        ]
        if not actuator_actions:
            continue
        avg_ts = sum(timestamps) / len(timestamps)
        try:
            dt = datetime.fromtimestamp(avg_ts)
            hour = dt.hour
        except Exception:
            hour = 8

        if 5 <= hour < 12:
            time_prefix = "Morning"
        elif 12 <= hour < 17:
            time_prefix = "Afternoon"
        elif 17 <= hour < 22:
            time_prefix = "Evening"
        else:
            time_prefix = "Night"

        all_entities = [trigger_entity] + [a["entity_id"] for a in actuator_actions]
        combined_text = " ".join(all_entities).lower()

        if "gym" in combined_text:
            context_label = "Gym"
        elif "bed" in combined_text or "sleep" in combined_text:
            context_label = "Bedtime" if time_prefix in ("Evening", "Night") else "Wakeup"
        elif "kitchen" in combined_text or "coffee" in combined_text:
            context_label = "Kitchen"
        elif "office" in combined_text or "desk" in combined_text:
            context_label = "Office"
        elif "theater" in combined_text or "cinema" in combined_text or "tv" in combined_text:
            context_label = "Media & Theater"
        else:
            first_action = actuator_actions[0]["entity_id"].split(".")[-1].replace("_", " ").title()
            context_label = first_action

        routine_name = f"{time_prefix} {context_label} Routine"
        confidence = min(1.0, len(timestamps) / (len(timestamps) + 1.0) + 0.25)

        action_payloads = []
        for act in actuator_actions:
            act_entity = act["entity_id"]
            act_state = act["state"]
            domain = act_entity.split(".")[0]
            if domain in ("light", "switch", "media_player", "fan"):
                service = f"{domain}.turn_{act_state}" if act_state in ("on", "off") else f"{domain}.turn_on"
                action_payloads.append({"service": service, "target": {"entity_id": act_entity}})
            elif domain == "select":
                action_payloads.append({
                    "service": "select.select_option",
                    "target": {"entity_id": act_entity},
                    "data": {"option": act_state},
                })
            else:
                action_payloads.append({
                    "service": "homeassistant.turn_on" if act_state == "on" else "homeassistant.turn_off",
                    "target": {"entity_id": act_entity},
                })

        proposals.append({
            "name": routine_name,
            "title": routine_name,
            "category": "habit_routine",
            "priority": "medium",
            "confidence": round(confidence, 2),
            "occurrences": len(timestamps),
            "trigger_entity": trigger_entity,
            "trigger_state": trigger_state,
            "actions": actions,
            "description": (
                f"Mined from your recurring habit patterns ({len(timestamps)} occurrences): "
                f"When {trigger_entity} turns {trigger_state}, {len(actuator_actions)} device action(s) consistently follow."
            ),
            "action_type": "create_automation",
            "action_payload": {
                "alias": routine_name,
                "description": f"Automated habit routine mined by Otis AI Companion ({len(timestamps)} occurrences)",
                "trigger": [{"platform": "state", "entity_id": trigger_entity, "to": trigger_state}],
                "action": action_payloads,
                "mode": "single",
            },
        })

    return proposals


class DiscoveryEngine:
    """Discovers and maps the Home Assistant registries and active integrations."""

    CAPABILITY_CACHE_TTL = 20.0
    HABITS_CACHE_TTL = 900.0

    def __init__(
        self,
        hass: HomeAssistant,
        spatial_manager: SpatialGraphManager | None = None,
        floorplan_parser: FloorplanParser | None = None,
        dashboard_manager: DashboardManager | None = None,
        theme_manager: ThemeManager | None = None,
        sentinel_manager: SentinelManager | None = None,
    ) -> None:
        """Initialize the discovery engine."""
        self.hass = hass
        self.spatial_manager = spatial_manager or SpatialGraphManager(hass)
        self.floorplan_parser = floorplan_parser or FloorplanParser(hass)
        self.dashboard_manager = dashboard_manager or DashboardManager(hass)
        self.theme_manager = theme_manager or ThemeManager(hass)
        self.sentinel_manager = sentinel_manager or SentinelManager(hass)
        self._cached_cap_map: dict[str, Any] | None = None
        self._cache_ts: float = 0.0
        self._cache_signature: tuple[Any, ...] | None = None
        self._cached_habits: list[dict[str, Any]] | None = None
        self._habits_cache_ts: float = 0.0
        self._habits_cache_key: tuple[Any, ...] | None = None
        self._suggestions_by_id: dict[str, dict[str, Any]] = {}

    def invalidate_cache(self) -> None:
        """Invalidate the cached capability map and suggestions."""
        self._cached_cap_map = None
        self._cache_ts = 0.0
        self._cache_signature = None

    def get_cached_suggestion(self, suggestion_id: str) -> dict[str, Any] | None:
        """Retrieve a generated suggestion by ID in O(1) without rescanning registries."""
        if not suggestion_id:
            return None
        return self._suggestions_by_id.get(suggestion_id)

    async def async_build_capability_map(self, force_refresh: bool = False) -> dict[str, Any]:
        """Scan HA registries and compile the capability map."""
        area_reg = ar.async_get(self.hass)
        device_reg = dr.async_get(self.hass)
        entity_reg = er.async_get(self.hass)

        ha_is_ready = getattr(self.hass, "is_running", True)
        area_list = list(area_reg.async_list_areas())
        current_sig = (
            ha_is_ready,
            len(area_list),
            len(device_reg.devices),
            len(entity_reg.entities),
            len(self.hass.config_entries.async_entries()),
            self.floorplan_parser.has_walkthrough(),
            self.floorplan_parser.floorplan_exists(),
        )
        now = time.monotonic()
        if (
            not force_refresh
            and self._cached_cap_map is not None
            and self._cache_signature == current_sig
            and (now - self._cache_ts) < self.CAPABILITY_CACHE_TTL
        ):
            return dict(self._cached_cap_map)

        _LOGGER.debug("Discovery Engine: Starting registry scan...")

        # 1. Active Integrations
        active_integrations = sorted(list(self.hass.config.components))
        _LOGGER.debug("Discovery Engine: Found %d active integrations", len(active_integrations))

        # 2. Areas mapping
        areas_map = {}
        for area_entry in area_list:
            areas_map[area_entry.id] = {
                "name": area_entry.name,
                "aliases": list(area_entry.aliases) if area_entry.aliases else [],
                "devices": [],
                "entities": [],
            }
        _LOGGER.debug("Discovery Engine: Found %d areas in registry", len(areas_map))

        # 3. Devices mapping (iterate device_reg.devices directly in HA 2026+ to avoid deprecation warning)
        devices_map = {}
        raw_devices = device_reg.devices
        device_iter = raw_devices.values() if isinstance(raw_devices, dict) else raw_devices
        for device_entry in device_iter:
            devices_map[device_entry.id] = {
                "name": device_entry.name_by_user or device_entry.name,
                "model": device_entry.model,
                "manufacturer": device_entry.manufacturer,
                "area_id": device_entry.area_id,
                "identifiers": [list(x) for x in device_entry.identifiers],
                "via_device_id": device_entry.via_device_id,
            }
            if device_entry.area_id in areas_map:
                areas_map[device_entry.area_id]["devices"].append(device_entry.id)
        _LOGGER.debug("Discovery Engine: Found %d devices in registry", len(devices_map))

        # 4. Active & Orphaned Entities mapping
        entities_list = []
        orphaned_entities = []

        # Only evaluate orphans if Home Assistant is completely started.
        # During startup, integrations load asynchronously and entities may be temporarily unready.
        ha_is_ready = getattr(self.hass, "is_running", True)
        if not ha_is_ready:
            _LOGGER.debug(
                "Discovery Engine: Home Assistant is still starting up; orphan detection suppressed until fully running."
            )

        # Get set of all existing config entry IDs from installed integrations
        installed_config_entries = {
            entry.entry_id for entry in self.hass.config_entries.async_entries()
        }

        # Known helper / system platforms that do not require external component checks
        standard_helpers = (
            "input_boolean",
            "input_number",
            "input_select",
            "input_text",
            "input_datetime",
            "counter",
            "timer",
            "group",
            "utility_meter",
            "template",
            "scene",
            "zone",
        )

        for entity_entry in entity_reg.entities.values():
            if getattr(entity_entry, "disabled_by", None) is not None:
                continue
            # Determine area ID (entity-specific area overrides device area)
            area_id = entity_entry.area_id
            if not area_id and entity_entry.device_id:
                device = device_reg.async_get(entity_entry.device_id)
                if device:
                    area_id = device.area_id

            is_orphan = False
            orphan_reason = None

            # Only check for orphans if HA is running
            if ha_is_ready:
                # Case 1: Entity is linked to a config entry, BUT that config entry was removed/deleted
                if entity_entry.config_entry_id:
                    if entity_entry.config_entry_id not in installed_config_entries:
                        is_orphan = True
                        orphan_reason = "config_entry_removed"
                    # If config_entry_id IS in installed_config_entries, it is NEVER an orphan!
                    # Offline, disconnected, or retry integrations must never have their entities pruned.
                # Case 2: Entity has no config entry (legacy/YAML), and its platform is completely absent
                elif entity_entry.platform:
                    if (
                        entity_entry.platform not in standard_helpers
                        and entity_entry.platform not in self.hass.config.components
                    ):
                        is_orphan = True
                        orphan_reason = "platform_not_loaded"

            state = self.hass.states.get(entity_entry.entity_id)
            raw_attrs = getattr(state, "attributes", None) if state else None
            attrs = dict(raw_attrs) if isinstance(raw_attrs, dict) else {}
            is_restored = bool(attrs.get("restored"))

            ent_cat = getattr(entity_entry, "entity_category", None)
            ent_cat_str = str(getattr(ent_cat, "value", ent_cat)) if ent_cat is not None else None
            dev_cls = attrs.get("device_class") or getattr(entity_entry, "device_class", None) or getattr(entity_entry, "original_device_class", None)
            dev_cls_str = str(dev_cls) if dev_cls is not None else None

            entity_info: dict[str, Any] = {
                "entity_id": entity_entry.entity_id,
                "name": entity_entry.name or entity_entry.original_name,
                "domain": entity_entry.domain,
                "platform": entity_entry.platform,
                "device_id": entity_entry.device_id,
                "area_id": area_id,
                "disabled_by": entity_entry.disabled_by,
                "hidden_by": entity_entry.hidden_by,
                "state": state.state if state else "unknown",
                "entity_category": ent_cat_str,
                "device_class": dev_cls_str,
            }
            if attrs:
                entity_info["attributes"] = {
                    k: attrs[k]
                    for k in ("source_list", "source", "device_class", "group_members", "volume_level")
                    if k in attrs
                }

            if is_orphan:
                entity_info["orphan_reason"] = orphan_reason
                entity_info["is_restored"] = is_restored
                orphaned_entities.append(entity_info)
                _LOGGER.debug(
                    "Discovery Engine: Identified true orphaned entity %s (reason: %s)",
                    entity_entry.entity_id,
                    orphan_reason,
                )
            else:
                entities_list.append(entity_info)
                if area_id in areas_map:
                    areas_map[area_id]["entities"].append(entity_entry.entity_id)

        _LOGGER.debug(
            "Discovery Engine: Scan complete. Active entities: %d, Orphaned entities: %d",
            len(entities_list),
            len(orphaned_entities)
        )

        # 5. Compile spatial adjacency graph
        spatial_graph = await self.spatial_manager.async_get_graph()
        for aid in areas_map:
            areas_map[aid]["adjacent_areas"] = spatial_graph.get("adjacencies", {}).get(aid, [])

        if not getattr(self.floorplan_parser, "_initialized", False):
            await self.floorplan_parser.async_load()
        has_floorplan = self.floorplan_parser.floorplan_exists()
        has_walkthrough = self.floorplan_parser.has_walkthrough()

        # 6. Discover advanced Media (Matrix Amp / Cinema) & Security topologies + System Maturity
        media_topology = self._discover_media_topology(areas_map, entities_list, active_integrations)
        security_topology = self._discover_security_topology(areas_map, entities_list, active_integrations)
        maturity = self._discover_system_maturity(
            areas_map,
            devices_map,
            entities_list,
            orphaned_entities,
            active_integrations,
            has_walkthrough,
            has_floorplan,
            media_topology,
            security_topology,
        )

        cap_map = {
            "integrations": active_integrations,
            "areas": areas_map,
            "devices": devices_map,
            "entities": entities_list,
            "orphaned_entities": orphaned_entities,
            "spatial_graph": spatial_graph,
            "floorplan": {
                "exists": has_floorplan,
                "walkthrough_completed": has_walkthrough,
                "url": "/local/otis_floorplan.svg" if has_floorplan else None,
                "lovelace_yaml": self.floorplan_parser.get_lovelace_yaml() if has_floorplan else None,
            },
            "media_topology": media_topology,
            "security_topology": security_topology,
            "maturity": maturity,
        }
        sentinel_data = {"active_anomalies": [], "count": 0}
        if self.sentinel_manager:
            try:
                anomalies = await self.sentinel_manager.async_scan_all_anomalies()
                sentinel_data = {"active_anomalies": anomalies, "count": len(anomalies)}
            except Exception as err:
                _LOGGER.debug("Error running Sentinel audit during discovery scan: %s", err)
        cap_map["sentinel"] = sentinel_data

        themes = []
        if self.theme_manager:
            themes = await self.theme_manager.async_list_otis_themes()
        cap_map["themes"] = themes
        cap_map["theme_presets"] = [
            {"key": k, "name": v["name"], "description": v["description"], "preview": v["preview"], "dark_mode": v.get("dark_mode", True)}
            for k, v in PRESET_THEMES.items()
        ]
        cap_map["proactive_suggestions"] = await self.async_generate_proactive_suggestions(cap_map)
        self._cached_cap_map = dict(cap_map)
        self._cache_ts = now
        self._cache_signature = current_sig

        # Continuous Discovery Synchronization: keep companion and user command center dashboard subviews updated
        if getattr(self, "dashboard_manager", None):
            try:
                await self.dashboard_manager.async_ensure_admin_companion_dashboard(cap_map)
                await self.dashboard_manager.async_ensure_user_command_center_dashboard(cap_map)
            except Exception as err:
                _LOGGER.debug("Could not synchronize dashboards during discovery scan: %s", err)

        return cap_map

    def _discover_media_topology(
        self,
        areas_map: dict[str, Any],
        entities_list: list[dict[str, Any]],
        active_integrations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Discover Control4 / Multi-Zone Matrix Amp audio topology, input bridges, and Cinema/TV zones."""
        media_players = [e for e in entities_list if e.get("domain") == "media_player"]
        integration_domains = {
            str(i.get("domain", "") if isinstance(i, dict) else i).lower()
            for i in active_integrations
        }
        has_control4 = "control4" in integration_domains or any(
            "control4" in str(e.get("platform", "")).lower() for e in media_players
        )

        # Group media players by shared source_list or Control4 platform / known room speaker naming
        source_groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for mp in media_players:
            attrs = mp.get("attributes") or {}
            src_list = attrs.get("source_list")
            if isinstance(src_list, (list, tuple)) and len(src_list) >= 2:
                key = tuple(sorted(str(s).strip() for s in src_list if s))
                if key:
                    source_groups.setdefault(key, []).append(mp)

        matrix_zones: list[dict[str, Any]] = []
        shared_sources: list[str] = []

        # Pick largest source group with >= 3 rooms sharing the same matrix input sources
        if source_groups:
            best_sources, best_players = max(source_groups.items(), key=lambda kv: len(kv[1]))
            if len(best_players) >= 3 or (has_control4 and len(best_players) >= 2):
                shared_sources = list(best_sources)
                matrix_zones = best_players

        # Fallback heuristic: if Control4 integration is active or >= 4 room media players match area names
        if not matrix_zones:
            area_lookup = build_area_lookup_map(areas_map)
            candidate_zones = []
            for mp in media_players:
                eid = mp.get("entity_id", "").lower()
                platform = str(mp.get("platform", "")).lower()
                if any(tok in eid for tok in ("bridge", "tv", "roku", "apple_tv", "shield", "chromecast", "plex")):
                    continue
                matched_area = mp.get("area_id") or resolve_area_identifier(
                    eid.replace("media_player.", ""), area_lookup
                )
                if "control4" in platform or matched_area or eid.endswith("_deck") or eid.endswith("_room"):
                    candidate_zones.append(mp)
            if (has_control4 and len(candidate_zones) >= 2) or len(candidate_zones) >= 5:
                matrix_zones = candidate_zones
                if not shared_sources:
                    discovered_bridges = [
                        str(mp.get("name") or mp.get("entity_id", ""))
                        for mp in media_players
                        if any(tok in mp.get("entity_id", "").lower() for tok in ("bridge", "stream", "input"))
                    ]
                    shared_sources = discovered_bridges or ["Stream 1", "Stream 2", "Media Server", "Home Assistant"]

        matrix_zone_ids = {z["entity_id"] for z in matrix_zones}

        # Identify upstream input streamer/bridge entities (e.g. media_player.bridge, media_player.gym_bridge)
        input_streamers: list[dict[str, Any]] = []
        shared_norm = {s.lower().replace(" ", "_") for s in shared_sources}
        for mp in media_players:
            eid = mp.get("entity_id", "")
            if eid in matrix_zone_ids:
                continue
            obj = eid.split(".", 1)[-1].lower()
            name_lower = str(mp.get("name") or "").lower()
            if (
                "bridge" in obj
                or "streamer" in obj
                or obj in shared_norm
                or any(s.lower() in name_lower for s in shared_sources if s)
            ):
                input_streamers.append(mp)

        # Identify Cinema / TV media players
        tv_cinema_zones: list[dict[str, Any]] = []
        for mp in media_players:
            eid = mp.get("entity_id", "")
            if eid in matrix_zone_ids:
                continue
            obj = eid.split(".", 1)[-1].lower()
            dev_class = str((mp.get("attributes") or {}).get("device_class", "")).lower()
            if (
                dev_class in ("tv", "receiver")
                or any(tok in obj for tok in ("tv", "theater", "cinema", "projector", "avr", "roku", "apple_tv"))
            ):
                tv_cinema_zones.append(mp)

        return {
            "matrix_amp_detected": len(matrix_zones) >= 2,
            "has_control4": has_control4,
            "matrix_zones": [
                {
                    "entity_id": z["entity_id"],
                    "name": z.get("name") or z["entity_id"],
                    "area_id": z.get("area_id"),
                    "state": z.get("state", "unknown"),
                }
                for z in matrix_zones
            ],
            "shared_sources": shared_sources,
            "input_streamers": [
                {
                    "entity_id": s["entity_id"],
                    "name": s.get("name") or s["entity_id"],
                    "state": s.get("state", "unknown"),
                }
                for s in input_streamers
            ],
            "tv_cinema_zones": [
                {
                    "entity_id": t["entity_id"],
                    "name": t.get("name") or t["entity_id"],
                    "area_id": t.get("area_id"),
                }
                for t in tv_cinema_zones
            ],
            "total_media_players": len(media_players),
        }

    def _discover_security_topology(
        self,
        areas_map: dict[str, Any],
        entities_list: list[dict[str, Any]],
        active_integrations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Discover Alarmo/alarm panels, smart locks, garage covers, sirens, cameras, persons, and SleepNumber bed occupancy."""
        alarm_panels = [
            e["entity_id"] for e in entities_list if e.get("domain") == "alarm_control_panel"
        ]
        locks = [e["entity_id"] for e in entities_list if e.get("domain") == "lock"]
        sirens = [e["entity_id"] for e in entities_list if e.get("domain") == "siren"]
        cameras = [
            e["entity_id"]
            for e in entities_list
            if e.get("domain") == "camera" and e.get("state") not in ("unavailable", "unknown")
        ]
        persons = [
            e["entity_id"]
            for e in entities_list
            if e.get("domain") == "person" and e.get("state") not in ("unavailable", "unknown")
        ]

        garage_covers = [
            e["entity_id"]
            for e in entities_list
            if e.get("domain") == "cover"
            and (
                "garage" in e.get("entity_id", "").lower()
                or str((e.get("attributes") or {}).get("device_class", "")).lower() == "garage"
            )
        ]

        bed_occupancy_sensors = [
            e["entity_id"]
            for e in entities_list
            if e.get("domain") == "binary_sensor"
            and any(
                kw in e.get("entity_id", "").lower()
                for kw in ("sleepnumber", "in_bed", "bed_occupancy", "bed_presence", "eight_sleep")
            )
        ]

        driving_sensors = [
            e["entity_id"]
            for e in entities_list
            if e.get("domain") == "binary_sensor"
            and any(kw in e.get("entity_id", "").lower() for kw in ("driving", "android_auto", "carplay"))
        ]

        perimeter_contact_sensors = [
            e["entity_id"]
            for e in entities_list
            if is_contact_sensor(e.get("entity_id", ""))
        ]

        return {
            "alarm_panels": alarm_panels,
            "locks": locks,
            "garage_covers": garage_covers,
            "sirens": sirens,
            "cameras": cameras,
            "persons": persons,
            "bed_occupancy_sensors": bed_occupancy_sensors,
            "driving_sensors": driving_sensors,
            "perimeter_contact_sensors": perimeter_contact_sensors,
            "ready_for_unified_coordinator": bool(
                alarm_panels or locks or garage_covers or bed_occupancy_sensors
            ),
        }

    def _discover_system_maturity(
        self,
        areas_map: dict[str, Any],
        devices_map: dict[str, Any],
        entities_list: list[dict[str, Any]],
        orphaned_entities: list[dict[str, Any]],
        active_integrations: list[dict[str, Any]],
        has_walkthrough: bool,
        has_floorplan: bool,
        media_topology: dict[str, Any],
        security_topology: dict[str, Any],
    ) -> dict[str, Any]:
        """Calculate Smart Home Maturity Score (0-100), infer areas for unassigned devices, and build onboarding checklist."""
        area_lookup = build_area_lookup_map(areas_map)

        # Find devices/entities without area_id whose name or entity_id matches a registered area
        inferred_device_assignments: dict[str, str] = {}
        inferred_entity_assignments: dict[str, str] = {}

        # Sort area tokens longest-first so "master_bath" matches before "master"
        sorted_tokens = sorted(area_lookup.items(), key=lambda kv: len(kv[0]), reverse=True)

        def _match_area_from_text(text: str) -> str | None:
            if not text:
                return None
            norm = text.lower().replace("-", "_").replace("'", "_")
            for token, aid in sorted_tokens:
                if len(token) < 3:
                    continue
                if token in norm.split("_") or f"_{token}_" in f"_{norm}_" or token in norm.lower():
                    return aid
            return None

        unassigned_devices_count = 0
        for dev_id, dev in devices_map.items():
            if not dev.get("area_id"):
                unassigned_devices_count += 1
                matched = _match_area_from_text(str(dev.get("name") or ""))
                if matched:
                    inferred_device_assignments[dev_id] = matched

        for ent in entities_list:
            if ent.get("domain") in ("automation", "script", "scene", "person", "zone", "sun", "weather"):
                continue
            if not ent.get("area_id"):
                dev_id = ent.get("device_id")
                if dev_id and dev_id in inferred_device_assignments:
                    continue
                matched = _match_area_from_text(
                    f"{ent.get('entity_id', '')} {ent.get('name', '')}"
                )
                if matched:
                    if dev_id and dev_id in devices_map and not devices_map[dev_id].get("area_id"):
                        inferred_device_assignments[dev_id] = matched
                    else:
                        inferred_entity_assignments[ent["entity_id"]] = matched

        automations_count = sum(1 for e in entities_list if e.get("domain") == "automation")
        scripts_count = sum(1 for e in entities_list if e.get("domain") == "script")
        areas_with_entities = sum(1 for a in areas_map.values() if a.get("entities"))

        # Compute 0-100 Smart Home Maturity Score across 5 weighted dimensions (20 pts each)
        # 1. Spatial & Floor Plan Organization (20 pts)
        spatial_pts = 0
        if len(areas_map) >= 3:
            spatial_pts += 8
        if areas_with_entities >= max(1, len(areas_map) // 2):
            spatial_pts += 6
        if has_walkthrough or has_floorplan:
            spatial_pts += 6

        # 2. Registry Hygiene & Area Assignment (20 pts)
        hygiene_pts = 20
        if orphaned_entities:
            hygiene_pts -= min(10, len(orphaned_entities) * 2)
        if inferred_device_assignments or inferred_entity_assignments:
            hygiene_pts -= min(10, len(inferred_device_assignments) + len(inferred_entity_assignments))
        hygiene_pts = max(0, hygiene_pts)

        # 3. Lighting & Climate Automation Coverage (20 pts)
        auto_pts = min(20, (automations_count * 4) + (scripts_count * 2))

        # 4. Security & Presence Intelligence (20 pts)
        sec_pts = 0
        if security_topology.get("alarm_panels") or security_topology.get("locks"):
            sec_pts += 10
        if security_topology.get("persons") or security_topology.get("bed_occupancy_sensors"):
            sec_pts += 5
        if automations_count >= 2:
            sec_pts += 5

        # 5. Media & Ecosystem Optimization (20 pts)
        media_pts = 10
        if media_topology.get("matrix_amp_detected"):
            has_router = any(
                "matrix" in str(e.get("entity_id", "")).lower() or "speaker" in str(e.get("entity_id", "")).lower()
                for e in entities_list
                if e.get("domain") in ("script", "automation")
            )
            media_pts = 20 if has_router else 12
        elif media_topology.get("total_media_players", 0) > 0:
            media_pts = 16

        score = max(5, min(100, spatial_pts + hygiene_pts + auto_pts + sec_pts + media_pts))
        if score >= 85:
            stage = "Fully Optimized Smart Home"
        elif score >= 60:
            stage = "Automated & Connected"
        elif score >= 35:
            stage = "Configured Foundation"
        else:
            stage = "Fresh / Bare Installation"

        return {
            "score": score,
            "stage": stage,
            "breakdown": {
                "spatial": spatial_pts,
                "hygiene": hygiene_pts,
                "automation": auto_pts,
                "security": sec_pts,
                "media": media_pts,
            },
            "unassigned_devices_count": unassigned_devices_count,
            "inferred_device_assignments": inferred_device_assignments,
            "inferred_entity_assignments": inferred_entity_assignments,
            "automations_count": automations_count,
            "scripts_count": scripts_count,
        }

    def _inspect_config_files_sync(
        self, active_entity_ids: set[str]
    ) -> dict[str, Any]:
        """Synchronously inspect automations.yaml, scripts.yaml, and configuration.yaml for overlap and improvements."""
        result: dict[str, Any] = {
            "norm_names": set(),
            "automated_entities": set(),
            "improvement_suggestions": [],
            "system_suggestions": [],
        }
        if not (hasattr(self.hass, "config") and hasattr(self.hass.config, "path")):
            return result

        try:
            auto_path = self.hass.config.path("automations.yaml")
            script_path = self.hass.config.path("scripts.yaml")
            config_path = self.hass.config.path("configuration.yaml")
        except Exception:
            return result

        if not isinstance(auto_path, str):
            return result

        def _norm(s: str) -> str:
            return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()

        service_verbs = {
            "turn_on",
            "turn_off",
            "turned_on",
            "turned_off",
            "toggle",
            "set_options",
            "select_option",
            "set_value",
            "set_temperature",
            "set_hvac_mode",
            "set_preset_mode",
            "set_fan_mode",
            "set_humidity",
            "volume_set",
            "volume_mute",
            "volume_up",
            "volume_down",
            "media_play",
            "media_pause",
            "media_play_pause",
            "media_stop",
            "media_next_track",
            "media_previous_track",
            "media_seek",
            "play_media",
            "clear_playlist",
            "shuffle_set",
            "repeat_set",
            "join",
            "unjoin",
            "select_source",
            "select_sound_mode",
            "lock",
            "unlock",
            "open",
            "open_cover",
            "close_cover",
            "stop_cover",
            "set_cover_position",
            "set_cover_tilt_position",
            "set_percentage",
            "set_direction",
            "oscillate",
            "increase_speed",
            "decrease_speed",
            "alarm_arm_away",
            "alarm_arm_home",
            "alarm_arm_night",
            "alarm_arm_vacation",
            "alarm_arm_custom_bypass",
            "alarm_disarm",
            " alarm_trigger",
            "start",
            "pause",
            "stop",
            "return_to_base",
            "clean_spot",
            "locate",
            "send_command",
            "set_fan_speed",
            "set_datetime",
            "reload",
            "create",
            "dismiss",
            "backup_full",
            "is_off",
            "is_on",
            "unlocked",
            "locked",
            "trigger",
            "yaml",
            "yml",
            "json",
            "mp3",
            "wav",
            "ogg",
            "flac",
            "m3u",
            "jpg",
            "jpeg",
            "png",
            "gif",
            "mp4",
        }
        tracked_domains = {
            "light",
            "switch",
            "binary_sensor",
            "sensor",
            "media_player",
            "climate",
            "lock",
            "cover",
            "alarm_control_panel",
            "script",
            "input_boolean",
            "input_select",
            "person",
        }

        def _extract_auto_entities(node: Any, parent_key: str = "") -> set[str]:
            """Extract entity_ids referenced in an automation while ignoring blueprint paths, actions, and trigger/condition types."""
            found: set[str] = set()
            skip_keys = {
                "path",
                "action",
                "service",
                "trigger",
                "condition",
                "platform",
                "domain",
                "type",
                "subtype",
                "event",
                "id",
                "alias",
                "description",
                "mode",
                "media_content_id",
                "media_content_type",
                "icon",
                "image",
                "icon_url",
            }
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "use_blueprint" and isinstance(v, dict):
                        if "input" in v:
                            found.update(_extract_auto_entities(v["input"], "input"))
                        continue
                    if k in skip_keys and isinstance(v, str):
                        continue
                    found.update(_extract_auto_entities(v, k))
            elif isinstance(node, list):
                for item in node:
                    found.update(_extract_auto_entities(item, parent_key))
            elif isinstance(node, str):
                # Skip file paths or URLs unless it's a Jinja template
                if ("/" in node or "\\" in node) and "{{" not in node and "{%" not in node:
                    return found
                for dom, obj in re.findall(r"(?<![/\w])([a-z_]+)\.([a-z0-9_]+)(?![/\w])", node):
                    if dom in tracked_domains and obj not in service_verbs:
                        found.add(f"{dom}.{obj}")
            return found

        # 1. Inspect scripts.yaml
        if isinstance(script_path, str) and os.path.isfile(script_path):
            try:
                with open(script_path, "r", encoding="utf-8") as f:
                    raw_scripts = f.read()
                for m in re.findall(r"(?<![/\w])([a-z_]+)\.([a-z0-9_]+)(?![/\w])", raw_scripts):
                    if m[0] in tracked_domains and m[1] not in service_verbs:
                        result["automated_entities"].add(f"{m[0]}.{m[1]}")
                parsed_scripts = yaml.safe_load(raw_scripts)
                if isinstance(parsed_scripts, dict):
                    for skey, sbody in parsed_scripts.items():
                        result["norm_names"].add(_norm(skey))
                        if isinstance(sbody, dict) and sbody.get("alias"):
                            result["norm_names"].add(_norm(sbody["alias"]))
            except Exception as err:
                _LOGGER.debug("Could not inspect scripts.yaml: %s", err)

        # 2. Inspect automations.yaml
        if os.path.isfile(auto_path):
            try:
                with open(auto_path, "r", encoding="utf-8") as f:
                    raw_autos = f.read()
                parsed_autos = yaml.safe_load(raw_autos)
                if isinstance(parsed_autos, list):
                    for auto in parsed_autos:
                        if not isinstance(auto, dict):
                            continue
                        aid = str(auto.get("id") or "")
                        alias = str(auto.get("alias") or aid)
                        result["norm_names"].add(_norm(alias))
                        auto_dump = yaml.dump(auto)

                        ref_eids = _extract_auto_entities(auto)
                        result["automated_entities"].update(ref_eids)

                        # Check A: Input select option whitespace mismatch (e.g. "<Label> ..." vs "<Label>...")
                        ellipsis_match = re.search(r"([A-Za-z0-9_]+)\s+\.\.\.", auto_dump)
                        if ellipsis_match and "input_select" in auto_dump:
                            bad_opt = ellipsis_match.group(0)
                            clean_opt = f"{ellipsis_match.group(1)}..."
                            result["improvement_suggestions"].append({
                                "id": f"fix_input_select_option_{aid}",
                                "title": f"Fix '{bad_opt}' Option Mismatch in '{alias}'",
                                "category": "automation",
                                "priority": "high",
                                "icon": "mdi:wrench-check",
                                "description": (
                                    f"Home Assistant logs a warning because '{alias}' selects option '{bad_opt}' "
                                    f"(with extra whitespace) while set_options defines '{clean_opt}'. "
                                    "Standardize the option string in 1 click to eliminate this log warning."
                                ),
                                "action_type": "improve_automation",
                                "action_payload": {
                                    "automation_id": aid,
                                    "alias": alias,
                                    "replace_map": {bad_opt: clean_opt},
                                },
                            })

                        # Check B: Broken / Typo entity references inside existing automations (high-confidence typos only)
                        if active_entity_ids:
                            import difflib
                            for eid in sorted(ref_eids):
                                if eid in active_entity_ids:
                                    continue
                                dom, obj = eid.split(".", 1)
                                if dom in ("script", "person"):
                                    continue
                                replacement_eid = None
                                # Only suggest replacement if another active entity in the same domain has a single-token typo (e.g. sstudy -> study)
                                obj_tokens = obj.split("_")
                                for cand in active_entity_ids:
                                    if not cand.startswith(f"{dom}."):
                                        continue
                                    cand_obj = cand.split(".", 1)[1]
                                    cand_tokens = cand_obj.split("_")
                                    if len(obj_tokens) != len(cand_tokens):
                                        continue
                                    diffs = [
                                        (t_a, t_b)
                                        for t_a, t_b in zip(obj_tokens, cand_tokens)
                                        if t_a != t_b
                                    ]
                                    if len(diffs) == 1:
                                        t_a, t_b = diffs[0]
                                        if (
                                            not t_a.isdigit()
                                            and not t_b.isdigit()
                                            and len(t_a) >= 4
                                            and len(t_b) >= 4
                                            and abs(len(t_a) - len(t_b)) <= 2
                                            and difflib.SequenceMatcher(None, t_a, t_b).ratio() >= 0.80
                                        ):
                                            replacement_eid = cand
                                            break

                                if replacement_eid:
                                    result["improvement_suggestions"].append({
                                        "id": f"fix_broken_entity_{aid}_{obj}",
                                        "title": f"Fix Broken Entity Reference in '{alias}' ({eid} → {replacement_eid})",
                                        "category": "automation",
                                        "priority": "high",
                                        "icon": "mdi:auto-fix",
                                        "description": (
                                            f"Existing automation '{alias}' references typo/missing entity "
                                            f"'{eid}', causing runtime service warnings in Home Assistant logs. "
                                            f"Replace it with active entity '{replacement_eid}'."
                                        ),
                                        "action_type": "improve_automation",
                                        "action_payload": {
                                            "automation_id": aid,
                                            "alias": alias,
                                            "replace_map": {eid: replacement_eid},
                                        },
                                    })

                        # Check C: Multi-trigger coordinator automations running in default mode: single (skip blueprints)
                        triggers = auto.get("trigger") or auto.get("triggers") or []
                        t_count = len(triggers) if isinstance(triggers, list) else 1
                        has_explicit_mode = "mode" in auto and auto.get("mode") is not None
                        if t_count >= 4 and not has_explicit_mode and "use_blueprint" not in auto:
                            result["improvement_suggestions"].append({
                                "id": f"upgrade_mode_queued_{aid}",
                                "title": f"Upgrade '{alias}' Execution Mode to Queued ({t_count} Triggers)",
                                "category": "automation",
                                "priority": "medium",
                                "icon": "mdi:fast-forward-outline",
                                "description": (
                                    f"'{alias}' monitors {t_count} distinct state triggers but omits an execution mode "
                                    "(defaulting to 'single'). Concurrent sensor or lock events are dropped while running. "
                                    "Upgrade to 'mode: queued' so no state transition is missed."
                                ),
                                "action_type": "improve_automation",
                                "action_payload": {
                                    "automation_id": aid,
                                    "alias": alias,
                                    "mode": "queued",
                                },
                            })
            except Exception as err:
                _LOGGER.debug("Could not inspect automations.yaml: %s", err)

        # 3. Inspect configuration.yaml for HA Performance & Log Hygiene
        if isinstance(config_path, str) and os.path.isfile(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    raw_cfg = f.read()

                if "recorder:" in raw_cfg and "commit_interval:" not in raw_cfg:
                    result["system_suggestions"].append({
                        "id": "optimize_recorder_commit_interval",
                        "title": "Optimize HA Database Performance (Recorder Commit Interval)",
                        "category": "system",
                        "priority": "high",
                        "icon": "mdi:database-sync",
                        "description": (
                            "Your configuration.yaml 'recorder:' section flushes SQLite writes continuously. "
                            "Adding 'commit_interval: 30' batches database commits every 30 seconds, reducing "
                            "disk I/O overhead and SQLite lock contention across 5,000+ entities."
                        ),
                        "action_type": "optimize_system_config",
                        "action_payload": {"optimization_type": "recorder_commit_interval"},
                    })

                if (
                    "input_select." in raw_cfg
                    and "Event data for call_service exceed maximum size" not in raw_cfg
                ):
                    result["system_suggestions"].append({
                        "id": "suppress_recorder_32kb_call_service_warning",
                        "title": "Eliminate Recorder 32KB Service Event Log Warning",
                        "category": "system",
                        "priority": "medium",
                        "icon": "mdi:file-document-check-outline",
                        "description": (
                            "Large media catalog option updates trigger 'WARNING (Recorder) Event data for "
                            "call_service exceed maximum size of 32768 bytes' in Home Assistant logs. "
                            "Add a targeted logger filter in configuration.yaml to keep system logs clean."
                        ),
                        "action_type": "optimize_system_config",
                        "action_payload": {"optimization_type": "suppress_recorder_32kb_log_filter"},
                    })
            except Exception as err:
                _LOGGER.debug("Could not inspect configuration.yaml: %s", err)

        # 4. Inspect .storage/backup and .storage/core.config_entries for automatic backup configurations (e.g. pCloud Backup, HA Automatic Backups)
        try:
            backup_storage_path = self.hass.config.path(".storage/backup")
            if isinstance(backup_storage_path, str) and os.path.isfile(backup_storage_path):
                with open(backup_storage_path, "r", encoding="utf-8") as bf:
                    bdata = json.load(bf).get("data", {})
                bcfg = bdata.get("config", {})
                if bcfg.get("automatic_backups_configured") or bcfg.get("agents"):
                    result["automatic_backups_configured"] = True
            ce_path = self.hass.config.path(".storage/core.config_entries")
            if isinstance(ce_path, str) and os.path.isfile(ce_path):
                with open(ce_path, "r", encoding="utf-8") as cf:
                    cedata = json.load(cf).get("data", {})
                for entry in cedata.get("entries", []):
                    edom = str(entry.get("domain", "")).lower()
                    if "backup" in edom and edom != "backup":
                        result["automatic_backups_configured"] = True
                        break
        except Exception as err:
            _LOGGER.debug("Could not inspect backup storage: %s", err)

        return result

    async def async_generate_proactive_suggestions(
        self, capability_map: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Generate intelligent, proactive smart home recommendations across all maturity stages."""
        suggestions: list[dict[str, Any]] = []

        orphaned = capability_map.get("orphaned_entities", [])
        areas = capability_map.get("areas", {})
        devices = capability_map.get("devices", {})
        entities = capability_map.get("entities", [])
        integrations = capability_map.get("integrations", [])

        # Lazily compute topologies if capability_map was constructed manually in tests
        media_topology = capability_map.get("media_topology")
        if not isinstance(media_topology, dict):
            media_topology = self._discover_media_topology(areas, entities, integrations)

        security_topology = capability_map.get("security_topology")
        if not isinstance(security_topology, dict):
            security_topology = self._discover_security_topology(areas, entities, integrations)

        maturity = capability_map.get("maturity")
        if not isinstance(maturity, dict):
            maturity = self._discover_system_maturity(
                areas,
                devices,
                entities,
                orphaned,
                integrations,
                self.floorplan_parser.has_walkthrough(),
                self.floorplan_parser.floorplan_exists(),
                media_topology,
                security_topology,
            )

        # Index existing automations and scripts (both from registry AND directly from automations.yaml/scripts.yaml)
        def _norm_str(s: str) -> str:
            return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()

        active_entity_ids = {e["entity_id"] for e in entities if e.get("entity_id")}
        exec_res = self.hass.async_add_executor_job(
            self._inspect_config_files_sync, active_entity_ids
        )
        if asyncio.iscoroutine(exec_res) or hasattr(exec_res, "__await__"):
            config_audit = await exec_res
        else:
            config_audit = self._inspect_config_files_sync(active_entity_ids)
        if not isinstance(config_audit, dict):
            config_audit = self._inspect_config_files_sync(active_entity_ids)
        automated_entities: set[str] = config_audit.get("automated_entities", set())

        existing_auto_names = {
            _norm_str(e.get("name") or e.get("entity_id") or "")
            for e in entities
            if e.get("domain") == "automation"
        } | config_audit.get("norm_names", set())
        existing_script_names = {
            _norm_str(e.get("name") or e.get("entity_id") or "")
            for e in entities
            if e.get("domain") == "script"
        } | config_audit.get("norm_names", set())
        all_existing_names = existing_auto_names | existing_script_names

        # 0. Surface Sentinel Telemetry Anomaly Self-Healing Alerts (Highest Priority)
        if self.sentinel_manager:
            try:
                sentinel_suggestions = self.sentinel_manager.convert_anomalies_to_proactive_suggestions()
                suggestions.extend(sentinel_suggestions)
            except Exception as err:
                _LOGGER.debug("Error generating Sentinel suggestions: %s", err)

        # Surface Existing Automation Improvements & HA System/Config Optimizations
        suggestions.extend(config_audit.get("improvement_suggestions", [])[:4])
        suggestions.extend(config_audit.get("system_suggestions", []))

        # Surface New Home Assistant Capabilities (Native Multi-Floor Registry Sync)
        try:
            from homeassistant.helpers import floor_registry as fr
            floor_reg = fr.async_get(self.hass)
            existing_floors = list(floor_reg.async_list_floors()) if hasattr(floor_reg, "async_list_floors") else []
            if len(areas) >= 3 and len(existing_floors) < 2:
                ha_ver = getattr(self.hass.config, "version", "2026.x")
                suggestions.append({
                    "id": "discover_ha_native_floor_registry",
                    "title": f"New HA Capability ({ha_ver}): Sync Native Multi-Floor Registry",
                    "category": "system",
                    "priority": "medium",
                    "icon": "mdi:layers-triple",
                    "description": (
                        "Home Assistant supports native Floor Registry grouping for voice intents and area cards, "
                        f"but your {len(areas)} areas are not yet linked to native HA floors. Sync Otis's Ground Floor, "
                        "Upper Level, and Outdoor zones into Home Assistant's Floor Registry in 1 click."
                    ),
                    "action_type": "sync_ha_floors",
                    "action_payload": {},
                })
        except Exception:
            pass

        # Surface Professional Dashboard Gap Recommendations
        try:
            dash_audit = await self.dashboard_manager.async_analyze_dashboard_gaps(capability_map)
            for prop in dash_audit.get("proposals", [])[:2]:
                suggestions.append({
                    "id": prop["id"],
                    "title": prop["title"],
                    "category": "dashboard",
                    "priority": prop.get("priority", "medium"),
                    "icon": prop.get("icon", "mdi:view-dashboard-plus"),
                    "description": prop["description"],
                    "action_type": "create_dashboard",
                    "action_payload": prop,
                })
        except Exception as err:
            _LOGGER.debug("Dashboard gap analysis skipped: %s", err)

        # 1. Orphaned entities cleanup suggestion
        if orphaned:
            orphan_count = len(orphaned)
            entity_ids = [e["entity_id"] for e in orphaned]
            suggestions.append({
                "id": f"cleanup_orphans_{orphan_count}",
                "title": f"Clean Up {orphan_count} Orphaned {'Entity' if orphan_count == 1 else 'Entities'}",
                "category": "cleanup",
                "priority": "high" if orphan_count >= 5 else "medium",
                "icon": "mdi:broom",
                "description": (
                    f"Found {orphan_count} orphaned entities from deleted or inactive integrations. "
                    "Cleaning them removes registry bloat and prevents state engine warnings."
                ),
                "action_type": "cleanup_orphans",
                "action_payload": {"entity_ids": entity_ids},
            })

        # 1b. 1-Click Auto-Assign Unassigned Devices & Entities to Areas
        inferred_devs = maturity.get("inferred_device_assignments", {})
        inferred_ents = maturity.get("inferred_entity_assignments", {})
        total_inferred = len(inferred_devs) + len(inferred_ents)
        if total_inferred > 0:
            suggestions.append({
                "id": "auto_assign_device_areas",
                "title": f"Auto-Assign {total_inferred} Unassigned {'Device' if total_inferred == 1 else 'Devices/Entities'} to Areas",
                "category": "cleanup",
                "priority": "high" if total_inferred >= 4 else "medium",
                "icon": "mdi:map-marker-check",
                "description": (
                    f"Otis matched {total_inferred} unassigned devices/entities to your registered rooms by name "
                    "and topology. Assigning them unlocks accurate room-level lighting, climate, and audio routing."
                ),
                "action_type": "auto_assign_areas",
                "action_payload": {
                    "device_assignments": inferred_devs,
                    "entity_assignments": inferred_ents,
                },
            })

        # 2. Control4 / Multi-Zone Matrix Amp Audio Router & Auto-Power Coordinator Package
        if media_topology.get("matrix_amp_detected"):
            matrix_zones = media_topology.get("matrix_zones", [])
            zone_ids = [z["entity_id"] for z in matrix_zones]
            shared_sources = media_topology.get("shared_sources") or [
                "Bridge",
                "Gym Bridge",
                "Server",
                "Home Assistant",
            ]
            input_streamers = [s["entity_id"] for s in media_topology.get("input_streamers", [])]
            has_matrix_router = (
                any(
                    any(
                        kw in name
                        for kw in (
                            "matrix audio router",
                            "matrix amp",
                            "room speaker",
                            "media router",
                            "bridge on off",
                            "media launcher",
                        )
                    )
                    for name in all_existing_names
                )
                or sum(1 for zid in zone_ids if zid in automated_entities) >= 3
            )
            if zone_ids and not has_matrix_router:
                default_source = shared_sources[0]
                package_scripts = [
                    {
                        "alias": "Otis Matrix Audio Router",
                        "description": (
                            f"Routes audio sources ({', '.join(shared_sources[:4])}) to {', '.join(zone_ids[:8])} "
                            "and sets optimal initial zone volume."
                        ),
                        "fields": {
                            "target_zones": {
                                "description": "Matrix output room media_player entities",
                                "example": zone_ids[:2],
                            },
                            "source_name": {
                                "description": "Matrix Amp input source name",
                                "example": default_source,
                            },
                            "volume": {
                                "description": "Initial volume level (0.0 - 1.0)",
                                "example": 0.35,
                            },
                        },
                        "sequence": [
                            {
                                "service": "media_player.turn_on",
                                "target": {"entity_id": "{{ target_zones | default(" + str(zone_ids[:1]) + ") }}"},
                            },
                            {
                                "service": "media_player.select_source",
                                "target": {"entity_id": "{{ target_zones | default(" + str(zone_ids[:1]) + ") }}"},
                                "data": {"source": "{{ source_name | default('" + default_source + "') }}"},
                            },
                            {
                                "service": "media_player.volume_set",
                                "target": {"entity_id": "{{ target_zones | default(" + str(zone_ids[:1]) + ") }}"},
                                "data": {"volume_level": "{{ volume | default(0.35) }}"},
                            },
                        ],
                        "mode": "parallel",
                    }
                ]
                idle_trigger = (
                    [
                        {
                            "platform": "state",
                            "entity_id": input_streamers,
                            "to": ["idle", "off", "paused"],
                            "for": {"minutes": 15},
                        }
                    ]
                    if input_streamers
                    else [
                        {
                            "platform": "state",
                            "entity_id": zone_ids,
                            "to": "idle",
                            "for": {"minutes": 20},
                        }
                    ]
                )
                package_automations = [
                    {
                        "alias": "Matrix Amp Coordinator: Auto-Off Idle Room Zones",
                        "description": (
                            "Automatically powers down Control4 Matrix Amp room output zones when upstream "
                            "streamer bridges remain idle for 15 minutes."
                        ),
                        "trigger": idle_trigger,
                        "action": [
                            {"service": "media_player.turn_off", "target": {"entity_id": zone_ids}}
                        ],
                        "mode": "single",
                    }
                ]
                suggestions.append({
                    "id": "matrix_audio_router_package",
                    "title": f"Multi-Zone Matrix Audio Router & Idle Power Guard ({len(zone_ids)} Zones)",
                    "category": "media",
                    "priority": "high",
                    "icon": "mdi:speaker-multiple",
                    "description": (
                        f"Discovered a multi-zone matrix audio architecture ({len(zone_ids)} room outputs sharing "
                        f"inputs: {', '.join(shared_sources[:4])}). Deploy a unified Matrix Audio Router script "
                        "plus an idle-streamer auto-shutdown coordinator to save amplifier power."
                    ),
                    "action_type": "create_package",
                    "action_payload": {
                        "scripts": package_scripts,
                        "automations": package_automations,
                    },
                })

        # 2b. Cinema / Theater Lighting & Shade Coordinator
        tv_zones = media_topology.get("tv_cinema_zones", [])
        has_cinema_auto = (
            any(
                any(kw in name for kw in ("cinema", "theater", "movie mode", "tv bias", "it s time"))
                for name in existing_auto_names
            )
            or any(t.get("entity_id") in automated_entities for t in tv_zones)
        )
        if tv_zones and not has_cinema_auto:
            primary_tv = tv_zones[0]
            tv_area_id = primary_tv.get("area_id")
            if not tv_area_id:
                for cand_aid in ("theater", "great_room", "living_room", "master"):
                    if cand_aid in areas:
                        tv_area_id = cand_aid
                        break
            tv_area = areas.get(tv_area_id, {}) if tv_area_id else {}
            tv_buckets = classify_area_entities(tv_area.get("entities", []))
            room_lights = tv_buckets["lights"] or [
                e["entity_id"] for e in entities if e.get("domain") == "light"
            ][:3]
            room_covers = [
                eid
                for eid in tv_area.get("entities", [])
                if eid.startswith("cover.") and "garage" not in eid.lower()
            ]
            if room_lights:
                play_actions: list[dict[str, Any]] = [
                    {
                        "service": "light.turn_on",
                        "target": {"entity_id": room_lights[:3]},
                        "data": {"brightness_pct": 15, "transition": 3},
                    }
                ]
                if room_covers:
                    play_actions.append(
                        {"service": "cover.close_cover", "target": {"entity_id": room_covers}}
                    )
                suggestions.append({
                    "id": "cinema_lighting_shade_coordinator",
                    "title": f"Cinema Mode Lighting & Shade Coordinator ({primary_tv.get('name')})",
                    "category": "media",
                    "priority": "medium",
                    "icon": "mdi:theater",
                    "description": (
                        f"Automatically dim lighting to 15% (and close shades if present) when {primary_tv.get('name')} "
                        "starts playing after sunset, and gently restore lighting to 60% when paused or stopped."
                    ),
                    "action_type": "create_automation",
                    "action_payload": {
                        "alias": f"Cinema Mode Coordinator: {primary_tv.get('name')}",
                        "description": "Automated by Otis AI Companion media topology engine",
                        "trigger": [
                            {
                                "platform": "state",
                                "entity_id": primary_tv["entity_id"],
                                "to": "playing",
                                "id": "media_playing",
                            },
                            {
                                "platform": "state",
                                "entity_id": primary_tv["entity_id"],
                                "from": "playing",
                                "to": ["paused", "idle", "off"],
                                "for": {"seconds": 15},
                                "id": "media_stopped",
                            },
                        ],
                        "condition": [
                            {"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"}
                        ],
                        "action": [
                            {
                                "choose": [
                                    {
                                        "conditions": [{"condition": "trigger", "id": "media_playing"}],
                                        "sequence": play_actions,
                                    },
                                    {
                                        "conditions": [{"condition": "trigger", "id": "media_stopped"}],
                                        "sequence": [
                                            {
                                                "service": "light.turn_on",
                                                "target": {"entity_id": room_lights[:3]},
                                                "data": {"brightness_pct": 60, "transition": 2},
                                            }
                                        ],
                                    },
                                ]
                            }
                        ],
                        "mode": "restart",
                    },
                })

        # 3. Unified Security, Presence & SleepNumber Bedtime Coordinator
        alarm_panels = security_topology.get("alarm_panels", [])
        locks = security_topology.get("locks", [])
        garage_covers = security_topology.get("garage_covers", [])
        sirens = security_topology.get("sirens", [])
        bed_sensors = security_topology.get("bed_occupancy_sensors", [])
        persons = security_topology.get("persons", [])
        all_lights = [e["entity_id"] for e in entities if e.get("domain") == "light"]
        all_media = [e["entity_id"] for e in entities if e.get("domain") == "media_player"]

        has_security_coordinator = (
            any(
                any(
                    kw in name
                    for kw in (
                        "security alarm system",
                        "security presence coordinator",
                        "unified security",
                        "alarm triggered router",
                        "disarm when door unlocked",
                    )
                )
                for name in all_existing_names
            )
            or any(ap in automated_entities for ap in alarm_panels)
        )
        if (
            (alarm_panels or (locks and (persons or bed_sensors)))
            and not has_security_coordinator
        ):
            triggers: list[dict[str, Any]] = []
            choose_branches: list[dict[str, Any]] = []

            # Branch 1: Everyone Leaves -> Arm Away + Lock Doors + Close Garage + Turn Off Lights/Media
            if persons:
                triggers.append(
                    {
                        "platform": "state",
                        "entity_id": persons,
                        "to": "not_home",
                        "for": {"minutes": 3},
                        "id": "everyone_left",
                    }
                )
                away_seq: list[dict[str, Any]] = []
                if locks:
                    away_seq.append({"service": "lock.lock", "target": {"entity_id": locks}})
                if garage_covers:
                    away_seq.append({"service": "cover.close_cover", "target": {"entity_id": garage_covers}})
                if alarm_panels:
                    away_seq.append(
                        {"service": "alarm_control_panel.alarm_arm_away", "target": {"entity_id": alarm_panels[0]}}
                    )
                if all_lights:
                    away_seq.append({"service": "light.turn_off", "target": {"entity_id": all_lights[:15]}})
                if all_media:
                    away_seq.append({"service": "media_player.turn_off", "target": {"entity_id": all_media[:10]}})
                choose_branches.append(
                    {
                        "conditions": [
                            {"condition": "trigger", "id": "everyone_left"},
                            *(
                                [{"condition": "state", "entity_id": p, "state": "not_home"} for p in persons]
                            ),
                        ],
                        "sequence": away_seq,
                    }
                )

            # Branch 2: Bed Occupancy (SleepNumber) -> Arm Night + Lock Doors + Shut Down House
            if bed_sensors:
                triggers.append(
                    {
                        "platform": "state",
                        "entity_id": bed_sensors,
                        "to": "on",
                        "for": {"minutes": 5},
                        "id": "bedtime_occupied",
                    }
                )
                night_seq: list[dict[str, Any]] = []
                if locks:
                    night_seq.append({"service": "lock.lock", "target": {"entity_id": locks}})
                if garage_covers:
                    night_seq.append({"service": "cover.close_cover", "target": {"entity_id": garage_covers}})
                if alarm_panels:
                    night_seq.append(
                        {"service": "alarm_control_panel.alarm_arm_night", "target": {"entity_id": alarm_panels[0]}}
                    )
                if all_lights:
                    night_seq.append({"service": "light.turn_off", "target": {"entity_id": all_lights[:15]}})
                choose_branches.append(
                    {
                        "conditions": [
                            {"condition": "trigger", "id": "bedtime_occupied"},
                            {"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"},
                            *(
                                [{"condition": "state", "entity_id": b, "state": "on"} for b in bed_sensors]
                            ),
                        ],
                        "sequence": night_seq,
                    }
                )

            # Branch 3: Arrival Home -> Disarm Alarm + Unlock Entry + Welcome Lights
            if persons:
                triggers.append(
                    {
                        "platform": "state",
                        "entity_id": persons,
                        "from": "not_home",
                        "to": "home",
                        "id": "person_arrived",
                    }
                )
                arrive_seq: list[dict[str, Any]] = []
                if alarm_panels:
                    arrive_seq.append(
                        {"service": "alarm_control_panel.alarm_disarm", "target": {"entity_id": alarm_panels[0]}}
                    )
                if locks:
                    arrive_seq.append({"service": "lock.unlock", "target": {"entity_id": locks[0]}})
                if all_lights:
                    arrive_seq.append({"service": "light.turn_on", "target": {"entity_id": all_lights[:3]}})
                choose_branches.append(
                    {
                        "conditions": [{"condition": "trigger", "id": "person_arrived"}],
                        "sequence": arrive_seq,
                    }
                )

            # Branch 4: Alarm Triggered -> Activate Sirens & Turn On All Interior/Exterior Lights
            if alarm_panels and (sirens or all_lights):
                triggers.append(
                    {
                        "platform": "state",
                        "entity_id": alarm_panels[0],
                        "to": "triggered",
                        "id": "alarm_triggered",
                    }
                )
                intrusion_seq: list[dict[str, Any]] = []
                if sirens:
                    intrusion_seq.append({"service": "siren.turn_on", "target": {"entity_id": sirens}})
                if all_lights:
                    intrusion_seq.append(
                        {
                            "service": "light.turn_on",
                            "target": {"entity_id": all_lights[:15]},
                            "data": {"brightness_pct": 100},
                        }
                    )
                choose_branches.append(
                    {
                        "conditions": [{"condition": "trigger", "id": "alarm_triggered"}],
                        "sequence": intrusion_seq,
                    }
                )

            if triggers and choose_branches:
                features_desc = []
                if alarm_panels:
                    features_desc.append(f"Alarm panel ({alarm_panels[0]})")
                if locks:
                    features_desc.append(f"{len(locks)} smart locks")
                if garage_covers:
                    features_desc.append(f"{len(garage_covers)} garage doors")
                if bed_sensors:
                    features_desc.append(f"{len(bed_sensors)} SleepNumber bed sensors")
                if sirens:
                    features_desc.append(f"{len(sirens)} indoor sirens")

                suggestions.append({
                    "id": "unified_security_presence_coordinator",
                    "title": "Unified Security, Presence & Bedtime Coordinator",
                    "category": "security",
                    "priority": "high",
                    "icon": "mdi:shield-lock",
                    "description": (
                        f"Cohesive multi-mode security coordinator integrating {', '.join(features_desc)}. "
                        "Handles Away arming & house shutdown on departure, automatic Night arming when bed sensors "
                        "confirm everyone is in bed, arrival disarming, and full siren/light activation on intrusion."
                    ),
                    "action_type": "create_automation",
                    "action_payload": {
                        "alias": "Unified Security, Presence & Bedtime Coordinator",
                        "description": "Synthesized by Otis AI Companion security topology engine",
                        "trigger": triggers,
                        "action": [{"choose": choose_branches}],
                        "mode": "queued",
                    },
                })

        # 4. Whole-Home Adaptive Multi-Room Occupancy Lighting Coordinator (plus per-area motion lighting)
        motion_light_areas: list[dict[str, Any]] = []
        for area_id, area_info in areas.items():
            area_name = area_info.get("name", area_id)
            area_buckets = classify_area_entities(area_info.get("entities", []))
            lights = area_buckets["lights"]
            motion_sensors = area_buckets["motion"]

            has_existing = (
                any(
                    _norm_str(area_name) in name
                    or _norm_str(area_id) in name
                    or ("inside lights" in name and ("adaptive" in name or "auto" in name))
                    or "lighting router" in name
                    for name in all_existing_names
                )
                or (
                    any(m in automated_entities for m in motion_sensors)
                    and any(lt in automated_entities for lt in lights)
                )
                or (lights and sum(1 for lt in lights if lt in automated_entities) >= max(1, len(lights) // 2))
            )
            if lights and motion_sensors and not has_existing:
                target_lights = lights[0] if len(lights) == 1 else lights
                motion_light_areas.append(
                    {
                        "area_id": area_id,
                        "area_name": area_name,
                        "motion": motion_sensors[0],
                        "lights": target_lights,
                    }
                )
                suggestions.append({
                    "id": f"motion_light_{area_id}",
                    "title": f"Motion-Activated Lighting in {area_name}",
                    "category": "automation",
                    "priority": "medium",
                    "icon": "mdi:motion-sensor",
                    "area_id": area_id,
                    "description": (
                        f"Automatically illuminate {area_name} when motion is detected, "
                        "and turn lights off automatically after 5 minutes of no occupancy."
                    ),
                    "action_type": "create_automation",
                    "action_payload": {
                        "alias": f"Motion-Activated Lighting: {area_name}",
                        "description": f"Automated by Otis AI Companion for {area_name}",
                        "trigger": [
                            {"platform": "state", "entity_id": motion_sensors[0], "to": "on"}
                        ],
                        "action": [
                            {"service": "light.turn_on", "target": {"entity_id": target_lights}},
                            {
                                "wait_for_trigger": [
                                    {
                                        "platform": "state",
                                        "entity_id": motion_sensors[0],
                                        "to": "off",
                                        "for": {"minutes": 5},
                                    }
                                ],
                                "continue_on_timeout": False,
                            },
                            {"service": "light.turn_off", "target": {"entity_id": target_lights}},
                        ],
                        "mode": "restart",
                    },
                })

        has_whole_home_lighting = any(
            any(
                kw in name
                for kw in (
                    "whole home adaptive",
                    "lighting coordinator",
                    "inside lights",
                    "lighting router",
                )
            )
            for name in all_existing_names
        )
        if len(motion_light_areas) >= 2 and not has_whole_home_lighting:
            coord_triggers = []
            coord_choices = []
            for item in motion_light_areas[:8]:
                aid = item["area_id"]
                coord_triggers.append(
                    {
                        "platform": "state",
                        "entity_id": item["motion"],
                        "to": "on",
                        "id": f"enter_{aid}",
                    }
                )
                coord_triggers.append(
                    {
                        "platform": "state",
                        "entity_id": item["motion"],
                        "to": "off",
                        "for": {"minutes": 5},
                        "id": f"clear_{aid}",
                    }
                )
                coord_choices.append(
                    {
                        "conditions": [{"condition": "trigger", "id": f"enter_{aid}"}],
                        "sequence": [{"service": "light.turn_on", "target": {"entity_id": item["lights"]}}],
                    }
                )
                coord_choices.append(
                    {
                        "conditions": [{"condition": "trigger", "id": f"clear_{aid}"}],
                        "sequence": [{"service": "light.turn_off", "target": {"entity_id": item["lights"]}}],
                    }
                )
            room_names = ", ".join(m["area_name"] for m in motion_light_areas[:5])
            suggestions.append({
                "id": "whole_home_lighting_coordinator",
                "title": f"Whole-Home Adaptive Occupancy Lighting Coordinator ({len(motion_light_areas)} Rooms)",
                "category": "lighting",
                "priority": "high",
                "icon": "mdi:home-lightbulb",
                "description": (
                    f"Instead of managing dozens of separate per-room automations, deploy a single cohesive "
                    f"multi-room occupancy lighting coordinator covering {room_names}."
                ),
                "action_type": "create_automation",
                "action_payload": {
                    "alias": "Whole-Home Adaptive Occupancy Lighting Coordinator",
                    "description": "Cohesive multi-room lighting coordinator generated by Otis AI Companion",
                    "trigger": coord_triggers,
                    "action": [{"choose": coord_choices}],
                    "mode": "parallel",
                },
            })

        # 5. Energy Guard: Climate pause on open door/window
        climates = [e for e in entities if e.get("domain") == "climate"]
        door_window_sensors = [
            e["entity_id"] for e in entities
            if is_contact_sensor(e.get("entity_id", ""))
        ]
        has_climate_guard = any(
            "climate" in name and ("door" in name or "window" in name or "pause" in name)
            for name in existing_auto_names
        )
        if climates and door_window_sensors and not has_climate_guard:
            suggestions.append({
                "id": "climate_door_window_guard",
                "title": "HVAC Energy Guard (Open Door/Window)",
                "category": "energy",
                "priority": "high",
                "icon": "mdi:hvac",
                "description": (
                    "Automatically pause heating/cooling when any door or window is left open "
                    "for more than 3 minutes to conserve energy and reduce utility costs."
                ),
                "action_type": "create_automation",
                "action_payload": {
                    "alias": "Climate Energy Guard: Pause HVAC on Open Door/Window",
                    "description": "Automated by Otis AI Companion",
                    "trigger": [
                        {
                            "platform": "state",
                            "entity_id": door_window_sensors[0],
                            "to": "on",
                            "for": {"minutes": 3},
                        }
                    ],
                    "action": [
                        {"service": "climate.turn_off", "target": {"entity_id": climates[0]["entity_id"]}}
                    ],
                    "mode": "single",
                },
            })

        # 6. Security / Bedtime Routine script
        has_night_routine = (
            any(
                any(
                    kw in name
                    for kw in (
                        "goodnight",
                        "bedtime",
                        "sleep",
                        "night routine",
                        "lights off at bed",
                    )
                )
                for name in all_existing_names
            )
            or any(b in automated_entities for b in bed_sensors)
        )
        if (locks or len(all_lights) >= 2) and not has_night_routine:
            seq = []
            if locks:
                seq.append({"service": "lock.lock", "target": {"entity_id": locks[0]}})
            if all_lights:
                seq.append({"service": "light.turn_off", "target": {"entity_id": all_lights[:5]}})
            suggestions.append({
                "id": "bedtime_goodnight_routine",
                "title": "Goodnight & Security Routine",
                "category": "security",
                "priority": "medium",
                "icon": "mdi:shield-moon",
                "description": (
                    "A 1-click evening routine that secures exterior doors, turns off living area lighting, "
                    "and arms perimeter detection."
                ),
                "action_type": "create_script",
                "action_payload": {
                    "alias": "Goodnight Routine",
                    "sequence": seq,
                    "mode": "single",
                },
            })

        # 7. Automated Nightly System Backup (Infrastructure Resilience)
        integration_domains = {
            str(i.get("domain", "") if isinstance(i, dict) else i).lower()
            for i in integrations
        }
        has_backup_integration = any(
            ("backup" in d and d != "backup")
            or d in ("pcloud_backup", "google_drive_backup", "samba_backup", "auto_backup", "onedrive")
            for d in integration_domains
        )
        has_backup_auto = (
            any("backup" in name for name in existing_auto_names)
            or bool(config_audit.get("automatic_backups_configured"))
            or has_backup_integration
        )
        if ("hassio" in integration_domains or "backup" in integration_domains) and not has_backup_auto:
            backup_service = "hassio.backup_full" if "hassio" in integration_domains else "backup.create"
            suggestions.append({
                "id": "automated_nightly_backup",
                "title": "Automated Nightly Home Assistant Backup (3:00 AM)",
                "category": "system",
                "priority": "medium",
                "icon": "mdi:backup-restore",
                "description": (
                    "Protect your smart home configuration, spatial graph, and automations by scheduling an "
                    "automatic nightly system backup at 3:00 AM."
                ),
                "action_type": "create_automation",
                "action_payload": {
                    "alias": "System Maintenance: Automated Nightly Backup",
                    "description": "Automated by Otis AI Companion infrastructure advisor",
                    "trigger": [{"platform": "time", "at": "03:00:00"}],
                    "action": [{"service": backup_service, "data": {}}],
                    "mode": "single",
                },
            })

        # 8. Ecosystem & Integration Advisor (Music Assistant, Alarmo, Spook/Watchman)
        if (
            media_topology.get("matrix_amp_detected")
            and "mass" not in integration_domains
            and "music_assistant" not in integration_domains
        ):
            streamers = media_topology.get("input_streamers", [])
            streamer_eids = ", ".join(s["entity_id"] for s in streamers[:2]) if streamers else "your matrix input bridges"
            suggestions.append({
                "id": "ecosystem_advisor_music_assistant",
                "title": "Ecosystem Advisor: Pair Music Assistant with Your Matrix Amp",
                "category": "system",
                "priority": "low",
                "icon": "mdi:music-box-multiple",
                "description": (
                    "Your multi-zone Matrix Amp routes shared input bridges across multiple rooms. Installing the "
                    "Music Assistant add-on/integration lets Otis stream Spotify, Apple Music, local FLAC libraries, "
                    "and voice announcements directly into your matrix input bridges."
                ),
                "action_type": "advisor_guide",
                "action_payload": {
                    "guide": (
                        f"Install the Music Assistant Server add-on and Home Assistant integration, then expose "
                        f"{streamer_eids} as upstream player providers."
                    )
                },
            })

        if (
            (locks or security_topology.get("perimeter_contact_sensors"))
            and not alarm_panels
            and "alarmo" not in integration_domains
        ):
            suggestions.append({
                "id": "ecosystem_advisor_alarmo",
                "title": "Ecosystem Advisor: Install Alarmo for Native Security Panel",
                "category": "security",
                "priority": "low",
                "icon": "mdi:shield-Plus",
                "description": (
                    "You have door/window sensors and smart locks but no active alarm_control_panel entity. "
                    "Installing Alarmo via HACS creates a full-featured security panel with entry/exit delays and PIN codes."
                ),
                "action_type": "advisor_guide",
                "action_payload": {
                    "guide": "Install 'Alarmo' from HACS -> Integrations to create alarm_control_panel.alarmo."
                },
            })

        # 9. Multi-agent failover configuration recommendation
        prioritized_agents = await async_get_prioritized_agents(self.hass)
        if len(prioritized_agents) <= 1:
            suggestions.append({
                "id": "multi_agent_redundancy",
                "title": "Configure AI Failover Redundancy",
                "category": "system",
                "priority": "low",
                "icon": "mdi:robot-confused",
                "description": (
                    "Only 1 AI conversation agent is active. Adding a local or cloud fallback agent "
                    "(e.g., Ollama or OpenAI) ensures Otis AI Companion remains 100% operational during cloud rate limits or provider downtime."
                ),
                "action_type": "configure_agent",
                "action_payload": {},
            })

        # 10. Historical Sensor Trend & Habit Routine Mining
        try:
            mined_routines = await self.async_mine_historical_habits(days=7)
            for idx, routine in enumerate(mined_routines[:3]):
                s_id = f"habit_routine_{idx}_{routine['trigger_entity'].replace('.', '_')}"
                suggestions.append({
                    "id": s_id,
                    "title": routine["title"],
                    "category": "habit_routine",
                    "priority": "medium",
                    "icon": "mdi:clock-check-outline",
                    "description": routine["description"],
                    "action_type": routine["action_type"],
                    "action_payload": routine["action_payload"],
                })
        except Exception as err:
            _LOGGER.debug("Discovery Engine: Habit mining skipped or failed: %s", err)

        # 11. Spatial Adjacency: Contextual Pathway Lighting
        spatial_graph = capability_map.get("spatial_graph", {})
        adjacencies = spatial_graph.get("adjacencies", {})
        has_pathway_auto = any("pathway" in name or "transition" in name for name in existing_auto_names)
        if not has_pathway_auto and adjacencies:
            for src_area_id, neighbors in adjacencies.items():
                src_area = areas.get(src_area_id, {})
                src_motion = classify_area_entities(src_area.get("entities", []))["motion"]
                if not src_motion:
                    continue
                for nbr_id in neighbors:
                    nbr_area = areas.get(nbr_id, {})
                    nbr_lights = classify_area_entities(nbr_area.get("entities", []))["lights"]
                    if nbr_lights:
                        src_name = src_area.get("name", src_area_id)
                        nbr_name = nbr_area.get("name", nbr_id)
                        suggestions.append({
                            "id": f"spatial_pathway_{src_area_id}_{nbr_id}",
                            "title": f"Pathway Lighting: {src_name} → {nbr_name}",
                            "category": "lighting",
                            "priority": "medium",
                            "icon": "mdi:map-marker-path",
                            "description": (
                                f"Automatically illuminate {nbr_name} pathway lighting when motion is detected in connected {src_name} after dark, "
                                "providing smooth visual transition between adjacent rooms."
                            ),
                            "action_type": "create_automation",
                            "action_payload": {
                                "alias": f"Contextual Pathway Lighting: {src_name} to {nbr_name}",
                                "description": "Automated by Otis AI Companion spatial adjacency engine",
                                "trigger": [
                                    {
                                        "platform": "state",
                                        "entity_id": src_motion[0],
                                        "to": "on",
                                    }
                                ],
                                "condition": [
                                    {
                                        "condition": "state",
                                        "entity_id": "sun.sun",
                                        "state": "below_horizon",
                                    }
                                ],
                                "action": [
                                    {"service": "light.turn_on", "target": {"entity_id": nbr_lights[0]}}
                                ],
                                "mode": "single",
                            },
                        })
                        break
                if any(s.get("id", "").startswith("spatial_pathway_") for s in suggestions):
                    break

        # 11b. Architectural Open-Concept Zone Sync (Living/Great Room + Kitchen)
        living_area_id = next(
            (aid for aid in areas if any(k in aid.lower() for k in ("great_room", "living", "family"))),
            None,
        )
        kitchen_area_id = next(
            (aid for aid in areas if "kitchen" in aid.lower()),
            None,
        )
        gr_buckets = classify_area_entities(areas.get(living_area_id or "", {}).get("entities", []))
        kit_buckets = classify_area_entities(areas.get(kitchen_area_id or "", {}).get("entities", []))
        gr_lights = gr_buckets["lights"]
        kit_lights = kit_buckets["lights"]
        gr_motion = gr_buckets["motion"] + kit_buckets["motion"]
        has_open_concept_sync = (
            any(
                any(
                    kw in name
                    for kw in (
                        "open concept",
                        "great room zone",
                        "inside lights",
                        "lighting router",
                    )
                )
                for name in all_existing_names
            )
            or (
                any(lt in automated_entities for lt in gr_lights)
                and any(lt in automated_entities for lt in kit_lights)
            )
        )
        if living_area_id and kitchen_area_id and gr_lights and kit_lights and gr_motion and not has_open_concept_sync:
            living_name = areas[living_area_id].get("name", living_area_id)
            kitchen_name = areas[kitchen_area_id].get("name", kitchen_area_id)
            suggestions.append({
                "id": "architectural_great_room_open_concept_sync",
                "title": f"{living_name} & {kitchen_name} Open-Concept Zone Sync",
                "category": "lighting",
                "priority": "high",
                "icon": "mdi:floor-plan",
                "description": (
                    f"Your floor plan maps {living_name} and {kitchen_name} as a connected open-concept space. "
                    f"Coordinate ambient lighting across both sub-zones upon evening entry and turn off together "
                    f"only when the entire open-concept zone clears."
                ),
                "action_type": "create_automation",
                "action_payload": {
                    "alias": f"Open-Concept Zone Sync ({living_name} & {kitchen_name})",
                    "description": "Synthesized from Otis AI architectural walkthrough floor plan",
                    "trigger": [
                        {"platform": "state", "entity_id": gr_motion[0], "to": "on"}
                    ],
                    "condition": [
                        {"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"}
                    ],
                    "action": [
                        {"service": "light.turn_on", "target": {"entity_id": [gr_lights[0], kit_lights[0]]}}
                    ],
                    "mode": "single",
                },
            })

        # 11c. Architectural Indoor-to-Outdoor Transition (Entry/Mudroom → Backyard/Patio/Pool)
        transition_in_id = next(
            (aid for aid in areas if any(k in aid.lower() for k in ("mudroom", "breezeway", "foyer", "back_entry"))),
            None,
        )
        outdoor_area_ids = [
            aid for aid in areas if any(k in aid.lower() for k in ("backyard", "patio", "deck", "pool", "yard"))
        ]
        mud_buckets = classify_area_entities(areas.get(transition_in_id or "", {}).get("entities", []))
        mud_triggers = list(mud_buckets["motion"] + mud_buckets["contact"])
        outdoor_lights: list[str] = []
        outdoor_names: list[str] = []
        for o_id in outdoor_area_ids:
            o_buckets = classify_area_entities(areas.get(o_id, {}).get("entities", []))
            mud_triggers.extend(o_buckets["motion"] + o_buckets["contact"])
            if o_buckets["lights"]:
                outdoor_lights.extend(o_buckets["lights"])
                outdoor_names.append(areas[o_id].get("name", o_id))

        has_backyard_transition = (
            any(
                any(
                    kw in name
                    for kw in (
                        "to backyard",
                        "backyard deck",
                        "outside lights",
                        "lighting router",
                    )
                )
                for name in all_existing_names
            )
            or any(lt in automated_entities for lt in outdoor_lights)
        )
        if transition_in_id and mud_triggers and outdoor_lights and not has_backyard_transition:
            in_name = areas[transition_in_id].get("name", transition_in_id)
            out_label = " & ".join(outdoor_names[:2]) if outdoor_names else "Outdoor Living"
            suggestions.append({
                "id": "architectural_mudroom_backyard_pool_transition",
                "title": f"{in_name} → {out_label} Evening Transition",
                "category": "lighting",
                "priority": "medium",
                "icon": "mdi:pool",
                "description": (
                    f"Based on your spatial transition from {in_name} out to {out_label}, "
                    "automatically illuminate outdoor perimeter & deck lighting when stepping outside after dark."
                ),
                "action_type": "create_automation",
                "action_payload": {
                    "alias": f"{in_name} to {out_label} Evening Lighting",
                    "description": "Synthesized from Otis AI architectural walkthrough floor plan",
                    "trigger": [
                        {"platform": "state", "entity_id": mud_triggers[0], "to": "on"}
                    ],
                    "condition": [
                        {"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"}
                    ],
                    "action": [
                        {"service": "light.turn_on", "target": {"entity_id": outdoor_lights[:3]}}
                    ],
                    "mode": "single",
                },
            })

        # 12. Interactive Vector Floor Plan walkthrough recommendation
        has_walkthrough = self.floorplan_parser.has_walkthrough()
        if not has_walkthrough:
            suggestions.append({
                "id": "record_walkthrough_floorplan",
                "title": "Record Walkthrough for Vector Floor Plan",
                "category": "visualization",
                "priority": "high",
                "icon": "mdi:floor-plan",
                "description": (
                    "No walkthrough video found for your home. Use your mobile phone to record a quick video "
                    "walkthrough, calling out each room as you enter. Otis will parse the video into an interactive "
                    "multi-floor SVG dashboard!"
                ),
                "action_type": "upload_walkthrough",
                "action_payload": {},
            })

        # Sort suggestions by priority: Critical -> High -> Medium -> Low
        priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        suggestions.sort(
            key=lambda s: priority_rank.get(str(s.get("priority", "medium")).lower(), 2)
        )

        self._suggestions_by_id = {s["id"]: s for s in suggestions if s.get("id")}
        return suggestions

    async def async_mine_historical_habits(self, days: int = 7) -> list[dict[str, Any]]:
        """Asynchronously mine Home Assistant SQLite recorder trends for habit routine patterns (with 15m TTL cache)."""
        db_path = None
        if hasattr(self.hass, "config") and hasattr(self.hass, "config") and hasattr(self.hass.config, "path"):
            try:
                db_path = self.hass.config.path("home-assistant_v2.db")
            except Exception:
                db_path = None

        cache_key = (days, db_path if isinstance(db_path, str) else None)
        now = time.monotonic()
        if (
            self._cached_habits is not None
            and self._habits_cache_key == cache_key
            and (now - self._habits_cache_ts) < self.HABITS_CACHE_TTL
        ):
            return list(self._cached_habits)

        res = await self.hass.async_add_executor_job(self._mine_habits_sync, days)
        self._cached_habits = list(res)
        self._habits_cache_ts = now
        self._habits_cache_key = cache_key
        return res

    def _mine_habits_sync(self, days: int = 7) -> list[dict[str, Any]]:
        """Synchronously query the SQLite recorder database in read-only mode to extract sequence transitions."""
        if not hasattr(self.hass, "config") or not hasattr(self.hass.config, "path"):
            return []
        try:
            db_path = self.hass.config.path("home-assistant_v2.db")
            if not isinstance(db_path, str) or not os.path.isfile(db_path):
                return []
        except Exception:
            return []

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT metadata_id, entity_id FROM states_meta
                WHERE entity_id LIKE 'binary_sensor.%'
                   OR entity_id LIKE 'light.%'
                   OR entity_id LIKE 'switch.%'
                   OR entity_id LIKE 'select.%'
                   OR entity_id LIKE 'media_player.%'
                """
            )
            meta_rows = cursor.fetchall()
            if not meta_rows:
                conn.close()
                return []

            relevant_meta_map = {}
            for meta_id, entity_id in meta_rows:
                if entity_id.startswith("binary_sensor."):
                    if any(kw in entity_id.lower() for kw in ("motion", "occupancy", "presence", "bed", "sleep", "door")):
                        relevant_meta_map[meta_id] = entity_id
                else:
                    relevant_meta_map[meta_id] = entity_id

            if not relevant_meta_map:
                conn.close()
                return []

            candidate_meta_ids = list(relevant_meta_map.keys())[:40]
            placeholders = ",".join("?" for _ in candidate_meta_ids)
            cutoff_ts = time.time() - (days * 86400)

            query = f"""
                SELECT metadata_id, state, last_updated_ts
                FROM states
                WHERE metadata_id IN ({placeholders})
                  AND last_updated_ts >= ?
                  AND state NOT IN ('unknown', 'unavailable', '')
                ORDER BY last_updated_ts ASC
                LIMIT 5000
            """
            cursor.execute(query, candidate_meta_ids + [cutoff_ts])
            raw_states = cursor.fetchall()
            conn.close()

            transition_rows = []
            last_state_by_entity = {}
            for meta_id, st, ts in raw_states:
                ent = relevant_meta_map.get(meta_id)
                if not ent:
                    continue
                if last_state_by_entity.get(ent) != st:
                    last_state_by_entity[ent] = st
                    transition_rows.append((ent, st, float(ts)))

            _LOGGER.debug(
                "Discovery Engine: Mined %d state transitions across %d entities",
                len(transition_rows),
                len(relevant_meta_map),
            )

            entity_area_map: dict[str, str] = {}
            adjacencies: dict[str, list[str]] = {}
            if isinstance(self._cached_cap_map, dict):
                for e in self._cached_cap_map.get("entities", []):
                    if e.get("entity_id") and e.get("area_id"):
                        entity_area_map[e["entity_id"]] = e["area_id"]
                adjacencies = (self._cached_cap_map.get("spatial_graph") or {}).get("adjacencies", {})

            return cluster_sequences_to_routines(
                transition_rows,
                entity_area_map=entity_area_map or None,
                adjacencies=adjacencies or None,
            )

        except Exception as err:
            _LOGGER.warning("Discovery Engine: Could not mine historical sensor trends: %s", err)
            return []
