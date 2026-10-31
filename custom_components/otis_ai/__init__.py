"""The Otis AI Companion custom integration for Home Assistant."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
import uuid
from typing import Any, Literal
import yaml

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse

try:
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
except ImportError:
    EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"
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
    SERVICE_SYNC_DASHBOARDS,
    SERVICE_EXECUTE_MACRO,
    SERVICE_ROLLBACK_MACRO,
    SERVICE_LIST_MACROS,
    SERVICE_AUDIO_HANDOFF,
    SERVICE_MEDIA_FOLLOW_ME,
    SERVICE_RELEASE_IDLE_SOURCES,
    SERVICE_NOTIFY_VOICE,
    SERVICE_GET_ENERGY_SUMMARY,
    SERVICE_LOAD_SHED,
    SERVICE_RESTORE_SHED_LOADS,
    SERVICE_GET_PRESENCE_STATES,
    SERVICE_ANALYZE_CAMERA,
    SERVICE_EVALUATE_CONTEXTUAL_ALERTS,
    SERVICE_MINE_HABITS,
    SERVICE_GET_CIRCADIAN_CURVES,
    SERVICE_AUDIT_HABIT_DEVIATIONS,
    SERVICE_AUDIT_UNASSIGNED_ENTITIES,
    SERVICE_AUTO_COMMISSION_ENTITIES,
    SERVICE_REGISTER_FEDERATED_NODE,
    SERVICE_REMOVE_FEDERATED_NODE,
    SERVICE_SYNC_FEDERATED_NODES,
    SERVICE_CALL_REMOTE_SERVICE,
    SERVICE_GET_FEDERATION_STATUS,
    SERVICE_GET_USER_RULES,
    SERVICE_SET_USER_RULES,
    SERVICE_DUCK_MEDIA,
    SERVICE_RESTORE_MEDIA,
    SERVICE_GET_VOICE_ASSIST_STATUS,
)
from .audio_manager import AudioHandoffManager
from .automation_manager import AutomationManager
from .dashboard_manager import DashboardManager
from .energy_manager import EnergyManager
from .macro_manager import MacroManager
from .rules_manager import BehavioralRulesManager
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
from .habit_manager import (
    BehavioralHabitManager,
    cluster_sequences_to_routines as cluster_sequences_to_routines,
)
from .commissioning_manager import AutonomousCommissioningManager
from .federation_manager import FederationManager
from .theme_manager import PRESET_THEMES, ThemeManager, slugify_theme_name
from .vision_manager import VisionPresenceManager, get_canonical_camera_key, stream_priority

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
    rules_manager = BehavioralRulesManager(hass)
    dashboard_manager = DashboardManager(hass, floorplan_parser=floorplan_parser, rules_manager=rules_manager)
    theme_manager = ThemeManager(hass)
    sentinel_manager = SentinelManager(hass)
    macro_manager = MacroManager(hass)
    audio_manager = AudioHandoffManager(hass, spatial_manager=spatial_manager, rules_manager=rules_manager)
    energy_manager = EnergyManager(hass, spatial_manager=spatial_manager)
    vision_manager = VisionPresenceManager(hass, spatial_manager=spatial_manager, energy_manager=energy_manager)
    habit_manager = BehavioralHabitManager(hass, spatial_manager=spatial_manager, energy_manager=energy_manager, vision_manager=vision_manager)
    commissioning_manager = AutonomousCommissioningManager(hass, spatial_manager=spatial_manager)
    federation_manager = FederationManager(hass)
    await asyncio.gather(
        spatial_manager.async_load(),
        floorplan_parser.async_load(),
        dashboard_manager.async_ensure_admin_companion_dashboard(),
        dashboard_manager.async_ensure_user_command_center_dashboard(),
        sentinel_manager.async_load_preferences(),
        federation_manager.async_load(),
        rules_manager.async_load(),
    )
    engine = DiscoveryEngine(
        hass,
        spatial_manager=spatial_manager,
        floorplan_parser=floorplan_parser,
        dashboard_manager=dashboard_manager,
        theme_manager=theme_manager,
        sentinel_manager=sentinel_manager,
        energy_manager=energy_manager,
        vision_manager=vision_manager,
        habit_manager=habit_manager,
        commissioning_manager=commissioning_manager,
        federation_manager=federation_manager,
        rules_manager=rules_manager,
    )

    async def _async_sync_dashboards_on_startup() -> None:
        try:
            if not getattr(hass, "is_running", True):
                start_event = asyncio.Event()
                hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED,
                    lambda _: start_event.set(),
                )
                try:
                    await asyncio.wait_for(start_event.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    pass
            await asyncio.sleep(0.5)
            cap_map = await engine.async_build_capability_map(force_refresh=True)
            await dashboard_manager.async_ensure_admin_companion_dashboard(cap_map)
            await dashboard_manager.async_ensure_user_command_center_dashboard(cap_map)
            _LOGGER.info("Otis AI Command Center and Companion dashboards synchronized on startup")
        except Exception as sync_err:
            _LOGGER.debug("Could not run initial dashboard sync: %s", sync_err)

    dash_coro = _async_sync_dashboards_on_startup()
    dash_task = hass.async_create_task(dash_coro)
    if not isinstance(dash_task, asyncio.Task) and asyncio.iscoroutine(dash_coro):
        dash_coro.close()

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
        macro_manager=macro_manager,
        audio_manager=audio_manager,
        energy_manager=energy_manager,
        vision_manager=vision_manager,
        habit_manager=habit_manager,
        commissioning_manager=commissioning_manager,
        federation_manager=federation_manager,
        rules_manager=rules_manager,
    )

    if hasattr(conversation, "async_register_agent"):
        conversation.async_register_agent(hass, agent)
    else:
        conversation.async_set_agent(hass, entry, agent)

    # Remediate any entity area assignments that trigger HA core repairs
    try:
        from .commissioning_manager import async_remediate_entity_area_repairs
        remediated_count = await async_remediate_entity_area_repairs(hass)
        if remediated_count > 0:
            _LOGGER.info("Otis AI self-healed %d entity area assignments to clear HA core repairs", remediated_count)
    except Exception as err:
        _LOGGER.debug("Could not run entity area remediation: %s", err)
    
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
        "macro_manager": macro_manager,
        "audio_manager": audio_manager,
        "energy_manager": energy_manager,
        "vision_manager": vision_manager,
        "habit_manager": habit_manager,
        "commissioning_manager": commissioning_manager,
        "federation_manager": federation_manager,
        "rules_manager": rules_manager,
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

    def _get_entry_data() -> dict:
        return hass.data.get(DOMAIN, {}).get(entry.entry_id, {})

    def _get_engine() -> DiscoveryEngine:
        return _get_entry_data().get("engine", engine)

    def _get_automation_manager() -> AutomationManager:
        return _get_entry_data().get("automation_manager", automation_manager)

    def _get_spatial_manager() -> SpatialGraphManager:
        return _get_entry_data().get("spatial_manager", spatial_manager)

    def _get_floorplan_parser() -> FloorplanParser:
        return _get_entry_data().get("floorplan_parser", floorplan_parser)

    def _get_theme_manager() -> ThemeManager:
        return _get_entry_data().get("theme_manager", theme_manager)

    def _get_sentinel_manager() -> SentinelManager:
        return _get_entry_data().get("sentinel_manager", sentinel_manager)

    def _get_dashboard_manager() -> DashboardManager:
        return _get_entry_data().get("dashboard_manager", dashboard_manager)

    def _get_macro_manager() -> MacroManager:
        return _get_entry_data().get("macro_manager", macro_manager)

    def _get_audio_manager() -> AudioHandoffManager:
        return _get_entry_data().get("audio_manager", audio_manager)

    def _get_energy_manager() -> EnergyManager:
        return _get_entry_data().get("energy_manager", energy_manager)

    def _get_vision_manager() -> VisionPresenceManager:
        return _get_entry_data().get("vision_manager", vision_manager)

    def _get_habit_manager() -> BehavioralHabitManager:
        return _get_entry_data().get("habit_manager", habit_manager)

    def _get_commissioning_manager() -> AutonomousCommissioningManager:
        return _get_entry_data().get("commissioning_manager", commissioning_manager)

    def _get_federation_manager() -> FederationManager:
        return _get_entry_data().get("federation_manager", federation_manager)

    def _get_rules_manager() -> BehavioralRulesManager:
        return _get_entry_data().get("rules_manager", rules_manager)

    def _get_active_managers():
        return (
            _get_engine(),
            _get_automation_manager(),
            _get_spatial_manager(),
            _get_floorplan_parser(),
            _get_theme_manager(),
            _get_sentinel_manager(),
            _get_dashboard_manager(),
            _get_macro_manager(),
            _get_audio_manager(),
            _get_energy_manager(),
            _get_vision_manager(),
            _get_habit_manager(),
            _get_commissioning_manager(),
            _get_federation_manager(),
        )

    async def handle_get_capability_map(call) -> ServiceResponse:
        """Handle service call to get the capability map."""
        _LOGGER.debug("Service 'get_capability_map' triggered")
        eng = _get_engine()
        capability_map = await eng.async_build_capability_map()
        capability_map["conversation_agent_id"] = entry.entry_id
        return capability_map

    async def handle_get_suggestions(call) -> ServiceResponse:
        """Handle service call to retrieve proactive suggestions."""
        _LOGGER.debug("Service 'get_suggestions' triggered")
        eng = _get_engine()
        capability_map = await eng.async_build_capability_map()
        return {"suggestions": capability_map.get("proactive_suggestions", [])}

    async def handle_apply_suggestion(call) -> ServiceResponse:
        """Handle service call to apply a proactive suggestion."""
        suggestion_id = call.data.get("suggestion_id")
        _LOGGER.debug("Service 'apply_suggestion' triggered for ID: %s", suggestion_id)
        if not suggestion_id:
            return {"success": False, "error": "Missing suggestion_id parameter"}

        eng = _get_engine()
        mgr = _get_automation_manager()
        sm = _get_sentinel_manager()
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
                    entry = entity_reg.async_get(ent_id) if (ent_id and hasattr(entity_reg, "async_get")) else None
                    actual_dev = dev_id or (getattr(entry, "device_id", None) if entry else None)
                    has_own_name = bool(getattr(entry, "name", None))

                    if actual_dev and hasattr(device_reg, "async_update_device"):
                        device_reg.async_update_device(actual_dev, area_id=area_id)
                        if ent_id and getattr(entry, "area_id", None) is not None and hasattr(entity_reg, "async_update_entity"):
                            entity_reg.async_update_entity(ent_id, area_id=None)
                        assigned_count += 1
                    elif ent_id and hasattr(entity_reg, "async_update_entity"):
                        if not has_own_name:
                            own_name = getattr(entry, "original_name", None) or ent_id.split(".")[-1].replace("_", " ").title()
                            entity_reg.async_update_entity(ent_id, area_id=area_id, name=own_name)
                        else:
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
                    entry = entity_reg.async_get(ent_id) if hasattr(entity_reg, "async_get") else None
                    actual_dev = getattr(entry, "device_id", None) if entry else None
                    has_own_name = bool(getattr(entry, "name", None))

                    if actual_dev and hasattr(device_reg, "async_update_device"):
                        device_reg.async_update_device(actual_dev, area_id=area_id)
                        if getattr(entry, "area_id", None) is not None and hasattr(entity_reg, "async_update_entity"):
                            entity_reg.async_update_entity(ent_id, area_id=None)
                        assigned_count += 1
                    elif hasattr(entity_reg, "async_update_entity"):
                        if not has_own_name:
                            own_name = getattr(entry, "original_name", None) or ent_id.split(".")[-1].replace("_", " ").title()
                            entity_reg.async_update_entity(ent_id, area_id=area_id, name=own_name)
                        else:
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
                "action": "open_failover_modal",
                "message": "Opening AI Failover Redundancy Guide...",
            }
        elif action_type == "upload_walkthrough":
            return {
                "success": True,
                "action": "open_walkthrough_modal",
                "message": "Ready to upload video walkthrough or generate floor plan.",
            }
        elif action_type == "load_shed":
            em = _get_energy_manager()
            tier = payload.get("tier", 1)
            target_watts = payload.get("target_watts", 0)
            res = await em.async_execute_load_shed(tier=tier, target_watts=target_watts)
            _invalidate()
            return res
        elif action_type in ("call_service", "remediate_contextual_alert"):
            svc = payload.get("service")
            target = payload.get("target") or {}
            s_data = payload.get("service_data") or payload.get("data") or {}
            if svc:
                s_domain, s_name = svc.split(".", 1)
                await hass.services.async_call(s_domain, s_name, s_data, target=target, context=call.context)
                _invalidate()
                btn_lbl = payload.get("button_label") or svc
                return {"success": True, "message": f"Successfully performed: {btn_lbl}"}
            return {"success": False, "error": "Missing service for contextual alert remediation"}
        elif action_type == "chat_prompt":
            return {
                "success": True,
                "action": "open_chat_prompt",
                "prompt": payload.get("prompt", ""),
                "message": f"Prompt queued for Assist Co-Pilot: '{payload.get('prompt', '')}'",
            }
        elif action_type == "auto_commission_entities":
            cm = _get_commissioning_manager()
            min_conf = float(payload.get("min_confidence", 0.85))
            res = await cm.async_auto_commission(min_confidence=min_conf)
            _invalidate()
            return res
        elif action_type == "sync_federated_nodes":
            fm = _get_federation_manager()
            node_id = payload.get("node_id")
            if node_id:
                res = await fm.async_sync_node(node_id)
            else:
                res = await fm.async_sync_all_nodes()
            _invalidate()
            return {"success": True, "sync_results": res}

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

        if hasattr(hass, "bus") and hasattr(hass.bus, "async_fire"):
            try:
                hass.bus.async_fire("otis_ai_reasoning_step", {
                    "conversation_id": conv_id,
                    "step": "intent",
                    "title": "Parsing Intent",
                    "detail": "Analyzing prompt requirements and spatial context",
                })
            except Exception:
                pass

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
        s_mgr = _get_spatial_manager()
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
            eng = _get_engine()
            s_mgr = _get_spatial_manager()
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
        eng = _get_engine()
        fp = _get_floorplan_parser()
        dm = _get_dashboard_manager()
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
        if dm and hasattr(dm, "async_ensure_admin_companion_dashboard"):
            try:
                cap_map = (
                    await eng.async_build_capability_map()
                    if hasattr(eng, "async_build_capability_map")
                    else None
                )
                await dm.async_ensure_admin_companion_dashboard(cap_map)
                await dm.async_ensure_user_command_center_dashboard(cap_map)
                hass.bus.async_fire("lovelace_updated", {"url_path": "otis-ai"})
                hass.bus.async_fire("lovelace_updated", {"url_path": "command-center"})
                hass.bus.async_fire("otis_ai_floorplan_updated", {"url": res.get("url")})
            except Exception as d_err:
                _LOGGER.debug("Could not refresh dashboards after floorplan generation: %s", d_err)
        return res

    async def handle_update_floorplan_layout(call) -> ServiceResponse:
        """Handle service call to adjust floorplan marker and room layout coordinates."""
        _LOGGER.debug("Service 'update_floorplan_layout' triggered with: %s", call.data)
        eng = _get_engine()
        fp = _get_floorplan_parser()
        dm = _get_dashboard_manager()
        badges = call.data.get("badges")
        rooms = call.data.get("rooms")
        deleted_rooms = call.data.get("deleted_rooms")
        svg_path = call.data.get("svg_path", "www/otis_floorplan.svg")
        res = await fp.async_update_floorplan_layout(
            badges=badges,
            rooms=rooms,
            deleted_rooms=deleted_rooms,
            svg_relative_path=svg_path,
        )
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        if dm and hasattr(dm, "async_ensure_admin_companion_dashboard"):
            try:
                cap_map = (
                    await eng.async_build_capability_map()
                    if hasattr(eng, "async_build_capability_map")
                    else None
                )
                await dm.async_ensure_admin_companion_dashboard(cap_map)
                await dm.async_ensure_user_command_center_dashboard(cap_map)
                hass.bus.async_fire("lovelace_updated", {"url_path": "otis-ai"})
                hass.bus.async_fire("lovelace_updated", {"url_path": "command-center"})
                hass.bus.async_fire("otis_ai_floorplan_updated", {"url": res.get("url")})
            except Exception as d_err:
                _LOGGER.debug("Could not refresh dashboards after floorplan update: %s", d_err)
        return res

    async def handle_sync_dashboards(call) -> ServiceResponse:
        """Handle service call to synchronize Studios and Rooms across Otis AI and Command Center."""
        _LOGGER.debug("Service 'sync_dashboards' triggered")
        eng = _get_engine()
        dm = _get_dashboard_manager()
        cap_map = (
            await eng.async_build_capability_map(force_refresh=True)
            if hasattr(eng, "async_build_capability_map")
            else None
        )
        admin_res = await dm.async_ensure_admin_companion_dashboard(cap_map)
        user_res = await dm.async_ensure_user_command_center_dashboard(cap_map)
        hass.bus.async_fire("lovelace_updated", {"url_path": "otis-ai"})
        hass.bus.async_fire("lovelace_updated", {"url_path": "command-center"})
        return {
            "success": True,
            "message": "Synchronized Studios, Glance cards, and Rooms across Otis AI and Command Center dashboards",
            "admin_dashboard": admin_res,
            "command_center": user_res,
        }

    async def handle_generate_theme(call) -> ServiceResponse:
        """Handle service call to generate and persist a custom theme."""
        _LOGGER.debug("Service 'generate_theme' triggered with: %s", call.data)
        eng = _get_engine()
        tm = _get_theme_manager()
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
        tm = _get_theme_manager()
        ok = await tm.async_apply_theme(theme_name, mode=mode, user_id=user_id, all_users=all_users)
        return {"success": ok, "theme": theme_name}

    async def handle_list_themes(call) -> ServiceResponse:
        """Handle service call to list generated Otis themes."""
        _LOGGER.debug("Service 'list_themes' triggered")
        tm = _get_theme_manager()
        themes = await tm.async_list_otis_themes()
        return {"themes": themes, "presets": list(PRESET_THEMES.keys())}

    async def handle_delete_theme(call) -> ServiceResponse:
        """Handle service call to delete an Otis theme."""
        theme_name = call.data.get("name") or call.data.get("theme_name")
        _LOGGER.debug("Service 'delete_theme' triggered for: %s", theme_name)
        if not theme_name:
            return {"success": False, "error": "Missing theme 'name' parameter"}
        eng = _get_engine()
        tm = _get_theme_manager()
        deleted = await tm.async_delete_theme(theme_name)
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        return {"success": deleted, "theme": theme_name}

    async def handle_run_sentinel_watchdog(call) -> ServiceResponse:
        """Handle service call to run Sentinel watchdog audit."""
        _LOGGER.debug("Service 'run_sentinel_watchdog' triggered")
        eng = _get_engine()
        sm = _get_sentinel_manager()
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
        eng = _get_engine()
        sm = _get_sentinel_manager()
        res = await sm.async_remediate_anomaly(anomaly_id, action=action)
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        return res

    async def handle_get_sentinel_telemetry(call) -> ServiceResponse:
        """Handle service call to retrieve Sentinel telemetry."""
        _LOGGER.debug("Service 'get_sentinel_telemetry' triggered")
        sm = _get_sentinel_manager()
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
        eng = _get_engine()
        sm = _get_sentinel_manager()
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
        eng = _get_engine()
        dm = _get_dashboard_manager()
        cap_map = (
            await eng.async_build_capability_map(force_refresh=True)
            if hasattr(eng, "async_build_capability_map")
            else {}
        )
        res = await dm.async_ensure_user_command_center_dashboard(cap_map)
        hass.bus.async_fire("lovelace_updated", {"url_path": "command-center"})
        return {"success": True, "dashboard": res}

    async def handle_execute_macro(call) -> ServiceResponse:
        """Handle service call to execute a multi-step smart macro pipeline."""
        _LOGGER.debug("Service 'execute_macro' triggered: %s", call.data)
        eng = _get_engine()
        mm = _get_macro_manager()
        macro_name = call.data.get("macro_name") or "Custom Macro"
        steps = call.data.get("steps")
        confirmed = call.data.get("confirmed", False)
        macro_id = call.data.get("macro_id")

        if not steps and macro_name:
            cap_map = await eng.async_build_capability_map()
            smart = mm.build_smart_macro(macro_name, capability_map=cap_map)
            macro_name = smart["name"]
            steps = smart["steps"]

        res = await mm.async_execute_macro(
            macro_name=macro_name,
            steps=steps or [],
            confirmed=confirmed,
            macro_id=macro_id,
            context=call.context,
        )
        return res

    async def handle_rollback_macro(call) -> ServiceResponse:
        """Handle service call to roll back an executed macro."""
        _LOGGER.debug("Service 'rollback_macro' triggered: %s", call.data)
        mm = _get_macro_manager()
        macro_id = call.data.get("macro_id")
        res = await mm.async_rollback_macro(macro_id=macro_id)
        return res

    async def handle_list_macros(call) -> ServiceResponse:
        """Handle service call to list available macros and execution history."""
        _LOGGER.debug("Service 'list_macros' triggered")
        mm = _get_macro_manager()
        templates = [
            {
                "template": "movie_night",
                "name": "Movie Night Mode",
                "description": "Dim media room lights, power on TV and select HDMI source, adjust climate, and set soundbar/AVR volume.",
            },
            {
                "template": "goodnight",
                "name": "Goodnight Routine",
                "description": "Extinguish common lights, engage deadbolts, close garage doors, set night climate, and arm perimeter security.",
            },
            {
                "template": "party_mode",
                "name": "Entertain & Party Mode",
                "description": "Broadcast matrix audio across output zones, set warm scene lighting, and social climate.",
            },
            {
                "template": "away_mode",
                "name": "Away & Lockdown Mode",
                "description": "Extinguish all lighting, secure deadbolts, close garage doors, and arm security away.",
            },
            {
                "template": "welcome_home",
                "name": "Welcome Home Arrival",
                "description": "Pathway lighting, comfortable temperature, entry door unlock, and alarm disarm.",
            },
        ]
        history = mm.get_history()
        return {"templates": templates, "history": history}

    def _get_audio_manager() -> AudioHandoffManager:
        entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        return entry_data.get("audio_manager", audio_manager)

    async def handle_audio_handoff(call) -> ServiceResponse:
        """Handle service call to transfer or mirror audio across rooms."""
        _LOGGER.debug("Service 'audio_handoff' triggered: %s", call.data)
        am = _get_audio_manager()
        source_area = call.data.get("source_area")
        target_area = call.data.get("target_area")
        mode = call.data.get("mode", "handoff")
        player = call.data.get("player")
        idle_guard = call.data.get("idle_power_guard", True)
        return await am.async_audio_handoff(
            source_area=source_area,
            target_area=target_area,
            mode=mode,
            player_entity_id=player,
            idle_power_guard=idle_guard,
        )

    async def handle_media_follow_me(call) -> ServiceResponse:
        """Handle service call to follow audio playback dynamically into a newly entered room."""
        _LOGGER.debug("Service 'media_follow_me' triggered: %s", call.data)
        am = _get_audio_manager()
        source_area = call.data.get("source_area")
        target_area = call.data.get("target_area")
        mode = call.data.get("mode", "follow")
        return await am.async_audio_handoff(
            source_area=source_area,
            target_area=target_area,
            mode=mode,
            idle_power_guard=True,
        )

    async def handle_release_idle_sources(call) -> ServiceResponse:
        """Handle idle power guard to pause unmonitored streamers and idle amp zones."""
        _LOGGER.debug("Service 'release_idle_sources' triggered")
        am = _get_audio_manager()
        return await am.async_release_idle_sources()

    async def handle_notify_voice(call) -> ServiceResponse:
        """Handle voice feedback routing via notify_router or direct TTS."""
        _LOGGER.debug("Service 'notify_voice' triggered: %s", call.data)
        am = _get_audio_manager()
        msg = call.data.get("message", "")
        area_id = call.data.get("area_id")
        person = call.data.get("person_entity_id")
        announce = call.data.get("announce", True)
        duck_media = call.data.get("duck_media", True)
        duck_duration = call.data.get("duck_duration")
        whisper_mode = call.data.get("whisper_mode", False)
        return await am.async_notify_voice(
            message=msg,
            area_id=area_id,
            person_entity_id=person,
            announce=announce,
            duck_media=duck_media,
            duck_duration=duck_duration,
            whisper_mode=whisper_mode,
        )

    async def handle_duck_media(call) -> ServiceResponse:
        """Handle service call to temporarily duck or pause active media playback."""
        _LOGGER.debug("Service 'duck_media' triggered: %s", call.data)
        am = _get_audio_manager()
        areas = call.data.get("areas")
        duck_ratio = float(call.data.get("duck_ratio", 0.25))
        duck_level = float(call.data.get("duck_level", 0.15))
        session_id = call.data.get("session_id")
        return await am.async_duck_media(
            areas=areas,
            duck_ratio=duck_ratio,
            duck_level=duck_level,
            session_id=session_id,
        )

    async def handle_restore_media(call) -> ServiceResponse:
        """Handle service call to restore previously ducked media playback."""
        _LOGGER.debug("Service 'restore_media' triggered: %s", call.data)
        am = _get_audio_manager()
        session_id = call.data.get("session_id")
        return await am.async_unduck_media(session_id=session_id)

    async def handle_get_voice_assist_status(call) -> ServiceResponse:
        """Handle service call to retrieve Assist pipelines, satellites, and wake-word status."""
        _LOGGER.debug("Service 'get_voice_assist_status' triggered")
        am = _get_audio_manager()
        return await am.async_get_assist_pipeline_status()

    async def handle_get_energy_summary(call) -> ServiceResponse:
        """Handle service call to retrieve live energy telemetry and tariff window."""
        _LOGGER.debug("Service 'get_energy_summary' triggered")
        em = _get_energy_manager()
        return await em.async_get_energy_summary()

    async def handle_load_shed(call) -> ServiceResponse:
        """Handle service call to execute dynamic load shedding."""
        _LOGGER.debug("Service 'load_shed' triggered: %s", call.data)
        em = _get_energy_manager()
        tier = call.data.get("tier", 1)
        target_watts = call.data.get("target_watts", 0)
        dry_run = call.data.get("dry_run", False)
        return await em.async_execute_load_shed(tier=tier, target_watts=target_watts, dry_run=dry_run)

    async def handle_restore_shed_loads(call) -> ServiceResponse:
        """Handle service call to restore shedded loads."""
        _LOGGER.debug("Service 'restore_shed_loads' triggered: %s", call.data)
        em = _get_energy_manager()
        record_id = call.data.get("record_id")
        return await em.async_restore_shed_loads(record_id=record_id)

    async def handle_get_presence_states(call) -> ServiceResponse:
        """Handle service call to retrieve fused room occupancy states."""
        _LOGGER.debug("Service 'get_presence_states' triggered")
        vm = _get_vision_manager()
        return await vm.async_get_presence_states()

    async def handle_analyze_camera(call) -> ServiceResponse:
        """Handle service call to analyze camera snapshot."""
        camera_entity_id = call.data.get("camera_entity_id")
        prompt = call.data.get("prompt")
        _LOGGER.debug("Service 'analyze_camera' triggered for %s", camera_entity_id)
        if not camera_entity_id:
            return {"success": False, "error": "Missing 'camera_entity_id' parameter"}
        vm = _get_vision_manager()
        return await vm.async_analyze_camera(camera_entity_id, prompt=prompt)

    async def handle_evaluate_contextual_alerts(call) -> ServiceResponse:
        """Handle service call to evaluate contextual presence alerts."""
        _LOGGER.debug("Service 'evaluate_contextual_alerts' triggered")
        vm = _get_vision_manager()
        alerts = await vm.async_evaluate_contextual_alerts()
        return {"alerts": alerts, "count": len(alerts)}

    async def handle_mine_habits(call) -> ServiceResponse:
        """Handle service call to mine historical habit routines."""
        _LOGGER.debug("Service 'mine_habits' triggered")
        hm = _get_habit_manager()
        days = call.data.get("days", 14)
        routines = await hm.async_mine_habits(days=days)
        return {"routines": routines, "count": len(routines)}

    async def handle_get_circadian_curves(call) -> ServiceResponse:
        """Handle service call to calculate circadian & seasonal curves."""
        _LOGGER.debug("Service 'get_circadian_curves' triggered")
        hm = _get_habit_manager()
        elevation = call.data.get("solar_elevation")
        return hm.calculate_circadian_curves(solar_elevation=elevation)

    async def handle_audit_habit_deviations(call) -> ServiceResponse:
        """Handle service call to audit habit deviations."""
        _LOGGER.debug("Service 'audit_habit_deviations' triggered")
        hm = _get_habit_manager()
        deviations = await hm.async_detect_habit_deviations()
        return {"deviations": deviations, "count": len(deviations)}

    async def handle_audit_unassigned_entities(call) -> ServiceResponse:
        """Handle service call to audit unassigned entities."""
        _LOGGER.debug("Service 'audit_unassigned_entities' triggered")
        cm = _get_commissioning_manager()
        min_conf = float(call.data.get("min_confidence", 0.85))
        return await cm.async_audit_unassigned(min_confidence=min_conf)

    async def handle_auto_commission_entities(call) -> ServiceResponse:
        """Handle service call to auto-commission unassigned entities."""
        _LOGGER.debug("Service 'auto_commission_entities' triggered")
        cm = _get_commissioning_manager()
        min_conf = float(call.data.get("min_confidence", 0.85))
        return await cm.async_auto_commission(min_confidence=min_conf)

    async def handle_register_federated_node(call) -> ServiceResponse:
        """Handle service call to register a remote federated node."""
        _LOGGER.debug("Service 'register_federated_node' triggered")
        fm = _get_federation_manager()
        node_id = call.data["node_id"]
        name = call.data.get("name", node_id)
        host = call.data["host"]
        port = int(call.data.get("port", 8123))
        token = call.data.get("token", "")
        ssl = bool(call.data.get("ssl", False))
        enabled = bool(call.data.get("enabled", True))
        return await fm.async_register_node(
            node_id=node_id,
            name=name,
            host=host,
            port=port,
            token=token,
            ssl=ssl,
            enabled=enabled,
        )

    async def handle_remove_federated_node(call) -> ServiceResponse:
        """Handle service call to remove a remote federated node."""
        _LOGGER.debug("Service 'remove_federated_node' triggered")
        fm = _get_federation_manager()
        node_id = call.data["node_id"]
        removed = await fm.async_remove_node(node_id)
        return {"success": removed, "node_id": node_id}

    async def handle_sync_federated_nodes(call) -> ServiceResponse:
        """Handle service call to sync federated edge nodes."""
        _LOGGER.debug("Service 'sync_federated_nodes' triggered")
        fm = _get_federation_manager()
        node_id = call.data.get("node_id")
        if node_id:
            return await fm.async_sync_node(node_id)
        return await fm.async_sync_all_nodes()

    async def handle_call_remote_service(call) -> ServiceResponse:
        """Handle service call to execute service on a remote federated node."""
        _LOGGER.debug("Service 'call_remote_service' triggered")
        fm = _get_federation_manager()
        node_id = call.data["node_id"]
        domain = call.data["domain"]
        service = call.data["service"]
        service_data = call.data.get("service_data")
        return await fm.async_call_remote_service(
            node_id=node_id,
            domain=domain,
            service=service,
            service_data=service_data,
        )

    async def handle_get_federation_status(call) -> ServiceResponse:
        """Handle service call to retrieve federation summary and node status."""
        _LOGGER.debug("Service 'get_federation_status' triggered")
        fm = _get_federation_manager()
        return await fm.async_get_federation_summary()

    async def handle_get_user_rules(call) -> ServiceResponse:
        """Handle service call to retrieve user behavioral rules and persona guidelines."""
        _LOGGER.debug("Service 'get_user_rules' triggered")
        rm = _get_rules_manager()
        return {"rules": rm.get_rules()}

    async def handle_set_user_rules(call) -> ServiceResponse:
        """Handle service call to update user behavioral rules and persona guidelines."""
        _LOGGER.debug("Service 'set_user_rules' triggered with: %s", call.data)
        rm = _get_rules_manager()
        eng = _get_engine()
        dm = _get_dashboard_manager()
        rules_payload = call.data.get("rules") if isinstance(call.data.get("rules"), dict) else call.data
        updated = await rm.async_save(rules_payload)
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        if dm and hasattr(dm, "async_ensure_user_command_center_dashboard"):
            try:
                cap_map = await eng.async_build_capability_map() if hasattr(eng, "async_build_capability_map") else None
                await dm.async_ensure_user_command_center_dashboard(cap_map)
                await dm.async_ensure_admin_companion_dashboard(cap_map)
                _LOGGER.info("Otis AI: Automatically synced dashboards following behavioral rules update")
            except Exception as sync_err:
                _LOGGER.debug("Dashboard auto-sync on set_user_rules notice: %s", sync_err)
        return {"success": True, "rules": updated}

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
    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_DASHBOARDS,
        handle_sync_dashboards,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXECUTE_MACRO,
        handle_execute_macro,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ROLLBACK_MACRO,
        handle_rollback_macro,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_MACROS,
        handle_list_macros,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_AUDIO_HANDOFF,
        handle_audio_handoff,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MEDIA_FOLLOW_ME,
        handle_media_follow_me,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RELEASE_IDLE_SOURCES,
        handle_release_idle_sources,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_NOTIFY_VOICE,
        handle_notify_voice,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ENERGY_SUMMARY,
        handle_get_energy_summary,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LOAD_SHED,
        handle_load_shed,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESTORE_SHED_LOADS,
        handle_restore_shed_loads,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PRESENCE_STATES,
        handle_get_presence_states,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ANALYZE_CAMERA,
        handle_analyze_camera,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EVALUATE_CONTEXTUAL_ALERTS,
        handle_evaluate_contextual_alerts,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MINE_HABITS,
        handle_mine_habits,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_CIRCADIAN_CURVES,
        handle_get_circadian_curves,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_AUDIT_HABIT_DEVIATIONS,
        handle_audit_habit_deviations,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_AUDIT_UNASSIGNED_ENTITIES,
        handle_audit_unassigned_entities,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_AUTO_COMMISSION_ENTITIES,
        handle_auto_commission_entities,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REGISTER_FEDERATED_NODE,
        handle_register_federated_node,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_FEDERATED_NODE,
        handle_remove_federated_node,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_FEDERATED_NODES,
        handle_sync_federated_nodes,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CALL_REMOTE_SERVICE,
        handle_call_remote_service,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_FEDERATION_STATUS,
        handle_get_federation_status,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_USER_RULES,
        handle_get_user_rules,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_USER_RULES,
        handle_set_user_rules,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DUCK_MEDIA,
        handle_duck_media,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESTORE_MEDIA,
        handle_restore_media,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_VOICE_ASSIST_STATUS,
        handle_get_voice_assist_status,
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
            SERVICE_GET_USER_RULES,
            SERVICE_SET_USER_RULES,
            SERVICE_DUCK_MEDIA,
            SERVICE_RESTORE_MEDIA,
            SERVICE_GET_VOICE_ASSIST_STATUS,
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
        macro_manager: MacroManager | None = None,
        audio_manager: AudioHandoffManager | None = None,
        energy_manager: EnergyManager | None = None,
        vision_manager: VisionPresenceManager | None = None,
        habit_manager: BehavioralHabitManager | None = None,
        commissioning_manager: AutonomousCommissioningManager | None = None,
        federation_manager: FederationManager | None = None,
        rules_manager: BehavioralRulesManager | None = None,
    ) -> None:
        """Initialize the agent."""
        self.hass = hass
        self.entry = entry
        self.engine = engine
        self.automation_manager = automation_manager
        self.spatial_manager = spatial_manager or SpatialGraphManager(hass)
        self.theme_manager = theme_manager or ThemeManager(hass)
        self.sentinel_manager = sentinel_manager or SentinelManager(hass)
        self.macro_manager = macro_manager or MacroManager(hass)
        self.audio_manager = audio_manager or AudioHandoffManager(hass, spatial_manager=self.spatial_manager)
        self.energy_manager = energy_manager or EnergyManager(hass, spatial_manager=self.spatial_manager)
        self.vision_manager = vision_manager or VisionPresenceManager(hass, spatial_manager=self.spatial_manager)
        self.habit_manager = habit_manager or BehavioralHabitManager(hass, spatial_manager=self.spatial_manager)
        self.commissioning_manager = commissioning_manager or AutonomousCommissioningManager(hass, spatial_manager=self.spatial_manager)
        self.federation_manager = federation_manager or FederationManager(hass)
        self.rules_manager = rules_manager or BehavioralRulesManager(hass)

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

        def fire_progress(step_id: str, title: str, detail: str) -> None:
            if hasattr(self.hass, "bus") and hasattr(self.hass.bus, "async_fire"):
                try:
                    self.hass.bus.async_fire("otis_ai_reasoning_step", {
                        "conversation_id": user_input.conversation_id,
                        "step": step_id,
                        "title": title,
                        "detail": detail,
                    })
                except Exception:
                    pass

        fire_progress("intent", "Parsing Intent", "Analyzing natural language prompt & target domains")
        
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

        # Check for pending macro confirmation
        if conv_id in sessions and sessions[conv_id].get("pending_macro"):
            if user_text in confirmations:
                pending_m = sessions[conv_id].pop("pending_macro")
                try:
                    res = await self.macro_manager.async_execute_macro(
                        macro_name=pending_m["name"],
                        steps=pending_m["steps"],
                        confirmed=True,
                        macro_id=pending_m.get("macro_id"),
                    )
                    if res.get("success"):
                        speech = (
                            f"🚀 **{pending_m['name']} Activated!**\n\n"
                            f"• {res.get('steps_executed', 0)} of {res.get('steps_total', 0)} step(s) executed successfully.\n"
                            f"• State snapshot saved for {res.get('snapshot_entities_count', 0)} entities.\n\n"
                            "*(Say 'undo' or 'rollback' anytime to revert devices to prior states)*"
                        )
                    else:
                        speech = f"⚠️ Macro execution encountered an issue: {res.get('summary', res.get('error'))}"
                    return self._create_response(user_input, speech)
                except Exception as err:
                    _LOGGER.error("Failed to execute pending macro: %s", err, exc_info=True)
                    return self._create_response(
                        user_input,
                        f"I encountered an error while executing the macro: {err}."
                    )
            elif user_text in rejections:
                sessions[conv_id].pop("pending_macro")
                return self._create_response(
                    user_input,
                    "Okay, I have cancelled the pending macro sequence."
                )

        # Check for rollback / undo commands
        if any(w in user_text for w in ("rollback", "undo macro", "revert macro", "undo last macro", "rollback macro", "undo action", "revert changes", "undo changes")):
            if self.macro_manager:
                res = await self.macro_manager.async_rollback_macro()
                if res.get("success"):
                    count = res.get("restored_count", 0)
                    speech = (
                        f"↺ **Macro Rolled Back Successfully!**\n\n"
                        f"Restored {count} entity/entities to their exact pre-execution state for **{res.get('name', 'macro')}**."
                    )
                else:
                    speech = f"⚠️ Could not roll back macro: {res.get('error', 'No restorable execution record found.')}"
                return self._create_response(user_input, speech)

        # Check for list macros command
        if any(w in user_text for w in ("list macros", "available macros", "show macros", "what macros", "macro list")):
            speech = (
                "⚡ **Otis Macro Orchestrator: Built-in Sequences**\n\n"
                "• 🎬 **Movie Night** (`prep movie night`): Dims entertainment lights, selects TV/HDMI source, lowers climate, adjusts audio volume.\n"
                "• 🌙 **Goodnight** (`bedtime routine`): Extinguishes common lights, locks deadbolts, closes garage, sets night climate, arms security.\n"
                "• 🥂 **Entertain / Party** (`party mode`): Multi-room matrix audio streaming, ambient lighting scene, social climate.\n"
                "• 🛡️ **Lockdown / Away** (`lockdown home`): Turns off non-essentials, locks all doors, closes garage, arms away security.\n"
                "• 🏡 **Welcome Home** (`arriving home`): Pathway lighting, comfortable temperature, entryway disarm & unlock.\n\n"
                "*(You can say 'run movie night' or 'undo' at any time)*"
            )
            return self._create_response(user_input, speech)

        # Check for direct multi-step macro trigger phrases
        macro_template_target = None
        if any(w in user_text for w in ("prep movie night", "movie night", "start movie night", "cinema mode", "film mode", "theater mode")):
            macro_template_target = "movie_night"
        elif any(w in user_text for w in ("bedtime routine", "goodnight routine", "goodnight mode", "time for bed", "go to sleep", "sleep mode", "goodnight")):
            macro_template_target = "goodnight"
        elif any(w in user_text for w in ("party mode", "entertain mode", "party time", "entertainment mode")):
            macro_template_target = "party_mode"
        elif any(w in user_text for w in ("lockdown home", "lock down home", "lockdown house", "away mode", "leaving home", "leaving house", "secure home")):
            macro_template_target = "away_mode"
        elif any(w in user_text for w in ("welcome home", "arriving home", "arrived home", "i'm home", "im home")):
            macro_template_target = "welcome_home"

        if macro_template_target and self.macro_manager:
            cap_map = await self.engine.async_build_capability_map()
            macro_plan = self.macro_manager.build_smart_macro(macro_template_target, capability_map=cap_map)
            safety = self.macro_manager.inspect_safety(macro_plan["steps"])

            if safety["requires_confirmation"]:
                m_id = f"macro_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                sessions[conv_id] = {
                    "pending_macro": {
                        "macro_id": m_id,
                        "name": macro_plan["name"],
                        "steps": macro_plan["steps"],
                    }
                }
                lines = [f"⚠️ **{macro_plan['name']} Prepared ({len(macro_plan['steps'])} Steps)**:"]
                for s_i, s in enumerate(macro_plan["steps"], 1):
                    lines.append(f"{s_i}. {s['name']}")
                lines.append("\n**Safety Checks:**")
                for w in safety["safety_warnings"]:
                    lines.append(f"• {w}")
                lines.append("\nWould you like me to execute this sequence now? Say 'yes' or 'confirm' to execute, or 'cancel'.")
                return self._create_response(user_input, "\n".join(lines))
            else:
                res = await self.macro_manager.async_execute_macro(
                    macro_name=macro_plan["name"],
                    steps=macro_plan["steps"],
                    confirmed=True,
                )
                lines = [f"🚀 **{macro_plan['name']} Activated!**\n"]
                for s_i, s in enumerate(macro_plan["steps"], 1):
                    lines.append(f"{s_i}. {s['name']}")
                lines.append(f"\n• State snapshot saved for {res.get('snapshot_entities_count', 0)} entities.")
                lines.append("*(Say 'undo' or 'rollback' anytime to revert your devices to their prior states)*")
                return self._create_response(user_input, "\n".join(lines))

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

        # Check for Phase 6 Audio Handoff / Follow-Me commands
        user_lower = user_text.lower()
        if self.audio_manager and any(w in user_lower for w in (
            "handoff audio", "hand off audio", "transfer music", "transfer audio",
            "follow me to", "music follow me", "audio follow me", "switch audio to",
            "move music to", "move audio to", "audio handoff", "audio transfer"
        )):
            target_match = re.search(r"(?:to|into)\s+(?:the\s+)?([a-zA-Z0-9_\s'-]+)$", user_input.text, re.IGNORECASE)
            source_match = re.search(r"(?:from)\s+(?:the\s+)?([a-zA-Z0-9_\s'-]+?)\s+(?:to|into)", user_input.text, re.IGNORECASE)
            target_area = target_match.group(1).strip() if target_match else ""
            source_area = source_match.group(1).strip() if source_match else ""
            mode = "follow" if "follow" in user_lower else "handoff"
            if target_area:
                zones = await self.audio_manager.async_get_active_media_zones()
                active_playing = [
                    z for z in (zones["matrix_zones"] + zones["other_players"])
                    if z["state"] in ("playing", "on") and z.get("area_id")
                ]
                if not source_area and active_playing:
                    source_area = active_playing[0]["area_id"]
                if source_area:
                    res = await self.audio_manager.async_audio_handoff(
                        source_area=source_area,
                        target_area=target_area,
                        mode=mode,
                        idle_power_guard=True,
                    )
                    if res.get("success"):
                        return self._create_response(user_input, res["message"])
                    return self._create_response(user_input, f"⚠️ Audio handoff: {res.get('error')}")

        # Check for Release Idle Sources command
        if self.audio_manager and any(w in user_lower for w in (
            "release idle sources", "turn off idle amp", "turn off idle zones",
            "pause idle streamers", "stop idle music", "idle power guard"
        )):
            res = await self.audio_manager.async_release_idle_sources()
            return self._create_response(user_input, res["message"])

        # Check for Roadmap Item 9 Voice Assist & Ducking commands
        if self.audio_manager and any(w in user_lower for w in (
            "voice assist status", "assist pipeline status", "assist status", "wake word status", "satellite status", "voice status"
        )):
            st = await self.audio_manager.async_get_assist_pipeline_status()
            pref = st.get("preferred_pipeline") or "Default"
            pipes = st.get("total_pipelines", 0)
            sats = st.get("total_satellites", 0)
            engines = len(st.get("wake_word_engines", []))
            quiet_state = f"Active (capped at {st.get('quiet_hours_volume_cap')}%)" if st.get("quiet_hours_active") else "Inactive"
            speech = (
                f"🎙️ **Voice Assist & Pipeline Status**\n\n"
                f"• **Preferred Pipeline**: {pref} (Total pipelines: {pipes})\n"
                f"• **Voice Satellites**: {sats} registered\n"
                f"• **Wake Word Engines**: {engines} active\n"
                f"• **Quiet Hours**: {quiet_state}\n"
                f"• **Active Audio Ducking Sessions**: {st.get('active_ducking_sessions', 0)}"
            )
            return self._create_response(user_input, speech)

        if self.audio_manager and any(w in user_lower for w in (
            "duck media", "duck audio", "duck music", "lower music", "attenuate audio", "lower background music"
        )):
            res = await self.audio_manager.async_duck_media()
            return self._create_response(user_input, res["message"])

        if self.audio_manager and any(w in user_lower for w in (
            "restore media", "unduck media", "restore music", "unmute music volume", "raise music back up"
        )):
            res = await self.audio_manager.async_unduck_media()
            return self._create_response(user_input, res["message"])

        # Check for Phase 7 Energy & Predictive Load commands
        if self.energy_manager and any(w in user_lower for w in (
            "energy summary", "power summary", "how much power", "current power",
            "current load", "power usage", "energy usage", "electricity load",
            "what devices are drawing power", "top power consumers", "top power devices",
            "active power", "live power", "energy load"
        )):
            fire_progress("domain", "Energy Telemetry", "Querying active power meters & tariff window")
            summary = await self.energy_manager.async_get_energy_summary()
            total_w = summary.get("total_power_w", 0)
            tariff = summary.get("tariff", {})
            solar = summary.get("solar", {})
            ups = summary.get("ups_storage", {})
            top = summary.get("top_consumers", [])

            lines = [
                "⚡ **Otis Energy & Load Orchestrator**\n",
                f"• **Current Home Draw:** `{total_w} W` across {summary.get('active_power_sensors_count', 0)} active monitoring circuits.",
                f"• **Grid Tariff Window:** `{tariff.get('period', 'standard').upper()}` ({tariff.get('peak_window_description', 'Standard')}) - {tariff.get('hours_until_change', 0)}h until rate transition.",
            ]
            if solar.get("production_w", 0) > 0 or solar.get("solar_elevation_deg") is not None:
                lines.append(f"• **Solar Generation:** `{solar.get('production_w', 0)} W` (Sun elevation: {solar.get('solar_elevation_deg', 0)}°).")
            if ups:
                lines.append(f"• **AV/Rack UPS Storage:** {ups.get('battery_charge', '100%')} charge ({ups.get('battery_runtime', 'N/A')}s runtime).")
            if top:
                lines.append("\n**Top Active Consumers Right Now:**")
                for i, c in enumerate(top[:5], 1):
                    lines.append(f"{i}. **{c['name']}**: `{c['power_w']} W`")

            lines.append("\n*(Say 'shed non-essential loads' to shed deferrable loads during peak hours, or 'restore shedded loads')*")
            return self._create_response(user_input, "\n".join(lines))

        # Check for Load Shedding commands
        if self.energy_manager and any(w in user_lower for w in (
            "shed non-essential loads", "shed non essentials", "shed peak loads",
            "load shedding", "shed load", "shed loads", "cut peak power", "cut power"
        )):
            fire_progress("macro", "Executing Load Shed", "Snapshotting states & shedding deferrable loads")
            res = await self.energy_manager.async_execute_load_shed(tier=1)
            if res.get("success"):
                speech = (
                    f"⚡ **Dynamic Load Shedding Executed!**\n\n"
                    f"• {res.get('message')}\n"
                    f"• Shed Entities: `{', '.join(res.get('executed_entities', [])) or 'None'}`\n\n"
                    f"*(Say 'restore shedded loads' anytime to return devices to their prior states)*"
                )
            else:
                speech = f"⚠️ Load shedding: {res.get('error', 'Encountered an issue.')}"
            return self._create_response(user_input, speech)

        # Check for Restore Shed Loads commands
        if self.energy_manager and any(w in user_lower for w in (
            "restore shedded loads", "restore shed loads", "undo load shed",
            "restore shedded", "restore power loads"
        )):
            fire_progress("macro", "Restoring Loads", "Restoring shedded loads to prior snapshot states")
            res = await self.energy_manager.async_restore_shed_loads()
            return self._create_response(user_input, res.get("message", res.get("error", "")))

        # Check for Presence / Occupancy queries (Phase 8)
        if getattr(self, "vision_manager", None) and any(w in user_lower for w in (
            "who is in the house", "who is home", "is anyone home", "is anybody home",
            "room occupancy", "which rooms are occupied", "presence status",
            "house occupancy", "who is in"
        )):
            fire_progress("domain", "Fusing Presence Sensors", "Calculating multi-sensor room occupancy probabilities")
            pres = await self.vision_manager.async_get_presence_states()
            occ = pres.get("occupied_areas", [])
            likely = pres.get("likely_areas", [])
            lines = ["👁️ **Otis Multi-Modal Presence Intelligence**\n"]
            if occ:
                lines.append(f"• **Occupied Rooms ({len(occ)}):** {', '.join(occ)}")
            if likely:
                lines.append(f"• **Likely Occupied ({len(likely)}):** {', '.join(likely)}")
            if not occ and not likely:
                lines.append("• **All Rooms Vacant:** No active room motion or mmWave presence detected.")
            household = "Yes, residents detected" if pres.get("household_present") else "No, all residents away"
            lines.append(f"• **Household Status:** {household}")
            return self._create_response(user_input, "\n".join(lines))

        # Check for Camera / Vision Audit queries (Phase 8)
        if getattr(self, "vision_manager", None) and any(w in user_lower for w in (
            "check cameras", "check security cameras", "analyze camera", "camera audit",
            "check front door", "check doorbell", "security audit"
        )):
            fire_progress("domain", "Auditing Cameras", "Capturing snapshots and evaluating scene tags")
            cams = await self.vision_manager.async_get_cameras()
            if not cams:
                return self._create_response(user_input, "No security cameras discovered in Home Assistant.")
            target_cam = next((c for c in cams if c.get("is_doorbell") or c.get("is_perimeter")), cams[0])
            res = await self.vision_manager.async_analyze_camera(target_cam["entity_id"])
            audit = res.get("audit", {})
            speech = (
                f"📷 **Otis Vision Audit: {audit.get('name', target_cam['name'])}**\n\n"
                f"• **Status:** `{audit.get('status', 'normal').upper()}`\n"
                f"• **Summary:** {audit.get('summary', 'Scene clear.')}\n"
                f"• **Safety Assessment:** {audit.get('safety_assessment', 'Normal baseline.')}\n"
                f"• **Detected Tags:** `{', '.join(audit.get('detected_objects', [])) or 'None'}`"
            )
            return self._create_response(user_input, speech)

        # Check for Habit Mining and Behavioral queries (Phase 9)
        if getattr(self, "habit_manager", None) and any(w in user_lower for w in (
            "habits", "learned habits", "habit routines", "behavioral", "circadian curve", "circadian lighting"
        )):
            if "circadian" in user_lower:
                curve = self.habit_manager.calculate_circadian_curves()
                light = curve["lighting_curve"]
                clim = curve["climate_curve"]
                resp = (
                    f"☀️ **Otis Seasonal & Circadian Intelligence ({curve['season']})**\n\n"
                    f"• **Circadian Phase:** `{light['circadian_phase']}` ({light['color_temp_kelvin']}K, {light['brightness_percent']}%)\n"
                    f"• **Calculated Solar Elevation:** {curve['solar_elevation']}°\n"
                    f"• **Seasonal Comfort Setpoints:** Heat {clim['target_temp_heat_f']}°F / Cool {clim['target_temp_cool_f']}°F\n"
                    f"• **Recommendation:** {clim['seasonal_recommendation']}"
                )
                return self._create_response(user_input, resp)
            else:
                fire_progress("domain", "Mining Habits", "Auditing recorder trends for recurring sequences")
                habits = await self.habit_manager.async_mine_habits()
                if not habits:
                    return self._create_response(
                        user_input,
                        "Otis hasn't discovered enough recurring trigger-action sequences in recorder history yet (needs 3+ occurrences)."
                    )
                lines = [f"📊 **Mined Behavioral Habits ({len(habits)} discovered):**\n"]
                for h in habits[:4]:
                    lines.append(f"• **{h['title']}** (Confidence: {int(h['confidence']*100)}%, {h['occurrences']}x): {h['description']}")
                return self._create_response(user_input, "\n".join(lines))

        # Check for Autonomous Home Commissioning & Multi-Node Federation queries (Phase 10)
        if getattr(self, "commissioning_manager", None) and any(w in user_lower for w in (
            "commission", "unassigned entities", "orphaned entities", "assign rooms", "assign areas"
        )):
            if any(w in user_lower for w in ("auto", "apply", "execute", "yes")):
                fire_progress("domain", "Commissioning Entities", "Executing zero-config room assignments")
                comm_res = await self.commissioning_manager.async_auto_commission(min_confidence=0.85)
                resp = (
                    f"🏠 **Otis Autonomous Home Commissioning Complete**\n\n"
                    f"• **Assigned Entities:** {comm_res.get('assigned_entities', 0)}\n"
                    f"• **Assigned Devices:** {comm_res.get('assigned_devices', 0)}\n"
                    f"• **Status:** {comm_res.get('message', 'Complete')}"
                )
                return self._create_response(user_input, resp)
            else:
                fire_progress("domain", "Auditing Unassigned", "Scanning registries for orphaned entities")
                audit = await self.commissioning_manager.async_audit_unassigned()
                total = audit.get("total_unassigned_entities", 0)
                high_conf = audit.get("high_confidence_count", 0)
                if total == 0:
                    return self._create_response(
                        user_input,
                        "✨ All entities and devices are already assigned to rooms! Your home registry is 100% organized."
                    )
                lines = [
                    f"📋 **Otis Commissioning Audit ({total} unassigned entities, {high_conf} eligible for auto-commissioning):**\n"
                ]
                for s in audit.get("suggested_assignments", [])[:5]:
                    lines.append(f"• `{s['entity_id']}` ➔ **{s['suggested_area_name']}** ({int(s['confidence']*100)}% confidence, {s['reason']})")
                if high_conf > 0:
                    lines.append("\n💡 Say *'Otis, auto commission unassigned entities'* to apply high-confidence assignments automatically.")
                return self._create_response(user_input, "\n".join(lines))

        if getattr(self, "federation_manager", None) and any(w in user_lower for w in (
            "federation", "edge node", "edge nodes", "remote node", "remote instance", "sync nodes"
        )):
            fire_progress("domain", "Federation Inspection", "Querying remote edge nodes and synchronization health")
            fed_summary = await self.federation_manager.async_get_federation_summary()
            total_nodes = fed_summary.get("total_nodes", 0)
            if total_nodes == 0:
                return self._create_response(
                    user_input,
                    "🌐 **Otis Multi-Node Federation:** No remote Home Assistant edge nodes registered yet. "
                    "Use the `otis_ai.register_federated_node` service to connect guest houses, workshops, or outbuildings."
                )
            online = fed_summary.get("online_nodes", 0)
            avg_lat = fed_summary.get("avg_latency_ms", 0.0)
            ents = fed_summary.get("total_federated_entities", 0)
            lines = [
                "🌐 **Otis Multi-Node Federation & Edge Synchronizer**\n",
                f"• **Active Nodes:** {online} / {total_nodes} Online",
                f"• **Synchronized Entities:** {ents}",
                f"• **Average Latency:** {avg_lat} ms\n",
                "**Nodes:**"
            ]
            for n in fed_summary.get("nodes", []):
                stat_icon = "🟢" if n.get("status") == "online" else "🔴"
                lines.append(f"• {stat_icon} **{n.get('name')}** (`{n.get('node_id')}`): {n.get('status')}, {n.get('latency_ms', 0)}ms, v{n.get('remote_version', 'unknown')}")
            return self._create_response(user_input, "\n".join(lines))

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
        fire_progress("topology", "Querying Topology", "Inspecting spatial adjacency graph & active entities")
        capability_map = await self.engine.async_build_capability_map()

        fire_progress("domain", "Domain Inspection", "Evaluating active audio zones, security perimeter & state history")
        # Summarize active entities by domain
        from collections import Counter
        entity_domains = Counter(e['domain'] for e in capability_map['entities'])
        entity_summary = ", ".join(f"{count} {domain}s" for domain, count in sorted(entity_domains.items()))

        # Filter active entities to only include physical control/actionable domains
        CONTROL_DOMAINS = {
            "light", "switch", "media_player", "climate", "lock", "cover", 
            "fan", "vacuum", "scene", "humidifier", "alarm_control_panel",
            "siren", "camera", "person",
        }
        control_candidates = [
            {"entity_id": e["entity_id"], "area_id": e.get("area_id"), "state": e.get("state")}
            for e in capability_map["entities"]
            if e["domain"] in CONTROL_DOMAINS
        ]
        # Prioritize active/on entities and sample inactive ones to keep prompt token size fast and lean
        active_control = [e for e in control_candidates if e["state"] not in ("off", "unavailable", "unknown", "idle")]
        inactive_sample = [e for e in control_candidates if e["state"] in ("off", "idle")][:20]
        # Compact string format e.g. 'light.dining (off) in dining_room' to dramatically reduce token and payload size
        detailed_entities = [
            f"{e['entity_id']} ({e.get('state')}) in {e.get('area_id') or 'unassigned'}"
            for e in (active_control + inactive_sample)[:40]
        ]

        # Extract existing automations and scripts concisely (capped to prevent exceeding model context)
        existing_automations = [
            f"{e['entity_id']}: {e.get('name') or ''}"
            for e in capability_map["entities"]
            if e["domain"] == "automation"
        ][:20]
        existing_scripts = [
            f"{e['entity_id']}: {e.get('name') or ''}"
            for e in capability_map["entities"]
            if e["domain"] == "script"
        ][:15]

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

        # Summarize Energy & Load Topology
        energy_topo = capability_map.get("energy_topology", {})
        if energy_topo:
            e_tariff = energy_topo.get("tariff", {}).get("period", "standard")
            e_power = energy_topo.get("total_power_w", 0)
            e_solar = energy_topo.get("solar", {}).get("production_w", 0)
            e_shed_count = energy_topo.get("load_shedding", {}).get("active_sheddable_loads_count", 0)
            energy_summary = (
                f"Total Power: {e_power}W | Tariff: {e_tariff.upper()} | Solar Generation: {e_solar}W | "
                f"Sheddable Deferrable Loads: {e_shed_count}"
            )
        else:
            energy_summary = "Not configured or inactive"

        # Summarize top proactive suggestions
        suggestions_list = capability_map.get("proactive_suggestions", [])
        suggestions_summary = "\n".join(
            f"- [{s.get('category', 'general').upper()}] {s.get('title')}: {s.get('description')}"
            for s in suggestions_list[:8]
        ) or "None currently pending."

        # 3. Format the prompt wrapping the user's input with the spatial/capability context
        conv_id = user_input.conversation_id or "default"
        session_data = sessions.setdefault(conv_id, {})
        turn_count = session_data.get("turn_count", 0) + 1
        session_data["turn_count"] = turn_count

        rules_snippet = ""
        if getattr(self, "rules_manager", None):
            rules_snippet = self.rules_manager.get_system_prompt_snippet()

        if turn_count > 1:
            # On follow-up turns, HA conversation agents retain conversational context.
            # Avoid re-sending thousands of tokens of static topology which triggers Groq/LLM HTTP 413 (Payload Too Large).
            prompt = f"""You are the Otis AI Companion, proactive smart home architect and co-pilot.
