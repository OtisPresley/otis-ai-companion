"""Unit tests for Otis Multimodal Presence Fusion (Phase 8)."""

import math
from unittest.mock import MagicMock
import pytest

from custom_components.otis_ai.presence_manager import (
    MMWAVE_STATE_BOTH,
    MMWAVE_STATE_CLEAR,
    MMWAVE_STATE_MOVING,
    MMWAVE_STATE_STATIONARY,
    STATUS_MICRO_PRESENCE,
    STATUS_OCCUPIED,
    STATUS_VACANT,
    PresenceFusionManager,
    calculate_ble_distance,
    evaluate_acoustic_footprint,
    evaluate_mmwave_signature,
    evaluate_thermal_signature,
    solve_2d_trilateration,
)


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = MagicMock()
    states_dict = {}

    def mock_set(entity_id, state, attributes=None):
        mock_state = MagicMock()
        mock_state.entity_id = entity_id
        mock_state.state = state
        mock_state.attributes = attributes or {}
        states_dict[entity_id] = mock_state

    def mock_get(entity_id):
        return states_dict.get(entity_id)

    def mock_all():
        return list(states_dict.values())

    from custom_components.otis_ai.const import DOMAIN

    class _EntityMap(dict):
        def get(self, key, default=None):
            if key not in self:
                ent = MagicMock()
                ent.async_set_state = lambda state, attributes=None, _eid=key: mock_set(_eid, state, attributes)
                self[key] = ent
            return super().get(key, default)

    hass.data = {DOMAIN: {"test_entry": {"entities": _EntityMap()}}}
    hass.states.async_set = mock_set
    hass.states.get = mock_get
    hass.states.async_all = mock_all
    return hass


@pytest.fixture
def presence_manager(mock_hass):
    """PresenceFusionManager fixture."""
    return PresenceFusionManager(mock_hass)


# ============================================================================
# 1. BLE Trilateration & Distance Modeling Tests
# ============================================================================

def test_calculate_ble_distance():
    """Test log-distance path loss distance calculation."""
    # At reference RSSI (-59 dBm), distance should be ~1.0m
    d_1m = calculate_ble_distance(-59.0, ref_rssi=-59.0, path_loss_exp=2.0)
    assert math.isclose(d_1m, 1.0, rel_tol=1e-2)

    # 6 dB drop with n=2.0 roughly doubles distance: -65 dBm -> ~2.0m
    d_2m = calculate_ble_distance(-65.0, ref_rssi=-59.0, path_loss_exp=2.0)
    assert 1.8 <= d_2m <= 2.2

    # High RSSI or zero should clamp to minimum distance
    assert calculate_ble_distance(0.0) == 0.1
    assert calculate_ble_distance(5.0) == 0.1

    # Extreme low RSSI should clamp to max bounds
    d_far = calculate_ble_distance(-110.0, ref_rssi=-59.0, path_loss_exp=2.0)
    assert d_far <= 50.0


def test_solve_2d_trilateration_exact():
    """Test 2D trilateration with 3 non-collinear anchors at known positions."""
    # Target is at (3.0, 4.0)
    # Anchor 1: (0, 0), distance = sqrt(3^2 + 4^2) = 5.0
    # Anchor 2: (6, 0), distance = sqrt((3-6)^2 + 4^2) = 5.0
    # Anchor 3: (0, 4), distance = sqrt(3^2 + (4-4)^2) = 3.0
    anchors = [
        {"name": "a1", "x": 0.0, "y": 0.0, "distance": 5.0},
        {"name": "a2", "x": 6.0, "y": 0.0, "distance": 5.0},
        {"name": "a3", "x": 0.0, "y": 4.0, "distance": 3.0},
    ]
    sol = solve_2d_trilateration(anchors)
    assert sol is not None
    assert sol["method"] == "least_squares_trilateration"
    assert math.isclose(sol["x"], 3.0, abs_tol=0.2)
    assert math.isclose(sol["y"], 4.0, abs_tol=0.2)


