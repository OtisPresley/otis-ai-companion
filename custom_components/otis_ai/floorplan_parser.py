"""Multimodal video walkthrough parser and vector SVG floor plan engine for Otis AI Companion."""
from __future__ import annotations

import asyncio
import base64
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
DEFAULT_OUTPUT_SVG_PATH = "www/otis_floorplan.svg"

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
        "doors": [("bottom", 600, 44, "Mudroom Door")],
    },
    "pool": {
        "x": 760, "y": 85, "width": 320, "height": 140,
        "sub_zones": ["Swimming Pool", "Pool Equipment"],
        "is_water": True,
        "doors": [("left", 140, 50, "Pool Deck")],
    },
    "great_room": {
        "x": 260, "y": 225, "width": 310, "height": 220,
        "container_title": "GREAT ROOM (Living Area • Kitchen Area • Breakfast Nook)",
        "container_bounds": (260, 225, 500, 220),
        "sub_zones": ["Living Area", "Breakfast Nook"],
        "open_right": True,
        "doors": [("bottom", 230, 60, "Open to Foyer"), ("bottom", 80, 50, "Dining")],
    },
    "kitchen": {
        "x": 570, "y": 225, "width": 190, "height": 220,
        "parent_container": "great_room",
        "display_subtitle": "Kitchen Area (Inside Great Room)",
        "sub_zones": ["Kitchen Island", "Kitchen Camera"],
        "open_left": True,
        "doors": [("right", 265, 36, "To Mudroom")],
    },
    "mudroom": {
        "x": 760, "y": 225, "width": 160, "height": 130,
        "sub_zones": ["Back Stairs (UP ↗)"],
        "has_stairs_up": True,
        "doors": [
            ("top", 800, 32, "To Backyard"),
            ("left", 265, 36, "Kitchen"),
            ("bottom", 810, 28, "Powder Rm"),
            ("right", 275, 34, "To Garage"),
        ],
    },
    "downstairs_bath": {
        "x": 760, "y": 355, "width": 160, "height": 90,
        "sub_zones": ["Powder Room"],
        "doors": [("top", 810, 28, "Mudroom")],
    },
    "garage": {
        "x": 920, "y": 225, "width": 260, "height": 360,
        "sub_zones": ["Large 2-Car Bay", "Small Bay • Water Heater"],
        "doors": [
            ("left", 275, 34, "Mudroom"),
            ("bottom", 960, 90, "Large Garage Door"),
            ("bottom", 1090, 55, "Small Bay Door"),
        ],
    },
    "dining_room": {
        "x": 260, "y": 445, "width": 210, "height": 140,
        "sub_zones": ["Formal Dining"],
        "doors": [("right", 495, 44, "Foyer"), ("top", 340, 50, "Great Room")],
    },
    "foyer": {
        "x": 470, "y": 445, "width": 140, "height": 140,
        "sub_zones": ["Main Entry"],
        "doors": [
            ("bottom", 520, 40, "Front Door"),
            ("top", 510, 55, "Great Room"),
            ("left", 495, 44, "Dining"),
            ("right", 495, 36, "Study"),
        ],
    },
    "study": {
        "x": 610, "y": 445, "width": 150, "height": 140,
        "sub_zones": ["Study Closet"],
        "doors": [("left", 495, 36, "Foyer")],
    },
    "frontyard": {
        "x": 260, "y": 585, "width": 920, "height": 105,
        "sub_zones": ["Front Porch & Doorbell Cam", "Wrap-Around Driveway", "Driveway Cam → Side Gate"],
        "doors": [("top", 520, 40, "Front Entry")],
    },
}

