"""Otis AI Companion: Audio Handoff & Voice Feedback Manager (Phase 6 & Roadmap Item 9).

Coordinates presence-based multi-room audio follow-me routing across multi-zone matrix
amplifiers (e.g., Control4), dynamic handoffs via the Spatial Adjacency topology, idle
power guards, spatial audio ducking, whisper/quiet voice mode, and Assist pipeline integration.
"""

from __future__ import annotations

import asyncio
from datetime import time as datetime_time
import logging
import time
from typing import Any
import uuid

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    ATTR_AUDIO_FOLLOW_ACTIVE,
    ATTR_AUDIO_FOLLOW_PLAYER,
    ATTR_AUDIO_FOLLOW_SOURCE,
    ATTR_AUDIO_FOLLOW_STATUS,
    ATTR_AUDIO_FOLLOW_TARGET,
    DEFAULT_AUDIO_MIGRATION_CONFIDENCE,
    is_otis_entity_id,
    resolve_otis_entity_id,
)
from .matrix_presets import is_matrix_entity, is_tv_cinema_player

_LOGGER = logging.getLogger(__name__)


def normalize_area_slug(area_name: str | None) -> str:
    """Normalize area name to lower snake_case."""
    return str(area_name or "").strip().lower().replace(" ", "_").replace("-", "_")


def zone_matches_area(zone: dict[str, Any], area_name: str) -> bool:
    """Check if a media zone matches a given area name dynamically."""
    norm_area = normalize_area_slug(area_name)
    if not norm_area:
        return False

    za = normalize_area_slug(zone.get("area_id"))
    ze = str(zone.get("entity_id") or "").lower()
    zn = str(zone.get("name") or "").lower()
    t_compressed = norm_area.replace("_", "")

    return (
        za == norm_area
        or norm_area in ze
        or t_compressed in ze.replace("_", "")
        or norm_area in zn
        or norm_area in zn.replace(" ", "_")
        or t_compressed in zn.replace(" ", "")
    )


def filter_zones_by_area(zones: list[dict[str, Any]], area_name: str) -> list[dict[str, Any]]:
    """Filter list of zones to those matching the specified area name."""
    norm_area = normalize_area_slug(area_name)
    if not norm_area:
        return []
    return [z for z in zones if zone_matches_area(z, norm_area)]


def _is_tv_display_player(z: dict[str, Any]) -> bool:
    """Return True if a zone dict represents a TV/streaming display rather than an audio zone/AVR."""
    eid = str(z.get("entity_id") or "").lower()
    platform = str(z.get("platform") or "").lower()
    d_class = str(z.get("device_class") or "").lower()
    if is_matrix_entity(eid, platform) or "receiver" in eid or "avr" in eid:
        return False
    if d_class == "tv" or platform in ("androidtv_remote", "apple_tv", "roku", "webostv", "samsungtv", "braviatv", "lg_netcast", "firetv"):
        return True
    return any(k in eid for k in ("_tv", "android_tv", "shield_tv", "shield_android_tv", "apple_tv", "roku", "fire_tv", "chromecast_tv"))