def test_solve_2d_trilateration_collinear_fallback():
    """Test fallback when 3 anchors are collinear along a single axis."""
    anchors = [
        {"name": "a1", "x": 0.0, "y": 0.0, "distance": 5.0},
        {"name": "a2", "x": 6.0, "y": 0.0, "distance": 5.0},
        {"name": "a3", "x": 3.0, "y": 0.0, "distance": 4.0},
    ]
    sol = solve_2d_trilateration(anchors)
    assert sol is not None
    assert sol["method"] == "weighted_centroid_fallback"


def test_solve_2d_trilateration_two_anchors():
    """Test fallback when only 2 anchors observe the beacon."""
    anchors = [
        {"name": "a1", "x": 0.0, "y": 0.0, "distance": 2.0},
        {"name": "a2", "x": 10.0, "y": 0.0, "distance": 2.0},
    ]
    sol = solve_2d_trilateration(anchors)
    assert sol is not None
    assert sol["method"] == "weighted_pair"
    # Equal distance means midpoint (5.0, 0.0)
    assert math.isclose(sol["x"], 5.0, abs_tol=0.1)
    assert math.isclose(sol["y"], 0.0, abs_tol=0.1)


def test_solve_2d_trilateration_degenerate_or_insufficient():
    """Test trilateration with fewer than 2 anchors or degenerate configuration."""
    assert solve_2d_trilateration([]) is None
    assert solve_2d_trilateration([{"x": 1.0, "y": 1.0, "distance": 2.0}]) is None


def test_manager_trilaterate_beacon(presence_manager):
    """Test trilaterating beacon through PresenceFusionManager with anchor registry."""
    presence_manager.set_anchor_positions({
        "proxy_north": {"x": 5.0, "y": 10.0},
        "proxy_east": {"x": 10.0, "y": 5.0},
        "proxy_west": {"x": 0.0, "y": 5.0},
    })
    presence_manager.assign_beacon_user("ble_watch_jordan", "Jordan")

    assert presence_manager.get_beacon_user("ble_watch_jordan") == "Jordan"

    # Observation without explicit x/y coordinates pulls from manager registry
    obs = [
        {"anchor_id": "proxy_north", "rssi": -65.0},
        {"anchor_id": "proxy_east", "rssi": -68.0},
        {"anchor_id": "proxy_west", "rssi": -68.0},
    ]
    result = presence_manager.trilaterate_beacon(obs)
    assert result is not None
    assert "x" in result
    assert "y" in result
    assert len(result["anchors_used"]) == 3


# ============================================================================
# 2. mmWave Micro-Motion & Static Target Sensing Tests
# ============================================================================

def test_evaluate_mmwave_stationary_micro_motion():
    """Test detecting stationary resident (breathing / sitting still) via mmWave."""
    eval_res = evaluate_mmwave_signature(
        state="on",
        attributes={"static_target_energy": 65, "moving_target_energy": 0, "target_distance": 2.4},
    )
    assert eval_res["active"] is True
    assert eval_res["mode"] == MMWAVE_STATE_STATIONARY
    assert eval_res["confidence"] >= 0.90
    assert eval_res["target_distance_m"] == 2.4
    assert eval_res["static_energy"] == 65


def test_evaluate_mmwave_moving_target():
    """Test detecting moving target via mmWave."""
    eval_res = evaluate_mmwave_signature(
        state="on",
        attributes={"static_target_energy": 0, "moving_target_energy": 80, "target_distance": 4.1},
    )
    assert eval_res["active"] is True
    assert eval_res["mode"] == MMWAVE_STATE_MOVING
    assert eval_res["confidence"] >= 0.85


def test_evaluate_mmwave_both_targets():
    """Test detecting simultaneous moving and stationary targets."""
    eval_res = evaluate_mmwave_signature(
        state="on",
        attributes={"static_target_energy": 45, "moving_target_energy": 70},
    )
    assert eval_res["active"] is True
    assert eval_res["mode"] == MMWAVE_STATE_BOTH
    assert eval_res["confidence"] >= 0.94


def test_evaluate_mmwave_clear():
    """Test mmWave sensor when clear/off."""
    eval_res = evaluate_mmwave_signature(state="off")
    assert eval_res["active"] is False
    assert eval_res["mode"] == MMWAVE_STATE_CLEAR
    assert eval_res["confidence"] == 0.0


# ============================================================================
# 3. Thermal Signature & Discrimination Tests
# ============================================================================

