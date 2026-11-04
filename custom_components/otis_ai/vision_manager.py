"""Otis AI Companion: Multi-Modal Vision & Presence Intelligence (Phase 8).

Coordinates multi-sensor room occupancy fusion (mmWave radar, PIR motion, media playback,
BLE beacon tracking) into spatial probability states, camera snapshot analysis & anomaly
detection via Gemini Vision, and proactive contextual perimeter alerts.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime
import logging
import math
import re
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er

from .const import (
    DOMAIN,
    CONF_CAMERA_STREAM_STRATEGY,
    CAMERA_STRATEGY_MANAGED_PROXY,
    CAMERA_STRATEGY_HIGH_EFFICIENCY,
    CAMERA_STRATEGY_HIGH_DEFINITION,
    DEFAULT_CAMERA_STREAM_STRATEGY,
    CAMERA_STRATEGY_ALIASES,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_ZONE_COORDINATES: dict[str, tuple[float, float]] = {
    "driveway": (120.0, 480.0),
    "front_porch": (260.0, 380.0),
    "porch": (260.0, 380.0),
    "front_door": (300.0, 340.0),
    "doorbell": (300.0, 340.0),
    "foyer": (320.0, 300.0),
    "garage": (110.0, 360.0),
    "side_yard": (140.0, 260.0),
    "side_gate": (150.0, 200.0),
    "gate": (150.0, 160.0),
    "backyard_gate": (150.0, 160.0),
    "backyard": (380.0, 120.0),
    "patio": (420.0, 200.0),
    "garden": (440.0, 140.0),
    "perimeter": (250.0, 250.0),
}

ZONE_OFFSETS: dict[str, tuple[float, float]] = {
    "approach": (-20.0, 30.0),
    "doorstep": (10.0, -10.0),
    "walkway": (0.0, 15.0),
    "gate": (-15.0, -15.0),
    "fence": (-30.0, -20.0),
    "street": (-40.0, 50.0),
    "lawn": (25.0, 20.0),
}


def get_cardinal_direction(deg: float) -> str:
    """Convert an angular heading in degrees (0-360) to a cardinal direction."""
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = int((deg + 22.5) // 45) % 8
    return directions[idx]


def get_canonical_camera_key(eid: str) -> str:
    """Extract a canonical physical camera key from an entity_id."""
    base = eid.lower().replace("camera.", "")
    for sfx in (
        "_snapshots_fluent", "_snapshots_clear", "_snapshots_sub", "_snapshots_main",
        "_snapshots", "_snapshot", "_fluent", "_clear", "_sub", "_main",
        "_balanced", "_recording", "_high", "_low", "_stream", "_live",
        "_gateway", "_proxy", "_webrtc", "_rtc", "_cam", "_camera",
        "_2", "_3", "_4",
    ):
        if base.endswith(sfx):
            base = base[:-len(sfx)]
            break
    if "doorbell" in base:
        base = "front_doorbell" if "front" in base else "doorbell"
    elif "frontdoor" in base:
        base = "front_doorbell"
    # Deduplicate duplicated prefixes like backyard_backyard -> backyard
    parts = base.split("_")
    if len(parts) == 2 and parts[0] == parts[1]:
        base = parts[0]
    return base


def stream_priority(
    eid: str,
    name: str = "",
    strategy: str = DEFAULT_CAMERA_STREAM_STRATEGY,
    platform: str | None = None,
    is_managed_proxy: bool | None = None,
) -> int:
    """Score camera stream preference generically (0 = most preferred for live UI).

    Agnostic Strategies:
    - CAMERA_STRATEGY_MANAGED_PROXY ("managed_proxy"): Prefer managed stream proxies
      (NVRs, WebRTC gateways, stream proxies) for synchronized low latency, falling
      back to high-efficiency sub-streams for unmanaged cameras.
    - CAMERA_STRATEGY_HIGH_EFFICIENCY ("high_efficiency"): Prefer lightweight sub-streams
      (sub, fluent, low, balanced, secondary) across all cameras to minimize browser lag
      and bandwidth overhead.
    - CAMERA_STRATEGY_HIGH_DEFINITION ("high_definition"): Prefer full-resolution main streams
      (main, clear, high, primary, hd) across all cameras for maximum detail.
    """
    eid_lower = eid.lower()
    name_lower = (name or "").lower()
    t = f"{eid_lower} {name_lower}"

    # Drop snapshot entities, vacuum maps, faces, and license plate crops
    if any(k in t for k in ("snapshot", "map", "recording", "face", "license_plate", "person_car")):
        return 100

    # Generic stream tier classification via standard RFC / RTSP stream terminology
    is_substream = any(k in t for k in ("sub", "fluent", "low", "balanced", "secondary", "preview", "thumb"))
    is_main_stream = any(k in t for k in ("main", "clear", "high", "primary", "hd", "full"))

    # Generic managed proxy / gateway detection
    if is_managed_proxy is None:
        plat = (platform or "").lower()
        is_managed_proxy = (
            any(k in plat for k in ("proxy", "gateway", "webrtc", "nvr", "agent"))
            or (not is_substream and not is_main_stream)
        )

    # Normalize strategy (handling legacy aliases)
    norm_strategy = CAMERA_STRATEGY_ALIASES.get(strategy, strategy)

    if norm_strategy == CAMERA_STRATEGY_MANAGED_PROXY:
        # Managed proxy live streams are top priority
        if is_managed_proxy and not is_main_stream and not is_substream:
            return 0
        if is_substream:
            return 1
        if not is_main_stream:
            return 2
        return 3

    elif norm_strategy == CAMERA_STRATEGY_HIGH_DEFINITION:
        # Main / HD streams are top priority
        if is_main_stream:
            return 0
        if not is_substream and not is_managed_proxy:
            return 1
        if is_managed_proxy:
            return 2
        return 3

    elif norm_strategy == CAMERA_STRATEGY_HIGH_EFFICIENCY:
        # High efficiency sub-stream is top priority
        if is_substream:
            return 0
        if is_managed_proxy:
            return 1
        if not is_main_stream:
            return 2
        return 3

    else:
        # Fallback to high-efficiency sub-stream priority
        if is_substream:
            return 0
        if is_managed_proxy:
            return 1
        if not is_main_stream:
            return 2
        return 3


class VisionPresenceManager:
    """Manages multi-sensor room occupancy fusion, camera vision analysis, and contextual perimeter alerts."""

    def __init__(
        self,
        hass: HomeAssistant,
        spatial_manager=None,
        energy_manager=None,
        macro_manager=None,
        audio_manager=None,
        local_llm_manager=None,
    ) -> None:
        """Initialize the Vision & Presence Manager."""
        self.hass = hass
        self.spatial_manager = spatial_manager
        self.energy_manager = energy_manager
        self.macro_manager = macro_manager
        self.audio_manager = audio_manager
        self.local_llm_manager = local_llm_manager
        self._camera_audit_history: list[dict[str, Any]] = []
        self._active_intruder_tracks: list[dict[str, Any]] = []
        self._historical_intruder_tracks: list[dict[str, Any]] = []
        self._presence_cache: dict[str, Any] = {}
        self._presence_cache_ts: float = 0.0
        self._transition_history: list[dict[str, Any]] = []
        self._active_migration: dict[str, Any] | None = None
        self._last_active_area: str | None = None
        self._last_active_area_ts: float = 0.0

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

    def _build_entity_to_area_map(self) -> dict[str, str]:
        """Build mapping of entity_id -> area_id considering both entity and device registries."""
        entity_to_area: dict[str, str] = {}
        dev_to_area: dict[str, str] = {}
        try:
            dev_reg = dr.async_get(self.hass)
            if hasattr(dev_reg, "devices"):
                raw_devs = dev_reg.devices
                dev_iter = raw_devs.values() if isinstance(raw_devs, dict) else raw_devs
                for dev in dev_iter:
                    d_id = getattr(dev, "id", None)
                    area_id = getattr(dev, "area_id", None)
                    if d_id and area_id:
                        dev_to_area[d_id] = area_id
        except Exception:
            pass

        try:
            ent_reg = er.async_get(self.hass)
            if hasattr(ent_reg, "entities"):
                for entry in ent_reg.entities.values():
                    if getattr(entry, "area_id", None):
                        entity_to_area[entry.entity_id] = entry.area_id
                    elif getattr(entry, "device_id", None) and entry.device_id in dev_to_area:
                        entity_to_area[entry.entity_id] = dev_to_area[entry.device_id]
        except Exception:
            pass

        return entity_to_area

    async def async_get_presence_states(self, use_cache: bool = False) -> dict[str, Any]:
        """Compute spatial occupancy probability states for every room using multi-sensor fusion."""
        now_ts = time.time()
        if use_cache and (now_ts - self._presence_cache_ts < 5.0) and self._presence_cache:
            return self._presence_cache

        area_reg = ar.async_get(self.hass)
        areas = list(area_reg.async_list_areas()) if hasattr(area_reg, "async_list_areas") else []
        all_states = self.hass.states.async_all() if hasattr(self.hass.states, "async_all") else []

        # Build mapping of entity_id -> area_id with device-level fallback
        entity_to_area = self._build_entity_to_area_map()

        # Also map area names to area ids for heuristic matching
        area_name_to_id: dict[str, str] = {a.name.lower(): a.id for a in areas}

        # Identify persons currently home and their area if detectable
        persons_home: list[dict[str, Any]] = []
        for s in all_states:
            if s.entity_id.startswith("person."):
                state_val = s.state.lower()
                matched_area = area_name_to_id.get(state_val) or (state_val if any(a.id == state_val for a in areas) else None)
                area_source = "state" if matched_area else None
                if not matched_area:
                    matched_area = entity_to_area.get(s.entity_id)
                    area_source = "registry" if matched_area else None
                is_home = (state_val in ("home", "on")) or (matched_area is not None and state_val not in ("not_home", "away"))
                persons_home.append({
                    "entity_id": s.entity_id,
                    "name": s.attributes.get("friendly_name", s.entity_id),
                    "is_home": is_home,
                    "state": state_val,
                    "area_id": matched_area,
                    "area_source": area_source,
                })

        room_results: dict[str, dict[str, Any]] = {}
        occupied_areas: list[str] = []
        likely_areas: list[str] = []
        vacant_areas: list[str] = []

        for area in areas:
            a_id = area.id
            a_name = area.name
            a_lower = a_name.lower()

            # Discover sensors in this area
            mmwave_entities: list[str] = []
            pir_entities: list[str] = []
            media_entities: list[str] = []
            ble_entities: list[str] = []
            light_entities: list[str] = []

            mmwave_active = False
            pir_active = False
            media_active = False
            ble_active = False
            lights_active = False
            most_recent_motion_ts: float = 0.0

            for s in all_states:
                eid = s.entity_id
                e_area = entity_to_area.get(eid)
                # Heuristic area fallback if entity_registry doesn't have area assigned
                if not e_area:
                    e_name = (s.attributes.get("friendly_name") or eid).lower()
                    if re.search(rf"\b{re.escape(a_lower)}\b", e_name) or re.search(rf"\b{re.escape(a_id)}\b", eid.lower()):
                        e_area = a_id

                if e_area != a_id:
                    continue

                d_class = str(s.attributes.get("device_class") or "").lower()
                eid_lower = eid.lower()

                # 1. mmWave Radar / Micro-movement presence
                is_mmwave = (
                    d_class in ("occupancy", "presence")
                    or any(k in eid_lower for k in ("mmwave", "radar", "ld2410", "fp1", "fp2", "screek", "presence"))
                )
                if is_mmwave and eid.startswith("binary_sensor."):
                    mmwave_entities.append(eid)
                    if s.state == "on":
                        mmwave_active = True

                # 2. PIR Motion
                is_pir = (
                    d_class == "motion"
                    or any(k in eid_lower for k in ("motion", "pir"))
                )
                if is_pir and eid.startswith("binary_sensor.") and not is_mmwave:
                    pir_entities.append(eid)
                    if s.state == "on":
                        pir_active = True
                        most_recent_motion_ts = now_ts
                    else:
                        # Check last_changed
                        last_changed = getattr(s, "last_changed", None)
                        if last_changed:
                            try:
                                if hasattr(last_changed, "timestamp"):
                                    l_ts = last_changed.timestamp()
                                else:
                                    l_ts = float(last_changed)
                                if l_ts > most_recent_motion_ts:
                                    most_recent_motion_ts = l_ts
                            except Exception:
                                pass

                # 3. Media Player Playback
                if eid.startswith("media_player."):
                    media_entities.append(eid)
                    if s.state == "playing":
                        media_active = True

                # 4. BLE Beacon / Room Tracker (Only true room-level micro-location, NOT generic zone "home")
                is_room_tracker = (
                    "espresence" in eid_lower
                    or "bermuda" in eid_lower
                    or "room_assistant" in eid_lower
                    or "find3" in eid_lower
                    or (eid.startswith("device_tracker.") and "beacon" in eid_lower)
                )
                if is_room_tracker:
                    ble_entities.append(eid)
                    st_lower = s.state.lower()
                    attr_room = str(s.attributes.get("room") or s.attributes.get("area") or "").lower()
                    if st_lower in (a_lower, a_id) or attr_room in (a_lower, a_id):
                        ble_active = True

                # 5. Lights active
                if eid.startswith("light.") and s.state == "on":
                    light_entities.append(eid)
                    lights_active = True

            # Also check if any Person entity is explicitly in this room (state matches room name, not generic "home")
            person_in_room = any(
                p["is_home"] and (
                    str(p.get("state") or "").lower() in (a_lower, a_id)
                    or (p.get("area_id") == a_id and p.get("area_source") == "state")
                )
                for p in persons_home
            )
            if person_in_room:
                ble_active = True

            # Calculate Probability Fusion
            # mmWave confidence (active detects breathing/micro-movement)
            p_mmwave = 0.92 if mmwave_active else 0.0

            # PIR motion confidence with time-decay
            if pir_active:
                p_pir = 0.75
            elif most_recent_motion_ts > 0:
                elapsed_sec = max(0.0, now_ts - most_recent_motion_ts)
                if elapsed_sec < 180:  # < 3 mins
                    p_pir = 0.45
                elif elapsed_sec < 600:  # < 10 mins
                    p_pir = 0.20
                elif elapsed_sec < 1200:  # < 20 mins
                    p_pir = 0.08
                else:
                    p_pir = 0.0
            else:
                p_pir = 0.0

            p_media = 0.45 if media_active else 0.0
            p_ble = 0.65 if ble_active else 0.0
            p_lights = 0.18 if lights_active else 0.0

            # Independent Bayesian combination: P = 1 - product(1 - p_i)
            combined_prob = 1.0 - (
                (1.0 - p_mmwave)
                * (1.0 - p_pir)
                * (1.0 - p_media)
                * (1.0 - p_ble)
                * (1.0 - p_lights)
            )
            prob_rounded = round(max(0.0, min(1.0, combined_prob)), 2)

            # Classify status
            if prob_rounded >= 0.65:
                status = "occupied"
                occupied_areas.append(a_name)
            elif prob_rounded >= 0.30:
                status = "likely_occupied"
                likely_areas.append(a_name)
            else:
                status = "vacant"
                vacant_areas.append(a_name)

            room_results[a_id] = {
                "area_id": a_id,
                "area_name": a_name,
                "probability": prob_rounded,
                "status": status,
                "confidence_percent": int(prob_rounded * 100),
                "sensors": {
                    "mmwave": {
                        "count": len(mmwave_entities),
                        "active": mmwave_active,
                        "entities": mmwave_entities,
                    },
                    "pir": {
                        "count": len(pir_entities),
                        "active": pir_active,
                        "entities": pir_entities,
                        "seconds_since_motion": int(now_ts - most_recent_motion_ts) if most_recent_motion_ts else None,
                    },
                    "media": {
                        "count": len(media_entities),
                        "playing": media_active,
                        "entities": media_entities,
                    },
                    "ble_beacon": {
                        "count": len(ble_entities),
                        "active": ble_active,
                        "entities": ble_entities,
                    },
                    "lights_on": len(light_entities),
                },
            }

        total_household_home = any(p["is_home"] for p in persons_home) if persons_home else True

        res = {
            "timestamp": datetime.now().isoformat(),
            "household_present": total_household_home,
            "total_areas": len(areas),
            "occupied_count": len(occupied_areas),
            "likely_count": len(likely_areas),
            "vacant_count": len(vacant_areas),
            "occupied_areas": occupied_areas,
            "likely_areas": likely_areas,
            "vacant_areas": vacant_areas,
            "rooms": room_results,
        }
        self._presence_cache = res
        self._presence_cache_ts = now_ts
        return res

    async def async_get_cameras(self) -> list[dict[str, Any]]:
        """Discover all security cameras and doorbells across Home Assistant with smart stream deduplication."""
        area_reg = ar.async_get(self.hass)
        areas_by_id = {a.id: a.name for a in area_reg.async_list_areas()} if hasattr(area_reg, "async_list_areas") else {}
        entity_to_area = self._build_entity_to_area_map()

        ent_reg = None
        dev_reg = None
        try:
            ent_reg = er.async_get(self.hass)
            dev_reg = dr.async_get(self.hass)
        except Exception:
            pass

        all_states = self.hass.states.async_all() if hasattr(self.hass.states, "async_all") else []
        VACUUM_MAP_KEYWORDS = ("map", "saved_map", "current_map", "cleaning_map", "vacuum", "floorplan")

        # Discover devices in vacuum domain to filter out navigation/map cameras generically
        vacuum_device_ids: set[str] = set()
        if ent_reg and hasattr(ent_reg, "entities"):
            for e_entry in ent_reg.entities.values():
                if getattr(e_entry, "domain", None) == "vacuum" and getattr(e_entry, "device_id", None):
                    vacuum_device_ids.add(e_entry.device_id)

        camera_groups: dict[str, list[tuple[Any, str, str]]] = {}

        for s in all_states:
            if not s.entity_id.startswith("camera."):
                continue

            eid = s.entity_id
            name = s.attributes.get("friendly_name") or eid
            cam_lower = (eid + " " + name).lower()

            # Skip vacuum cleaning maps and navigation map cameras generically
            if any(k in cam_lower for k in VACUUM_MAP_KEYWORDS):
                continue
            if s.attributes.get("device_class") == "map":
                continue
            if ent_reg and hasattr(ent_reg, "entities") and eid in ent_reg.entities:
                entry = ent_reg.entities[eid]
                if getattr(entry, "device_id", None) and entry.device_id in vacuum_device_ids:
                    continue

            canonical_key = get_canonical_camera_key(eid)
            camera_groups.setdefault(canonical_key, []).append((s, eid, name))

        cameras: list[dict[str, Any]] = []
        strategy = self.get_camera_stream_strategy()
        ent_platform_map: dict[str, str] = {}
        if ent_reg and hasattr(ent_reg, "entities"):
            for e_entry in ent_reg.entities.values():
                ent_platform_map[e_entry.entity_id] = getattr(e_entry, "platform", "")

        for canonical_key, stream_list in camera_groups.items():
            # Sort by stream priority according to configured strategy
            stream_list.sort(key=lambda item: stream_priority(
                item[1],
                item[2],
                strategy=strategy,
                platform=ent_platform_map.get(item[1]) or (getattr(item[0], "attributes", {}).get("platform") if hasattr(item[0], "attributes") else None),
            ))
            best_s, best_eid, best_name = stream_list[0]

            area_id = entity_to_area.get(best_eid)
            area_name = areas_by_id.get(area_id, "Unknown Area")

            # Clean name if integration provided generic stream label like "Fluent" or "Clear"
            clean_name = best_name
            if best_name.lower().strip() in (
                "fluent", "clear", "sub", "main", "snapshots fluent",
                "snapshots clear", "balanced", "snapshots sub", "snapshots main"
            ):
                device_name = None
                if ent_reg and dev_reg and hasattr(ent_reg, "entities") and best_eid in ent_reg.entities:
                    entry = ent_reg.entities[best_eid]
                    if getattr(entry, "device_id", None):
                        dev = dev_reg.async_get(entry.device_id) if hasattr(dev_reg, "async_get") else None
                        if dev:
                            device_name = dev.name_by_user or dev.name

                if device_name:
                    clean_name = device_name
                else:
                    pretty_key = canonical_key.replace("_", " ").title()
                    clean_name = pretty_key if ("camera" in pretty_key.lower() or "doorbell" in pretty_key.lower()) else f"{pretty_key} Camera"

            cam_lower = (best_eid + " " + clean_name).lower()
            is_doorbell = "doorbell" in cam_lower or "frontdoor" in cam_lower
            is_perimeter = any(k in cam_lower for k in ("front", "back", "patio", "yard", "driveway", "porch", "exterior"))
            is_interior = any(k in cam_lower for k in ("living", "kitchen", "study", "nursery", "office", "hallway", "garage", "mudroom", "foyer"))

            cameras.append({
                "entity_id": best_eid,
                "name": clean_name,
                "state": best_s.state,
                "area_id": area_id,
                "area_name": area_name,
                "is_doorbell": is_doorbell,
                "is_perimeter": is_perimeter,
                "is_interior": is_interior,
                "model": best_s.attributes.get("model_name") or best_s.attributes.get("brand"),
                "stream_source": best_s.attributes.get("frontend_stream_type"),
                "entity_picture": best_s.attributes.get("entity_picture"),
                "access_token": best_s.attributes.get("access_token"),
            })

        # Sort cameras: doorbells first, then perimeter, then interior, then alphabetically
        def _cam_sort_key(c: dict[str, Any]) -> tuple[int, str]:
            rank = 0 if c["is_doorbell"] else (1 if c["is_perimeter"] else 2)
            return (rank, c["name"].lower())

        cameras.sort(key=_cam_sort_key)
        return cameras

    async def async_analyze_camera(
        self,
        camera_entity_id: str,
        prompt: str | None = None,
        context: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Perform snapshot analysis and perimeter anomaly detection using Local LLM / Ollama with sensor telemetry fallback."""
        _LOGGER.debug("Starting camera analysis for entity: %s", camera_entity_id)
        state = self.hass.states.get(camera_entity_id) if hasattr(self.hass.states, "get") else None
        if not state:
            return {
                "success": False,
                "error": f"Camera entity '{camera_entity_id}' not found.",
                "camera": camera_entity_id,
            }

        name = state.attributes.get("friendly_name") or camera_entity_id
        cam_lower = (camera_entity_id + " " + name).lower()

        # 1. Capture snapshot image bytes via Home Assistant camera component
        image_bytes: bytes | None = None
        base64_data: str | None = None
        try:
            from homeassistant.components import camera as ha_camera
            if hasattr(ha_camera, "async_get_image"):
                img_obj = await ha_camera.async_get_image(self.hass, camera_entity_id)
                if img_obj and hasattr(img_obj, "content"):
                    image_bytes = img_obj.content
                    content_type = getattr(img_obj, "content_type", "image/jpeg")
                    base64_data = f"data:{content_type};base64,{base64.b64encode(image_bytes).decode('utf-8')}"
        except Exception as img_err:
            _LOGGER.debug("Could not capture camera snapshot image: %s", img_err)

        # 2. Derive perimeter zone from camera metadata
        perimeter_zone = "perimeter"
        for z in ("driveway", "porch", "front_door", "backyard", "side_yard", "gate", "garage", "patio", "garden"):
            if z in cam_lower:
                perimeter_zone = z
                break

        detected_objects: list[str] = []
        anomaly_detected = False
        anomaly_type: str | None = None
        severity = "normal"
        confidence = 0.50
        recommended_action: str | None = None
        llm_used = False
        llm_model: str | None = None
        safety_assessment = "Perimeter normal. No security anomalies detected."
        summary = f"Visual audit for {name}: Scene clear. Normal baseline."
        status = "normal"

        # 3. Attempt local multimodal vision analysis if LocalLLMManager is available and snapshot captured
        if image_bytes and getattr(self, "local_llm_manager", None):
            try:
                llm_res = await self.local_llm_manager.async_analyze_vision(
                    image_bytes=image_bytes,
                    prompt=prompt,
                    model=model,
                    context=context,
                )
                if llm_res.get("success"):
                    llm_used = True
                    llm_model = llm_res.get("model")
                    detected_objects = llm_res.get("detected_objects", [])
                    perimeter_zone = llm_res.get("perimeter_zone", perimeter_zone)
                    anomaly_detected = bool(llm_res.get("anomaly_detected", False))
                    anomaly_type = llm_res.get("anomaly_type")
                    severity = llm_res.get("severity", "normal")
                    confidence = float(llm_res.get("confidence", 0.85))
                    recommended_action = llm_res.get("recommended_action")
                    summary = llm_res.get("summary") or f"Visual audit for {name}: Analysis completed."
                    safety_assessment = summary
                    if anomaly_detected:
                        status = "anomaly"
                    elif severity in ("low", "medium"):
                        status = "attention_needed"
                    else:
                        status = "normal"
            except Exception as llm_err:
                _LOGGER.debug("Local LLM vision analysis failed, falling back to sensor telemetry: %s", llm_err)

        # 4. Fallback to smart vision sensors in same area or prefix if LLM not used
        if not llm_used:
            is_doorbell = "doorbell" in cam_lower
            prefix = camera_entity_id.replace("camera.", "")

            all_states = self.hass.states.async_all() if hasattr(self.hass.states, "async_all") else []
            for s in all_states:
                eid = s.entity_id.lower()
                if prefix in eid and s.state == "on":
                    if "person" in eid:
                        detected_objects.append("person")
                    elif "vehicle" in eid or "car" in eid:
                        detected_objects.append("vehicle")
                    elif "package" in eid:
                        detected_objects.append("package")
                    elif "pet" in eid or "animal" in eid:
                        detected_objects.append("animal")
                    elif "motion" in eid:
                        detected_objects.append("motion")

            detected_objects = sorted(list(set(detected_objects)))

            if "package" in detected_objects:
                status = "attention_needed"
                severity = "low"
                confidence = 0.80
                safety_assessment = "Package delivery detected on doorstep/walkway."
                summary = f"Visual audit for {name}: Package detected. Walkway unobstructed."
                recommended_action = "log_delivery"
            elif "person" in detected_objects:
                status = "attention_needed" if is_doorbell else "motion_detected"
                severity = "medium" if is_doorbell else "low"
                confidence = 0.85
                safety_assessment = "Visitor or individual detected within field of view."
                summary = f"Visual audit for {name}: Person presence detected."
            elif "vehicle" in detected_objects:
                status = "motion_detected"
                severity = "low"
                confidence = 0.85
                safety_assessment = "Vehicle detected in driveway or approach zone."
                summary = f"Visual audit for {name}: Vehicle presence detected."
            elif "motion" in detected_objects:
                status = "motion_detected"
                severity = "low"
                confidence = 0.70
                safety_assessment = "Active movement detected in monitored zone."
                summary = f"Visual audit for {name}: Movement in frame."
            else:
                summary = f"Visual audit for {name}: Scene clear. Normal baseline."

        prefix = camera_entity_id.replace("camera.", "")
        audit_entry = {
            "id": f"audit_{int(time.time())}_{prefix}",
            "timestamp": datetime.now().isoformat(),
            "camera": camera_entity_id,
            "name": name,
            "status": status,
            "summary": summary,
            "detected_objects": detected_objects,
            "perimeter_zone": perimeter_zone,
            "safety_assessment": safety_assessment,
            "anomaly_detected": anomaly_detected,
            "anomaly_type": anomaly_type,
            "severity": severity,
            "confidence": confidence,
            "recommended_action": recommended_action,
            "llm_used": llm_used,
            "llm_model": llm_model,
            "has_snapshot": image_bytes is not None,
            "snapshot_preview": base64_data[:60] + "..." if base64_data else None,
            "prompt_used": prompt or "Analyze camera frame for visitors, packages, open gates, or anomalies",
        }

        self._camera_audit_history.insert(0, audit_entry)
        if len(self._camera_audit_history) > 30:
            self._camera_audit_history.pop()

        # Multi-camera spatial triangulation and unified intruder tracking
        track = self.process_visual_detection(audit_entry)
        if track:
            audit_entry["track_id"] = track.get("track_id")
            audit_entry["threat_level"] = track.get("threat_level")
            audit_entry["predicted_next_area"] = track.get("predicted_next_area")
            audit_entry["velocity"] = track.get("velocity")

        # Update sensor.otis_perimeter_sentinel
        self._update_perimeter_sentinel_sensor(audit_entry)

        # Fire perimeter anomaly event if anomaly detected
        if (anomaly_detected or severity in ("medium", "high", "critical")) and hasattr(self.hass, "bus") and hasattr(self.hass.bus, "async_fire"):
            self.hass.bus.async_fire("otis_ai_perimeter_anomaly_detected", audit_entry)

        # Fire event on bus for real-time frontend listener
        if hasattr(self.hass, "bus") and hasattr(self.hass.bus, "async_fire"):
            self.hass.bus.async_fire("otis_ai_vision_analysis_completed", audit_entry)

        return {
            "success": True,
            "audit": audit_entry,
        }

    def _update_perimeter_sentinel_sensor(self, latest_audit: dict[str, Any]) -> None:
        """Publish or update sensor.otis_perimeter_sentinel state with security status."""
        if not hasattr(self.hass, "states") or not hasattr(self.hass.states, "async_set"):
            return

        recent_anomalies = [
            a for a in self._camera_audit_history
            if a.get("anomaly_detected") or a.get("severity") in ("medium", "high", "critical")
        ]
        has_critical = any(a.get("severity") == "critical" for a in recent_anomalies)
        has_warning = any(a.get("severity") in ("high", "medium") for a in recent_anomalies)

        if has_critical:
            state_val = "critical"
        elif has_warning:
            state_val = "warning"
        elif latest_audit.get("severity") == "low":
            state_val = "attention"
        else:
            state_val = "normal"

        attrs = {
            "friendly_name": "Otis Perimeter Sentinel",
            "icon": "mdi:shield-alert" if state_val in ("critical", "warning") else "mdi:shield-check",
            "latest_camera": latest_audit.get("camera"),
            "latest_zone": latest_audit.get("perimeter_zone"),
            "latest_severity": latest_audit.get("severity"),
            "latest_anomaly_type": latest_audit.get("anomaly_type"),
            "latest_confidence": latest_audit.get("confidence"),
            "latest_summary": latest_audit.get("summary"),
            "active_anomalies_count": len(recent_anomalies),
            "detected_objects": latest_audit.get("detected_objects", []),
            "recommended_action": latest_audit.get("recommended_action"),
            "llm_used": latest_audit.get("llm_used", False),
            "llm_model": latest_audit.get("llm_model"),
            "total_audits": len(self._camera_audit_history),
        }
        active_tracks = [t for t in self._active_intruder_tracks if t.get("status") == "active"]
        attrs["active_intruder_tracks_count"] = len(active_tracks)
        if active_tracks:
            attrs["latest_intruder_track"] = active_tracks[-1].get("track_id")
            attrs["predicted_target_zone"] = active_tracks[-1].get("predicted_next_area")
        self.hass.states.async_set("sensor.otis_perimeter_sentinel", state_val, attrs)

    async def async_audit_perimeter(self, camera_entities: list[str] | None = None) -> dict[str, Any]:
        """Audit all perimeter cameras concurrently for security anomalies."""
        if not camera_entities:
            all_cams = await self.async_get_cameras()
            perimeter_kw = ("driveway", "porch", "yard", "gate", "perimeter", "doorbell", "patio", "garage", "entrance")
            target_cams = [
                c["entity_id"] for c in all_cams
                if any(kw in (c["entity_id"] + " " + c.get("name", "") + " " + c.get("area_name", "")).lower() for kw in perimeter_kw)
            ]
            if not target_cams:
                target_cams = [c["entity_id"] for c in all_cams]
        else:
            target_cams = list(camera_entities)

        if not target_cams:
            return {
                "success": True,
                "total_cameras_scanned": 0,
                "anomalies_detected": 0,
                "anomalies": [],
                "scans": [],
            }

        tasks = [self.async_analyze_camera(eid) for eid in target_cams]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        scans: list[dict[str, Any]] = []
        anomalies: list[dict[str, Any]] = []

        for r in results:
            if isinstance(r, dict) and r.get("success"):
                audit = r.get("audit", {})
                scans.append(audit)
                if audit.get("anomaly_detected") or audit.get("severity") in ("medium", "high", "critical"):
                    anomalies.append(audit)

        return {
            "success": True,
            "total_cameras_scanned": len(target_cams),
            "anomalies_detected": len(anomalies),
            "anomalies": anomalies,
            "scans": scans,
        }

    def _resolve_camera_area(self, camera_entity_id: str) -> str:
        """Resolve the area slug for a camera entity using entity registry or entity name."""
        cam_lower = camera_entity_id.lower().replace("camera.", "")
        # 1. Check entity registry
        if hasattr(self.hass, "data") and isinstance(getattr(self.hass, "data", None), dict):
            try:
                ent_reg = er.async_get(self.hass)
                entry = ent_reg.async_get(camera_entity_id) if hasattr(ent_reg, "async_get") else None
                if not entry and hasattr(ent_reg, "entities") and isinstance(ent_reg.entities, dict):
                    entry = ent_reg.entities.get(camera_entity_id)
                if entry and hasattr(entry, "area_id") and isinstance(entry.area_id, str) and entry.area_id:
                    return entry.area_id
            except Exception:
                pass

        # 2. Check area names in DEFAULT_ZONE_COORDINATES
        for zone_name in DEFAULT_ZONE_COORDINATES:
            if zone_name in cam_lower:
                return zone_name

        return "perimeter"

    def _get_camera_area_coordinates(self, camera_entity_id: str, zone_hint: str | None = None) -> tuple[float, float]:
        """Resolve the spatial (x, y) coordinates for a camera detection."""
        cam_lower = camera_entity_id.lower()
        base_x, base_y = 250.0, 250.0

        area_id = self._resolve_camera_area(camera_entity_id)
        if area_id in DEFAULT_ZONE_COORDINATES:
            base_x, base_y = DEFAULT_ZONE_COORDINATES[area_id]
        else:
            for zone_name, coords in DEFAULT_ZONE_COORDINATES.items():
                if zone_name in cam_lower:
                    base_x, base_y = coords
                    break

        if zone_hint:
            hint_lower = zone_hint.lower()
            for hint_key, offset in ZONE_OFFSETS.items():
                if hint_key in hint_lower:
                    base_x += offset[0]
                    base_y += offset[1]
                    break

        return round(base_x, 1), round(base_y, 1)

    def process_visual_detection(self, audit_entry: dict[str, Any]) -> dict[str, Any] | None:
        """Process visual audit detection into unified intruder track history and spatial triangulation."""
        if not isinstance(audit_entry, dict):
            return None

        detected_objects = audit_entry.get("detected_objects", [])
        anomaly_detected = bool(audit_entry.get("anomaly_detected", False))
        severity = str(audit_entry.get("severity", "normal")).lower()
        camera_entity_id = audit_entry.get("camera", "")
        name = audit_entry.get("name") or camera_entity_id

        # Target types of interest
        target_type = "unknown"
        if "person" in detected_objects:
            target_type = "person"
        elif "vehicle" in detected_objects:
            target_type = "vehicle"
        elif "animal" in detected_objects:
            target_type = "animal"
        elif anomaly_detected or severity in ("medium", "high", "critical"):
            target_type = "target"
        else:
            return None

        now_ts = time.time()
        now_iso = audit_entry.get("timestamp") or datetime.now().isoformat()
        current_area = self._resolve_camera_area(camera_entity_id)
        perimeter_zone = str(audit_entry.get("perimeter_zone") or "perimeter").lower()
        x, y = self._get_camera_area_coordinates(camera_entity_id, perimeter_zone)

        # 1. Clean up expired active tracks (> 180 seconds)
        still_active: list[dict[str, Any]] = []
        for trk in self._active_intruder_tracks:
            if now_ts - trk.get("last_seen_ts", 0) > 180:
                trk["status"] = "departed"
            else:
                still_active.append(trk)
        self._active_intruder_tracks = still_active

        # 2. Match with existing active track
        matched_track: dict[str, Any] | None = None
        min_dist = float("inf")

        for trk in self._active_intruder_tracks:
            trk_type = trk.get("target_type")
            if trk_type != target_type and trk_type != "target" and target_type != "target":
                continue

            last_area = trk.get("current_area", "")
            last_wp = trk["trajectory"][-1] if trk.get("trajectory") else None
            last_x = last_wp.get("x", 250.0) if last_wp else 250.0
            last_y = last_wp.get("y", 250.0) if last_wp else 250.0
            dist = math.hypot(x - last_x, y - last_y)

            # Spatial adjacency check
            is_adjacent = False
            if hasattr(self, "spatial_manager") and self.spatial_manager:
                try:
                    adj = self.spatial_manager.get_adjacent_areas(last_area)
                    is_adjacent = current_area in adj or last_area in self.spatial_manager.get_adjacent_areas(current_area)
                except Exception:
                    is_adjacent = False

            if last_area == current_area or is_adjacent or dist <= 250.0:
                if dist < min_dist:
                    min_dist = dist
                    matched_track = trk

        # 3. Update existing track or instantiate new track
        if matched_track:
            prev_wp = matched_track["trajectory"][-1]
            dx = x - prev_wp.get("x", x)
            dy = y - prev_wp.get("y", y)
            dt = max(1.0, now_ts - matched_track.get("last_seen_ts", now_ts))
            dist = math.hypot(dx, dy)
            speed = round(dist / dt, 2)
            # In screen/SVG coordinates, -dy is North (upwards) and +dx is East (rightwards)
            heading_deg = round((math.degrees(math.atan2(dx, -dy)) + 360) % 360, 1) if dist > 0.1 else 0.0
            heading_dir = get_cardinal_direction(heading_deg) if dist > 5.0 else "Stationary"

            # Predict next area from adjacent topology
            predicted_next_area = current_area
            if hasattr(self, "spatial_manager") and self.spatial_manager and dist > 5.0:
                try:
                    adj_areas = self.spatial_manager.get_adjacent_areas(current_area)
                    best_dot = -1.0
                    for adj in adj_areas:
                        adj_x, adj_y = self._get_camera_area_coordinates(adj)
                        v_adj_x = adj_x - x
                        v_adj_y = adj_y - y
                        mag = math.hypot(v_adj_x, v_adj_y)
                        if mag > 0:
                            dot = (dx * v_adj_x + dy * v_adj_y) / (dist * mag)
                            if dot > best_dot:
                                best_dot = dot
                                predicted_next_area = adj
                except Exception:
                    predicted_next_area = current_area

            # Threat escalation
            new_threat = (
                "critical" if severity == "critical" or audit_entry.get("anomaly_type") == "perimeter_breach"
                else ("intruder" if severity == "high" or audit_entry.get("anomaly_type") in ("prowler", "trespassing")
                else ("suspicious" if severity == "medium" or anomaly_detected
                else "normal"))
            )
            threat_rank = {"normal": 0, "suspicious": 1, "intruder": 2, "critical": 3}
            current_threat = matched_track.get("threat_level", "normal")
            if threat_rank.get(new_threat, 0) > threat_rank.get(current_threat, 0):
                matched_track["threat_level"] = new_threat

            new_wp = {
                "timestamp": now_iso,
                "camera": camera_entity_id,
                "area": current_area,
                "zone": perimeter_zone,
                "x": x,
                "y": y,
                "confidence": audit_entry.get("confidence", 0.8),
                "detected_objects": list(detected_objects),
            }
            matched_track["trajectory"].append(new_wp)
            matched_track["last_seen_ts"] = now_ts
            matched_track["last_seen_time"] = now_iso
            matched_track["current_area"] = current_area
            matched_track["current_camera"] = camera_entity_id
            matched_track["predicted_next_area"] = predicted_next_area
            if camera_entity_id not in matched_track["cameras_involved"]:
                matched_track["cameras_involved"].append(camera_entity_id)

            matched_track["velocity"] = {
                "speed": speed,
                "heading_deg": heading_deg,
                "heading_dir": heading_dir,
                "dx": round(dx, 1),
                "dy": round(dy, 1),
            }
            cams_str = " -> ".join(matched_track["cameras_involved"])
            matched_track["summary"] = (
                f"{target_type.capitalize()} tracked across {len(matched_track['cameras_involved'])} camera(s) ({cams_str}). "
                f"Heading {heading_dir} ({heading_deg}°) at {speed} u/s toward {predicted_next_area}."
            )

            # Fire updated event
            if hasattr(self.hass, "bus") and hasattr(self.hass.bus, "async_fire"):
                self.hass.bus.async_fire("otis_ai_intruder_track_updated", matched_track)

            result_track = matched_track

        else:
            prefix = camera_entity_id.replace("camera.", "")
            track_id = f"trk_{int(now_ts)}_{prefix}"
            threat_level = (
                "critical" if severity == "critical" or audit_entry.get("anomaly_type") == "perimeter_breach"
                else ("intruder" if severity == "high" or audit_entry.get("anomaly_type") in ("prowler", "trespassing")
                else ("suspicious" if severity == "medium" or anomaly_detected
                else "normal"))
            )
            new_track = {
                "track_id": track_id,
                "target_type": target_type,
                "threat_level": threat_level,
                "status": "active",
                "start_time": now_iso,
                "last_seen_time": now_iso,
                "start_ts": now_ts,
                "last_seen_ts": now_ts,
                "current_area": current_area,
                "current_camera": camera_entity_id,
                "cameras_involved": [camera_entity_id],
                "predicted_next_area": current_area,
                "velocity": {
                    "speed": 0.0,
                    "heading_deg": 0.0,
                    "heading_dir": "Stationary",
                    "dx": 0.0,
                    "dy": 0.0,
                },
                "trajectory": [{
                    "timestamp": now_iso,
                    "camera": camera_entity_id,
                    "area": current_area,
                    "zone": perimeter_zone,
                    "x": x,
                    "y": y,
                    "confidence": audit_entry.get("confidence", 0.8),
                    "detected_objects": list(detected_objects),
                }],
                "summary": f"{target_type.capitalize()} detected at {current_area} via {name}.",
            }
            self._active_intruder_tracks.append(new_track)
            self._historical_intruder_tracks.insert(0, new_track)
            if len(self._historical_intruder_tracks) > 50:
                self._historical_intruder_tracks.pop()

            # Fire created event
            if hasattr(self.hass, "bus") and hasattr(self.hass.bus, "async_fire"):
                self.hass.bus.async_fire("otis_ai_intruder_track_created", new_track)

            result_track = new_track

        # 4. Update sensor telemetry
        self._update_intruder_tracks_sensor()
        return result_track

    def _update_intruder_tracks_sensor(self) -> None:
        """Publish or update sensor.otis_intruder_tracks state with real-time triangulation state."""
        if not hasattr(self.hass, "states") or not hasattr(self.hass.states, "async_set"):
            return

        active = [t for t in self._active_intruder_tracks if t.get("status") == "active"]
        has_critical = any(t.get("threat_level") == "critical" for t in active)
        has_intruder = any(t.get("threat_level") in ("intruder", "suspicious") for t in active)

        if has_critical:
            state_val = "breach"
        elif has_intruder:
            state_val = "tracking"
        elif active:
            state_val = "monitoring"
        else:
            state_val = "clear"

        latest = active[-1] if active else (self._historical_intruder_tracks[0] if self._historical_intruder_tracks else None)

        attrs: dict[str, Any] = {
            "friendly_name": "Otis Intruder Spatial Tracks",
            "icon": "mdi:radar" if state_val in ("breach", "tracking") else "mdi:shield-check",
            "active_tracks_count": len(active),
            "active_tracks": [
                {
                    "track_id": t["track_id"],
                    "target_type": t["target_type"],
                    "threat_level": t["threat_level"],
                    "current_camera": t["current_camera"],
                    "current_area": t["current_area"],
                    "predicted_next_area": t.get("predicted_next_area"),
                    "waypoints_count": len(t.get("trajectory", [])),
                    "speed": t.get("velocity", {}).get("speed", 0.0),
                    "heading": t.get("velocity", {}).get("heading_dir", "Stationary"),
                    "summary": t.get("summary"),
                }
                for t in active
            ],
            "total_historical_tracks": len(self._historical_intruder_tracks),
        }

        if latest:
            attrs["latest_track_id"] = latest.get("track_id")
            attrs["latest_threat_level"] = latest.get("threat_level")
            attrs["latest_target_type"] = latest.get("target_type")
            attrs["latest_camera"] = latest.get("current_camera")
            attrs["latest_area"] = latest.get("current_area")
            attrs["latest_predicted_next_area"] = latest.get("predicted_next_area")
            attrs["latest_velocity"] = latest.get("velocity")
            attrs["latest_trajectory"] = latest.get("trajectory", [])
            attrs["latest_summary"] = latest.get("summary")

        self.hass.states.async_set("sensor.otis_intruder_tracks", state_val, attrs)

    def get_intruder_tracks(self) -> dict[str, Any]:
        """Return active and historical intruder spatial tracks."""
        active = [t for t in self._active_intruder_tracks if t.get("status") == "active"]
        return {
            "success": True,
            "active_tracks_count": len(active),
            "active_tracks": active,
            "historical_tracks": self._historical_intruder_tracks,
            "total_tracks": len(self._historical_intruder_tracks),
        }

    async def async_evaluate_contextual_alerts(self) -> list[dict[str, Any]]:
        """Evaluate cross-domain presence rules to detect garage doors left open, unattended appliances, etc."""
        presence_states = await self.async_get_presence_states(use_cache=True)
        household_present = presence_states.get("household_present", True)
        rooms = presence_states.get("rooms", {})

        all_states = self.hass.states.async_all() if hasattr(self.hass.states, "async_all") else []

        alerts: list[dict[str, Any]] = []
        now_dt = datetime.now()
        is_night = now_dt.hour >= 22 or now_dt.hour < 6

        # Rule 1: Garage Door Left Open While Away or Late at Night
        for s in all_states:
            eid = s.entity_id
            if eid.startswith("cover."):
                d_class = str(s.attributes.get("device_class") or "").lower()
                name = s.attributes.get("friendly_name") or eid
                is_garage = d_class == "garage" or "garage" in (eid + " " + name).lower()
                if is_garage and s.state == "open":
                    if not household_present:
                        alerts.append({
                            "id": f"contextual_garage_open_away_{eid}",
                            "title": f"Security Alert: {name} Left Open While Away",
                            "category": "security",
                            "priority": "high",
                            "icon": "mdi:garage-alert",
                            "description": f"{name} is currently open while all household members are away.",
                            "action_type": "call_service",
                            "action_payload": {
                                "service": "cover.close_cover",
                                "target": {"entity_id": eid},
                                "button_label": f"Close {name}",
                            },
                        })
                    elif is_night:
                        alerts.append({
                            "id": f"contextual_garage_open_night_{eid}",
                            "title": f"Security Alert: {name} Left Open at Night",
                            "category": "security",
                            "priority": "high",
                            "icon": "mdi:garage-alert",
                            "description": f"{name} remains open at {now_dt.strftime('%I:%M %p')}.",
                            "action_type": "call_service",
                            "action_payload": {
                                "service": "cover.close_cover",
                                "target": {"entity_id": eid},
                                "button_label": f"Close {name}",
                            },
                        })

        # Rule 2: Unattended High-Power Appliance in Vacant Room
        appliance_pattern = re.compile(
            r"\b(space[ _-]?heater|radiator|heater|iron|curling[ _-]?iron|hair[ _-]?dryer|blow[ _-]?dryer|curling[ _-]?wand|stove|cooktop|oven|griddle|kettle|air[ _-]?fryer|deep[ _-]?fryer|toaster)\b",
            re.IGNORECASE,
        )
        non_appliance_keywords = (
            "theater", "theatre", "avr", "receiver", "amplifier", "audio", "sound", "speaker",
            "subwoofer", "zone", "enhancer", "auto-update", "status", "firmware", "sync",
            "led", "light", "strip", "lamp", "bulb", "display", "tv", "television", "remote",
            "fan", "mute", "volume", "input", "hdmi", "sensor"
        )

        entity_to_area = self._build_entity_to_area_map()
        ent_reg = None
        try:
            ent_reg = er.async_get(self.hass)
        except Exception:
            pass

        for s in all_states:
            eid = s.entity_id
            if not eid.startswith("switch.") or s.state != "on":
                continue

            fname = s.attributes.get("friendly_name") or eid
            fname_lower = fname.lower()
            eid_lower = eid.lower()

            # Skip diagnostic or configuration entities
            entry = None
            if ent_reg:
                if hasattr(ent_reg, "async_get"):
                    entry = ent_reg.async_get(eid)
                elif hasattr(ent_reg, "entities") and eid in ent_reg.entities:
                    entry = ent_reg.entities[eid]
            if entry and getattr(entry, "entity_category", None) in ("config", "diagnostic"):
                continue

            # Skip devices that match common AV/lighting/non-appliance keywords
            if any(k in fname_lower or k in eid_lower for k in non_appliance_keywords):
                continue

            # Check if this switch matches actual high-draw appliance names with strict word boundaries
            if not appliance_pattern.search(fname_lower) and not appliance_pattern.search(eid_lower):
                continue

            # Determine the exact area for this appliance
            e_area = entity_to_area.get(eid)
            if not e_area:
                # Conservative fallback: only match if the entity explicitly references an area name with word boundary
                for a_id_cand, a_cand in rooms.items():
                    a_name_cand = (a_cand.get("area_name") or a_id_cand).lower()
                    if re.search(rf"\b{re.escape(a_id_cand)}\b", eid_lower) or re.search(rf"\b{re.escape(a_name_cand)}\b", fname_lower):
                        e_area = a_id_cand
                        break

            if not e_area or e_area not in rooms:
                continue

            r_info = rooms[e_area]
            if r_info.get("status") == "vacant":
                friendly = fname
                alerts.append({
                    "id": f"contextual_unattended_{eid}",
                    "title": f"Safety Alert: Unattended {friendly} in {r_info['area_name']}",
                    "category": "energy",
                    "priority": "high",
                    "icon": "mdi:fire-alert",
                    "description": f"{friendly} is turned on in {r_info['area_name']}, but the room has been vacant.",
                    "action_type": "call_service",
                    "action_payload": {
                        "service": "homeassistant.turn_off",
                        "target": {"entity_id": eid},
                        "button_label": f"Turn Off {friendly}",
                    },
                })

        # Rule 3: Exterior Locks Unlocked While Away or During Sleep Hours
        if not household_present or is_night:
            for s in all_states:
                eid = s.entity_id
                if eid.startswith("lock.") and s.state == "unlocked":
                    fname = s.attributes.get("friendly_name") or eid
                    reason = "while away" if not household_present else "during late night hours"
                    alerts.append({
                        "id": f"contextual_unlocked_{eid}",
                        "title": f"Security Guard: {fname} is Unlocked",
                        "category": "security",
                        "priority": "high",
                        "icon": "mdi:lock-alert",
                        "description": f"{fname} is unlocked {reason}.",
                        "action_type": "call_service",
                        "action_payload": {
                            "service": "lock.lock",
                            "target": {"entity_id": eid},
                            "button_label": f"Lock {fname}",
                        },
                    })

        # Rule 4: Unexpected Indoor Presence While Away
        if not household_present:
            for a_id, r_info in rooms.items():
                if r_info["probability"] >= 0.70:
                    alerts.append({
                        "id": f"contextual_intruder_{a_id}",
                        "title": f"Intrusion Alert: Presence in {r_info['area_name']} While Away",
                        "category": "security",
                        "priority": "critical",
                        "icon": "mdi:shield-account",
                        "description": f"High confidence occupancy ({r_info['confidence_percent']}%) detected in {r_info['area_name']} while away.",
                        "action_type": "call_service",
                        "action_payload": {
                            "service": "homeassistant.turn_on",
                            "target": {"entity_id": "alarm_control_panel.home"},
                            "button_label": "Arm Security",
                        },
                    })

        return alerts

    def get_audit_history(self) -> list[dict[str, Any]]:
        """Return the recent camera visual audit history."""
        return list(self._camera_audit_history)

    async def async_publish_fused_presence_states(self) -> dict[str, Any]:
        """Compute presence states and publish binary_sensor.otis_presence_<slug> to Home Assistant states."""
        res = await self.async_get_presence_states(use_cache=False)
        rooms = res.get("rooms", {})
        any_occupied = False

        for a_id, r_info in rooms.items():
            slug = re.sub(r"[^a-z0-9_]+", "_", a_id.lower()).strip("_") or "room"
            eid = f"binary_sensor.otis_presence_{slug}"
            prob = r_info.get("probability", 0.0)
            status = r_info.get("status", "vacant")
            is_active = (prob >= 0.50) or (status in ("occupied", "likely_occupied"))
            if is_active:
                any_occupied = True
            state_val = "on" if is_active else "off"
            attrs = {
                "friendly_name": f"{r_info.get('area_name', a_id)} Presence",
                "device_class": "occupancy",
                "probability": prob,
                "confidence_percent": r_info.get("confidence_percent", 0),
                "status": status,
                "area_id": a_id,
                "area_name": r_info.get("area_name", a_id),
                "sensors": r_info.get("sensors", {}),
            }
            if hasattr(self.hass, "states") and hasattr(self.hass.states, "async_set"):
                self.hass.states.async_set(eid, state_val, attrs)

        # Publish global active household occupancy sensor
        if hasattr(self.hass, "states") and hasattr(self.hass.states, "async_set"):
            self.hass.states.async_set(
                "binary_sensor.otis_active_occupancy",
                "on" if any_occupied else "off",
                {
                    "friendly_name": "Active Household Occupancy",
                    "device_class": "occupancy",
                    "occupied_count": res.get("occupied_count", 0),
                    "likely_count": res.get("likely_count", 0),
                    "occupied_areas": res.get("occupied_areas", []),
                    "likely_areas": res.get("likely_areas", []),
                },
            )

        # Process spatial presence transitions and migration pre-conditioning
        try:
            await self.async_process_presence_transitions(res)
        except Exception as trans_err:
            _LOGGER.debug("Error processing presence transitions: %s", trans_err)

        return res

    def record_area_transition(
        self,
        from_area: str | None,
        to_area: str,
        confidence: float = 0.8,
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        """Record an observed or inferred physical presence transition between areas."""
        ts = timestamp or time.time()
        record = {
            "from_area": from_area,
            "to_area": to_area,
            "confidence": round(confidence, 2),
            "timestamp": ts,
            "iso_time": datetime.fromtimestamp(ts).isoformat(),
        }
        self._transition_history.append(record)
        if len(self._transition_history) > 100:
            self._transition_history = self._transition_history[-100:]
        self._last_active_area = to_area
        self._last_active_area_ts = ts
        return record

    def get_transition_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the recent area transition history."""
        return self._transition_history[-limit:]

    def get_active_migration_intent(self) -> dict[str, Any] | None:
        """Return current active spatial migration hypothesis if still within validity window."""
        if not self._active_migration:
            return None
        now_ts = time.time()
        valid_until = self._active_migration.get("valid_until", 0.0)
        if now_ts > valid_until:
            self._active_migration = None
            return None
        return dict(self._active_migration)

    async def async_detect_migration_intent(
        self, presence_data: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Analyze recent spatial migration vector and time-of-day to predict intent and pre-conditioning."""
        if not self._transition_history:
            return None

        recent = self._transition_history[-1]
        now_ts = time.time()
        if now_ts - recent["timestamp"] > 300.0:
            return None

        now_dt = datetime.now()
        cur_hour = now_dt.hour + (now_dt.minute / 60.0)
        cur_to = (recent.get("to_area") or "").lower()

        rooms = (presence_data or {}).get("rooms", {})

        def is_room_occupied(area_keyword: str) -> bool:
            for rid, rdata in rooms.items():
                if area_keyword in rid.lower():
                    return rdata.get("probability", 0.0) >= 0.65
            return False

        # Pattern 1: Late Evening / Night Bedtime Sleep Migration (21:30 - 02:30)
        if (21.5 <= cur_hour <= 23.99 or cur_hour < 2.5) and any(
            k in cur_to for k in ("hallway", "stairs", "master")
        ):
            if not is_room_occupied("master"):
                intent = {
                    "intent": "sleep_bedtime",
                    "target_area": "master",
                    "source_area": cur_to,
                    "confidence": 0.88 if "master" in cur_to or "hallway" in cur_to else 0.72,
                    "lifestyle_macro": "bedtime_mode",
                    "preconditioning_state": "armed",
                    "suggested_action": "Pre-conditioning bedroom climate, dimming hallway lights, and pre-arming perimeter security",
                    "detected_at": now_dt.isoformat(),
                    "valid_until": now_ts + 600.0,
                }
                self._active_migration = intent
                return intent

        # Pattern 2: Evening Movie Migration (17:00 - 21:30)
        if (17.0 <= cur_hour < 21.5) and any(
            k in cur_to for k in ("hallway", "living", "theater", "great_room")
        ):
            if any(k in cur_to for k in ("hallway", "stairs", "great_room")) and not is_room_occupied("theater"):
                intent = {
                    "intent": "movie_night",
                    "target_area": "theater",
                    "source_area": cur_to,
                    "confidence": 0.85 if "hallway" in cur_to else 0.70,
                    "lifestyle_macro": "movie_night_mode",
                    "preconditioning_state": "armed",
                    "suggested_action": "Pre-cooling Theater to 68°F & pre-arming cinema display",
                    "detected_at": now_dt.isoformat(),
                    "valid_until": now_ts + 600.0,
                }
                self._active_migration = intent
                return intent

        # Pattern 3: Morning Awakening Migration (05:30 - 10:00)
        if (5.5 <= cur_hour <= 10.0) and any(
            k in cur_to for k in ("kitchen", "great_room", "hallway", "dining")
        ):
            if not is_room_occupied("kitchen"):
                intent = {
                    "intent": "morning_wake",
                    "target_area": "kitchen",
                    "source_area": cur_to,
                    "confidence": 0.80,
                    "lifestyle_macro": "morning_mode",
                    "preconditioning_state": "armed",
                    "suggested_action": "Adjusting morning kitchen temperature, raising motorized shades, and staging coffee appliance",
                    "detected_at": now_dt.isoformat(),
                    "valid_until": now_ts + 600.0,
                }
                self._active_migration = intent
                return intent

        # Pattern 4: Workday Focus Migration (07:30 - 18:00)
        if (7.5 <= cur_hour <= 18.0) and any(
            k in cur_to for k in ("hallway", "study", "office", "amy_s_office")
        ):
            target_slug = "study" if "study" in cur_to else "amy_s_office"
            if not is_room_occupied(target_slug):
                intent = {
                    "intent": "focus_work",
                    "target_area": target_slug,
                    "source_area": cur_to,
                    "confidence": 0.78,
                    "lifestyle_macro": "focus_work_mode",
                    "preconditioning_state": "armed",
                    "suggested_action": f"Adjusting {target_slug.replace('_', ' ').title()} comfort climate and circadian work illumination",
                    "detected_at": now_dt.isoformat(),
                    "valid_until": now_ts + 600.0,
                }
                self._active_migration = intent
                return intent

        return None

    async def async_process_presence_transitions(
        self, presence_data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Process updated presence states, record transition if room changed, and update sensor.otis_spatial_migration."""
        occupied_areas = presence_data.get("occupied_areas") or []
        now_ts = time.time()

        if occupied_areas:
            primary_area = occupied_areas[0].lower().replace(" ", "_")
            if self._last_active_area != primary_area:
                if self._last_active_area is not None:
                    self.record_area_transition(
                        from_area=self._last_active_area,
                        to_area=primary_area,
                        confidence=0.85,
                        timestamp=now_ts,
                    )
                else:
                    self._last_active_area = primary_area
                    self._last_active_area_ts = now_ts

        intent = await self.async_detect_migration_intent(presence_data)

        # Publish sensor.otis_spatial_migration
        if hasattr(self.hass, "states") and hasattr(self.hass.states, "async_set"):
            state_val = intent["intent"] if intent else "idle"
            attrs = {
                "friendly_name": "Otis Spatial Migration & Pre-Conditioning",
                "icon": "mdi:transit-connection-variant",
                "target_area": intent.get("target_area") if intent else None,
                "source_area": intent.get("source_area") if intent else None,
                "confidence": intent.get("confidence") if intent else 0.0,
                "lifestyle_macro": intent.get("lifestyle_macro") if intent else None,
                "preconditioning_state": intent.get("preconditioning_state") if intent else "idle",
                "suggested_action": intent.get("suggested_action") if intent else "Monitoring room-to-room migration flows",
                "recent_transitions": self.get_transition_history(5),
            }
            self.hass.states.async_set("sensor.otis_spatial_migration", state_val, attrs)

        # Trigger soft pre-conditioning actions in macro_manager
        if getattr(self, "macro_manager", None):
            try:
                await self.macro_manager.async_process_spatial_migration(
                    intent, occupied_areas=presence_data.get("occupied_areas")
                )
            except Exception as mm_err:
                _LOGGER.debug("Error processing spatial migration in macro_manager: %s", mm_err)

        # Trigger follow-me audio migration in audio_manager
        if getattr(self, "audio_manager", None):
            try:
                await self.audio_manager.async_process_spatial_audio_migration(
                    intent, occupied_areas=presence_data.get("occupied_areas")
                )
            except Exception as am_err:
                _LOGGER.debug("Error processing spatial audio migration in audio_manager: %s", am_err)

        return intent

    def async_start_presence_tracking(self) -> None:
        """Start listening to state changes on presence, motion, and media entities to auto-publish presence states."""
        if getattr(self, "_tracking_unsub", None):
            return

        import asyncio

        _debounce_task: asyncio.Task | None = None

        async def _debounced_publish():
            await asyncio.sleep(0.5)
            try:
                await self.async_publish_fused_presence_states()
            except Exception as e:
                _LOGGER.debug("Error in auto-publishing fused presence: %s", e)

        def _schedule_publish():
            nonlocal _debounce_task
            if _debounce_task and not _debounce_task.done():
                _debounce_task.cancel()
            if hasattr(self.hass, "async_create_task"):
                _debounce_task = self.hass.async_create_task(_debounced_publish())

        def _on_state_changed(event):
            eid = getattr(event, "data", {}).get("entity_id", "")
            if (
                eid.startswith("binary_sensor.")
                or eid.startswith("media_player.")
                or eid.startswith("person.")
                or eid.startswith("device_tracker.")
            ):
                if eid.startswith("binary_sensor.otis_"):
                    return
                if hasattr(self.hass, "loop") and self.hass.loop:
                    try:
                        import asyncio

                        if asyncio.get_running_loop() is self.hass.loop:
                            _schedule_publish()
                        else:
                            self.hass.loop.call_soon_threadsafe(_schedule_publish)
                    except RuntimeError:
                        self.hass.loop.call_soon_threadsafe(_schedule_publish)
                else:
                    _schedule_publish()

        if hasattr(self.hass, "bus") and hasattr(self.hass.bus, "async_listen"):
            try:
                from homeassistant.const import EVENT_STATE_CHANGED
            except ImportError:
                EVENT_STATE_CHANGED = "state_changed"

            self._tracking_unsub = self.hass.bus.async_listen(
                EVENT_STATE_CHANGED, _on_state_changed
            )
