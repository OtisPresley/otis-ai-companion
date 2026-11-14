"""Tests for Media default/return input, input-stop listener, Audio Follow-Me _2 resolution, and dynamic Studio naming."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.otis_ai.audio_manager import AudioHandoffManager
from custom_components.otis_ai.const import is_otis_entity_id, resolve_otis_entity_id
from custom_components.otis_ai.dashboard_manager import DashboardManager


def _make_state(entity_id: str, state: str, attrs: dict | None = None):
    return SimpleNamespace(entity_id=entity_id, state=state, attributes=attrs or {})


def _make_hass(states_list: list[SimpleNamespace]):
    states_map = {s.entity_id: s for s in states_list}
    hass = MagicMock()
    hass.data = {}
    hass.states = MagicMock()
    hass.states.get = MagicMock(side_effect=lambda eid: states_map.get(eid))
    hass.states.async_all = MagicMock(
        side_effect=lambda domain=None: [
            s for s in states_list if not domain or s.entity_id.startswith(f"{domain}.")
        ]
    )
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    listeners: dict[str, list] = {}

    def _listen(event_type, cb):
        listeners.setdefault(event_type, []).append(cb)
        return lambda: None

    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock(side_effect=_listen)
    hass._listeners = listeners
    return hass


@pytest.mark.asyncio
async def test_unjoin_zones_routes_to_configured_default_input():
    """Unjoining zones selects the configured default return input when present."""
    hass = _make_hass([
        _make_state(
            "media_player.matrix_amp_kitchen",
            "on",
            {"source": "Spotify", "source_list": ["Spotify", "Bridge", "None"]},
        ),
    ])
    rules_mgr = MagicMock()
    rules_mgr.get_rules = MagicMock(return_value={"media_unjoin_input": "Bridge"})
    mgr = AudioHandoffManager(hass, rules_manager=rules_mgr)

    res = await mgr.async_unjoin_zones(["media_player.matrix_amp_kitchen"])
    assert res["success"] is True
    assert res["default_input"] == "Bridge"
    assert res["reverted"] == ["media_player.matrix_amp_kitchen"]
    hass.services.async_call.assert_awaited_once_with(
        "media_player",
        "select_source",
        {"entity_id": "media_player.matrix_amp_kitchen", "source": "Bridge"},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_unjoin_zones_turns_off_when_none_not_in_source_list():
    """Unjoining zones turns off the zone when default input is None and not in source_list."""
    hass = _make_hass([
        _make_state(
            "media_player.matrix_amp_patio",
            "on",
            {"source": "Spotify", "source_list": ["Spotify", "AirPlay"]},
        ),
    ])
    rules_mgr = MagicMock()
    rules_mgr.get_rules = MagicMock(return_value={"media_unjoin_input": "None"})
    mgr = AudioHandoffManager(hass, rules_manager=rules_mgr)

    res = await mgr.async_unjoin_zones(["media_player.matrix_amp_patio"])
    assert res["success"] is True
    assert res["turned_off"] == ["media_player.matrix_amp_patio"]
    hass.services.async_call.assert_awaited_once_with(
        "media_player",
        "turn_off",
        {"entity_id": "media_player.matrix_amp_patio"},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_input_stop_listener_reverts_zones_on_idle_not_pause():
    """When a mapped input player stops playing (idle/off), routed zones return to default input."""
    hass = _make_hass([
        _make_state("media_player.spotify_bridge", "idle", {"friendly_name": "Spotify Bridge"}),
        _make_state(
            "media_player.matrix_amp_1_kitchen",
            "on",
            {
                "friendly_name": "Matrix Amp 1 Kitchen",
                "source": "Spotify",
                "source_list": ["Spotify", "Home Assistant", "None"],
            },
        ),
    ])
    rules_mgr = MagicMock()
    rules_mgr.get_rules = MagicMock(
        return_value={
            "media_input_mappings": {"Spotify": "media_player.spotify_bridge"},
            "media_unjoin_input": "Home Assistant",
        }
    )
    mgr = AudioHandoffManager(hass, rules_manager=rules_mgr)
    mgr.async_start_input_stop_listener()
    assert hass.bus.async_listen.called
    cb = hass.bus.async_listen.call_args[0][1]

    # Pause should NOT revert zones
    await cb(SimpleNamespace(data={
        "entity_id": "media_player.spotify_bridge",
        "old_state": _make_state("media_player.spotify_bridge", "playing"),
        "new_state": _make_state("media_player.spotify_bridge", "paused"),
    }))
    hass.services.async_call.assert_not_called()

    # Transition from playing -> idle SHOULD revert zones to Home Assistant
    await cb(SimpleNamespace(data={
        "entity_id": "media_player.spotify_bridge",
        "old_state": _make_state("media_player.spotify_bridge", "playing"),
        "new_state": _make_state("media_player.spotify_bridge", "idle"),
    }))
    hass.services.async_call.assert_awaited_once_with(
        "media_player",
        "select_source",
        {"entity_id": "media_player.matrix_amp_1_kitchen", "source": "Home Assistant"},
        blocking=True,
    )


def test_resolve_otis_entity_id_handles_suffixed_entities():
    """resolve_otis_entity_id finds _2 suffixed entities when canonical ID is absent."""
    hass = _make_hass([
        _make_state("sensor.otis_spatial_migration_2", "idle"),
        _make_state("switch.otis_audio_follow_2", "on"),
    ])
    assert is_otis_entity_id("sensor.otis_spatial_migration_2", "sensor", "spatial_migration") is True
    assert is_otis_entity_id("sensor.otis_other", "sensor", "spatial_migration") is False
    assert resolve_otis_entity_id(hass, "sensor", "spatial_migration") == "sensor.otis_spatial_migration_2"
    assert resolve_otis_entity_id(hass, "switch", "audio_follow") == "switch.otis_audio_follow_2"


def test_dynamic_studio_naming_and_visibility():
    """Studios omit missing domains and name Climate without Pool when no pool entities exist."""
    hass = _make_hass([])
    dm = DashboardManager(hass)

    # No media, no pool, has climate + security + energy
    cap_no_media_no_pool = {
        "entities": [
            {"entity_id": "climate.downstairs", "domain": "climate", "state": "heat"},
            {"entity_id": "lock.front_door", "domain": "lock", "state": "locked"},
            {"entity_id": "sensor.grid_power", "domain": "sensor", "state": "450", "attributes": {"unit_of_measurement": "W"}},
        ],
        "media_topology": {},
        "security_topology": {"locks": ["lock.front_door"]},
        "energy_topology": {"total_power_w": 450},
    }
    studios = dm._get_active_studios(cap_no_media_no_pool)
    names = [s["name"] for s in studios]
    assert "Media Studio" not in names
    assert "Climate" in names
    assert "Climate & Pool" not in names
    assert "Security Center" in names
    assert "Energy Studio" in names

    # With pool entity -> Climate & Pool
    cap_with_pool = {
        "entities": [
            {"entity_id": "climate.downstairs", "domain": "climate", "state": "heat"},
            {"entity_id": "sensor.pentair_pool_temp", "domain": "sensor", "state": "82"},
        ],
        "media_topology": {},
        "security_topology": {},
        "energy_topology": {},
    }
    studios_pool = dm._get_active_studios(cap_with_pool)
    assert [s["name"] for s in studios_pool] == ["Floor Plan", "Climate & Pool"]


def test_all_studio_views_start_with_studio_navigation_card():
    """Media, Energy, Security, and Climate views all place Studio Navigation first for consistent sections."""
    hass = _make_hass([])
    dm = DashboardManager(hass)
    cap = {
        "entities": [
            {"entity_id": "climate.main", "domain": "climate", "state": "cool"},
            {"entity_id": "lock.front", "domain": "lock", "state": "locked"},
            {"entity_id": "media_player.kitchen", "domain": "media_player", "state": "idle"},
            {"entity_id": "sensor.home_power", "domain": "sensor", "state": "200", "attributes": {"unit_of_measurement": "W"}},
        ],
        "media_topology": {"matrix_zones": ["media_player.kitchen"]},
        "security_topology": {"locks": ["lock.front"]},
        "energy_topology": {"total_power_w": 200},
    }
    for cards in (
        dm._build_media_view_cards(cap),
        dm._build_energy_view_cards(cap),
        dm._build_security_view_cards(cap),
        dm._build_climate_view_cards(cap),
    ):
        assert cards[0]["type"] == "grid"
        assert cards[0]["title"] == "Studio Navigation"
        assert cards[1]["type"] == "markdown"


@pytest.mark.asyncio
async def test_apply_default_input_to_idle_zones_skips_playing_zones():
    """Setting Default/Return Input routes idle zones to it while leaving playing zones untouched."""
    hass = _make_hass([
        _make_state("media_player.bridge", "playing", {"friendly_name": "Bridge"}),
        _make_state("media_player.vlc_telnet", "idle", {"friendly_name": "VLC"}),
        _make_state(
            "media_player.matrix_amp_1_kitchen",
            "on",
            {"friendly_name": "Kitchen", "source": "Bridge", "source_list": ["Bridge", "Home Assistant", "Server"]},
        ),
        _make_state(
            "media_player.matrix_amp_1_study",
            "off",
            {"friendly_name": "Study", "source": "Server", "source_list": ["Bridge", "Home Assistant", "Server"]},
        ),
    ])
    rules_mgr = MagicMock()
    rules_mgr.get_rules = MagicMock(
        return_value={
            "media_input_mappings": {"Bridge": "media_player.bridge", "Home Assistant": "media_player.vlc_telnet"},
            "media_unjoin_input": "Home Assistant",
        }
    )
    mgr = AudioHandoffManager(hass, rules_manager=rules_mgr)

    res = await mgr.async_apply_default_input_to_idle_zones("Home Assistant")
    assert res["success"] is True
    assert res["reverted"] == ["media_player.matrix_amp_1_study"]
    assert hass.services.async_call.await_count == 2
    hass.services.async_call.assert_any_await(
        "media_player", "turn_on", {"entity_id": "media_player.matrix_amp_1_study"}, blocking=True
    )
    hass.services.async_call.assert_any_await(
        "media_player",
        "select_source",
        {"entity_id": "media_player.matrix_amp_1_study", "source": "Home Assistant"},
        blocking=True,
    )