def test_evaluate_thermal_human_signature():
    """Test human body surface temperature detection."""
    # Target temp = 33.5C (skin surface), ambient = 22.0C -> Delta = 11.5C
    eval_res = evaluate_thermal_signature(
        target_temp_c=33.5,
        ambient_temp_c=22.0,
        attributes={"hotspot_pixel_count": 12},
    )
    assert eval_res["detected"] is True
    assert eval_res["target_type"] == "human"
    assert eval_res["confidence"] >= 0.85
    assert eval_res["delta_c"] == 11.5


def test_evaluate_thermal_pet_rejection():
    """Test pet / small warm object rejection."""
    # Target temp = 26.5C (cool pet fur surface above ambient 21.0C, but below human 29.5C)
    eval_res = evaluate_thermal_signature(
        target_temp_c=26.5,
        ambient_temp_c=21.0,
    )
    assert eval_res["detected"] is False
    assert eval_res["target_type"] == "pet_or_appliance"
    assert eval_res["confidence"] <= 0.35


def test_evaluate_thermal_heat_source_rejection():
    """Test non-human high heat source rejection (radiator/fireplace/stove)."""
    eval_res = evaluate_thermal_signature(
        target_temp_c=48.0,
        ambient_temp_c=22.0,
    )
    assert eval_res["detected"] is False
    assert eval_res["target_type"] == "heat_source"


def test_evaluate_thermal_missing_temperatures():
    """Test thermal evaluation with missing or invalid inputs."""
    eval_res = evaluate_thermal_signature(None, 22.0)
    assert eval_res["detected"] is False
    assert eval_res["confidence"] == 0.0


# ============================================================================
# 4. Acoustic Footprinting Tests
# ============================================================================

def test_evaluate_acoustic_speech_detection():
    """Test speech / conversation audio detection."""
    eval_res = evaluate_acoustic_footprint(
        current_db=52.0,
        ambient_floor_db=36.0,
        event_type="speech_detected",
    )
    assert eval_res["detected"] is True
    assert eval_res["confidence"] >= 0.85
    assert eval_res["db_delta"] == 16.0


def test_evaluate_acoustic_activity_spike():
    """Test physical activity acoustic spike (footsteps / keyboard)."""
    eval_res = evaluate_acoustic_footprint(
        current_db=48.0,
        ambient_floor_db=38.0,
        event_type="footsteps",
    )
    assert eval_res["detected"] is True
    assert eval_res["confidence"] >= 0.60


def test_evaluate_acoustic_generic_noise_spike_not_confirmed():
    """Test non-classified generic sound spike (does not affirm human presence alone)."""
    eval_res = evaluate_acoustic_footprint(
        current_db=49.0,
        ambient_floor_db=38.0,
        event_type=None,
    )
    assert eval_res["detected"] is False
    assert eval_res["confidence"] <= 0.50


# ============================================================================
# 5. Multimodal Bayesian Fusion & Edge Cases Tests
# ============================================================================

def test_fuse_room_false_negative_prevention(presence_manager):
    """Test that sleeping or reading resident (PIR off) is accurately detected as micro_presence."""
    # Resident sitting reading: PIR is off, but mmWave detects stationary breathing and thermal detects human skin temp
    res = presence_manager.fuse_room_modalities(
        area_id="master_bedroom",
        area_name="Master Bedroom",
        mmwave_data={"active": True, "confidence": 0.94, "mode": MMWAVE_STATE_STATIONARY},
        thermal_data={"detected": True, "confidence": 0.88, "target_type": "human"},
        pir_data={"active": False, "confidence": 0.0},
    )
    assert res["status"] == STATUS_MICRO_PRESENCE
    assert res["is_micro_presence"] is True
    assert res["probability"] >= 0.90
    assert "mmwave_stationary" in res["active_modalities"]
    assert "thermal_human" in res["active_modalities"]


