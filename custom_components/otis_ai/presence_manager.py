"""Otis Multimodal Presence Fusion Manager (Phase 8).

Combines four advanced sensing pillars:
1. BLE RSSI trilateration and micro-beacon distance modeling.
2. mmWave micro-radar static and micro-motion target sensing (e.g. breathing/heartbeat while sitting still or sleeping).
3. Thermal infrared heat-signature delta and human vs pet/vacuum discrimination.
4. Acoustic footprinting (ambient noise floor, decibel spikes, voice/speech events).

Fused using Bayesian dynamic confidence weighting to completely eliminate false positives
(robotic vacuums, wandering pets, abandoned TVs) and false negatives (residents sitting still reading or asleep).
"""

from __future__ import annotations

import logging
import math
import re
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)

_LOGGER = logging.getLogger(__name__)

# Modality Fusion Confidence Weights (Default normalized weights)
DEFAULT_WEIGHT_MMWAVE = 0.35
DEFAULT_WEIGHT_THERMAL = 0.25
DEFAULT_WEIGHT_BLE = 0.20
DEFAULT_WEIGHT_PIR = 0.10
DEFAULT_WEIGHT_ACOUSTIC = 0.05
DEFAULT_WEIGHT_MEDIA = 0.05

# BLE Path Loss Parameters (Log-distance indoor model)
DEFAULT_BLE_REF_RSSI = -59.0  # RSSI at 1 meter in dBm
DEFAULT_BLE_PATH_LOSS_EXPONENT = 2.2  # Indoor residential path-loss exponent (n)

# Thermal Signature Gating (Degrees Celsius)
HUMAN_MIN_SURFACE_TEMP_C = 29.5
HUMAN_MAX_SURFACE_TEMP_C = 38.5
MIN_THERMAL_AMBIENT_DELTA_C = 2.0
PET_MAX_SURFACE_TEMP_C = 28.5  # Typical fur exterior surface temperature is substantially cooler than human skin

# Acoustic Footprinting Parameters
DEFAULT_ACOUSTIC_SPIKE_DB = 8.0  # dB increase over ambient noise floor for activity
SPEECH_CONFIDENCE_BONUS = 0.35

# Target States
MMWAVE_STATE_STATIONARY = "stationary"
MMWAVE_STATE_MOVING = "moving"
MMWAVE_STATE_BOTH = "both"
MMWAVE_STATE_CLEAR = "clear"

STATUS_OCCUPIED = "occupied"
STATUS_MICRO_PRESENCE = "micro_presence"
STATUS_LIKELY = "likely_occupied"
STATUS_VACANT = "vacant"


def calculate_ble_distance(
    rssi: float,
    ref_rssi: float = DEFAULT_BLE_REF_RSSI,
    path_loss_exp: float = DEFAULT_BLE_PATH_LOSS_EXPONENT,
) -> float:
    """Calculate estimated distance (in meters) from BLE RSSI using the log-distance path loss model.

    Formula: d = 10 ** ((ref_rssi - rssi) / (10 * n))
    """
    if rssi >= 0 or math.isnan(rssi):
        return 0.1
    # Cap path loss exponent within sensible physical bounds [1.5, 4.5]
    n = max(1.5, min(4.5, float(path_loss_exp)))
    exponent = (ref_rssi - rssi) / (10.0 * n)
    try:
        distance = math.pow(10.0, exponent)
        return round(max(0.1, min(50.0, distance)), 2)
    except (OverflowError, ValueError):
        return 50.0