# Upper Level Floor Plan (Drawn Separately at y = 805..1185):
# Left-to-right top row matches the physical orientation above the Ground Floor:
# Guest Room -> Laundry Room -> Office -> Gym (aligned above the Mudroom Back Stairs on the right)
UPPER_FLOOR_BLUEPRINT: dict[str, dict[str, Any]] = {
    "guest_room": {
        "x": 180, "y": 805, "width": 270, "height": 150,
        "sub_zones": ["Guest Bedroom", "Ensuite Guest Bath"],
        "doors": [("bottom", 300, 36, "Hallway")],
    },
    "laundry_room": {
        "x": 450, "y": 805, "width": 190, "height": 150,
        "sub_zones": ["Upper Laundry"],
        "doors": [("bottom", 525, 36, "Hallway")],
    },
    "office": {
        "x": 640, "y": 805, "width": 210, "height": 150,
        "sub_zones": ["Upstairs Office"],
        "doors": [("bottom", 725, 36, "Hallway")],
    },
    "gym": {
        "x": 850, "y": 805, "width": 230, "height": 150,
        "sub_zones": ["Stair Landing (DN ↙)", "Reading Nook", "Fitness Zone"],
        "has_stairs_down": True,
        "doors": [("bottom", 810, 44, "Upper Hall")],
    },
    "hallway": {
        "x": 180, "y": 955, "width": 680, "height": 70,
        "sub_zones": ["Upper Corridor Spine", "Hall Bath"],
        "doors": [("right", 975, 40, "To Theater")],
    },
    "theater": {
        "x": 860, "y": 955, "width": 280, "height": 185,
        "sub_zones": ["Home Theater • Wall Tablet", "AV Equipment Closet"],
        "doors": [("left", 975, 40, "Hallway")],
    },
    "master_bath": {
        "x": 180, "y": 1025, "width": 270, "height": 160,
        "container_title": "MASTER SUITE (Master Bedroom • Master Bath • Walk-In Closet)",
        "container_bounds": (180, 1025, 680, 160),
        "sub_zones": ["Master Bathroom", "Powder Room"],
        "open_right": True,
        "doors": [("top", 300, 40, "Hallway"), ("right", 1085, 45, "To Master Bed")],
    },
    "master": {
        "x": 450, "y": 1025, "width": 410, "height": 160,
        "parent_container": "master_bath",
        "sub_zones": ["Master Bedroom • TV Wall", "Walk-In Closet"],
        "open_left": True,
        "doors": [("top", 560, 40, "Hallway")],
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

    def _parse_svg_room_bounds_sync(self, svg_file_path: str) -> dict[str, dict[str, float]]:
        """Parse room coordinates from floorplan SVG synchronously in executor."""
        bounds: dict[str, dict[str, float]] = {}
        if not isinstance(svg_file_path, str) or not os.path.exists(svg_file_path):
            return bounds
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
        data = await self._store.async_load()
        if data and isinstance(data, dict):
            self._metadata = data
        self._initialized = True
        await self.async_refresh_svg_cache()
        return self._metadata

    async def async_save_metadata(self, metadata: dict[str, Any]) -> None:
        """Persist floorplan metadata to storage."""
        self._metadata = metadata
        await self._store.async_save(metadata)

    def has_walkthrough(self) -> bool:
        """Check if a video walkthrough has been completed."""
        return bool(self._metadata.get("walkthrough_completed", False))

    def floorplan_exists(self) -> bool:
        """Check if an interactive floorplan SVG already exists in www/."""
        if hasattr(self.hass, "config") and hasattr(self.hass.config, "path"):
            full_path = self.hass.config.path(DEFAULT_OUTPUT_SVG_PATH)
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
        if not os.path.exists(video_path):
            _LOGGER.error("Walkthrough video file not found: %s", video_path)
            return False

        ffmpeg_bin = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
        if not os.path.exists(ffmpeg_bin):
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
            if process.returncode == 0 and os.path.exists(output_wav_path):
                _LOGGER.info("Successfully extracted walkthrough audio to %s", output_wav_path)
                return True
            else:
                _LOGGER.warning("ffmpeg audio extraction failed (code %s): %s", process.returncode, stderr.decode("utf-8", "ignore")[-300:])
                return False
        except Exception as err:
            _LOGGER.error("Error executing ffmpeg subprocess: %s", err)
            return False

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
        if not os.path.exists(video_path):
            return []
        ffmpeg_bin = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
        if not os.path.exists(ffmpeg_bin):
            return []

        os.makedirs(output_dir, exist_ok=True)
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
            frames = sorted(
                os.path.join(output_dir, f)
                for f in os.listdir(output_dir)
                if f.startswith(prefix) and f.endswith(".jpg")
            )
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
        """Transcribe walkthrough audio + video keyframes and extract ordered areas, containment, and adjacencies."""
        result: dict[str, Any] = {
            "transcript": "",
            "ordered_areas": [],
            "adjacencies": [],
            "contained_areas": {},
            "floor_assignments": {},
        }
        if not audio_path or not os.path.exists(audio_path):
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
            "`upper` for upstairs/second floor).\n\n"
            "Respond strictly with valid JSON matching this schema:\n"
            '{"transcript": "...", "ordered_areas": ["area_id_1", "area_id_2"], '
            '"adjacencies": [["area_id_1", "area_id_2"]], '
            '"contained_areas": {"great_room": ["kitchen"]}, '
            '"floor_assignments": {"area_id_1": "outdoor", "area_id_2": "main"}}'
        )

        candidate_models = [preferred_model]
        for fallback_m in ("models/gemini-3.5-flash", "models/gemini-2.5-flash", "models/gemini-2.0-flash"):
            if fallback_m not in candidate_models:
                candidate_models.append(fallback_m)

        def _call_gemini_sync() -> dict[str, Any]:
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

            _LOGGER.info(
                "Walkthrough audio analysis complete: %d areas ordered (%s), %d adjacencies, contained=%s",
                len(ordered),
                ordered,
                len(adjacencies),
                contained,
            )
        except Exception as err:
            _LOGGER.warning("Gemini walkthrough audio analysis failed: %s", err)

        return result

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

        # Calculate layout coordinates for each room
        layout_by_zone = self._calculate_orthogonal_layout(zones)

        # Render complete SVG markup
        svg_content = self._render_svg_markup(layout_by_zone, entities, theme)

        # Write SVG file to destination
        output_full_path = (
            self.hass.config.path(output_relative_path)
            if hasattr(self.hass, "config") and hasattr(self.hass.config, "path")
            else output_relative_path
        )
        os.makedirs(os.path.dirname(output_full_path), exist_ok=True)

        def write_sync():
            with open(output_full_path, "w", encoding="utf-8") as f:
                f.write(svg_content)

        await self.hass.async_add_executor_job(write_sync)
        await self.async_refresh_svg_cache(output_relative_path)
        _LOGGER.info("Generated vector SVG floor plan saved to %s (walkthrough=%s)", output_full_path, is_walkthrough)

        # Generate Lovelace Picture-Elements Card YAML snippet
        lovelace_card_yaml = self._generate_lovelace_card_yaml(output_relative_path, layout_by_zone)

        # Save metadata to storage
        transcripts = kwargs.get("transcripts") or self._metadata.get("transcripts", [])
        meta = {
            "version": STORAGE_VERSION,
            "svg_path": output_relative_path,
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
            "url": f"/local/{os.path.basename(output_relative_path)}",
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
        svg_relative_path: str = "www/otis_floorplan.svg",
    ) -> dict[str, Any]:
        """Update SVG floorplan device marker coordinates and area boundary geometry, or delete rooms."""
        output_full_path = (
            self.hass.config.path(svg_relative_path)
            if hasattr(self.hass, "config") and hasattr(self.hass.config, "path")
            else svg_relative_path
        )
        if not os.path.exists(output_full_path):
            return {
                "success": False,
                "error": f"Floorplan SVG not found at {output_full_path}. Generate floor plan first.",
            }

        def read_sync() -> str:
            with open(output_full_path, "r", encoding="utf-8") as f:
                return f.read()

        svg_content = await self.hass.async_add_executor_job(read_sync)
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
                    pattern = rf'<g\b[^>]*class="[^"]*entity-badge[^"]*"[^>]*data-entity-id="{re.escape(eid)}"[^>]*>[\s\S]*?</g>'
                    new_svg, count = re.subn(pattern, "", svg_content)
                    if count > 0:
                        svg_content = new_svg
                        deleted_badges_count += count
                    else:
                        pattern_alt = rf'<g\b[^>]*data-entity-id="{re.escape(eid)}"[^>]*class="[^"]*entity-badge[^"]*"[^>]*>[\s\S]*?</g>'
                        new_svg, count = re.subn(pattern_alt, "", svg_content)
                        if count > 0:
                            svg_content = new_svg
                            deleted_badges_count += count
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

        await self.hass.async_add_executor_job(write_sync)
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
            "url": f"/local/{os.path.basename(svg_relative_path)}?v={int(time.time())}",
            "updated_badges": updated_badges,
            "updated_rooms": updated_rooms,
            "deleted_rooms": deleted_rooms_count,
        }

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

        return layout

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
    ) -> str:
        """Render architectural vector SVG floor plans (Ground+Outdoor combined, Upper Level separate)."""
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
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1300 {canvas_height}" data-full-viewbox="0 0 1300 {canvas_height}" width="1300" height="{canvas_height}" class="otis-floorplan {theme}">
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
      .entity-badge {{
        display: inline;
        cursor: pointer;
        transition: transform 0.2s ease;
      }}
      .entity-badge:hover {{
        transform: scale(1.2);
      }}
      .badge-circle {{ fill: rgba(15, 23, 42, 0.92); stroke: {accent_color}; stroke-width: 1.5; }}
      .badge-icon {{ fill: {text_color}; font-size: 10px; text-anchor: middle; dominant-baseline: middle; }}
      .door-cut {{ stroke: {accent_secondary}; stroke-width: 4; stroke-linecap: round; }}
      .stairs-step {{ stroke: #38bdf8; stroke-width: 1.2; opacity: 0.65; }}
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

        # Render doorway openings along walls
        doors = room.get("doors", [])
        if doors:
            for side, pos, length, _label in doors:
                if side == "top":
                    dx = max(x + 8, min(pos, x + w - length - 8))
                    parts.append(f'    <line x1="{dx}" y1="{y}" x2="{dx + length}" y2="{y}" class="door-cut" />\n')
                elif side == "bottom":
                    dx = max(x + 8, min(pos, x + w - length - 8))
                    parts.append(f'    <line x1="{dx}" y1="{y + h}" x2="{dx + length}" y2="{y + h}" class="door-cut" />\n')
                elif side == "left":
                    dy = max(y + 8, min(pos, y + h - length - 8))
                    parts.append(f'    <line x1="{x}" y1="{dy}" x2="{x}" y2="{dy + length}" class="door-cut" />\n')
                elif side == "right":
                    dy = max(y + 8, min(pos, y + h - length - 8))
                    parts.append(f'    <line x1="{x + w}" y1="{dy}" x2="{x + w}" y2="{dy + length}" class="door-cut" />\n')
        elif room.get("adjacent_areas"):
            door_x = x + w - 34
            door_y = y + h
            parts.append(f'    <line x1="{door_x}" y1="{door_y}" x2="{door_x + 22}" y2="{door_y}" class="door-cut" />\n')

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
            "image": f"/local/{os.path.basename(svg_relative_path)}?v={int(time.time())}",
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