def test_fuse_room_false_positive_rejection_vacuum(presence_manager):
    """Test that robot vacuum moving (PIR on, but no human thermal/BLE/mmWave) is rejected."""
    # Robot vacuum: PIR triggers, but thermal shows pet_or_appliance, mmWave is clear, no BLE
    res = presence_manager.fuse_room_modalities(
        area_id="living_room",
        area_name="Living Room",
        pir_data={"active": True, "confidence": 0.75},
        thermal_data={"detected": False, "confidence": 0.20, "target_type": "pet_or_appliance"},
        mmwave_data={"active": False, "confidence": 0.0, "mode": MMWAVE_STATE_CLEAR},
        ble_data={"active": False, "confidence": 0.0},
    )
    # The PIR confidence is heavily discounted (0.75 * 0.20 = 0.15), keeping probability well below 0.30
    assert res["status"] == STATUS_VACANT
    assert res["probability"] < 0.30


def test_fuse_room_false_positive_rejection_abandoned_media(presence_manager):
    """Test that a TV left playing in an empty room is discounted and rejected."""
    res = presence_manager.fuse_room_modalities(
        area_id="theater",
        area_name="Home Theater",
        media_data={"active": True, "confidence": 0.45},
        pir_data={"active": False, "confidence": 0.0},
        mmwave_data={"active": False, "confidence": 0.0, "mode": MMWAVE_STATE_CLEAR},
        thermal_data={"detected": False, "confidence": 0.0, "target_type": "none"},
        ble_data={"active": False, "confidence": 0.0},
    )
    assert res["status"] == STATUS_VACANT
    assert res["probability"] < 0.20


def test_fuse_room_ble_user_attribution(presence_manager):
    """Test associating detected room occupancy with a recognized user via BLE."""
    res = presence_manager.fuse_room_modalities(
        area_id="office",
        area_name="Office",
        pir_data={"active": True, "confidence": 0.75},
        ble_data={"active": True, "confidence": 0.85, "user": "Jordan"},
    )
    assert res["status"] == STATUS_OCCUPIED
    assert res["attributed_user"] == "Jordan"
    assert any("ble_beacon (Jordan)" in m for m in res["active_modalities"])


# ============================================================================
# 6. Full Area Audit & Sensor Publishing Tests
# ============================================================================

@pytest.mark.asyncio
async def test_async_fuse_presence_full_audit(presence_manager, mock_hass):
    """Test full async area presence audit and sensor.otis_fused_presence telemetry."""
    # Mock area registry
    area_mock = MagicMock()
    area_mock.id = "office"
    area_mock.name = "Office"

    ar_mock = MagicMock()
    ar_mock.async_list_areas.return_value = [area_mock]

    # Patch ar.async_get to return ar_mock
    import homeassistant.helpers.area_registry as ar
    orig_ar = getattr(ar, "async_get", None)
    ar.async_get = MagicMock(return_value=ar_mock)

    try:
        # Populate Home Assistant states
        mock_hass.states.async_set(
            "binary_sensor.office_mmwave_radar",
            "on",
            {"device_class": "presence", "static_target_energy": 55, "friendly_name": "Office mmWave"},
        )
        mock_hass.states.async_set(
            "sensor.office_ambient_temp",
            "21.5",
            {"device_class": "temperature", "friendly_name": "Office Ambient Temp"},
        )
        mock_hass.states.async_set(
            "sensor.office_thermal_target",
            "33.2",
            {"device_class": "temperature", "friendly_name": "Office Thermal Target"},
        )
        mock_hass.states.async_set(
            "sensor.office_ble_rssi",
            "-62",
            {"friendly_name": "Office BLE RSSI", "distance": 1.2, "person": "Jordan"},
        )

        telemetry = await presence_manager.async_fuse_presence(use_cache=False)

        assert telemetry["total_areas"] == 1
        assert telemetry["occupied_count"] >= 1 or telemetry["micro_presence_count"] >= 1
        assert "office" in telemetry["rooms"]

        office_room = telemetry["rooms"]["office"]
        assert office_room["probability"] >= 0.85
        assert office_room["status"] in (STATUS_OCCUPIED, STATUS_MICRO_PRESENCE)

        # Check published sensor
        sensor_st = mock_hass.states.get("sensor.otis_fused_presence")
        assert sensor_st is not None
        assert sensor_st.state in ("occupied", "likely")
        assert sensor_st.attributes["occupied_count"] >= 1 or sensor_st.attributes["micro_presence_count"] >= 1

    finally:
        if orig_ar:
            ar.async_get = orig_ar