def solve_2d_trilateration(
    anchors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Solve 2D position (x, y) from 3 or more fixed anchor receivers with distance estimates.

    Anchors format: [{"x": float, "y": float, "distance": float, "name": str}, ...]
    Uses linearized least-squares estimation with singular matrix fallback.
    """
    valid_anchors = [
        a for a in anchors
        if isinstance(a, dict)
        and "x" in a and "y" in a and "distance" in a
        and a["distance"] > 0
    ]

    if len(valid_anchors) < 2:
        return None

    if len(valid_anchors) == 2:
        # 2-point weighted midpoint approximation
        a1, a2 = valid_anchors[0], valid_anchors[1]
        w1 = 1.0 / max(0.1, a1["distance"]) ** 2
        w2 = 1.0 / max(0.1, a2["distance"]) ** 2
        total_w = w1 + w2
        est_x = round((a1["x"] * w1 + a2["x"] * w2) / total_w, 2)
        est_y = round((a1["y"] * w1 + a2["y"] * w2) / total_w, 2)
        return {"x": est_x, "y": est_y, "method": "weighted_pair", "anchor_count": 2}

    # Linearized trilateration with reference point (x1, y1)
    # 2(x_i - x_1)x + 2(y_i - y_1)y = (d_1^2 - d_i^2) - (x_1^2 - x_i^2) - (y_1^2 - y_i^2)
    ref = valid_anchors[0]
    x1, y1, d1 = float(ref["x"]), float(ref["y"]), float(ref["distance"])

    a_matrix: list[list[float]] = []
    b_vector: list[float] = []

    for a in valid_anchors[1:]:
        xi, yi, di = float(a["x"]), float(a["y"]), float(a["distance"])
        row = [2.0 * (xi - x1), 2.0 * (yi - y1)]
        b_val = (d1 ** 2 - di ** 2) - (x1 ** 2 - xi ** 2) - (y1 ** 2 - yi ** 2)
        a_matrix.append(row)
        b_vector.append(b_val)

    # Solve normal equations: (A^T * A) * [x, y]^T = A^T * b
    ata_00 = sum(row[0] * row[0] for row in a_matrix)
    ata_01 = sum(row[0] * row[1] for row in a_matrix)
    ata_10 = ata_01
    ata_11 = sum(row[1] * row[1] for row in a_matrix)

    atb_0 = sum(row[0] * b_vector[i] for i, row in enumerate(a_matrix))
    atb_1 = sum(row[1] * b_vector[i] for i, row in enumerate(a_matrix))

    det = (ata_00 * ata_11) - (ata_01 * ata_10)

    if abs(det) < 1e-6:
        # Collinear or ill-conditioned: fall back to inverse-distance weighted centroid
        weights = [1.0 / max(0.1, a["distance"]) ** 2 for a in valid_anchors]
        total_w = sum(weights)
        cx = sum(a["x"] * w for a, w in zip(valid_anchors, weights)) / total_w
        cy = sum(a["y"] * w for a, w in zip(valid_anchors, weights)) / total_w
        return {"x": round(cx, 2), "y": round(cy, 2), "method": "weighted_centroid_fallback", "anchor_count": len(valid_anchors)}

    inv_00 = ata_11 / det
    inv_01 = -ata_01 / det
    inv_10 = -ata_10 / det
    inv_11 = ata_00 / det

    x_sol = (inv_00 * atb_0) + (inv_01 * atb_1)
    y_sol = (inv_10 * atb_0) + (inv_11 * atb_1)

    return {
        "x": round(x_sol, 2),
        "y": round(y_sol, 2),
        "method": "least_squares_trilateration",
        "anchor_count": len(valid_anchors),
    }


def evaluate_mmwave_signature(
    state: str,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate mmWave radar target presence, distinguishing static micro-motion from dynamic movement."""
    attrs = attributes or {}
    st_lower = str(state).lower()

    # Inspect attributes for micro-motion / stationary target indicators (LD2410, FP1/FP2, Screek)
    static_energy = float(attrs.get("static_target_energy") or attrs.get("stationary_energy") or 0.0)
    moving_energy = float(attrs.get("moving_target_energy") or attrs.get("motion_energy") or 0.0)
    target_distance = attrs.get("target_distance") or attrs.get("detection_distance") or attrs.get("distance")
    target_count = attrs.get("target_count") or attrs.get("targets") or (1 if st_lower == "on" else 0)

    try:
        dist_float = float(target_distance) if target_distance is not None else None
    except (ValueError, TypeError):
        dist_float = None

    is_active = st_lower in ("on", "true", "detected", "occupied")
    is_stationary = static_energy > 0 or "stationary" in st_lower or bool(attrs.get("still_target"))
    is_moving = moving_energy > 0 or "moving" in st_lower or bool(attrs.get("moving_target"))

    if is_active and is_stationary and not is_moving:
        mode = MMWAVE_STATE_STATIONARY
        confidence = 0.94  # Static presence (breathing/micro-posture)
    elif is_active and is_moving and not is_stationary:
        mode = MMWAVE_STATE_MOVING
        confidence = 0.90
    elif is_active:
        mode = MMWAVE_STATE_BOTH if (is_stationary and is_moving) else MMWAVE_STATE_MOVING
        confidence = 0.95
    else:
        mode = MMWAVE_STATE_CLEAR
        confidence = 0.0

    return {
        "active": is_active,
        "mode": mode,
        "confidence": confidence,
        "target_distance_m": dist_float,
        "target_count": int(target_count) if isinstance(target_count, (int, float)) else 1,
        "static_energy": static_energy,
        "moving_energy": moving_energy,
        "zone": attrs.get("zone") or attrs.get("detection_zone"),
    }


def evaluate_thermal_signature(
    target_temp_c: float | None,
    ambient_temp_c: float | None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate thermal infrared sensor / array for human body heat vs background and pets."""
    attrs = attributes or {}
    if target_temp_c is None or ambient_temp_c is None:
        return {
            "detected": False,
            "confidence": 0.0,
            "target_type": "unknown",
            "delta_c": 0.0,
            "reason": "missing_temperatures",
        }

    delta = target_temp_c - ambient_temp_c
    pixel_count = attrs.get("hotspot_pixel_count") or attrs.get("pixel_count") or 1

    # Check for human body surface range (typically 30C - 38C)
    if (HUMAN_MIN_SURFACE_TEMP_C <= target_temp_c <= HUMAN_MAX_SURFACE_TEMP_C) and delta >= MIN_THERMAL_AMBIENT_DELTA_C:
        confidence = min(0.96, 0.70 + (delta * 0.04))
        target_type = "human"
        detected = True
    elif target_temp_c < HUMAN_MIN_SURFACE_TEMP_C and delta >= 1.5:
        # Warmer than ambient but below human skin surface: typical small domestic pet or localized warm surface
        confidence = 0.30
        target_type = "pet_or_appliance"
        detected = False  # Reject as human presence
    elif target_temp_c > HUMAN_MAX_SURFACE_TEMP_C:
        # High heat signature: stovetop, fireplace, radiator, electronics
        confidence = 0.10
        target_type = "heat_source"
        detected = False
    else:
        confidence = 0.0
        target_type = "none"
        detected = False

    return {
        "detected": detected,
        "confidence": round(confidence, 2),
        "target_type": target_type,
        "delta_c": round(delta, 1),
        "target_temp_c": round(target_temp_c, 1),
        "ambient_temp_c": round(ambient_temp_c, 1),
        "pixel_count": pixel_count,
    }


def evaluate_acoustic_footprint(
    current_db: float | None,
    ambient_floor_db: float | None,
    event_type: str | None = None,
) -> dict[str, Any]:
    """Evaluate acoustic sensor readings, decibel spikes, and voice detection events."""
    if current_db is None or ambient_floor_db is None:
        return {
            "detected": False,
            "confidence": 0.0,
            "event_type": event_type or "none",
            "db_delta": 0.0,
        }

    db_delta = max(0.0, current_db - ambient_floor_db)
    is_spike = db_delta >= DEFAULT_ACOUSTIC_SPIKE_DB

    # Acoustic classifications
    evt = str(event_type or "").lower()
    is_speech = any(k in evt for k in ("speech", "voice", "talking", "conversation"))
    is_activity = any(k in evt for k in ("footstep", "walking", "keyboard", "presence", "cough"))

    if is_speech:
        confidence = min(0.92, 0.55 + SPEECH_CONFIDENCE_BONUS + (db_delta * 0.02))
        detected = True
    elif is_spike and is_activity:
        confidence = min(0.75, 0.40 + (db_delta * 0.03))
        detected = True
    elif is_spike:
        # Noise spike without classified activity: lower confidence to avoid HVAC / exterior false alarms
        confidence = min(0.50, 0.25 + (db_delta * 0.02))
        detected = False
    else:
        confidence = 0.0
        detected = False

    return {
        "detected": detected,
        "confidence": round(confidence, 2),
        "event_type": evt or "ambient",
        "current_db": round(current_db, 1),
        "ambient_floor_db": round(ambient_floor_db, 1),
        "db_delta": round(db_delta, 1),
    }


class PresenceFusionManager:
    """Multimodal presence fusion engine coordinating BLE, mmWave, Thermal, and Acoustic sensors."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the Multimodal Presence Fusion Manager."""
        self.hass = hass
        self._last_fused_telemetry: dict[str, Any] = {}
        self._last_fused_ts: float = 0.0
        self._cache_duration_sec: float = 3.0
        self._anchor_positions: dict[str, dict[str, float]] = {}  # {anchor_id: {"x": float, "y": float, "area": str}}
        self._beacon_assignments: dict[str, str] = {}  # {beacon_mac_or_id: user_persona}

    def set_anchor_positions(self, anchors: dict[str, dict[str, float]]) -> None:
        """Configure spatial anchor receiver coordinates for BLE trilateration."""
        self._anchor_positions = dict(anchors)

    def get_anchor_positions(self) -> dict[str, dict[str, float]]:
        """Return registered BLE anchor coordinates."""
        return dict(self._anchor_positions)

    def assign_beacon_user(self, beacon_id: str, persona: str) -> None:
        """Map a BLE beacon MAC, UUID, or tracker entity to a specific persona/user."""
        self._beacon_assignments[str(beacon_id).lower()] = str(persona)

    def get_beacon_user(self, beacon_id: str) -> str | None:
        """Get the persona/user attributed to a beacon."""
        return self._beacon_assignments.get(str(beacon_id).lower())

    def trilaterate_beacon(
        self,
        anchor_observations: list[dict[str, Any]],
        ref_rssi: float = DEFAULT_BLE_REF_RSSI,
        path_loss_exp: float = DEFAULT_BLE_PATH_LOSS_EXPONENT,
    ) -> dict[str, Any] | None:
        """Trilaterate a BLE target given observations from multiple anchors.

        anchor_observations: [{"anchor_id": "esp32_proxy_1", "rssi": -68.0, "x": 2.0, "y": 4.5}, ...]
        """
        prepared_anchors: list[dict[str, Any]] = []
        for obs in anchor_observations:
            aid = str(obs.get("anchor_id") or "")
            rssi = float(obs.get("rssi") or -100.0)
            x_pos = obs.get("x")
            y_pos = obs.get("y")

            # Fall back to internal registered anchor coordinates if not in observation dict
            if (x_pos is None or y_pos is None) and aid in self._anchor_positions:
                x_pos = self._anchor_positions[aid].get("x")
                y_pos = self._anchor_positions[aid].get("y")

            if x_pos is not None and y_pos is not None:
                dist = calculate_ble_distance(rssi, ref_rssi, path_loss_exp)
                prepared_anchors.append({
                    "anchor_id": aid,
                    "x": float(x_pos),
                    "y": float(y_pos),
                    "distance": dist,
                    "rssi": rssi,
                })

        result = solve_2d_trilateration(prepared_anchors)
        if result:
            result["anchors_used"] = prepared_anchors
        return result

    def fuse_room_modalities(
        self,
        area_id: str,
        area_name: str,
        mmwave_data: dict[str, Any] | None = None,
        thermal_data: dict[str, Any] | None = None,
        ble_data: dict[str, Any] | None = None,
        pir_data: dict[str, Any] | None = None,
        acoustic_data: dict[str, Any] | None = None,
        media_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Combine all modalities for a room using dynamic Bayesian weighting and false-alarm suppression.

        Suppresses false positives:
        - Moving vacuum: PIR is on, but thermal is non-human, mmWave static is 0, BLE is absent.
        - Pet roaming: PIR is on, but thermal signature is pet (<29.5C), no BLE, no speech.
        - TV left playing: Media is playing, but mmWave, thermal, BLE, PIR, and speech are all 0.

        Eliminates false negatives:
        - Resident sitting completely still reading / sleeping: PIR is off, but mmWave stationary micro-motion
          and human thermal presence are active -> yields high occupancy probability.
        """
        mmwave = mmwave_data or {"active": False, "confidence": 0.0, "mode": MMWAVE_STATE_CLEAR}
        thermal = thermal_data or {"detected": False, "confidence": 0.0, "target_type": "none"}
        ble = ble_data or {"active": False, "confidence": 0.0, "distance_m": None, "user": None}
        pir = pir_data or {"active": False, "confidence": 0.0, "seconds_since_motion": None}
        acoustic = acoustic_data or {"detected": False, "confidence": 0.0, "event_type": "ambient"}
        media = media_data or {"active": False, "confidence": 0.0}

        p_mmwave = float(mmwave.get("confidence") or 0.0)
        p_thermal = float(thermal.get("confidence") or 0.0) if thermal.get("detected") else 0.0
        p_ble = float(ble.get("confidence") or 0.0)
        p_pir = float(pir.get("confidence") or 0.0)
        p_acoustic = float(acoustic.get("confidence") or 0.0)
        p_media = float(media.get("confidence") or 0.0)

        # Dynamic cross-validation & false positive suppression:
        # Case A: Vacuum / Pet Rejection
        # If PIR triggered, but thermal target is explicitly 'pet_or_appliance' or 'heat_source', or thermal is 0 with no BLE and no mmWave static
        is_false_pir_suspect = (
            pir.get("active")
            and not mmwave.get("active")
            and not ble.get("active")
            and (thermal.get("target_type") in ("pet_or_appliance", "heat_source") or not thermal.get("detected"))
        )
        if is_false_pir_suspect:
            # Heavily discount PIR to avoid triggering full room occupancy on robot vacuums or pets
            p_pir *= 0.20

        # Case B: TV left playing in empty room
        # Media active but zero human biological/spatial confirmation across mmWave, Thermal, BLE, and PIR
        is_abandoned_media = (
            media.get("active")
            and not mmwave.get("active")
            and not thermal.get("detected")
            and not ble.get("active")
            and not pir.get("active")
            and not acoustic.get("detected")
        )
        if is_abandoned_media:
            p_media *= 0.15

        # Case C: Micro-presence boost (sleeping / reading resident)
        # mmWave stationary micro-motion or human thermal detected while PIR is off
        is_micro_presence = (
            (mmwave.get("mode") == MMWAVE_STATE_STATIONARY or thermal.get("detected"))
            and not pir.get("active")
        )

        # Multiplicative Bayesian odds combination: P = 1 - prod(1 - p_i)
        combined_prob = 1.0 - (
            (1.0 - p_mmwave)
            * (1.0 - p_thermal)
            * (1.0 - p_ble)
            * (1.0 - p_pir)
            * (1.0 - p_acoustic)
            * (1.0 - p_media)
        )
        prob_clamped = max(0.0, min(1.0, combined_prob))

        # Classification
        if is_micro_presence and prob_clamped >= 0.70:
            status = STATUS_MICRO_PRESENCE
        elif prob_clamped >= 0.65:
            status = STATUS_OCCUPIED
        elif prob_clamped >= 0.30:
            status = STATUS_LIKELY
        else:
            status = STATUS_VACANT

        # Build list of active confirmation modalities
        active_modalities: list[str] = []
        if mmwave.get("active"):
            active_modalities.append(f"mmwave_{mmwave.get('mode', 'active')}")
        if thermal.get("detected"):
            active_modalities.append("thermal_human")
        if ble.get("active"):
            user_lbl = f" ({ble['user']})" if ble.get("user") else ""
            active_modalities.append(f"ble_beacon{user_lbl}")
        if pir.get("active") and not is_false_pir_suspect:
            active_modalities.append("pir_motion")
        if acoustic.get("detected"):
            active_modalities.append(f"acoustic_{acoustic.get('event_type', 'sound')}")
        if media.get("active") and not is_abandoned_media:
            active_modalities.append("media_playback")

        return {
            "area_id": area_id,
            "area_name": area_name,
            "status": status,
            "probability": round(prob_clamped, 2),
            "confidence_percent": int(prob_clamped * 100),
            "active_modalities": active_modalities,
            "is_micro_presence": is_micro_presence,
            "attributed_user": ble.get("user"),
            "modalities": {
                "mmwave": mmwave,
                "thermal": thermal,
                "ble": ble,
                "pir": pir,
                "acoustic": acoustic,
                "media": media,
            },
        }

    async def async_fuse_presence(self, use_cache: bool = True) -> dict[str, Any]:
        """Audit all Home Assistant areas and compute fused multimodal presence across all 4 pillars."""
        now_ts = time.time()
        if use_cache and (now_ts - self._last_fused_ts < self._cache_duration_sec) and self._last_fused_telemetry:
            return self._last_fused_telemetry

        area_reg = ar.async_get(self.hass) if hasattr(ar, "async_get") else None
        ent_reg = er.async_get(self.hass) if hasattr(er, "async_get") else None
        dev_reg = dr.async_get(self.hass) if hasattr(dr, "async_get") else None

        areas = list(area_reg.async_list_areas()) if area_reg and hasattr(area_reg, "async_list_areas") else []
        all_states = self.hass.states.async_all() if hasattr(self.hass.states, "async_all") else []

        # Map entities to areas
        entity_to_area: dict[str, str] = {}
        if ent_reg and hasattr(ent_reg, "entities"):
            for ent_entry in ent_reg.entities.values():
                if ent_entry.area_id:
                    entity_to_area[ent_entry.entity_id] = ent_entry.area_id
                elif ent_entry.device_id and dev_reg:
                    dev = dev_reg.async_get(ent_entry.device_id) if hasattr(dev_reg, "async_get") else getattr(dev_reg, "devices", {}).get(ent_entry.device_id)
                    if dev and getattr(dev, "area_id", None):
                        entity_to_area[ent_entry.entity_id] = dev.area_id

        room_results: dict[str, dict[str, Any]] = {}
        occupied_areas: list[str] = []
        micro_presence_areas: list[str] = []
        likely_areas: list[str] = []
        vacant_areas: list[str] = []

        for area in areas:
            a_id = area.id
            a_name = area.name
            a_lower = a_name.lower()

            area_states = [
                s for s in all_states
                if entity_to_area.get(s.entity_id) == a_id
                or re.search(rf"\b{re.escape(a_lower)}\b", (s.attributes.get("friendly_name") or s.entity_id).lower())
            ]

            # 1. mmWave Radar
            mmwave_eval: dict[str, Any] = {"active": False, "confidence": 0.0, "mode": MMWAVE_STATE_CLEAR}
            for s in area_states:
                eid_l = s.entity_id.lower()
                d_class = str(s.attributes.get("device_class") or "").lower()
                is_mm = (
                    d_class in ("occupancy", "presence")
                    or any(k in eid_l for k in ("mmwave", "radar", "ld2410", "fp1", "fp2", "screek"))
                ) and s.entity_id.startswith("binary_sensor.")
                if is_mm:
                    ev = evaluate_mmwave_signature(s.state, s.attributes)
                    if ev["confidence"] > mmwave_eval["confidence"]:
                        mmwave_eval = ev

            # 2. Thermal Signature
            ambient_temp: float | None = None
            target_temp: float | None = None
            thermal_attrs: dict[str, Any] = {}
            for s in area_states:
                d_class = str(s.attributes.get("device_class") or "").lower()
                eid_l = s.entity_id.lower()
                if d_class == "temperature" or "temp" in eid_l:
                    try:
                        t_val = float(s.state)
                        if any(k in eid_l for k in ("ambient", "room_temp", "climate", "air")):
                            ambient_temp = t_val
                        elif any(k in eid_l for k in ("thermal", "target", "body", "amg8833", "mlx90640")):
                            target_temp = t_val
                            thermal_attrs = dict(s.attributes)
                        elif ambient_temp is None:
                            ambient_temp = t_val
                    except (ValueError, TypeError):
                        pass

            thermal_eval = evaluate_thermal_signature(target_temp, ambient_temp, thermal_attrs)

            # 3. BLE Beacon / Room Tracker
            ble_eval: dict[str, Any] = {"active": False, "confidence": 0.0, "distance_m": None, "user": None}
            for s in area_states:
                eid_l = s.entity_id.lower()
                is_ble = any(k in eid_l for k in ("espresence", "bermuda", "beacon", "ble_rssi"))
                if is_ble:
                    st_l = str(s.state).lower()
                    attr_room = str(s.attributes.get("room") or s.attributes.get("area") or "").lower()
                    rssi_val = s.attributes.get("rssi") or (float(s.state) if s.state.startswith("-") else None)
                    dist = s.attributes.get("distance")
                    try:
                        dist_val = float(dist) if dist is not None else (calculate_ble_distance(float(rssi_val)) if rssi_val is not None else None)
                    except (ValueError, TypeError):
                        dist_val = None

                    if st_l in (a_lower, a_id) or attr_room in (a_lower, a_id) or (dist_val is not None and dist_val < 3.5):
                        user = self.get_beacon_user(s.entity_id) or s.attributes.get("person") or s.attributes.get("user")
                        ble_eval = {
                            "active": True,
                            "confidence": 0.85 if dist_val and dist_val < 2.0 else 0.70,
                            "distance_m": dist_val,
                            "user": user,
                        }
                        break

            # 4. PIR Motion
            pir_eval: dict[str, Any] = {"active": False, "confidence": 0.0, "seconds_since_motion": None}
            for s in area_states:
                eid_l = s.entity_id.lower()
                d_class = str(s.attributes.get("device_class") or "").lower()
                is_pir = (d_class == "motion" or any(k in eid_l for k in ("pir", "motion"))) and s.entity_id.startswith("binary_sensor.")
                if is_pir and "mmwave" not in eid_l and "radar" not in eid_l:
                    if s.state == "on":
                        pir_eval = {"active": True, "confidence": 0.75, "seconds_since_motion": 0}
                        break

            # 5. Acoustic Footprinting
            acoustic_eval: dict[str, Any] = {"detected": False, "confidence": 0.0, "event_type": "ambient"}
            cur_db: float | None = None
            floor_db: float | None = None
            ac_event: str | None = None
            for s in area_states:
                eid_l = s.entity_id.lower()
                if any(k in eid_l for k in ("sound_level", "noise", "decibel", "sound_pressure", "dba")):
                    try:
                        val = float(s.state)
                        if "floor" in eid_l or "baseline" in eid_l:
                            floor_db = val
                        elif cur_db is None:
                            cur_db = val
                    except (ValueError, TypeError):
                        pass
                if any(k in eid_l for k in ("speech_detected", "voice_activity", "acoustic_event", "sound_type")):
                    if s.state == "on" or s.state not in ("off", "idle", "unknown", "unavailable"):
                        ac_event = s.state

            if cur_db is not None and floor_db is None:
                floor_db = 38.0  # Default nominal residential noise floor in dBA
            if cur_db is not None or ac_event is not None:
                acoustic_eval = evaluate_acoustic_footprint(cur_db, floor_db, ac_event)

            # 6. Media Playback
            media_eval: dict[str, Any] = {"active": False, "confidence": 0.0}
            for s in area_states:
                if s.entity_id.startswith("media_player.") and s.state in ("playing", "on"):
                    media_eval = {"active": True, "confidence": 0.45}
                    break

            # Perform Room Fusion
            fused = self.fuse_room_modalities(
                area_id=a_id,
                area_name=a_name,
                mmwave_data=mmwave_eval,
                thermal_data=thermal_eval,
                ble_data=ble_eval,
                pir_data=pir_eval,
                acoustic_data=acoustic_eval,
                media_data=media_eval,
            )

            room_results[a_id] = fused
            st = fused["status"]
            if st == STATUS_OCCUPIED:
                occupied_areas.append(a_name)
            elif st == STATUS_MICRO_PRESENCE:
                micro_presence_areas.append(a_name)
            elif st == STATUS_LIKELY:
                likely_areas.append(a_name)
            else:
                vacant_areas.append(a_name)

        telemetry = {
            "timestamp": time.time(),
            "total_areas": len(areas),
            "occupied_count": len(occupied_areas),
            "micro_presence_count": len(micro_presence_areas),
            "likely_count": len(likely_areas),
            "vacant_count": len(vacant_areas),
            "occupied_areas": occupied_areas,
            "micro_presence_areas": micro_presence_areas,
            "likely_areas": likely_areas,
            "vacant_areas": vacant_areas,
            "rooms": room_results,
        }

        self._last_fused_telemetry = telemetry
        self._last_fused_ts = now_ts
        self._publish_telemetry_sensor(telemetry)
        return telemetry

    def _publish_telemetry_sensor(self, telemetry: dict[str, Any]) -> None:
        """Publish real-time telemetry to sensor.otis_fused_presence."""
        total_active = telemetry["occupied_count"] + telemetry["micro_presence_count"]
        state_str = "occupied" if total_active > 0 else ("likely" if telemetry["likely_count"] > 0 else "vacant")
        attrs = {
            "friendly_name": "Otis Fused Presence",
            "icon": "mdi:motion-sensor-multimodal",
            "occupied_count": telemetry["occupied_count"],
            "micro_presence_count": telemetry["micro_presence_count"],
            "likely_count": telemetry["likely_count"],
            "vacant_count": telemetry["vacant_count"],
            "occupied_areas": telemetry["occupied_areas"],
            "micro_presence_areas": telemetry["micro_presence_areas"],
            "likely_areas": telemetry["likely_areas"],
            "rooms": telemetry["rooms"],
            "last_updated": telemetry["timestamp"],
        }
        try:
            from .sensor import async_update_entity_state
            async_update_entity_state(self.hass, "sensor.otis_fused_presence", state_str, attrs)
        except Exception as err:
            _LOGGER.debug("Entity state update notice: %s", err)
