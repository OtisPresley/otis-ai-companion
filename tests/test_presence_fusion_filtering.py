"""Tests for PresenceFusionManager occupancy filtering and telemetry publishing."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.otis_ai.presence_manager import PresenceFusionManager


def _make_state(entity_id: str, state: str, attributes: dict | None = None, last_changed=None):
    st = SimpleNamespace(
        entity_id=entity_id,
        state=state,
        attributes=attributes or {},
        last_changed=last_changed or datetime.now(timezone.utc),
    )
    return st


@pytest.mark.asyncio
async def test_presence_fusion_filters_frigate_all_dog_and_stale_ecobee():
    """Rooms with only *_all_occupancy / *_dog_occupancy or stale *_temp_occupancy stay vacant with mmWave idle."""
    stale_ts = datetime.now(timezone.utc) - timedelta(minutes=30)
    states = [
        _make_state(
            "binary_sensor.foyer_all_occupancy",
            "on",
            {"device_class": "occupancy", "friendly_name": "Foyer All Occupancy"},
        ),
        _make_state(
            "binary_sensor.foyer_dog_occupancy",
            "on",
            {"device_class": "occupancy", "friendly_name": "Foyer Dog Occupancy"},
        ),
        _make_state(
            "binary_sensor.foyer_person_occupancy",
            "off",
            {"device_class": "occupancy", "friendly_name": "Foyer Person Occupancy"},
        ),
        _make_state(
            "binary_sensor.otis_presence_foyer",
            "on",
            {"device_class": "occupancy", "friendly_name": "Otis Presence Foyer"},
        ),
        _make_state(
            "binary_sensor.study_temp_occupancy",
            "on",
            {"device_class": "occupancy", "friendly_name": "Study Temp Occupancy"},
            last_changed=stale_ts,
        ),
    ]

    from custom_components.otis_ai.const import DOMAIN

    hass = MagicMock()
    mock_ent = MagicMock()
    hass.data = {DOMAIN: {"test_entry": {"entities": {"sensor.otis_fused_presence": mock_ent}}}}
    hass.states = MagicMock()
    hass.states.async_all = MagicMock(return_value=states)

    areas = [
        SimpleNamespace(id="foyer", name="Foyer"),
        SimpleNamespace(id="study", name="Study"),
    ]
    ent_entries = {
        "binary_sensor.foyer_all_occupancy": SimpleNamespace(
            entity_id="binary_sensor.foyer_all_occupancy", area_id="foyer", device_id=None
        ),
        "binary_sensor.foyer_dog_occupancy": SimpleNamespace(
            entity_id="binary_sensor.foyer_dog_occupancy", area_id="foyer", device_id=None
        ),
        "binary_sensor.foyer_person_occupancy": SimpleNamespace(
            entity_id="binary_sensor.foyer_person_occupancy", area_id="foyer", device_id=None
        ),
        "binary_sensor.otis_presence_foyer": SimpleNamespace(
            entity_id="binary_sensor.otis_presence_foyer", area_id="foyer", device_id=None
        ),
        "binary_sensor.study_temp_occupancy": SimpleNamespace(
            entity_id="binary_sensor.study_temp_occupancy", area_id="study", device_id=None
        ),
    }

    area_reg = MagicMock()
    area_reg.async_list_areas = MagicMock(return_value=areas)
    ent_reg = MagicMock()
    ent_reg.entities = ent_entries
    dev_reg = MagicMock()
    dev_reg.devices = {}

    with (
        patch("custom_components.otis_ai.presence_manager.ar.async_get", return_value=area_reg),
        patch("custom_components.otis_ai.presence_manager.er.async_get", return_value=ent_reg),
        patch("custom_components.otis_ai.presence_manager.dr.async_get", return_value=dev_reg),
    ):
        pm = PresenceFusionManager(hass)
        telemetry = await pm.async_fuse_presence(use_cache=False)

    foyer = telemetry["rooms"]["foyer"]
    assert foyer["status"] == "vacant"
    assert foyer["modalities"]["mmwave"]["active"] is False

    study = telemetry["rooms"]["study"]
    assert study["status"] == "occupied"
    assert study["modalities"]["mmwave"]["active"] is False
    assert study["modalities"]["pir"]["active"] is True

    mock_ent.async_set_state.assert_called_once()
    state_val, _attrs = mock_ent.async_set_state.call_args[0]
    assert state_val == "occupied"


def test_connected_indoor_ha_areas_traverses_non_ha_subzone():
    """Pass-through spatial nodes like 'kitchen' resolve to connected HA areas such as 'mudroom'."""
    from custom_components.otis_ai.vision_manager import VisionPresenceManager

    hass = MagicMock()
    spatial_mgr = MagicMock()
    graph = {
        "great_room": ["foyer", "hallway", "kitchen", "dining_room"],
        "kitchen": ["great_room", "dining_room", "mudroom"],
    }
    spatial_mgr.get_adjacent_areas = MagicMock(side_effect=lambda aid: graph.get(aid, []))

    vm = VisionPresenceManager(hass, spatial_manager=spatial_mgr)
    known_ha_areas = {"foyer", "hallway", "great_room", "dining_room", "mudroom", "frontyard"}
    connected = vm._get_connected_indoor_ha_areas("great_room", known_ha_areas)
    assert connected == ["foyer", "hallway", "dining_room", "mudroom"]


@pytest.mark.asyncio
async def test_presence_fusion_pir_recency_hold_and_expiry():
    """Transient camera/PIR triggers decay through 'likely' for 90s before returning to 'vacant'."""
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.async_set = MagicMock()
    hass.data = {}

    foyer_person_state = _make_state("binary_sensor.foyer_person_occupancy", "on", {"device_class": "occupancy"})
    hass.states.async_all = MagicMock(return_value=[foyer_person_state])
    hass.states.get = MagicMock(return_value=None)

    area_reg = MagicMock()
    area_reg.async_list_areas = MagicMock(return_value=[SimpleNamespace(id="foyer", name="Foyer")])
    ent_reg = MagicMock()
    ent_reg.entities = {
        "binary_sensor.foyer_person_occupancy": MagicMock(
            entity_id="binary_sensor.foyer_person_occupancy", area_id="foyer", device_id=None
        )
    }
    dev_reg = MagicMock()
    dev_reg.devices = {}

    with (
        patch("custom_components.otis_ai.presence_manager.ar.async_get", return_value=area_reg),
        patch("custom_components.otis_ai.presence_manager.er.async_get", return_value=ent_reg),
        patch("custom_components.otis_ai.presence_manager.dr.async_get", return_value=dev_reg),
        patch("custom_components.otis_ai.presence_manager.time.time", side_effect=[1000.0, 1000.0, 1000.0]),
    ):
        pm = PresenceFusionManager(hass)
        t1 = await pm.async_fuse_presence(use_cache=False)

    assert t1["rooms"]["foyer"]["status"] == "occupied"
    assert t1["rooms"]["foyer"]["confidence_percent"] == 75

    # Turn off sensor; 30s later it should hold as 'likely' with seconds_since_motion=30
    foyer_person_state.state = "off"
    with (
        patch("custom_components.otis_ai.presence_manager.ar.async_get", return_value=area_reg),
        patch("custom_components.otis_ai.presence_manager.er.async_get", return_value=ent_reg),
        patch("custom_components.otis_ai.presence_manager.dr.async_get", return_value=dev_reg),
        patch("custom_components.otis_ai.presence_manager.time.time", side_effect=[1030.0, 1030.0, 1030.0]),
    ):
        t2 = await pm.async_fuse_presence(use_cache=False)

    assert t2["rooms"]["foyer"]["status"] == "likely_occupied"
    assert t2["rooms"]["foyer"]["modalities"]["pir"]["active"] is False
    assert t2["rooms"]["foyer"]["modalities"]["pir"]["seconds_since_motion"] == 30

    # 100s after trigger (past 90s hold), it should return to 'vacant'
    with (
        patch("custom_components.otis_ai.presence_manager.ar.async_get", return_value=area_reg),
        patch("custom_components.otis_ai.presence_manager.er.async_get", return_value=ent_reg),
        patch("custom_components.otis_ai.presence_manager.dr.async_get", return_value=dev_reg),
        patch("custom_components.otis_ai.presence_manager.time.time", side_effect=[1100.0, 1100.0, 1100.0]),
    ):
        t3 = await pm.async_fuse_presence(use_cache=False)

    assert t3["rooms"]["foyer"]["status"] == "vacant"
    assert t3["rooms"]["foyer"]["confidence_percent"] == 0
    assert t3["rooms"]["foyer"]["modalities"]["pir"]["seconds_since_motion"] is None

