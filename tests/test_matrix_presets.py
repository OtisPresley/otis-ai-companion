"""Unit tests for Multi-Zone Audio Matrix Presets and Modular Hardware Agnostic Discovery."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.otis_ai.matrix_presets import (
    MATRIX_PRESETS,
    get_matrix_presets_list,
    identify_matrix_preset,
    is_matrix_entity,
    is_tv_cinema_player,
)
from custom_components.otis_ai.audio_manager import AudioHandoffManager


class TestMatrixPresetsArchitecture:
    """Test suite verifying vendor-agnostic matrix presets and audio routing."""

    def test_presets_registry_integrity(self):
        """Verify all first-class matrix amplifier presets are properly registered."""
        expected_presets = {
            "universal",
            "control4",
            "russound",
            "monoprice",
            "snapone_episode",
            "htd",
            "audiocontrol",
        }
        presets = MATRIX_PRESETS
        for key in expected_presets:
            assert key in presets, f"Missing expected matrix preset: {key}"
            p = presets[key]
            assert "name" in p
            assert "vendor" in p
            assert "platforms" in p
            assert "entity_patterns" in p
            assert "default_sources" in p
            assert len(p["default_sources"]) >= 3

        presets_list = get_matrix_presets_list()
        assert len(presets_list) >= 7

    def test_identify_matrix_preset_russound(self):
        """Test identification of Russound multi-zone hardware."""
        active_integrations = [{"domain": "russound_rio"}, {"domain": "weather"}]
        media_players = [
            {"entity_id": "media_player.living_room_zone", "platform": "russound_rio"},
            {"entity_id": "media_player.kitchen_zone", "platform": "russound_rio"},
        ]
        preset = identify_matrix_preset(active_integrations, media_players)
        assert preset["id"] == "russound"
        assert "Russound" in preset["name"]

    def test_identify_matrix_preset_monoprice(self):
        """Test identification of Monoprice 6-Zone / Dayton Audio hardware."""
        active_integrations = [{"domain": "monoprice"}]
        media_players = [
            {"entity_id": "media_player.zone_1", "platform": "monoprice"},
            {"entity_id": "media_player.zone_2", "platform": "monoprice"},
        ]
        preset = identify_matrix_preset(active_integrations, media_players)
        assert preset["id"] == "monoprice"
        assert "Monoprice" in preset["name"]

    def test_identify_matrix_preset_snapone_episode(self):
        """Test identification of Snap One / Episode Response DSP matrix."""
        active_integrations = [{"domain": "episode"}]
        media_players = [
            {"entity_id": "media_player.patio_episode", "platform": "episode"},
            {"entity_id": "media_player.dining_episode", "platform": "episode"},
        ]
        preset = identify_matrix_preset(active_integrations, media_players)
        assert preset["id"] == "snapone_episode"
        assert "Episode" in preset["name"]

    def test_identify_matrix_preset_htd(self):
        """Test identification of HTD Lync / MC-66 matrix."""
        active_integrations = [{"domain": "htd_lync"}]
        preset = identify_matrix_preset(active_integrations)
        assert preset["id"] == "htd"
        assert "HTD" in preset["name"]

    def test_identify_matrix_preset_audiocontrol(self):
        """Test identification of AudioControl Director DSP matrix."""
        active_integrations = [{"domain": "audiocontrol"}]
        preset = identify_matrix_preset(active_integrations)
        assert preset["id"] == "audiocontrol"
        assert "AudioControl" in preset["name"]

    def test_identify_matrix_preset_universal_fallback(self):
        """Test fallback to Universal Multi-Zone Matrix when custom/generic matrix is used."""
        active_integrations = [{"domain": "homeassistant"}]
        media_players = [
            {"entity_id": "media_player.custom_speaker_1"},
            {"entity_id": "media_player.custom_speaker_2"},
        ]
        preset = identify_matrix_preset(active_integrations, media_players)
        assert preset["id"] == "universal"

    def test_is_matrix_entity_heuristic(self):
        """Verify matrix entity matching across diverse vendor patterns."""
        assert is_matrix_entity("media_player.russound_zone_1") is True
        assert is_matrix_entity("media_player.monoprice_zone_4") is True
        assert is_matrix_entity("media_player.episode_patio") is True
        assert is_matrix_entity("media_player.htd_lync_zone_2") is True
        assert is_matrix_entity("media_player.c4_amp_study") is True
        assert is_matrix_entity("media_player.matrix_amp_1_deck") is True
        assert is_matrix_entity("media_player.audio_matrix_master") is True
        assert is_matrix_entity("media_player.living_room_tv") is False
        assert is_matrix_entity("media_player.echo_dot") is False

    def test_is_tv_cinema_player_agnostic(self):
        """Verify TV / Cinema / AVR player classification without vendor bias."""
        assert is_tv_cinema_player("media_player.theater_avr") is True
        assert is_tv_cinema_player("media_player.living_room_tv") is True
        assert is_tv_cinema_player("media_player.basement_projector") is True
        assert is_tv_cinema_player("media_player.patio_soundbar") is True
        assert is_tv_cinema_player("media_player.bravia_4k") is True
        assert is_tv_cinema_player("media_player.shield_tv") is True
        assert is_tv_cinema_player("media_player.denon_receiver", {"device_class": "receiver"}) is True
        assert is_tv_cinema_player("media_player.generic_tv", {"device_class": "tv"}) is True
        assert is_tv_cinema_player("media_player.kitchen_matrix_speaker") is False

    def test_audio_handoff_with_russound_matrix(self):
        """Verify audio follow-me handoff works seamlessly on Russound hardware."""
        class MockState:
            def __init__(self, entity_id, state="on", attributes=None):
                self.entity_id = entity_id
                self.state = state
                self.attributes = attributes or {}

        hass = MagicMock()
        states = [
            MockState("media_player.russound_great_room", "playing", {"friendly_name": "Great Room", "source": "Source 1", "volume_level": 0.3}),
            MockState("media_player.russound_patio", "off", {"friendly_name": "Patio", "source": "Source 2", "volume_level": 0.2}),
        ]
        hass.states.async_all = MagicMock(return_value=states)
        hass.services.has_service = MagicMock(return_value=True)
        hass.services.async_call = AsyncMock()

        mgr = AudioHandoffManager(hass)
        res = asyncio.run(mgr.async_audio_handoff(
            source_area="great_room",
            target_area="patio",
            mode="handoff",
            idle_power_guard=False,
        ))

        assert res["success"] is True
        assert res["source_player"] == "media_player.russound_great_room"
        assert res["target_player"] == "media_player.russound_patio"

        calls = [(c[0][0], c[0][1], c[0][2].get("entity_id")) for c in hass.services.async_call.call_args_list]
        assert ("media_player", "turn_on", "media_player.russound_patio") in calls
        assert ("media_player", "select_source", "media_player.russound_patio") in calls
        assert ("media_player", "turn_off", "media_player.russound_great_room") in calls

    def test_audio_handoff_with_monoprice_matrix(self):
        """Verify audio follow-me handoff works seamlessly on Monoprice 6-zone hardware."""
        class MockState:
            def __init__(self, entity_id, state="on", attributes=None):
                self.entity_id = entity_id
                self.state = state
                self.attributes = attributes or {}

        hass = MagicMock()
        states = [
            MockState("media_player.monoprice_zone_1", "playing", {"friendly_name": "Dining Room", "source": "Source 3", "volume_level": 0.4}),
            MockState("media_player.monoprice_zone_2", "off", {"friendly_name": "Master Bed", "source": "Source 1", "volume_level": 0.15}),
        ]
        hass.states.async_all = MagicMock(return_value=states)
        hass.services.has_service = MagicMock(return_value=True)
        hass.services.async_call = AsyncMock()

        mgr = AudioHandoffManager(hass)
        res = asyncio.run(mgr.async_audio_handoff(
            source_area="dining_room",
            target_area="master_bed",
            mode="follow",
            idle_power_guard=False,
        ))

        assert res["success"] is True
        assert res["source_player"] == "media_player.monoprice_zone_1"
        assert res["target_player"] == "media_player.monoprice_zone_2"

        calls = [(c[0][0], c[0][1], c[0][2].get("entity_id")) for c in hass.services.async_call.call_args_list]
        assert ("media_player", "turn_on", "media_player.monoprice_zone_2") in calls
        assert ("media_player", "select_source", "media_player.monoprice_zone_2") in calls
        # Follow mode does NOT turn off source zone
        assert ("media_player", "turn_off", "media_player.monoprice_zone_1") not in calls

    def test_discovery_engine_russound_matrix_topology(self):
        """Verify DiscoveryEngine identifies Russound MCA matrix and attributes."""
        from custom_components.otis_ai import DiscoveryEngine

        hass = MagicMock()
        engine = DiscoveryEngine(hass)

        areas = {
            "patio": {"name": "Patio"},
            "kitchen": {"name": "Kitchen"},
            "living_room": {"name": "Living Room"},
        }
        entities = [
            {"entity_id": "media_player.russound_patio", "name": "Patio Audio", "domain": "media_player", "area_id": "patio", "platform": "russound_rio"},
            {"entity_id": "media_player.russound_kitchen", "name": "Kitchen Audio", "domain": "media_player", "area_id": "kitchen", "platform": "russound_rio"},
            {"entity_id": "media_player.russound_living_room", "name": "Living Room Audio", "domain": "media_player", "area_id": "living_room", "platform": "russound_rio"},
            {"entity_id": "media_player.bridge_streamer", "name": "Bridge Streamer", "domain": "media_player", "platform": "mass"},
            {"entity_id": "media_player.living_room_tv", "name": "Living Room TV", "domain": "media_player", "area_id": "living_room", "attributes": {"device_class": "tv"}},
        ]
        integrations = [{"domain": "russound_rio"}, {"domain": "mass"}]

        media_topo = engine._discover_media_topology(areas, entities, integrations)
        assert media_topo["matrix_amp_detected"] is True
        assert media_topo["matrix_platform"] == "russound"
        assert "Russound" in media_topo["matrix_preset_name"]
        assert len(media_topo["matrix_zones"]) == 3
        assert len(media_topo["input_streamers"]) == 1
        assert len(media_topo["tv_cinema_zones"]) == 1
        assert media_topo["ready_for_unified_coordinator"] is True

    def test_discovery_engine_monoprice_matrix_topology(self):
        """Verify DiscoveryEngine identifies Monoprice 6-Zone matrix and attributes."""
        from custom_components.otis_ai import DiscoveryEngine

        hass = MagicMock()
        engine = DiscoveryEngine(hass)

        areas = {
            "deck": {"name": "Deck"},
            "gym": {"name": "Gym"},
            "study": {"name": "Study"},
        }
        entities = [
            {"entity_id": "media_player.monoprice_zone_1", "name": "Deck Speakers", "domain": "media_player", "area_id": "deck", "platform": "monoprice"},
            {"entity_id": "media_player.monoprice_zone_2", "name": "Gym Speakers", "domain": "media_player", "area_id": "gym", "platform": "monoprice"},
            {"entity_id": "media_player.monoprice_zone_3", "name": "Study Speakers", "domain": "media_player", "area_id": "study", "platform": "monoprice"},
        ]
        integrations = [{"domain": "monoprice"}]

        media_topo = engine._discover_media_topology(areas, entities, integrations)
        assert media_topo["matrix_amp_detected"] is True
        assert media_topo["matrix_platform"] == "monoprice"
        assert "Monoprice" in media_topo["matrix_preset_name"]
        assert len(media_topo["matrix_zones"]) == 3
        assert media_topo["ready_for_unified_coordinator"] is True
