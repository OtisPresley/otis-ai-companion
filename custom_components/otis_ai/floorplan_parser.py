"""Multimodal video walkthrough parser and vector SVG floor plan engine for Otis AI Companion."""
from __future__ import annotations

import asyncio
import base64
import functools
import html
import json
import logging
import math
import os
import re
import shutil
import time
from typing import Any
import urllib.request

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import CONF_GEMINI_API_KEY, DOMAIN
from .spatial_manager import (
    build_area_lookup_map,
    classify_area_entities,
    normalize_area_key,
    resolve_area_identifier,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "otis_ai_floorplan"
STORAGE_VERSION = 1
DEFAULT_OUTPUT_SVG_PATH = ".storage/otis_ai/media/otis_floorplan.svg"

# Area keywords for floor & outdoor classification
OUTDOOR_KEYWORDS = {
    "yard", "backyard", "frontyard", "pool", "patio", "garden", "driveway", 
    "deck", "porch", "exterior", "perimeter", "lawn", "courtyard"
}

UPPER_KEYWORDS = {
    "upper", "upstairs", "second", "2nd", "attic", "loft", "balcony", 
    "master", "master_bath", "theater", "gym",
    "office", "laundry", "guest_room", "guest_bedroom", "hallway"
}

# Floor plan layouts are dynamically synthesized from Home Assistant areas and walkthrough features.
# Kept as empty dicts for backwards compatibility with callers/tests.
GROUND_AND_OUTDOOR_BLUEPRINT: dict[str, dict[str, Any]] = {}
UPPER_FLOOR_BLUEPRINT: dict[str, dict[str, Any]] = {}


def classify_area_zone(area_key: str, area_name: str) -> str:
    """Classify an area into 'outdoor', 'upper', or 'main' floor zone."""
    key = normalize_area_key(area_key)
    name = (area_name or "").lower()

    if any(k in key or k in name for k in OUTDOOR_KEYWORDS):
        return "outdoor"
    if any(k in key or k in name for k in UPPER_KEYWORDS):
        return "upper"
    return "main"


def detect_door_orientation(
    room: dict[str, Any],
    side: str,
    pos: float,
    length: float,
    all_rooms: list[dict[str, Any]] | None = None,
) -> str:
    """Automatically detect architectural door swing orientation (inward/outward, left/right hinge)."""
    rx = float(room.get("x", 0))
    ry = float(room.get("y", 0))
    rw = float(room.get("width", 200))
    rh = float(room.get("height", 140))
    rzone = room.get("zone", "main")
    rid = room.get("id", "")

    # Exterior boundaries and outdoor areas
    is_outward = False
    if room.get("is_water") or rzone == "outdoor":
        is_outward = False
    elif side == "top" and "mudroom" in rid:
        # Mudroom door opening out to backyard
        is_outward = True
    elif side == "bottom" and (ry + rh) >= 550 and rzone == "main":
        # Front door on main floor entrance swings inward into foyer
        is_outward = False

    # Standard corner clearance hinge calculation:
    # Hinge on the side closest to adjacent perpendicular corner wall
    if side in ("top", "bottom"):
        dist_to_left = pos - rx
        dist_to_right = (rx + rw) - (pos + length)
        hinge = "left" if dist_to_left <= dist_to_right else "right"
    else:
        dist_to_top = pos - ry
        dist_to_bottom = (ry + rh) - (pos + length)
        hinge = "top" if dist_to_top <= dist_to_bottom else "bottom"

    prefix = "outward" if is_outward else "inward"
    return f"{prefix}-{hinge}"


def normalize_door_spec(
    door: Any,
    room: dict[str, Any] | None = None,
    all_rooms: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Normalize a door definition (tuple or dict) into a consistent schema with detected orientation."""
    if isinstance(door, dict):
        side = str(door.get("side", "bottom")).lower()
        pos = float(door.get("pos", 0))
        length = float(door.get("length", 36))
        label = str(door.get("label", "Door"))
        orientation = door.get("orientation")
        door_type = str(door.get("type", "swing")).lower()
    elif isinstance(door, (list, tuple)):
        side = str(door[0]).lower()
        pos = float(door[1])
        length = float(door[2])
        label = str(door[3]) if len(door) > 3 else "Door"
        orientation = str(door[4]) if len(door) > 4 else None
        door_type = str(door[5]) if len(door) > 5 else "swing"
    else:
        return {}

    lbl_lower = label.lower()
    if "garage" in lbl_lower:
        door_type = "garage"
    elif "sliding" in lbl_lower or "pocket" in lbl_lower:
        door_type = "sliding"
    elif "open" in lbl_lower or "cased" in lbl_lower or orientation in ("open", "cased"):
        door_type = "cased"

    if orientation in ("cased", "open"):
        door_type = "cased"
        orientation = None
    elif orientation in ("garage",):
        door_type = "garage"
        orientation = None

    if not orientation and room and door_type == "swing":
        orientation = detect_door_orientation(room, side, pos, length, all_rooms)
    elif not orientation and door_type == "swing":
        orientation = "inward-left"

    return {
        "side": side,
        "pos": pos,
        "length": length,
        "label": label,
        "orientation": orientation,
        "door_type": door_type,
    }


def normalize_window_spec(
    window: Any,
    room: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize a window definition (tuple or dict) into a consistent schema."""
    if isinstance(window, dict):
        side = str(window.get("side", "top")).lower()
        pos = float(window.get("pos", 0))
        length = float(window.get("length", 48))
        label = str(window.get("label", "Window"))
        orientation = str(window.get("orientation", "exterior"))
        window_type = str(window.get("type", "standard")).lower()
    elif isinstance(window, (list, tuple)):
        side = str(window[0]).lower()
        pos = float(window[1])
        length = float(window[2])
        label = str(window[3]) if len(window) > 3 else "Window"
        orientation = str(window[4]) if len(window) > 4 else "exterior"
        window_type = str(window[5]) if len(window) > 5 else "standard"
    else:
        return {}

    return {
        "side": side,
        "pos": pos,
        "length": length,
        "label": label,
        "orientation": orientation,
        "window_type": window_type,
    }


def detect_exterior_windows(
    room: dict[str, Any],
    all_rooms: list[dict[str, Any]],
    min_wall_span: float = 70.0,
) -> list[dict[str, Any]]:
    """Automatically detect exterior walls and place oriented architectural window symbols."""
    rx = float(room.get("x", 0))
    ry = float(room.get("y", 0))
    rw = float(room.get("width", 200))
    rh = float(room.get("height", 140))
    rzone = room.get("zone", "main")
    rid = room.get("id", "")

    if rzone == "outdoor" or room.get("is_water") or "hallway" in rid:
        return []

    if room.get("windows"):
        return [normalize_window_spec(w, room) for w in room["windows"]]

    windows: list[dict[str, Any]] = []
    existing_doors = [normalize_door_spec(d, room) for d in room.get("doors", [])]

    def _has_door_conflict(side: str, seg_pos: float, seg_len: float) -> bool:
        for d in existing_doors:
            if d.get("side") == side:
                d_pos = d.get("pos", 0)
                d_len = d.get("length", 36)
                if not (seg_pos + seg_len < d_pos - 8 or seg_pos > d_pos + d_len + 8):
                    return True
        return False

    # 1. Top wall
    top_shared = any(
        other.get("id") != rid
        and other.get("zone") != "outdoor"
        and abs((other.get("y", 0) + other.get("height", 0)) - ry) < 15
        and not (other.get("x", 0) + other.get("width", 0) <= rx or other.get("x", 0) >= rx + rw)
        for other in all_rooms
    )
    if not top_shared and rw >= min_wall_span:
        w_len = min(60.0, rw * 0.4)
        w_pos = rx + (rw - w_len) / 2.0
        if not _has_door_conflict("top", w_pos, w_len):
            windows.append({
                "side": "top",
                "pos": w_pos,
                "length": w_len,
                "label": f"{room.get('name', rid)} North Window",
                "orientation": "exterior",
                "window_type": "standard",
            })

    # 2. Bottom wall
    bottom_shared = any(
        other.get("id") != rid
        and other.get("zone") != "outdoor"
        and abs(other.get("y", 0) - (ry + rh)) < 15
        and not (other.get("x", 0) + other.get("width", 0) <= rx or other.get("x", 0) >= rx + rw)
        for other in all_rooms
    )
    if not bottom_shared and rw >= min_wall_span:
        w_len = min(60.0, rw * 0.4)
        w_pos = rx + (rw - w_len) / 2.0
        if not _has_door_conflict("bottom", w_pos, w_len):
            windows.append({
                "side": "bottom",
                "pos": w_pos,
                "length": w_len,
                "label": f"{room.get('name', rid)} South Window",
                "orientation": "exterior",
                "window_type": "standard",
            })

    # 3. Left wall
    left_shared = any(
        other.get("id") != rid
        and other.get("zone") != "outdoor"
        and abs((other.get("x", 0) + other.get("width", 0)) - rx) < 15
        and not (other.get("y", 0) + other.get("height", 0) <= ry or other.get("y", 0) >= ry + rh)
        for other in all_rooms
    )
    if not left_shared and rh >= min_wall_span:
        w_len = min(50.0, rh * 0.4)
        w_pos = ry + (rh - w_len) / 2.0
        if not _has_door_conflict("left", w_pos, w_len):
            windows.append({
                "side": "left",
                "pos": w_pos,
                "length": w_len,
                "label": f"{room.get('name', rid)} West Window",
                "orientation": "exterior",
                "window_type": "standard",
            })

    # 4. Right wall
    right_shared = any(
        other.get("id") != rid
        and other.get("zone") != "outdoor"
        and abs(other.get("y", 0) - (rx + rw)) < 15
        and not (other.get("y", 0) + other.get("height", 0) <= ry or other.get("y", 0) >= ry + rh)
        for other in all_rooms
    )
    if not right_shared and rh >= min_wall_span:
        w_len = min(50.0, rh * 0.4)
        w_pos = ry + (rh - w_len) / 2.0
        if not _has_door_conflict("right", w_pos, w_len):
            windows.append({
                "side": "right",
                "pos": w_pos,
                "length": w_len,
                "label": f"{room.get('name', rid)} East Window",
                "orientation": "exterior",
                "window_type": "standard",
            })

    return windows


def find_room_group_span(svg: str, area_id: str) -> tuple[int, int, str, str] | None:
    """Find the start index, end index, open tag header, and inner markup for a room group."""
    open_re = re.compile(
        rf'<g\b[^>]*class="[^"]*room-group[^"]*"[^>]*data-area-id="{re.escape(area_id)}"[^>]*>'
    )
    m = open_re.search(svg)
    if not m:
        open_re_alt = re.compile(
            rf'<g\b[^>]*data-area-id="{re.escape(area_id)}"[^>]*class="[^"]*room-group[^"]*"[^>]*>'
        )
        m = open_re_alt.search(svg)
        if not m:
            return None

    start_idx = m.start()
    header_end = m.end()
    header = svg[start_idx:header_end]

    depth = 1
    pos = header_end
    tag_re = re.compile(r'(<g\b|</g>)')
    while depth > 0:
        tag_m = tag_re.search(svg, pos)
        if not tag_m:
            break
        if tag_m.group(1).startswith('<g'):
            depth += 1
        else:
            depth -= 1
        pos = tag_m.end()

    if depth == 0:
        end_idx = pos
        inner = svg[header_end:end_idx - 4]
        return start_idx, end_idx, header, inner
    return None


def sanitize_corrupted_svg_text(svg: str) -> str:
    """Sanitize corrupted <text> elements where attributes leaked into inner content."""
    def _fix_text(m: re.Match) -> str:
        tag_str = m.group(0)
        cls_name = m.group(1)
        content = m.group(2)
        xm = re.search(r'x="([0-9.]+)"', tag_str)
        ym = re.search(r'y="([0-9.]+)"', tag_str)
        x_val = xm.group(1) if xm else "40"
        y_val = ym.group(1) if ym else "40"
        clean_txt = re.sub(r'^(?:\s*(?:x|y)="[^"]*"[>\s]*)+', '', content).strip()
        return f'<text x="{x_val}" y="{y_val}" class="{cls_name}">{clean_txt}</text>'

    return re.sub(
        r'<text\b[^>]*class="([^"]*(?:room-header|room-label|subzone-pill)[^"]*)"[^>]*>(.*?)</text>',
        _fix_text,
        svg,
    )


def select_intelligent_room_controls(
    room_ents: list[dict[str, Any]],
    valid_eids: set[str] | None = None,
    area_name: str = "",
    area_id: str = "",
    max_controls: int = 3,
    devices_map: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Select up to max_controls high-utility, diverse controllable devices for a room."""
    reject_keywords = (
        "cleaning", "customized_cleaning", "clean_record", "mop", "water_box",
        "child_lock", "dnd", "carpet_boost", "gentle_mode", "auto_empty", "dock_led",
        "auto_dust_collecting", "cleaning_sequence", "resume_cleaning", "multi_floor_map",
        "sleep_pause", "super_sleep", "sleep_number", "responsive_air",
        "pause_mode", "smart_sleeper", "bed_presence", "sleep_tracker",
        "ice_maker", "ice_plus", "express_freeze", "sabbath", "door_alarm",
        "filter_reset", "fresh_air", "water_filter", "air_filter",
        "poe", "port_", "switch_port", "status_led", "led_ring", "night_vision",
        "screen_saver", "auto_update", "cloud_connection", "mesh_reboot",
        "restart", "reboot", "tamper", "pairing", "update", "firmware",
        "mute", "do_not_disturb", "beep", "buzzer", "indicator", "identify",
        "detect", "motion", "recordings", "snapshots", "review_alerts", "review_detections",
        "infra_red", "record_audio", "siren_on_event", "email_on_event", "ftp_upload",
        "push_notifications", "privacy_mode", "button_sound", "no_command_mode",
        "pure_direct", "party_mode", "enhancer", "amazon_kids", "_led",
    )
    noisy_switch_platforms = {"frigate", "reolink", "snmp_switch_manager", "unifi", "alexa_media"}

    native_media_platforms = {
        "androidtv_remote", "androidtv", "apple_tv", "webostv", "samsungtv",
        "braviatv", "roku", "lg_netcast", "firetv", "yamaha_musiccast",
        "yamaha_ynca", "denonavr", "onkyo", "marantz", "sonos", "heos",
        "bluesound", "kef", "control4_mediaplayer",
    }
    secondary_media_platforms = {"cast", "airplay", "plex"}
    assistant_media_platforms = {"alexa_media", "browser_mod"}
    wrapper_media_platforms = {"music_assistant", "dlna_dmr", "upnp"}

    domain_candidates: dict[str, list[tuple[float, dict[str, Any]]]] = {
        "light": [],
        "media_player": [],
        "fan": [],
        "switch": [],
        "cover": [],
        "lock": [],
        "climate": [],
        "vacuum": [],
    }

    aname_norm = area_name.lower()

    for e in room_ents:
        eid = e.get("entity_id", "")
        if not eid or (valid_eids and eid not in valid_eids):
            continue
        if e.get("entity_category") in ("config", "diagnostic"):
            continue
        if e.get("disabled_by") or e.get("hidden_by"):
            continue

        dom = e.get("domain") or (eid.split(".")[0] if "." in eid else "")
        if dom not in domain_candidates:
            continue

        fname = (e.get("name") or e.get("friendly_name") or eid).lower()
        ename_norm = eid.lower()
        plat = str(e.get("platform") or "").lower()
        if dom == "switch" and plat in noisy_switch_platforms:
            continue
        if any(rk in ename_norm or rk in fname for rk in reject_keywords):
            continue

        dev_id = e.get("device_id")
        dev_info = devices_map.get(dev_id) if isinstance(devices_map, dict) and dev_id else None
        dev_name = str((dev_info.get("name") if isinstance(dev_info, dict) else None) or e.get("device_name") or "")
        dev_model = str((dev_info.get("model") if isinstance(dev_info, dict) else None) or "").lower()

        base_score = 0.0
        if dom == "light":
            base_score = 100.0
            if aname_norm and aname_norm in fname:
                base_score += 40.0
            if any(k in fname or k in ename_norm for k in ("main", "ceiling", "overhead", "chandelier", "recessed", "downlight", "island", "table")):
                base_score += 30.0
            if any(k in fname or k in ename_norm for k in ("accent", "cabinet", "closet", "nightlight", "strip", "bias", "under_cabinet", "counter")):
                base_score -= 30.0
        elif dom == "media_player":
            base_score = 90.0
            if plat in native_media_platforms:
                base_score += 80.0
            elif plat in secondary_media_platforms:
                base_score += 20.0
            elif plat in assistant_media_platforms:
                base_score -= 40.0
            elif plat in wrapper_media_platforms:
                base_score -= 80.0
            if any(k in dev_model for k in ("dashboard display", "renderer", "universal group")):
                base_score -= 60.0
            if any(k in fname or k in ename_norm or k in dev_name.lower() for k in ("tv", "television", "apple_tv", "shield", "roku", "soundbar", "sonos", "receiver", "avr", "stereo")):
                base_score += 35.0
            if plat == "control4_mediaplayer":
                base_score += 20.0
        elif dom == "fan":
            base_score = 85.0
            if any(k in fname or k in ename_norm for k in ("ceiling", "fan", "exhaust", "vent")):
                base_score += 25.0
        elif dom == "climate":
            base_score = 80.0
            if any(k in fname or k in ename_norm for k in ("thermostat", "hvac", "ac", "furnace", "pool")):
                base_score += 20.0
        elif dom == "cover":
            base_score = 75.0
            if any(k in fname or k in ename_norm for k in ("garage", "shades", "blinds", "curtain", "door")):
                base_score += 25.0
        elif dom == "lock":
            base_score = 75.0
            if any(k in fname or k in ename_norm for k in ("front", "garage", "deadbolt", "entry")):
                base_score += 25.0
        elif dom == "switch":
            base_score = 60.0
            if any(k in fname or k in ename_norm for k in ("fan", "exhaust", "vent", "bath_fan", "fireplace", "heater", "fountain", "pump", "pool", "disposal", "lamp")):
                base_score += 35.0
            elif any(k in fname or k in ename_norm for k in ("plug", "outlet", "switch")):
                base_score += 15.0
        elif dom == "vacuum":
            base_score = 65.0

        raw_dedup = dev_name or (e.get("name") or e.get("friendly_name") or eid.split(".", 1)[-1])
        dedup_norm = re.sub(r"[^a-z0-9]+", " ", raw_dedup.lower()).strip()
        dedup_norm = re.sub(r"\s+\d+$", "", dedup_norm).strip()
        domain_candidates[dom].append((base_score, {
            "entity": eid,
            "domain": dom,
            "name": e.get("name") or e.get("friendly_name") or eid,
            "device_id": dev_id,
            "dedup_key": dedup_norm or eid,
        }))

    for dom in domain_candidates:
        domain_candidates[dom].sort(key=lambda x: x[0], reverse=True)

    # Deduplicate media_player entities that represent the same physical device across integrations
    if domain_candidates["media_player"]:
        deduped_media: list[tuple[float, dict[str, Any]]] = []
        seen_dev_ids: set[str] = set()
        seen_media_keys: set[str] = set()
        for score, cand in domain_candidates["media_player"]:
            did = cand.get("device_id")
            dkey = cand.get("dedup_key") or cand["entity"]
            if did and did in seen_dev_ids:
                continue
            if dkey in seen_media_keys:
                continue
            if did:
                seen_dev_ids.add(did)
            seen_media_keys.add(dkey)
            deduped_media.append((score, cand))
        domain_candidates["media_player"] = deduped_media

    selected: list[dict[str, Any]] = []
    cfg_map = {
        "light": {"color": "#38bdf8", "action": "toggle"},
        "switch": {"color": "#a855f7", "action": "toggle"},
        "media_player": {"color": "#ec4899", "action": "more-info"},
        "fan": {"color": "#06b6d4", "action": "toggle"},
        "climate": {"color": "#f97316", "action": "more-info"},
        "cover": {"color": "#eab308", "action": "toggle"},
        "lock": {"color": "#10b981", "action": "more-info"},
        "vacuum": {"color": "#8b5cf6", "action": "more-info"},
    }

    if domain_candidates["light"]:
        best = domain_candidates["light"].pop(0)[1]
        selected.append({"entity": best["entity"], "color": cfg_map["light"]["color"], "action": cfg_map["light"]["action"]})

    entertainment_or_comfort: list[tuple[float, dict[str, Any]]] = []
    for key in ("media_player", "fan", "climate"):
        if domain_candidates[key]:
            entertainment_or_comfort.append(domain_candidates[key][0])

    if entertainment_or_comfort:
        entertainment_or_comfort.sort(key=lambda x: x[0], reverse=True)
        best_ec = entertainment_or_comfort[0][1]
        domain_candidates[best_ec["domain"]] = [
            c for c in domain_candidates[best_ec["domain"]] if c[1]["entity"] != best_ec["entity"]
        ]
        selected.append({
            "entity": best_ec["entity"],
            "color": cfg_map[best_ec["domain"]]["color"],
            "action": cfg_map[best_ec["domain"]]["action"],
        })

    remaining_candidates: list[tuple[float, dict[str, Any]]] = []
    for cands in domain_candidates.values():
        remaining_candidates.extend(cands)
    remaining_candidates.sort(key=lambda x: x[0], reverse=True)

    while len(selected) < max_controls and remaining_candidates:
        media_selected = sum(1 for s in selected if s["entity"].startswith("media_player."))
        has_non_media_left = any(c[1]["domain"] != "media_player" for c in remaining_candidates)
        if media_selected >= 2 and has_non_media_left:
            idx = next((i for i, c in enumerate(remaining_candidates) if c[1]["domain"] != "media_player"), 0)
            cand = remaining_candidates.pop(idx)[1]
        else:
            cand = remaining_candidates.pop(0)[1]
        cdom = cand["domain"]
        selected.append({
            "entity": cand["entity"],
            "color": cfg_map[cdom]["color"],
            "action": cfg_map[cdom]["action"],
        })

    return selected


def compute_room_center_pin_positions(
    rx: float,
    ry: float,
    rw: float,
    rh: float,
    count: int = 0,
    sub_zones_count: int = 0,
    has_container: bool = False,
) -> tuple[int, list[tuple[float, float]]]:
    """Compute non-crowded room pin capacity and centered (x, y) positions avoiding room text.

    Returns (max_pins, positions) where positions has min(count, max_pins) coordinates
    situated outward from the center of the text-free interior of the room.
    """
    pin_spacing_x = 34.0
    pin_spacing_y = 32.0

    # Room header sits at y+22 (or y+34 inside container), subzone-pills stack 16px each below it
    header_offset = 34.0 if has_container else 22.0
    text_bottom_y = ry + header_offset + (sub_zones_count * 16.0) + 18.0
    if text_bottom_y > ry + rh - 24.0 and rw >= 360.0:
        # Wide, short rooms (e.g. Hallway, Frontyard): left-aligned text occupies only the left ~240px,
        # so place pins vertically centered in the open right-of-text interior instead of overflowing the bottom.
        safe_left = max(rx + 22.0, min(rx + rw * 0.35, rx + 240.0))
        safe_right = max(safe_left + 16.0, rx + rw - 22.0)
        safe_top = ry + 18.0
        safe_bottom = max(safe_top, ry + rh - 18.0)
    else:
        safe_left = rx + 22.0
        safe_right = max(safe_left + 16.0, rx + rw - 22.0)
        safe_bottom = max(ry + 24.0, ry + rh - 18.0)
        safe_top = min(safe_bottom, max(ry + 40.0, text_bottom_y))

    usable_w = max(0.0, safe_right - safe_left)
    usable_h = max(0.0, safe_bottom - safe_top)

    max_cols = max(1, int(usable_w // pin_spacing_x))
    max_rows = max(1, int(usable_h // pin_spacing_y))
    max_pins = max(1, min(8, max_cols * max_rows))

    n = min(max(0, count), max_pins)
    if n == 0:
        return max_pins, []

    center_x = (safe_left + safe_right) / 2.0
    center_y = (safe_top + safe_bottom) / 2.0

    if n <= max_cols and (n < 4 or max_rows == 1 or usable_w >= n * pin_spacing_x):
        cols = n
    else:
        cols = min(max_cols, max(2, math.ceil(n / max_rows)))
        if max_rows >= 2 and n >= 4:
            cols = min(max_cols, math.ceil(n / 2))
    rows = math.ceil(n / cols)

    positions: list[tuple[float, float]] = []
    for idx in range(n):
        row = idx // cols
        col = idx % cols
        row_items = cols if row < rows - 1 else (n - row * cols)
        px = center_x + (col - (row_items - 1) / 2.0) * pin_spacing_x
        py = center_y + (row - (rows - 1) / 2.0) * pin_spacing_y
        px = round(max(safe_left, min(safe_right, px)), 1)
        py = round(max(safe_top, min(safe_bottom, py)), 1)
        positions.append((px, py))

    return max_pins, positions


class FloorplanParser:
    """Parses video walkthroughs, audio callouts, and topological graphs into interactive SVG floorplans."""

    def __init__(self, hass: HomeAssistant, storage_key: str = STORAGE_KEY) -> None:
        """Initialize the floorplan parser."""
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, storage_key)
        self._metadata: dict[str, Any] = {}
        self._initialized: bool = False
        self._cached_svg_room_bounds: dict[str, dict[str, float]] = {}
        self._floorplan_exists: bool = False
        self._regen_progress: dict[str, Any] = {
            "active": False,
            "percent": 0,
            "stage": "Idle",
            "discovered_areas": [],
            "error": None,
        }

    def get_regen_progress(self) -> dict[str, Any]:
        """Return live background floorplan regeneration progress."""
        return dict(self._regen_progress)

    def _set_regen_progress(
        self,
        percent: int,
        stage: str,
        active: bool = True,
        discovered_areas: list[str] | None = None,
        error: str | None = None,
    ) -> None:
        """Update live background floorplan regeneration progress."""
        self._regen_progress = {
            "active": active,
            "percent": max(0, min(100, int(percent))),
            "stage": stage,
            "discovered_areas": list(discovered_areas) if discovered_areas is not None else list(self._regen_progress.get("discovered_areas") or []),
            "error": error,
        }

    async def _async_run_in_executor(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute a blocking function in the Home Assistant executor pool."""
        target = func if not kwargs else functools.partial(func, *args, **kwargs)
        actual_args = args if not kwargs else ()
        if hasattr(self.hass, "async_add_executor_job"):
            try:
                res = self.hass.async_add_executor_job(target, *actual_args)
                if asyncio.iscoroutine(res) or isinstance(res, asyncio.Future):
                    return await res
                elif res is not None and not hasattr(res, "_mock_return_value"):
                    return res
            except Exception:
                pass
        try:
            return await asyncio.to_thread(target, *actual_args)
        except Exception:
            return target(*actual_args)

    def _parse_svg_room_bounds_sync(self, svg_file_path: str) -> dict[str, dict[str, float]]:
        """Parse room coordinates from floorplan SVG synchronously in executor."""
        bounds: dict[str, dict[str, float]] = {}
        if not isinstance(svg_file_path, str) or not os.path.exists(svg_file_path):
            self._floorplan_exists = False
            return bounds
        self._floorplan_exists = True
        try:
            with open(svg_file_path, encoding="utf-8") as svg_f:
                svg_txt = svg_f.read()
            if not isinstance(svg_txt, str):
                return bounds
            for m in re.finditer(
                r'<g\b[^>]*class="[^"]*room-group[^"]*"[^>]*data-area-id="([^"]*)"[^>]*>[\s\S]*?<rect\b[^>]*x="([0-9.]+)"\s+y="([0-9.]+)"\s+width="([0-9.]+)"\s+height="([0-9.]+)"',
                svg_txt,
            ):
                aid_svg = m.group(1)
                z_m = re.search(r'\bdata-zone="([^"]*)"', m.group(0))
                zone_svg = z_m.group(1) if z_m else "main"
                bounds[aid_svg] = {
                    "id": aid_svg,
                    "zone": zone_svg,
                    "x": float(m.group(2)),
                    "y": float(m.group(3)),
                    "width": float(m.group(4)),
                    "height": float(m.group(5)),
                }
        except Exception as err:
            _LOGGER.debug("Error parsing SVG room bounds: %s", err)
        return bounds

    def _sanitize_svg_path(self, svg_relative_path: str | None) -> str:
        """Sanitize and confine SVG output path strictly to managed media storage."""
        if not svg_relative_path:
            return DEFAULT_OUTPUT_SVG_PATH
        cleaned = os.path.normpath(str(svg_relative_path))
        # Prevent directory traversal and prevent writing to www
        if ".." in cleaned or "www" in cleaned.split(os.sep):
            _LOGGER.warning(
                "Disallowed floor plan path '%s'; confining to managed storage",
                svg_relative_path,
            )
            return DEFAULT_OUTPUT_SVG_PATH
        return cleaned

    async def async_refresh_svg_cache(self, svg_relative_path: str = DEFAULT_OUTPUT_SVG_PATH) -> None:
        """Asynchronously refresh cached SVG room bounds in executor to avoid blocking event loop."""
        svg_relative_path = self._sanitize_svg_path(svg_relative_path)
        if hasattr(self.hass, "config") and hasattr(self.hass.config, "path"):
            full_path = self.hass.config.path(svg_relative_path)
        else:
            full_path = svg_relative_path
        if not isinstance(full_path, str):
            self._cached_svg_room_bounds = {}
            return
        if hasattr(self.hass, "async_add_executor_job"):
            res = self.hass.async_add_executor_job(
                self._parse_svg_room_bounds_sync, full_path
            )
            if hasattr(res, "__await__"):
                self._cached_svg_room_bounds = await res
            else:
                self._cached_svg_room_bounds = res
        else:
            self._cached_svg_room_bounds = self._parse_svg_room_bounds_sync(full_path)

    async def async_load(self) -> dict[str, Any]:
        """Load stored floorplan metadata."""
        if hasattr(self._store, "async_load"):
            try:
                res = self._store.async_load()
                if asyncio.iscoroutine(res) or isinstance(res, asyncio.Future):
                    data = await res
                elif isinstance(res, dict):
                    data = res
                else:
                    data = None
                if data and isinstance(data, dict):
                    self._metadata = data
            except Exception:
                pass
        self._initialized = True
        svg_p = self._metadata.get("svg_path") or DEFAULT_OUTPUT_SVG_PATH
        await self.async_refresh_svg_cache(svg_p)
        return self._metadata

    async def async_save_metadata(self, metadata: dict[str, Any]) -> None:
        """Persist floorplan metadata to storage."""
        self._metadata = metadata
        if hasattr(self._store, "async_save"):
            try:
                res = self._store.async_save(metadata)
                if asyncio.iscoroutine(res) or isinstance(res, asyncio.Future):
                    await res
            except Exception:
                pass

    def has_walkthrough(self) -> bool:
        """Check if a video walkthrough has been completed."""
        return bool(self._metadata.get("walkthrough_completed", False))

    def _read_svg_content_sync(self, full_path: str) -> str | None:
        """Read SVG content synchronously in executor."""
        if not os.path.isfile(full_path):
            return None
        try:
            with open(full_path, encoding="utf-8") as f:
                return f.read()
        except Exception as err:
            _LOGGER.debug("Could not read floorplan SVG content: %s", err)
            return None

    async def async_get_svg_content(self, svg_relative_path: str = DEFAULT_OUTPUT_SVG_PATH) -> str | None:
        """Asynchronously return raw SVG content from executor."""
        if hasattr(self.hass, "config") and hasattr(self.hass.config, "path"):
            full_path = self.hass.config.path(svg_relative_path)
        else:
            full_path = svg_relative_path
        return await self._async_run_in_executor(self._read_svg_content_sync, full_path)

    def floorplan_exists(self) -> bool:
        """Check if an interactive floorplan SVG already exists in www/."""
        if self._floorplan_exists or bool(self._cached_svg_room_bounds):
            return True
        if hasattr(self.hass, "config") and hasattr(self.hass.config, "path"):
            full_path = self.hass.config.path(DEFAULT_OUTPUT_SVG_PATH)
            try:
                asyncio.get_running_loop()
                return self._floorplan_exists
            except RuntimeError:
                return os.path.exists(full_path)
        return False

    def get_lovelace_yaml(self) -> str | None:
        """Return cached lovelace card YAML if available."""
        return self._metadata.get("lovelace_yaml")

    def cleanup_previous_uploads(self, upload_dir: str) -> int:
        """Remove any previously uploaded walkthrough video or audio files to conserve disk space."""
        if not os.path.isdir(upload_dir):
            return 0
        removed = 0
        for fname in os.listdir(upload_dir):
            if fname.startswith("walkthrough_upload") or fname.startswith("walkthrough_audio"):
                fpath = os.path.join(upload_dir, fname)
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                        removed += 1
                    except Exception as err:
                        _LOGGER.warning("Could not remove old walkthrough file %s: %s", fpath, err)
        if removed:
            _LOGGER.info("Cleaned up %d previous walkthrough file(s) from %s", removed, upload_dir)
        return removed

    async def async_extract_audio_from_video(self, video_path: str, output_wav_path: str) -> bool:
        """Extract a 16kHz mono audio track from a walkthrough video using ffmpeg."""
        if not await self._async_run_in_executor(os.path.exists, video_path):
            _LOGGER.error("Walkthrough video file not found: %s", video_path)
            return False

        ffmpeg_bin = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
        if not await self._async_run_in_executor(os.path.exists, ffmpeg_bin):
            _LOGGER.warning("ffmpeg binary not found in container path. Skipping audio extraction.")
            return False

        if output_wav_path.lower().endswith(".mp3"):
            cmd = [
                ffmpeg_bin,
                "-i", video_path,
                "-vn",
                "-acodec", "libmp3lame",
                "-ac", "1",
                "-ar", "16000",
                "-b:a", "32k",
                "-y",
                output_wav_path,
            ]
        else:
            cmd = [
                ffmpeg_bin,
                "-i", video_path,
                "-vn",
                "-acodec", "pcm_s16le",
                "-ac", "1",
                "-ar", "16000",
                "-y",
                output_wav_path,
            ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode == 0 and await self._async_run_in_executor(os.path.exists, output_wav_path):
                _LOGGER.info("Successfully extracted walkthrough audio to %s", output_wav_path)
                return True
            else:
                _LOGGER.warning("ffmpeg audio extraction failed (code %s): %s", process.returncode, stderr.decode("utf-8", "ignore")[-300:])
                return False
        except Exception as err:
            _LOGGER.error("Error executing ffmpeg subprocess: %s", err)
            return False

    async def async_extract_audio_from_videos(
        self,
        video_paths: list[str],
        output_dir: str,
        preferred_format: str = "mp3",
    ) -> list[str]:
        """Extract audio tracks sequentially from a list of walkthrough video clips."""
        extracted_paths: list[str] = []
        await self._async_run_in_executor(os.makedirs, output_dir, exist_ok=True)
        for idx, vpath in enumerate(video_paths, start=1):
            if not await self._async_run_in_executor(os.path.exists, vpath):
                _LOGGER.warning("Video clip %s not found. Skipping.", vpath)
                continue
            ext = preferred_format.lower().lstrip(".")
            target_name = f"walkthrough_audio.{ext}" if idx == 1 else f"walkthrough_audio_{idx}.{ext}"
            target_path = os.path.join(output_dir, target_name)
            success = await self.async_extract_audio_from_video(vpath, target_path)
            if not success and ext == "mp3":
                target_path = os.path.join(
                    output_dir,
                    "walkthrough_audio.wav" if idx == 1 else f"walkthrough_audio_{idx}.wav",
                )
                success = await self.async_extract_audio_from_video(vpath, target_path)
            if success and await self._async_run_in_executor(os.path.exists, target_path):
                extracted_paths.append(target_path)
        return extracted_paths

    async def async_concatenate_audio_clips(
        self, audio_paths: list[str], output_path: str
    ) -> bool:
        """Concatenate multiple sequential audio clips into a unified audio track using ffmpeg."""
        if not audio_paths:
            return False
        if len(audio_paths) == 1:
            try:
                def _copy_single() -> None:
                    if os.path.abspath(audio_paths[0]) != os.path.abspath(output_path):
                        shutil.copyfile(audio_paths[0], output_path)

                await self._async_run_in_executor(_copy_single)
                return True
            except Exception as err:
                _LOGGER.warning("Could not copy single audio track to %s: %s", output_path, err)
                return False

        ffmpeg_bin = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
        if not await self._async_run_in_executor(os.path.exists, ffmpeg_bin):
            _LOGGER.warning("ffmpeg binary not found. Skipping audio clip concatenation.")
            return False

        list_file = os.path.join(os.path.dirname(output_path), f"concat_manifest_{int(time.time())}.txt")
        try:
            def _write_manifest() -> None:
                with open(list_file, "w", encoding="utf-8") as f:
                    for a_path in audio_paths:
                        escaped = a_path.replace("'", "'\\''")
                        f.write(f"file '{escaped}'\n")

            await self._async_run_in_executor(_write_manifest)

            cmd = [
                ffmpeg_bin,
                "-f", "concat",
                "-safe", "0",
                "-i", list_file,
                "-c", "copy",
                "-y",
                output_path,
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode == 0 and await self._async_run_in_executor(os.path.exists, output_path):
                _LOGGER.info("Successfully concatenated %d audio clips into %s", len(audio_paths), output_path)
                return True
            else:
                _LOGGER.debug("Direct concat copy failed, attempting re-encode concat: %s", stderr.decode("utf-8", "ignore")[-200:])
                filter_inputs = "".join(f"[{i}:a]" for i in range(len(audio_paths)))
                cmd_reencode = [ffmpeg_bin]
                for a_p in audio_paths:
                    cmd_reencode.extend(["-i", a_p])
                cmd_reencode.extend([
                    "-filter_complex", f"{filter_inputs}concat=n={len(audio_paths)}:v=0:a=1[outa]",
                    "-map", "[outa]",
                    "-y",
                    output_path,
                ])
                proc2 = await asyncio.create_subprocess_exec(
                    *cmd_reencode,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc2.communicate()
                return proc2.returncode == 0 and await self._async_run_in_executor(os.path.exists, output_path)
        except Exception as err:
            _LOGGER.warning("ffmpeg concatenation exception: %s", err)
            return False
        finally:
            def _cleanup_manifest() -> None:
                if os.path.exists(list_file):
                    try:
                        os.remove(list_file)
                    except Exception:
                        pass

            await self._async_run_in_executor(_cleanup_manifest)

    def _get_gemini_credentials(self) -> tuple[str | None, str]:
        """Retrieve Gemini API key from Otis AI's own config entry or options."""
        model = "models/gemini-2.5-flash"
        api_key = None
        if hasattr(self.hass, "data") and isinstance(self.hass.data, dict):
            otis_data = self.hass.data.get(DOMAIN, {})
            if isinstance(otis_data, dict):
                for _k, v in otis_data.items():
                    if isinstance(v, dict) and "data" in v:
                        entry_cfg = v.get("data", {})
                        if isinstance(entry_cfg, dict):
                            key = entry_cfg.get(CONF_GEMINI_API_KEY)
                            if key:
                                api_key = str(key)
                                break
        if not api_key and hasattr(self.hass, "config_entries") and hasattr(self.hass.config_entries, "async_entries"):
            try:
                otis_entries = self.hass.config_entries.async_entries(DOMAIN)
                for entry in otis_entries:
                    key = entry.options.get(CONF_GEMINI_API_KEY) or entry.data.get(CONF_GEMINI_API_KEY)
                    if key:
                        api_key = str(key)
                        break
            except Exception as err:
                _LOGGER.debug("Could not inspect Otis config entries: %s", err)
        return api_key, model

    async def async_extract_keyframes_from_video(
        self, video_path: str, output_dir: str, prefix: str = "frame", max_frames: int = 24
    ) -> list[str]:
        """Extract evenly-spaced JPEG keyframes across the full walkthrough video using ffmpeg."""
        def _check_inputs() -> tuple[bool, str | None]:
            if not os.path.exists(video_path):
                return False, None
            f_bin = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
            if not os.path.exists(f_bin):
                return False, None
            os.makedirs(output_dir, exist_ok=True)
            return True, f_bin

        valid, ffmpeg_bin = await self._async_run_in_executor(_check_inputs)
        if not valid or not ffmpeg_bin:
            return []

        # Probe duration with ffmpeg -i so fps spans the entire video rather than stopping early
        duration_sec = 0.0
        try:
            probe_proc = await asyncio.create_subprocess_exec(
                ffmpeg_bin, "-i", video_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, probe_err = await probe_proc.communicate()
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", (probe_err or b"").decode("utf-8", "ignore"))
            if m:
                duration_sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        except Exception:
            duration_sec = 0.0

        fps_val = (
            max(0.03, min(1.0, max_frames / max(duration_sec, 1.0)))
            if duration_sec > 0
            else 0.2
        )
        pattern = os.path.join(output_dir, f"{prefix}_%02d.jpg")
        cmd = [
            ffmpeg_bin,
            "-i", video_path,
            "-vf", f"fps={fps_val:.4f},scale=512:-1",
            "-frames:v", str(max_frames),
            "-q:v", "6",
            "-y",
            pattern,
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()

            def _collect_frames() -> list[str]:
                if not os.path.exists(output_dir):
                    return []
                return sorted(
                    os.path.join(output_dir, f)
                    for f in os.listdir(output_dir)
                    if f.startswith(prefix) and f.endswith(".jpg")
                )

            frames = await self._async_run_in_executor(_collect_frames)
            return frames
        except Exception as err:
            _LOGGER.debug("Keyframe extraction skipped: %s", err)
            return []

    async def async_analyze_walkthrough_audio(
        self,
        audio_path: str,
        area_list: list[dict[str, Any]],
        frame_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Transcribe walkthrough audio + video keyframes and extract ordered areas, containment, adjacencies, doors and windows."""
        result: dict[str, Any] = {
            "transcript": "",
            "ordered_areas": [],
            "adjacencies": [],
            "contained_areas": {},
            "floor_assignments": {},
            "detected_doors": [],
            "detected_windows": [],
        }
        if not audio_path:
            return result

        api_key, preferred_model = self._get_gemini_credentials()
        if not api_key:
            _LOGGER.warning("No Google Generative AI API key found for walkthrough audio transcription.")
            return result

        mime_type = "audio/mp3" if audio_path.lower().endswith(".mp3") else "audio/wav"
        areas_desc = [{"id": a.get("id", ""), "name": a.get("name", "")} for a in area_list]

        prompt = (
            "You are an architectural AI analyzing a home walkthrough recording (audio + video frames) for Home Assistant.\n"
            f"Registered Home Assistant areas: {json.dumps(areas_desc)}\n\n"
            "1. Transcribe the spoken walkthrough audio verbatim.\n"
            "2. Match every room or area mentioned to its exact Home Assistant area `id` from the list above, "
            "in the chronological order the person walks through or mentions them.\n"
            "3. Identify pairs of areas `[area_id_1, area_id_2]` where the speaker walks directly from one into the other "
            "or describes them as connected/adjacent.\n"
            "4. Identify any open-concept parent rooms that contain sub-areas (for example, if the Great Room comprises "
            "a living room area, a kitchen area (`kitchen`), and a breakfast nook).\n"
            "5. Identify which floor each area belongs to (`main` for ground floor, `outdoor` for yard/pool/perimeter, "
            "`upper` for upstairs/second floor).\n"
            "6. Identify any doors mentioned or seen, noting the room, wall side (`top`, `bottom`, `left`, `right`), "
            "and swing orientation (`inward-left`, `inward-right`, `outward-left`, `outward-right`, `sliding`, or `cased`).\n"
            "7. Identify any windows mentioned or seen, noting the room and wall side (`top`, `bottom`, `left`, `right`).\n"
            "8. Identify any staircases (room, direction `up` or `down`, and label) and outdoor architectural features "
            "(such as `pool`, `deck_stairs`, or `front_porch`).\n"
            "9. Estimate each room's visual shape (`wide`, `tall`, `square`, or `corridor`) and relative size (`large`, `medium`, or `small`), "
            "and list directional room-to-room connections seen in the video (`side` of `from` where `to` connects: `top`, `bottom`, `left`, `right`, and `type`: `open`, `door`, or `stairs`).\n\n"
            "Respond strictly with valid JSON matching this schema:\n"
            '{"transcript": "...", "ordered_areas": ["area_id_1", "area_id_2"], '
            '"adjacencies": [["area_id_1", "area_id_2"]], '
            '"contained_areas": {"great_room": ["kitchen"]}, '
            '"floor_assignments": {"area_id_1": "outdoor", "area_id_2": "main"}, '
            '"doors": [{"room": "foyer", "wall": "bottom", "orientation": "inward-right", "label": "Front Door"}], '
            '"windows": [{"room": "dining_room", "wall": "bottom", "label": "Bay Window"}], '
            '"stairs": [{"room": "foyer", "direction": "up", "label": "Front Stairs (UP ↗)"}], '
            '"outdoor_features": [{"room": "backyard", "feature": "pool", "label": "Pool & Patio"}], '
            '"room_shapes": {"great_room": {"shape": "wide", "size": "large"}}, '
            '"directional_connections": [{"from": "foyer", "to": "great_room", "side": "top", "type": "open"}]}'
        )

        candidate_models = [preferred_model]
        for fallback_m in ("models/gemini-3.5-flash", "models/gemini-2.5-flash", "models/gemini-2.0-flash"):
            if fallback_m not in candidate_models:
                candidate_models.append(fallback_m)

        def _call_gemini_sync() -> dict[str, Any]:
            if not os.path.exists(audio_path):
                return result
            with open(audio_path, "rb") as af:
                audio_b64 = base64.b64encode(af.read()).decode("ascii")
            parts: list[dict[str, Any]] = [
                {"text": prompt},
                {"inline_data": {"mime_type": mime_type, "data": audio_b64}},
            ]
            for fp in (frame_paths or [])[:24]:
                if os.path.exists(fp):
                    try:
                        with open(fp, "rb") as imgf:
                            parts.append({
                                "inline_data": {
                                    "mime_type": "image/jpeg",
                                    "data": base64.b64encode(imgf.read()).decode("ascii"),
                                }
                            })
                    except Exception:
                        pass

            payload = {
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.1,
                },
            }
            last_err: Exception | None = None
            for m_name in candidate_models:
                url = f"https://generativelanguage.googleapis.com/v1beta/{m_name}:generateContent?key={api_key}"
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                try:
                    with urllib.request.urlopen(req, timeout=180) as resp:
                        return json.loads(resp.read().decode("utf-8"))
                except Exception as err:
                    last_err = err
                    continue
            if last_err:
                raise last_err
            return {}

        try:
            raw_resp = await self.hass.async_add_executor_job(_call_gemini_sync)
            text_out = (
                raw_resp.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
            cleaned_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", text_out.strip())
            parsed = json.loads(cleaned_json)
            transcript = str(parsed.get("transcript") or "").strip()
            result["transcript"] = transcript

            valid_ids = build_area_lookup_map(area_list)

            ordered: list[str] = []
            for raw_aid in parsed.get("ordered_areas") or []:
                resolved = resolve_area_identifier(str(raw_aid), valid_ids)
                if resolved and resolved not in ordered:
                    ordered.append(resolved)

            # Supplement with deterministic regex speech callouts on the transcript
            if transcript:
                regex_callouts = self.parse_speech_callouts(transcript, area_list)
                for c in regex_callouts:
                    cid = c.get("area_id")
                    if cid and cid not in ordered:
                        ordered.append(cid)

            result["ordered_areas"] = ordered

            adjacencies: list[list[str]] = []
            for pair in parsed.get("adjacencies") or []:
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    a1 = resolve_area_identifier(str(pair[0]), valid_ids)
                    a2 = resolve_area_identifier(str(pair[1]), valid_ids)
                    if a1 and a2 and a1 != a2:
                        adjacencies.append([a1, a2])

            result["adjacencies"] = adjacencies

            contained: dict[str, list[str]] = {}
            raw_contained = parsed.get("contained_areas") or {}
            if isinstance(raw_contained, dict):
                for p_raw, c_list in raw_contained.items():
                    p_id = resolve_area_identifier(str(p_raw), valid_ids)
                    if p_id and isinstance(c_list, list):
                        resolved_children = []
                        for c_raw in c_list:
                            c_id = resolve_area_identifier(str(c_raw), valid_ids)
                            if c_id and c_id != p_id:
                                resolved_children.append(c_id)
                        if resolved_children:
                            contained[p_id] = resolved_children
            result["contained_areas"] = contained

            floors: dict[str, str] = {}
            raw_floors = parsed.get("floor_assignments") or {}
            if isinstance(raw_floors, dict):
                for a_raw, fl_val in raw_floors.items():
                    a_id = resolve_area_identifier(str(a_raw), valid_ids)
                    fl_norm = str(fl_val).lower().strip()
                    if fl_norm in ("ground", "main", "first", "1st"):
                        fl_norm = "main"
                    elif fl_norm in ("upper", "upstairs", "second", "2nd"):
                        fl_norm = "upper"
                    elif fl_norm in ("outdoor", "exterior", "yard"):
                        fl_norm = "outdoor"
                    if a_id and fl_norm in ("main", "upper", "outdoor"):
                        floors[a_id] = fl_norm
            result["floor_assignments"] = floors

            # Doors detection with orientation
            doors_out: list[dict[str, Any]] = []
            for raw_d in parsed.get("doors") or []:
                if isinstance(raw_d, dict):
                    r_id = resolve_area_identifier(str(raw_d.get("room") or raw_d.get("area_id") or ""), valid_ids)
                    wall = str(raw_d.get("wall") or raw_d.get("side") or "bottom").lower()
                    if r_id and wall in ("top", "bottom", "left", "right"):
                        doors_out.append({
                            "room": r_id,
                            "side": wall,
                            "orientation": str(raw_d.get("orientation") or "inward-left"),
                            "label": str(raw_d.get("label") or "Door"),
                            "type": str(raw_d.get("type") or "swing"),
                        })
            result["detected_doors"] = doors_out

            # Windows detection with orientation
            windows_out: list[dict[str, Any]] = []
            for raw_w in parsed.get("windows") or []:
                if isinstance(raw_w, dict):
                    r_id = resolve_area_identifier(str(raw_w.get("room") or raw_w.get("area_id") or ""), valid_ids)
                    wall = str(raw_w.get("wall") or raw_w.get("side") or "top").lower()
                    if r_id and wall in ("top", "bottom", "left", "right"):
                        windows_out.append({
                            "room": r_id,
                            "side": wall,
                            "label": str(raw_w.get("label") or "Window"),
                            "orientation": "exterior",
                        })
            result["detected_windows"] = windows_out

            # Stairs, outdoor features, room shapes, and directional connections
            stairs_out: list[dict[str, Any]] = []
            for raw_s in parsed.get("stairs") or []:
                if isinstance(raw_s, dict):
                    r_id = resolve_area_identifier(str(raw_s.get("room") or ""), valid_ids)
                    direction = str(raw_s.get("direction") or "up").lower()
                    if r_id and direction in ("up", "down"):
                        stairs_out.append({
                            "room": r_id,
                            "direction": direction,
                            "label": str(raw_s.get("label") or f"Stairs ({direction.upper()})"),
                        })
            result["stairs"] = stairs_out

            outdoor_out: list[dict[str, Any]] = []
            for raw_o in parsed.get("outdoor_features") or []:
                if isinstance(raw_o, dict):
                    r_id = resolve_area_identifier(str(raw_o.get("room") or ""), valid_ids)
                    feat = str(raw_o.get("feature") or "").lower()
                    if r_id and feat:
                        outdoor_out.append({
                            "room": r_id,
                            "feature": feat,
                            "label": str(raw_o.get("label") or feat.replace("_", " ").title()),
                        })
            result["outdoor_features"] = outdoor_out

            shapes_out: dict[str, dict[str, str]] = {}
            raw_shapes = parsed.get("room_shapes") or {}
            if isinstance(raw_shapes, dict):
                for raw_rk, sval in raw_shapes.items():
                    r_id = resolve_area_identifier(str(raw_rk), valid_ids)
                    if r_id and isinstance(sval, dict):
                        shape = str(sval.get("shape") or "square").lower()
                        size = str(sval.get("size") or "medium").lower()
                        if shape in ("wide", "tall", "square", "corridor") and size in ("large", "medium", "small"):
                            shapes_out[r_id] = {"shape": shape, "size": size}
            result["room_shapes"] = shapes_out

            dir_conns_out: list[dict[str, str]] = []
            for raw_c in parsed.get("directional_connections") or []:
                if isinstance(raw_c, dict):
                    f_id = resolve_area_identifier(str(raw_c.get("from") or ""), valid_ids)
                    t_id = resolve_area_identifier(str(raw_c.get("to") or ""), valid_ids)
                    side = str(raw_c.get("side") or "").lower()
                    ctype = str(raw_c.get("type") or "door").lower()
                    if f_id and t_id and f_id != t_id and side in ("top", "bottom", "left", "right"):
                        dir_conns_out.append({
                            "from": f_id,
                            "to": t_id,
                            "side": side,
                            "type": ctype if ctype in ("open", "door", "stairs") else "door",
                        })
            result["directional_connections"] = dir_conns_out

            _LOGGER.info(
                "Walkthrough audio analysis complete: %d areas ordered (%s), %d adjacencies, doors=%d, windows=%d",
                len(ordered),
                ordered,
                len(adjacencies),
                len(doors_out),
                len(windows_out),
            )
        except Exception as err:
            _LOGGER.warning("Gemini walkthrough audio analysis failed: %s", err)

        return result

    async def async_process_multiclip_walkthrough(
        self,
        clips: list[str] | list[dict[str, Any]],
        area_list: list[dict[str, Any]],
        upload_dir: str | None = None,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        """Process multi-clip sequential video walkthrough uploads with cross-clip continuity."""
        if not upload_dir:
            upload_dir = "/tmp/walkthrough_processing"
        await self._async_run_in_executor(os.makedirs, upload_dir, exist_ok=True)

        combined_ordered_areas: list[str] = []
        combined_adjacencies: list[list[str]] = []
        combined_transcripts: list[str] = []
        combined_floor_assignments: dict[str, str] = {}
        combined_contained_areas: dict[str, list[str]] = {}
        combined_detected_doors: list[dict[str, Any]] = []
        combined_detected_windows: list[dict[str, Any]] = []
        combined_stairs: list[dict[str, Any]] = []
        combined_outdoor_features: list[dict[str, Any]] = []
        combined_room_shapes: dict[str, dict[str, str]] = {}
        combined_dir_connections: list[dict[str, str]] = []
        discovered_area_names: list[str] = []

        area_name_by_id = {a.get("id"): a.get("name", a.get("id")) for a in area_list}
        last_clip_last_area: str | None = None

        for idx, clip in enumerate(clips, start=1):
            if isinstance(clip, dict):
                video_path = clip.get("video_path")
                audio_path = clip.get("audio_path")
                frame_paths = clip.get("frame_paths")
            else:
                video_path = str(clip)
                audio_path = None
                frame_paths = None

            # 1. Extract audio if not provided
            if not audio_path and video_path and await self._async_run_in_executor(os.path.exists, video_path):
                audio_target = os.path.join(upload_dir, f"walkthrough_clip_{idx}.mp3")
                extracted = await self.async_extract_audio_from_video(video_path, audio_target)
                if not extracted:
                    audio_target = os.path.join(upload_dir, f"walkthrough_clip_{idx}.wav")
                    extracted = await self.async_extract_audio_from_video(video_path, audio_target)
                if extracted:
                    audio_path = audio_target

            # 2. Extract keyframes if not provided
            frame_dir = None
            if not frame_paths and video_path and await self._async_run_in_executor(os.path.exists, video_path):
                frame_dir = os.path.join(upload_dir, f"_frames_clip_{idx}")
                frame_paths = await self.async_extract_keyframes_from_video(
                    video_path, frame_dir, prefix=f"clip{idx}", max_frames=24
                )

            # 3. Analyze audio + frames with multimodal AI
            if audio_path and await self._async_run_in_executor(os.path.exists, audio_path):
                analysis = await self.async_analyze_walkthrough_audio(
                    audio_path, area_list, frame_paths=frame_paths
                )
                t_text = (analysis.get("transcript") or "").strip()
                if t_text:
                    combined_transcripts.append(f"[Clip {idx}] {t_text}")

                seg_areas = analysis.get("ordered_areas") or []
                for aid in seg_areas:
                    if aid not in combined_ordered_areas:
                        combined_ordered_areas.append(aid)
                        fname = area_name_by_id.get(aid, aid)
                        if fname not in discovered_area_names:
                            discovered_area_names.append(fname)
                        if callable(progress_callback):
                            try:
                                res_coro = progress_callback(
                                    f"Clip {idx}: Discovered {fname}", discovered_area_names
                                )
                                if asyncio.iscoroutine(res_coro):
                                    await res_coro
                            except Exception:
                                pass

                # Cross-clip sequential continuity: link previous clip's ending room to this clip's starting room
                if last_clip_last_area and seg_areas:
                    first_area = seg_areas[0]
                    if last_clip_last_area != first_area:
                        inter_pair = [last_clip_last_area, first_area]
                        if inter_pair not in combined_adjacencies and [first_area, last_clip_last_area] not in combined_adjacencies:
                            combined_adjacencies.append(inter_pair)

                if seg_areas:
                    last_clip_last_area = seg_areas[-1]

                # Intra-clip adjacencies
                for i in range(len(seg_areas) - 1):
                    pair = [seg_areas[i], seg_areas[i + 1]]
                    if pair[0] != pair[1] and pair not in combined_adjacencies and [pair[1], pair[0]] not in combined_adjacencies:
                        combined_adjacencies.append(pair)

                for pair in analysis.get("adjacencies") or []:
                    if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0] != pair[1]:
                        p_list = [pair[0], pair[1]]
                        if p_list not in combined_adjacencies and [pair[1], pair[0]] not in combined_adjacencies:
                            combined_adjacencies.append(p_list)

                # Merge floors & containment
                combined_floor_assignments.update(analysis.get("floor_assignments") or {})
                for p_k, c_list in (analysis.get("contained_areas") or {}).items():
                    if p_k not in combined_contained_areas:
                        combined_contained_areas[p_k] = []
                    for c_item in c_list:
                        if c_item not in combined_contained_areas[p_k]:
                            combined_contained_areas[p_k].append(c_item)

                # Merge detected doors and windows
                for d in analysis.get("detected_doors") or []:
                    if d not in combined_detected_doors:
                        combined_detected_doors.append(d)
                for w in analysis.get("detected_windows") or []:
                    if w not in combined_detected_windows:
                        combined_detected_windows.append(w)
                for st in analysis.get("stairs") or []:
                    if st not in combined_stairs:
                        combined_stairs.append(st)
                for feat in analysis.get("outdoor_features") or []:
                    if feat not in combined_outdoor_features:
                        combined_outdoor_features.append(feat)
                combined_room_shapes.update(analysis.get("room_shapes") or {})
                for dc in analysis.get("directional_connections") or []:
                    if dc not in combined_dir_connections:
                        combined_dir_connections.append(dc)

            # Cleanup temporary frame directory
            if frame_dir and await self._async_run_in_executor(os.path.isdir, frame_dir):
                try:
                    await self.hass.async_add_executor_job(shutil.rmtree, frame_dir, True)
                except Exception:
                    pass

        walkthrough_features = {
            "stairs": combined_stairs,
            "outdoor_features": combined_outdoor_features,
            "room_shapes": combined_room_shapes,
            "directional_connections": combined_dir_connections,
        }
        if hasattr(self, "_metadata") and isinstance(self._metadata, dict):
            self._metadata["walkthrough_features"] = walkthrough_features
            if combined_transcripts:
                self._metadata["transcripts"] = combined_transcripts
            if combined_ordered_areas:
                self._metadata["spoken_order"] = combined_ordered_areas

        return {
            "transcript": "\n".join(combined_transcripts),
            "transcripts": combined_transcripts,
            "ordered_areas": combined_ordered_areas,
            "adjacencies": combined_adjacencies,
            "contained_areas": combined_contained_areas,
            "floor_assignments": combined_floor_assignments,
            "detected_doors": combined_detected_doors,
            "detected_windows": combined_detected_windows,
            "walkthrough_features": walkthrough_features,
            "discovered_names": discovered_area_names,
            "clips_processed": len(clips),
        }

    def parse_speech_callouts(self, transcript_or_text: str, area_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Parse spoken room callouts from speech transcription to order the walkthrough path."""
        if not transcript_or_text:
            return []

        callouts: list[dict[str, Any]] = []
        cleaned_text = transcript_or_text.lower()

        # Build name to area mapping
        for area in area_list:
            aid = area.get("id", "")
            aname = (area.get("name") or aid).lower()
            norm_phrase = normalize_area_key(aname).replace("_", " ")
            name_options = rf"(?:{re.escape(aname)}|{re.escape(norm_phrase)})"
            
            # Search for occurrences of room name or phrases (e.g. "foyer", "in the kitchen", "into great room")
            pattern = re.compile(rf"\b(?:in(?:to)?|entering|this is(?: the)?|now in(?: the)?|here is(?: the)?|moving to)?\s*{name_options}\b", re.IGNORECASE)
            for match in pattern.finditer(cleaned_text):
                callouts.append({
                    "area_id": aid,
                    "area_name": area.get("name") or aid,
                    "char_position": match.start(),
                    "matched_text": match.group(0),
                })

        callouts.sort(key=lambda x: x["char_position"])
        # Deduplicate consecutive identical room mentions
        deduped: list[dict[str, Any]] = []
        for c in callouts:
            if not deduped or deduped[-1]["area_id"] != c["area_id"]:
                deduped.append(c)

        _LOGGER.info("Parsed %d sequential room callouts from walkthrough transcript", len(deduped))
        return deduped

    async def async_generate_svg_floorplan(
        self,
        capability_map: dict[str, Any],
        output_relative_path: str = DEFAULT_OUTPUT_SVG_PATH,
        theme: str = "cyberpunk",
        video_path: str | None = None,
        spoken_order: list[str] | str | None = None,
        walkthrough_completed: bool | None = None,
        reset_layout: bool = False,
        reanalyze_walkthrough: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Synthesize interactive vector SVG floor plan with multi-floor zones and active entities."""
        output_relative_path = self._sanitize_svg_path(output_relative_path)
        areas_map = capability_map.get("areas", {})
        entities = capability_map.get("entities", [])
        spatial_graph = capability_map.get("spatial_graph", {})
        adjacencies = spatial_graph.get("adjacencies", {})

        if reset_layout:
            if not self._initialized:
                await self.async_load()
            self._cached_svg_room_bounds = {}
            self._metadata["custom_layout"] = {"rooms": [], "badges": []}
            self._metadata["deleted_rooms"] = []
            self._metadata["walkthrough_features"] = {}
            self._metadata["transcripts"] = []

        if reanalyze_walkthrough and not video_path and getattr(self, "hass", None):
            media_dir = self.hass.config.path(".storage", DOMAIN, "media")

            def _find_stored_walkthrough_clips() -> list[str]:
                if not os.path.isdir(media_dir):
                    return []
                return sorted(
                    os.path.join(media_dir, f)
                    for f in os.listdir(media_dir)
                    if f.startswith("walkthrough_upload") and f.lower().endswith((".mp4", ".mov", ".webm", ".mkv"))
                )

            stored_clips = await self._async_run_in_executor(_find_stored_walkthrough_clips)
            if stored_clips:
                self._set_regen_progress(15, f"Re-analyzing {len(stored_clips)} stored walkthrough video(s)...", active=True, discovered_areas=[])
                area_list = [
                    {"id": aid, "name": (ainfo.get("name") if isinstance(ainfo, dict) else None) or aid}
                    for aid, ainfo in areas_map.items()
                ]

                def _on_wt_progress(stage_msg: str, disc_list: list[str]) -> None:
                    self._set_regen_progress(
                        min(78, 20 + len(disc_list) * 3),
                        stage_msg,
                        active=True,
                        discovered_areas=disc_list,
                    )

                wt_res = await self.async_process_multiclip_walkthrough(
                    stored_clips, area_list, upload_dir=media_dir, progress_callback=_on_wt_progress
                )
                if wt_res.get("ordered_areas"):
                    spoken_order = wt_res["ordered_areas"]
                if wt_res.get("detected_doors"):
                    kwargs["detected_doors"] = wt_res["detected_doors"]
                if wt_res.get("detected_windows"):
                    kwargs["detected_windows"] = wt_res["detected_windows"]
                walkthrough_completed = True
        if reset_layout or reanalyze_walkthrough:
            self._set_regen_progress(84, "Synthesizing vector SVG floor plan & placing room pins...", active=True)

        # Normalize spoken order if provided, or fall back to previously stored spoken_order
        order_list: list[str] = []
        if isinstance(spoken_order, str):
            order_list = [normalize_area_key(x.strip()) for x in spoken_order.split(",") if x.strip()]
        elif isinstance(spoken_order, (list, tuple)):
            order_list = [normalize_area_key(str(x).strip()) for x in spoken_order if str(x).strip()]
        elif self._metadata.get("spoken_order"):
            order_list = [normalize_area_key(str(x).strip()) for x in self._metadata["spoken_order"] if str(x).strip()]

        # Determine walkthrough completion state
        if walkthrough_completed is not None:
            is_walkthrough = bool(walkthrough_completed)
        elif video_path or order_list:
            is_walkthrough = True
        else:
            is_walkthrough = bool(self._metadata.get("walkthrough_completed", False))

        # Group areas into floor zones (excluding rooms previously deleted by user)
        deleted_set = set(self._metadata.get("deleted_rooms", []))
        zones: dict[str, list[dict[str, Any]]] = {
            "main": [],
            "upper": [],
            "outdoor": [],
        }

        for aid, ainfo in areas_map.items():
            if aid in deleted_set:
                continue
            aname = ainfo.get("name", aid)
            zone_type = classify_area_zone(aid, aname)
            zones[zone_type].append({
                "id": aid,
                "name": aname,
                "entities": ainfo.get("entities", []),
                "adjacent_areas": adjacencies.get(aid, []),
            })

        # Order rooms within each zone based on walkthrough spoken order if available
        if order_list:
            for _z, r_list in zones.items():
                def _sort_key(room: dict[str, Any]) -> int:
                    key = normalize_area_key(room["id"])
                    name_key = normalize_area_key(room["name"])
                    for idx, target in enumerate(order_list):
                        if target in (key, name_key):
                            return idx
                    return 999
                r_list.sort(key=_sort_key)

        # Attach detected doors and windows passed via kwargs to matching rooms
        detected_doors = kwargs.get("detected_doors") or []
        detected_windows = kwargs.get("detected_windows") or []
        if detected_doors or detected_windows:
            for _z, r_list in zones.items():
                for r in r_list:
                    rid = r["id"]
                    for d in detected_doors:
                        if d.get("room") == rid:
                            if "doors" not in r:
                                r["doors"] = []
                            r["doors"].append(d)
                    for w in detected_windows:
                        if w.get("room") == rid:
                            if "windows" not in r:
                                r["windows"] = []
                            r["windows"].append(w)

        # Calculate layout coordinates for each room
        layout_by_zone = self._calculate_orthogonal_layout(zones)
        # Calculate stacked multi-floor 3D isometric layout coordinates
        iso_layout_by_zone = self._calculate_isometric_layout(layout_by_zone)

        # Render complete SVG markup
        svg_content = self._render_svg_markup(
            layout_by_zone, entities, theme, iso_layout_by_zone=iso_layout_by_zone
        )

        # Write SVG file to destination
        output_full_path = (
            self.hass.config.path(output_relative_path)
            if hasattr(self.hass, "config") and hasattr(self.hass.config, "path")
            else output_relative_path
        )
        output_dir = os.path.dirname(output_full_path)
        base_name = os.path.basename(output_full_path)
        name_no_ext, ext = os.path.splitext(base_name)
        output_3d_rel = (
            f"{os.path.dirname(output_relative_path)}/{name_no_ext}_3d{ext}".lstrip("/")
            if os.path.dirname(output_relative_path)
            else f"{name_no_ext}_3d{ext}"
        )
        output_3d_full = os.path.join(output_dir, f"{name_no_ext}_3d{ext}")
        svg_3d_content = self._make_3d_primary_svg(svg_content)

        def write_sync():
            os.makedirs(output_dir, exist_ok=True)
            with open(output_full_path, "w", encoding="utf-8") as f:
                f.write(svg_content)
            with open(output_3d_full, "w", encoding="utf-8") as f_3d:
                f_3d.write(svg_3d_content)

        await self._async_run_in_executor(write_sync)
        await self.async_refresh_svg_cache(output_relative_path)
        _LOGGER.info(
            "Generated vector SVG floor plans saved to %s and %s (walkthrough=%s)",
            output_full_path,
            output_3d_full,
            is_walkthrough,
        )

        # Generate Lovelace Picture-Elements Card YAML snippet
        lovelace_card_yaml = self._generate_lovelace_card_yaml(output_relative_path, layout_by_zone)

        # Save metadata to storage
        transcripts = kwargs.get("transcripts") or self._metadata.get("transcripts", [])
        meta = {
            "version": STORAGE_VERSION,
            "svg_path": output_relative_path,
            "svg_path_3d": output_3d_rel,
            "theme": theme,
            "zones": {z: [a["name"] for a in room_list] for z, room_list in zones.items()},
            "room_count": len(areas_map),
            "walkthrough_completed": is_walkthrough,
            "spoken_order": order_list,
            "transcripts": transcripts,
            "lovelace_yaml": lovelace_card_yaml,
        }
        await self.async_save_metadata(meta)

        return {
            "success": True,
            "svg_path": output_relative_path,
            "svg_path_3d": output_3d_rel,
            "url": f"/api/otis_ai/media/{os.path.basename(output_relative_path)}",
            "url_3d": f"/api/otis_ai/media/{os.path.basename(output_3d_rel)}",
            "room_count": len(areas_map),
            "zones": meta["zones"],
            "walkthrough_completed": is_walkthrough,
            "spoken_order": order_list,
            "transcripts": transcripts,
            "lovelace_yaml": lovelace_card_yaml,
        }

    async def async_update_floorplan_layout(
        self,
        badges: list[dict[str, Any]] | None = None,
        rooms: list[dict[str, Any]] | None = None,
        deleted_rooms: list[str] | None = None,
        custom_features: list[dict[str, Any]] | None = None,
        svg_relative_path: str = DEFAULT_OUTPUT_SVG_PATH,
    ) -> dict[str, Any]:
        """Update SVG floorplan device marker coordinates and area boundary geometry, or delete rooms."""
        svg_relative_path = self._sanitize_svg_path(svg_relative_path)
        if os.path.isabs(svg_relative_path):
            output_full_path = svg_relative_path
        elif hasattr(self.hass, "config") and hasattr(self.hass.config, "path"):
            p = self.hass.config.path(svg_relative_path)
            output_full_path = p if isinstance(p, str) else svg_relative_path
        else:
            output_full_path = svg_relative_path

        def read_sync() -> str | None:
            if not os.path.exists(output_full_path):
                return None
            with open(output_full_path, encoding="utf-8") as f:
                return f.read()

        svg_content = await self._async_run_in_executor(read_sync)
        if svg_content is None:
            return {
                "success": False,
                "error": f"Floorplan SVG not found at {output_full_path}. Generate floor plan first.",
            }

        # Sanitize any existing corrupted <text> elements in the SVG
        svg_content = sanitize_corrupted_svg_text(svg_content)

        # 0. Delete requested rooms/areas from SVG markup
        to_delete = set(deleted_rooms or [])
        if rooms:
            for r in rooms:
                if r.get("delete") or r.get("deleted"):
                    if r.get("id"):
                        to_delete.add(r["id"])

        deleted_rooms_count = 0
        for del_id in to_delete:
            while True:
                span = find_room_group_span(svg_content, del_id)
                if not span:
                    break
                s_idx, e_idx, _, _ = span
                svg_content = svg_content[:s_idx] + svg_content[e_idx:]
                deleted_rooms_count += 1

        # 1. Update device marker badges
        updated_badges = 0
        deleted_badges_count = 0
        explicit_badge_ids = set()
        if badges:
            for b in badges:
                eid = b.get("entity_id")
                if not eid:
                    continue
                if b.get("delete") or b.get("deleted"):
                    pattern = rf'<g\b[^>]*class="[^"]*(?:entity-badge|iso-marker-badge)[^"]*"[^>]*data-entity-id="{re.escape(eid)}"[^>]*>[\s\S]*?</g>'
                    new_svg, count = re.subn(pattern, "", svg_content)
                    if count > 0:
                        svg_content = new_svg
                        deleted_badges_count += 1
                    pattern_alt = rf'<g\b[^>]*data-entity-id="{re.escape(eid)}"[^>]*class="[^"]*(?:entity-badge|iso-marker-badge)[^"]*"[^>]*>[\s\S]*?</g>'
                    new_svg, count = re.subn(pattern_alt, "", svg_content)
                    if count > 0:
                        svg_content = new_svg
                        if deleted_badges_count == 0:
                            deleted_badges_count += 1
                    continue

                if "x" not in b or "y" not in b:
                    continue
                explicit_badge_ids.add(eid)
                bx = round(float(b["x"]), 1)
                by = round(float(b["y"]), 1)
                # Match <g ... class="entity-badge" ... data-entity-id="eid" ... transform="...">
                pattern = rf'(<g\b[^>]*class="[^"]*entity-badge[^"]*"[^>]*data-entity-id="{re.escape(eid)}"[^>]*?)(\s+transform="translate\([^)]*\)")?'

                def _badge_sub(match: re.Match, _bx: float = bx, _by: float = by) -> str:
                    prefix = match.group(1)
                    prefix = re.sub(r'\s+transform="[^"]*"', '', prefix)
                    return f'{prefix} transform="translate({_bx}, {_by})"'

                new_svg, count = re.subn(pattern, _badge_sub, svg_content)
                if count > 0:
                    svg_content = new_svg
                    updated_badges += count
                else:
                    # Also try pattern if data-entity-id came before class
                    pattern_alt = rf'(<g\b[^>]*data-entity-id="{re.escape(eid)}"[^>]*class="[^"]*entity-badge[^"]*"[^>]*?)(\s+transform="translate\([^)]*\)")?'
                    new_svg, count = re.subn(pattern_alt, _badge_sub, svg_content)
                    if count > 0:
                        svg_content = new_svg
                        updated_badges += count
                    else:
                        # Insert as new badge before closing of plan-ground or </svg>
                        domain = eid.split(".")[0] if "." in eid else "unknown"
                        icon_char = "💡" if domain == "light" else "🚶" if domain == "binary_sensor" else "🌡️" if domain == "climate" else "📺" if domain == "media_player" else "📹" if domain == "camera" else "⚡"
                        eid_esc = html.escape(str(eid), quote=True)
                        badge_markup = (
                            f'    <g class="entity-badge" data-entity-id="{eid_esc}" transform="translate({bx}, {by})">\n'
                            f'      <circle cx="0" cy="0" r="9" class="badge-circle" />\n'
                            f'      <text class="badge-icon">{icon_char}</text>\n'
                            f'    </g>\n'
                        )
                        if '</g>\n</svg>' in svg_content:
                            svg_content = svg_content.replace('</g>\n</svg>', f'{badge_markup}  </g>\n</svg>', 1)
                        elif '</svg>' in svg_content:
                            svg_content = svg_content.replace('</svg>', f'{badge_markup}</svg>', 1)
                        updated_badges += 1

        # 2. Update room boundaries & geometry
        updated_rooms = 0
        if rooms:
            for r in rooms:
                rid = r.get("id")
                if not rid or "x" not in r or "y" not in r:
                    continue
                rx = max(40.0, min(round(float(r["x"]), 1), 1200.0))
                ry = max(30.0, min(round(float(r["y"]), 1), 1350.0))
                rw = max(60.0, min(round(float(r.get("width", 160)), 1), 1260.0 - rx))
                rh = max(50.0, min(round(float(r.get("height", 120)), 1), 1400.0 - ry))
                points = r.get("points")
                rname = r.get("name")

                # Match room group by data-area-id using depth-aware parsing
                span = find_room_group_span(svg_content, rid)
                if span:
                    s_idx, e_idx, header, inner = span
                    if points:
                        points_esc = html.escape(str(points), quote=True)
                        if '<polygon' in inner:
                            inner = re.sub(r'<polygon[^>]*class="room-polygon"[^>]*/>', f'<polygon points="{points_esc}" class="room-polygon" />', inner)
                        else:
                            inner = re.sub(r'<rect[^>]*class="room-rect"[^>]*/>', f'<polygon points="{points_esc}" class="room-polygon" />', inner)
                    else:
                        def _rect_sub(rmatch: re.Match, _rx: float = rx, _ry: float = ry, _rw: float = rw, _rh: float = rh) -> str:
                            tag = rmatch.group(0)
                            tag = re.sub(r'\s+(?:x|y|width|height)="[^"]*"', '', tag)
                            return f'<rect x="{_rx}" y="{_ry}" width="{_rw}" height="{_rh}"' + tag[5:]

                        inner = re.sub(
                            r'<rect\b[^>]*class="[^"]*(?:room-box|room-rect)[^"]*"[^>]*/>',
                            _rect_sub,
                            inner,
                        )

                    # Preserve header offset (34px inside multi-zone containers, 22px otherwise)
                    has_container_offset = (
                        "container-shell" in inner
                        or "container-banner" in inner
                        or "has-container" in header
                    )
                    hdr_y_off = 34 if has_container_offset else 22

                    # Update text label position cleanly inside attributes
                    def _text_sub(
                        tmatch: re.Match,
                        _rx: float = rx,
                        _ry: float = ry,
                        _hdr_y_off: int = hdr_y_off,
                        _rname: Any = rname,
                        _rid: str = rid,
                    ) -> str:
                        orig_content = tmatch.group(1)
                        cleaned_txt = re.sub(r'^(?:\s*(?:x|y)="[^"]*"[>\s]*)+', '', orig_content).strip()
                        display_name = _rname.strip() if (_rname and str(_rname).strip()) else cleaned_txt
                        if not display_name:
                            display_name = _rid.replace('_', ' ').title()
                        return f'<text x="{round(_rx + 14, 1)}" y="{round(_ry + _hdr_y_off, 1)}" class="room-header">{html.escape(html.unescape(display_name))}</text>'

                    inner = re.sub(
                        r'<text\b[^>]*class="[^"]*(?:room-header|room-label)[^"]*"[^>]*>(.*?)</text>',
                        _text_sub,
                        inner,
                    )

                    # Update internal architectural subzone pills in sync with room coordinates (or replace if sub_zones supplied)
                    if "sub_zones" in r and isinstance(r.get("sub_zones"), list):
                        new_pills = []
                        for _pill_i, sz_item in enumerate(r["sub_zones"]):
                            sz_clean = str(sz_item or "").strip()
                            if not sz_clean:
                                continue
                            py = round(ry + hdr_y_off + 18 + len(new_pills) * 16, 1)
                            new_pills.append(
                                f'    <text x="{round(rx + 16, 1)}" y="{py}" class="subzone-pill">▪ {html.escape(sz_clean)}</text>'
                            )
                        inner = re.sub(
                            r'\n?\s*<text\b[^>]*class="[^"]*subzone-pill[^"]*"[^>]*>.*?</text>',
                            "",
                            inner,
                        )
                        if new_pills:
                            pill_block = "\n" + "\n".join(new_pills)
                            inner, replaced_hdr = re.subn(
                                r'(<text\b[^>]*class="[^"]*(?:room-header|room-label)[^"]*"[^>]*>.*?</text>)',
                                lambda m, _pb=pill_block: m.group(1) + _pb,
                                inner,
                                count=1,
                            )
                            if not replaced_hdr:
                                inner = pill_block + "\n" + inner
                    else:
                        pill_idx = 0

                        def _pill_sub(
                            pmatch: re.Match,
                            _rx: float = rx,
                            _ry: float = ry,
                            _hdr_y_off: int = hdr_y_off,
                        ) -> str:
                            nonlocal pill_idx
                            orig_txt = pmatch.group(1)
                            clean_pill = re.sub(r'^(?:\s*(?:x|y)="[^"]*"[>\s]*)+', '', orig_txt).strip()
                            py = round(_ry + _hdr_y_off + 18 + pill_idx * 16, 1)
                            pill_idx += 1
                            return f'<text x="{round(_rx + 16, 1)}" y="{py}" class="subzone-pill">{html.escape(html.unescape(clean_pill))}</text>'

                        inner = re.sub(
                            r'<text\b[^>]*class="[^"]*subzone-pill[^"]*"[^>]*>(.*?)</text>',
                            _pill_sub,
                            inner,
                        )

                    # Update internal entity badges in sync with room coordinates
                    b_idx = 0

                    def _badge_sub(bmatch: re.Match, _rx: float = rx, _ry: float = ry, _rh: float = rh) -> str:
                        nonlocal b_idx
                        badge_full = bmatch.group(0)
                        eid_match = re.search(r'data-entity-id="([^"]*)"', badge_full)
                        if eid_match and eid_match.group(1) in explicit_badge_ids:
                            b_idx += 1
                            return badge_full
                        bx = round(_rx + 16 + b_idx * 24, 1)
                        by = round(_ry + _rh - 18, 1)
                        b_idx += 1
                        badge_no_tr = re.sub(r'\s+transform="[^"]*"', '', badge_full)
                        return re.sub(r'^(<g\b[^>]*?)>', rf'\1 transform="translate({bx}, {by})">', badge_no_tr, count=1)

                    inner = re.sub(
                        r'<g\b[^>]*class="[^"]*entity-badge[^"]*"[^>]*>[\s\S]*?</g>',
                        _badge_sub,
                        inner,
                    )

                    # Update internal stairs in sync with room coordinates or explicit feature position
                    r_features = r.get("features") if isinstance(r.get("features"), dict) else {}
                    stairs_feat = r_features.get("stairs") if isinstance(r_features.get("stairs"), dict) else None
                    sx = round(float(stairs_feat["x"]), 1) if (stairs_feat and "x" in stairs_feat) else round(rx + rw - 58, 1)
                    sy = round(float(stairs_feat["y"]), 1) if (stairs_feat and "y" in stairs_feat) else round(ry + rh - 42, 1)
                    inner = re.sub(
                        r'(<g\b[^>]*class="[^"]*room-feature[^"]*"[^>]*data-feature="stairs"[^>]*>)',
                        f'<g class="room-feature" data-feature="stairs" data-x="{sx}" data-y="{sy}">',
                        inner,
                    )
                    inner = re.sub(
                        r'(<rect\b[^>]*class="stairs-step"[^>]*?)\s+x="[^"]*"\s+y="[^"]*"',
                        rf'\1 x="{sx}" y="{sy}"',
                        inner,
                    )
                    inner = re.sub(
                        r'(<rect\b[^>]*?)\s+x="[^"]*"\s+y="[^"]*"([^>]*class="stairs-step")',
                        rf'\1 x="{sx}" y="{sy}"\2',
                        inner,
                    )
                    step_i = 0

                    def _step_sub(smatch: re.Match, _sx: float = sx, _sy: float = sy) -> str:
                        nonlocal step_i
                        step_i += 1
                        lx = round(_sx + step_i * 9, 1)
                        return f'<line x1="{lx}" y1="{_sy}" x2="{lx}" y2="{round(_sy + 28, 1)}" class="stairs-step" />'

                    inner = re.sub(
                        r'<line\b[^>]*class="stairs-step"[^>]*/>',
                        _step_sub,
                        inner,
                    )

                    # Update pool / front_porch feature boxes if custom coordinates were provided
                    for feat_key in ("pool", "front_porch"):
                        f_pos = r_features.get(feat_key) if isinstance(r_features.get(feat_key), dict) else None
                        if not f_pos or "x" not in f_pos or "y" not in f_pos:
                            continue
                        fx = round(float(f_pos["x"]), 1)
                        fy = round(float(f_pos["y"]), 1)
                        feat_pat = rf'<g\b[^>]*class="[^"]*room-feature[^"]*"[^>]*data-feature="{feat_key}"[^>]*>([\s\S]*?)</g>'

                        def _feat_sub(
                            fmatch: re.Match,
                            _feat_key: str = feat_key,
                            _fx: float = fx,
                            _fy: float = fy,
                        ) -> str:
                            f_body = fmatch.group(1)
                            w_m = re.search(r'<rect\b[^>]*\swidth="([^"]+)"', f_body)
                            h_m = re.search(r'<rect\b[^>]*\sheight="([^"]+)"', f_body)
                            fw = float(w_m.group(1)) if w_m else (170.0 if _feat_key == "pool" else 200.0)
                            fh = float(h_m.group(1)) if h_m else (64.0 if _feat_key == "pool" else 20.0)
                            f_body = re.sub(
                                r'(<rect\b[^>]*?)\s+x="[^"]*"\s+y="[^"]*"',
                                rf'\1 x="{_fx}" y="{_fy}"',
                                f_body,
                                count=1,
                            )
                            tx = round(_fx + fw / 2.0, 1)
                            ty = round(_fy + (fh / 2.0 + 4.0 if _feat_key == "pool" else 13.0), 1)
                            f_body = re.sub(
                                r'(<text\b[^>]*?)\s+x="[^"]*"\s+y="[^"]*"',
                                rf'\1 x="{tx}" y="{ty}"',
                                f_body,
                                count=1,
                            )
                            return f'<g class="room-feature" data-feature="{_feat_key}" data-x="{_fx}" data-y="{_fy}">{f_body}</g>'

                        inner = re.sub(feat_pat, _feat_sub, inner, count=1)

                    svg_content = svg_content[:s_idx] + header + inner + "</g>" + svg_content[e_idx:]
                    updated_rooms += 1

        # 3. Persist updated layout coordinates to metadata storage
        if not self._initialized:
            await self.async_load()

        custom_layout = self._metadata.setdefault("custom_layout", {})
        if badges:
            existing_badges = {b["entity_id"]: b for b in custom_layout.get("badges", []) if isinstance(b, dict) and b.get("entity_id")}
            for b in badges:
                if isinstance(b, dict) and b.get("entity_id"):
                    if b.get("delete") or b.get("deleted"):
                        existing_badges.pop(b["entity_id"], None)
                    else:
                        b_copy = dict(b)
                        b_copy.setdefault("custom", True)
                        existing_badges[b["entity_id"]] = b_copy
            custom_layout["badges"] = list(existing_badges.values())

        if rooms:
            existing_rooms = {r["id"]: r for r in custom_layout.get("rooms", []) if isinstance(r, dict) and r.get("id")}
            for r in rooms:
                if isinstance(r, dict):
                    rid = r.get("id")
                    if rid and rid not in to_delete and not r.get("delete"):
                        merged_r = dict(existing_rooms.get(rid, {}))
                        for k, v in r.items():
                            if k == "features" and isinstance(v, dict) and isinstance(merged_r.get("features"), dict):
                                merged_f = dict(merged_r["features"])
                                merged_f.update(v)
                                merged_r["features"] = merged_f
                            else:
                                merged_r[k] = v
                        existing_rooms[rid] = merged_r
            custom_layout["rooms"] = [r for r in existing_rooms.values() if r.get("id") not in to_delete]

        if to_delete:
            del_list = self._metadata.setdefault("deleted_rooms", [])
            for did in to_delete:
                if did not in del_list:
                    del_list.append(did)
            if "rooms" in custom_layout and isinstance(custom_layout["rooms"], list):
                custom_layout["rooms"] = [r for r in custom_layout["rooms"] if r.get("id") not in to_delete]

        # 3b. Persist & apply independent custom features (stairs, labeled boxes)
        if custom_features:
            existing_cf = {
                cf["id"]: cf
                for cf in (custom_layout.get("custom_features") or [])
                if isinstance(cf, dict) and cf.get("id")
            }
            for cf in custom_features:
                if not isinstance(cf, dict) or not cf.get("id"):
                    continue
                fid = str(cf["id"])
                cf_pat = rf'\n?\s*<g\b[^>]*data-custom-id="{re.escape(fid)}"[^>]*>[\s\S]*?</g>'
                svg_content = re.sub(cf_pat, "", svg_content)
                if cf.get("delete") or cf.get("deleted"):
                    existing_cf.pop(fid, None)
                    continue
                merged_cf = dict(existing_cf.get(fid, {}))
                merged_cf.update(cf)
                existing_cf[fid] = merged_cf
                cf_markup = self._render_custom_feature_svg(merged_cf)
                target_zone = str(merged_cf.get("zone") or "main").lower()
                if target_zone == "upper":
                    anchor_re = r'(<g\b[^>]*id="plan-upper"[^>]*>[\s\S]*?)(  </g>\s*\n\s*</g>\s*<!-- /view-mode-2d -->)'
                else:
                    anchor_re = r'(<g\b[^>]*id="plan-ground"[^>]*>[\s\S]*?)(  </g>\s*\n\s*(?:<!-- PLAN 2|</g>\s*<!-- /view-mode-2d -->))'
                svg_content, inserted = re.subn(
                    anchor_re,
                    lambda m, mk=cf_markup: f"{m.group(1)}{mk}{m.group(2)}",
                    svg_content,
                    count=1,
                )
                if not inserted:
                    if '</g>  <!-- /view-mode-2d -->' in svg_content:
                        svg_content = svg_content.replace('</g>  <!-- /view-mode-2d -->', f'{cf_markup}  </g>  <!-- /view-mode-2d -->', 1)
                    elif '</svg>' in svg_content:
                        svg_content = svg_content.replace('</svg>', f'{cf_markup}</svg>', 1)
            custom_layout["custom_features"] = list(existing_cf.values())

        self._metadata["last_layout_update"] = int(time.time())
        await self.async_save_metadata(self._metadata)

        def write_sync():
            with open(output_full_path, "w", encoding="utf-8") as f:
                f.write(svg_content)

        await self._async_run_in_executor(write_sync)
        await self.async_refresh_svg_cache(svg_relative_path)
        _LOGGER.info(
            "Updated floorplan layout in %s (badges=%d, rooms=%d, deleted=%d)",
            output_full_path,
            updated_badges,
            updated_rooms,
            deleted_rooms_count,
        )

        return {
            "success": True,
            "message": f"Updated floor plan layout ({updated_badges} badges, {updated_rooms} rooms, {deleted_rooms_count} deleted)",
            "svg_path": svg_relative_path,
            "url": f"/api/otis_ai/media/{os.path.basename(svg_relative_path)}?v={int(time.time())}",
            "updated_badges": updated_badges,
            "updated_rooms": updated_rooms,
            "deleted_rooms": deleted_rooms_count,
        }

    async def async_pin_entity(
        self,
        entity_id: str,
        area_id: str | None = None,
        x: float | None = None,
        y: float | None = None,
        svg_relative_path: str = DEFAULT_OUTPUT_SVG_PATH,
    ) -> dict[str, Any]:
        """Pin or reposition an entity badge on the floorplan (by room area or explicit coordinates)."""
        await self.async_load()
        svg_relative_path = self._sanitize_svg_path(svg_relative_path)
        if os.path.isabs(svg_relative_path):
            svg_full_path = svg_relative_path
        elif hasattr(self.hass, "config") and hasattr(self.hass.config, "path"):
            p = self.hass.config.path(svg_relative_path)
            svg_full_path = p if isinstance(p, str) else svg_relative_path
        else:
            svg_full_path = svg_relative_path

        target_x = x
        target_y = y
        target_area = area_id

        # If explicit coordinates not supplied, resolve via area bounds
        if target_x is None or target_y is None:
            room_bounds = await self._async_run_in_executor(
                self._parse_svg_room_bounds_sync, svg_full_path
            )
            matched_room = None
            if target_area:
                norm_area = str(target_area).lower().replace(" ", "_").strip()
                for rid, rdata in room_bounds.items():
                    if rid.lower() == norm_area or rid.lower() == f"area_{norm_area}":
                        matched_room = rdata
                        break
                    if norm_area in rid.lower():
                        matched_room = rdata
                        break

            if matched_room:
                rx = float(matched_room.get("x", 100.0))
                ry = float(matched_room.get("y", 100.0))
                rw = float(matched_room.get("width", 200.0))
                rh = float(matched_room.get("height", 140.0))
                target_x = round(rx + (rw / 2.0), 1)
                target_y = round(ry + (rh / 2.0), 1)
            else:
                target_x = 400.0
                target_y = 300.0

        # Check existing badges to avoid exact stacking
        custom_layout = self._metadata.get("custom_layout", {})
        existing_badges = custom_layout.get("badges", [])
        stacked_count = sum(
            1 for b in existing_badges
            if isinstance(b, dict)
            and abs(float(b.get("x", 0)) - target_x) < 8
            and abs(float(b.get("y", 0)) - target_y) < 8
            and b.get("entity_id") != entity_id
        )
        if stacked_count > 0:
            target_x += (stacked_count * 24.0)

        badge_payload = {
            "entity_id": entity_id,
            "x": target_x,
            "y": target_y,
        }
        res = await self.async_update_floorplan_layout(
            badges=[badge_payload],
            svg_relative_path=svg_relative_path,
        )
        res["entity_id"] = entity_id
        res["area_id"] = target_area
        res["x"] = target_x
        res["y"] = target_y
        return res

    async def async_unpin_entity(
        self,
        entity_id: str,
        svg_relative_path: str = DEFAULT_OUTPUT_SVG_PATH,
    ) -> dict[str, Any]:
        """Remove a pinned entity badge from the floorplan."""
        svg_relative_path = self._sanitize_svg_path(svg_relative_path)
        res = await self.async_update_floorplan_layout(
            badges=[{"entity_id": entity_id, "delete": True}],
            svg_relative_path=svg_relative_path,
        )
        res["entity_id"] = entity_id
        return res

    async def async_recalculate_floorplan(
        self,
        capability_map: dict[str, Any],
        preserve_custom_pins: bool = True,
        output_relative_path: str = DEFAULT_OUTPUT_SVG_PATH,
    ) -> dict[str, Any]:
        """Force recalculation of floorplan SVG layout and auto-placed room entity pins."""
        if not self._initialized:
            await self.async_load()

        custom_layout = self._metadata.setdefault("custom_layout", {})
        if not isinstance(custom_layout, dict):
            custom_layout = {}
            self._metadata["custom_layout"] = custom_layout

        old_badges = custom_layout.get("badges", []) if isinstance(custom_layout.get("badges"), list) else []
        if preserve_custom_pins:
            kept_badges = [
                dict(b)
                for b in old_badges
                if isinstance(b, dict) and b.get("entity_id") and b.get("custom") and not (b.get("delete") or b.get("deleted"))
            ]
        else:
            kept_badges = []

        cleared_count = max(0, len(old_badges) - len(kept_badges))
        custom_layout["badges"] = kept_badges

        res = await self.async_generate_svg_floorplan(
            capability_map,
            output_relative_path=output_relative_path,
        )
        await self.async_save_metadata(self._metadata)
        return {
            "status": "ok",
            "badges_cleared": cleared_count,
            "badges_preserved": len(kept_badges),
            "svg_path": res.get("svg_path", output_relative_path),
            "room_count": res.get("room_count", 0),
        }

    def build_effective_badges(
        self,
        areas_map: dict[str, Any] | None,
        entities_list: list[dict[str, Any]] | None,
        devices_map: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return custom_layout badges augmented with centered default room pins for uncustomized rooms."""
        meta = getattr(self, "_metadata", {}) or {}
        c_layout = meta.get("custom_layout", {}) if isinstance(meta, dict) else {}
        if not isinstance(c_layout, dict):
            c_layout = {}
        deleted_rooms = set(meta.get("deleted_rooms", [])) if isinstance(meta, dict) else set()

        raw_badges = c_layout.get("badges", []) if isinstance(c_layout.get("badges"), list) else []

        if not areas_map or not entities_list:
            return [
                dict(b)
                for b in raw_badges
                if isinstance(b, dict) and b.get("entity_id") and not (b.get("delete") or b.get("deleted"))
            ]

        valid_eids = {
            e["entity_id"]
            for e in entities_list
            if isinstance(e, dict)
            and e.get("entity_id")
            and not e.get("disabled_by")
            and not e.get("hidden_by")
            and e.get("state") not in ("unknown", "unavailable", None, "")
        }
        entities_by_area: dict[str, list[dict[str, Any]]] = {}
        entity_area_map: dict[str, str] = {}
        for e in entities_list:
            if not isinstance(e, dict) or not e.get("entity_id"):
                continue
            aid = e.get("area_id")
            if aid:
                entities_by_area.setdefault(str(aid), []).append(e)
                entity_area_map[str(e["entity_id"])] = str(aid)

        # Build live room bounds from SVG cache + custom_layout rooms, falling back to orthogonal layout
        rooms_by_id: dict[str, dict[str, Any]] = {}
        for aid_svg, b_val in getattr(self, "_cached_svg_room_bounds", {}).items():
            if isinstance(b_val, dict):
                rooms_by_id[str(aid_svg)] = dict(b_val)

        if isinstance(c_layout.get("rooms"), list):
            for cr in c_layout["rooms"]:
                if isinstance(cr, dict) and cr.get("id"):
                    rid = str(cr["id"])
                    entry = rooms_by_id.setdefault(rid, {})
                    for k in ("x", "y", "width", "height", "name"):
                        if k in cr and cr[k] is not None:
                            entry[k] = cr[k]

        # If no cached SVG bounds exist yet, compute orthogonal layout from areas_map
        if not rooms_by_id:
            zones_in: dict[str, list[dict[str, Any]]] = {"main": [], "upper": [], "outdoor": []}
            for aid, ainfo in areas_map.items():
                aname = (ainfo.get("name") if isinstance(ainfo, dict) else None) or str(aid)
                z = classify_area_zone(str(aid), str(aname))
                zones_in.setdefault(z, []).append({
                    "id": str(aid),
                    "name": str(aname),
                    "zone": z,
                    "entities": entities_by_area.get(str(aid), []),
                })
            layout = self._calculate_orthogonal_layout(zones_in)
            for rlist in layout.values():
                for r in rlist:
                    rooms_by_id[str(r["id"])] = dict(r)

        def _is_legacy_bottom_auto_badge(badge: dict[str, Any]) -> bool:
            """Detect unflagged legacy auto-generated bottom-row badges so rooms upgrade to center-outward pins."""
            if badge.get("custom"):
                return False
            bx, by = badge.get("x"), badge.get("y")
            if bx is None or by is None:
                return False
            try:
                fx, fy = float(bx), float(by)
            except (TypeError, ValueError):
                return False
            for r in rooms_by_id.values():
                rx = float(r.get("x", 0))
                ry = float(r.get("y", 0))
                rw = float(r.get("width", 0))
                rh = float(r.get("height", 0))
                if rx <= fx <= rx + rw and ry <= fy <= ry + rh:
                    if abs((ry + rh - 23.8) - fy) <= 1.5:
                        return True
            return False

        custom_badges: list[dict[str, Any]] = []
        deleted_eids: set[str] = set()
        custom_eids: set[str] = set()
        for b in raw_badges:
            if not isinstance(b, dict) or not b.get("entity_id"):
                continue
            eid = str(b["entity_id"])
            if b.get("delete") or b.get("deleted"):
                deleted_eids.add(eid)
            elif not _is_legacy_bottom_auto_badge(b):
                custom_badges.append(dict(b))
                custom_eids.add(eid)

        control_domains = {"light", "switch", "media_player", "fan", "climate", "cover", "lock", "vacuum"}

        # Determine which rooms already have user-placed controllable pins
        customized_rooms: set[str] = set()
        for b in custom_badges:
            eid = str(b["entity_id"])
            dom = eid.split(".")[0] if "." in eid else ""
            if dom not in control_domains:
                continue
            if eid in entity_area_map:
                customized_rooms.add(entity_area_map[eid])
            bx = b.get("x")
            by = b.get("y")
            if bx is not None and by is not None:
                try:
                    fx, fy = float(bx), float(by)
                    for rid, r in rooms_by_id.items():
                        rx = float(r.get("x", 0))
                        ry = float(r.get("y", 0))
                        rw = float(r.get("width", 0))
                        rh = float(r.get("height", 0))
                        if rx <= fx <= rx + rw and ry <= fy <= ry + rh:
                            customized_rooms.add(rid)
                except (TypeError, ValueError):
                    pass

        effective_badges = list(custom_badges)
        for rid, r in rooms_by_id.items():
            if rid in deleted_rooms or rid in customized_rooms:
                continue
            room_ents = entities_by_area.get(rid, [])
            if not room_ents:
                continue
            rx = float(r.get("x", 0))
            ry = float(r.get("y", 0))
            rw = float(r.get("width", 0))
            rh = float(r.get("height", 0))
            if rw <= 0 or rh <= 0:
                continue

            ainfo = areas_map.get(rid, {})
            rname = str(r.get("name") or (ainfo.get("name") if isinstance(ainfo, dict) else None) or rid)
            bp = GROUND_AND_OUTDOOR_BLUEPRINT.get(rid) or UPPER_FLOOR_BLUEPRINT.get(rid) or {}
            sub_zones_count = len(r.get("sub_zones") or bp.get("sub_zones") or [])
            has_container = bool(r.get("container_bounds") or r.get("parent_container") or bp.get("container_bounds") or bp.get("parent_container"))

            max_pins, _ = compute_room_center_pin_positions(
                rx, ry, rw, rh, count=0, sub_zones_count=sub_zones_count, has_container=has_container
            )
            ctrls = [
                c for c in select_intelligent_room_controls(
                    room_ents, valid_eids, area_name=rname, area_id=rid, max_controls=max_pins, devices_map=devices_map
                )
                if c["entity"] not in deleted_eids and c["entity"] not in custom_eids
            ]
            if not ctrls:
                continue

            _, positions = compute_room_center_pin_positions(
                rx, ry, rw, rh, count=len(ctrls), sub_zones_count=sub_zones_count, has_container=has_container
            )
            for ctrl, (px, py) in zip(ctrls, positions, strict=False):
                effective_badges.append({
                    "entity_id": ctrl["entity"],
                    "x": px,
                    "y": py,
                    "area_id": rid,
                    "auto_default": True,
                })

        return effective_badges

    def _place_zone_rooms(
        self,
        rooms: list[dict[str, Any]],
        zone_key: str,
        blueprint_map: dict[str, dict[str, Any]],
        base_y: int,
        y_shift: int,
        used_boxes: list[tuple[int, int, int, int]],
    ) -> list[dict[str, Any]]:
        """Place rooms for a given zone using architectural blueprints or non-overlapping grid fallback."""
        def _overlaps(x: int, y: int, w: int, h: int) -> bool:
            for ux, uy, uw, uh in used_boxes:
                if (x < ux + uw) and (ux < x + w) and (y < uy + uh) and (uy < y + h):
                    return True
            return False

        placed: list[dict[str, Any]] = []
        unmapped_idx = 0
        for room in rooms:
            norm_id = normalize_area_key(room["id"])
            norm_name = normalize_area_key(room["name"])
            bp = blueprint_map.get(norm_id) or blueprint_map.get(norm_name)
            if not bp:
                for bp_key, bp_val in blueprint_map.items():
                    if (
                        norm_id.endswith(f"_{bp_key}")
                        or norm_name.endswith(f"_{bp_key}")
                        or norm_id.startswith(f"{bp_key}_")
                        or norm_name.startswith(f"{bp_key}_")
                    ):
                        bp = bp_val
                        break

            if bp and not _overlaps(bp["x"], bp["y"] + y_shift, bp["width"], bp["height"]):
                x = bp["x"]
                y = bp["y"] + y_shift
                w = bp["width"]
                h = bp["height"]
                extra_meta = {
                    k: v
                    for k, v in bp.items()
                    if k not in ("x", "y", "width", "height")
                }
                if y_shift and "container_bounds" in extra_meta:
                    cb = extra_meta["container_bounds"]
                    extra_meta["container_bounds"] = (cb[0], cb[1] + y_shift, cb[2], cb[3])
                if y_shift and "doors" in extra_meta:
                    shifted_doors = []
                    for d_entry in extra_meta["doors"]:
                        norm_d = normalize_door_spec(d_entry)
                        if norm_d.get("side") in ("left", "right"):
                            norm_d["pos"] = norm_d.get("pos", 0) + y_shift
                        shifted_doors.append(norm_d)
                    extra_meta["doors"] = shifted_doors
                if y_shift and "windows" in extra_meta:
                    shifted_windows = []
                    for w_entry in extra_meta["windows"]:
                        norm_w = normalize_window_spec(w_entry)
                        if norm_w.get("side") in ("left", "right"):
                            norm_w["pos"] = norm_w.get("pos", 0) + y_shift
                        shifted_windows.append(norm_w)
                    extra_meta["windows"] = shifted_windows
            else:
                # Size from walkthrough room_shapes if available
                wf = (getattr(self, "_metadata", {}) or {}).get("walkthrough_features") or {}
                shapes_map = wf.get("room_shapes", {}) if isinstance(wf, dict) else {}
                dir_conns = wf.get("directional_connections", []) if isinstance(wf, dict) else []
                shape_info = shapes_map.get(norm_id) or shapes_map.get(room["id"]) or {}
                shape_kind = str(shape_info.get("shape", "square")).lower()
                size_kind = str(shape_info.get("size", "medium")).lower()
                dim_table = {
                    ("wide", "large"): (340, 170),
                    ("wide", "medium"): (280, 130),
                    ("wide", "small"): (210, 105),
                    ("tall", "large"): (180, 240),
                    ("tall", "medium"): (150, 200),
                    ("tall", "small"): (120, 160),
                    ("corridor", "large"): (380, 75),
                    ("corridor", "medium"): (300, 70),
                    ("corridor", "small"): (220, 65),
                    ("square", "large"): (260, 200),
                    ("square", "medium"): (210, 150),
                    ("square", "small"): (140, 110),
                }
                room_w, room_h = dim_table.get((shape_kind, size_kind), (250, 140))

                # Try placing flush against a connected already-placed room on the video-observed side
                placed_by_id = {normalize_area_key(p["id"]): p for p in placed}
                opposite_side = {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}
                cand_coords: list[tuple[int, int]] = []
                for dc in dir_conns:
                    if not isinstance(dc, dict):
                        continue
                    f_key = normalize_area_key(str(dc.get("from", "")))
                    t_key = normalize_area_key(str(dc.get("to", "")))
                    side = str(dc.get("side", "")).lower()
                    anchor = None
                    place_side = None
                    if t_key == norm_id and f_key in placed_by_id:
                        anchor = placed_by_id[f_key]
                        place_side = side
                    elif f_key == norm_id and t_key in placed_by_id:
                        anchor = placed_by_id[t_key]
                        place_side = opposite_side.get(side)
                    if anchor and place_side:
                        ax, ay, aw, ah = int(anchor["x"]), int(anchor["y"]), int(anchor["width"]), int(anchor["height"])
                        if place_side == "right":
                            cand_coords.append((ax + aw, ay))
                        elif place_side == "left":
                            cand_coords.append((ax - room_w, ay))
                        elif place_side == "bottom":
                            cand_coords.append((ax, ay + ah))
                        elif place_side == "top":
                            cand_coords.append((ax, ay - room_h))

                chosen_xy = None
                for cx, cy in cand_coords:
                    if cx >= 20 and cy >= 40 and not _overlaps(cx, cy, room_w, room_h):
                        chosen_xy = (cx, cy)
                        break

                if chosen_xy:
                    x, y = chosen_xy
                else:
                    col = unmapped_idx % 4
                    row = unmapped_idx // 4
                    x = 60 + col * (room_w + 16)
                    y = base_y + row * (room_h + 16)
                    while _overlaps(x, y, room_w, room_h):
                        y += room_h + 16
                    unmapped_idx += 1
                w, h = room_w, room_h
                extra_meta = {}

            used_boxes.append((x, y, w, h))
            placed.append({
                "id": room["id"],
                "name": room["name"],
                "zone": zone_key,
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "entities": room.get("entities", []),
                "adjacent_areas": room.get("adjacent_areas", []),
                **extra_meta,
            })
        return placed

    def _apply_walkthrough_features(self, layout: dict[str, list[dict[str, Any]]]) -> None:
        """Enrich placed rooms with walkthrough-detected stairs, pool/deck, and covered front porch."""
        meta = getattr(self, "_metadata", {}) or {}
        if not isinstance(meta, dict):
            return
        walkthrough_completed = bool(meta.get("walkthrough_completed", False))
        spoken_order = {str(s).lower() for s in (meta.get("spoken_order") or [])}
        wf = meta.get("walkthrough_features") or {}
        stairs_list = wf.get("stairs", []) if isinstance(wf, dict) else []
        outdoor_list = wf.get("outdoor_features", []) if isinstance(wf, dict) else []
        dir_conns_check = wf.get("directional_connections", []) if isinstance(wf, dict) else []

        if not (walkthrough_completed or spoken_order or stairs_list or outdoor_list or dir_conns_check):
            return

        placed_outdoor_ids = {str(r.get("id", "")).lower() for r in layout.get("outdoor", [])}
        all_rooms = [r for r_list in layout.values() for r in r_list]
        room_by_id = {str(r.get("id", "")).lower(): r for r in all_rooms}

        for st in stairs_list:
            if not isinstance(st, dict):
                continue
            rid = str(st.get("room", "")).lower()
            target = room_by_id.get(rid)
            if not target:
                continue
            direction = str(st.get("direction", "up")).lower()
            if direction == "down":
                target["has_stairs_down"] = True
            else:
                target["has_stairs_up"] = True
            label = str(st.get("label") or "").strip()
            if label and not target.get("_custom_sub_zones"):
                sz = list(target.get("sub_zones") or [])
                if label not in sz:
                    sz.append(label)
                target["sub_zones"] = sz

        for feat in outdoor_list:
            if not isinstance(feat, dict):
                continue
            rid = str(feat.get("room", "")).lower()
            ftype = str(feat.get("feature", "")).lower()
            target = room_by_id.get(rid)
            if not target:
                continue
            if ftype == "pool" and "pool" not in placed_outdoor_ids:
                target["has_pool"] = True
            elif ftype == "front_porch":
                target["has_front_porch"] = True

        # Ensure directional_connections from video analysis have shared-wall doorways/openings
        dir_conns = wf.get("directional_connections", []) if isinstance(wf, dict) else []
        for dc in dir_conns:
            if not isinstance(dc, dict):
                continue
            r1 = room_by_id.get(str(dc.get("from", "")).lower())
            r2 = room_by_id.get(str(dc.get("to", "")).lower())
            if not r1 or not r2:
                continue
            ctype = str(dc.get("type", "door")).lower()
            style = "cased" if ctype == "open" else "swing"
            x1, y1, w1, h1 = int(r1["x"]), int(r1["y"]), int(r1["width"]), int(r1["height"])
            x2, y2, w2, h2 = int(r2["x"]), int(r2["y"]), int(r2["width"]), int(r2["height"])

            shared_side = None
            door_pos = None
            # Horizontal shared wall (top/bottom)
            ox = min(x1 + w1, x2 + w2) - max(x1, x2)
            oy = min(y1 + h1, y2 + h2) - max(y1, y2)
            if ox >= 28:
                if abs((y1 + h1) - y2) <= 6:
                    shared_side = "bottom"
                    door_pos = int(max(x1, x2) + ox / 2 - 18)
                elif abs((y2 + h2) - y1) <= 6:
                    shared_side = "top"
                    door_pos = int(max(x1, x2) + ox / 2 - 18)
            elif oy >= 28:
                if abs((x1 + w1) - x2) <= 6:
                    shared_side = "right"
                    door_pos = int(max(y1, y2) + oy / 2 - 18)
                elif abs((x2 + w2) - x1) <= 6:
                    shared_side = "left"
                    door_pos = int(max(y1, y2) + oy / 2 - 18)

            if shared_side and door_pos is not None:
                existing_doors = [normalize_door_spec(d, r1) for d in (r1.get("doors") or [])]
                if not any(d.get("side") == shared_side for d in existing_doors):
                    r1_doors = list(r1.get("doors") or [])
                    r1_doors.append((shared_side, door_pos, 36, f"To {r2.get('name', r2.get('id'))}", "inward-left", style))
                    r1["doors"] = r1_doors

    def _calculate_orthogonal_layout(
        self, zones: dict[str, list[dict[str, Any]]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Compute architectural floorplan coordinates (x, y, width, height) for Ground+Outdoor and Upper floors."""
        layout: dict[str, list[dict[str, Any]]] = {
            "main": [],
            "upper": [],
            "outdoor": [],
        }

        used_boxes: list[tuple[int, int, int, int]] = []

        # 1. Ground Floor & Outdoor Plan (Combined into one contiguous architectural floorplan at the top)
        for zone_key in ("outdoor", "main"):
            base_y = 85 if zone_key == "main" else 585
            layout[zone_key] = self._place_zone_rooms(
                zones.get(zone_key, []),
                zone_key,
                GROUND_AND_OUTDOOR_BLUEPRINT,
                base_y=base_y,
                y_shift=0,
                used_boxes=used_boxes,
            )

        # Compute bottom of Ground + Outdoor plan so Upper Level is always drawn separately below
        ground_max_y = 0
        for z_k in ("main", "outdoor"):
            for r in layout[z_k]:
                ground_max_y = max(ground_max_y, r["y"] + r["height"])

        upper_base_offset = max(805, ground_max_y + 95) if ground_max_y > 0 else 85
        bp_shift_y = upper_base_offset - 805

        # 2. Upper Level Floor Plan (Drawn Separately below Ground + Outdoor Plan)
        layout["upper"] = self._place_zone_rooms(
            zones.get("upper", []),
            "upper",
            UPPER_FLOOR_BLUEPRINT,
            base_y=upper_base_offset,
            y_shift=bp_shift_y,
            used_boxes=used_boxes,
        )

        # 3. Apply custom layout room coordinates from metadata and SVG
        custom_rooms_map = {}
        if hasattr(self, "_metadata") and isinstance(self._metadata, dict):
            c_layout = self._metadata.get("custom_layout", {})
            if isinstance(c_layout, dict) and "rooms" in c_layout:
                for cr in c_layout["rooms"]:
                    if isinstance(cr, dict) and cr.get("id"):
                        custom_rooms_map[cr["id"]] = dict(cr)

        # Apply room bounds from in-memory SVG cache (asynchronously parsed, non-blocking)
        for aid_svg, b_val in getattr(self, "_cached_svg_room_bounds", {}).items():
            if aid_svg not in custom_rooms_map:
                custom_rooms_map[aid_svg] = dict(b_val)
            else:
                custom_rooms_map[aid_svg]["x"] = b_val["x"]
                custom_rooms_map[aid_svg]["y"] = b_val["y"]
                custom_rooms_map[aid_svg]["width"] = b_val["width"]
                custom_rooms_map[aid_svg]["height"] = b_val["height"]

        for room_list in layout.values():
            for r in room_list:
                rid = r.get("id")
                if rid in custom_rooms_map:
                    cr = custom_rooms_map[rid]
                    if "x" in cr and "y" in cr:
                        r["x"] = cr["x"]
                        r["y"] = cr["y"]
                    if "width" in cr:
                        r["width"] = cr["width"]
                    if "height" in cr:
                        r["height"] = cr["height"]
                    if cr.get("name"):
                        r["name"] = cr["name"]
                    if "sub_zones" in cr and isinstance(cr["sub_zones"], list):
                        r["sub_zones"] = list(cr["sub_zones"])
                        r["_custom_sub_zones"] = True
                    if isinstance(cr.get("features"), dict):
                        r["features"] = dict(cr["features"])

        # Filter out deleted rooms
        deleted_rooms = set()
        if hasattr(self, "_metadata") and isinstance(self._metadata, dict):
            deleted_rooms = set(self._metadata.get("deleted_rooms", []))

        for zone_k in list(layout.keys()):
            layout[zone_k] = [r for r in layout[zone_k] if r.get("id") not in deleted_rooms]

        # Automatically enrich layout from walkthrough analysis, spoken_order, and spatial graph
        self._apply_walkthrough_features(layout)

        # Automatic exterior window placement for rooms that don't have windows defined
        all_placed = [r for r_list in layout.values() for r in r_list]
        for _z_key, r_list in layout.items():
            for r in r_list:
                if not r.get("windows"):
                    detected_wins = detect_exterior_windows(r, all_placed)
                    if detected_wins:
                        r["windows"] = detected_wins

        return layout

    def _calculate_isometric_layout(
        self, layout_by_zone: dict[str, list[dict[str, Any]]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Project 2D orthogonal room layouts into stacked 2.5D isometric spatial coordinates."""
        iso_layout: dict[str, list[dict[str, Any]]] = {
            "main": [],
            "upper": [],
            "outdoor": [],
        }

        origin_x = 650.0
        origin_y = 640.0
        scale = 0.58
        cx = 680.0
        cy = 385.0
        cos30 = 0.866025
        sin30 = 0.500000
        slab_thickness = 12.0

        def project(x: float, y: float, z: float) -> tuple[float, float]:
            dx = (x - cx) * scale
            dy = (y - cy) * scale
            ix = origin_x + (dx - dy) * cos30
            iy = origin_y + (dx + dy) * sin30 - z
            return round(ix, 1), round(iy, 1)

        # 1. Main & Outdoor (z = 0.0, Outdoor z = -6.0)
        for zone_k in ("outdoor", "main"):
            z_elevation = -6.0 if zone_k == "outdoor" else 0.0
            for r in layout_by_zone.get(zone_k, []):
                rx = float(r["x"])
                ry = float(r["y"])
                rw = float(r["width"])
                rh = float(r["height"])

                p1 = project(rx, ry, z_elevation)
                p2 = project(rx + rw, ry, z_elevation)
                p3 = project(rx + rw, ry + rh, z_elevation)
                p4 = project(rx, ry + rh, z_elevation)

                center = project(rx + rw / 2.0, ry + rh / 2.0, z_elevation)

                south_facet = [
                    p4,
                    p3,
                    (p3[0], round(p3[1] + slab_thickness, 1)),
                    (p4[0], round(p4[1] + slab_thickness, 1)),
                ]
                east_facet = [
                    p3,
                    p2,
                    (p2[0], round(p2[1] + slab_thickness, 1)),
                    (p3[0], round(p3[1] + slab_thickness, 1)),
                ]

                iso_r = dict(r)
                iso_r["iso_points"] = [p1, p2, p3, p4]
                iso_r["iso_points_str"] = f"{p1[0]},{p1[1]} {p2[0]},{p2[1]} {p3[0]},{p3[1]} {p4[0]},{p4[1]}"
                iso_r["iso_center"] = center
                iso_r["iso_south_facet"] = " ".join(f"{pt[0]},{pt[1]}" for pt in south_facet)
                iso_r["iso_east_facet"] = " ".join(f"{pt[0]},{pt[1]}" for pt in east_facet)
                iso_r["elevation"] = z_elevation
                iso_layout[zone_k].append(iso_r)

        # 2. Upper Level Floor (Suspended above ground floor at z = 320.0)
        upper_rooms = layout_by_zone.get("upper", [])
        if upper_rooms:
            min_u_y = min(float(r["y"]) for r in upper_rooms)
            y_shift = min_u_y - 85.0
            z_elevation_upper = 320.0

            for r in upper_rooms:
                rx = float(r["x"])
                ry_loc = float(r["y"]) - y_shift
                rw = float(r["width"])
                rh = float(r["height"])

                p1 = project(rx, ry_loc, z_elevation_upper)
                p2 = project(rx + rw, ry_loc, z_elevation_upper)
                p3 = project(rx + rw, ry_loc + rh, z_elevation_upper)
                p4 = project(rx, ry_loc + rh, z_elevation_upper)

                center = project(rx + rw / 2.0, ry_loc + rh / 2.0, z_elevation_upper)

                south_facet = [
                    p4,
                    p3,
                    (p3[0], round(p3[1] + slab_thickness, 1)),
                    (p4[0], round(p4[1] + slab_thickness, 1)),
                ]
                east_facet = [
                    p3,
                    p2,
                    (p2[0], round(p2[1] + slab_thickness, 1)),
                    (p3[0], round(p3[1] + slab_thickness, 1)),
                ]

                iso_r = dict(r)
                iso_r["iso_points"] = [p1, p2, p3, p4]
                iso_r["iso_points_str"] = f"{p1[0]},{p1[1]} {p2[0]},{p2[1]} {p3[0]},{p3[1]} {p4[0]},{p4[1]}"
                iso_r["iso_center"] = center
                iso_r["iso_south_facet"] = " ".join(f"{pt[0]},{pt[1]}" for pt in south_facet)
                iso_r["iso_east_facet"] = " ".join(f"{pt[0]},{pt[1]}" for pt in east_facet)
                iso_r["elevation"] = z_elevation_upper
                iso_layout["upper"].append(iso_r)

        return iso_layout

    def _render_isometric_svg_markup(
        self,
        iso_layout: dict[str, list[dict[str, Any]]],
        accent_color: str,
        outdoor_accent: str,
    ) -> str:
        """Render stacked 2.5D multi-floor architectural isometric view SVG group."""
        parts: list[str] = []

        main_rooms = iso_layout.get("main", [])
        outdoor_rooms = iso_layout.get("outdoor", [])
        upper_rooms = iso_layout.get("upper", [])

        # 1. Multi-Floor Structural Connectors
        parts.append('    <!-- ISO: MULTI-FLOOR STRUCTURAL CONNECTORS & VERTICAL RISERS -->\n')
        parts.append('    <g id="iso-connectors" data-connector="multi-floor">\n')

        origin_x = 650.0
        origin_y = 640.0
        scale = 0.58
        cx = 680.0
        cy = 385.0
        cos30 = 0.866025
        sin30 = 0.500000

        def project(x: float, y: float, z: float) -> tuple[float, float]:
            dx = (x - cx) * scale
            dy = (y - cy) * scale
            ix = origin_x + (dx - dy) * cos30
            iy = origin_y + (dx + dy) * sin30 - z
            return round(ix, 1), round(iy, 1)

        corners = [(180.0, 85.0), (1140.0, 85.0), (180.0, 465.0), (1140.0, 465.0)]
        for cx_pt, cy_pt in corners:
            g_pt = project(cx_pt, cy_pt, 0.0)
            u_pt = project(cx_pt, cy_pt, 320.0)
            parts.append(
                f'      <line x1="{g_pt[0]}" y1="{g_pt[1]}" x2="{u_pt[0]}" y2="{u_pt[1]}" class="iso-structural-pillar" />\n'
            )

        stair_g = project(840.0, 290.0, 0.0)
        stair_u = project(960.0, 160.0, 320.0)
        parts.append(
            '      <!-- Multi-Floor Staircase Connector -->\n'
            f'      <path d="M {stair_g[0]} {stair_g[1]} L {stair_g[0] + 25} {stair_g[1] - 80} '
            f'L {stair_u[0] - 25} {stair_u[1] + 80} L {stair_u[0]} {stair_u[1]}" '
            'class="iso-stairs-step" fill="none" stroke-dasharray="6 3" />\n'
        )
        parts.append('    </g>\n')

        # 2. Ground & Outdoor Slab (z = 0, z = -6)
        if main_rooms or outdoor_rooms:
            parts.append('    <!-- ISO FLOOR: GROUND & OUTDOOR SLAB -->\n')
            parts.append('    <g id="iso-ground" data-floor="ground">\n')
            parts.append('      <text x="65" y="470" class="iso-floor-badge">Ground &amp; Outdoor</text>\n')
            parts.append('      <text x="65" y="492" class="iso-floor-subbadge">Level 1 • Elevation 0.0m</text>\n')

            for r in outdoor_rooms + main_rooms:
                parts.append(self._render_iso_room(r, accent_color, outdoor_accent))
            parts.append('    </g>\n')

        # 3. Upper Level Floor Slab (z = 320)
        if upper_rooms:
            parts.append('    <!-- ISO FLOOR: UPPER LEVEL SLAB -->\n')
            parts.append('    <g id="iso-upper" data-floor="upper">\n')
            parts.append('      <text x="65" y="125" class="iso-floor-badge">Upper Level</text>\n')
            parts.append('      <text x="65" y="147" class="iso-floor-subbadge">Level 2 • Elevation +3.2m</text>\n')

            for r in upper_rooms:
                parts.append(self._render_iso_room(r, accent_color, outdoor_accent))
            parts.append('    </g>\n')

        return "".join(parts)

    def _render_iso_room(
        self,
        room: dict[str, Any],
        accent_color: str,
        outdoor_accent: str,
    ) -> str:
        """Render a single 3D isometric room slab with facets, headers, and device badges."""
        rid = html.escape(str(room.get("id", "room")), quote=True)
        rname = html.escape(str(room.get("name", room.get("id", "room"))))
        rzone = html.escape(str(room.get("zone", "main")), quote=True)
        pts_str = html.escape(str(room.get("iso_points_str", "")), quote=True)
        south_facet = html.escape(str(room.get("iso_south_facet", "")), quote=True)
        east_facet = html.escape(str(room.get("iso_east_facet", "")), quote=True)
        center = room.get("iso_center", (650.0, 500.0))
        entities = room.get("entities", [])
        buckets = classify_area_entities(entities)

        box_classes = ["iso-floor-slab"]
        if room.get("zone") == "outdoor":
            if room.get("is_water"):
                box_classes.append("water-box")
            else:
                box_classes.append("outdoor-box")

        sub_zones = room.get("sub_zones", [])
        subzone_preview = html.escape(str(sub_zones[0])) if sub_zones else ""

        room_parts = [
            f'      <g class="room-group iso-room-group" data-area-id="{rid}" data-zone="{rzone}" data-iso-cx="{center[0]}" data-iso-cy="{center[1]}">\n',
        ]
        if south_facet:
            room_parts.append(f'        <polygon points="{south_facet}" class="iso-slab-facet south-facet" />\n')
        if east_facet:
            room_parts.append(f'        <polygon points="{east_facet}" class="iso-slab-facet east-facet" />\n')
        room_parts.extend([
            f'        <polygon points="{pts_str}" class="{" ".join(box_classes)}" />\n',
            f'        <text x="{center[0]}" y="{center[1] - 4}" class="iso-room-header" text-anchor="middle">{rname}</text>\n',
        ])
        if subzone_preview:
            room_parts.append(
                f'        <text x="{center[0]}" y="{center[1] + 11}" class="iso-subzone-pill" text-anchor="middle">{subzone_preview}</text>\n'
            )

        # Entity badges in 3D
        badge_spacing = 22
        active_badges = []
        for domain_key, icon_char in (
            ("lights", "💡"),
            ("media", "📺"),
            ("fans", "🌀"),
            ("vacuums", "🧹"),
            ("covers", "🚪"),
            ("switches", "🔌"),
            ("climates", "🌡️"),
            ("motion", "🚶"),
            ("cameras", "📹"),
            ("locks", "🔒"),
        ):
            domain_entities = buckets.get(domain_key, [])
            if domain_entities:
                active_badges.append((domain_entities[0], icon_char))

        total_b = len(active_badges)
        for idx, (raw_eid, icon_char) in enumerate(active_badges[:4]):
            eid = html.escape(str(raw_eid), quote=True)
            offset_x = (idx - (min(total_b, 4) - 1) / 2.0) * badge_spacing
            bx = round(center[0] + offset_x, 1)
            by = round(center[1] + 25.0, 1)
            room_parts.append(
                f'        <g class="iso-marker-badge" data-entity-id="{eid}" transform="translate({bx}, {by})">\n'
                f'          <circle cx="0" cy="0" r="9" class="badge-circle" />\n'
                f'          <text class="badge-icon">{icon_char}</text>\n'
                f'        </g>\n'
            )

        room_parts.append('      </g>\n')
        return "".join(room_parts)

    def _make_3d_primary_svg(self, svg_content: str) -> str:
        """Create a standalone 3D isometric SVG where 3D is active and 2D is hidden."""
        res = re.sub(
            r'viewBox="0 0 1300 \d+"',
            'viewBox="0 0 1300 1080"',
            svg_content,
            count=1,
        )
        res = re.sub(
            r'height="\d+"',
            'height="1080"',
            res,
            count=1,
        )
        res = res.replace('<g id="view-mode-2d">', '<g id="view-mode-2d" style="display: none;">', 1)
        res = res.replace('<g id="view-mode-3d" style="display: none;">', '<g id="view-mode-3d">', 1)
        return res

    def _get_canvas_height(self, layout_by_zone: dict[str, list[dict[str, Any]]]) -> int:
        """Compute total SVG canvas height required to fit all positioned rooms without clipping."""
        max_bottom = 0
        for rooms in layout_by_zone.values():
            for r in rooms:
                bottom = r["y"] + r["height"]
                if bottom > max_bottom:
                    max_bottom = bottom
        return max(880, max_bottom + 65)

    def _render_svg_markup(
        self,
        layout_by_zone: dict[str, list[dict[str, Any]]],
        entities: list[dict[str, Any]],
        theme: str = "cyberpunk",
        iso_layout_by_zone: dict[str, list[dict[str, Any]]] | None = None,
    ) -> str:
        """Render architectural vector SVG floor plans (Ground+Outdoor combined, Upper Level separate, and 3D Isometric)."""
        accent_color = "#0ea5e9"  # Sky Cyan
        accent_secondary = "#a855f7"  # Lavender Purple
        outdoor_accent = "#10b981"  # Emerald Perimeter
        bg_color = "#070b14"
        card_bg = "#0f172a"
        wall_color = "#38bdf8"
        text_color = "#f8fafc"

        if theme == "blueprint":
            accent_color = "#38bdf8"
            wall_color = "#7dd3fc"
            bg_color = "#0b192c"
            card_bg = "#1e3e62"
        elif theme == "emerald":
            accent_color = "#10b981"
            wall_color = "#34d399"
            bg_color = "#022c22"
            card_bg = "#064e3b"

        entity_by_id = {e["entity_id"]: e for e in entities}
        canvas_height = self._get_canvas_height(layout_by_zone)

        svg_parts = [
            f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1300 {canvas_height}" data-full-viewbox="0 0 1300 {canvas_height}" data-iso-viewbox="0 0 1300 1080" width="1300" height="{canvas_height}" class="otis-floorplan {theme}">
  <defs>
    <style>
      .otis-floorplan {{
        background: {bg_color};
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        user-select: none;
      }}
      .floor-zone {{
        transition: opacity 0.25s ease, filter 0.25s ease;
      }}
      .plan-frame {{
        fill: rgba(15, 23, 42, 0.38);
        stroke: rgba(56, 189, 248, 0.24);
        stroke-width: 1.5;
        rx: 14px;
        pointer-events: none;
      }}
      .room-box {{
        fill: {card_bg};
        fill-opacity: 0.9;
        stroke: {wall_color};
        stroke-width: 2.5;
        rx: 3px;
        transition: all 0.25s ease;
        cursor: pointer;
        pointer-events: all;
      }}
      .room-box.outdoor-box {{
        fill: rgba(6, 78, 59, 0.28);
        stroke: {outdoor_accent};
        stroke-width: 2;
        stroke-dasharray: 6 3;
      }}
      .room-box.water-box {{
        fill: rgba(14, 165, 233, 0.22);
        stroke: #38bdf8;
        stroke-width: 2.2;
      }}
      .room-box.open-sub-box {{
        fill: rgba(30, 41, 59, 0.55);
        stroke: rgba(56, 189, 248, 0.45);
        stroke-width: 1.5;
        stroke-dasharray: 6 4;
      }}
      .room-box:hover {{
        fill-opacity: 1;
        stroke: {accent_color};
        filter: drop-shadow(0 0 10px {accent_color});
      }}
      .container-shell {{
        fill: none;
        stroke: {accent_color};
        stroke-width: 3.5;
        rx: 4px;
        pointer-events: none;
      }}
      .container-banner {{
        font-size: 10.5px;
        font-weight: 800;
        fill: #38bdf8;
        letter-spacing: 0.9px;
        text-transform: uppercase;
        pointer-events: none;
      }}
      .room-header {{
        font-size: 13px;
        font-weight: 700;
        fill: {text_color};
        letter-spacing: 0.3px;
        pointer-events: none;
      }}
      .subzone-pill {{
        font-size: 10px;
        font-weight: 600;
        fill: #94a3b8;
        pointer-events: none;
      }}
      .zone-title {{
        font-size: 15px;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        fill: {accent_color};
      }}
      .zone-subtitle {{
        font-size: 11px;
        font-weight: 600;
        fill: #94a3b8;
        letter-spacing: 0.6px;
      }}
      .entity-badge, .iso-marker-badge {{
        display: inline;
        cursor: pointer;
        transition: transform 0.2s ease;
      }}
      .entity-badge:hover, .iso-marker-badge:hover {{
        transform: scale(1.2);
      }}
      .badge-circle {{ fill: rgba(15, 23, 42, 0.92); stroke: {accent_color}; stroke-width: 1.5; }}
      .badge-icon {{ fill: {text_color}; font-size: 10px; text-anchor: middle; dominant-baseline: middle; }}
      .door-cut, .door-leaf, .door-swing, .door-garage, .door-sliding, .window-cut, .window-sill, .window-pane, .window-cap {{
        pointer-events: none;
      }}
      .room-feature, .room-feature * {{
        pointer-events: all;
      }}
      .door-cut {{ stroke: {accent_secondary}; stroke-width: 4; stroke-linecap: round; }}
      .door-leaf {{ stroke: {accent_color}; stroke-width: 2.2; stroke-linecap: round; }}
      .door-swing {{ stroke: {accent_color}; stroke-width: 1.2; stroke-dasharray: 3 3; fill: none; opacity: 0.80; }}
      .door-garage {{ stroke: #94a3b8; stroke-width: 2.5; stroke-dasharray: 4 2; opacity: 0.85; }}
      .door-sliding {{ stroke: {accent_secondary}; stroke-width: 2.0; stroke-linecap: round; }}
      .window-cut {{ stroke: {bg_color}; stroke-width: 4; stroke-linecap: square; }}
      .window-sill {{ stroke: #64748b; stroke-width: 3.5; stroke-linecap: square; }}
      .window-pane {{ stroke: #38bdf8; stroke-width: 1.4; opacity: 0.90; }}
      .window-cap {{ stroke: #64748b; stroke-width: 2; }}
      .stairs-step {{ stroke: #38bdf8; stroke-width: 1.2; opacity: 0.65; }}
      /* 3D Isometric Styles */
      .iso-room-group {{
        cursor: pointer;
        transition: transform 0.25s ease, filter 0.25s ease;
      }}
      .iso-room-group:hover .iso-floor-slab {{
        fill-opacity: 1;
        stroke: {accent_color};
        filter: drop-shadow(0 0 12px {accent_color});
      }}
      .iso-floor-slab {{
        fill: {card_bg};
        fill-opacity: 0.88;
        stroke: {wall_color};
        stroke-width: 2.0;
        transition: all 0.25s ease;
      }}
      .iso-floor-slab.outdoor-box {{
        fill: rgba(6, 78, 59, 0.32);
        stroke: {outdoor_accent};
        stroke-width: 1.8;
        stroke-dasharray: 6 3;
      }}
      .iso-floor-slab.water-box {{
        fill: rgba(14, 165, 233, 0.28);
        stroke: #38bdf8;
        stroke-width: 2.0;
      }}
      .iso-slab-facet {{
        transition: all 0.25s ease;
      }}
      .iso-slab-facet.south-facet {{
        fill: rgba(15, 23, 42, 0.95);
        stroke: rgba(56, 189, 248, 0.45);
        stroke-width: 1.2;
      }}
      .iso-slab-facet.east-facet {{
        fill: rgba(30, 41, 59, 0.85);
        stroke: rgba(56, 189, 248, 0.35);
        stroke-width: 1.2;
      }}
      .iso-room-header {{
        font-size: 12px;
        font-weight: 700;
        fill: {text_color};
        letter-spacing: 0.4px;
        pointer-events: none;
      }}
      .iso-subzone-pill {{
        font-size: 9px;
        font-weight: 600;
        fill: #94a3b8;
        letter-spacing: 0.2px;
        pointer-events: none;
      }}
      .iso-structural-pillar {{
        stroke: rgba(56, 189, 248, 0.40);
        stroke-width: 1.5;
        stroke-dasharray: 4 4;
      }}
      .iso-floor-badge {{
        font-size: 13px;
        font-weight: 800;
        letter-spacing: 1.2px;
        text-transform: uppercase;
        fill: {accent_color};
      }}
      .iso-floor-subbadge {{
        font-size: 10px;
        font-weight: 600;
        fill: #94a3b8;
        letter-spacing: 0.4px;
      }}
      .iso-stairs-step {{
        stroke: #38bdf8;
        stroke-width: 2.0;
        fill: rgba(56, 189, 248, 0.25);
      }}
    </style>
  </defs>

  <!-- Architectural Blueprint Grid Texture -->
  <g opacity="0.10" style="pointer-events: none;">
    <pattern id="grid" width="30" height="30" patternUnits="userSpaceOnUse">
      <path d="M 30 0 L 0 0 0 30" fill="none" stroke="{accent_color}" stroke-width="0.8" />
    </pattern>
    <rect width="1300" height="{canvas_height}" fill="url(#grid)" style="pointer-events: none;" />
  </g>
'''
        ]

        main_rooms = layout_by_zone.get("main", [])
        outdoor_rooms = layout_by_zone.get("outdoor", [])
        upper_rooms = layout_by_zone.get("upper", [])

        # Wrap 2D orthogonal views
        svg_parts.append('  <!-- 2D ORTHOGONAL BLUEPRINT VIEW -->\n')
        svg_parts.append('  <g id="view-mode-2d">\n')

        # PLAN 1: GROUND FLOOR & OUTDOOR PERIMETER (Combined Architectural Plan)
        if main_rooms or outdoor_rooms:
            all_ground = main_rooms + outdoor_rooms
            min_y = min(r["y"] for r in all_ground)
            max_y = max(r["y"] + r["height"] for r in all_ground)
            frame_y = max(20, min_y - 52)
            frame_h = (max_y - frame_y) + 24
            g_vb_y = max(0, frame_y - 16)
            g_vb_h = frame_h + 32

            svg_parts.append('  <!-- PLAN 1: GROUND FLOOR & OUTDOOR PERIMETER -->\n')
            svg_parts.append(f'  <g id="plan-ground" data-plan="ground" data-viewbox="0 {g_vb_y} 1300 {g_vb_h}">\n')
            svg_parts.append(f'    <rect x="40" y="{frame_y}" width="1220" height="{frame_h}" class="plan-frame" />\n')

            if main_rooms:
                svg_parts.append('    <!-- ZONE: MAIN FLOOR -->\n')
                svg_parts.append('    <g class="floor-zone" data-zone="main">\n')
                svg_parts.append(
                    f'      <text x="65" y="{frame_y + 28}" class="zone-title">Ground / Main Floor</text>\n'
                )
                svg_parts.append(
                    f'      <text x="275" y="{frame_y + 28}" class="zone-subtitle">'
                    '• Architectural Plan with Great Room (Living, Kitchen &amp; Nook) &amp; Outdoor Perimeter</text>\n'
                )
                for r in main_rooms:
                    svg_parts.append(self._render_room_svg(r, entity_by_id, accent_color))
                svg_parts.append('    </g>\n')

            if outdoor_rooms:
                svg_parts.append('    <!-- ZONE: OUTDOOR PERIMETER -->\n')
                svg_parts.append('    <g class="floor-zone" data-zone="outdoor">\n')
                svg_parts.append(
                    f'      <text x="980" y="{frame_y + 28}" class="zone-title" style="fill: {outdoor_accent}; font-size: 13px;">'
                    'Outdoor &amp; Perimeter</text>\n'
                )
                for r in outdoor_rooms:
                    svg_parts.append(self._render_room_svg(r, entity_by_id, accent_color))
                svg_parts.append('    </g>\n')
            custom_feats = (self._metadata.get("custom_layout", {}) if isinstance(getattr(self, "_metadata", None), dict) else {}).get("custom_features") or []
            ground_cfs = [cf for cf in custom_feats if isinstance(cf, dict) and cf.get("id") and str(cf.get("zone") or "main").lower() != "upper"]
            if ground_cfs:
                svg_parts.append('    <g class="room-features-overlay">\n')
                for cf in ground_cfs:
                    svg_parts.append(self._render_custom_feature_svg(cf))
                svg_parts.append('    </g>\n')
            svg_parts.append('  </g>\n')

        # PLAN 2: UPPER LEVEL FLOOR PLAN (Drawn Separately)
        if upper_rooms:
            min_u_y = min(r["y"] for r in upper_rooms)
            max_u_y = max(r["y"] + r["height"] for r in upper_rooms)
            u_frame_y = max(20, min_u_y - 52)
            u_frame_h = (max_u_y - u_frame_y) + 24
            u_vb_y = max(0, u_frame_y - 16)
            u_vb_h = u_frame_h + 32

            svg_parts.append('  <!-- PLAN 2: UPPER LEVEL -->\n')
            svg_parts.append('  <!-- ZONE: UPPER LEVEL -->\n')
            svg_parts.append(
                f'  <g id="plan-upper" data-plan="upper" data-viewbox="0 {u_vb_y} 1300 {u_vb_h}" class="floor-zone" data-zone="upper">\n'
            )
            svg_parts.append(f'    <rect x="40" y="{u_frame_y}" width="1220" height="{u_frame_h}" class="plan-frame" />\n')
            svg_parts.append(
                f'    <text x="65" y="{u_frame_y + 28}" class="zone-title">Upper Level &amp; Suites</text>\n'
            )
            svg_parts.append(
                f'    <text x="295" y="{u_frame_y + 28}" class="zone-subtitle">'
                '• Separate Second-Floor Architectural Plan (Stair Landing, Upper Hallway, Suites &amp; Theater)</text>\n'
            )
            for r in upper_rooms:
                svg_parts.append(self._render_room_svg(r, entity_by_id, accent_color))
            custom_feats = (self._metadata.get("custom_layout", {}) if isinstance(getattr(self, "_metadata", None), dict) else {}).get("custom_features") or []
            upper_cfs = [cf for cf in custom_feats if isinstance(cf, dict) and cf.get("id") and str(cf.get("zone") or "main").lower() == "upper"]
            if upper_cfs:
                svg_parts.append('    <g class="room-features-overlay">\n')
                for cf in upper_cfs:
                    svg_parts.append(self._render_custom_feature_svg(cf))
                svg_parts.append('    </g>\n')
            svg_parts.append('  </g>\n')

        svg_parts.append('  </g>  <!-- /view-mode-2d -->\n\n')

        # 3D MULTI-FLOOR ISOMETRIC VIEW
        if iso_layout_by_zone:
            svg_parts.append('  <!-- 3D MULTI-FLOOR ISOMETRIC VIEW -->\n')
            svg_parts.append('  <g id="view-mode-3d" style="display: none;">\n')
            svg_parts.append(
                self._render_isometric_svg_markup(
                    iso_layout_by_zone, accent_color, outdoor_accent
                )
            )
            svg_parts.append('  </g>  <!-- /view-mode-3d -->\n')

        svg_parts.append('</svg>\n')
        return "".join(svg_parts)

    def _render_custom_feature_svg(self, feat: dict[str, Any]) -> str:
        """Render an independent draggable stairs or labeled box SVG group."""
        fid = html.escape(str(feat.get("id") or "custom"), quote=True)
        ftype = str(feat.get("type") or "box").lower()
        zone = html.escape(str(feat.get("zone") or "main").lower(), quote=True)
        fx = round(float(feat.get("x", 400.0)), 1)
        fy = round(float(feat.get("y", 250.0)), 1)
        if ftype == "stairs":
            lines = [
                f'    <g class="room-feature custom-feature" data-custom-id="{fid}" data-feature="stairs" data-zone="{zone}" data-x="{fx}" data-y="{fy}">\n',
                f'      <rect x="{fx}" y="{fy}" width="44" height="28" fill="rgba(56, 189, 248, 0.12)" stroke="#38bdf8" stroke-width="1" rx="2" class="stairs-step" />\n',
            ]
            for step_i in range(1, 5):
                lx = round(fx + step_i * 9, 1)
                lines.append(
                    f'      <line x1="{lx}" y1="{fy}" x2="{lx}" y2="{round(fy + 28, 1)}" class="stairs-step" />\n'
                )
            lines.append("    </g>\n")
            return "".join(lines)
        fw = round(max(60.0, float(feat.get("width", 150.0))), 1)
        fh = round(max(24.0, float(feat.get("height", 56.0))), 1)
        label = html.escape(str(feat.get("label") or "CUSTOM ZONE").upper())
        label_attr = html.escape(str(feat.get("label") or "CUSTOM ZONE"), quote=True)
        return (
            f'    <g class="room-feature custom-feature" data-custom-id="{fid}" data-feature="box" data-zone="{zone}" data-x="{fx}" data-y="{fy}" data-width="{fw}" data-height="{fh}" data-label="{label_attr}">\n'
            f'      <rect x="{fx}" y="{fy}" width="{fw}" height="{fh}" rx="6" fill="rgba(6, 182, 212, 0.14)" stroke="#22d3ee" stroke-width="1.2" stroke-dasharray="4 2" />\n'
            f'      <text x="{round(fx + fw / 2.0, 1)}" y="{round(fy + fh / 2.0 + 4.0, 1)}" text-anchor="middle" fill="#67e8f9" font-size="9" font-weight="700" letter-spacing="1.2">{label}</text>\n'
            f'    </g>\n'
        )

    def _render_room_svg(
        self, room: dict[str, Any], entity_by_id: dict[str, Any], accent_color: str
    ) -> str:
        """Render an architectural room polygon/footprint with sub-zones, doors, stairs, and entity badges."""
        x = room["x"]
        y = room["y"]
        w = room["width"]
        h = room["height"]
        rid = room["id"]
        rname = room["name"]
        rzone = room.get("zone", "main")
        entities = room.get("entities", [])

        buckets = classify_area_entities(entities)

        box_classes = ["room-box"]
        if rzone == "outdoor":
            if room.get("is_water"):
                box_classes.append("water-box")
            else:
                box_classes.append("outdoor-box")
        elif room.get("parent_container") or room.get("open_right") or room.get("open_left"):
            box_classes.append("open-sub-box")

        rid_esc = html.escape(str(rid), quote=True)
        rzone_esc = html.escape(str(rzone), quote=True)
        parts = [
            f'  <g class="room room-group" id="area-{rid_esc}" data-area-id="{rid_esc}" data-zone="{rzone_esc}">\n',
            f'    <rect x="{x}" y="{y}" width="{w}" height="{h}" class="{" ".join(box_classes)}" />\n',
        ]

        # If this room is the anchor of a unified multi-zone container (e.g., Great Room or Master Suite),
        # draw the outer unified architectural shell and container banner
        if room.get("container_bounds"):
            cx, cy, cw, ch = room["container_bounds"]
            parts.append(
                f'    <rect x="{cx}" y="{cy}" width="{cw}" height="{ch}" class="container-shell" />\n'
            )
            if room.get("container_title"):
                parts.append(
                    f'    <text x="{cx + 14}" y="{cy + 16}" class="container-banner">{html.escape(str(room["container_title"]))}</text>\n'
                )

        header_y = y + 34 if (room.get("container_bounds") or room.get("parent_container")) else y + 22
        parts.append(f'    <text x="{x + 14}" y="{header_y}" class="room-header">{html.escape(str(rname))}</text>\n')

        # Render internal architectural sub-zones (e.g., Living Area, Breakfast Nook, Kitchen Island, Deck & Grill)
        sub_zones = room.get("sub_zones", [])
        for s_idx, sz_label in enumerate(sub_zones):
            sy = header_y + 18 + s_idx * 16
            if sy < y + h - 32:
                parts.append(
                    f'    <text x="{x + 16}" y="{sy}" class="subzone-pill">▪ {html.escape(str(sz_label))}</text>\n'
                )

        room_features = room.get("features") if isinstance(room.get("features"), dict) else {}

        # Render staircase steps if room contains stairs
        if room.get("has_stairs_up") or room.get("has_stairs_down"):
            st_pos = room_features.get("stairs") if isinstance(room_features.get("stairs"), dict) else {}
            sx = round(float(st_pos["x"]), 1) if "x" in st_pos else x + w - 58
            sy = round(float(st_pos["y"]), 1) if "y" in st_pos else y + h - 42
            parts.append(f'    <g class="room-feature" data-feature="stairs" data-x="{sx}" data-y="{sy}">\n')
            parts.append(
                f'      <rect x="{sx}" y="{sy}" width="44" height="28" fill="rgba(56, 189, 248, 0.12)" stroke="#38bdf8" stroke-width="1" rx="2" class="stairs-step" />\n'
            )
            for step_i in range(1, 5):
                lx = round(sx + step_i * 9, 1)
                parts.append(
                    f'      <line x1="{lx}" y1="{sy}" x2="{lx}" y2="{round(sy + 28, 1)}" class="stairs-step" />\n'
                )
            parts.append("    </g>\n")

        # Render Pool & Deck Stairs inside Backyard when walkthrough includes pool without separate HA area
        if room.get("has_pool") and w >= 260:
            pw, ph = min(170, int(w * 0.28)), max(48, min(90, int(h - 32)))
            pl_pos = room_features.get("pool") if isinstance(room_features.get("pool"), dict) else {}
            px = round(float(pl_pos["x"]), 1) if "x" in pl_pos else x + w - pw - 20
            py = round(float(pl_pos["y"]), 1) if "y" in pl_pos else y + (h - ph) // 2
            parts.append(f'    <g class="room-feature" data-feature="pool" data-x="{px}" data-y="{py}">\n')
            parts.append(
                f'      <rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="6" fill="rgba(6, 182, 212, 0.14)" stroke="#22d3ee" stroke-width="1.2" stroke-dasharray="4 2" />\n'
            )
            parts.append(
                f'      <text x="{round(px + pw / 2, 1)}" y="{round(py + ph / 2 + 4, 1)}" text-anchor="middle" fill="#67e8f9" font-size="9" font-weight="700" letter-spacing="1.2">POOL &amp; PATIO</text>\n'
            )
            parts.append("    </g>\n")

        # Render Covered Front Porch & 2nd-Story Balcony canopy strip between Frontyard and Foyer
        if room.get("has_front_porch") and w >= 280:
            porch_w = min(200, int(w * 0.24))
            fp_pos = room_features.get("front_porch") if isinstance(room_features.get("front_porch"), dict) else {}
            porch_x = round(float(fp_pos["x"]), 1) if "x" in fp_pos else x + 220
            porch_y = round(float(fp_pos["y"]), 1) if "y" in fp_pos else y + 6
            parts.append(f'    <g class="room-feature" data-feature="front_porch" data-x="{porch_x}" data-y="{porch_y}">\n')
            parts.append(
                f'      <rect x="{porch_x}" y="{porch_y}" width="{porch_w}" height="20" rx="3" fill="rgba(56, 189, 248, 0.10)" stroke="rgba(56, 189, 248, 0.45)" stroke-width="1" stroke-dasharray="3 2" />\n'
            )
            parts.append(
                f'      <text x="{round(porch_x + porch_w / 2, 1)}" y="{round(porch_y + 13, 1)}" text-anchor="middle" fill="#7dd3fc" font-size="8" font-weight="700" letter-spacing="1">COVERED FRONT PORCH &amp; BALCONY</text>\n'
            )
            parts.append("    </g>\n")

        # Render doorway openings, door leaves, and swing arcs along walls
        raw_doors = room.get("doors", [])
        doors = [normalize_door_spec(d, room) for d in raw_doors] if raw_doors else []
        if not doors and room.get("adjacent_areas"):
            door_x = x + w - 34
            doors.append(normalize_door_spec(("bottom", door_x, 22, "Passage", "inward-right", "swing"), room))

        for d in doors:
            side = d.get("side", "bottom")
            pos = d.get("pos", 0)
            length = d.get("length", 36)
            orientation = d.get("orientation") or "inward-left"
            door_type = d.get("door_type", "swing")

            if side == "top":
                dx = max(x + 8, min(pos, x + w - length - 8))
                parts.append(f'    <line x1="{dx}" y1="{y}" x2="{dx + length}" y2="{y}" class="door-cut" />\n')
                if door_type == "swing":
                    if orientation == "inward-left":
                        parts.append(f'    <line x1="{dx}" y1="{y}" x2="{dx}" y2="{y + length}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {dx + length} {y} A {length} {length} 0 0 1 {dx} {y + length}" class="door-swing" />\n')
                    elif orientation == "inward-right":
                        parts.append(f'    <line x1="{dx + length}" y1="{y}" x2="{dx + length}" y2="{y + length}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {dx} {y} A {length} {length} 0 0 0 {dx + length} {y + length}" class="door-swing" />\n')
                    elif orientation == "outward-left":
                        parts.append(f'    <line x1="{dx}" y1="{y}" x2="{dx}" y2="{y - length}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {dx + length} {y} A {length} {length} 0 0 0 {dx} {y - length}" class="door-swing" />\n')
                    elif orientation == "outward-right":
                        parts.append(f'    <line x1="{dx + length}" y1="{y}" x2="{dx + length}" y2="{y - length}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {dx} {y} A {length} {length} 0 0 1 {dx + length} {y - length}" class="door-swing" />\n')
                elif door_type == "garage":
                    for off_y in (-2, 0, 2):
                        parts.append(f'    <line x1="{dx}" y1="{y + off_y}" x2="{dx + length}" y2="{y + off_y}" class="door-garage" />\n')
                elif door_type == "sliding":
                    parts.append(f'    <line x1="{dx}" y1="{y - 2}" x2="{dx + length * 0.55}" y2="{y - 2}" class="door-sliding" />\n')
                    parts.append(f'    <line x1="{dx + length * 0.45}" y1="{y + 2}" x2="{dx + length}" y2="{y + 2}" class="door-sliding" />\n')
            elif side == "bottom":
                dx = max(x + 8, min(pos, x + w - length - 8))
                parts.append(f'    <line x1="{dx}" y1="{y + h}" x2="{dx + length}" y2="{y + h}" class="door-cut" />\n')
                if door_type == "swing":
                    if orientation == "inward-left":
                        parts.append(f'    <line x1="{dx}" y1="{y + h}" x2="{dx}" y2="{y + h - length}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {dx + length} {y + h} A {length} {length} 0 0 0 {dx} {y + h - length}" class="door-swing" />\n')
                    elif orientation == "inward-right":
                        parts.append(f'    <line x1="{dx + length}" y1="{y + h}" x2="{dx + length}" y2="{y + h - length}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {dx} {y + h} A {length} {length} 0 0 1 {dx + length} {y + h - length}" class="door-swing" />\n')
                    elif orientation == "outward-left":
                        parts.append(f'    <line x1="{dx}" y1="{y + h}" x2="{dx}" y2="{y + h + length}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {dx + length} {y + h} A {length} {length} 0 0 1 {dx} {y + h + length}" class="door-swing" />\n')
                    elif orientation == "outward-right":
                        parts.append(f'    <line x1="{dx + length}" y1="{y + h}" x2="{dx + length}" y2="{y + h + length}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {dx} {y + h} A {length} {length} 0 0 0 {dx + length} {y + h + length}" class="door-swing" />\n')
                elif door_type == "garage":
                    for off_y in (-2, 0, 2):
                        parts.append(f'    <line x1="{dx}" y1="{y + h + off_y}" x2="{dx + length}" y2="{y + h + off_y}" class="door-garage" />\n')
                elif door_type == "sliding":
                    parts.append(f'    <line x1="{dx}" y1="{y + h - 2}" x2="{dx + length * 0.55}" y2="{y + h - 2}" class="door-sliding" />\n')
                    parts.append(f'    <line x1="{dx + length * 0.45}" y1="{y + h + 2}" x2="{dx + length}" y2="{y + h + 2}" class="door-sliding" />\n')
            elif side == "left":
                dy = max(y + 8, min(pos, y + h - length - 8))
                parts.append(f'    <line x1="{x}" y1="{dy}" x2="{x}" y2="{dy + length}" class="door-cut" />\n')
                if door_type == "swing":
                    if orientation in ("inward-top", "inward-left"):
                        parts.append(f'    <line x1="{x}" y1="{dy}" x2="{x + length}" y2="{dy}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {x} {dy + length} A {length} {length} 0 0 0 {x + length} {dy}" class="door-swing" />\n')
                    elif orientation in ("inward-bottom", "inward-right"):
                        parts.append(f'    <line x1="{x}" y1="{dy + length}" x2="{x + length}" y2="{dy + length}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {x} {dy} A {length} {length} 0 0 1 {x + length} {dy + length}" class="door-swing" />\n')
                    elif orientation in ("outward-top", "outward-left"):
                        parts.append(f'    <line x1="{x}" y1="{dy}" x2="{x - length}" y2="{dy}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {x} {dy + length} A {length} {length} 0 0 1 {x - length} {dy}" class="door-swing" />\n')
                    elif orientation in ("outward-bottom", "outward-right"):
                        parts.append(f'    <line x1="{x}" y1="{dy + length}" x2="{x - length}" y2="{dy + length}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {x} {dy} A {length} {length} 0 0 0 {x - length} {dy + length}" class="door-swing" />\n')
                elif door_type == "sliding":
                    parts.append(f'    <line x1="{x - 2}" y1="{dy}" x2="{x - 2}" y2="{dy + length * 0.55}" class="door-sliding" />\n')
                    parts.append(f'    <line x1="{x + 2}" y1="{dy + length * 0.45}" x2="{x + 2}" y2="{dy + length}" class="door-sliding" />\n')
            elif side == "right":
                dy = max(y + 8, min(pos, y + h - length - 8))
                parts.append(f'    <line x1="{x + w}" y1="{dy}" x2="{x + w}" y2="{dy + length}" class="door-cut" />\n')
                if door_type == "swing":
                    if orientation in ("inward-top", "inward-left"):
                        parts.append(f'    <line x1="{x + w}" y1="{dy}" x2="{x + w - length}" y2="{dy}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {x + w} {dy + length} A {length} {length} 0 0 1 {x + w - length} {dy}" class="door-swing" />\n')
                    elif orientation in ("inward-bottom", "inward-right"):
                        parts.append(f'    <line x1="{x + w}" y1="{dy + length}" x2="{x + w - length}" y2="{dy + length}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {x + w} {dy} A {length} {length} 0 0 0 {x + w - length} {dy + length}" class="door-swing" />\n')
                    elif orientation in ("outward-top", "outward-left"):
                        parts.append(f'    <line x1="{x + w}" y1="{dy}" x2="{x + w + length}" y2="{dy}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {x + w} {dy + length} A {length} {length} 0 0 0 {x + w + length} {dy}" class="door-swing" />\n')
                    elif orientation in ("outward-bottom", "outward-right"):
                        parts.append(f'    <line x1="{x + w}" y1="{dy + length}" x2="{x + w + length}" y2="{dy + length}" class="door-leaf" />\n')
                        parts.append(f'    <path d="M {x + w} {dy} A {length} {length} 0 0 1 {x + w + length} {dy + length}" class="door-swing" />\n')
                elif door_type == "sliding":
                    parts.append(f'    <line x1="{x + w - 2}" y1="{dy}" x2="{x + w - 2}" y2="{dy + length * 0.55}" class="door-sliding" />\n')
                    parts.append(f'    <line x1="{x + w + 2}" y1="{dy + length * 0.45}" x2="{x + w + 2}" y2="{dy + length}" class="door-sliding" />\n')

        # Render architectural windows along exterior/specified walls
        raw_windows = room.get("windows", [])
        windows = [normalize_window_spec(w, room) for w in raw_windows] if raw_windows else []
        for w_item in windows:
            side = w_item.get("side", "top")
            pos = w_item.get("pos", 0)
            length = w_item.get("length", 48)
            if side == "top":
                wx = max(x + 8, min(pos, x + w - length - 8))
                parts.append(f'    <line x1="{wx}" y1="{y}" x2="{wx + length}" y2="{y}" class="window-cut" />\n')
                parts.append(f'    <line x1="{wx}" y1="{y - 2}" x2="{wx + length}" y2="{y - 2}" class="window-sill" />\n')
                parts.append(f'    <line x1="{wx}" y1="{y - 1}" x2="{wx + length}" y2="{y - 1}" class="window-pane" />\n')
                parts.append(f'    <line x1="{wx}" y1="{y + 1}" x2="{wx + length}" y2="{y + 1}" class="window-pane" />\n')
                parts.append(f'    <line x1="{wx}" y1="{y - 3}" x2="{wx}" y2="{y + 3}" class="window-cap" />\n')
                parts.append(f'    <line x1="{wx + length}" y1="{y - 3}" x2="{wx + length}" y2="{y + 3}" class="window-cap" />\n')
            elif side == "bottom":
                wx = max(x + 8, min(pos, x + w - length - 8))
                parts.append(f'    <line x1="{wx}" y1="{y + h}" x2="{wx + length}" y2="{y + h}" class="window-cut" />\n')
                parts.append(f'    <line x1="{wx}" y1="{y + h + 2}" x2="{wx + length}" y2="{y + h + 2}" class="window-sill" />\n')
                parts.append(f'    <line x1="{wx}" y1="{y + h - 1}" x2="{wx + length}" y2="{y + h - 1}" class="window-pane" />\n')
                parts.append(f'    <line x1="{wx}" y1="{y + h + 1}" x2="{wx + length}" y2="{y + h + 1}" class="window-pane" />\n')
                parts.append(f'    <line x1="{wx}" y1="{y + h - 3}" x2="{wx}" y2="{y + h + 3}" class="window-cap" />\n')
                parts.append(f'    <line x1="{wx + length}" y1="{y + h - 3}" x2="{wx + length}" y2="{y + h + 3}" class="window-cap" />\n')
            elif side == "left":
                wy = max(y + 8, min(pos, y + h - length - 8))
                parts.append(f'    <line x1="{x}" y1="{wy}" x2="{x}" y2="{wy + length}" class="window-cut" />\n')
                parts.append(f'    <line x1="{x - 2}" y1="{wy}" x2="{x - 2}" y2="{wy + length}" class="window-sill" />\n')
                parts.append(f'    <line x1="{x - 1}" y1="{wy}" x2="{x - 1}" y2="{wy + length}" class="window-pane" />\n')
                parts.append(f'    <line x1="{x + 1}" y1="{wy}" x2="{x + 1}" y2="{wy + length}" class="window-pane" />\n')
                parts.append(f'    <line x1="{x - 3}" y1="{wy}" x2="{x + 3}" y2="{wy}" class="window-cap" />\n')
                parts.append(f'    <line x1="{x - 3}" y1="{wy + length}" x2="{x + 3}" y2="{wy + length}" class="window-cap" />\n')
            elif side == "right":
                wy = max(y + 8, min(pos, y + h - length - 8))
                parts.append(f'    <line x1="{x + w}" y1="{wy}" x2="{x + w}" y2="{wy + length}" class="window-cut" />\n')
                parts.append(f'    <line x1="{x + w + 2}" y1="{wy}" x2="{x + w + 2}" y2="{wy + length}" class="window-sill" />\n')
                parts.append(f'    <line x1="{x + w - 1}" y1="{wy}" x2="{x + w - 1}" y2="{wy + length}" class="window-pane" />\n')
                parts.append(f'    <line x1="{x + w + 1}" y1="{wy}" x2="{x + w + 1}" y2="{wy + length}" class="window-pane" />\n')
                parts.append(f'    <line x1="{x + w - 3}" y1="{wy}" x2="{x + w + 3}" y2="{wy}" class="window-cap" />\n')
                parts.append(f'    <line x1="{x + w - 3}" y1="{wy + length}" x2="{x + w + 3}" y2="{wy + length}" class="window-cap" />\n')

        # Render interactive entity badges along bottom of room footprint
        badge_start_x = x + 16
        badge_y = y + h - 18
        badge_spacing = 24
        badge_idx = 0

        for domain_key, icon_char in (
            ("lights", "💡"),
            ("media", "📺"),
            ("fans", "🌀"),
            ("vacuums", "🧹"),
            ("covers", "🚪"),
            ("switches", "🔌"),
            ("climates", "🌡️"),
            ("motion", "🚶"),
            ("cameras", "📹"),
            ("locks", "🔒"),
        ):
            domain_entities = buckets.get(domain_key, [])
            if domain_entities:
                eid_esc = html.escape(str(domain_entities[0]), quote=True)
                parts.append(
                    f'    <g class="entity-badge" data-entity-id="{eid_esc}" transform="translate({badge_start_x + badge_idx * badge_spacing}, {badge_y})">'
                    f'<circle cx="0" cy="0" r="10" class="badge-circle" />'
                    f'<text class="badge-icon">{icon_char}</text></g>\n'
                )
                badge_idx += 1

        parts.append('  </g>\n')
        return "".join(parts)

    def _generate_lovelace_card_yaml(
        self, svg_relative_path: str, layout_by_zone: dict[str, list[dict[str, Any]]]
    ) -> str:
        """Generate ready-to-use Lovelace picture-elements YAML configuration."""
        card_def = {
            "type": "picture-elements",
            "image": f"/api/otis_ai/media/{os.path.basename(svg_relative_path)}?v={int(time.time())}",
            "title": "Interactive Home Floor Plan",
            "elements": [],
        }

        canvas_h = float(self._get_canvas_height(layout_by_zone))

        # Embed click elements for primary room lights
        for _zone, rooms in layout_by_zone.items():
            for r in rooms:
                lights = [e for e in r.get("entities", []) if e.startswith("light.")]
                if lights:
                    top_pct = round(((r["y"] + r["height"] - 24) / canvas_h) * 100)
                    left_pct = round(((r["x"] + 16) / 1300.0) * 100)
                    card_def["elements"].append({
                        "type": "state-icon",
                        "entity": lights[0],
                        "style": {
                            "top": f"{top_pct}%",
                            "left": f"{left_pct}%",
                            "--paper-item-icon-active-color": "#38bdf8",
                        },
                        "tap_action": {"action": "toggle"},
                    })

        import yaml
        from .const import SafeNoAliasDumper
        if SafeNoAliasDumper is not None:
            return yaml.dump(card_def, Dumper=SafeNoAliasDumper, default_flow_style=False, sort_keys=False)
        return yaml.dump(card_def, default_flow_style=False, sort_keys=False)
