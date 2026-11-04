"""Tests for Otis AI Companion Energy Arbitrage & Battery Scheduling Engine (Phase 2)."""

import asyncio
from datetime import datetime
from unittest.mock import MagicMock
import pytest

from custom_components.otis_ai.energy_manager import (
    ACTION_CHARGE_GRID,
    ACTION_DISCHARGE_PEAK,
    ACTION_HOLD_RESERVE,
    ACTION_IDLE,
    ACTION_STORE_SOLAR,
    DEFAULT_TOU_RATES,
    MODE_AUTO,
    MODE_BACKUP_RESERVE,
    MODE_PEAK_ARBITRAGE,
    MODE_SELF_CONSUMPTION,
    EnergyManager,
)


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = MagicMock()
    hass.states.async_all.return_value = []
    hass.states.get.return_value = None
    return hass


@pytest.fixture
def energy_manager(mock_hass):
    """Energy manager fixture."""
    return EnergyManager(mock_hass)


def test_arbitrage_mode_switching(energy_manager):
    """Test switching between valid arbitrage modes and rejecting invalid ones."""
    assert energy_manager.get_arbitrage_mode() == MODE_AUTO
    assert energy_manager.set_arbitrage_mode(MODE_PEAK_ARBITRAGE) is True
    assert energy_manager.get_arbitrage_mode() == MODE_PEAK_ARBITRAGE
    assert energy_manager.set_arbitrage_mode(MODE_BACKUP_RESERVE) is True
    assert energy_manager.get_arbitrage_mode() == MODE_BACKUP_RESERVE
    assert energy_manager.set_arbitrage_mode(MODE_SELF_CONSUMPTION) is True
    assert energy_manager.get_arbitrage_mode() == MODE_SELF_CONSUMPTION
    assert energy_manager.set_arbitrage_mode("invalid_mode") is False
    assert energy_manager.get_arbitrage_mode() == MODE_SELF_CONSUMPTION


def test_tou_rates_configuration(energy_manager):
    """Test reading and overriding TOU electricity rates."""
    rates = energy_manager.get_tou_rates()
    assert rates == DEFAULT_TOU_RATES
    energy_manager.set_tou_rates({"off_peak": 0.05, "peak": 0.45})
    updated = energy_manager.get_tou_rates()
    assert updated["off_peak"] == 0.05
    assert updated["peak"] == 0.45
    assert updated["shoulder"] == DEFAULT_TOU_RATES["shoulder"]


def test_solar_production_profile(energy_manager):
    """Test astronomical bell curve generation for solar production."""
    profile = energy_manager.estimate_solar_production_profile(daily_forecast_kwh=30.0)
    assert len(profile) == 24
    # Night hours (00:00 - 05:00 and 20:00 - 23:00) should be zero
    for h in [0, 1, 2, 3, 4, 5, 20, 21, 22, 23]:
        assert profile[h] == 0.0
    # Solar peak should occur around midday (12:00 - 13:00)
    assert profile[12] > profile[7]
    assert profile[13] > profile[18]
    # Sum of hourly kWh should approximately equal the 30.0 kWh forecast
    assert abs(sum(profile) - 30.0) < 0.2

    # Zero forecast handles gracefully
    zero_profile = energy_manager.estimate_solar_production_profile(daily_forecast_kwh=0.0)
    assert all(x == 0.0 for x in zero_profile)


def test_household_consumption_profile(energy_manager):
    """Test empirical residential load profile generation."""
    profile = energy_manager.estimate_household_consumption_profile(baseline_kw=1.0)
    assert len(profile) == 24
    # Evening peak (17:00 - 20:00) should be higher than overnight low (01:00 - 04:00)
    assert profile[18] > profile[2]
    # Morning prep (07:00) should be higher than overnight
    assert profile[7] > profile[3]


def test_arbitrage_schedule_peak_arbitrage_mode(energy_manager):
    """Test peak arbitrage mode charges in off-peak and discharges during 2PM-7PM peak."""
    # Simulation starts on a weekday at 10:00 AM (shoulder window) with 60% SoC
    start_dt = datetime(2026, 11, 4, 10, 0, 0)  # Wednesday
    plan = energy_manager.calculate_arbitrage_schedule(
        current_soc_pct=60.0,
        battery_capacity_kwh=13.5,
        max_charge_kw=5.0,
        max_discharge_kw=5.0,
        min_reserve_soc_pct=20.0,
        mode=MODE_PEAK_ARBITRAGE,
        daily_solar_kwh=25.0,
        baseline_load_kw=1.2,
        start_dt=start_dt,
    )

    assert plan["mode"] == MODE_PEAK_ARBITRAGE
    assert len(plan["schedule"]) == 24
    assert plan["projected_savings_usd"] >= 0.0
    assert plan["projected_peak_shave_kwh"] > 0.0

    # Locate peak hours in the schedule (14:00 to 18:00)
    peak_steps = [s for s in plan["schedule"] if s["tariff_period"] == "peak"]
    assert len(peak_steps) == 5
    # During peak hours, battery should discharge to eliminate grid import
    assert any(s["action"] == ACTION_DISCHARGE_PEAK for s in peak_steps)

    # Battery must not drop below reserve floor
    for s in plan["schedule"]:
        assert s["ending_soc_pct"] >= 20.0


