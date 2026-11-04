"""Tests for Otis AI Companion Energy Arbitrage & Battery Scheduling Engine (Phase 2)."""

import asyncio
from datetime import datetime
from unittest.mock import MagicMock
import pytest

from custom_components.otis_ai.energy_manager import (
    ACTION_CHARGE_GRID,
    ACTION_DISCHARGE_EVENING,
    ACTION_DISCHARGE_PEAK,
    ACTION_DISCHARGE_SELF_CONSUMPTION,
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
        ACTION_DISCHARGE_EVENING,
        ACTION_DISCHARGE_SELF_CONSUMPTION,
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


def test_dynamic_hourly_tariffs_and_negative_pricing(mock_hass, energy_manager):
    """Test dynamic spot price sensor extraction with peak, shoulder, off-peak, and negative pricing."""
    mock_nordpool = MagicMock()
    mock_nordpool.entity_id = "sensor.nordpool_kwh_eur"
    mock_nordpool.state = "0.15"
    # 24 hourly prices with a negative price at 13:00 and peak at 17:00
    prices = [0.08] * 12 + [-0.02, 0.05, 0.12, 0.20, 0.45, 0.40, 0.25, 0.15, 0.10, 0.08, 0.08, 0.08]
    mock_nordpool.attributes = {"raw_today": prices}

    mock_hass.states.async_all.return_value = [mock_nordpool]

    start_dt = datetime(2026, 11, 4, 0, 0, 0)
    schedule = energy_manager.get_hourly_tariffs(start_dt)
    assert len(schedule) == 24

    # Hour 12 (12:00) has price -0.02 -> should be classified as negative
    neg_step = schedule[12]
    assert neg_step["period"] == "negative"
    assert neg_step["rate_per_kwh"] == -0.02
    assert neg_step["is_negative"] is True

    # Hour 16 (16:00) has price 0.45 -> should be classified as peak
    peak_step = schedule[16]
    assert peak_step["period"] == "peak"
    assert peak_step["is_peak"] is True


def test_contextual_solar_forecast_detailed_table(mock_hass, energy_manager):
    """Test contextual solar forecasting parsing detailed attribute tables."""
    mock_solar = MagicMock()
    mock_solar.entity_id = "sensor.forecast_solar_energy_today"
    mock_solar.state = "32.0"
    detailed = [
        {"datetime": "2026-11-04T08:00:00", "pv_estimate": 1500},
        {"datetime": "2026-11-04T12:00:00", "pv_estimate": 6200},
        {"datetime": "2026-11-04T16:00:00", "pv_estimate": 2800},
    ]
    mock_solar.attributes = {"detailed_forecast": detailed}

    def mock_get(eid):
        if eid == "sensor.forecast_solar_energy_today":
            return mock_solar
        return None

    mock_hass.states.get.side_effect = mock_get

    forecast = energy_manager.get_hourly_solar_forecast(start_dt=datetime(2026, 11, 4, 0, 0, 0))
    assert len(forecast) == 24
    assert forecast[8]["solar_kwh"] == 1.5
    assert forecast[12]["solar_kwh"] == 6.2
    assert forecast[16]["solar_kwh"] == 2.8
    assert "provider_telemetry" in forecast[12]["source"]


def test_smart_ev_charging_schedule_optimization(energy_manager):
    """Test smart EV scheduling prioritizes solar surplus and off-peak windows before departure."""
    start_dt = datetime(2026, 11, 4, 8, 0, 0)  # 08:00 AM
    solar_profile = [0.0] * 8 + [1.5, 3.5, 6.0, 7.5, 6.0, 3.5, 1.5] + [0.0] * 9  # High midday solar
    load_profile = [1.0] * 24

    plan = energy_manager.calculate_ev_charging_schedule(
        current_soc_pct=40.0,
        target_soc_pct=80.0,
        battery_capacity_kwh=77.0,
        max_charge_rate_kw=9.6,
        target_departure_hour=7,  # Tomorrow 07:00 AM
        prefer_solar_surplus=True,
        solar_profile=solar_profile,
        load_profile=load_profile,
        start_dt=start_dt,
    )

    assert plan["energy_needed_kwh"] == 30.8
    assert plan["hours_needed"] >= 3
    assert plan["solar_kwh_utilized"] > 0.0
    assert len(plan["schedule"]) == 24

    # Midday hours with surplus should have ACTION_EV_SOLAR_CHARGE
    solar_steps = [s for s in plan["schedule"] if s["source"] == "solar"]
    assert len(solar_steps) > 0
    assert any(s["action"] == "smart_ev_solar_charge" for s in solar_steps)

    # Peak hours (14:00 - 19:00) should pause EV charging
    peak_steps = [s for s in plan["schedule"] if s["hour"] in (14, 15, 16, 17, 18)]
    assert all(s["action"] in ("ev_charge_pause_peak", "smart_ev_solar_charge", "idle") for s in peak_steps)


def test_async_discover_ev_infrastructure(mock_hass, energy_manager):
    """Test discovery of EV chargers, amperage sliders, and vehicle battery entities."""
    charger_switch = MagicMock()
    charger_switch.entity_id = "switch.rivian_wall_charger"
    charger_switch.state = "off"
    charger_switch.attributes = {"friendly_name": "Rivian Wall Charger"}

    charger_current = MagicMock()
    charger_current.entity_id = "number.rivian_charger_amperage"
    charger_current.state = "32"
    charger_current.attributes = {"friendly_name": "Rivian Charger Amperage"}

    ev_vehicle = MagicMock()
    ev_vehicle.entity_id = "sensor.rivian_r1t_battery"
    ev_vehicle.state = "52.0"
    ev_vehicle.attributes = {"friendly_name": "Rivian R1T Battery", "device_class": "battery", "unit_of_measurement": "%"}

    mock_hass.states.async_all.return_value = [charger_switch, charger_current, ev_vehicle]

    topo = asyncio.run(energy_manager.async_discover_energy_topology())
    assert len(topo["ev_chargers"]) >= 2
    assert any(c["entity_id"] == "switch.rivian_wall_charger" for c in topo["ev_chargers"])
    assert any(c["entity_id"] == "number.rivian_charger_amperage" for c in topo["ev_chargers"])
    assert len(topo["ev_vehicles"]) >= 1
    assert topo["ev_vehicles"][0]["soc_pct"] == 52.0


def test_sensor_otis_energy_arbitrage_publishing(mock_hass, energy_manager):
    """Test publish_energy_arbitrage_telemetry sets sensor.otis_energy_arbitrage with rich attributes."""
    plan = {
        "current_action": "store_solar_surplus",
        "mode": "auto",
        "current_soc_pct": 68.0,
        "battery_capacity_kwh": 13.5,
        "min_reserve_soc_pct": 20.0,
        "daily_solar_forecast_kwh": 26.5,
        "baseline_load_kw": 1.1,
        "projected_savings_usd": 3.45,
        "projected_peak_shave_kwh": 7.2,
        "ev_charging_plan": {"current_action": "smart_ev_solar_charge", "target_soc_pct": 80.0},
        "schedule": [],
        "timestamp": "2026-11-04T12:00:00",
    }

    energy_manager.publish_energy_arbitrage_telemetry(plan)
    mock_hass.states.async_set.assert_called_once()
    args = mock_hass.states.async_set.call_args[0]
    assert args[0] == "sensor.otis_energy_arbitrage"
    assert args[1] == "store_solar_surplus"
    assert args[2]["current_soc_pct"] == 68.0
    assert args[2]["projected_savings_usd"] == 3.45
    assert args[2]["ev_charging"]["current_action"] == "smart_ev_solar_charge"


def test_conversational_assist_ev_schedule_and_dispatch(mock_hass, energy_manager):
    """Test Assist NLP processing of EV charging schedule and arbitrage dispatch."""
    from custom_components.otis_ai import OtisAIConversationAgent

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {}
    entry.options = {}

    agent = OtisAIConversationAgent(
        mock_hass,
        entry,
        MagicMock(),
        automation_manager=MagicMock(),
        energy_manager=energy_manager,
    )

    user_input = MagicMock()
    user_input.text = "What is my EV charging schedule?"
    user_input.conversation_id = "conv_ev_1"
    user_input.create_response = MagicMock(return_value=MagicMock(conversation_id="conv_ev_1"))

    result = asyncio.run(agent.async_process(user_input))
    assert result.conversation_id == "conv_ev_1"
    speech = user_input.create_response.call_args[1]["speech"]
    assert "Smart EV Charging Schedule" in speech
    assert "Energy Needed" in speech

    # Dispatch command
    user_input_dispatch = MagicMock()
    user_input_dispatch.text = "Execute energy arbitrage"
    user_input_dispatch.conversation_id = "conv_ev_2"
    user_input_dispatch.create_response = MagicMock(return_value=MagicMock(conversation_id="conv_ev_2"))

    result_dispatch = asyncio.run(agent.async_process(user_input_dispatch))
    assert result_dispatch.conversation_id == "conv_ev_2"
    speech_dispatch = user_input_dispatch.create_response.call_args[1]["speech"]
    assert "Energy Arbitrage Dispatch Executed" in speech_dispatch