@pytest.mark.asyncio
async def test_conversation_agent_fused_presence_query(mock_hass):
    """Test OtisAIConversationAgent responding to multimodal presence queries."""
    from unittest.mock import AsyncMock
    from custom_components.otis_ai import OtisAIConversationAgent

    entry = MagicMock()
    entry.options = {}
    entry.data = {}
    engine = MagicMock()
    auto_mgr = MagicMock()

    pm_mock = MagicMock()
    pm_mock.async_fuse_presence = AsyncMock(return_value={
        "occupied_areas": ["Office"],
        "micro_presence_areas": ["Master Bedroom"],
        "likely_areas": [],
        "rooms": {
            "office": {
                "area_name": "Office",
                "status": "occupied",
                "attributed_user": "Jordan",
                "active_modalities": ["mmwave_moving", "thermal_human", "ble_beacon"],
                "confidence_percent": 95,
            },
            "master_bedroom": {
                "area_name": "Master Bedroom",
                "status": "micro_presence",
                "attributed_user": "Elena",
                "active_modalities": ["mmwave_stationary", "thermal_human"],
                "confidence_percent": 92,
            },
        },
    })

    agent = OtisAIConversationAgent(
        mock_hass, entry, engine, auto_mgr, presence_fusion_manager=pm_mock
    )

    u1 = MagicMock()
    u1.text = "Where is everyone right now?"
    u1.conversation_id = "test_conv_fused_pres"
    u1.create_response = MagicMock(return_value="mock_resp")
    await agent.async_process(u1)

    speech = u1.create_response.call_args[1]["speech"]
    assert "Office" in speech
    assert "Jordan" in speech
    assert "Master Bedroom" in speech
    assert "Elena" in speech
    assert "Micro-Presence" in speech


def test_resolve_media_player_playback_output_zone_vs_input_source():
    """Always-on output zone players must defer playback truth to their selected input source."""
    from custom_components.otis_ai.presence_manager import resolve_media_player_playback

    input_idle = MagicMock(
        entity_id="media_player.sonos_port",
        state="idle",
        attributes={"friendly_name": "Sonos Port"},
    )
    input_playing = MagicMock(
        entity_id="media_player.apple_tv",
        state="playing",
        attributes={"friendly_name": "Apple TV", "media_title": "Movie"},
    )
    zone_on_idle_src = MagicMock(
        entity_id="media_player.kitchen_zone",
        state="on",
        attributes={
            "friendly_name": "Kitchen Zone",
            "source": "Sonos Port",
            "source_list": ["Sonos Port", "Apple TV"],
        },
    )
    zone_on_playing_src = MagicMock(
        entity_id="media_player.dining_zone",
        state="on",
        attributes={
            "friendly_name": "Dining Zone",
            "source": "Apple TV",
            "source_list": ["Sonos Port", "Apple TV"],
        },
    )
    zone_playing_paused_src = MagicMock(
        entity_id="media_player.study_zone",
        state="playing",
        attributes={
            "friendly_name": "Study Zone",
            "source": "Sonos Port",
            "source_list": ["Sonos Port", "Apple TV"],
        },
    )
    standalone_playing = MagicMock(
        entity_id="media_player.office_speaker",
        state="playing",
        attributes={"friendly_name": "Office Speaker", "media_title": "Focus"},
    )

    all_states = [
        input_idle,
        input_playing,
        zone_on_idle_src,
        zone_on_playing_src,
        zone_playing_paused_src,
        standalone_playing,
    ]

    res_idle = resolve_media_player_playback(zone_on_idle_src, all_states)
    assert res_idle["playing"] is False
    assert res_idle["is_output_zone"] is True
    assert res_idle["resolved_input"] == "media_player.sonos_port"

    res_active = resolve_media_player_playback(zone_on_playing_src, all_states)
    assert res_active["playing"] is True
    assert res_active["resolved_input"] == "media_player.apple_tv"

    res_override = resolve_media_player_playback(zone_playing_paused_src, all_states)
    assert res_override["playing"] is False
    assert res_override["resolved_input"] == "media_player.sonos_port"

    res_standalone = resolve_media_player_playback(standalone_playing, all_states)
    assert res_standalone["playing"] is True
    assert res_standalone["is_output_zone"] is False


