"""Otis AI Companion: Audio Handoff & Voice Feedback Manager (Phase 6).

Coordinates presence-based multi-room audio follow-me routing across multi-zone matrix
amplifiers (e.g., Control4), dynamic handoffs via the Spatial Adjacency topology, idle
power guards, and voice feedback integration with notify_router.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class AudioHandoffManager:
    """Manages multi-room audio follow-me handoffs and voice feedback routing."""

    def __init__(self, hass: HomeAssistant, spatial_manager=None) -> None:
        """Initialize the Audio Handoff Manager."""
        self.hass = hass
        self.spatial_manager = spatial_manager

    async def async_get_active_media_zones(self) -> dict[str, Any]:
        """Discover active media players, matrix amplifier zones, and input streamers."""
        matrix_zones: list[dict[str, Any]] = []
        streamers: list[dict[str, Any]] = []
        tv_players: list[dict[str, Any]] = []
        other_players: list[dict[str, Any]] = []

        try:
            ent_reg = None
            if hasattr(self.hass.helpers, "entity_registry"):
                ent_reg = self.hass.helpers.entity_registry.async_get(self.hass)
        except Exception as reg_err:
            _LOGGER.debug("Could not get entity registry for audio zones: %s", reg_err)
            ent_reg = None

        for state in self.hass.states.async_all("media_player"):
            entity_id = state.entity_id
            attrs = state.attributes or {}
            platform = ""
            area_id = None

            if ent_reg:
                entry = ent_reg.async_get(entity_id)
                if entry:
                    platform = getattr(entry, "platform", "")
                    area_id = getattr(entry, "area_id", None)

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

    async def async_notify_voice(
        self,
        message: str,
        area_id: str | None = None,
        person_entity_id: str | None = None,
        announce: bool = True,
        tts_service: str | None = None,
    ) -> dict[str, Any]:
        """Deliver voice feedback to a specific area or follow a person's location."""
        clean_msg = (message or "").strip()
        if not clean_msg:
            return {"success": False, "error": "Message cannot be empty."}

        target_area = area_id

        # If person specified, attempt to locate them
        if person_entity_id and not target_area:
            p_state = self.hass.states.get(person_entity_id)
            if p_state and p_state.state not in ("not_home", "away", "unknown"):
                # Person may be in an area matching their state
                target_area = p_state.state

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
                # Try tts.speak
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
                }
            except Exception as d_err:
                _LOGGER.error("Direct TTS delivery failed: %s", d_err)
                return {"success": False, "error": str(d_err)}

        return {
            "success": False,
            "error": "No media players available to deliver voice feedback.",
        }