class AudioHandoffManager:
    """Manages multi-room audio follow-me handoffs, spatial ducking, and voice feedback routing."""

    def __init__(self, hass: HomeAssistant, spatial_manager=None, rules_manager=None) -> None:
        """Initialize the Audio Handoff Manager."""
        self.hass = hass
        self.spatial_manager = spatial_manager
        self.rules_manager = rules_manager
        self._ducked_sessions: dict[str, dict[str, Any]] = {}
        self._active_audio_migration: dict[str, Any] | None = None
        self._media_sessions: dict[str, dict[str, Any]] = {}
        self._migration_unsub: Any = None
        self._fav_store = Store(hass, 1, "otis_ai_media_favorites")
        self._favorites_data: dict[str, Any] = {
            "users": {},
            "shared_favorites": [],
        }
        self._fav_loaded: bool = False

    def set_rules_manager(self, rules_manager: Any) -> None:
        """Set the user behavioral rules manager."""
        self.rules_manager = rules_manager

    async def async_load_favorites(self) -> dict[str, Any]:
        """Load per-user and shared media favorites from .storage/otis_ai_media_favorites."""
        if self._fav_loaded:
            return self._favorites_data
        try:
            stored = await self._fav_store.async_load()
            if isinstance(stored, dict):
                self._favorites_data = {
                    "users": dict(stored.get("users") or {}),
                    "shared_favorites": list(stored.get("shared_favorites") or []),
                }
        except Exception as err:
            _LOGGER.debug("Could not load media favorites store: %s", err)
        finally:
            self._fav_loaded = True
        return self._favorites_data

    async def async_save_favorites(self) -> None:
        """Persist media favorites to .storage/otis_ai_media_favorites."""
        try:
            await self._fav_store.async_save(self._favorites_data)
        except Exception as err:
            _LOGGER.debug("Could not save media favorites store: %s", err)

    def get_input_mappings(self) -> dict[str, str]:
        """Return configured or auto-inferred input-to-player mappings."""
        configured: dict[str, str] = {}
        if self.rules_manager:
            rules = self.rules_manager.get_rules()
            raw_map = rules.get("media_input_mappings")
            if isinstance(raw_map, dict):
                configured = {
                    str(k).strip(): str(v).strip()
                    for k, v in raw_map.items()
                    if str(k).strip() and str(v).strip()
                }
        return configured

    def resolve_effective_input_mappings(
        self,
        shared_sources: list[str] | None = None,
        streamers: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        """Return input-to-player mappings combining explicit user mappings with smart auto-discovery."""
        mappings = dict(self.get_input_mappings())
        if not shared_sources and hasattr(self.hass, "states"):
            discovered_sources: list[str] = []
            for st in self.hass.states.async_all("media_player"):
                s_list = (st.attributes or {}).get("source_list") or []
                for s in s_list:
                    if s and s not in discovered_sources:
                        discovered_sources.append(str(s))
            shared_sources = discovered_sources
        if not shared_sources:
            return mappings

        avail_streamers = streamers or []
        if not avail_streamers and hasattr(self.hass, "states"):
            for st in self.hass.states.async_all("media_player"):
                eid = st.entity_id
                attrs = st.attributes or {}
                avail_streamers.append({
                    "entity_id": eid,
                    "name": attrs.get("friendly_name", eid),
                })

        for src in shared_sources:
            src_clean = str(src).strip()
            if not src_clean or src_clean in mappings:
                continue
            src_low = src_clean.lower()
            src_slug = src_low.replace(" ", "_")

            # Auto-match known streamer entities by exact slug or friendly name match
            for st in avail_streamers:
                eid = str(st.get("entity_id") or "")
                obj_id = eid.split(".", 1)[-1].lower()
                st_name = str(st.get("name") or "").strip().lower()
                if obj_id == src_slug or st_name == src_low:
                    mappings[src_clean] = eid
                    break
            else:
                # Secondary heuristic: e.g. "Server" -> music_assistant / vlc_telnet_2
                if src_low in ("server", "media server", "music assistant", "stream 1"):
                    for target_sub in ("vlc_telnet_2", "music_assistant", "study_group"):
                        matched_eid = next(
                            (
                                str(st.get("entity_id") or "")
                                for st in avail_streamers
                                if target_sub in str(st.get("entity_id") or "").lower()
                            ),
                            None,
                        )
                        if not matched_eid and hasattr(self.hass, "states"):
                            for h_st in self.hass.states.async_all("media_player"):
                                if target_sub in h_st.entity_id.lower():
                                    matched_eid = h_st.entity_id
                                    break
                        if matched_eid:
                            mappings[src_clean] = matched_eid
                            break
                elif src_low in ("home assistant", "tts", "announcements"):
                    for st in avail_streamers:
                        eid = str(st.get("entity_id") or "")
                        if any(k in eid.lower() for k in ("vlc", "tts", "announcement", "streamer", "speaker")):
                            mappings[src_clean] = eid
                            break

        return mappings

    async def get_media_studio_data(
        self,
        user_id: str | None = None,
        user_name: str | None = None,
    ) -> dict[str, Any]:
        """Convenience alias for async_get_user_media_studio_state."""
        return await self.async_get_user_media_studio_state(user_id=user_id, user_name=user_name)

    def get_player_service_profile(self, player_eid: str) -> dict[str, Any]:
        """Dynamically resolve the underlying platform and capabilities of a media player entity.

        Zero hard-coding: resolves platform dynamically from Home Assistant's entity registry
        and inspects registered services to determine capabilities.
        """
        if not player_eid:
            return {
                "platform": "",
                "provider": "media_player",
                "display_name": "Media Player",
                "service": "media_player.play_media",
                "supported_media_types": ["music", "custom"],
                "supports_browse": False,
                "supports_search": False,
                "supports_voice": False,
            }

        plat = ""
        try:
            from homeassistant.helpers import entity_registry as er

            ent_reg = er.async_get(self.hass)
            ent = ent_reg.async_get(player_eid)
            if ent and getattr(ent, "platform", None) and isinstance(ent.platform, str):
                plat = str(ent.platform).strip().lower()
        except Exception as ex:
            _LOGGER.debug("Could not resolve entity registry platform for %s: %s", player_eid, ex)

        # Check for Music Assistant platform or registered service
        if plat in ("music_assistant", "mass") or (
            self.hass.services.has_service("music_assistant", "play_media")
            and ("mass" in player_eid.lower() or "music_assistant" in player_eid.lower())
        ):
            return {
                "platform": plat or "music_assistant",
                "provider": "music_assistant",
                "display_name": "Music Assistant",
                "service": "music_assistant.play_media" if self.hass.services.has_service("music_assistant", "play_media") else "media_player.play_media",
                "supported_media_types": ["playlist", "radio", "artist", "album", "track", "music"],
                "supports_browse": self.hass.services.has_service("music_assistant", "get_library"),
                "supports_search": self.hass.services.has_service("music_assistant", "search"),
                "supports_voice": False,
            }

        # Check for Alexa Media Player platform
        if plat == "alexa_media" or "alexa" in player_eid.lower() or "echo" in player_eid.lower():
            return {
                "platform": plat or "alexa_media",
                "provider": "alexa_media",
                "display_name": "Alexa Media Player",
                "service": "media_player.play_media",
                "supported_media_types": ["custom", "phrase", "music"],
                "supports_browse": False,
                "supports_search": False,
                "supports_voice": True,
            }

        # Check for Plex
        if plat == "plex" or "plex" in player_eid.lower():
            return {
                "platform": plat or "plex",
                "provider": "plex",
                "display_name": "Plex Media Server",
                "service": "media_player.play_media",
                "supported_media_types": ["music", "playlist", "station", "audio"],
                "supports_browse": True,
                "supports_search": True,
                "supports_voice": False,
            }

        # Check for Jellyfin
        if plat == "jellyfin" or "jellyfin" in player_eid.lower():
            return {
                "platform": plat or "jellyfin",
                "provider": "jellyfin",
                "display_name": "Jellyfin Media",
                "service": "media_player.play_media",
                "supported_media_types": ["music", "playlist", "audio"],
                "supports_browse": True,
                "supports_search": False,
                "supports_voice": False,
            }

        # Check for VLC Telnet virtual player
        if plat == "vlc_telnet" or "vlc" in player_eid.lower():
            return {
                "platform": plat or "vlc_telnet",
                "provider": "vlc_telnet",
                "display_name": "VLC Virtual Audio",
                "service": "media_player.play_media",
                "supported_media_types": ["music", "url"],
                "supports_browse": False,
                "supports_search": False,
                "supports_voice": False,
            }

        # Check for Cast / Android TV
        if plat in ("cast", "androidtv", "androidtv_remote"):
            return {
                "platform": plat,
                "provider": plat,
                "display_name": "Google Cast / TV",
                "service": "media_player.play_media",
                "supported_media_types": ["music", "url", "channel"],
                "supports_browse": False,
                "supports_search": False,
                "supports_voice": False,
            }

        # Check for Yamaha MusicCast
        if plat in ("yamaha_musiccast", "yamaha_ynca"):
            return {
                "platform": plat,
                "provider": plat,
                "display_name": "Yamaha MusicCast",
                "service": "media_player.play_media",
                "supported_media_types": ["music", "net_radio", "url"],
                "supports_browse": False,
                "supports_search": False,
                "supports_voice": False,
            }

        # Generic / fallback
        display_name = plat.replace("_", " ").title() if plat else "Standard Media Player"
        return {
            "platform": plat or "media_player",
            "provider": plat or "media_player",
            "display_name": display_name,
            "service": "media_player.play_media",
            "supported_media_types": ["music", "custom"],
            "supports_browse": False,
            "supports_search": False,
            "supports_voice": False,
        }

    async def async_browse_player_library(
        self,
        player_entity_id: str,
        media_type: str = "playlist",
        search_query: str | None = None,
        limit: int = 40,
    ) -> dict[str, Any]:
        """Dynamically query media library items from the underlying service provider."""
        # Normalize media_type to a valid Music Assistant MediaType
        m_type_raw = str(media_type or "playlist").lower().strip()
        if m_type_raw in ("playlists", "playlist"):
            norm_type = "playlist"
        elif m_type_raw in ("radios", "radio", "station", "stations"):
            norm_type = "radio"
        elif m_type_raw in ("artists", "artist"):
            norm_type = "artist"
        elif m_type_raw in ("albums", "album"):
            norm_type = "album"
        elif m_type_raw in ("tracks", "track", "songs", "song"):
            norm_type = "track"
        else:
            norm_type = "playlist"

        has_mass_service = self.hass.services.has_service("music_assistant", "get_library")
        profile = self.get_player_service_profile(player_entity_id) if player_entity_id else {}
        provider = profile.get("provider", "")

        # Allow browsing Music Assistant if the player is backed by MASS or whenever MASS is installed in HA
        if (provider == "music_assistant" or has_mass_service) and has_mass_service:
            mass_entries = self.hass.config_entries.async_entries("music_assistant")
            if not mass_entries:
                mass_entries = self.hass.config_entries.async_entries("mass")
            entry_id = mass_entries[0].entry_id if mass_entries else None

            if entry_id:
                try:
                    service_data: dict[str, Any] = {
                        "config_entry_id": entry_id,
                        "media_type": norm_type,
                        "limit": limit,
                    }
                    if search_query:
                        service_data["search"] = search_query

                    resp = await self.hass.services.async_call(
                        "music_assistant",
                        "get_library",
                        service_data,
                        blocking=True,
                        return_response=True,
                    )
                    items = []
                    raw_items = []
                    if isinstance(resp, dict):
                        raw_items = resp.get("items") or resp.get("library") or resp.get(norm_type) or []
                        if not raw_items and "items" not in resp:
                            for val in resp.values():
                                if isinstance(val, list):
                                    raw_items = val
                                    break
                    elif isinstance(resp, list):
                        raw_items = resp

                    for item in raw_items:
                        if isinstance(item, dict):
                            name = item.get("name") or "Unknown"
                            uri = item.get("uri") or str(item.get("item_id") or name)
                            art = item.get("artist") or ""
                            if not art and isinstance(item.get("artists"), list) and item["artists"]:
                                art = item["artists"][0].get("name", "")
                            img = item.get("image")
                            if isinstance(img, dict):
                                img = img.get("path") or img.get("url")
                            items.append({
                                "id": uri,
                                "name": name,
                                "media_type": norm_type,
                                "artist": art,
                                "image": img or "",
                            })

                    return {
                        "success": True,
                        "provider": "music_assistant",
                        "player_entity_id": player_entity_id,
                        "media_type": norm_type,
                        "items": items,
                    }
                except Exception as err:
                    _LOGGER.warning("Failed to browse Music Assistant library: %s", err)
                    return {
                        "success": False,
                        "error": str(err),
                        "provider": "music_assistant",
                        "items": [],
                    }

        return {
            "success": False,
            "error": f"Library browsing is not supported by provider '{provider}' for player '{player_entity_id}'",
            "items": [],
        }

    async def async_get_user_media_studio_state(
        self,
        user_id: str | None = None,
        user_name: str | None = None,
    ) -> dict[str, Any]:
        """Return full Media Studio state including zones, inputs, mappings, and per-user favorites."""
        await self.async_load_favorites()
        uid = str(user_id or "default").strip()
        users_dict = self._favorites_data.setdefault("users", {})
        user_prof = users_dict.get(uid) or {
            "name": user_name or "Resident",
            "default_zone": "",
            "favorites": [],
        }
        if user_name and not user_prof.get("name"):
            user_prof["name"] = user_name

        zones_data = await self.async_get_active_media_zones()
        raw_matrix_zones = zones_data.get("matrix_zones", [])
        dedicated_matrix_zones = [
            z for z in raw_matrix_zones
            if any(
                k in z.get("entity_id", "").lower() or k in str(z.get("platform", "")).lower()
                for k in ("matrix_amp", "control4", "russound", "monoprice", "dayton", "htd", "episode", "triad", "savant")
            )
        ]
        non_dedicated_matrix = [z for z in raw_matrix_zones if z not in dedicated_matrix_zones]
        matrix_zones = dedicated_matrix_zones if dedicated_matrix_zones else raw_matrix_zones
        streamers = zones_data.get("input_streamers", [])
        tv_players = zones_data.get("tv_cinema_players", [])
        other_players = zones_data.get("other_players", [])
        if dedicated_matrix_zones and non_dedicated_matrix:
            other_players.extend(non_dedicated_matrix)

        # Gather shared_sources across matrix zones
        shared_sources: list[str] = []
        for z in matrix_zones:
            s_list = z.get("source_list") or []
            for s in s_list:
                if s and s not in shared_sources:
                    shared_sources.append(str(s))

        # Combine all candidate streaming and source players (including receiver secondary zones & bridges)
        seen_cand_eids: set[str] = set()
        all_candidate_players: list[dict[str, Any]] = []

        for p in (streamers + other_players + tv_players):
            peid = str(p.get("entity_id") or "")
            if peid and peid not in seen_cand_eids:
                seen_cand_eids.add(peid)
                all_candidate_players.append(p)

        # Ensure all media_players across Home Assistant are accessible candidates
        if hasattr(self.hass, "states"):
            for st in self.hass.states.async_all("media_player"):
                if st.entity_id not in seen_cand_eids:
                    seen_cand_eids.add(st.entity_id)
                    all_candidate_players.append({
                        "entity_id": st.entity_id,
                        "name": (st.attributes or {}).get("friendly_name", st.entity_id),
                        "platform": "",
                        "state": st.state,
                    })

        all_candidate_players.sort(key=lambda x: str(x.get("name") or x.get("entity_id", "")).lower())

        effective_mappings = self.resolve_effective_input_mappings(
            shared_sources=shared_sources,
            streamers=all_candidate_players,
        )

        # Enrich mapped player states for live Now Playing metadata & service profile
        mapped_players_state: dict[str, dict[str, Any]] = {}
        for inp_name, plr_eid in effective_mappings.items():
            st = self.hass.states.get(plr_eid) if hasattr(self.hass, "states") else None
            profile = self.get_player_service_profile(plr_eid)
            if st:
                attrs = st.attributes or {}
                mapped_players_state[inp_name] = {
                    "entity_id": plr_eid,
                    "name": attrs.get("friendly_name", plr_eid),
                    "state": st.state,
                    "media_title": attrs.get("media_title"),
                    "media_artist": attrs.get("media_artist"),
                    "media_album_name": attrs.get("media_album_name"),
                    "entity_picture": attrs.get("entity_picture"),
                    "volume_level": attrs.get("volume_level"),
                    "supported_features": attrs.get("supported_features", 0),
                    "service_profile": profile,
                }
            elif plr_eid:
                mapped_players_state[inp_name] = {
                    "entity_id": plr_eid,
                    "name": plr_eid,
                    "state": "unknown",
                    "service_profile": profile,
                }

        rules = self.rules_manager.get_rules() if self.rules_manager else {}
        default_zone = (
            user_prof.get("default_zone")
            or rules.get("media_default_zone")
            or (matrix_zones[0]["entity_id"] if matrix_zones else "")
        )
        unjoin_input = rules.get("media_unjoin_input") or "None"

        user_favs_tagged = [
            {**f, "scope": "user"} for f in (user_prof.get("favorites") or [])
        ]
        shared_favs_tagged = [
            {**f, "scope": "shared"} for f in (self._favorites_data.get("shared_favorites") or [])
        ]

        return {
            "success": True,
            "user_id": uid,
            "user_name": user_prof.get("name") or user_name or "Resident",
            "default_zone": default_zone,
            "household_default_zone": rules.get("media_default_zone") or "",
            "unjoin_input": unjoin_input,
            "zones": matrix_zones,
            "matrix_zones": matrix_zones,
            "shared_sources": shared_sources,
            "effective_mappings": effective_mappings,
            "input_mappings": effective_mappings,
            "explicit_input_mappings": self.get_input_mappings(),
            "mapped_players_state": mapped_players_state,
            "candidate_players": [
                {
                    "entity_id": p["entity_id"],
                    "name": p.get("name") or p["entity_id"],
                    "platform": self.get_player_service_profile(p["entity_id"]).get("platform", p.get("platform", "")),
                    "state": p.get("state", "unknown"),
                    "service_profile": self.get_player_service_profile(p["entity_id"]),
                }
                for p in all_candidate_players
            ],
            "tv_cinema_players": tv_players,
            "favorites": user_favs_tagged + shared_favs_tagged,
            "user_favorites": user_favs_tagged,
            "shared_favorites": shared_favs_tagged,
        }

    async def async_add_user_favorite(
        self,
        user_id: str,
        name: str,
        input_source: str = "",
        player_entity_id: str = "",
        media_content_id: str = "",
        media_content_type: str = "custom",
        zone_entity_id: str = "",
        icon: str = "mdi:music-circle",
        is_shared: bool = False,
        user_name: str | None = None,
    ) -> dict[str, Any]:
        """Add a favorite station, playlist, or track for the user (or shared household)."""
        await self.async_load_favorites()
        clean_name = str(name or "").strip()
        if not clean_name:
            return {"success": False, "error": "Favorite name is required."}

        fav_item = {
            "id": f"fav_{uuid.uuid4().hex[:8]}",
            "name": clean_name,
            "input": str(input_source or "").strip(),
            "player": str(player_entity_id or "").strip(),
            "media_content_id": str(media_content_id or clean_name).strip(),
            "media_content_type": str(media_content_type or "custom").strip(),
            "zone": str(zone_entity_id or "").strip(),
            "icon": str(icon or "mdi:music-circle").strip(),
            "created_at": int(time.time()),
        }

        if is_shared:
            shared_list = self._favorites_data.setdefault("shared_favorites", [])
            if not any(f.get("name", "").lower() == clean_name.lower() and f.get("input") == fav_item["input"] for f in shared_list):
                shared_list.append(fav_item)
        else:
            uid = str(user_id or "default").strip()
            users_dict = self._favorites_data.setdefault("users", {})
            u_prof = users_dict.setdefault(uid, {
                "name": user_name or "Resident",
                "default_zone": "",
                "favorites": [],
            })
            if user_name:
                u_prof["name"] = user_name
            u_favs = u_prof.setdefault("favorites", [])
            if not any(f.get("name", "").lower() == clean_name.lower() and f.get("input") == fav_item["input"] for f in u_favs):
                u_favs.append(fav_item)

        await self.async_save_favorites()
        return await self.async_get_user_media_studio_state(user_id=user_id, user_name=user_name)

    async def async_remove_user_favorite(
        self,
        user_id: str,
        fav_id: str,
        is_shared: bool = False,
        user_name: str | None = None,
    ) -> dict[str, Any]:
        """Delete a favorite item by ID or name."""
        await self.async_load_favorites()
        target_id = str(fav_id or "").strip()
        if not target_id:
            return {"success": False, "error": "Favorite ID is required."}

        if is_shared:
            shared_list = self._favorites_data.get("shared_favorites") or []
            self._favorites_data["shared_favorites"] = [
                f for f in shared_list
                if f.get("id") != target_id and f.get("name") != target_id
            ]
        else:
            uid = str(user_id or "default").strip()
            users_dict = self._favorites_data.get("users") or {}
            if uid in users_dict:
                u_favs = users_dict[uid].get("favorites") or []
                users_dict[uid]["favorites"] = [
                    f for f in u_favs
                    if f.get("id") != target_id and f.get("name") != target_id
                ]

        await self.async_save_favorites()
        return await self.async_get_user_media_studio_state(user_id=user_id, user_name=user_name)

    async def async_set_user_default_zone(
        self,
        user_id: str,
        zone_entity_id: str,
        user_name: str | None = None,
    ) -> dict[str, Any]:
        """Save the user's preferred default speaker zone."""
        await self.async_load_favorites()
        uid = str(user_id or "default").strip()
        users_dict = self._favorites_data.setdefault("users", {})
        u_prof = users_dict.setdefault(uid, {
            "name": user_name or "Resident",
            "default_zone": "",
            "favorites": [],
        })
        u_prof["default_zone"] = str(zone_entity_id or "").strip()
        if user_name:
            u_prof["name"] = user_name
        await self.async_save_favorites()
        return await self.async_get_user_media_studio_state(user_id=user_id, user_name=user_name)

    async def async_play_favorite(
        self,
        user_id: str,
        fav_id: str | None = None,
        favorite_data: dict[str, Any] | None = None,
        target_zone: str | None = None,
    ) -> dict[str, Any]:
        """Route a zone to the favorite's input source and start playback on the mapped streaming player."""
        await self.async_load_favorites()
        uid = str(user_id or "default").strip()
        fav = favorite_data

        if not fav and fav_id:
            u_favs = (self._favorites_data.get("users", {}).get(uid, {}).get("favorites") or [])
            shared_favs = self._favorites_data.get("shared_favorites") or []
            for candidate in u_favs + shared_favs:
                if candidate.get("id") == fav_id or candidate.get("name") == fav_id:
                    fav = candidate
                    break

        if not fav or not isinstance(fav, dict):
            return {"success": False, "error": f"Favorite '{fav_id}' not found."}

        zone_eid = str(target_zone or fav.get("zone") or "").strip()
        input_name = str(fav.get("input") or "").strip()
        mappings = self.resolve_effective_input_mappings(
            shared_sources=[input_name] if input_name else []
        )
        player_eid = str(fav.get("player") or mappings.get(input_name) or "").strip()
        media_cmd = str(fav.get("media_content_id") or fav.get("media_title") or fav.get("name") or "").strip()
        media_type = str(fav.get("media_content_type") or "custom").strip()

        actions: list[str] = []
        try:
            # 1. Turn on and route the speaker zone if specified
            if zone_eid:
                await self.hass.services.async_call(
                    "media_player",
                    "turn_on",
                    {"entity_id": zone_eid},
                    blocking=True,
                )
                actions.append(f"Turned on {zone_eid}")
                if input_name:
                    await self.hass.services.async_call(
                        "media_player",
                        "select_source",
                        {"entity_id": zone_eid, "source": input_name},
                        blocking=True,
                    )
                    actions.append(f"Routed {zone_eid} to input '{input_name}'")
                self.record_media_session_owner(player_entity_id=zone_eid, user_id=uid)

            # 2. Trigger playback on mapped streamer player
            if player_eid and media_cmd:
                self.record_media_session_owner(player_entity_id=player_eid, user_id=uid)
                profile = self.get_player_service_profile(player_eid)
                provider = profile.get("provider", "")

                # Alexa voice/custom phrase dispatch
                if provider == "alexa_media" or media_type in ("custom", "phrase"):
                    cmd_str = media_cmd if media_cmd.lower().startswith("play ") else f"play {media_cmd}"
                    await self.hass.services.async_call(
                        "media_player",
                        "play_media",
                        {
                            "entity_id": player_eid,
                            "media_content_id": cmd_str,
                            "media_content_type": "custom",
                        },
                        blocking=False,
                    )
                    actions.append(f"Dispatched '{cmd_str}' to {player_eid}")

                # Music Assistant dispatch
                elif provider == "music_assistant" and self.hass.services.has_service("music_assistant", "play_media"):
                    effective_type = media_type if media_type not in ("custom", "phrase") else "playlist"
                    await self.hass.services.async_call(
                        "music_assistant",
                        "play_media",
                        {
                            "entity_id": player_eid,
                            "media_id": media_cmd,
                            "media_type": effective_type,
                        },
                        blocking=False,
                    )
                    actions.append(f"Playing '{media_cmd}' ({effective_type}) via Music Assistant on {player_eid}")

                # Standard media player dispatch
                else:
                    await self.hass.services.async_call(
                        "media_player",
                        "play_media",
                        {
                            "entity_id": player_eid,
                            "media_content_id": media_cmd,
                            "media_content_type": media_type if media_type != "custom" else "music",
                        },
                        blocking=False,
                    )
                    actions.append(f"Playing '{media_cmd}' on {player_eid}")

            return {
                "success": True,
                "zone": zone_eid,
                "input": input_name,
                "routed_input": input_name,
                "player": player_eid,
                "favorite": fav,
                "favorite_name": fav.get("name"),
                "actions": actions,
            }
        except Exception as err:
            _LOGGER.warning("Error playing favorite '%s': %s", fav.get("name"), err)
            return {"success": False, "error": str(err), "actions": actions}

    def record_media_session_owner(
        self,
        player_entity_id: str,
        user_id: str | None = None,
        person_id: str | None = None,
        area_id: str | None = None,
    ) -> None:
        """Associate an active media player session with the Home Assistant user or person who initiated it."""
        clean_eid = str(player_entity_id).strip().lower()
        self._media_sessions[clean_eid] = {
            "player_entity_id": clean_eid,
            "user_id": user_id,
            "person_id": person_id,
            "area_id": normalize_area_slug(area_id) if area_id else None,
            "timestamp": time.time(),
        }

    def get_media_session_owner(self, player_entity_id: str) -> dict[str, Any] | None:
        """Retrieve the registered session owner of an active media player."""
        clean_eid = str(player_entity_id).strip().lower()
        return self._media_sessions.get(clean_eid)

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
            if is_matrix_entity(entity_id, platform):
                matrix_zones.append(entry_info)
            elif "bridge" in entity_id or "streamer" in entity_id or platform in ("alexa_media", "music_assistant", "mass"):
                streamers.append(entry_info)
            elif is_tv_cinema_player(entity_id, attrs):
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
        target_volume: float | None = None,
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

        # 2. Discover media players in source and target areas (exclude TVs/displays from audio handoff targets)
        zones_data = await self.async_get_active_media_zones()
        all_zones = zones_data["matrix_zones"] + zones_data["other_players"] + zones_data["tv_cinema_players"]
        audio_zones = [z for z in all_zones if not _is_tv_display_player(z)]

        # Locate source player
        source_player: dict[str, Any] | None = None
        if player_entity_id:
            for z in all_zones:
                if z["entity_id"] == player_entity_id:
                    source_player = z
                    break

        if not source_player:
            # Find active/playing zone in source_area
            source_candidates = filter_zones_by_area(audio_zones, source_area_clean)
            playing_candidates = [z for z in source_candidates if z["state"] in ("playing", "on")]
            source_player = playing_candidates[0] if playing_candidates else (source_candidates[0] if source_candidates else None)

        if not source_player:
            return {
                "success": False,
                "error": f"No active media player or matrix zone found in source area '{source_area}'.",
                "source_area": source_area,
                "target_area": target_area,
            }

        # Locate target player (audio zones only; never hand off to TVs/cinema displays)
        target_candidates = filter_zones_by_area(audio_zones, target_area_clean)
        if not target_candidates:
            return {
                "success": False,
                "error": f"No media player or matrix amplifier zone found in target area '{target_area}'.",
                "source_area": source_area,
                "target_area": target_area,
            }

        # Prefer matrix amplifier zone if source is matrix zone, else first candidate
        is_matrix_source = is_matrix_entity(source_player["entity_id"], source_player.get("platform", ""))
        target_player = None
        if is_matrix_source:
            matrix_targets = [
                z for z in target_candidates
                if is_matrix_entity(z["entity_id"], z.get("platform", ""))
            ]
            target_player = matrix_targets[0] if matrix_targets else target_candidates[0]
        else:
            target_player = target_candidates[0]

        # 3. Perform routing actions
        current_source = source_player.get("source")
        current_volume = target_volume if target_volume is not None else (source_player.get("volume_level") or 0.25)
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

    async def async_process_spatial_audio_migration(
        self,
        migration_intent: dict[str, Any] | None,
        occupied_areas: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Process spatial migration intent and route follow-me audio if media is actively playing."""
        if not migration_intent or not isinstance(migration_intent, dict):
            return None

        # Check confidence against centralized threshold
        confidence = float(migration_intent.get("confidence") or 0.0)
        if confidence < DEFAULT_AUDIO_MIGRATION_CONFIDENCE:
            _LOGGER.debug(
                "Audio migration ignored: confidence %.2f below threshold %.2f",
                confidence,
                DEFAULT_AUDIO_MIGRATION_CONFIDENCE,
            )
            return None

        source_area = normalize_area_slug(migration_intent.get("source_area"))
        target_area = normalize_area_slug(migration_intent.get("target_area"))

        if not target_area or (source_area and source_area == target_area):
            return None

        # Check behavioral rules
        if self.rules_manager:
            rules = self.rules_manager.get_rules()
            if not rules.get("audio_follow_enabled", True):
                _LOGGER.debug("Audio follow-me disabled by user behavioral rules")
                return None
            if rules.get("party_mode_enabled", False):
                _LOGGER.debug("Audio follow-me suppressed because Party Mode is enabled in user rules")
                return None

        # Check user toggle entity and Party Mode entity if present
        if hasattr(self.hass, "states") and hasattr(self.hass.states, "get"):
            follow_eid = resolve_otis_entity_id(self.hass, "switch", "audio_follow")
            for eid in (follow_eid, "switch.otis_audio_follow", "input_boolean.otis_audio_follow"):
                toggle_st = self.hass.states.get(eid)
                if toggle_st and toggle_st.state in ("off", "false", "0"):
                    _LOGGER.debug("Audio follow-me disabled by entity toggle '%s'", eid)
                    return None
            party_entities = [
                s.entity_id for s in self.hass.states.async_all()
                if "party_mode" in s.entity_id and s.state in ("on", "true", "1")
            ]
            if party_entities:
                _LOGGER.debug("Audio follow-me suppressed because Party Mode entity '%s' is active", party_entities[0])
                return None

        # If an active follow migration already routed to this target_area and arrival is confirmed, finalize it
        if (
            self._active_audio_migration
            and self._active_audio_migration.get("status") == "following"
            and normalize_area_slug(self._active_audio_migration.get("target_area")) == target_area
            and occupied_areas
            and any(target_area == normalize_area_slug(a) for a in occupied_areas)
        ):
            return await self.async_finalize_audio_handoff()

        # Discover active audio players (exclude TVs/displays from audio follow-me)
        zones_data = await self.async_get_active_media_zones()
        all_zones = [
            z for z in (zones_data["matrix_zones"] + zones_data["other_players"] + zones_data["tv_cinema_players"])
            if not _is_tv_display_player(z)
        ]

        effective_mappings = self.resolve_effective_input_mappings()

        def _is_zone_actively_playing_music(z: dict[str, Any]) -> bool:
            st = str(z.get("state") or "").lower()
            src = str(z.get("source") or "").strip()
            src_l = src.lower()
            if src_l in ("home assistant", "tts", "announcements", "none", ""):
                return st == "playing"
            if st == "playing":
                return True
            if st == "on" and src:
                mapped_eid = next(
                    (v for k, v in effective_mappings.items() if k.lower() == src_l),
                    None,
                )
                if mapped_eid and hasattr(self.hass, "states"):
                    m_st = self.hass.states.get(mapped_eid)
                    if m_st is not None:
                        return str(m_st.state).lower() == "playing"
                return True
            return False

        def _is_active_music_zone(z: dict[str, Any]) -> tuple[int, int]:
            st = str(z.get("state") or "").lower()
            src = str(z.get("source") or "").strip().lower()
            is_real_music = 1 if (src and src not in ("home assistant", "tts", "announcements", "none")) else 0
            is_playing = 1 if st == "playing" else 0
            return (is_real_music, is_playing)

        playing_sources: list[dict[str, Any]] = []
        if source_area:
            source_candidates = filter_zones_by_area(all_zones, source_area)
            playing_sources = [z for z in source_candidates if _is_zone_actively_playing_music(z)]
            playing_sources.sort(key=_is_active_music_zone, reverse=True)

        # Fallback: if source_area had no playing zone (e.g. walked through a hallway/foyer without speakers)
        # or if source_area was only on an idle TTS channel while another zone is actively streaming music
        other_active = [
            z for z in all_zones
            if _is_zone_actively_playing_music(z) and not zone_matches_area(z, target_area)
        ]
        other_active.sort(key=_is_active_music_zone, reverse=True)

        if other_active and (
            not playing_sources
            or (_is_active_music_zone(other_active[0]) > _is_active_music_zone(playing_sources[0]))
        ):
            best_z = other_active[0]
            playing_sources = [best_z]
            raw_z_area = best_z.get("area_id") or best_z.get("entity_id", "").split(".")[-1]
            for prefix in ("matrix_amp_1_", "matrix_amp_2_", "matrix_amp_", "amp_"):
                if str(raw_z_area).lower().startswith(prefix):
                    raw_z_area = str(raw_z_area)[len(prefix):]
                    break
            source_area = normalize_area_slug(raw_z_area)

        if not playing_sources:
            _LOGGER.debug("No active audio playing in source area '%s'; no audio follow required", source_area)
            return {
                "migrated": False,
                "reason": "no_active_audio",
                "source_area": source_area,
                "target_area": target_area,
            }

        source_player = playing_sources[0]

        # Check person / user attribution to ensure audio only follows the person who initiated playback
        intent_person = migration_intent.get("person_id") or migration_intent.get("user_id")
        session_info = self.get_media_session_owner(source_player["entity_id"])
        if session_info and intent_person:
            session_owner = session_info.get("person_id") or session_info.get("user_id")
            if session_owner and session_owner.lower() != intent_person.lower():
                _LOGGER.debug(
                    "Audio follow skipped: person mismatch (session owner: %s, transitioning: %s)",
                    session_owner,
                    intent_person,
                )
                return {
                    "migrated": False,
                    "reason": "user_mismatch",
                    "session_owner": session_owner,
                    "transitioning_user": intent_person,
                    "source_area": source_area,
                    "target_area": target_area,
                }

        # Target candidate
        target_candidates = filter_zones_by_area(all_zones, target_area)
        if not target_candidates:
            _LOGGER.debug("No media player available in target area '%s' for audio follow", target_area)
            return {
                "migrated": False,
                "reason": "no_target_player",
                "source_area": source_area,
                "target_area": target_area,
            }
        if any(_is_zone_actively_playing_music(z) for z in target_candidates):
            _LOGGER.debug("Target area '%s' is already actively playing media; skipping audio follow overwrite", target_area)
            return {
                "migrated": False,
                "reason": "target_already_playing",
                "source_area": source_area,
                "target_area": target_area,
            }

        # Check quiet hours & volume cap
        is_quiet, quiet_vol, _ = self.is_quiet_hours_active()
        src_vol = source_player.get("volume_level") or 0.25
        target_vol = (quiet_vol / 100.0) if is_quiet else src_vol

        # Perform follow-me routing
        handoff_res = await self.async_audio_handoff(
            source_area=source_area,
            target_area=target_area,
            mode="follow",
            player_entity_id=source_player["entity_id"],
            idle_power_guard=False,
            target_volume=target_vol,
        )

        if not handoff_res.get("success"):
            return handoff_res

        # Transfer media session owner to target player if registered
        if session_info:
            target_eid = handoff_res.get("target_player") or (target_candidates[0]["entity_id"] if target_candidates else None)
            if target_eid:
                self.record_media_session_owner(
                    player_entity_id=target_eid,
                    user_id=session_info.get("user_id"),
                    person_id=session_info.get("person_id"),
                    area_id=target_area,
                )

        self._active_audio_migration = {
            "source_area": source_area,
            "target_area": target_area,
            "source_player": source_player["entity_id"],
            "target_player": handoff_res.get("target_player"),
            "source_streamer": source_player.get("source"),
            "volume_level": target_vol,
            "quiet_hours_applied": is_quiet,
            "status": "following",
        }

        self._update_spatial_migration_sensor(status="following")
        _LOGGER.info(
            "Otis Audio Follow-Me active: %s -> %s (target=%s, vol=%.2f, quiet=%s)",
            source_area,
            target_area,
            handoff_res.get("target_player"),
            target_vol,
            is_quiet,
        )
        return {
            "success": True,
            "migrated": True,
            "source_area": source_area,
            "target_area": target_area,
            "source_player": source_player["entity_id"],
            "target_player": handoff_res.get("target_player"),
            "status": "following",
            "quiet_hours_applied": is_quiet,
        }

    async def async_finalize_audio_handoff(self) -> dict[str, Any]:
        """Finalize follow-me audio handoff once occupancy reaches target area, powering down departed zone."""
        if not self._active_audio_migration or self._active_audio_migration.get("status") != "following":
            return {"success": False, "reason": "no_active_follow"}

        source_player = self._active_audio_migration.get("source_player")
        target_player = self._active_audio_migration.get("target_player")

        try:
            if source_player:
                await self.hass.services.async_call(
                    "media_player",
                    "turn_off",
                    {"entity_id": source_player},
                    blocking=True,
                )
                _LOGGER.info("Finalized audio handoff: powered off departed source player %s", source_player)

            self._active_audio_migration["status"] = "completed"
            self._update_spatial_migration_sensor(status="completed")

            # Clean idle sources across matrix
            await self.async_release_idle_sources()

            return {
                "success": True,
                "status": "completed",
                "source_player": source_player,
                "target_player": target_player,
            }
        except Exception as fin_err:
            _LOGGER.debug("Error finalizing audio handoff: %s", fin_err)
            return {"success": False, "error": str(fin_err)}

    async def async_cancel_audio_migration(self) -> dict[str, Any]:
        """Cancel active follow-me audio migration and power off target zone if user turned back."""
        if not self._active_audio_migration:
            return {"cancelled": False, "reason": "no_active_migration"}

        target_player = self._active_audio_migration.get("target_player")
        try:
            if target_player and self._active_audio_migration.get("status") == "following":
                await self.hass.services.async_call(
                    "media_player",
                    "turn_off",
                    {"entity_id": target_player},
                    blocking=True,
                )
                _LOGGER.info("Cancelled audio migration: turned off target player %s", target_player)

            self._active_audio_migration["status"] = "cancelled"
            self._update_spatial_migration_sensor(status="cancelled")
            mig = self._active_audio_migration
            self._active_audio_migration = None
            return {"cancelled": True, "details": mig}
        except Exception as c_err:
            _LOGGER.debug("Error cancelling audio migration: %s", c_err)
            return {"cancelled": False, "error": str(c_err)}

    def _update_spatial_migration_sensor(self, status: str) -> None:
        """Update sensor.otis_spatial_migration with audio follow-me attributes."""
        if hasattr(self.hass, "states") and hasattr(self.hass.states, "get") and hasattr(self.hass.states, "async_set"):
            sensor_eid = resolve_otis_entity_id(self.hass, "sensor", "spatial_migration")
            st = self.hass.states.get(sensor_eid)
            if st:
                attrs = dict(st.attributes) if st.attributes else {}
                attrs[ATTR_AUDIO_FOLLOW_ACTIVE] = (status == "following")
                attrs[ATTR_AUDIO_FOLLOW_STATUS] = status
                if self._active_audio_migration:
                    attrs[ATTR_AUDIO_FOLLOW_SOURCE] = self._active_audio_migration.get("source_area")
                    attrs[ATTR_AUDIO_FOLLOW_TARGET] = self._active_audio_migration.get("target_area")
                    attrs[ATTR_AUDIO_FOLLOW_PLAYER] = self._active_audio_migration.get("target_player")
                try:
                    from .sensor import async_update_entity_state
                    async_update_entity_state(self.hass, sensor_eid, st.state, attrs)
                except Exception as err:
                    _LOGGER.debug("Entity state update notice: %s", err)

    def async_start_migration_listener(self) -> None:
        """Listen to state changes on sensor.otis_spatial_migration for autonomous audio migration."""
        if getattr(self, "_migration_unsub", None):
            return

        async def _on_sensor_changed(event):
            data = getattr(event, "data", {})
            if not is_otis_entity_id(data.get("entity_id"), "sensor", "spatial_migration"):
                return
            new_state = data.get("new_state")
            if not new_state:
                return
            attrs = new_state.attributes or {}
            intent_dict = {
                "intent": new_state.state,
                "target_area": attrs.get("target_area"),
                "source_area": attrs.get("source_area"),
                "confidence": attrs.get("confidence", 0.0),
                "preconditioning_state": attrs.get("preconditioning_state"),
            }
            await self.async_process_spatial_audio_migration(intent_dict)

        if hasattr(self.hass, "bus") and hasattr(self.hass.bus, "async_listen"):
            try:
                from homeassistant.const import EVENT_STATE_CHANGED
            except ImportError:
                EVENT_STATE_CHANGED = "state_changed"

            self._migration_unsub = self.hass.bus.async_listen(
                EVENT_STATE_CHANGED, _on_sensor_changed
            )

    def get_default_unjoin_input(self) -> str:
        """Return the configured default/return input when zones are unjoined or input playback stops."""
        rules = self.rules_manager.get_rules() if self.rules_manager else {}
        return str(rules.get("media_unjoin_input") or "None").strip() or "None"

    async def async_unjoin_zones(
        self,
        zone_entity_ids: list[str],
        default_input: str | None = None,
    ) -> dict[str, Any]:
        """Return one or more matrix speaker zones to the configured default/unjoin input."""
        target_input = str(default_input or self.get_default_unjoin_input()).strip() or "None"
        reverted: list[str] = []
        turned_off: list[str] = []
        errors: list[str] = []

        for zid in zone_entity_ids:
            z_eid = str(zid or "").strip()
            if not z_eid:
                continue
            st = self.hass.states.get(z_eid) if hasattr(self.hass, "states") else None
            attrs = (st.attributes or {}) if st else {}
            source_list = [str(s) for s in (attrs.get("source_list") or []) if s]
            matched_src = next(
                (s for s in source_list if s.lower() == target_input.lower()),
                None,
            )
            try:
                if matched_src is not None:
                    if target_input.lower() != "none" and st and str(st.state).lower() == "off":
                        await self.hass.services.async_call(
                            "media_player",
                            "turn_on",
                            {"entity_id": z_eid},
                            blocking=True,
                        )
                    await self.hass.services.async_call(
                        "media_player",
                        "select_source",
                        {"entity_id": z_eid, "source": matched_src},
                        blocking=True,
                    )
                    reverted.append(z_eid)
                elif target_input.lower() == "none":
                    await self.hass.services.async_call(
                        "media_player",
                        "turn_off",
                        {"entity_id": z_eid},
                        blocking=True,
                    )
                    turned_off.append(z_eid)
                else:
                    await self.hass.services.async_call(
                        "media_player",
                        "select_source",
                        {"entity_id": z_eid, "source": target_input},
                        blocking=True,
                    )
                    reverted.append(z_eid)
            except Exception as err:
                _LOGGER.debug("Failed to return zone %s to default input '%s': %s", z_eid, target_input, err)
                errors.append(f"{z_eid}: {err}")

        return {
            "success": len(errors) == 0,
            "default_input": target_input,
            "reverted": reverted,
            "turned_off": turned_off,
            "errors": errors,
        }

    async def async_apply_default_input_to_idle_zones(
        self,
        default_input: str | None = None,
    ) -> dict[str, Any]:
        """Route all non-playing matrix zones to the configured default/return input."""
        target_input = str(default_input or self.get_default_unjoin_input()).strip() or "None"
        zones_data = await self.async_get_active_media_zones()
        matrix_zones = zones_data.get("matrix_zones", [])
        effective_mappings = self.resolve_effective_input_mappings()

        # Build set of inputs whose mapped upstream player is currently playing
        playing_inputs: set[str] = set()
        if hasattr(self.hass, "states"):
            for inp_name, plr_eid in effective_mappings.items():
                if not plr_eid:
                    continue
                plr_st = self.hass.states.get(plr_eid)
                if plr_st and str(plr_st.state).lower() == "playing":
                    playing_inputs.add(str(inp_name).strip().lower())

        idle_zones: list[str] = []
        for z in matrix_zones:
            z_eid = str(z.get("entity_id") or "").strip()
            if not z_eid:
                continue
            z_state = str(z.get("state") or "").lower()
            if z_state == "unavailable":
                continue
            cur_src = str(z.get("source") or "").strip().lower()
            if z_state == "playing" or (cur_src and cur_src in playing_inputs):
                continue
            if cur_src == target_input.lower() and (target_input.lower() != "none" or z_state == "off"):
                continue
            idle_zones.append(z_eid)

        if not idle_zones:
            return {"success": True, "default_input": target_input, "reverted": [], "turned_off": [], "errors": []}
        return await self.async_unjoin_zones(idle_zones, default_input=target_input)

    def async_start_input_stop_listener(self) -> None:
        """Listen for mapped input media players stopping playback and return routed zones to default input."""
        if getattr(self, "_input_stop_unsub", None):
            return

        async def _on_input_player_changed(event):
            data = getattr(event, "data", {})
            eid = str(data.get("entity_id") or "")
            if not eid.startswith("media_player."):
                return
            old_state = data.get("old_state")
            new_state = data.get("new_state")
            if not old_state or not new_state:
                return
            if str(old_state.state).lower() != "playing":
                return
            if str(new_state.state).lower() not in ("idle", "off", "standby"):
                return

            effective_mappings = self.resolve_effective_input_mappings()
            matching_inputs = [
                inp_name
                for inp_name, plr_eid in effective_mappings.items()
                if str(plr_eid or "").strip().lower() == eid.lower()
            ]
            if not matching_inputs:
                return

            default_input = self.get_default_unjoin_input()
            matching_lower = {inp.lower() for inp in matching_inputs}
            if default_input.lower() in matching_lower:
                return

            zones_data = await self.async_get_active_media_zones()
            matrix_zones = zones_data.get("matrix_zones", [])
            zones_to_revert = [
                z["entity_id"]
                for z in matrix_zones
                if z.get("entity_id")
                and str(z.get("state") or "").lower() not in ("off", "unavailable")
                and str(z.get("source") or "").strip().lower() in matching_lower
            ]
            if not zones_to_revert:
                return

            _LOGGER.info(
                "Input player %s (%s) stopped playing; returning %d zone(s) to default input '%s'",
                eid,
                ", ".join(matching_inputs),
                len(zones_to_revert),
                default_input,
            )
            await self.async_unjoin_zones(zones_to_revert, default_input=default_input)

        if hasattr(self.hass, "bus") and hasattr(self.hass.bus, "async_listen"):
            try:
                from homeassistant.const import EVENT_STATE_CHANGED
            except ImportError:
                EVENT_STATE_CHANGED = "state_changed"

            self._input_stop_unsub = self.hass.bus.async_listen(
                EVENT_STATE_CHANGED, _on_input_player_changed
            )

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
        effective_mappings = self.resolve_effective_input_mappings()
        mapped_active_players: set[str] = {
            str(plr).strip().lower()
            for inp, plr in effective_mappings.items()
            if str(inp).strip().lower() in active_sources and plr
        }
        for st in streamers:
            st_id = st["entity_id"]
            st_name = str(st["name"]).strip().lower()
            st_state = st["state"]

            if st_state in ("playing", "on"):
                # Check if any active matrix zone is listening to this streamer
                is_listened_to = (
                    st_id.lower() in mapped_active_players
                    or any(
                        (st_name in active_s or active_s in st_name or st_id.split(".")[-1] in active_s)
                        for active_s in active_sources
                    )
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

            # If clean_areas specified, check match using shared matcher
            if clean_areas and not any(zone_matches_area(p, ca) for ca in clean_areas):
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
