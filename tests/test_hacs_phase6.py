"""Unit tests for HACS Default Catalog PR 13059 Compliance: Phase 6 (Items 15–20)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from custom_components.otis_ai.const import DOMAIN, PLATFORMS
from custom_components.otis_ai.sensor import (
    SENSOR_DEFINITIONS,
    OtisSensorEntity,
    async_update_entity_state,
)
from custom_components.otis_ai.binary_sensor import (
    BINARY_SENSOR_DEFINITIONS,
    OtisBinarySensorEntity,
)
from custom_components.otis_ai.switch import (
    SWITCH_DEFINITIONS,
    OtisSwitchEntity,
)
from custom_components.otis_ai.rules_manager import (
    BehavioralRulesManager,
    scrub_sensitive_rules,
)
from custom_components.otis_ai.habit_manager import BehavioralHabitManager
from custom_components.otis_ai.dashboard_manager import DashboardManager


# ==============================================================================
# ITEM 15: ENTITY PLATFORMS & STATE MANAGEMENT (NO PHANTOM STATES)
# ==============================================================================

def test_platforms_list_and_definitions():
    """Verify standard PLATFORMS list and canonical definitions are configured."""
    assert "sensor" in PLATFORMS
    assert "binary_sensor" in PLATFORMS
    assert "switch" in PLATFORMS
    assert len(SENSOR_DEFINITIONS) >= 12
    assert len(BINARY_SENSOR_DEFINITIONS) >= 1
    assert len(SWITCH_DEFINITIONS) >= 2


def test_sensor_entity_state_lifecycle():
    """Verify OtisSensorEntity updates state and attributes via async_set_state."""
    hass = MagicMock()
    hass.states = MagicMock()
    entry = MagicMock(entry_id="test_entry_1")

    s_def = SENSOR_DEFINITIONS[0]  # spatial_migration
    sensor = OtisSensorEntity(hass, entry, s_def)

    assert sensor.entity_id == "sensor.otis_spatial_migration"
    assert sensor.native_value == "idle"

    # Update state via coordinator callback
    sensor.async_set_state("in_progress", {"target_area": "living_room"})
    assert sensor.native_value == "in_progress"
    assert sensor.extra_state_attributes["target_area"] == "living_room"


def test_binary_sensor_entity_state_lifecycle():
    """Verify OtisBinarySensorEntity updates state and attributes via async_set_state."""
    hass = MagicMock()
    entry = MagicMock(entry_id="test_entry_1")

    b_def = BINARY_SENSOR_DEFINITIONS[0]  # active_occupancy
    b_sensor = OtisBinarySensorEntity(hass, entry, b_def)

    assert b_sensor.entity_id == "binary_sensor.otis_active_occupancy"
    assert b_sensor.is_on is False

    b_sensor.async_set_state(True, {"occupied_count": 2})
    assert b_sensor.is_on is True
    assert b_sensor.extra_state_attributes["occupied_count"] == 2


def test_switch_entity_state_lifecycle():
    """Verify OtisSwitchEntity integrates with rules manager and toggles."""
    hass = MagicMock()
    entry = MagicMock(entry_id="test_entry_1")
    rules_mgr = MagicMock()
    rules_mgr.get_rules.return_value = {"audio_follow_enabled": True}
    rules_mgr.async_save = AsyncMock()

    s_def = SWITCH_DEFINITIONS[0]  # audio_follow
    switch = OtisSwitchEntity(hass, entry, s_def, rules_manager=rules_mgr)

    assert switch.entity_id == "switch.otis_audio_follow"
    assert switch.is_on is True

    # Turn off
    asyncio.run(switch.async_turn_off())
    assert switch.is_on is False
    rules_mgr.async_save.assert_awaited_with({"audio_follow_enabled": False})


def test_async_update_entity_state_dispatches_to_platform_entity():
    """Verify async_update_entity_state updates registered entity and never spoofs hass.states.async_set."""
    hass = MagicMock()
    mock_entity = MagicMock()
    mock_entity.async_set_state = MagicMock()

    hass.data = {
        DOMAIN: {
            "test_entry_1": {
                "entities": {
                    "sensor.otis_mesh_health": mock_entity
                }
            }
        }
    }

    # 1. Update registered platform entity
    async_update_entity_state(hass, "sensor.otis_mesh_health", "healthy", {"nodes": 12})
    mock_entity.async_set_state.assert_called_once_with("healthy", {"nodes": 12})

    # 2. Unbacked entities must NOT spoof hass.states.async_set
    async_update_entity_state(hass, "sensor.otis_unbacked", "active", {})
    hass.states.async_set.assert_not_called()


# ==============================================================================
# ITEM 17: DYNAMIC STATE CHECKS (NO CANNED STATUS RESPONSES)
# ==============================================================================

@pytest.mark.asyncio
async def test_dynamic_security_status_check():
    """Verify HA Core status dynamically queries live locks and alarm panels."""
    from custom_components.otis_ai import OtisAIConversationAgent

    hass = MagicMock()
    entry = MagicMock(entry_id="test_entry")
    entry.options = {}
    entry.data = {}
    engine = MagicMock()
    engine.async_build_capability_map = AsyncMock(return_value={"areas": {}, "entities": []})
    auto_mgr = MagicMock()

    mock_panel = MagicMock(entity_id="alarm_control_panel.home", state="armed_home", name="Home Alarm")
    mock_lock = MagicMock(entity_id="lock.front_door", state="locked", name="Front Door Lock")

    hass.states.async_all.side_effect = lambda domain: [mock_panel] if domain == "alarm_control_panel" else [mock_lock] if domain == "lock" else []

    agent = OtisAIConversationAgent(hass, entry, engine, auto_mgr, local_llm_manager=MagicMock())

    user_input = MagicMock()
    user_input.text = "what is the current status of HA core?"
    user_input.conversation_id = "test_conv"
    user_input.create_response = MagicMock(return_value="response")

    await agent.async_process(user_input)
    speech = user_input.create_response.call_args[1]["speech"]

    # Verify real dynamic values are reflected, NOT canned text
    assert "Alarm panel is armed_home" in speech
    assert "Smart locks (1/1 secured)" in speech
    assert "exterior deadbolts are locked (no guest access)" not in speech


# ==============================================================================
# ITEM 18: ZERO HARDCODED PERSONAL ENTITIES
# ==============================================================================

def test_no_hardcoded_personal_entities_in_prompts():
    """Verify prompts avoid personal hardcoded entities like climate.downstairs or personal names."""
    from custom_components.otis_ai import OtisAIConversationAgent

    hass = MagicMock()
    entry = MagicMock(entry_id="test_entry")
    agent = OtisAIConversationAgent(hass, entry, MagicMock(), MagicMock())

    # Verify macro pre-arming fallback does not inject fictitious entity
    # (macro_manager returns None instead of input_boolean.master_night_prearm)
    from custom_components.otis_ai.macro_manager import MacroManager
    mm = MacroManager(hass)
    hass.states.async_all.return_value = []
    res = asyncio.run(mm.async_process_spatial_migration({"target_area": "master", "intent": "sleep_bedtime"}))
    assert res is None


# ==============================================================================
# ITEM 19: NON-BLOCKING FILESYSTEM CHECKS
# ==============================================================================

@pytest.mark.asyncio
async def test_habit_manager_non_blocking_db_resolution():
    """Verify BehavioralHabitManager resolves db path via executor."""
    hass = MagicMock()
    hass.config.path.return_value = "/tmp/home-assistant_v2.db"
    hass.async_add_executor_job = AsyncMock(return_value="/tmp/home-assistant_v2.db")

    hm = BehavioralHabitManager(hass)
    resolved = await hm._async_get_db_path()
    assert resolved == "/tmp/home-assistant_v2.db"
    hass.async_add_executor_job.assert_awaited()


@pytest.mark.asyncio
async def test_dashboard_manager_non_blocking_svg_stat():
    """Verify DashboardManager inspects SVG floorplan stats via executor."""
    hass = MagicMock()
    hass.config.path.return_value = "/tmp/otis_floorplan.svg"
    hass.async_add_executor_job = AsyncMock(return_value=(True, 12345678))

    dm = DashboardManager(hass)
    stat = await dm._async_get_floorplan_svg_stat()
    assert stat == (True, 12345678)
    hass.async_add_executor_job.assert_awaited()


# ==============================================================================
# ITEM 20: SENSITIVE DATA SCRUBBING ON EVENT BUS
# ==============================================================================

def test_scrub_sensitive_rules_redacts_credentials_and_pins():
    """Verify scrub_sensitive_rules redacts PINs, lock codes, and credentials."""
    unscrubbed_rules = {
        "persona": "concierge",
        "guest_lock_code": "1234",
        "lock_code": "5678",
        "access_pin": "9999",
        "api_key": "secret_abc123",
        "password": "my_secure_password",
        "user_token": "token_xyz",
        "nested": {
            "door_pin": "4321",
            "safe_value": "living_room",
        },
        "safe_list": ["item1", "item2"],
    }

    scrubbed = scrub_sensitive_rules(unscrubbed_rules)

    assert scrubbed["persona"] == "concierge"
    assert scrubbed["guest_lock_code"] == "[REDACTED]"
    assert scrubbed["lock_code"] == "[REDACTED]"
    assert scrubbed["access_pin"] == "[REDACTED]"
    assert scrubbed["api_key"] == "[REDACTED]"
    assert scrubbed["password"] == "[REDACTED]"
    assert scrubbed["user_token"] == "[REDACTED]"
    assert scrubbed["nested"]["door_pin"] == "[REDACTED]"
    assert scrubbed["nested"]["safe_value"] == "living_room"
    assert scrubbed["safe_list"] == ["item1", "item2"]


@pytest.mark.asyncio
async def test_rules_manager_event_bus_scrubbing():
    """Verify BehavioralRulesManager scrubs sensitive payload before async_fire."""
    hass = MagicMock()
    hass.bus.async_fire = MagicMock()

    rm = BehavioralRulesManager(hass)
    rm._rules = {
        "persona": "butler",
        "guest_lock_code": "4321",
    }
    rm._loaded = True

    mock_store = MagicMock()
    mock_store.async_save = AsyncMock()
    rm._store = mock_store

    await rm.async_confirm_person_identity("person.guest", confirmed=True, visual_features={"area": "porch"})

    hass.bus.async_fire.assert_called()
    event_call = hass.bus.async_fire.call_args
    event_name = event_call[0][0]
    event_payload = event_call[0][1]

    assert event_name == "otis_ai_rules_updated"
    assert event_payload["rules"]["guest_lock_code"] == "[REDACTED]"
    assert event_payload["rules"]["persona"] == "butler"
