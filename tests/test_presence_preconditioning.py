"""Tests for Phase 4 Step 1: Contextual Presence-Based Migration Flow & Macro Pre-Conditioning."""
from __future__ import annotations

from typing import Any
import unittest
from unittest.mock import MagicMock
import time

from custom_components.otis_ai.vision_manager import VisionPresenceManager
from custom_components.otis_ai.dashboard_manager import DashboardManager


class TestPresencePreconditioning(unittest.IsolatedAsyncioTestCase):
    """Test presence migration tracking and macro pre-conditioning hypotheses."""

    def setUp(self) -> None:
        """Set up mocked Home Assistant environment."""
        self.hass = MagicMock()
        self.hass.states = MagicMock()
        self._states_store: dict[str, Any] = {}

        def mock_set(entity_id, state, attributes=None):
            self._states_store[entity_id] = {"state": state, "attributes": attributes or {}}

        self.hass.states.async_set.side_effect = mock_set
        self.hass.states.get.side_effect = lambda eid: self._states_store.get(eid)
        self.vision_manager = VisionPresenceManager(self.hass)

    def test_record_and_retrieve_area_transitions(self) -> None:
        """Test recording physical presence transitions between areas."""
        t1 = self.vision_manager.record_area_transition("kitchen", "hallway", confidence=0.88)
        self.assertEqual(t1["from_area"], "kitchen")
        self.assertEqual(t1["to_area"], "hallway")
        self.assertEqual(t1["confidence"], 0.88)

        t2 = self.vision_manager.record_area_transition("hallway", "theater", confidence=0.92)
        self.assertEqual(t2["from_area"], "hallway")
        self.assertEqual(t2["to_area"], "theater")

        history = self.vision_manager.get_transition_history(10)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["from_area"], "kitchen")
        self.assertEqual(history[1]["to_area"], "theater")

    async def test_detect_movie_night_migration_intent(self) -> None:
        """Test detecting evening movie night migration toward theater."""
        # Record transition from kitchen to hallway
        now_ts = time.time()
        self.vision_manager.record_area_transition("kitchen", "hallway", confidence=0.9, timestamp=now_ts)

        presence_data = {
            "occupied_areas": ["Hallway"],
            "rooms": {
                "hallway": {"probability": 0.85, "status": "occupied"},
                "theater": {"probability": 0.05, "status": "vacant"},
            },
        }

        # Mock current hour as 20.5 (8:30 PM evening)
        from unittest.mock import patch
        with patch("custom_components.otis_ai.vision_manager.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 20
            mock_now.minute = 30
            mock_now.isoformat.return_value = "2026-11-04T20:30:00"
            mock_dt.now.return_value = mock_now
            mock_dt.fromtimestamp = lambda ts: mock_now

            intent = await self.vision_manager.async_detect_migration_intent(presence_data)
            self.assertIsNotNone(intent)
            self.assertEqual(intent["intent"], "movie_night")
            self.assertEqual(intent["target_area"], "theater")
            self.assertEqual(intent["lifestyle_macro"], "movie_night_mode")
            self.assertEqual(intent["preconditioning_state"], "armed")

    async def test_detect_bedtime_sleep_migration_intent(self) -> None:
        """Test detecting bedtime sleep migration toward master suite."""
        now_ts = time.time()
        self.vision_manager.record_area_transition("great_room", "hallway", confidence=0.85, timestamp=now_ts)

        presence_data = {
            "occupied_areas": ["Hallway"],
            "rooms": {
                "hallway": {"probability": 0.80, "status": "occupied"},
                "master": {"probability": 0.10, "status": "vacant"},
            },
        }

        from unittest.mock import patch
        with patch("custom_components.otis_ai.vision_manager.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 22
            mock_now.minute = 45
            mock_now.isoformat.return_value = "2026-11-04T22:45:00"
            mock_dt.now.return_value = mock_now
            mock_dt.fromtimestamp = lambda ts: mock_now

            intent = await self.vision_manager.async_detect_migration_intent(presence_data)
            self.assertIsNotNone(intent)
            self.assertEqual(intent["intent"], "sleep_bedtime")
            self.assertEqual(intent["target_area"], "master")
            self.assertEqual(intent["lifestyle_macro"], "bedtime_mode")

    async def test_process_presence_transitions_and_sensor_publication(self) -> None:
        """Test full transition processing and publication of sensor.otis_spatial_migration."""
        presence_data = {
            "occupied_areas": ["Hallway"],
            "rooms": {
                "hallway": {"probability": 0.90, "status": "occupied"},
                "theater": {"probability": 0.0, "status": "vacant"},
            },
        }

        # Set prior room
        self.vision_manager._last_active_area = "living_room"
        self.vision_manager._last_active_area_ts = time.time() - 30

        from unittest.mock import patch
        with patch("custom_components.otis_ai.vision_manager.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 19
            mock_now.minute = 15
            mock_now.isoformat.return_value = "2026-11-04T19:15:00"
            mock_dt.now.return_value = mock_now
            mock_dt.fromtimestamp = lambda ts: mock_now

            await self.vision_manager.async_process_presence_transitions(presence_data)

            self.assertIn("sensor.otis_spatial_migration", self._states_store)
            sensor_state = self._states_store["sensor.otis_spatial_migration"]
            self.assertEqual(sensor_state["state"], "movie_night")
            attrs = sensor_state["attributes"]
            self.assertEqual(attrs["target_area"], "theater")
            self.assertEqual(attrs["preconditioning_state"], "armed")
            self.assertEqual(attrs["lifestyle_macro"], "movie_night_mode")

    def test_dashboard_manager_3d_view_generation(self) -> None:
        """Test that dashboard_manager builds 3D companion card when floorplan_view_mode is 3d."""
        rules_manager = MagicMock()
        rules_manager.get_rules.return_value = {"floorplan_view_mode": "3d", "floorplan_3d": True}

        dash_mgr = DashboardManager(self.hass, rules_manager=rules_manager)
        cards = dash_mgr._build_floorplan_view_cards(capability_map=None)

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["type"], "custom:otis-companion-card")
        self.assertEqual(cards[0]["mode"], "floorplan_control")
        self.assertEqual(cards[0]["view_mode"], "3d")


if __name__ == "__main__":
    unittest.main()
