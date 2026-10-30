"""Unit tests for Otis AI Companion Phase 9: Self-Supervised Habit Learning & Behavioral Modeling."""

import asyncio
from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, MagicMock

from custom_components.otis_ai.habit_manager import BehavioralHabitManager


class MockEntityState:
    def __init__(self, entity_id: str, state: str = "off", attributes: dict | None = None):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}


class TestBehavioralHabitManager(unittest.TestCase):
    """Test suite for BehavioralHabitManager."""

    def setUp(self):
        self.hass = MagicMock()
        self.hass.states = MagicMock()
        self.hass.services = MagicMock()
        self.hass.services.async_call = AsyncMock()

    def test_cluster_temporal_sequences_morning_wakeup(self):
        """Test clustering recurrent morning wakeup habit patterns."""
        mgr = BehavioralHabitManager(self.hass)

        # 4 consecutive days of bed occupancy off -> master bath light on at 7:30 AM
        rows = []
        base_ts = datetime(2026, 10, 20, 7, 30, tzinfo=timezone.utc).timestamp()
        for day in range(4):
            day_ts = base_ts + (day * 86400)
            rows.append(("binary_sensor.master_bed_occupancy", "off", day_ts))
            rows.append(("light.master_bath_vanity", "on", day_ts + 45))
            rows.append(("switch.kitchen_espresso_machine", "on", day_ts + 120))

        routines = mgr.cluster_temporal_sequences(rows, window_seconds=180.0, min_occurrences=3)
        self.assertGreaterEqual(len(routines), 1)

        wakeup_routine = next((r for r in routines if "Wakeup" in r["title"] or "Morning" in r["title"]), None)
        self.assertIsNotNone(wakeup_routine)
        self.assertEqual(wakeup_routine["trigger_entity"], "binary_sensor.master_bed_occupancy")
        self.assertEqual(wakeup_routine["trigger_state"], "off")
        self.assertGreaterEqual(wakeup_routine["confidence"], 0.70)
        self.assertEqual(wakeup_routine["occurrences"], 4)

        # Verify action payload structure
        action_payload = wakeup_routine["action_payload"]
        self.assertEqual(action_payload["trigger"][0]["entity_id"], "binary_sensor.master_bed_occupancy")
        self.assertEqual(action_payload["trigger"][0]["to"], "off")
        self.assertEqual(len(action_payload["action"]), 2)

    def test_detect_habit_deviations_missed_bedtime(self):
        """Test deviation detection when exterior locks remain unsecured late at night."""
        states = [
            MockEntityState("lock.front_door", "unlocked", {"friendly_name": "Front Door Lock"}),
            MockEntityState("light.living_room_ceiling", "on", {"friendly_name": "Living Room Ceiling"}),
            MockEntityState("light.foyer_chandelier", "on", {"friendly_name": "Foyer Chandelier"}),
        ]
        self.hass.states.async_all.return_value = states

        mgr = BehavioralHabitManager(self.hass)

        # Mock current time at 23:45 (11:45 PM)
        with unittest.mock.patch("custom_components.otis_ai.habit_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 10, 30, 23, 45)
            mock_dt.strftime = datetime.strftime
            deviations = asyncio.run(mgr.async_detect_habit_deviations())

        self.assertGreaterEqual(len(deviations), 1)
        bedtime_dev = next((d for d in deviations if "missed_bedtime" in d["id"]), None)
        self.assertIsNotNone(bedtime_dev)
        self.assertEqual(bedtime_dev["priority"], "high")
        self.assertIn("Bedtime Routine Deviation", bedtime_dev["title"])
        self.assertEqual(bedtime_dev["action_payload"]["service"], "lock.lock")

    def test_detect_habit_deviations_morning_shades(self):
        """Test daylight deviation suggestion to open closed shades in the morning."""
        states = [
            MockEntityState("cover.master_shades", "closed", {"device_class": "shade", "friendly_name": "Master Shades"}),
        ]
        self.hass.states.async_all.return_value = states

        mgr = BehavioralHabitManager(self.hass)

        # Mock current time at 9:15 AM
        with unittest.mock.patch("custom_components.otis_ai.habit_manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 10, 30, 9, 15)
            mock_dt.strftime = datetime.strftime
            deviations = asyncio.run(mgr.async_detect_habit_deviations())

        self.assertGreaterEqual(len(deviations), 1)
        morning_dev = next((d for d in deviations if "morning_shades" in d["id"]), None)
        self.assertIsNotNone(morning_dev)
        self.assertEqual(morning_dev["priority"], "medium")
        self.assertIn("Morning Routine", morning_dev["title"])
        self.assertEqual(morning_dev["action_payload"]["service"], "cover.open_cover")

    def test_calculate_circadian_and_seasonal_curves(self):
        """Test dynamic circadian Kelvin color temperature and seasonal HVAC setpoint curves."""
        mgr = BehavioralHabitManager(self.hass)

        # 1. Midnight / Deep night profile
        night_dt = datetime(2026, 1, 15, 1, 30)  # Winter night
        night_curve = mgr.calculate_circadian_curves(solar_elevation=-35.0, now_dt=night_dt)
        self.assertEqual(night_curve["season"], "Winter")
        self.assertEqual(night_curve["lighting_curve"]["color_temp_kelvin"], 2200)
        self.assertEqual(night_curve["lighting_curve"]["mode"], "night_sleep")
        self.assertEqual(night_curve["climate_curve"]["target_temp_heat_f"], 69.0)

        # 2. Midday bright sun profile
        summer_dt = datetime(2026, 7, 15, 13, 0)  # Summer midday
        midday_curve = mgr.calculate_circadian_curves(solar_elevation=55.0, now_dt=summer_dt)
        self.assertEqual(midday_curve["season"], "Summer")
        self.assertEqual(midday_curve["lighting_curve"]["color_temp_kelvin"], 5500)
        self.assertEqual(midday_curve["lighting_curve"]["mode"], "midday_focus")
        self.assertEqual(midday_curve["climate_curve"]["target_temp_cool_f"], 73.0)

    def test_conversational_habit_and_circadian_queries(self):
        """Test conversational agent handling of habit routines and circadian curves."""
        from custom_components.otis_ai import OtisAIConversationAgent

        entry = MagicMock()
        entry.options = {}
        entry.data = {}

        engine = MagicMock()
        automation_manager = MagicMock()
        mgr = BehavioralHabitManager(self.hass)

        agent = OtisAIConversationAgent(
            self.hass,
            entry,
            engine,
            automation_manager,
            habit_manager=mgr,
        )

        user_input = MagicMock()
        user_input.text = "Show circadian curves"
        user_input.conversation_id = "test_conv"
        user_input.create_response = MagicMock(return_value="circadian_response_mock")

        res = asyncio.run(agent.async_process(user_input))
        self.assertIsNotNone(res)
        user_input.create_response.assert_called_once()
        speech = user_input.create_response.call_args[1]["speech"]
        self.assertIn("Circadian Phase", speech)
        self.assertIn("Seasonal Comfort Setpoints", speech)