def test_arbitrage_schedule_backup_reserve_mode(energy_manager):
    """Test backup reserve mode keeps battery full and never discharges for arbitrage."""
    start_dt = datetime(2026, 11, 4, 14, 0, 0)  # Wednesday peak window, 70% SoC
    plan = energy_manager.calculate_arbitrage_schedule(
        current_soc_pct=70.0,
        battery_capacity_kwh=13.5,
        min_reserve_soc_pct=20.0,
        mode=MODE_BACKUP_RESERVE,
        daily_solar_kwh=20.0,
        baseline_load_kw=1.0,
        start_dt=start_dt,
    )

    assert plan["mode"] == MODE_BACKUP_RESERVE
    # In backup reserve mode, the battery should never discharge for price arbitrage
    for s in plan["schedule"]:
        assert s["action"] != ACTION_DISCHARGE_PEAK
        assert s["battery_flow_kw"] >= 0.0  # Zero or positive (charging only)


def test_arbitrage_schedule_self_consumption_mode(energy_manager):
    """Test self consumption mode stores daytime solar surplus and covers evening deficit."""
    start_dt = datetime(2026, 11, 4, 8, 0, 0)  # Wednesday 8am
    plan = energy_manager.calculate_arbitrage_schedule(
        current_soc_pct=30.0,
        battery_capacity_kwh=13.5,
        mode=MODE_SELF_CONSUMPTION,
        daily_solar_kwh=35.0,  # High solar day
        baseline_load_kw=0.8,
        start_dt=start_dt,
    )

    assert plan["mode"] == MODE_SELF_CONSUMPTION
    # At midday, solar surplus should be stored
    midday_steps = [s for s in plan["schedule"] if s["hour"] in (11, 12, 13)]
    assert any(s["action"] == ACTION_STORE_SOLAR for s in midday_steps)


def test_async_get_arbitrage_plan_live_telemetry(mock_hass, energy_manager):
    """Test async_get_arbitrage_plan discovers live battery and solar states without blocking calls."""
    # Mock battery state
    mock_battery = MagicMock()
    mock_battery.state = "74.5"
    mock_battery.attributes = {"unit_of_measurement": "%", "device_class": "battery"}

    # Mock solar forecast state
    mock_solar = MagicMock()
    mock_solar.state = "28.5"
    mock_solar.attributes = {"unit_of_measurement": "kWh"}

    def mock_get(entity_id):
        if entity_id == "sensor.powerwall_battery":
            return mock_battery
        if entity_id == "sensor.energy_production_today":
            return mock_solar
        return None

    mock_hass.states.get.side_effect = mock_get

    plan = asyncio.run(
        energy_manager.async_get_arbitrage_plan(
            battery_entity="sensor.powerwall_battery",
            mode=MODE_AUTO,
        )
    )

    assert plan is not None
    assert plan["current_soc_pct"] == 74.5
    assert plan["daily_solar_forecast_kwh"] == 28.5
    assert len(plan["schedule"]) == 24
    assert plan["current_action"] in (
        ACTION_CHARGE_GRID,
        ACTION_STORE_SOLAR,
        ACTION_DISCHARGE_PEAK,
        ACTION_HOLD_RESERVE,
        ACTION_IDLE,
    )


def test_conversational_assist_battery_plan(mock_hass, energy_manager):
    """Test Assist conversation intent for energy arbitrage and battery plan."""
    from custom_components.otis_ai import OtisAIConversationAgent

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {}
    entry.options = {}

    engine = MagicMock()
    agent = OtisAIConversationAgent(
        mock_hass,
        entry,
        engine,
        automation_manager=MagicMock(),
        energy_manager=energy_manager,
    )

    user_input = MagicMock()
    user_input.text = "What is my energy arbitrage plan?"
    user_input.conversation_id = "conv_energy_1"
    user_input.create_response = MagicMock(return_value=MagicMock(conversation_id="conv_energy_1"))

    result = asyncio.run(agent.async_process(user_input))
    assert result.conversation_id == "conv_energy_1"
    user_input.create_response.assert_called_once()
    speech = user_input.create_response.call_args[1]["speech"]
    assert "24-Hour Energy Arbitrage & Battery Plan" in speech
    assert "Current Battery State of Charge" in speech
    assert "Estimated Daily Savings" in speech


def test_conversational_assist_backup_reserve_intent(mock_hass, energy_manager):
    """Test Assist conversation intent specifically requesting backup reserve mode."""
    from custom_components.otis_ai import OtisAIConversationAgent

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {}
    entry.options = {}

    engine = MagicMock()
    agent = OtisAIConversationAgent(
        mock_hass,
        entry,
        engine,
        automation_manager=MagicMock(),
        energy_manager=energy_manager,
    )

    user_input = MagicMock()
    user_input.text = "Optimize battery for storm outage backup"
    user_input.conversation_id = "conv_energy_2"
    user_input.create_response = MagicMock(return_value=MagicMock(conversation_id="conv_energy_2"))

    result = asyncio.run(agent.async_process(user_input))
    assert result.conversation_id == "conv_energy_2"
    speech = user_input.create_response.call_args[1]["speech"]
    assert "BACKUP_RESERVE" in speech