Continue assisting the user in this conversation. Leverage the home's hardware architecture (Control4 Matrix Audio, Alarmo, Climate, Energy) previously established.
Keep your response concise, structured, and actionable.

{rules_snippet}

User: {user_input.text}
"""
        else:
            prompt = f"""You are the Otis AI Companion, an intelligent, proactive smart home architect, co-pilot, and butler.
Your goal is to guide the user from a bare Home Assistant installation to a fully optimized, cohesive, automated smart home—and offer to build and configure everything for them.
Always prioritize native Home Assistant solutions, minimize frontend dependencies, and synthesize right-sized, modular coordinator automations and scripts (avoiding thousands of tiny per-entity automations or brittle monoliths).

{rules_snippet}

Here is the current capability and architecture map of the home:
- System Maturity: {maturity_summary}
- Active Integrations: {capability_map['integrations']}
- Areas: {list(capability_map['areas'].keys())}
- Spatial Adjacency (Connected Rooms): {spatial_summary}
- Discovered Media & Matrix Audio Architecture: {media_summary}
- Discovered Security, Presence & Sleep Architecture: {security_summary}
- Discovered Energy & Load Topology: {energy_summary}
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
7. When the user requests multi-step routines (such as movie night, bedtime, party, lockdown, or arrival), you can propose or trigger Otis dynamic macros, which feature atomic snapshotting and 1-click state rollback.
8. When the user asks to move music, transfer audio, or follow them between rooms, you can propose or trigger Otis Audio Handoff (`audio_handoff` / `media_follow_me`), which leverages Spatial Adjacency to route matrix amplifier zones (Control4) and streamers seamlessly.
9. When the user asks about energy usage, electrical power, peak tariff hours, or load shedding, reference the Discovered Energy & Load Topology and propose or trigger Otis dynamic load shedding (`load_shed` / `restore_shed_loads`) or appliance sequencing.
10. When proposing automations or scripts in YAML code blocks:
    - ALWAYS provide an explicit, descriptive `alias: 'Descriptive Name'` inside the YAML (e.g. `alias: 'Media Matrix Zone Coordinator'`).
    - For scripts, always include `alias:` and `sequence:`. Never output nameless script blocks.

