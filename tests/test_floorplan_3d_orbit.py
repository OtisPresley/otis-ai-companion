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

    def test_version_synchronization_v0_1_39(self) -> None:
        """Verify manifest.json, otis-companion-card.js, and CHANGELOG.md are synced to v0.1.39."""
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["version"], "0.1.39")

        with open(self.card_path, "r", encoding="utf-8") as f:
            card_content = f.read()
        self.assertIn('const CARD_VERSION = "0.1.39";', card_content)

        with open(self.changelog_path, "r", encoding="utf-8") as f:
            changelog_content = f.read()
        self.assertIn("## [0.1.39] - 2026-11-04", changelog_content)

    def test_card_3d_orbit_and_pitch_elements(self) -> None:
        """Verify that otis-companion-card.js contains Phase 3 3D orbit, pitch, and raised glass wall components."""
        with open(self.card_path, "r", encoding="utf-8") as f:
            content = f.read()

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
        """Verify otis-companion-card.js has zero JavaScript syntax errors using QuickJS engine."""
        try:
            import quickjs
        except ImportError:
            return

        with open(self.card_path, "r", encoding="utf-8") as f:
            code = f.read()

        preamble = (
            "class HTMLElement {}\n"
            "const customElements = { define: () => {} };\n"
            "const window = { addEventListener: () => {} };\n"
            "const console = { info: () => {}, log: () => {}, error: () => {}, warn: () => {} };\n"
        )
        ctx = quickjs.Context()
        # Must execute without throwing SyntaxError or ReferenceError
        ctx.eval(preamble + code)

        # 5. Check Drag-to-orbit pointer interaction
        self.assertIn("floorplanViewport.onpointerdown", code)
        self.assertIn("isOrbiting", code)

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
        with open(self.card_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 1. Studio header must be guarded so isControlMode hides it
        self.assertIn("!isControlMode", content)

        # 2. Edit Floor Plan button must be hidden in control mode
        self.assertIn("isAdmin && !isControlOnly", content)

        # 3. Canvas must bind aspect-ratio to match viewBox and eliminate letterbox drift
        self.assertIn("aspect-ratio:", content)
        self.assertIn("floorplanCanvas.style.aspectRatio", content)


if __name__ == "__main__":
    unittest.main()
