"""Unit tests for Phase 4 Step 3 Multi-Zone Audio Migration & Seamless Hand-Off."""

from __future__ import annotations

from typing import Any
import unittest
from unittest.mock import AsyncMock, MagicMock

from custom_components.otis_ai.audio_manager import (
    AudioHandoffManager,
    filter_zones_by_area,
    normalize_area_slug,
    zone_matches_area,
)


class TestAudioMigration(unittest.IsolatedAsyncioTestCase):
    """Test multi-zone audio follow-me and spatial migration routing."""

    def setUp(self) -> None:
        """Set up mocked Home Assistant environment."""
        self.hass = MagicMock()
        self.hass.states = MagicMock()
        self.hass.services = MagicMock()
        self.hass.services.async_call = AsyncMock()
        self.hass.services.has_service = MagicMock(return_value=False)
        self._states: dict[str, Any] = {}

    def test_area_matching_utilities(self) -> None:
        """Test normalized area matching across entity ids, names, and area slugs."""
        self.assertEqual(normalize_area_slug("Living Room"), "living_room")
        self.assertEqual(normalize_area_slug("Master-Bedroom"), "master_bedroom")
        self.assertEqual(normalize_area_slug(""), "")

        zone = {
            "entity_id": "media_player.theater_receiver",
            "name": "Theater Receiver",
            "area_id": "theater_room",
        }
        self.assertTrue(zone_matches_area(zone, "theater_room"))
        self.assertTrue(zone_matches_area(zone, "theater"))
        self.assertFalse(zone_matches_area(zone, "kitchen"))

        zones = [
            zone,
            {"entity_id": "media_player.kitchen_speaker", "name": "Kitchen Speaker", "area_id": "kitchen"},
        ]
        matched = filter_zones_by_area(zones, "theater")
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["entity_id"], "media_player.theater_receiver")

    async def test_audio_migration_bypasses_when_no_active_media(self) -> None:
        """Verify that migration intent does not activate audio handoff if no source media is playing."""
        lr_state = MagicMock()
        lr_state.entity_id = "media_player.living_room_amp"
        lr_state.state = "off"
        lr_state.attributes = {"area_id": "living_room", "friendly_name": "Living Room Amp"}

        theater_state = MagicMock()
        theater_state.entity_id = "media_player.theater_receiver"
        theater_state.state = "off"
        theater_state.attributes = {"area_id": "theater", "friendly_name": "Theater Receiver"}

        self.hass.states.async_all.return_value = [lr_state, theater_state]

        am = AudioHandoffManager(self.hass)

        intent = {
            "intent": "movie_night",
            "source_area": "living_room",
            "target_area": "theater",
            "confidence": 0.85,
        }

        res = await am.async_process_spatial_audio_migration(intent)
        self.assertIsNotNone(res)
        self.assertFalse(res.get("migrated"))
        self.assertEqual(res.get("reason"), "no_active_audio")
        self.hass.services.async_call.assert_not_called()

    async def test_audio_migration_triggers_follow_me_when_playing(self) -> None:
        """Verify that migration intent activates follow-me audio handoff when source media is playing."""
        lr_state = MagicMock()
        lr_state.entity_id = "media_player.living_room_amp"
        lr_state.state = "playing"
        lr_state.attributes = {
            "area_id": "living_room",
            "friendly_name": "Living Room Amp",
            "source": "Spotify",
            "volume_level": 0.60,
        }

        theater_state = MagicMock()
        theater_state.entity_id = "media_player.theater_receiver"
        theater_state.state = "off"
        theater_state.attributes = {
            "area_id": "theater",
            "friendly_name": "Theater Receiver",
        }

        mig_sensor_state = MagicMock()
        mig_sensor_state.state = "movie_night"
        mig_sensor_state.attributes = {}

        def get_state(eid):
            if eid == "sensor.otis_spatial_migration":
                return mig_sensor_state
            return None

        self.hass.states.get.side_effect = get_state
        self.hass.states.async_all.return_value = [lr_state, theater_state]

        am = AudioHandoffManager(self.hass)

        intent = {
            "intent": "movie_night",
            "source_area": "living_room",
            "target_area": "theater",
            "confidence": 0.85,
        }

        res = await am.async_process_spatial_audio_migration(intent)
        self.assertIsNotNone(res)
        self.assertTrue(res.get("success"))
        self.assertTrue(res.get("migrated"))
        self.assertEqual(res.get("target_player"), "media_player.theater_receiver")
        self.assertEqual(res.get("status"), "following")

        calls = self.hass.services.async_call.call_args_list
        domains = [c[0][0] for c in calls]
        services = [c[0][1] for c in calls]
        self.assertIn("media_player", domains)
        self.assertIn("turn_on", services)

    async def test_audio_migration_respects_quiet_hours(self) -> None:
        """Verify that audio follow-me caps target zone volume to quiet hours threshold when active."""
        lr_state = MagicMock()
        lr_state.entity_id = "media_player.living_room_amp"
        lr_state.state = "playing"
        lr_state.attributes = {
            "area_id": "living_room",
            "friendly_name": "Living Room Amp",
            "source": "Tidal",
            "volume_level": 0.80,
        }

        bed_state = MagicMock()
        bed_state.entity_id = "media_player.master_bedroom_speaker"
        bed_state.state = "off"
        bed_state.attributes = {
            "area_id": "master_bedroom",
            "friendly_name": "Master Bedroom Speaker",
        }

        self.hass.states.async_all.return_value = [lr_state, bed_state]
        self.hass.states.get.return_value = None

        mock_rules = MagicMock()
        mock_rules.get_rules.return_value = {
            "quiet_hours_enabled": True,
            "quiet_hours_start": "00:00",
            "quiet_hours_end": "23:59",
            "quiet_hours_volume": 20,
            "audio_follow_enabled": True,
        }

        am = AudioHandoffManager(self.hass, rules_manager=mock_rules)

        intent = {
            "intent": "sleep_bedtime",
            "source_area": "living_room",
            "target_area": "master_bedroom",
            "confidence": 0.90,
        }

        res = await am.async_process_spatial_audio_migration(intent)
        self.assertIsNotNone(res)
        self.assertTrue(res.get("success"))
        self.assertTrue(res.get("quiet_hours_applied"))

        calls = self.hass.services.async_call.call_args_list
        vol_calls = [c for c in calls if c[0][1] == "volume_set"]
        self.assertGreater(len(vol_calls), 0)
        vol_payload = vol_calls[0][0][2]
        self.assertLessEqual(vol_payload["volume_level"], 0.20)

    async def test_audio_migration_finalizes_on_target_arrival(self) -> None:
        """Verify that confirming arrival in the target area powers off the departed source player."""
        am = AudioHandoffManager(self.hass)
        am._active_audio_migration = {
            "source_player": "media_player.living_room_amp",
            "target_player": "media_player.theater_receiver",
            "source_area": "living_room",
            "target_area": "theater",
            "status": "following",
        }

        res = await am.async_finalize_audio_handoff()
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("status"), "completed")

        calls = self.hass.services.async_call.call_args_list
        off_calls = [c for c in calls if c[0][1] == "turn_off"]
        self.assertGreater(len(off_calls), 0)
        self.assertEqual(off_calls[0][0][2]["entity_id"], "media_player.living_room_amp")

    async def test_audio_migration_cancels_on_abort(self) -> None:
        """Verify that cancelling migration turns off target player."""
        am = AudioHandoffManager(self.hass)
        am._active_audio_migration = {
            "source_player": "media_player.living_room_amp",
            "target_player": "media_player.theater_receiver",
            "source_area": "living_room",
            "target_area": "theater",
            "status": "following",
        }

        res = await am.async_cancel_audio_migration()
        self.assertTrue(res.get("cancelled"))

        calls = self.hass.services.async_call.call_args_list
        off_calls = [c for c in calls if c[0][1] == "turn_off"]
        self.assertGreater(len(off_calls), 0)
        self.assertEqual(off_calls[0][0][2]["entity_id"], "media_player.theater_receiver")

    async def test_audio_follow_study_to_great_room_with_occupied_areas_and_party_suppressant(self) -> None:
        """Verify audio follows from Study to Great Room even when target is in occupied_areas, and suppresses on Party Mode."""
        from custom_components.otis_ai.rules_manager import BehavioralRulesManager

        rm = BehavioralRulesManager(self.hass)
        rm._loaded = True
        rm._rules["audio_follow_enabled"] = True
        rm._rules["party_mode_enabled"] = False
        rm._rules["quiet_hours_enabled"] = False

        am = AudioHandoffManager(self.hass, rules_manager=rm)
        am.async_get_active_media_zones = unittest.mock.AsyncMock(return_value={
            "matrix_zones": [
                {
                    "entity_id": "media_player.matrix_amp_1_study",
                    "name": "Matrix Amp 1 Study",
                    "area_id": None,
                    "state": "on",
                    "source": "Server",
                    "volume_level": 0.45,
                },
                {
                    "entity_id": "media_player.matrix_amp_1_great_room",
                    "name": "Matrix Amp 1 Great Room",
                    "area_id": None,
                    "state": "on",
                    "source": "Home Assistant",
                    "volume_level": 0.25,
                },
            ],
            "other_players": [],
            "tv_cinema_players": [],
        })

        res = await am.async_process_spatial_audio_migration(
            {"source_area": "study", "target_area": "great_room", "confidence": 0.90},
            occupied_areas=["great_room", "study"],
        )
        self.assertIsNotNone(res)
        self.assertTrue(res.get("migrated"))
        self.assertEqual(res.get("source_area"), "study")
        self.assertEqual(res.get("target_area"), "great_room")

        # Verify Party Mode suppresses Audio Follow
        rm._rules["party_mode_enabled"] = True
        suppressed = await am.async_process_spatial_audio_migration(
            {"source_area": "study", "target_area": "great_room", "confidence": 0.90},
            occupied_areas=["great_room"],
        )
        self.assertIsNone(suppressed)

    async def test_audio_follow_excludes_tv_cinema_players(self) -> None:
        """Verify Audio Follow-Me and async_audio_handoff never target tv_cinema_players like Shield TV."""
        from custom_components.otis_ai.audio_manager import AudioHandoffManager

        am = AudioHandoffManager(self.hass)
        am.async_get_active_media_zones = unittest.mock.AsyncMock(return_value={
            "matrix_zones": [
                {
                    "entity_id": "media_player.matrix_amp_1_study",
                    "area_id": "study",
                    "state": "playing",
                    "source": "Music Assistant",
                    "volume_level": 0.35,
                    "platform": "control4_mediaplayer",
                },
            ],
            "other_players": [],
            "tv_cinema_players": [
                {
                    "entity_id": "media_player.shield_android_tv",
                    "area_id": "theater",
                    "state": "off",
                    "source": None,
                    "volume_level": 0.25,
                    "platform": "androidtv_remote",
                },
            ],
        })

        res = await am.async_process_spatial_audio_migration(
            {"source_area": "study", "target_area": "theater", "confidence": 0.90},
            occupied_areas=["theater"],
        )
        self.assertIsNotNone(res)
        self.assertFalse(res.get("migrated"))
        self.assertEqual(res.get("reason"), "no_target_player")

        handoff_res = await am.async_audio_handoff(
            source_area="study",
            target_area="theater",
            mode="follow",
        )
        self.assertFalse(handoff_res.get("success"))
        self.hass.services.async_call.assert_not_called()

    async def test_agent_classification_and_self_learning_upgrade(self) -> None:
        """Verify Paid vs Free tier scoring, YAML syntax upgrade, and autonomous rule learning."""
        from custom_components.otis_ai import (
            classify_and_score_agent,
            validate_and_upgrade_assistant_response,
        )
        from custom_components.otis_ai.rules_manager import BehavioralRulesManager

        # Paid vs Free Restricted scoring
        paid_info = classify_and_score_agent(None, "anthropic_claude", {})
        free_groq_info = classify_and_score_agent(None, "groq_free_models", {})
        self.assertEqual(paid_info["tier"], "paid")
        self.assertEqual(free_groq_info["tier"], "free_restricted")
        self.assertGreater(paid_info["score"], free_groq_info["score"])

        # Deprecated YAML auto-upgrade
        legacy_resp = (
            "Here is your automation:\n```yaml\nalias: Test Light\ntrigger:\n"
            "  - platform: state\n    entity_id: binary_sensor.study_motion\n"
            "action:\n  - service: light.turn_on\n    target:\n      entity_id: light.study\n```"
        )
        upgraded, notes, penalty = validate_and_upgrade_assistant_response(None, legacy_resp)
        self.assertIn("triggers:", upgraded)
        self.assertIn("- trigger: state", upgraded)
        self.assertIn("actions:", upgraded)
        self.assertIn("- action: light.turn_on", upgraded)
        self.assertGreaterEqual(penalty, 2)
        self.assertGreaterEqual(len(notes), 2)

        # Autonomous user teaching learning
        rm = BehavioralRulesManager(self.hass)
        rm._loaded = True
        rm._store.async_save = unittest.mock.AsyncMock()
        learned = await rm.async_learn_from_interaction(
            "Remember that the Great Room chandelier should never be turned on after 10pm",
            upgraded,
            correction_notes=notes,
        )
        self.assertTrue(any("Great Room chandelier" in item for item in learned))
        self.assertIn("Great Room chandelier", rm.get_rules()["custom_instructions"])


if __name__ == "__main__":
    unittest.main()