User: {user_input.text}
"""

        # 4. Delegate to the AI agent pool with automatic transparent failover
        result = None
        last_error_msg = None

        for idx, agent_id in enumerate(prioritized_agents):
            is_primary = (idx == 0)
            role_label = "Primary" if is_primary else f"Failover #{idx}"
            _LOGGER.debug("Attempting conversation with %s AI agent: %s", role_label, agent_id)
            fire_progress("llm", f"Consulting {role_label} AI", f"Reasoning with model '{agent_id}'")

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
                            inferred_key = None
                            if len(parsed) == 1 and not ("sequence" in parsed or "trigger" in parsed or "action" in parsed):
                                single_key = next(iter(parsed.keys()))
                                single_val = parsed[single_key]
                                if isinstance(single_val, dict) and ("sequence" in single_val or "action" in single_val or "trigger" in single_val):
                                    inferred_key = single_key
                                    if "alias" not in single_val:
                                        single_val["alias"] = single_key.replace("_", " ").title()
                                    parsed = single_val

                            if "trigger" in parsed or "action" in parsed:
                                auto_name = parsed.get("alias", (inferred_key.replace("_", " ").title() if inferred_key else "Proposed Automation"))
                                parsed["alias"] = auto_name
                                sessions[conv_id] = {
                                    "pending_yaml": {
                                        "type": "automation",
                                        "yaml_data": parsed
                                    }
                                }
                                _LOGGER.debug("Stored pending automation: %s", parsed)
                                confirm_text = f"\n\nWould you like me to create and enable this automation '{auto_name}' in your Home Assistant? Say 'yes' or 'apply' to confirm, or 'no' to cancel."
                                result.response.speech["plain"]["speech"] += confirm_text
                                break
                            elif "sequence" in parsed:
                                alias = parsed.get("alias")
                                if not alias and inferred_key:
                                    alias = inferred_key.replace("_", " ").title()
                                elif not alias:
                                    user_low = user_input.text.lower()
                                    if any(w in user_low for w in ("media", "audio", "matrix", "speaker", "music", "volume", "sound")):
                                        alias = "Media Matrix Zone Coordinator"
                                    elif any(w in user_low for w in ("light", "lamp", "dimmer")):
                                        alias = "Smart Lighting Coordinator"
                                    elif any(w in user_low for w in ("climate", "temp", "thermostat", "hvac")):
                                        alias = "Climate Zone Coordinator"
                                    elif any(w in user_low for w in ("security", "lock", "alarm", "perimeter")):
                                        alias = "Perimeter Security Coordinator"
                                    else:
                                        alias = "Otis System Routine"
                                parsed["alias"] = alias
                                script_key = inferred_key or re.sub(r"\W+", "_", alias.lower()).strip("_")
                                sessions[conv_id] = {
                                    "pending_yaml": {
                                        "type": "script",
                                        "id": script_key,
                                        "yaml_data": parsed
                                    }
                                }
                                _LOGGER.debug("Stored pending script: %s with key %s", parsed, script_key)
                                confirm_text = f"\n\nWould you like me to create this script '{alias}' (`script.{script_key}`) in your Home Assistant? Say 'yes' or 'apply' to confirm, or 'no' to cancel."
                                result.response.speech["plain"]["speech"] += confirm_text
                                break
                    except Exception as yaml_err:
                        _LOGGER.debug("Failed to parse YAML block: %s", yaml_err)
        except Exception as parse_err:
            _LOGGER.error("Error parsing LLM response for YAML: %s", parse_err)

        fire_progress("synthesizing", "Synthesizing Actions", "Validating action safety guards & formatting plan")
        return result
ERROR_SIGNATURES = [
    "sorry, i had a problem getting a response from",
    "api error",
    "groq api error",
    "openai api error",
    "anthropic api error",
    "gemini api error",
    "http 413",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "payload too large",
    "request entity too large",
    "context_length_exceeded",
    "context length",
    "maximum context length",
    "too many tokens",
    "rate_limit_exceeded",
    "rate limit reached",
    "rate limit",
    "quota exceeded",
    "exceeded your current quota",
    "insufficient funds",
    "no credits remaining",
    "check your plan and billing details",
    "model is overloaded",
    "service temporarily unavailable",
    '"code": 503',
    '"code": 429',
    '"code": 413',
    '"status": "unavailable"',
    '"status": "resource_exhausted"',
    "high demand",
    "spikes in demand are usually temporary",
    "protect_free_tier",
    "free tier limit",
]


def is_provider_error(speech: str) -> bool:
    """Detect if the LLM agent returned a provider error string instead of a valid conversation response."""
    if not speech:
        return True
    speech_lower = speech.lower().strip()
    if re.search(r"\b(?:api error|error code|http\s*(?:4\d\d|5\d\d)|status\s*code\s*(?:4\d\d|5\d\d))\b", speech_lower):
        return True
    return any(sig in speech_lower for sig in ERROR_SIGNATURES)


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
        energy_manager: EnergyManager | None = None,
        vision_manager: VisionPresenceManager | None = None,
        habit_manager: BehavioralHabitManager | None = None,
        commissioning_manager: AutonomousCommissioningManager | None = None,
        federation_manager: FederationManager | None = None,
        rules_manager: BehavioralRulesManager | None = None,
    ) -> None:
        """Initialize the discovery engine."""
        self.hass = hass
        self.spatial_manager = spatial_manager or SpatialGraphManager(hass)
        self.floorplan_parser = floorplan_parser or FloorplanParser(hass)
        self.theme_manager = theme_manager or ThemeManager(hass)
        self.sentinel_manager = sentinel_manager or SentinelManager(hass)
        self.energy_manager = energy_manager or EnergyManager(hass, spatial_manager=self.spatial_manager)
        self.vision_manager = vision_manager or VisionPresenceManager(hass, spatial_manager=self.spatial_manager)
        self.habit_manager = habit_manager or BehavioralHabitManager(hass, spatial_manager=self.spatial_manager)
        self.commissioning_manager = commissioning_manager or AutonomousCommissioningManager(hass, spatial_manager=self.spatial_manager)
        self.federation_manager = federation_manager or FederationManager(hass)
        self.rules_manager = rules_manager or BehavioralRulesManager(hass)
        self.dashboard_manager = dashboard_manager or DashboardManager(
            hass, floorplan_parser=self.floorplan_parser, rules_manager=self.rules_manager
        )
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
                "custom_layout": getattr(self.floorplan_parser, "_metadata", {}).get("custom_layout", {}),
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

        energy_data = {}
        if self.energy_manager:
            try:
                energy_data = await self.energy_manager.async_get_energy_summary()
            except Exception as err:
                _LOGGER.debug("Error running Energy summary during discovery scan: %s", err)
        cap_map["energy_topology"] = energy_data

        vision_data = {}
        if getattr(self, "vision_manager", None):
            try:
                presence_states = await self.vision_manager.async_get_presence_states(use_cache=True)
                cameras = await self.vision_manager.async_get_cameras()
                vision_data = {
                    "presence": presence_states,
                    "cameras": cameras,
                    "recent_audits": self.vision_manager.get_audit_history(),
                }
            except Exception as err:
                _LOGGER.debug("Error retrieving Vision presence states during discovery scan: %s", err)
        cap_map["vision_topology"] = vision_data

        commissioning_data = {}
        if getattr(self, "commissioning_manager", None):
            try:
                commissioning_data = await self.commissioning_manager.async_audit_unassigned()
            except Exception as err:
                _LOGGER.debug("Error auditing unassigned entities: %s", err)
        cap_map["commissioning"] = commissioning_data

        federation_data = {}
        if getattr(self, "federation_manager", None):
            try:
                federation_data = await self.federation_manager.async_get_federation_summary()
            except Exception as err:
                _LOGGER.debug("Error retrieving federation summary: %s", err)
        cap_map["federation"] = federation_data

        themes = []
        if self.theme_manager:
            themes = await self.theme_manager.async_list_otis_themes()
        cap_map["themes"] = themes
        cap_map["theme_presets"] = [
            {"key": k, "name": v["name"], "description": v["description"], "preview": v["preview"], "dark_mode": v.get("dark_mode", True)}
            for k, v in PRESET_THEMES.items()
        ]

        user_rules = {}
        if getattr(self, "rules_manager", None):
            user_rules = self.rules_manager.get_rules()
        cap_map["user_rules"] = user_rules

        # Discovered registered Home Assistant users & person entities
        discovered_users = []
        try:
            if hasattr(self.hass, "auth") and hasattr(self.hass.auth, "async_get_users"):
                auth_users = await self.hass.auth.async_get_users()
                for u in auth_users:
                    if getattr(u, "is_active", True) and not getattr(u, "system_generated", False):
                        discovered_users.append({
                            "id": u.id,
                            "name": u.name or u.id,
                        })
        except Exception as u_err:
            _LOGGER.debug("Could not query auth users: %s", u_err)

        existing_uids = {u["id"] for u in discovered_users}
        for ent in entities_list:
            if ent.get("domain") == "person":
                attrs = ent.get("attributes") or {}
                uid = attrs.get("user_id")
                p_name = attrs.get("friendly_name") or ent.get("name") or ent.get("entity_id")
                if uid and uid not in existing_uids:
                    discovered_users.append({"id": uid, "name": p_name})
                    existing_uids.add(uid)
                elif not uid and ent.get("entity_id") not in existing_uids:
                    discovered_users.append({"id": ent.get("entity_id"), "name": p_name})
        cap_map["users"] = discovered_users

        cap_map["proactive_suggestions"] = await self.async_generate_proactive_suggestions(cap_map)
        self._cached_cap_map = dict(cap_map)
        self._cache_ts = now
        self._cache_signature = current_sig

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
        raw_cameras = [
            e["entity_id"]
            for e in entities_list
            if e.get("domain") == "camera" and e.get("state") not in ("unavailable", "unknown")
        ]
        cam_groups: dict[str, list[str]] = {}
        for c_eid in raw_cameras:
            if any(k in c_eid.lower() for k in ("map", "vacuum", "cleaning")):
                continue
            ckey = get_canonical_camera_key(c_eid)
            cam_groups.setdefault(ckey, []).append(c_eid)
        cameras = []
        for ckey, c_list in cam_groups.items():
            c_list.sort(key=lambda x: stream_priority(x, x))
            cameras.append(c_list[0])
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
        spatial_gaps: list[str] = []
        if len(areas_map) >= 3:
            spatial_pts += 8
        else:
            spatial_gaps.append(f"Add at least 3 areas (currently {len(areas_map)}).")

        if areas_with_entities >= max(1, len(areas_map) // 2):
            spatial_pts += 6
        else:
            spatial_gaps.append(f"Populate more areas with devices/entities ({areas_with_entities}/{len(areas_map)} populated).")

        if has_walkthrough or has_floorplan:
            spatial_pts += 6
        else:
            spatial_gaps.append("Upload a walkthrough video or create a vector Floor Plan.")

        # 2. Registry Hygiene & Area Assignment (20 pts)
        hygiene_pts = 20
        hygiene_gaps: list[str] = []
        if orphaned_entities:
            hygiene_pts -= min(10, len(orphaned_entities) * 2)
            hygiene_gaps.append(f"Clean up {len(orphaned_entities)} orphaned entities.")
        if inferred_device_assignments or inferred_entity_assignments:
            unassigned_count = len(inferred_device_assignments) + len(inferred_entity_assignments)
            hygiene_pts -= min(10, unassigned_count)
            hygiene_gaps.append(f"Commission or auto-assign {unassigned_count} unassigned devices/entities to areas.")
        hygiene_pts = max(0, hygiene_pts)

        # 3. Lighting & Climate Automation Coverage (20 pts)
        auto_pts = min(20, (automations_count * 4) + (scripts_count * 2))
        auto_gaps: list[str] = []
        if auto_pts < 20:
            needed = max(1, (20 - auto_pts + 3) // 4)
            auto_gaps.append(f"Create ~{needed} more automations or scripts (currently {automations_count} automations, {scripts_count} scripts).")

        # 4. Security & Presence Intelligence (20 pts)
        sec_pts = 0
        sec_gaps: list[str] = []
        if security_topology.get("alarm_panels") or security_topology.get("locks"):
            sec_pts += 10
        else:
            sec_gaps.append("Install an alarm panel (e.g. Alarmo) or smart locks.")

        if security_topology.get("persons") or security_topology.get("bed_occupancy_sensors"):
            sec_pts += 5
        else:
            sec_gaps.append("Configure person presence or bed occupancy sensors.")

        if automations_count >= 2:
            sec_pts += 5
        else:
            sec_gaps.append("Create at least 2 security or arrival/departure automations.")

        # 5. Media & Ecosystem Optimization (20 pts)
        media_pts = 10
        media_gaps: list[str] = []
        media_keywords = ("matrix", "router", "media", "audio", "speaker", "sound", "streamer", "music", "cinema")
        has_media_coordinator = any(
            any(kw in str(e.get("entity_id", "")).lower() or kw in str(e.get("name", "")).lower() for kw in media_keywords)
            for e in entities_list
            if e.get("domain") in ("script", "automation")
        )
        if media_topology.get("matrix_amp_detected"):
            if has_media_coordinator:
                media_pts = 20
            else:
                media_pts = 12
                media_gaps.append("Deploy an Otis Matrix Audio Router script to automate zone switching.")
        elif media_topology.get("total_media_players", 0) > 0:
            if has_media_coordinator or "music_assistant" in active_integrations or "mass" in active_integrations:
                media_pts = 20
            else:
                media_pts = 16
                media_gaps.append("Configure multi-room audio grouping or deploy a media coordinator script.")
        else:
            media_gaps.append("Add media player entities (Sonos, Cast, Apple TV, Music Assistant) to your rooms.")

        tips = {
            "spatial": "20/20 (Perfect) • Spatial organization and floor plan are fully mapped." if spatial_pts >= 20 else f"{spatial_pts}/20 • To reach 20/20: {' '.join(spatial_gaps)}",
            "hygiene": "20/20 (Perfect) • Entity registry is clean with zero unassigned or orphaned entities." if hygiene_pts >= 20 else f"{hygiene_pts}/20 • To reach 20/20: {' '.join(hygiene_gaps)}",
            "automation": "20/20 (Perfect) • Deep automation coverage across lighting, climate, and daily routines." if auto_pts >= 20 else f"{auto_pts}/20 • To reach 20/20: {' '.join(auto_gaps)}",
            "security": "20/20 (Perfect) • Complete security and presence intelligence active." if sec_pts >= 20 else f"{sec_pts}/20 • To reach 20/20: {' '.join(sec_gaps)}",
            "media": "20/20 (Perfect) • Multi-room audio matrix and media players fully coordinated." if media_pts >= 20 else f"{media_pts}/20 • To reach 20/20: {' '.join(media_gaps)}",
        }

        gaps = {
            "spatial": spatial_gaps,
            "hygiene": hygiene_gaps,
            "automation": auto_gaps,
            "security": sec_gaps,
            "media": media_gaps,
        }

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
            "tips": tips,
            "gaps": gaps,
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

        # 13. Phase 7 Energy & Predictive Load Orchestrator Suggestions
        energy_topo = capability_map.get("energy_topology", {})
        tariff_info = energy_topo.get("tariff", {})
        load_shed_info = energy_topo.get("load_shedding", {})
        solar_info = energy_topo.get("solar", {})

        if tariff_info.get("is_peak") and load_shed_info.get("active_sheddable_loads_count", 0) > 0:
            savings = round(load_shed_info.get("potential_savings_w", 0))
            suggestions.append({
                "id": "peak_load_shed_recommendation",
                "title": f"Shed High-Draw Loads for Peak Tariff (~{savings}W)",
                "category": "energy",
                "priority": "high",
                "icon": "mdi:transmission-tower-export",
                "description": (
                    f"Your electrical grid is currently in PEAK rate window. Otis detected "
                    f"{load_shed_info.get('active_sheddable_loads_count')} deferrable load(s) consuming up to {savings}W. "
                    "Shed non-essential loads now to minimize peak energy costs."
                ),
                "action_type": "load_shed",
                "action_payload": {"tier": 1},
            })

        if solar_info.get("has_surplus"):
            prod = round(solar_info.get("production_w", 0))
            suggestions.append({
                "id": "solar_surplus_sequencing",
                "title": f"Solar Production Surplus (+{prod}W Available)",
                "category": "energy",
                "priority": "medium",
                "icon": "mdi:solar-power-variant",
                "description": (
                    f"Your solar generation currently exceeds home consumption with ~{prod}W surplus. "
                    "Ideal window to charge electric vehicles, run pool filtration, or pre-heat/pre-cool rooms."
                ),
                "action_type": "chat_prompt",
                "action_payload": {"prompt": "Optimize high loads for solar production surplus"},
            })

        # 11. Multi-Modal Vision & Presence Contextual Alerts & Automation Optimizations (Phase 8)
        if getattr(self, "vision_manager", None):
            try:
                ctx_alerts = await self.vision_manager.async_evaluate_contextual_alerts()
                for alert in ctx_alerts:
                    suggestions.append(alert)

                # Generate proactive Vision & Presence automation recommendations
                presence_states = await self.vision_manager.async_get_presence_states(use_cache=True)
                p_rooms = presence_states.get("rooms", {})
                for aid, ainfo in areas.items():
                    a_name = ainfo.get("name") or aid.replace("_", " ").title()
                    a_ents = ainfo.get("entities", [])
                    has_presence = any(
                        eid.startswith("binary_sensor.") and any(k in eid.lower() for k in ("motion", "occupancy", "presence"))
                        for eid in a_ents
                    ) or aid in p_rooms
                    a_lights = [eid for eid in a_ents if eid.startswith("light.")]
                    has_vacancy_auto = any(
                        "vacancy" in name and aid in name
                        for name in all_existing_names
                    )
                    if has_presence and a_lights and not has_vacancy_auto:
                        m_sensor = next(
                            (eid for eid in a_ents if eid.startswith("binary_sensor.") and any(k in eid.lower() for k in ("motion", "occupancy", "presence"))),
                            None
                        )
                        if m_sensor:
                            suggestions.append({
                                "id": f"vision_presence_vacancy_auto_{aid}",
                                "title": f"Vision & Presence: Auto-Power Down Vacant {a_name}",
                                "category": "energy",
                                "priority": "medium",
                                "icon": "mdi:motion-sensor-off",
                                "description": (
                                    f"Presence telemetry indicates {a_name} is actively occupied during the day. "
                                    f"Deploy an intelligent 10-minute vacancy auto-off coordinator for {len(a_lights)} "
                                    "room lights to save power when residents leave."
                                ),
                                "action_type": "create_automation",
                                "action_payload": {
                                    "alias": f"Vacancy Coordinator: Auto-Off {a_name} Lights",
                                    "description": f"Automated by Otis AI Companion Vision & Presence for {a_name}",
                                    "trigger": [
                                        {
                                            "platform": "state",
                                            "entity_id": m_sensor,
                                            "to": "off",
                                            "for": {"minutes": 10},
                                        }
                                    ],
                                    "action": [
                                        {"service": "light.turn_off", "target": {"entity_id": a_lights[:5]}}
                                    ],
                                    "mode": "single",
                                },
                            })
                            break  # Surface top vacancy coordinator

                # Outdoor Camera Smart Detection Alerts
                cams = await self.vision_manager.async_get_cameras()
                for c in cams:
                    c_eid = c.get("entity_id", "")
                    c_name = c.get("name") or c_eid
                    c_lower = (c_eid + " " + c_name).lower()
                    is_outdoor = any(k in c_lower for k in ("front", "driveway", "porch", "patio", "backyard", "doorbell", "yard"))
                    has_cam_alert = any(c_name.lower() in name for name in all_existing_names)
                    if is_outdoor and not has_cam_alert:
                        c_slug = re.sub(r"\W+", "_", c_eid.lower()).strip("_")
                        suggestions.append({
                            "id": f"vision_outdoor_watchdog_{c_slug}",
                            "title": f"Vision Watchdog: Outdoor Arrival & Delivery Detection ({c_name})",
                            "category": "security",
                            "priority": "high",
                            "icon": "mdi:cctv",
                            "description": (
                                f"Connect Otis AI vision heuristics with {c_name} to broadcast actionable mobile alerts "
                                "with live snapshots when delivery vehicles, packages, or visitors approach after sunset."
                            ),
                            "action_type": "create_automation",
                            "action_payload": {
                                "alias": f"Vision Watchdog: {c_name} Person & Delivery Alert",
                                "description": "Automated by Otis AI Companion Vision Watchdog",
                                "trigger": [
                                    {
                                        "platform": "state",
                                        "entity_id": c_eid,
                                        "to": "recording",
                                    }
                                ],
                                "condition": [
                                    {"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"}
                                ],
                                "action": [
                                    {
                                        "service": "notify.notify",
                                        "data": {
                                            "title": f"Security Notice: Activity at {c_name}",
                                            "message": f"Otis detected evening activity on {c_name}.",
                                        },
                                    }
                                ],
                                "mode": "single",
                            },
                        })
                        break  # Surface 1 primary outdoor camera suggestion
            except Exception as err:
                _LOGGER.debug("Error evaluating contextual alerts: %s", err)

        # 12. Self-Supervised Habit Learning & Behavioral Routines (Phase 9)
        if getattr(self, "habit_manager", None):
            try:
                deviations = await self.habit_manager.async_detect_habit_deviations()
                for dev in deviations:
                    suggestions.append(dev)

                mined_habits = await self.habit_manager.async_mine_habits(days=14, min_occurrences=3)
                for routine in mined_habits[:2]:
                    suggestions.append(routine)
            except Exception as err:
                _LOGGER.debug("Error evaluating habit routine suggestions: %s", err)

        # 13. Autonomous Home Commissioning (Phase 10)
        if getattr(self, "commissioning_manager", None):
            try:
                comm_audit = await self.commissioning_manager.async_audit_unassigned()
                high_conf = comm_audit.get("high_confidence_count", 0)
                if high_conf > 0:
                    suggestions.append({
                        "id": f"auto_commission_{high_conf}_entities",
                        "title": f"Autonomous Commissioning: {high_conf} Unassigned Entities Detected",
                        "category": "cleanup",
                        "priority": "high" if high_conf >= 3 else "medium",
                        "icon": "mdi:home-plus",
                        "description": (
                            f"Otis discovered {high_conf} unassigned entities with strong heuristic & spatial "
                            "room matches (e.g. naming tokens and parent device topology). "
                            "Click to automatically commission them with zero manual configuration."
                        ),
                        "action_type": "auto_commission_entities",
                        "action_payload": {"min_confidence": 0.85},
                    })
            except Exception as err:
                _LOGGER.debug("Error generating commissioning suggestions: %s", err)

        # 14. Multi-Node Federation Edge Sync (Phase 10)
        if getattr(self, "federation_manager", None):
            try:
                fed_summary = await self.federation_manager.async_get_federation_summary()
                offline = fed_summary.get("offline_nodes", 0)
                total_nodes = fed_summary.get("total_nodes", 0)
                if offline > 0:
                    suggestions.append({
                        "id": "federation_offline_alert",
                        "title": f"Federation Alert: {offline} Remote Edge Node(s) Unreachable",
                        "category": "system",
                        "priority": "high",
                        "icon": "mdi:server-network-off",
                        "description": (
                            f"{offline} of {total_nodes} federated Home Assistant edge nodes are unreachable. "
                            "Inspect network link or trigger edge resynchronization."
                        ),
                        "action_type": "sync_federated_nodes",
                        "action_payload": {},
                    })
            except Exception as err:
                _LOGGER.debug("Error generating federation suggestions: %s", err)

        # 15. Smart Home Maturity Improvement Cards (Guarantee actionable cards for any dimension < 20/20)
        bd = maturity.get("breakdown", {})
        mat_gaps = maturity.get("gaps", {})

        # Spatial Maturity (< 20)
        if bd.get("spatial", 20) < 20 and not any(
            s.get("category") == "visualization" or "floor" in s.get("id", "") or "pathway" in s.get("id", "")
            for s in suggestions
        ):
            spatial_desc = (
                " ".join(mat_gaps.get("spatial", []))
                if mat_gaps.get("spatial")
                else "Upload a walkthrough video or map your rooms to unlock 20/20 spatial intelligence."
            )
            suggestions.append({
                "id": "maturity_reach_20_spatial",
                "title": f"Maturity Goal: Reach 20/20 Spatial Organization ({bd.get('spatial', 0)}/20)",
                "category": "system",
                "priority": "medium",
                "icon": "mdi:floor-plan",
                "description": (
                    f"Otis spatial maturity is at {bd.get('spatial', 0)}/20. {spatial_desc} "
                    "Achieving 20/20 gives Otis complete spatial context for room-aware commands and auto-routing."
                ),
                "action_type": "upload_walkthrough",
                "action_payload": {},
            })

        # Hygiene Maturity (< 20)
        if bd.get("hygiene", 20) < 20 and not any(
            s.get("category") == "cleanup" for s in suggestions
        ):
            hygiene_desc = (
                " ".join(mat_gaps.get("hygiene", []))
                if mat_gaps.get("hygiene")
                else "Clean up orphaned entities or assign unassigned devices to areas."
            )
            suggestions.append({
                "id": "maturity_reach_20_hygiene",
                "title": f"Maturity Goal: Reach 20/20 Registry Hygiene ({bd.get('hygiene', 0)}/20)",
                "category": "cleanup",
                "priority": "medium",
                "icon": "mdi:broom",
                "description": (
                    f"Registry hygiene is at {bd.get('hygiene', 0)}/20. {hygiene_desc} "
                    "A clean registry prevents state engine collisions and ensures 100% entity addressability."
                ),
                "action_type": "auto_commission_entities",
                "action_payload": {},
            })

        # Automation Maturity (< 20)
        if bd.get("automation", 20) < 20 and not any(
            s.get("category") in ("automation", "lighting", "habit_routine") for s in suggestions
        ):
            auto_desc = (
                " ".join(mat_gaps.get("automation", []))
                if mat_gaps.get("automation")
                else "Add essential occupancy lighting, sunset, or climate automations."
            )
            suggestions.append({
                "id": "maturity_reach_20_automation",
                "title": f"Maturity Goal: Reach 20/20 Automation Depth ({bd.get('automation', 0)}/20)",
                "category": "automation",
                "priority": "medium",
                "icon": "mdi:lightning-bolt-circle",
                "description": (
                    f"Automation coverage is at {bd.get('automation', 0)}/20. {auto_desc} "
                    "Reaching 20/20 transforms manual switch presses into autonomous background routines."
                ),
                "action_type": "chat_prompt",
                "action_payload": {"prompt": "Create essential smart home automations for my lighting and climate"},
            })

        # Security Maturity (< 20)
        if bd.get("security", 20) < 20 and not any(
            s.get("category") == "security" for s in suggestions
        ):
            sec_desc = (
                " ".join(mat_gaps.get("security", []))
                if mat_gaps.get("security")
                else "Configure an alarm control panel (e.g. Alarmo), smart locks, or presence tracking."
            )
            suggestions.append({
                "id": "maturity_reach_20_security",
                "title": f"Maturity Goal: Reach 20/20 Security & Presence ({bd.get('security', 0)}/20)",
                "category": "security",
                "priority": "medium",
                "icon": "mdi:shield-check",
                "description": (
                    f"Security intelligence is at {bd.get('security', 0)}/20. {sec_desc} "
                    "Reaching 20/20 ensures automated perimeter defense, night arming, and intrusion deterrence."
                ),
                "action_type": "advisor_guide",
                "action_payload": {"guide": "Install Alarmo via HACS and configure smart locks or presence sensors for whole-home security."},
            })

        # Media Maturity (< 20)
        if bd.get("media", 20) < 20 and not any(
            s.get("category") == "media" for s in suggestions
        ):
            media_desc = (
                " ".join(mat_gaps.get("media", []))
                if mat_gaps.get("media")
                else "Deploy whole-home audio grouping or pair Music Assistant with your media players."
            )
            suggestions.append({
                "id": "maturity_reach_20_media",
                "title": f"Maturity Goal: Reach 20/20 Media Harmony ({bd.get('media', 0)}/20)",
                "category": "media",
                "priority": "medium",
                "icon": "mdi:speaker-multiple",
                "description": (
                    f"Media architecture is at {bd.get('media', 0)}/20. {media_desc} "
                    "Reaching 20/20 unlocks cross-room follow-me audio, synchronized party mode, and voice announcements."
                ),
                "action_type": "advisor_guide",
                "action_payload": {"guide": "Configure media players or Music Assistant in your main rooms for coordinated multi-room audio."},
            })

        # Sort suggestions by priority: Critical -> High -> Medium -> Low
        priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        suggestions.sort(
            key=lambda s: priority_rank.get(str(s.get("priority", "medium")).lower(), 2)
        )

        self._suggestions_by_id = {s["id"]: s for s in suggestions if s.get("id")}
        return suggestions

    async def async_mine_historical_habits(self, days: int = 7) -> list[dict[str, Any]]:
        """Asynchronously mine Home Assistant SQLite recorder trends for habit routine patterns."""
        if getattr(self, "habit_manager", None):
            return await self.habit_manager.async_mine_habits(days=days, min_occurrences=2)
        return []
