"""Multimodal video walkthrough parser and vector SVG floor plan engine for Otis AI Companion."""
from __future__ import annotations

import asyncio
import base64
import functools
import html
import json
import logging
import os
import re
import shutil
import time
from typing import Any
import urllib.request

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

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

# Architectural blueprint templates mapping normalized area keys to contiguous (x, y, w, h) footprints
# Ground Floor & Outdoor Plan (y = 85..690):
# - Great Room (x=260..760, y=225..445) is ONE unified open-concept space containing:
#   * Living Area & Breakfast Nook (great_room: x=260..570)
#   * Kitchen Area (kitchen: x=570..760)
GROUND_AND_OUTDOOR_BLUEPRINT: dict[str, dict[str, Any]] = {
    "backyard": {
        "x": 180, "y": 85, "width": 580, "height": 140,
        "sub_zones": ["Deck & Grill", "Hot Tub", "Side Gate"],
        "doors": [("bottom", 600, 44, "Mudroom Door", "outward-left")],
    },
    "pool": {
        "x": 760, "y": 85, "width": 320, "height": 140,
        "sub_zones": ["Swimming Pool", "Pool Equipment"],
        "is_water": True,
        "doors": [("left", 140, 50, "Pool Deck", "inward-top")],
    },
    "great_room": {
        "x": 260, "y": 225, "width": 310, "height": 220,
        "container_title": "GREAT ROOM (Living Area • Kitchen Area • Breakfast Nook)",
        "container_bounds": (260, 225, 500, 220),
        "sub_zones": ["Living Area", "Breakfast Nook"],
        "open_right": True,
        "doors": [("bottom", 230, 60, "Open to Foyer", "cased"), ("bottom", 80, 50, "Dining", "cased")],
        "windows": [("top", 320, 60, "Backyard View", "exterior"), ("left", 280, 50, "Patio Window", "exterior")],
    },
    "kitchen": {
        "x": 570, "y": 225, "width": 190, "height": 220,
        "parent_container": "great_room",
        "display_subtitle": "Kitchen Area (Inside Great Room)",
        "sub_zones": ["Kitchen Island", "Kitchen Camera"],
        "open_left": True,
        "doors": [("right", 265, 36, "To Mudroom", "inward-top")],
        "windows": [("top", 620, 50, "Garden Window", "exterior")],
    },
    "mudroom": {
        "x": 760, "y": 225, "width": 160, "height": 130,
        "sub_zones": ["Back Stairs (UP ↗)"],
        "has_stairs_up": True,
        "doors": [
            ("top", 800, 32, "To Backyard", "outward-left"),
            ("left", 265, 36, "Kitchen", "inward-top"),
            ("bottom", 810, 28, "Powder Rm", "inward-left"),
            ("right", 275, 34, "To Garage", "inward-top"),
        ],
    },
    "downstairs_bath": {
        "x": 760, "y": 355, "width": 160, "height": 90,
        "sub_zones": ["Powder Room"],
        "doors": [("top", 810, 28, "Mudroom", "inward-left")],
        "windows": [("right", 390, 30, "Bath Window", "exterior")],
    },
    "garage": {
        "x": 920, "y": 225, "width": 260, "height": 360,
        "sub_zones": ["Large 2-Car Bay", "Small Bay • Water Heater"],
        "doors": [
            ("left", 275, 34, "Mudroom", "inward-top"),
            ("bottom", 960, 90, "Large Garage Door", "garage"),
            ("bottom", 1090, 55, "Small Bay Door", "garage"),
        ],
        "windows": [("right", 320, 45, "Side Garage Window", "exterior")],
    },
    "dining_room": {
        "x": 260, "y": 445, "width": 210, "height": 140,
        "sub_zones": ["Formal Dining"],
        "doors": [("right", 495, 44, "Foyer", "cased"), ("top", 340, 50, "Great Room", "cased")],
        "windows": [("bottom", 280, 55, "Front Dining Window", "exterior"), ("left", 480, 45, "Side Dining Window", "exterior")],
    },
    "foyer": {
        "x": 470, "y": 445, "width": 140, "height": 140,
        "sub_zones": ["Main Entry"],
        "doors": [
            ("bottom", 520, 40, "Front Door", "inward-right"),
            ("top", 510, 55, "Great Room", "cased"),
            ("left", 495, 44, "Dining", "cased"),
            ("right", 495, 36, "Study", "inward-top"),
        ],
    },
    "study": {
        "x": 610, "y": 445, "width": 150, "height": 140,
        "sub_zones": ["Study Closet"],
        "doors": [("left", 495, 36, "Foyer", "inward-top")],
        "windows": [("bottom", 650, 45, "Study Front Window", "exterior")],
    },
    "frontyard": {
        "x": 260, "y": 585, "width": 920, "height": 105,
        "sub_zones": ["Front Porch & Doorbell Cam", "Wrap-Around Driveway", "Driveway Cam → Side Gate"],
        "doors": [("top", 520, 40, "Front Entry", "inward-right")],
    },
}

