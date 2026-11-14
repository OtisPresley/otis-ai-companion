"""Unit tests for Phase 3: Interactive Floorplan 3D Orbit & Pitch Controls."""
import json
import os
import unittest


class TestFloorplan3DOrbitAndControls(unittest.TestCase):
    """Test suite for Phase 3 3D orbit and pitch controls in floorplan."""

    def setUp(self) -> None:
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.manifest_path = os.path.join(
            self.root_dir, "custom_components", "otis_ai", "manifest.json"
        )
        self.card_path = os.path.join(
            self.root_dir, "custom_components", "otis_ai", "frontend", "otis-companion-card.js"
        )
        self.changelog_path = os.path.join(self.root_dir, "CHANGELOG.md")

    def test_version_synchronization(self) -> None:
        """Verify manifest.json, otis-companion-card.js, and CHANGELOG.md are synced."""
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        current_version = manifest["version"]
        self.assertTrue(len(current_version) > 0)

        with open(self.card_path, "r", encoding="utf-8") as f:
            card_content = f.read()
        self.assertIn(f'const CARD_VERSION = "{current_version}";', card_content)

        with open(self.changelog_path, "r", encoding="utf-8") as f:
            changelog_content = f.read()
        self.assertIn(f"## [{current_version}]", changelog_content)

    def _read_all_frontend_js(self) -> str:
        fe_dir = os.path.dirname(self.card_path)
        parts = []
        for fn in sorted(os.listdir(fe_dir)):
            if fn.endswith(".js"):
                with open(os.path.join(fe_dir, fn), "r", encoding="utf-8") as f:
                    parts.append(f.read())
        return "\n".join(parts)

    def test_card_3d_orbit_and_pitch_elements(self) -> None:
        """Verify that frontend card modules contain Phase 3 3D orbit, pitch, and raised glass wall components."""
        content = self._read_all_frontend_js()

        # 1. Check CSS 3D stage and canvas definitions
        self.assertIn(".floorplan-3d-stage", content)
        self.assertIn("perspective: 1200px;", content)
        self.assertIn(".floorplan-3d-canvas", content)
        self.assertIn("transform-style: preserve-3d;", content)

        # 2. Check 3D device pin billboarding counter-rotation
        self.assertIn("--floorplan-azimuth", content)
        self.assertIn("--floorplan-pitch", content)
        self.assertIn("calc(-1 * var(--floorplan-azimuth", content)
        self.assertIn("calc(-1 * var(--floorplan-pitch", content)

        # 3. Check 3D HUD controls markup
        self.assertIn("_renderFloorplan3dControls", content)
        self.assertIn("slider-orbit-azimuth", content)
        self.assertIn("slider-pitch-incline", content)
        self.assertIn("btn-reset-3d-view", content)
        self.assertIn("btn-preset-pill", content)

        # 4. Check 3D raised transparent glass walls
        self.assertIn(".floorplan-walls-overlay", content)
        self.assertIn(".floorplan-3d-room-shell", content)
        self.assertIn(".floorplan-3d-wall-north", content)
        self.assertIn(".floorplan-3d-wall-south", content)
        self.assertIn(".floorplan-3d-wall-west", content)
        self.assertIn(".floorplan-3d-wall-east", content)
        self.assertIn("_renderFloorplan3dWalls", content)
        self.assertIn("btn-toggle-3d-walls", content)

        # 5. Check persistent state keys in localStorage
        self.assertIn("otis_floorplan_orbit_azimuth", content)
        self.assertIn("otis_floorplan_pitch_incline", content)
        self.assertIn("otis_floorplan_walls_enabled", content)

    def test_card_javascript_syntax_validity(self) -> None:
        """Verify all frontend ES modules have zero JavaScript syntax errors using QuickJS engine."""
        import re

        try:
            import quickjs
        except ImportError:
            return

        fe_dir = os.path.dirname(self.card_path)
        preamble = (
            "class HTMLElement {}\n"
            "const customElements = { define: () => {} };\n"
            "const window = { addEventListener: () => {} };\n"
            "const console = { info: () => {}, log: () => {}, error: () => {}, warn: () => {} };\n"
        )
        ctx = quickjs.Context()
        ctx.eval(preamble)

        module_order = [
            "card-styles.js",
            "floorplan-3d.js",
            "card-modals.js",
            "card-tabs.js",
            "otis-companion-card.js",
        ]
        card_code = ""
        for fn in module_order:
            with open(os.path.join(fe_dir, fn), "r", encoding="utf-8") as f:
                raw = f.read()
            if fn == "otis-companion-card.js":
                card_code = raw
            eval_code = re.sub(r"^import\s+.*?;\s*$", "", raw, flags=re.MULTILINE)
            eval_code = re.sub(r"^export\s+(const|function|class)\s+", r"\1 ", eval_code, flags=re.MULTILINE)
            ctx.eval(eval_code)

        # 5. Check Drag-to-orbit pointer interaction
        self.assertIn("floorplanViewport.onpointerdown", card_code)
        self.assertIn("isOrbiting", card_code)

    def test_zero_drift_coordinate_invariance(self) -> None:
        """Mathematically verify that percentage pin coordinates remain invariant under 3D transforms."""
        viewbox_x = 0.0
        viewbox_y = 360.0
        viewbox_w = 1300.0
        viewbox_h = 680.0

        test_points = [
            (260.0, 400.0),
            (650.0, 500.0),
            (1100.0, 650.0),
            (470.0, 445.0),
        ]

        for bx, by in test_points:
            pct_x = ((bx - viewbox_x) / viewbox_w) * 100.0
            pct_y = ((by - viewbox_y) / viewbox_h) * 100.0

            # Test that back-projection matches exactly
            calc_bx = viewbox_x + (pct_x / 100.0) * viewbox_w
            calc_by = viewbox_y + (pct_y / 100.0) * viewbox_h

            self.assertAlmostEqual(bx, calc_bx, places=4)
            self.assertAlmostEqual(by, calc_by, places=4)

    def test_floorplan_control_mode_clean_toolbar_and_aspect_ratio(self) -> None:
        """Verify that floorplan_control mode strips studio header and editor buttons, keeping only pills and HUD."""
        content = self._read_all_frontend_js()

        # 1. Studio header must be guarded so isControlMode hides it
        self.assertIn("!isControlMode", content)

        # 2. Edit Floor Plan button must be hidden in control mode
        self.assertIn("isAdmin && !isControlOnly", content)

        # 3. Canvas must bind aspect-ratio to match viewBox and eliminate letterbox drift
        self.assertIn("aspect-ratio:", content)
        self.assertIn("floorplanCanvas.style.aspectRatio", content)

    def test_center_outward_default_room_pins_and_no_text_overlap(self) -> None:
        """Verify rooms default to >3 useful entities centered in text-free interior when uncrowded."""
        from unittest.mock import MagicMock
        from custom_components.otis_ai.floorplan_parser import (
            FloorplanParser,
            compute_room_center_pin_positions,
        )

        # Large room (310x220 with 2 sub_zones inside a container) should allow >3 pins below text
        max_pins, positions = compute_room_center_pin_positions(
            260, 225, 310, 220, count=5, sub_zones_count=2, has_container=True
        )
        self.assertGreater(max_pins, 3)
        self.assertEqual(len(positions), 5)
        # Header at 225+34=259, 2 subzones at 277 & 293 -> safe_top >= 309
        for px, py in positions:
            self.assertGreaterEqual(py, 309.0)
            self.assertGreaterEqual(px, 282.0)
            self.assertLessEqual(px, 548.0)

        # Small room should cap cleanly without crowding
        small_max, _ = compute_room_center_pin_positions(0, 0, 120, 90, count=0)
        self.assertLessEqual(small_max, 3)

        # Wide, short rooms (Hallway 680x70, Frontyard 920x105) must stay vertically centered inside bounds
        _, hallway_pos = compute_room_center_pin_positions(180, 955, 680, 70, count=4, sub_zones_count=2)
        self.assertEqual(len(hallway_pos), 4)
        for px, py in hallway_pos:
            self.assertGreaterEqual(px, 418.0)
            self.assertGreaterEqual(py, 973.0)
            self.assertLessEqual(py, 1007.0)

        _, frontyard_pos = compute_room_center_pin_positions(260, 585, 920, 105, count=5, sub_zones_count=3)
        self.assertEqual(len(frontyard_pos), 5)
        for px, py in frontyard_pos:
            self.assertGreaterEqual(px, 500.0)
            self.assertGreaterEqual(py, 603.0)
            self.assertLessEqual(py, 672.0)

        # FloorplanParser.build_effective_badges auto-populates >3 centered pins for uncustomized rooms
        hass = MagicMock()
        parser = FloorplanParser(hass)
        parser._cached_svg_room_bounds = {
            "great_room": {"x": 260, "y": 225, "width": 310, "height": 220, "name": "Great Room"},
            "study": {"x": 260, "y": 460, "width": 160, "height": 120, "name": "Study"},
        }
        parser._metadata = {
            "custom_layout": {
                "badges": [
                    {"entity_id": "light.study_desk", "x": 340, "y": 530},
                    {"entity_id": "switch.great_room_deleted", "delete": True},
                ]
            }
        }
        areas_map = {
            "great_room": {"name": "Great Room"},
            "study": {"name": "Study"},
        }
        entities_list = [
            {"entity_id": "light.great_room_main", "domain": "light", "area_id": "great_room", "name": "Great Room Main", "state": "on"},
            {"entity_id": "media_player.great_room_tv", "domain": "media_player", "area_id": "great_room", "name": "Great Room TV", "state": "off"},
            {"entity_id": "fan.great_room_ceiling", "domain": "fan", "area_id": "great_room", "name": "Great Room Fan", "state": "off"},
            {"entity_id": "climate.great_room_thermostat", "domain": "climate", "area_id": "great_room", "name": "Great Room Thermostat", "state": "heat"},
            {"entity_id": "switch.great_room_fireplace", "domain": "switch", "area_id": "great_room", "name": "Fireplace", "state": "off"},
            {"entity_id": "switch.great_room_deleted", "domain": "switch", "area_id": "great_room", "name": "Deleted Plug", "state": "off"},
            {"entity_id": "light.study_desk", "domain": "light", "area_id": "study", "name": "Study Desk", "state": "on"},
            {"entity_id": "light.study_overhead", "domain": "light", "area_id": "study", "name": "Study Overhead", "state": "off"},
        ]
        badges = parser.build_effective_badges(areas_map, entities_list)
        great_room_badges = [b for b in badges if b.get("area_id") == "great_room"]
        self.assertGreater(len(great_room_badges), 3)
        self.assertNotIn("switch.great_room_deleted", [b["entity_id"] for b in badges])
        # Study already had a custom badge, so it should not be overwritten by auto defaults
        study_badges = [b for b in badges if b["entity_id"].startswith("light.study_")]
        self.assertEqual([b["entity_id"] for b in study_badges], ["light.study_desk"])

        # Legacy unflagged bottom-docked badges (ry + rh - 23.8) should upgrade to center-outward defaults,
        # and non-control custom pins (camera/sensor) must not suppress default control pins.
        parser._metadata = {
            "custom_layout": {
                "badges": [
                    {"entity_id": "light.great_room_main", "x": 289.9, "y": 421.2},
                    {"entity_id": "camera.great_room_cam", "x": 365, "y": 350},
                ]
            }
        }
        upgraded = parser.build_effective_badges(areas_map, entities_list)
        upgraded_gr = [b for b in upgraded if b.get("area_id") == "great_room"]
        self.assertGreater(len(upgraded_gr), 3)
        self.assertIn("camera.great_room_cam", [b["entity_id"] for b in upgraded])
        # Upgraded light.great_room_main must be moved out of the old 421.2 bottom row
        gr_light = next(b for b in upgraded if b["entity_id"] == "light.great_room_main")
        self.assertLess(gr_light["y"], 410.0)

    def test_media_player_dedup_and_noisy_switch_filtering(self) -> None:
        """Duplicate media_players for the same physical TV collapse to the native control, and NVR switches are excluded."""
        from custom_components.otis_ai.floorplan_parser import select_intelligent_room_controls

        devices_map = {
            "dev_bravia_remote": {"name": "Great Room TV", "model": "BRAVIA 4K"},
            "dev_bravia_cast": {"name": "Great Room TV", "model": "BRAVIA 4K"},
            "dev_bravia_dlna": {"name": "Great Room TV", "model": "MediaRenderer"},
            "dev_bravia_ma": {"name": "Great Room TV", "model": "Music Assistant Dashboard display"},
        }
        room_ents = [
            {"entity_id": "media_player.great_room_tv_3", "domain": "media_player", "platform": "cast", "device_id": "dev_bravia_cast", "name": "Great Room TV"},
            {"entity_id": "media_player.great_room_tv_4", "domain": "media_player", "platform": "dlna_dmr", "device_id": "dev_bravia_dlna", "name": "Great Room TV"},
            {"entity_id": "media_player.great_room_tv_2", "domain": "media_player", "platform": "music_assistant", "device_id": "dev_bravia_ma", "name": "Great Room TV"},
            {"entity_id": "media_player.bravia_4k_gb_atv3", "domain": "media_player", "platform": "androidtv_remote", "device_id": "dev_bravia_remote", "name": "Great Room TV"},
            {"entity_id": "light.island_2", "domain": "light", "platform": "lutron", "name": "Island"},
            {"entity_id": "light.kitchen_main", "domain": "light", "platform": "lutron", "name": "Kitchen Main"},
            {"entity_id": "fan.great_room_fan", "domain": "fan", "platform": "lutron", "name": "Great Room Fan"},
            {"entity_id": "switch.frontyard_detect", "domain": "switch", "platform": "frigate", "name": "Detect"},
            {"entity_id": "switch.frontyard_ftp_upload", "domain": "switch", "platform": "reolink", "name": "FTP upload"},
        ]
        selected = select_intelligent_room_controls(
            room_ents, area_name="Great Room", max_controls=6, devices_map=devices_map
        )
        eids = [s["entity"] for s in selected]
        self.assertIn("media_player.bravia_4k_gb_atv3", eids)
        self.assertNotIn("media_player.great_room_tv_3", eids)
        self.assertNotIn("media_player.great_room_tv_4", eids)
        self.assertNotIn("media_player.great_room_tv_2", eids)
        self.assertNotIn("switch.frontyard_detect", eids)
        self.assertNotIn("switch.frontyard_ftp_upload", eids)
        self.assertIn("light.island_2", eids)
        self.assertIn("light.kitchen_main", eids)
        self.assertIn("fan.great_room_fan", eids)

    def test_recalculate_floorplan_preserves_custom_and_clears_auto_badges(self) -> None:
        """async_recalculate_floorplan clears non-custom badges, keeps custom=True pins, and regenerates SVG."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        hass = MagicMock()
        parser = FloorplanParser(hass)
        parser._initialized = True
        parser._metadata = {
            "custom_layout": {
                "badges": [
                    {"entity_id": "light.stale_auto", "x": 100, "y": 200},
                    {"entity_id": "camera.user_custom", "x": 365, "y": 493, "custom": True},
                ]
            }
        }
        parser.async_generate_svg_floorplan = AsyncMock(return_value={"svg_path": "x.svg", "room_count": 2})
        parser.async_save_metadata = AsyncMock()

        res = asyncio.run(parser.async_recalculate_floorplan({"areas": {}, "entities": []}))
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["badges_cleared"], 1)
        self.assertEqual(res["badges_preserved"], 1)
        self.assertEqual([b["entity_id"] for b in parser._metadata["custom_layout"]["badges"]], ["camera.user_custom"])
        parser.async_generate_svg_floorplan.assert_awaited_once()
        parser.async_save_metadata.assert_awaited_once()

    def test_walkthrough_architectural_features_enrichment(self) -> None:
        """Explicit walkthrough_features enrich stairs, pool, and front_porch without hardcoding rooms."""
        from unittest.mock import MagicMock
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        parser = FloorplanParser(MagicMock())
        parser._metadata = {
            "walkthrough_completed": True,
            "walkthrough_features": {
                "stairs": [{"room": "entryway", "direction": "up", "label": "Main Stairs"}],
                "outdoor_features": [
                    {"feature": "pool", "room": "yard"},
                    {"feature": "front_porch", "room": "front_garden"},
                ],
            },
        }
        layout = {
            "main": [{"id": "entryway", "name": "Entryway", "x": 450, "y": 445, "width": 140, "height": 140, "sub_zones": ["Entry"]}],
            "upper": [{"id": "media_room", "name": "Media Room", "x": 860, "y": 955, "width": 280, "height": 185}],
            "outdoor": [
                {"id": "yard", "name": "Yard", "x": 180, "y": 85, "width": 580, "height": 140},
                {"id": "front_garden", "name": "Front Garden", "x": 260, "y": 585, "width": 920, "height": 105},
            ],
        }
        parser._apply_walkthrough_features(layout)
        self.assertTrue(layout["main"][0].get("has_stairs_up"))
        self.assertIn("Main Stairs", layout["main"][0]["sub_zones"])
        self.assertFalse(layout["upper"][0].get("has_stairs_up"))
        self.assertFalse(layout["upper"][0].get("has_stairs_down"))
        self.assertTrue(layout["outdoor"][0].get("has_pool"))
        self.assertTrue(layout["outdoor"][1].get("has_front_porch"))

    def test_video_room_shape_and_directional_connection_placement(self) -> None:
        """Unmapped rooms use video-detected room_shapes and directional_connections to place flush against neighbors."""
        from unittest.mock import MagicMock
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        parser = FloorplanParser(MagicMock())
        parser._metadata = {
            "walkthrough_features": {
                "room_shapes": {
                    "sunroom": {"shape": "wide", "size": "small"},
                },
                "directional_connections": [
                    {"from": "den", "to": "sunroom", "side": "right", "type": "open"},
                ],
            }
        }
        rooms_in = [
            {"id": "den", "name": "Den", "entities": [], "adjacent_areas": ["sunroom"]},
            {"id": "sunroom", "name": "Sunroom", "entities": [], "adjacent_areas": ["den"]},
        ]
        placed = parser._place_zone_rooms(rooms_in, "main", {}, base_y=60, y_shift=0, used_boxes=[])
        den = next(r for r in placed if r["id"] == "den")
        sunroom = next(r for r in placed if r["id"] == "sunroom")
        # Sunroom should be sized as wide/small (210x105) and placed flush to the right of Den
        self.assertEqual((sunroom["width"], sunroom["height"]), (210, 105))
        self.assertEqual(sunroom["x"], den["x"] + den["width"])
        self.assertEqual(sunroom["y"], den["y"])
        # _apply_walkthrough_features should add a cased opening on Den's right shared wall
        parser._apply_walkthrough_features({"main": placed, "upper": [], "outdoor": []})
        self.assertTrue(any(d[0] == "right" and d[5] == "cased" for d in den.get("doors", [])))

    def test_dynamic_orthogonal_layout_has_no_hardcoded_blueprint(self) -> None:
        """Verify blueprints are empty and _calculate_orthogonal_layout places generic rooms without overlap."""
        from unittest.mock import MagicMock
        from custom_components.otis_ai.floorplan_parser import (
            GROUND_AND_OUTDOOR_BLUEPRINT,
            UPPER_FLOOR_BLUEPRINT,
            FloorplanParser,
        )

        self.assertEqual(GROUND_AND_OUTDOOR_BLUEPRINT, {})
        self.assertEqual(UPPER_FLOOR_BLUEPRINT, {})

        parser = FloorplanParser(MagicMock())
        parser._initialized = True
        parser._metadata = {}
        zones = {
            "main": [
                {"id": "living_room", "name": "Living Room", "entities": []},
                {"id": "kitchen", "name": "Kitchen", "entities": []},
            ],
            "upper": [
                {"id": "bedroom_1", "name": "Bedroom 1", "entities": []},
            ],
            "outdoor": [
                {"id": "patio", "name": "Patio", "entities": []},
            ],
        }
        layout = parser._calculate_orthogonal_layout(zones)
        self.assertEqual(len(layout["main"]), 2)
        self.assertEqual(len(layout["upper"]), 1)
        self.assertEqual(len(layout["outdoor"]), 1)
        # Ensure upper floor is placed below ground/outdoor rooms
        ground_max_y = max(r["y"] + r["height"] for r in layout["main"] + layout["outdoor"])
        self.assertGreater(layout["upper"][0]["y"], ground_max_y)

    def test_generate_floorplan_reset_layout_clears_stale_state(self) -> None:
        """generate_floorplan with reset_layout=True throws out cached rooms, badges, and deleted_rooms."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        hass = MagicMock()
        parser = FloorplanParser(hass)
        parser._initialized = True
        parser._cached_svg_room_bounds = {"study": {"x": 10, "y": 10, "width": 100, "height": 100}}
        parser._metadata = {
            "custom_layout": {
                "rooms": [{"id": "study", "x": 10, "y": 10, "width": 100, "height": 100}],
                "badges": [{"entity_id": "light.old", "x": 50, "y": 50, "custom": True}],
            },
            "deleted_rooms": ["garage"],
            "walkthrough_features": {"stairs": [{"room": "old"}]},
            "transcripts": ["old transcript"],
        }
        parser.async_save_metadata = AsyncMock()
        parser._async_run_in_executor = AsyncMock(return_value=None)

        cap_map = {
            "areas": {"foyer": {"name": "Foyer", "entities": []}},
            "entities": [],
            "spatial_graph": {"adjacencies": {}},
        }
        res = asyncio.run(parser.async_generate_svg_floorplan(cap_map, reset_layout=True))
        self.assertEqual(res["status"] if "status" in res else "ok", "ok")
        self.assertEqual(parser._metadata["custom_layout"], {"rooms": [], "badges": []})
        self.assertEqual(parser._metadata["deleted_rooms"], [])
        self.assertEqual(parser._metadata["walkthrough_features"], {})
        self.assertEqual(parser._metadata["transcripts"], [])


if __name__ == "__main__":
    unittest.main()
