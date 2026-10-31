"""Otis AI Companion: Audio Handoff & Voice Feedback Manager (Phase 6 & Roadmap Item 9).

Coordinates presence-based multi-room audio follow-me routing across multi-zone matrix
amplifiers (e.g., Control4), dynamic handoffs via the Spatial Adjacency topology, idle
power guards, spatial audio ducking, whisper/quiet voice mode, and Assist pipeline integration.
"""

from __future__ import annotations

import asyncio
from datetime import time as datetime_time
import logging
from typing import Any
import uuid

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class AudioHandoffManager:
    """Manages multi-room audio follow-me handoffs, spatial ducking, and voice feedback routing."""

    def __init__(self, hass: HomeAssistant, spatial_manager=None, rules_manager=None) -> None:
        """Initialize the Audio Handoff Manager."""
        self.hass = hass
        self.spatial_manager = spatial_manager
        self.rules_manager = rules_manager
        self._ducked_sessions: dict[str, dict[str, Any]] = {}

    def set_rules_manager(self, rules_manager: Any) -> None:
        """Set the user behavioral rules manager."""
        self.rules_manager = rules_manager

    def is_quiet_hours_active(self) -> tuple[bool, int, str]:
        """Check if quiet hours are currently active based on BehavioralRulesManager."""
        if not self.rules_manager:
            return (False, 100, "")

        try:
            rules = self.rules_manager.get_rules()
            if not rules.get("quiet_hours_enabled", True):
                return (False, 100, "")

            q_start = rules.get("quiet_hours_start", "22:00")
            q_end = rules.get("quiet_hours_end", "07:00")
            q_vol = int(rules.get("quiet_hours_volume", 25))
            pref_speaker = str(rules.get("preferred_speaker", "")).strip()

            start_parts = [int(p) for p in q_start.split(":")]
            end_parts = [int(p) for p in q_end.split(":")]
            start_time = datetime_time(start_parts[0], start_parts[1])
            end_time = datetime_time(end_parts[0], end_parts[1])

            now = None
            try:
                from homeassistant.util import dt as dt_util

                dt_now = dt_util.now()
                if hasattr(dt_now, "time") and "mock" not in str(type(dt_now)).lower():
                    t_val = dt_now.time()
                    if isinstance(t_val, datetime_time):
                        now = t_val
            except Exception:
                now = None

            if now is None or not isinstance(now, datetime_time):
                from datetime import datetime

                now = datetime.now().time()

            if start_time <= end_time:
                is_active = start_time <= now < end_time
            else:  # Overnight interval (e.g. 22:00 -> 07:00)
                is_active = now >= start_time or now < end_time

            return (is_active, q_vol, pref_speaker)
        except Exception as q_err:
            _LOGGER.debug("Could not evaluate quiet hours: %s", q_err)
            return (False, 100, "")

    async def async_get_active_media_zones(self) -> dict[str, Any]:
        """Discover active media players, matrix amplifier zones, and input streamers."""
        matrix_zones: list[dict[str, Any]] = []
        streamers: list[dict[str, Any]] = []
        tv_players: list[dict[str, Any]] = []
        other_players: list[dict[str, Any]] = []

        try:
            from homeassistant.helpers import entity_registry as er

            ent_reg = er.async_get(self.hass)
        except Exception as reg_err:
            _LOGGER.debug("Could not get entity registry for audio zones: %s", reg_err)
            ent_reg = None

        for state in self.hass.states.async_all("media_player"):
            entity_id = state.entity_id
            attrs = state.attributes or {}
            platform = ""
            area_id = attrs.get("area_id")

            if ent_reg:
                entry = ent_reg.async_get(entity_id)
                if entry:
                    platform_val = getattr(entry, "platform", "")
                    if isinstance(platform_val, str):
                        platform = platform_val
                    entry_area = getattr(entry, "area_id", None)
                    if isinstance(entry_area, str) and entry_area:
                        area_id = entry_area

            entry_info = {
                "entity_id": entity_id,
                "name": attrs.get("friendly_name", entity_id),
                "state": state.state,
                "area_id": area_id,
                "source": attrs.get("source"),
                "source_list": attrs.get("source_list", []),
                "volume_level": attrs.get("volume_level"),
                "is_volume_muted": attrs.get("is_volume_muted", False),
                "platform": platform,
            }

            # Classify zone
            if "matrix_amp" in entity_id or platform == "control4_mediaplayer":
                matrix_zones.append(entry_info)
            elif "bridge" in entity_id or "streamer" in entity_id or platform in ("alexa_media", "music_assistant", "mass"):
                streamers.append(entry_info)
            elif any(k in entity_id for k in ("tv", "bravia", "shield", "theater_yamaha", "googletv")):
                tv_players.append(entry_info)
            else:
                other_players.append(entry_info)

        return {
            "matrix_zones": matrix_zones,
            "input_streamers": streamers,
            "tv_cinema_players": tv_players,
            "other_players": other_players,
            "has_matrix_amp": len(matrix_zones) > 0,
        }

    async def async_audio_handoff(
        self,
        source_area: str,
        target_area: str,
        mode: str = "handoff",
        player_entity_id: str | None = None,
        idle_power_guard: bool = True,
    ) -> dict[str, Any]:
        """Transfer or follow audio from a source room to a target room.

        Modes:
        - 'handoff': Route audio to target room, and gracefully power off source room zone.
        - 'follow' / 'mirror': Route audio to target room while keeping source room active (multi-room party/flow).
        """
        source_area_clean = str(source_area or "").strip().lower().replace(" ", "_").replace("-", "_")
        target_area_clean = str(target_area or "").strip().lower().replace(" ", "_").replace("-", "_")

        if not source_area_clean or not target_area_clean:
            return {
                "success": False,
                "error": "Both 'source_area' and 'target_area' must be specified for audio handoff.",
            }

        _LOGGER.info(
            "Otis Audio Handoff requested: %s -> %s (mode=%s, guard=%s)",
            source_area_clean,
            target_area_clean,
            mode,
            idle_power_guard,
        )

        # 1. Spatial adjacency check
        is_adjacent = False
        spatial_path: list[str] = []
        if self.spatial_manager:
            try:
                graph = await self.spatial_manager.async_get_graph()
                adj_map = graph.get("named_adjacencies", {})
                source_nbrs = adj_map.get(source_area_clean, [])
                if target_area_clean in source_nbrs or any(target_area_clean in str(n).lower() for n in source_nbrs):
                    is_adjacent = True
                    spatial_path = [source_area_clean, target_area_clean]
                else:
                    spatial_path = [source_area_clean, target_area_clean]
            except Exception as s_err:
                _LOGGER.debug("Spatial adjacency check error: %s", s_err)

        # 2. Discover media players in source and target areas
        zones_data = await self.async_get_active_media_zones()
        all_zones = zones_data["matrix_zones"] + zones_data["other_players"] + zones_data["tv_cinema_players"]

        def area_matches(zone: dict[str, Any], target_a: str) -> bool:
            za = str(zone.get("area_id") or "").lower()
            ze = str(zone.get("entity_id") or "").lower()
            zn = str(zone.get("name") or "").lower()
            return (
                za == target_a
                or target_a in ze
                or target_a.replace("_", "") in ze.replace("_", "")
                or target_a in zn
            )

        # Locate source player
        source_player: dict[str, Any] | None = None
        if player_entity_id:
            for z in all_zones:
                if z["entity_id"] == player_entity_id:
                    source_player = z
                    break

        if not source_player:
            # Find active/playing zone in source_area
            source_candidates = [z for z in all_zones if area_matches(z, source_area_clean)]
            playing_candidates = [z for z in source_candidates if z["state"] in ("playing", "on")]
            source_player = playing_candidates[0] if playing_candidates else (source_candidates[0] if source_candidates else None)

        if not source_player:
            return {
                "success": False,
                "error": f"No active media player or matrix zone found in source area '{source_area}'.",
                "source_area": source_area,
                "target_area": target_area,
            }

        # Locate target player
        target_candidates = [z for z in all_zones if area_matches(z, target_area_clean)]
        if not target_candidates:
            return {
                "success": False,
                "error": f"No media player or matrix amplifier zone found in target area '{target_area}'.",
                "source_area": source_area,
                "target_area": target_area,
            }

        # Prefer matrix amplifier zone if source is matrix zone, else first candidate
        is_matrix_source = "matrix_amp" in source_player["entity_id"] or source_player.get("platform") == "control4_mediaplayer"
        target_player = None
        if is_matrix_source:
            matrix_targets = [z for z in target_candidates if "matrix_amp" in z["entity_id"] or z.get("platform") == "control4_mediaplayer"]
            target_player = matrix_targets[0] if matrix_targets else target_candidates[0]
        else:
            target_player = target_candidates[0]

        # 3. Perform routing actions
        current_source = source_player.get("source")
        current_volume = source_player.get("volume_level") or 0.25
        target_entity = target_player["entity_id"]
        source_entity = source_player["entity_id"]

        actions_taken: list[str] = []

        try:
            # Turn on target zone
            await self.hass.services.async_call(
                "media_player",
                "turn_on",
                {"entity_id": target_entity},
                blocking=True,
            )
            actions_taken.append(f"Turned on {target_entity}")

            # Select matching source if supported
            if current_source:
                await self.hass.services.async_call(
                    "media_player",
                    "select_source",
                    {"entity_id": target_entity, "source": current_source},
                    blocking=True,
                )
                actions_taken.append(f"Selected source '{current_source}' on {target_entity}")

            # Match volume level
            await self.hass.services.async_call(
                "media_player",
                "volume_set",
                {"entity_id": target_entity, "volume_level": current_volume},
                blocking=True,
            )
            actions_taken.append(f"Set volume to {int(current_volume * 100)}% on {target_entity}")

            # If media_router script exists in HA, notify it of room sync
            if self.hass.services.has_service("script", "media_router"):
                try:
                    await self.hass.services.async_call(
                        "script",
                        "media_router",
                        {
                            "action": "route_play",
                            "room": target_area_clean,
                            "source": current_source or "default",
                            "desired_source": current_source,
                            "profile": "zone_source",
                        },
                        blocking=False,
                    )
                    actions_taken.append("Synchronized with script.media_router")
                except Exception as mr_err:
                    _LOGGER.debug("Could not dispatch script.media_router: %s", mr_err)

            # 4. Handle mode
            if mode == "handoff":
                # Power off the departed room
                await self.hass.services.async_call(
                    "media_player",
                    "turn_off",
                    {"entity_id": source_entity},
                    blocking=True,
                )
                actions_taken.append(f"Powered off departed zone {source_entity}")

            # 5. Idle power guard
            if idle_power_guard:
                await self.async_release_idle_sources()

            return {
                "success": True,
                "source_area": source_area,
                "target_area": target_area,
                "source_player": source_entity,
                "target_player": target_entity,
                "source_streamer": current_source,
                "volume_level": current_volume,
                "mode": mode,
                "spatially_adjacent": is_adjacent,
                "spatial_path": spatial_path,
                "actions": actions_taken,
                "message": (
                    f"🎵 Audio successfully {'handed off' if mode == 'handoff' else 'mirrored'} "
                    f"from **{source_player['name']}** ({source_area}) to **{target_player['name']}** ({target_area}) "
                    f"via source '{current_source or 'active streamer'}'. "
                    f"{'Source room zone released.' if mode == 'handoff' else 'Both zones active in follow-me mode.'}"
                ),
            }

        except Exception as exec_err:
            _LOGGER.error("Audio handoff execution failed: %s", exec_err, exc_info=True)
            return {
                "success": False,
                "error": f"Failed during audio routing execution: {exec_err}",
                "actions_attempted": actions_taken,
            }

    async def async_release_idle_sources(self) -> dict[str, Any]:
        """Inspect matrix zones and upstream streamers; pause streamers and release powered-off zones.

        Guards against phantom power draw across multi-zone amplifiers when no speakers
        are actively outputting sound.
        """
        zones_data = await self.async_get_active_media_zones()
        matrix_zones = zones_data["matrix_zones"]
        streamers = zones_data["input_streamers"]

        # Collect active sources currently playing across matrix zones
        active_sources: set[str] = set()
        idle_zones_powered_off: list[str] = []
        streamers_paused: list[str] = []

        for z in matrix_zones:
            state = z["state"]
            source = z.get("source")
            is_muted = z.get("is_volume_muted", False)
            vol = z.get("volume_level") or 0.0

            if state in ("playing", "on") and not is_muted and vol > 0.0:
                if source:
                    active_sources.add(str(source).strip().lower())
            elif state in ("off", "idle", "paused"):
                # Zone is already inactive
                pass

        # Check input streamers: if a streamer is playing, but NO matrix zones are listening, pause it
        for st in streamers:
            st_id = st["entity_id"]
            st_name = str(st["name"]).strip().lower()
            st_state = st["state"]

            if st_state in ("playing", "on"):
                # Check if any active matrix zone is listening to this streamer
                is_listened_to = any(
                    (st_name in active_s or active_s in st_name or st_id.split(".")[-1] in active_s)
                    for active_s in active_sources
                )
                if not is_listened_to:
                    try:
                        await self.hass.services.async_call(
                            "media_player",
                            "media_pause",
                            {"entity_id": st_id},
                            blocking=True,
                        )
                        streamers_paused.append(st_id)
                        _LOGGER.info("Otis Idle Guard: Paused unmonitored upstream streamer %s", st_id)
                    except Exception as p_err:
                        _LOGGER.debug("Could not pause streamer %s: %s", st_id, p_err)

        return {
            "success": True,
            "active_sources": list(active_sources),
            "idle_zones_powered_off": idle_zones_powered_off,
            "streamers_paused": streamers_paused,
            "message": (
                f"🛡️ Idle Power Guard evaluated: {len(active_sources)} source(s) active. "
                f"Paused {len(streamers_paused)} unmonitored streamer(s)."
            ),
        }

    async def async_duck_media(
        self,
        areas: list[str] | str | None = None,
        duck_ratio: float = 0.25,
        duck_level: float = 0.15,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Temporarily attenuate (duck) or pause active media playback in targeted and adjacent rooms."""
        if isinstance(areas, str):
            areas = [areas]

        clean_areas: set[str] = set()
        if areas:
            for a in areas:
                if a:
                    c = a.strip().lower().replace(" ", "_").replace("-", "_")
                    clean_areas.add(c)

            # If spatial_manager is available, also include adjacent rooms for acoustic isolation
            if self.spatial_manager:
                try:
                    graph = await self.spatial_manager.async_get_graph()
                    adj_map = graph.get("named_adjacencies", {})
                    for a in list(clean_areas):
                        for nbr in adj_map.get(a, []):
                            clean_areas.add(str(nbr).lower())
                except Exception as s_err:
                    _LOGGER.debug("Could not expand adjacent areas for ducking: %s", s_err)

        zones_data = await self.async_get_active_media_zones()
        all_players = (
            zones_data["matrix_zones"]
            + zones_data["other_players"]
            + zones_data["tv_cinema_players"]
            + zones_data["input_streamers"]
        )

        sid = session_id or f"duck_{uuid.uuid4().hex[:8]}"
        ducked_players: list[dict[str, Any]] = []
        actions_taken: list[str] = []

        for p in all_players:
            entity_id = p["entity_id"]
            state = p.get("state")
            if state not in ("playing", "on"):
                continue

            area_id = str(p.get("area_id") or "").lower()
            name = str(p.get("name") or "").lower()

            # If clean_areas specified, check match
            if clean_areas:
                matches_area = (
                    area_id in clean_areas
                    or any(ca in entity_id.lower() or ca in name for ca in clean_areas)
                )
                if not matches_area:
                    continue

            # Capture prior state
            current_vol = p.get("volume_level")
            is_volume_supported = current_vol is not None

            player_record = {
                "entity_id": entity_id,
                "prev_state": state,
                "prev_volume": current_vol,
                "duck_type": "volume" if is_volume_supported else "pause",
            }

            if is_volume_supported:
                target_vol = max(0.05, min(duck_level, float(current_vol) * duck_ratio))
                player_record["ducked_volume"] = target_vol
                try:
                    await self.hass.services.async_call(
                        "media_player",
                        "volume_set",
                        {"entity_id": entity_id, "volume_level": target_vol},
                        blocking=True,
                    )
                    actions_taken.append(f"Ducked {entity_id} volume {int(float(current_vol) * 100)}% -> {int(target_vol * 100)}%")
                except Exception as v_err:
                    _LOGGER.debug("Could not duck volume for %s: %s", entity_id, v_err)
            else:
                try:
                    await self.hass.services.async_call(
                        "media_player",
                        "media_pause",
                        {"entity_id": entity_id},
                        blocking=True,
                    )
                    actions_taken.append(f"Paused playback on {entity_id}")
                except Exception as p_err:
                    _LOGGER.debug("Could not pause %s for ducking: %s", entity_id, p_err)

            ducked_players.append(player_record)

        self._ducked_sessions[sid] = {
            "session_id": sid,
            "areas": list(clean_areas),
            "players": ducked_players,
        }

        return {
            "success": True,
            "session_id": sid,
            "ducked_count": len(ducked_players),
            "ducked_players": ducked_players,
            "actions": actions_taken,
            "message": f"Ducked {len(ducked_players)} active media player(s) for voice clarity.",
        }

    async def async_unduck_media(self, session_id: str | None = None) -> dict[str, Any]:
        """Restore ducked or paused media players back to their original volumes."""
        target_sessions: list[dict[str, Any]] = []

        if session_id and session_id != "all":
            sess = self._ducked_sessions.pop(session_id, None)
            if sess:
                target_sessions.append(sess)
        else:
            target_sessions = list(self._ducked_sessions.values())
            self._ducked_sessions.clear()

        restored_players: list[str] = []
        actions_taken: list[str] = []

        for sess in target_sessions:
            for p in sess.get("players", []):
                entity_id = p["entity_id"]
                prev_vol = p.get("prev_volume")
                duck_type = p.get("duck_type")
                prev_state = p.get("prev_state")

                try:
                    if duck_type == "volume" and prev_vol is not None:
                        await self.hass.services.async_call(
                            "media_player",
                            "volume_set",
                            {"entity_id": entity_id, "volume_level": float(prev_vol)},
                            blocking=True,
                        )
                        actions_taken.append(f"Restored {entity_id} volume to {int(float(prev_vol) * 100)}%")
                        restored_players.append(entity_id)
                    elif duck_type == "pause" and prev_state == "playing":
                        await self.hass.services.async_call(
                            "media_player",
                            "media_play",
                            {"entity_id": entity_id},
                            blocking=True,
                        )
                        actions_taken.append(f"Resumed playback on {entity_id}")
                        restored_players.append(entity_id)
                except Exception as r_err:
                    _LOGGER.debug("Could not restore media player %s: %s", entity_id, r_err)

        return {
            "success": True,
            "restored_count": len(restored_players),
            "restored_players": restored_players,
            "actions": actions_taken,
            "message": f"Restored {len(restored_players)} media player(s) to original volume/playback state.",
        }

    async def async_get_assist_pipeline_status(self) -> dict[str, Any]:
        """Inspect Home Assistant's assist pipeline registry, wake-word engines, and satellite states."""
        pipelines_list: list[dict[str, Any]] = []
        preferred_id = None

        # 1. Try homeassistant.components.assist_pipeline
        try:
            from homeassistant.components import assist_pipeline

            pipelines = assist_pipeline.async_get_pipelines(self.hass)
            store = getattr(self.hass.data.get("assist_pipeline"), "pipeline_store", None)
            if store and hasattr(store, "async_get_preferred_item"):
                preferred_id = store.async_get_preferred_item()

            for p in (pipelines or []):
                p_id = getattr(p, "id", "")
                pipelines_list.append({
                    "id": p_id,
                    "name": getattr(p, "name", "Assist Pipeline"),
                    "is_preferred": (p_id == preferred_id),
                    "conversation_engine": getattr(p, "conversation_engine", None),
                    "stt_engine": getattr(p, "stt_engine", None),
                    "tts_engine": getattr(p, "tts_engine", None),
                    "wake_word_entity": getattr(p, "wake_word_entity", None),
                    "wake_word_id": getattr(p, "wake_word_id", None),
                    "prefer_local_intents": getattr(p, "prefer_local_intents", False),
                })
        except Exception as ap_err:
            _LOGGER.debug("Could not inspect assist_pipeline components directly: %s", ap_err)

        # Fallback to storage load if empty
        if not pipelines_list:
            try:
                from homeassistant.helpers.storage import Store

                ap_store = Store(self.hass, 1, "assist_pipeline.pipelines")
                data = await ap_store.async_load()
                if data and isinstance(data, dict):
                    preferred_id = data.get("preferred_item")
                    for item in data.get("items", []):
                        item_id = item.get("id")
                        pipelines_list.append({
                            "id": item_id,
                            "name": item.get("name", "Assist Pipeline"),
                            "is_preferred": (item_id == preferred_id),
                            "conversation_engine": item.get("conversation_engine"),
                            "stt_engine": item.get("stt_engine"),
                            "tts_engine": item.get("tts_engine"),
                            "wake_word_entity": item.get("wake_word_entity"),
                            "wake_word_id": item.get("wake_word_id"),
                            "prefer_local_intents": item.get("prefer_local_intents", False),
                        })
            except Exception as st_err:
                _LOGGER.debug("Could not inspect assist_pipeline from storage: %s", st_err)

        # 2. Discover assist satellites
        satellites: list[dict[str, Any]] = []
        try:
            for state in self.hass.states.async_all("assist_satellite"):
                satellites.append({
                    "entity_id": state.entity_id,
                    "name": state.attributes.get("friendly_name", state.entity_id),
                    "state": state.state,
                    "pipeline": state.attributes.get("active_pipeline"),
                })
        except Exception as sat_err:
            _LOGGER.debug("Error discovering assist_satellite entities: %s", sat_err)

        # 3. Discover wake-word engines
        wake_engines: list[dict[str, Any]] = []
        try:
            for state in self.hass.states.async_all("wake_word"):
                wake_engines.append({
                    "entity_id": state.entity_id,
                    "name": state.attributes.get("friendly_name", state.entity_id),
                    "state": state.state,
                })
            for s in self.hass.states.async_all():
                if any(k in s.entity_id for k in ("openwakeword", "wyoming", "porcupine", "micro_wake_word")):
                    if not any(w["entity_id"] == s.entity_id for w in wake_engines):
                        wake_engines.append({
                            "entity_id": s.entity_id,
                            "name": s.attributes.get("friendly_name", s.entity_id),
                            "state": s.state,
                        })
        except Exception as ww_err:
            _LOGGER.debug("Error discovering wake_word entities: %s", ww_err)

        is_quiet, vol_cap, pref_speaker = self.is_quiet_hours_active()

        return {
            "success": True,
            "total_pipelines": len(pipelines_list),
            "preferred_pipeline": next((p["name"] for p in pipelines_list if p.get("is_preferred")), None),
            "pipelines": pipelines_list,
            "satellites": satellites,
            "total_satellites": len(satellites),
            "wake_word_engines": wake_engines,
            "active_ducking_sessions": len(self._ducked_sessions),
            "quiet_hours_active": is_quiet,
            "quiet_hours_volume_cap": vol_cap,
            "preferred_speaker": pref_speaker,
        }

    async def async_notify_voice(
        self,
        message: str,
        area_id: str | None = None,
        person_entity_id: str | None = None,
        announce: bool = True,
        tts_service: str | None = None,
        duck_media: bool = True,
        duck_duration: float | None = None,
        whisper_mode: bool = False,
    ) -> dict[str, Any]:
        """Deliver voice feedback to a specific area or follow a person's location, with spatial audio ducking and quiet hours awareness."""
        clean_msg = (message or "").strip()
        if not clean_msg:
            return {"success": False, "error": "Message cannot be empty."}

        target_area = area_id

        # If person specified, attempt to locate them
        if person_entity_id and not target_area:
            p_state = self.hass.states.get(person_entity_id)
            if p_state and p_state.state not in ("not_home", "away", "unknown"):
                target_area = p_state.state

        # Check quiet hours & whisper mode
        is_quiet, vol_cap, pref_speaker = self.is_quiet_hours_active()
        apply_quiet = whisper_mode or is_quiet
        effective_volume = (vol_cap / 100.0) if apply_quiet else None

        if apply_quiet and not target_area and pref_speaker:
            target_area = pref_speaker

        # Perform spatial audio ducking if enabled
        duck_session_id = None
        if duck_media:
            try:
                duck_res = await self.async_duck_media(areas=[target_area] if target_area else None)
                duck_session_id = duck_res.get("session_id")
                if duck_session_id and duck_res.get("ducked_players"):
                    if duck_duration is None:
                        words = len(clean_msg.split())
                        calc_delay = max(4.0, (words * 0.45) + 1.5)
                    else:
                        calc_delay = float(duck_duration)

                    async def _delayed_unduck(sid: str, delay: float):
                        try:
                            await asyncio.sleep(delay)
                            await self.async_unduck_media(sid)
                        except Exception as ud_err:
                            _LOGGER.debug("Delayed unduck error: %s", ud_err)

                    asyncio.create_task(_delayed_unduck(duck_session_id, calc_delay))
            except Exception as duck_err:
                _LOGGER.debug("Audio ducking error prior to voice notification: %s", duck_err)

        # Check for notify_router script
        if self.hass.services.has_service("script", "notify_router"):
            try:
                payload: dict[str, Any] = {
                    "message": clean_msg,
                    "announce": announce,
                    "announce_message": clean_msg,
                }
                if target_area:
                    payload["context"] = target_area
                if apply_quiet and effective_volume is not None:
                    payload["volume"] = effective_volume
                    payload["whisper_mode"] = True

                await self.hass.services.async_call(
                    "script",
                    "notify_router",
                    payload,
                    blocking=False,
                )
                return {
                    "success": True,
                    "routed_via": "script.notify_router",
                    "target_area": target_area,
                    "message": clean_msg,
                    "whisper_mode": apply_quiet,
                    "quiet_hours_active": is_quiet,
                    "volume_cap": vol_cap if apply_quiet else None,
                    "ducked_session": duck_session_id,
                    "status": "Dispatched voice notification through central notify_router.",
                }
            except Exception as n_err:
                _LOGGER.warning("notify_router script call failed, falling back to direct TTS: %s", n_err)

        # Fallback: direct TTS to target area media player
        zones_data = await self.async_get_active_media_zones()
        all_players = zones_data["matrix_zones"] + zones_data["tv_cinema_players"] + zones_data["other_players"]
        target_player = None

        if target_area:
            t_clean = target_area.lower().replace(" ", "_")
            for p in all_players:
                pa = str(p.get("area_id") or "").lower()
                pe = str(p.get("entity_id") or "").lower()
                if pa == t_clean or t_clean in pe:
                    target_player = p["entity_id"]
                    break

        if not target_player and all_players:
            target_player = all_players[0]["entity_id"]

        if target_player:
            try:
                if apply_quiet and effective_volume is not None:
                    try:
                        await self.hass.services.async_call(
                            "media_player",
                            "volume_set",
                            {"entity_id": target_player, "volume_level": effective_volume},
                            blocking=True,
                        )
                    except Exception as vol_err:
                        _LOGGER.debug("Could not pre-set volume for quiet hours TTS: %s", vol_err)

                service_domain = "tts"
                service_name = "speak"
                tts_data: dict[str, Any] = {
                    "entity_id": target_player,
                    "message": clean_msg,
                }
                if self.hass.services.has_service("tts", "speak"):
                    await self.hass.services.async_call(service_domain, service_name, tts_data, blocking=False)
                elif self.hass.services.has_service("tts", "google_translate_say"):
                    await self.hass.services.async_call("tts", "google_translate_say", tts_data, blocking=False)
                return {
                    "success": True,
                    "routed_via": "direct_tts",
                    "target_player": target_player,
                    "target_area": target_area,
                    "message": clean_msg,
                    "whisper_mode": apply_quiet,
                    "quiet_hours_active": is_quiet,
                    "volume_cap": vol_cap if apply_quiet else None,
                    "ducked_session": duck_session_id,
                }
            except Exception as d_err:
                _LOGGER.error("Direct TTS delivery failed: %s", d_err)
                return {"success": False, "error": str(d_err)}

        return {
            "success": False,
            "error": "No media players available to deliver voice feedback.",
        }