# Upper Level Floor Plan (Drawn Separately at y = 805..1185):
# Left-to-right top row matches the physical orientation above the Ground Floor:
# Guest Room -> Laundry Room -> Office -> Gym (aligned above the Mudroom Back Stairs on the right)
UPPER_FLOOR_BLUEPRINT: dict[str, dict[str, Any]] = {
    "guest_room": {
        "x": 180, "y": 805, "width": 270, "height": 150,
        "sub_zones": ["Guest Bedroom", "Ensuite Guest Bath"],
        "doors": [("bottom", 300, 36, "Hallway", "inward-right")],
        "windows": [("top", 240, 55, "Guest Bed Window", "exterior"), ("left", 850, 45, "Guest Side Window", "exterior")],
    },
    "laundry_room": {
        "x": 450, "y": 805, "width": 190, "height": 150,
        "sub_zones": ["Upper Laundry"],
        "doors": [("bottom", 525, 36, "Hallway", "inward-left")],
        "windows": [("top", 510, 40, "Laundry Window", "exterior")],
    },
    "office": {
        "x": 640, "y": 805, "width": 210, "height": 150,
        "sub_zones": ["Upstairs Office"],
        "doors": [("bottom", 725, 36, "Hallway", "inward-right")],
        "windows": [("top", 710, 50, "Office North Window", "exterior")],
    },
    "gym": {
        "x": 850, "y": 805, "width": 230, "height": 150,
        "sub_zones": ["Stair Landing (DN ↙)", "Reading Nook", "Fitness Zone"],
        "has_stairs_down": True,
        "doors": [("bottom", 810, 44, "Upper Hall", "inward-left")],
        "windows": [("top", 920, 55, "Gym North Window", "exterior"), ("right", 860, 45, "Gym East Window", "exterior")],
    },
    "hallway": {
        "x": 180, "y": 955, "width": 680, "height": 70,
        "sub_zones": ["Upper Corridor Spine", "Hall Bath"],
        "doors": [("right", 975, 40, "To Theater", "inward-top")],
    },
    "theater": {
        "x": 860, "y": 955, "width": 280, "height": 185,
        "sub_zones": ["Home Theater • Wall Tablet", "AV Equipment Closet"],
        "doors": [("left", 975, 40, "Hallway", "inward-top")],
        "windows": [("right", 1010, 40, "Theater Window", "exterior")],
    },
    "master_bath": {
        "x": 180, "y": 1025, "width": 270, "height": 160,
        "container_title": "MASTER SUITE (Master Bedroom • Master Bath • Walk-In Closet)",
        "container_bounds": (180, 1025, 680, 160),
        "sub_zones": ["Master Bathroom", "Powder Room"],
        "open_right": True,
        "doors": [("top", 300, 40, "Hallway", "inward-right"), ("right", 1085, 45, "To Master Bed", "cased")],
        "windows": [("bottom", 240, 50, "Master Bath Window", "exterior"), ("left", 1070, 45, "Bath Side Window", "exterior")],
    },
    "master": {
        "x": 450, "y": 1025, "width": 410, "height": 160,
        "parent_container": "master_bath",
        "sub_zones": ["Master Bedroom • TV Wall", "Walk-In Closet"],
        "open_left": True,
        "doors": [("top", 560, 40, "Hallway", "inward-left")],
        "windows": [("bottom", 540, 60, "Master Bed Window", "exterior"), ("bottom", 680, 60, "Master Nook Window", "exterior")],
    },
}


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
            with open(svg_file_path, "r", encoding="utf-8") as svg_f:
                svg_txt = svg_f.read()
            if not isinstance(svg_txt, str):
                return bounds
            for m in re.finditer(
                r'<g\b[^>]*class="[^"]*room-group[^"]*"[^>]*data-area-id="([^"]*)"[^>]*>[\s\S]*?<rect\b[^>]*x="([0-9.]+)"\s+y="([0-9.]+)"\s+width="([0-9.]+)"\s+height="([0-9.]+)"',
                svg_txt,
            ):
                aid_svg = m.group(1)
                bounds[aid_svg] = {
                    "id": aid_svg,
                    "x": float(m.group(2)),
                    "y": float(m.group(3)),
                    "width": float(m.group(4)),
                    "height": float(m.group(5)),
                }
        except Exception as err:
            _LOGGER.debug("Error parsing SVG room bounds: %s", err)
        return bounds

    async def async_refresh_svg_cache(self, svg_relative_path: str = DEFAULT_OUTPUT_SVG_PATH) -> None:
        """Asynchronously refresh cached SVG room bounds in executor to avoid blocking event loop."""
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
        """Retrieve Google Generative AI API key and model from Home Assistant config entries."""
        model = "models/gemini-3.5-flash"
        if not hasattr(self.hass, "config_entries"):
            return None, model
        try:
            entries = self.hass.config_entries.async_entries("google_generative_ai_conversation")
            for entry in entries:
                api_key = entry.data.get("api_key")
                if api_key:
                    subentries = getattr(entry, "subentries", None)
                    if hasattr(subentries, "values"):
                        sub_iter = list(subentries.values())
                    elif isinstance(subentries, (list, tuple)):
                        sub_iter = list(subentries)
                    else:
                        sub_iter = []
                    for sub in sub_iter:
                        sub_data = getattr(sub, "data", None) or (sub.get("data") if isinstance(sub, dict) else {}) or {}
                        sub_type = getattr(sub, "subentry_type", None) or (sub.get("subentry_type") if isinstance(sub, dict) else None)
                        chat_model = sub_data.get("chat_model")
                        if chat_model and sub_type in ("conversation", "stt", "ai_task_data", None):
                            model = chat_model if str(chat_model).startswith("models/") else f"models/{chat_model}"
                            break
                    return str(api_key), model
        except Exception as err:
            _LOGGER.debug("Could not inspect google_generative_ai_conversation entry: %s", err)
        return None, model

    async def async_extract_keyframes_from_video(
        self, video_path: str, output_dir: str, prefix: str = "frame", max_frames: int = 8
    ) -> list[str]:
        """Extract sampled JPEG keyframes from a walkthrough video using ffmpeg for visual layout analysis."""
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

        pattern = os.path.join(output_dir, f"{prefix}_%02d.jpg")
        cmd = [
            ffmpeg_bin,
            "-i", video_path,
            "-vf", "fps=1/10,scale=512:-1",
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
            "7. Identify any windows mentioned or seen, noting the room and wall side (`top`, `bottom`, `left`, `right`).\n\n"
            "Respond strictly with valid JSON matching this schema:\n"
            '{"transcript": "...", "ordered_areas": ["area_id_1", "area_id_2"], '
            '"adjacencies": [["area_id_1", "area_id_2"]], '
            '"contained_areas": {"great_room": ["kitchen"]}, '
            '"floor_assignments": {"area_id_1": "outdoor", "area_id_2": "main"}, '
            '"doors": [{"room": "foyer", "wall": "bottom", "orientation": "inward-right", "label": "Front Door"}], '
            '"windows": [{"room": "dining_room", "wall": "bottom", "label": "Bay Window"}]}'
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
            for fp in (frame_paths or [])[:6]:
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
                    with urllib.request.urlopen(req, timeout=90) as resp:
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
                    video_path, frame_dir, prefix=f"clip{idx}", max_frames=6
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

            # Cleanup temporary frame directory
            if frame_dir and await self._async_run_in_executor(os.path.isdir, frame_dir):
                try:
                    await self.hass.async_add_executor_job(shutil.rmtree, frame_dir, True)
                except Exception:
                    pass

        return {
            "transcript": "\n".join(combined_transcripts),
            "transcripts": combined_transcripts,
            "ordered_areas": combined_ordered_areas,
            "adjacencies": combined_adjacencies,
            "contained_areas": combined_contained_areas,
            "floor_assignments": combined_floor_assignments,
            "detected_doors": combined_detected_doors,
            "detected_windows": combined_detected_windows,
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
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Synthesize interactive vector SVG floor plan with multi-floor zones and active entities."""
        areas_map = capability_map.get("areas", {})
        entities = capability_map.get("entities", [])
        spatial_graph = capability_map.get("spatial_graph", {})
        adjacencies = spatial_graph.get("adjacencies", {})

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
            for z, r_list in zones.items():
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
            for z, r_list in zones.items():
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
        svg_relative_path: str = DEFAULT_OUTPUT_SVG_PATH,
    ) -> dict[str, Any]:
        """Update SVG floorplan device marker coordinates and area boundary geometry, or delete rooms."""
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
            with open(output_full_path, "r", encoding="utf-8") as f:
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

                def _badge_sub(match: re.Match) -> str:
                    prefix = match.group(1)
                    prefix = re.sub(r'\s+transform="[^"]*"', '', prefix)
                    return f'{prefix} transform="translate({bx}, {by})"'

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
                        badge_markup = (
                            f'    <g class="entity-badge" data-entity-id="{eid}" transform="translate({bx}, {by})">\n'
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
                        if '<polygon' in inner:
                            inner = re.sub(r'<polygon[^>]*class="room-polygon"[^>]*/>', f'<polygon points="{points}" class="room-polygon" />', inner)
                        else:
                            inner = re.sub(r'<rect[^>]*class="room-rect"[^>]*/>', f'<polygon points="{points}" class="room-polygon" />', inner)
                    else:
                        def _rect_sub(rmatch: re.Match) -> str:
                            tag = rmatch.group(0)
                            tag = re.sub(r'\s+(?:x|y|width|height)="[^"]*"', '', tag)
                            return f'<rect x="{rx}" y="{ry}" width="{rw}" height="{rh}"' + tag[5:]

                        inner = re.sub(
                            r'<rect\b[^>]*class="[^"]*(?:room-box|room-rect)[^"]*"[^>]*/>',
                            _rect_sub,
                            inner,
                        )

                    # Update text label position cleanly inside attributes
                    def _text_sub(tmatch: re.Match) -> str:
                        orig_content = tmatch.group(1)
                        cleaned_txt = re.sub(r'^(?:\s*(?:x|y)="[^"]*"[>\s]*)+', '', orig_content).strip()
                        display_name = rname.strip() if (rname and str(rname).strip()) else cleaned_txt
                        if not display_name:
                            display_name = rid.replace('_', ' ').title()
                        return f'<text x="{round(rx + 14, 1)}" y="{round(ry + 22, 1)}" class="room-header">{display_name}</text>'

                    inner = re.sub(
                        r'<text\b[^>]*class="[^"]*(?:room-header|room-label)[^"]*"[^>]*>(.*?)</text>',
                        _text_sub,
                        inner,
                    )

                    # Update internal architectural subzone pills in sync with room coordinates
                    pill_idx = 0

                    def _pill_sub(pmatch: re.Match) -> str:
                        nonlocal pill_idx
                        orig_txt = pmatch.group(1)
                        clean_pill = re.sub(r'^(?:\s*(?:x|y)="[^"]*"[>\s]*)+', '', orig_txt).strip()
                        py = round(ry + 22 + 18 + pill_idx * 16, 1)
                        pill_idx += 1
                        return f'<text x="{round(rx + 16, 1)}" y="{py}" class="subzone-pill">{clean_pill}</text>'

                    inner = re.sub(
                        r'<text\b[^>]*class="[^"]*subzone-pill[^"]*"[^>]*>(.*?)</text>',
                        _pill_sub,
                        inner,
                    )

                    # Update internal entity badges in sync with room coordinates
                    b_idx = 0

                    def _badge_sub(bmatch: re.Match) -> str:
                        nonlocal b_idx
                        badge_full = bmatch.group(0)
                        eid_match = re.search(r'data-entity-id="([^"]*)"', badge_full)
                        if eid_match and eid_match.group(1) in explicit_badge_ids:
                            b_idx += 1
                            return badge_full
                        bx = round(rx + 16 + b_idx * 24, 1)
                        by = round(ry + rh - 18, 1)
                        b_idx += 1
                        badge_no_tr = re.sub(r'\s+transform="[^"]*"', '', badge_full)
                        return re.sub(r'^(<g\b[^>]*?)>', rf'\1 transform="translate({bx}, {by})">', badge_no_tr, count=1)

                    inner = re.sub(
                        r'<g\b[^>]*class="[^"]*entity-badge[^"]*"[^>]*>[\s\S]*?</g>',
                        _badge_sub,
                        inner,
                    )

                    # Update internal stairs in sync with room coordinates if present
                    sx = round(rx + rw - 58, 1)
                    sy = round(ry + rh - 42, 1)
                    inner = re.sub(
                        r'(<rect\b[^>]*fill="rgba\(56,\s*189,\s*248,\s*0\.12\)"[^>]*?)\s+x="[^"]*"\s+y="[^"]*"',
                        rf'\1 x="{sx}" y="{sy}"',
                        inner,
                    )
                    step_i = 0

                    def _step_sub(smatch: re.Match) -> str:
                        nonlocal step_i
                        step_i += 1
                        lx = round(sx + step_i * 9, 1)
                        return f'<line x1="{lx}" y1="{sy}" x2="{lx}" y2="{round(sy + 28, 1)}" class="stairs-step" />'

                    inner = re.sub(
                        r'<line\b[^>]*class="stairs-step"[^>]*/>',
                        _step_sub,
                        inner,
                    )
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
                        existing_badges[b["entity_id"]] = b
            custom_layout["badges"] = list(existing_badges.values())

        if rooms:
            existing_rooms = {r["id"]: r for r in custom_layout.get("rooms", []) if isinstance(r, dict) and r.get("id")}
            for r in rooms:
                if isinstance(r, dict):
                    rid = r.get("id")
                    if rid and rid not in to_delete and not r.get("delete"):
                        existing_rooms[rid] = r
            custom_layout["rooms"] = [r for r in existing_rooms.values() if r.get("id") not in to_delete]

        if to_delete:
            del_list = self._metadata.setdefault("deleted_rooms", [])
            for did in to_delete:
                if did not in del_list:
                    del_list.append(did)
            if "rooms" in custom_layout and isinstance(custom_layout["rooms"], list):
                custom_layout["rooms"] = [r for r in custom_layout["rooms"] if r.get("id") not in to_delete]

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
        res = await self.async_update_floorplan_layout(
            badges=[{"entity_id": entity_id, "delete": True}],
            svg_relative_path=svg_relative_path,
        )
        res["entity_id"] = entity_id
        return res

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
                col = unmapped_idx % 4
                row = unmapped_idx // 4
                room_w, room_h = 250, 140
                x = 60 + col * (room_w + 16)
                y = base_y + row * (room_h + 16)
                while _overlaps(x, y, room_w, room_h):
                    y += room_h + 16
                w, h = room_w, room_h
                extra_meta = {}
                unmapped_idx += 1

            used_boxes.append((x, y, w, h))
            placed.append({
                "id": room["id"],
                "name": room["name"],
                "zone": zone_key,
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "entities": room["entities"],
                "adjacent_areas": room["adjacent_areas"],
                **extra_meta,
            })
        return placed

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

        for zone_k, room_list in layout.items():
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

        # Filter out deleted rooms
        deleted_rooms = set()
        if hasattr(self, "_metadata") and isinstance(self._metadata, dict):
            deleted_rooms = set(self._metadata.get("deleted_rooms", []))

        for zone_k in list(layout.keys()):
            layout[zone_k] = [r for r in layout[zone_k] if r.get("id") not in deleted_rooms]

        # Automatic exterior window placement for rooms that don't have windows defined
        all_placed = [r for r_list in layout.values() for r in r_list]
        for z_key, r_list in layout.items():
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
        rid = room.get("id", "room")
        rname = room.get("name", rid)
        rzone = room.get("zone", "main")
        pts_str = room.get("iso_points_str", "")
        south_facet = room.get("iso_south_facet", "")
        east_facet = room.get("iso_east_facet", "")
        center = room.get("iso_center", (650.0, 500.0))
        entities = room.get("entities", [])
        buckets = classify_area_entities(entities)

        box_classes = ["iso-floor-slab"]
        if rzone == "outdoor":
            if room.get("is_water"):
                box_classes.append("water-box")
            else:
                box_classes.append("outdoor-box")

        sub_zones = room.get("sub_zones", [])
        subzone_preview = sub_zones[0] if sub_zones else ""

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
        for idx, (eid, icon_char) in enumerate(active_badges[:4]):
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
      }}
      .room-box {{
        fill: {card_bg};
        fill-opacity: 0.9;
        stroke: {wall_color};
        stroke-width: 2.5;
        rx: 3px;
        transition: all 0.25s ease;
        cursor: pointer;
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
  <g opacity="0.10">
    <pattern id="grid" width="30" height="30" patternUnits="userSpaceOnUse">
      <path d="M 30 0 L 0 0 0 30" fill="none" stroke="{accent_color}" stroke-width="0.8" />
    </pattern>
    <rect width="1300" height="{canvas_height}" fill="url(#grid)" />
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

        parts = [
            f'  <g class="room room-group" id="area-{rid}" data-area-id="{rid}" data-zone="{rzone}">\n',
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

        # Render staircase steps if room contains stairs
        if room.get("has_stairs_up") or room.get("has_stairs_down"):
            sx = x + w - 58
            sy = y + h - 42
            parts.append(
                f'    <rect x="{sx}" y="{sy}" width="44" height="28" fill="rgba(56, 189, 248, 0.12)" stroke="#38bdf8" stroke-width="1" rx="2" />\n'
            )
            for step_i in range(1, 5):
                lx = sx + step_i * 9
                parts.append(
                    f'    <line x1="{lx}" y1="{sy}" x2="{lx}" y2="{sy + 28}" class="stairs-step" />\n'
                )

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
                parts.append(
                    f'    <g class="entity-badge" data-entity-id="{domain_entities[0]}" transform="translate({badge_start_x + badge_idx * badge_spacing}, {badge_y})">'
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
        for zone, rooms in layout_by_zone.items():
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
        return yaml.dump(card_def, default_flow_style=False, sort_keys=False)
