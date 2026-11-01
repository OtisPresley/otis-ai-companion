"""Unit tests for multi-clip sequential walkthrough video/audio processing and door/window symbol orientation detection."""
import asyncio
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

from custom_components.otis_ai.floorplan_parser import (
    FloorplanParser,
    detect_door_orientation,
    detect_exterior_windows,
    normalize_door_spec,
    normalize_window_spec,
)


class MockHassConfig:
    """Mock Home Assistant config for filesystem path resolution."""

    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir

    def path(self, *parts: str) -> str:
        return os.path.join(self.base_dir, *parts)


class TestMulticlipWalkthroughAndSymbols(unittest.TestCase):
    """Test suite for multi-clip walkthrough processing and architectural symbols."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="otis_test_multiclip_")
        self.hass = MagicMock()
        self.hass.config = MockHassConfig(self.tmp_dir)
        self.hass.async_add_executor_job = AsyncMock(
            side_effect=lambda func, *args: func(*args) if not asyncio.iscoroutinefunction(func) else func(*args)
        )
        self.parser = FloorplanParser(self.hass)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_normalize_door_spec_tuples_and_dicts(self) -> None:
        """Verify normalization of door specs from tuples and dicts into canonical schema."""
        room = {"id": "foyer", "x": 470, "y": 445, "width": 140, "height": 140, "zone": "main"}

        # 4-tuple
        door_4 = ("bottom", 520, 40, "Front Door")
        norm_4 = normalize_door_spec(door_4, room)
        self.assertEqual(norm_4["side"], "bottom")
        self.assertEqual(norm_4["pos"], 520)
        self.assertEqual(norm_4["length"], 40)
        self.assertEqual(norm_4["label"], "Front Door")
        self.assertEqual(norm_4["door_type"], "swing")
        self.assertIn(norm_4["orientation"], ("inward-left", "inward-right"))

        # 5-tuple with explicit orientation
        door_5 = ("top", 510, 55, "Open to Great Room", "cased")
        norm_5 = normalize_door_spec(door_5, room)
        self.assertEqual(norm_5["door_type"], "cased")
        self.assertIsNone(norm_5["orientation"])

        # Garage door inference
        door_garage = ("bottom", 960, 90, "Large Garage Door")
        norm_garage = normalize_door_spec(door_garage, room)
        self.assertEqual(norm_garage["door_type"], "garage")

        # Sliding door inference
        door_sliding = ("left", 140, 50, "Sliding Patio Door")
        norm_sliding = normalize_door_spec(door_sliding, room)
        self.assertEqual(norm_sliding["door_type"], "sliding")

        # Dict input
        door_dict = {
            "side": "right",
            "pos": 495,
            "length": 36,
            "label": "Study Door",
            "orientation": "inward-top",
            "type": "swing",
        }
        norm_dict = normalize_door_spec(door_dict, room)
        self.assertEqual(norm_dict["side"], "right")
        self.assertEqual(norm_dict["orientation"], "inward-top")

    def test_normalize_window_spec_tuples_and_dicts(self) -> None:
        """Verify normalization of window specs from tuples and dicts."""
        room = {"id": "great_room", "x": 260, "y": 225, "width": 310, "height": 220}

        win_tuple = ("top", 320, 60, "Backyard View", "exterior")
        norm_t = normalize_window_spec(win_tuple, room)
        self.assertEqual(norm_t["side"], "top")
        self.assertEqual(norm_t["pos"], 320)
        self.assertEqual(norm_t["length"], 60)
        self.assertEqual(norm_t["label"], "Backyard View")
        self.assertEqual(norm_t["orientation"], "exterior")

        win_dict = {
            "side": "bottom",
            "pos": 280,
            "length": 55,
            "label": "Front Window",
            "orientation": "exterior",
        }
        norm_d = normalize_window_spec(win_dict, room)
        self.assertEqual(norm_d["side"], "bottom")
        self.assertEqual(norm_d["pos"], 280)
        self.assertEqual(norm_d["length"], 55)

    def test_detect_door_orientation_corner_clearance(self) -> None:
        """Verify automatic door swing orientation detection based on corner clearance and wall sides."""
        room = {"id": "guest_room", "x": 180, "y": 805, "width": 270, "height": 150, "zone": "upper"}

        # Door on bottom wall closer to right wall than left wall
        # pos = 380, length = 36. dist_left = 380 - 180 = 200. dist_right = (180+270) - (380+36) = 450 - 416 = 34.
        orient_right = detect_door_orientation(room, "bottom", 380, 36)
        self.assertEqual(orient_right, "inward-right")

        # Door on bottom wall closer to left wall
        # pos = 200, length = 36. dist_left = 20. dist_right = 450 - 236 = 214.
        orient_left = detect_door_orientation(room, "bottom", 200, 36)
        self.assertEqual(orient_left, "inward-left")

        # Mudroom exterior exit door on top wall swings outward
        mudroom = {"id": "mudroom", "x": 760, "y": 225, "width": 160, "height": 130, "zone": "main"}
        orient_out = detect_door_orientation(mudroom, "top", 800, 32)
        self.assertEqual(orient_out, "outward-left")

    def test_detect_exterior_windows_on_isolated_room(self) -> None:
        """Verify automatic exterior window detection on room with exposed perimeter walls."""
        room = {
            "id": "standalone_office",
            "name": "Standalone Office",
            "x": 300,
            "y": 300,
            "width": 200,
            "height": 150,
            "zone": "main",
            "doors": [("bottom", 380, 40, "Entrance Door")],
        }
        all_rooms = [room]

        windows = detect_exterior_windows(room, all_rooms)
        self.assertGreater(len(windows), 0)
        sides = [w["side"] for w in windows]
        # Top, left, and right should have windows since they are exterior and have no door conflicts
        self.assertIn("top", sides)
        self.assertIn("left", sides)
        self.assertIn("right", sides)

    def test_svg_rendering_includes_door_swings_and_windows(self) -> None:
        """Verify that generated SVG contains door swing arcs, door leaves, and architectural window symbols."""
        mock_cap_map = {
            "areas": {
                "foyer": {"name": "Foyer", "entities": ["light.foyer_lights"]},
                "dining_room": {"name": "Dining Room", "entities": ["light.dining"]},
            },
            "entities": [
                {"entity_id": "light.foyer_lights", "name": "Foyer Lights", "domain": "light"},
                {"entity_id": "light.dining", "name": "Dining", "domain": "light"},
            ],
            "spatial_graph": {"adjacencies": {"foyer": ["dining_room"]}},
        }

        output_svg = "test_architectural_fp.svg"
        res = asyncio.run(
            self.parser.async_generate_svg_floorplan(
                mock_cap_map,
                output_relative_path=output_svg,
            )
        )
        self.assertTrue(res["success"])

        full_path = self.hass.config.path(output_svg)
        with open(full_path, "r", encoding="utf-8") as f:
            svg = f.read()

        # Check door elements
        self.assertIn('class="door-cut"', svg)
        self.assertIn('class="door-leaf"', svg)
        self.assertIn('class="door-swing"', svg)
        self.assertIn("<path", svg)

        # Check window elements
        self.assertIn('class="window-cut"', svg)
        self.assertIn('class="window-sill"', svg)
        self.assertIn('class="window-pane"', svg)
        self.assertIn('class="window-cap"', svg)

    def test_multiclip_walkthrough_sequential_continuity(self) -> None:
        """Verify multi-clip processing preserves sequential room ordering and creates inter-clip continuity adjacencies."""
        area_list = [
            {"id": "frontyard", "name": "Frontyard"},
            {"id": "foyer", "name": "Foyer"},
            {"id": "great_room", "name": "Great Room"},
            {"id": "kitchen", "name": "Kitchen"},
            {"id": "mudroom", "name": "Mudroom"},
            {"id": "garage", "name": "Garage"},
        ]

        # Clip 1 visits Frontyard -> Foyer -> Great Room
        clip1_analysis = {
            "transcript": "Starting at the front porch and walking through the foyer into great room.",
            "ordered_areas": ["frontyard", "foyer", "great_room"],
            "adjacencies": [["frontyard", "foyer"], ["foyer", "great_room"]],
            "floor_assignments": {"frontyard": "outdoor", "foyer": "main", "great_room": "main"},
            "contained_areas": {},
            "detected_doors": [{"room": "foyer", "side": "bottom", "orientation": "inward-right", "label": "Front Door"}],
            "detected_windows": [{"room": "great_room", "side": "top", "label": "Backyard Window"}],
        }

        # Clip 2 continues from Great Room -> Kitchen -> Mudroom -> Garage
        clip2_analysis = {
            "transcript": "From great room stepping into kitchen, back through mudroom into garage.",
            "ordered_areas": ["great_room", "kitchen", "mudroom", "garage"],
            "adjacencies": [["great_room", "kitchen"], ["kitchen", "mudroom"], ["mudroom", "garage"]],
            "floor_assignments": {"kitchen": "main", "mudroom": "main", "garage": "main"},
            "contained_areas": {"great_room": ["kitchen"]},
            "detected_doors": [{"room": "mudroom", "side": "right", "orientation": "inward-top", "label": "Garage Entry"}],
            "detected_windows": [{"room": "garage", "side": "right", "label": "Side Garage Window"}],
        }

        async def _mock_analyze(audio_path, areas, frame_paths=None):
            if "clip_1" in audio_path or "clip1" in audio_path:
                return clip1_analysis
            return clip2_analysis

        self.parser.async_analyze_walkthrough_audio = AsyncMock(side_effect=_mock_analyze)

        # Mock audio files
        c1_audio = os.path.join(self.tmp_dir, "walkthrough_clip_1.mp3")
        c2_audio = os.path.join(self.tmp_dir, "walkthrough_clip_2.mp3")
        with open(c1_audio, "wb") as f1, open(c2_audio, "wb") as f2:
            f1.write(b"mock_audio_1")
            f2.write(b"mock_audio_2")

        clips = [
            {"audio_path": c1_audio},
            {"audio_path": c2_audio},
        ]

        progress_messages: list[str] = []

        def _on_progress(msg, names):
            progress_messages.append(msg)

        res = asyncio.run(
            self.parser.async_process_multiclip_walkthrough(
                clips,
                area_list,
                upload_dir=self.tmp_dir,
                progress_callback=_on_progress,
            )
        )

        self.assertEqual(res["clips_processed"], 2)
        # All 6 areas discovered in sequential order
        self.assertEqual(
            res["ordered_areas"],
            ["frontyard", "foyer", "great_room", "kitchen", "mudroom", "garage"],
        )
        self.assertEqual(len(res["transcripts"]), 2)
        self.assertIn("[Clip 1]", res["transcripts"][0])
        self.assertIn("[Clip 2]", res["transcripts"][1])

        # Verify cross-clip adjacency continuity
        adj_pairs = res["adjacencies"]
        self.assertIn(["frontyard", "foyer"], adj_pairs)
        self.assertIn(["foyer", "great_room"], adj_pairs)
        self.assertIn(["great_room", "kitchen"], adj_pairs)
        self.assertIn(["kitchen", "mudroom"], adj_pairs)
        self.assertIn(["mudroom", "garage"], adj_pairs)

        # Verify combined doors and windows
        self.assertEqual(len(res["detected_doors"]), 2)
        self.assertEqual(len(res["detected_windows"]), 2)
        door_labels = [d["label"] for d in res["detected_doors"]]
        self.assertIn("Front Door", door_labels)
        self.assertIn("Garage Entry", door_labels)

        # Verify progress callback messages
        self.assertGreater(len(progress_messages), 0)

    def test_audio_concatenation_single_clip(self) -> None:
        """Verify audio concatenation handles single clip trivially via direct file copy."""
        src_path = os.path.join(self.tmp_dir, "source.mp3")
        dst_path = os.path.join(self.tmp_dir, "dest.mp3")
        with open(src_path, "wb") as f:
            f.write(b"audio_bytes")

        success = asyncio.run(self.parser.async_concatenate_audio_clips([src_path], dst_path))
        self.assertTrue(success)
        self.assertTrue(os.path.exists(dst_path))
        with open(dst_path, "rb") as f:
            self.assertEqual(f.read(), b"audio_bytes")


if __name__ == "__main__":
    unittest.main()
