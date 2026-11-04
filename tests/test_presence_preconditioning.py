"""Tests for Phase 4 Step 1: Contextual Presence-Based Migration Flow & Macro Pre-Conditioning."""
from __future__ import annotations

from typing import Any
import unittest
from unittest.mock import MagicMock, AsyncMock
import time
import asyncio

from custom_components.otis_ai.vision_manager import VisionPresenceManager
from custom_components.otis_ai.dashboard_manager import DashboardManager
from custom_components.otis_ai.macro_manager import MacroManager


class TestPresencePreconditioning(unittest.IsolatedAsyncioTestCase):
    """Test presence migration tracking and macro pre-conditioning hypotheses."""

    def setUp(self) -> None:
        """Set up mocked Home Assistant environment."""
        self.hass = MagicMock()
        self.hass.states = MagicMock()
        self._states_store: dict[str, Any] = {}

        def mock_set(entity_id, state, attributes=None):
            self._states_store[entity_id] = MagicMock(
                entity_id=entity_id,
                state=state,
                attributes=attributes or {},
            )

        def mock_all():
            return list(self._states_store.values())

        self.hass.states.async_set.side_effect = mock_set
        self.hass.states.get.side_effect = lambda eid: self._states_store.get(eid)
        self.hass.states.async_all.side_effect = mock_all
        self.hass.services = MagicMock()
        self.hass.services.async_call = AsyncMock()
        self.hass.async_create_task = lambda coro: asyncio.create_task(coro)

        self.macro_manager = MacroManager(self.hass)
        self.vision_manager = VisionPresenceManager(self.hass, macro_manager=self.macro_manager)

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
            state_val = getattr(sensor_state, "state", None) or sensor_state.get("state")
            attrs = getattr(sensor_state, "attributes", None) or sensor_state.get("attributes", {})
            self.assertEqual(state_val, "movie_night")
            self.assertEqual(attrs["target_area"], "theater")
            self.assertIn(attrs["preconditioning_state"], ("armed", "in_progress"))
            self.assertEqual(attrs["lifestyle_macro"], "movie_night_mode")

    async def test_movie_night_soft_precooling_macro_execution(self) -> None:
        """Test that movie_night spatial migration intent pre-cools theater climate by -1°F."""
        self._states_store["climate.theater"] = MagicMock(
            entity_id="climate.theater",
            state="cool",
            attributes={"temperature": 70.0, "current_temperature": 71.0},
        )

        intent = {
            "intent": "movie_night",
            "target_area": "theater",
            "preconditioning_state": "armed",
            "lifestyle_macro": "movie_night_mode",
        }

        res = await self.macro_manager.async_process_spatial_migration(intent)
        self.assertIsNotNone(res)
        self.assertEqual(res["intent"], "movie_night")
        self.assertEqual(res["target_area"], "theater")
        self.assertEqual(res["status"], "in_progress")
        self.assertIn("-1°F", res["action_summary"])

        # Verify climate service was called with 69.0°F
        self.hass.services.async_call.assert_called()
        calls = [c for c in self.hass.services.async_call.call_args_list if (c.kwargs.get("domain") == "climate" and c.kwargs.get("service") == "set_temperature") or (len(c.args) >= 2 and c.args[0] == "climate" and c.args[1] == "set_temperature")]
        self.assertTrue(len(calls) > 0)
        data = calls[0].kwargs.get("service_data") if "service_data" in calls[0].kwargs else calls[0].args[2]
        self.assertEqual(data["temperature"], 69.0)

    async def test_sleep_bedtime_staged_dimming_and_white_noise(self) -> None:
        """Test that sleep_bedtime intent dims master lighting to 10% and arms white noise."""
        self._states_store["light.master_bedroom_overhead"] = MagicMock(
            entity_id="light.master_bedroom_overhead",
            state="on",
            attributes={"brightness": 255},
        )
        self._states_store["switch.master_white_noise"] = MagicMock(
            entity_id="switch.master_white_noise",
            state="off",
            attributes={},
        )

        intent = {
            "intent": "sleep_bedtime",
            "target_area": "master",
            "preconditioning_state": "armed",
            "lifestyle_macro": "bedtime_mode",
        }

        res = await self.macro_manager.async_process_spatial_migration(intent)
        self.assertIsNotNone(res)
        self.assertEqual(res["intent"], "sleep_bedtime")
        self.assertEqual(res["target_area"], "master")
        self.assertEqual(res["status"], "in_progress")

        # Verify light dimming step executed
        light_calls = [c for c in self.hass.services.async_call.call_args_list if (c.kwargs.get("domain") == "light" and c.kwargs.get("service") == "turn_on") or (len(c.args) >= 2 and c.args[0] == "light" and c.args[1] == "turn_on")]
        self.assertTrue(len(light_calls) > 0)
        ldata = light_calls[0].kwargs.get("service_data") if "service_data" in light_calls[0].kwargs else light_calls[0].args[2]
        self.assertEqual(ldata["brightness_pct"], 10)

    async def test_watchdog_auto_rollback_when_target_area_unoccupied(self) -> None:
        """Test that 10-minute watchdog rolls back macro if target area is not occupied."""
        self._states_store["climate.theater"] = MagicMock(
            entity_id="climate.theater",
            state="cool",
            attributes={"temperature": 71.0},
        )

        intent = {
            "intent": "movie_night",
            "target_area": "theater",
            "preconditioning_state": "armed",
        }

        res = await self.macro_manager.async_process_spatial_migration(intent)
        macro_id = res["macro_id"]

        # Run watchdog with 0-second timeout to trigger immediately
        self.macro_manager._start_watchdog(target_area="theater", macro_id=macro_id, timeout_seconds=0.001)
        import asyncio
        await asyncio.sleep(0.02)

        # Preconditioning must be rolled back
        active = self.macro_manager.get_active_preconditioning()
        self.assertEqual(active["status"], "rolled_back")

    async def test_arrival_confirmation_cancels_watchdog(self) -> None:
        """Test that occupant arrival in target area confirms pre-conditioning and cancels watchdog."""
        intent = {
            "intent": "movie_night",
            "target_area": "theater",
            "preconditioning_state": "armed",
        }
        await self.macro_manager.async_process_spatial_migration(intent)

        # Arrival in Theater confirmed
        confirmed = await self.macro_manager.async_process_spatial_migration(
            None, occupied_areas=["Theater"]
        )
        self.assertIsNotNone(confirmed)
        self.assertEqual(confirmed["status"], "confirmed")

    async def test_manual_cancel_preconditioning_rolls_back(self) -> None:
        """Test manual 1-click cancel via async_cancel_preconditioning."""
        self._states_store["climate.theater"] = MagicMock(
            entity_id="climate.theater",
            state="cool",
            attributes={"temperature": 72.0},
        )
        intent = {
            "intent": "movie_night",
            "target_area": "theater",
            "preconditioning_state": "armed",
        }
        await self.macro_manager.async_process_spatial_migration(intent)

        cancel_res = await self.macro_manager.async_cancel_preconditioning()
        self.assertTrue(cancel_res["success"])
        self.assertEqual(self.macro_manager._active_preconditioning["status"], "cancelled")

    def test_companion_card_preconditioning_chip_contract(self) -> None:
        """Verify that otis-companion-card.js contains preconditioning chip template and cancel handler."""
        import os
        card_path = os.path.join(
            os.path.dirname(__file__), "..", "custom_components", "otis_ai", "frontend", "otis-companion-card.js"
        )
        with open(card_path, "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("_renderPreconditioningChip", code)
        self.assertIn("preconditioning-banner", code)
        self.assertIn("btn-cancel-preconditioning", code)
        self.assertIn("cancel_preconditioning", code)

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
