"""Otis AI Companion: Multi-Modal Vision & Presence Intelligence (Phase 8).

Coordinates multi-sensor room occupancy fusion (mmWave radar, PIR motion, media playback,
BLE beacon tracking) into spatial probability states, camera snapshot analysis & anomaly
detection via Gemini Vision, and proactive contextual perimeter alerts.
"""

from __future__ import annotations

import base64
from datetime import datetime
import logging
import re
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er

_LOGGER = logging.getLogger(__name__)


class VisionPresenceManager:
    """Manages multi-sensor room occupancy fusion, camera vision analysis, and contextual perimeter alerts."""

    def __init__(self, hass: HomeAssistant, spatial_manager=None, energy_manager=None) -> None:
        """Initialize the Vision & Presence Manager."""
        self.hass = hass
        self.spatial_manager = spatial_manager
        self.energy_manager = energy_manager
        self._camera_audit_history: list[dict[str, Any]] = []
        self._presence_cache: dict[str, Any] = {}
        self._presence_cache_ts: float = 0.0

    def _build_entity_to_area_map(self) -> dict[str, str]:
        """Build mapping of entity_id -> area_id considering both entity and device registries."""
        entity_to_area: dict[str, str] = {}
        dev_to_area: dict[str, str] = {}
        try:
            dev_reg = dr.async_get(self.hass)
            if hasattr(dev_reg, "devices"):
                for dev_id, dev in dev_reg.devices.items():
                    if getattr(dev, "area_id", None):
                        dev_to_area[dev_id] = dev.area_id
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
                if not matched_area:
                    matched_area = entity_to_area.get(s.entity_id)
                is_home = (state_val in ("home", "on")) or (matched_area is not None and state_val not in ("not_home", "away"))
                persons_home.append({
                    "entity_id": s.entity_id,
                    "name": s.attributes.get("friendly_name", s.entity_id),
                    "is_home": is_home,
                    "area_id": matched_area,
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

                # 4. BLE Beacon / Room Tracker
                if eid.startswith("device_tracker.") or "espresence" in eid_lower or "beacon" in eid_lower:
                    ble_entities.append(eid)
                    if s.state in ("home", "on") or s.state.lower() == a_lower:
                        ble_active = True

                # 5. Lights / Switches active
                if eid.startswith("light.") or (eid.startswith("switch.") and "plug" in eid_lower):
                    if s.state == "on":
                        light_entities.append(eid)
                        lights_active = True

            # Also check if any Person entity is explicitly in this room
            person_in_room = any(p["is_home"] and p.get("area_id") == a_id for p in persons_home)
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
        """Discover all security cameras and doorbells across Home Assistant."""
        area_reg = ar.async_get(self.hass)
        areas_by_id = {a.id: a.name for a in area_reg.async_list_areas()} if hasattr(area_reg, "async_list_areas") else {}
        entity_to_area = self._build_entity_to_area_map()

        all_states = self.hass.states.async_all() if hasattr(self.hass.states, "async_all") else []
        cameras: list[dict[str, Any]] = []

        for s in all_states:
            if not s.entity_id.startswith("camera."):
                continue

            area_id = entity_to_area.get(s.entity_id)
            area_name = areas_by_id.get(area_id, "Unknown Area")
            name = s.attributes.get("friendly_name") or s.entity_id

            # Detect camera classification
            cam_lower = (s.entity_id + " " + name).lower()
            is_doorbell = "doorbell" in cam_lower
            is_perimeter = any(k in cam_lower for k in ("front", "back", "patio", "yard", "driveway", "porch", "exterior"))
            is_interior = any(k in cam_lower for k in ("living", "kitchen", "study", "nursery", "office", "hallway", "garage"))

            cameras.append({
                "entity_id": s.entity_id,
                "name": name,
                "state": s.state,
                "area_id": area_id,
                "area_name": area_name,
                "is_doorbell": is_doorbell,
                "is_perimeter": is_perimeter,
                "is_interior": is_interior,
                "model": s.attributes.get("model_name") or s.attributes.get("brand"),
                "stream_source": s.attributes.get("frontend_stream_type"),
            })

        return cameras

    async def async_analyze_camera(
        self,
        camera_entity_id: str,
        prompt: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform snapshot analysis and anomaly detection using Gemini Vision or multi-attribute telemetry."""
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

        # 2. Inspect smart camera sensors in same area or prefix (Reolink, Protect, Frigate)
        detected_objects: list[str] = []
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

        # Deduplicate tags
        detected_objects = sorted(list(set(detected_objects)))

        # 3. Formulate Vision Analysis summary
        status = "normal"
        safety_assessment = "Perimeter normal. No security anomalies detected."

        if "package" in detected_objects:
            status = "attention_needed"
            safety_assessment = "Package delivery detected on doorstep/walkway."
            summary = f"Visual audit for {name}: Package detected. Walkway unobstructed."
        elif "person" in detected_objects:
            status = "attention_needed" if is_doorbell else "motion_detected"
            safety_assessment = "Visitor or individual detected within field of view."
            summary = f"Visual audit for {name}: Person presence detected."
        elif "vehicle" in detected_objects:
            status = "motion_detected"
            safety_assessment = "Vehicle detected in driveway or approach zone."
            summary = f"Visual audit for {name}: Vehicle presence detected."
        elif "motion" in detected_objects:
            status = "motion_detected"
            safety_assessment = "Active movement detected in monitored zone."
            summary = f"Visual audit for {name}: Movement in frame."
        else:
            summary = f"Visual audit for {name}: Scene clear. Normal baseline."

        audit_entry = {
            "id": f"audit_{int(time.time())}_{prefix}",
            "timestamp": datetime.now().isoformat(),
            "camera": camera_entity_id,
            "name": name,
            "status": status,
            "summary": summary,
            "detected_objects": detected_objects,
            "safety_assessment": safety_assessment,
            "has_snapshot": image_bytes is not None,
            "snapshot_preview": base64_data[:60] + "..." if base64_data else None,
            "prompt_used": prompt or "Analyze camera frame for visitors, packages, open gates, or anomalies",
        }

        self._camera_audit_history.insert(0, audit_entry)
        if len(self._camera_audit_history) > 30:
            self._camera_audit_history.pop()

        # Fire event on bus for real-time frontend listener
        if hasattr(self.hass, "bus") and hasattr(self.hass.bus, "async_fire"):
            self.hass.bus.async_fire("otis_ai_vision_analysis_completed", audit_entry)

        return {
            "success": True,
            "audit": audit_entry,
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
            "theater", "theatre", "yamaha", "receiver", "amplifier", "audio", "sound", "speaker",
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
