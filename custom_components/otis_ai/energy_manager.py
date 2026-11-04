"""Otis AI Companion: Energy & Predictive Load Orchestrator (Phase 7).

Coordinates energy monitoring, solar surplus utilization, battery/UPS storage tracking,
grid tariff awareness, dynamic load-shedding, and appliance sequencing across Home Assistant.
"""

from __future__ import annotations

from datetime import datetime
import logging
import math
import time
from typing import Any
import uuid

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# TOU Rate & Arbitrage Modes (Phase 2 Energy Arbitrage)
DEFAULT_TOU_RATES: dict[str, float] = {
    "off_peak": 0.08,  # $0.08 / kWh
    "shoulder": 0.15,  # $0.15 / kWh
    "peak": 0.35,      # $0.35 / kWh
}

MODE_AUTO = "auto"
MODE_SELF_CONSUMPTION = "self_consumption"
MODE_PEAK_ARBITRAGE = "peak_arbitrage"
MODE_BACKUP_RESERVE = "backup_reserve"
VALID_ARBITRAGE_MODES = {
    MODE_AUTO,
    MODE_SELF_CONSUMPTION,
    MODE_PEAK_ARBITRAGE,
    MODE_BACKUP_RESERVE,
}

ACTION_CHARGE_GRID = "charge_grid_offpeak"
ACTION_STORE_SOLAR = "store_solar_surplus"
ACTION_DISCHARGE_PEAK = "discharge_peak"
ACTION_DISCHARGE_EVENING = "discharge_evening"
ACTION_DISCHARGE_SELF_CONSUMPTION = "discharge_self_consumption"
ACTION_HOLD_RESERVE = "hold_reserve"
ACTION_IDLE = "idle"


class EnergyManager:
    """Manages energy topology discovery, live load telemetry, and dynamic load shedding."""

    def __init__(self, hass: HomeAssistant, spatial_manager=None) -> None:
        """Initialize the Energy Manager."""
        self.hass = hass
        self.spatial_manager = spatial_manager
        self._shed_history: list[dict[str, Any]] = []
        self._arbitrage_mode: str = MODE_AUTO
        self._cached_arbitrage_plan: dict[str, Any] | None = None
        self._battery_capacity_kwh: float = 13.5
        self._min_reserve_soc_pct: float = 20.0
        self._max_charge_kw: float = 5.0
        self._max_discharge_kw: float = 5.0
        self._custom_tou_rates: dict[str, float] = dict(DEFAULT_TOU_RATES)

    def get_tariff_window(self, dt: datetime | None = None) -> dict[str, Any]:
        """Calculate the current electrical tariff window (Peak, Shoulder, Off-Peak)."""
        now = dt or datetime.now()
        hour = now.hour
        is_weekend = now.weekday() >= 5  # Saturday=5, Sunday=6

        # Check if an external grid tariff sensor exists
        for tariff_entity in ("sensor.electricity_tariff", "sensor.grid_rate_period", "sensor.utility_meter_tariff"):
            state = self.hass.states.get(tariff_entity)
            if state and state.state not in ("unavailable", "unknown"):
                val = state.state.lower()
                return {
                    "period": val,
                    "is_peak": "peak" in val and "off" not in val,
                    "source": tariff_entity,
                    "peak_window_description": "Managed by external utility provider sensor",
                }

        # Standard default TOU (Time-Of-Use) Tariff Curve:
        # Weekdays: Peak (14:00 - 19:00 / 2pm-7pm), Shoulder (07:00 - 14:00 & 19:00 - 22:00), Off-Peak (22:00 - 07:00)
        # Weekends: Off-Peak all day
        if is_weekend:
            period = "off_peak"
            is_peak = False
            hours_until_change = (24 - hour) + 7  # Until Monday 07:00
        else:
            if 14 <= hour < 19:
                period = "peak"
                is_peak = True
                hours_until_change = 19 - hour
            elif (7 <= hour < 14) or (19 <= hour < 22):
                period = "shoulder"
                is_peak = False
                hours_until_change = 14 - hour if hour < 14 else 22 - hour
            else:
                period = "off_peak"
                is_peak = False
                hours_until_change = (7 - hour) if hour < 7 else (24 - hour + 7)

        return {
            "period": period,
            "is_peak": is_peak,
            "peak_window_description": "Weekdays 2:00 PM – 7:00 PM",
            "hours_until_change": hours_until_change,
            "source": "otis_tou_curve",
        }

    async def async_discover_energy_topology(self) -> dict[str, Any]:
        """Discover power sensors, energy meters, solar inverters, batteries, and sheddable loads."""
        power_sensors: list[dict[str, Any]] = []
        energy_sensors: list[dict[str, Any]] = []
        solar_sensors: list[dict[str, Any]] = []
        battery_sensors: list[dict[str, Any]] = []
        sheddable_loads: list[dict[str, Any]] = []

        all_states = self.hass.states.async_all()

        for st in all_states:
            eid = st.entity_id
            domain = eid.split(".")[0]
            attrs = st.attributes or {}
            unit = str(attrs.get("unit_of_measurement") or "")
            device_class = str(attrs.get("device_class") or "")
            friendly_name = attrs.get("friendly_name") or eid

            # 1. Power sensors (Watts / kW)
            if (
                device_class == "power"
                or unit in ("W", "kW", "VA")
                or (domain == "sensor" and eid.endswith("_power") and unit not in ("%", "V", "A"))
            ):
                try:
                    val = float(st.state) if st.state not in ("unavailable", "unknown", "None") else 0.0
                    if unit == "kW":
                        val *= 1000.0
                except (ValueError, TypeError):
                    val = 0.0

                power_sensors.append({
                    "entity_id": eid,
                    "name": friendly_name,
                    "power_w": round(val, 1),
                    "unit": unit or "W",
                    "state": st.state,
                })

            # 2. Cumulative Energy sensors (Wh / kWh)
            elif (
                device_class == "energy"
                or unit in ("kWh", "Wh", "MWh")
                or (domain == "sensor" and eid.endswith("_energy") and unit != "W")
            ):
                energy_sensors.append({
                    "entity_id": eid,
                    "name": friendly_name,
                    "unit": unit or "kWh",
                    "state": st.state,
                })

            # 3. Solar / Inverter Generation
            if any(k in eid for k in ("solar", "inverter", "photovoltaic", "pv_generation")):
                solar_sensors.append({
                    "entity_id": eid,
                    "name": friendly_name,
                    "state": st.state,
                    "unit": unit,
                })

            # 4. Battery & UPS Storage
            if (
                device_class == "battery"
                or "ups_theater" in eid
                or (domain == "sensor" and eid.endswith(("_battery_charge", "_battery_level", "_battery")))
            ):
                battery_sensors.append({
                    "entity_id": eid,
                    "name": friendly_name,
                    "state": st.state,
                    "unit": unit or "%",
                })

            # 5. Sheddable High-Draw Loads & Deferrable Consumers
            if domain in ("switch", "climate", "water_heater", "number", "select"):
                eid_lower = eid.lower()
                name_lower = friendly_name.lower()

                # Critical appliances that must NOT be shed
                if any(c in eid_lower for c in ("fridge", "refrigerator", "freezer", "alarm", "network", "router", "core")):
                    continue

                # Tier 1 Deferrable: EV charging, pool pumps, heaters, phone chargers
                if any(t in eid_lower or t in name_lower for t in (
                    "pool", "pump", "rivian", "charger", "ev_", "water_heater", "hottub", "spa", "phone_charger"
                )):
                    sheddable_loads.append({
                        "entity_id": eid,
                        "name": friendly_name,
                        "domain": domain,
                        "tier": 1,
                        "category": "deferrable_appliance",
                        "state": st.state,
                        "estimated_watts": 1500 if "pool" in eid_lower or "heater" in eid_lower else (7200 if "rivian" in eid_lower else 40),
                    })
                # Tier 2 Deferrable: AV matrix switches, secondary amplifiers, comfort climate
                elif any(t in eid_lower for t in ("amp_power", "processor_power", "subwoofer", "receiver", "projector")):
                    sheddable_loads.append({
                        "entity_id": eid,
                        "name": friendly_name,
                        "domain": domain,
                        "tier": 2,
                        "category": "entertainment_power",
                        "state": st.state,
                        "estimated_watts": 220,
                    })
                elif domain == "climate":
                    sheddable_loads.append({
                        "entity_id": eid,
                        "name": friendly_name,
                        "domain": domain,
                        "tier": 2,
                        "category": "hvac_setback",
                        "state": st.state,
                        "estimated_watts": 1200,
                    })

        return {
            "power_sensors": power_sensors,
            "energy_sensors": energy_sensors,
            "solar_sensors": solar_sensors,
            "battery_sensors": battery_sensors,
            "sheddable_loads": sheddable_loads,
        }

    async def async_get_energy_summary(self) -> dict[str, Any]:
        """Aggregate real-time power consumption, solar surplus, battery status, and load shedding readiness."""
        topo = await self.async_discover_energy_topology()
        tariff = self.get_tariff_window()

        # Calculate total current power from all positive active power sensors
        power_sensors = topo["power_sensors"]
        active_power_draws = [p for p in power_sensors if p["power_w"] > 0]
        total_current_power_w = round(sum(p["power_w"] for p in active_power_draws), 1)

        # Sort top consumers
        top_consumers = sorted(active_power_draws, key=lambda p: p["power_w"], reverse=True)[:10]

        # Check Solar Production & Elevation
        solar_elevation = None
        elevation_st = self.hass.states.get("sensor.sun_solar_elevation")
        if elevation_st and elevation_st.state not in ("unavailable", "unknown"):
            try:
                solar_elevation = round(float(elevation_st.state), 1)
            except ValueError:
                pass

        solar_watts = 0.0
        for s in topo["solar_sensors"]:
            if s["unit"] in ("W", "kW") or "power" in s["entity_id"]:
                try:
                    w = float(s["state"])
                    if s["unit"] == "kW":
                        w *= 1000.0
                    solar_watts += w
                except (ValueError, TypeError):
                    pass

        # Check UPS & Battery Status
        ups_data: dict[str, Any] = {}
        for b in topo["battery_sensors"]:
            if "ups_theater" in b["entity_id"]:
                key = b["entity_id"].replace("sensor.ups_theater_", "")
                ups_data[key] = b["state"]

        # Calculate potential load shedding savings
        active_candidates = [
            load for load in topo["sheddable_loads"]
            if load["state"] in ("on", "heat", "cool", "auto")
        ]
        potential_savings_w = sum(load["estimated_watts"] for load in active_candidates)

        return {
            "total_power_w": total_current_power_w,
            "active_power_sensors_count": len(active_power_draws),
            "top_consumers": top_consumers,
            "tariff": tariff,
            "solar": {
                "production_w": round(solar_watts, 1),
                "solar_elevation_deg": solar_elevation,
                "has_surplus": solar_watts > total_current_power_w if solar_watts > 0 else False,
            },
            "ups_storage": ups_data,
            "load_shedding": {
                "active_shed_records": len(self._shed_history),
                "active_sheddable_loads_count": len(active_candidates),
                "potential_savings_w": potential_savings_w,
                "candidates": active_candidates[:8],
            },
            "timestamp": datetime.now().isoformat(),
        }

    async def async_execute_load_shed(
        self,
        tier: int = 1,
        target_watts: float = 0,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Shed deferrable loads to reduce electrical draw during peak tariffs or grid constraints."""
        topo = await self.async_discover_energy_topology()
        candidates = [
            load for load in topo["sheddable_loads"]
            if load["tier"] <= tier and load["state"] in ("on", "heat", "cool", "auto")
        ]

        if not candidates:
            return {
                "success": True,
                "shed_count": 0,
                "estimated_watts_saved": 0,
                "message": "No active sheddable loads discovered matching criteria.",
                "dry_run": dry_run,
            }

        plan: list[dict[str, Any]] = []
        accumulated_watts = 0.0

        for candidate in candidates:
            plan.append(candidate)
            accumulated_watts += candidate["estimated_watts"]
            if target_watts > 0 and accumulated_watts >= target_watts:
                break

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "planned_shed_count": len(plan),
                "estimated_watts_saved": accumulated_watts,
                "plan": plan,
            }

        # Snapshot and execute load shed
        record_id = f"shed_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        snapshots: dict[str, Any] = {}
        executed: list[str] = []

        for item in plan:
            eid = item["entity_id"]
            current_state = self.hass.states.get(eid)
            if not current_state:
                continue

            snapshots[eid] = {
                "state": current_state.state,
                "attributes": dict(current_state.attributes),
                "domain": item["domain"],
            }

            try:
                if item["domain"] == "switch":
                    await self.hass.services.async_call("switch", "turn_off", {"entity_id": eid}, blocking=True)
                    executed.append(eid)
                elif item["domain"] == "climate":
                    # For HVAC, set back setpoint rather than turning off completely
                    hvac_mode = current_state.state
                    target_temp = current_state.attributes.get("temperature", 70)
                    new_temp = target_temp - 3 if hvac_mode == "heat" else target_temp + 3
                    await self.hass.services.async_call(
                        "climate",
                        "set_temperature",
                        {"entity_id": eid, "temperature": new_temp},
                        blocking=True,
                    )
                    executed.append(eid)
            except Exception as err:
                _LOGGER.warning("Failed to shed load '%s': %s", eid, err)

        record = {
            "record_id": record_id,
            "timestamp": datetime.now().isoformat(),
            "tier": tier,
            "snapshots": snapshots,
            "executed_entities": executed,
            "estimated_watts_saved": accumulated_watts,
            "status": "active",
        }
        self._shed_history.append(record)

        return {
            "success": True,
            "record_id": record_id,
            "shed_count": len(executed),
            "estimated_watts_saved": accumulated_watts,
            "executed_entities": executed,
            "message": f"Successfully shed {len(executed)} loads saving ~{round(accumulated_watts)}W during peak period.",
        }

    async def async_restore_shed_loads(self, record_id: str | None = None) -> dict[str, Any]:
        """Restore shedded loads to their prior snapshot state when peak rate period expires."""
        if not self._shed_history:
            return {
                "success": False,
                "error": "No active load shedding records available to restore.",
            }

        target_record = None
        if record_id:
            for r in self._shed_history:
                if r["record_id"] == record_id:
                    target_record = r
                    break
        else:
            # Pick latest active record
            for r in reversed(self._shed_history):
                if r.get("status") == "active":
                    target_record = r
                    break

        if not target_record:
            return {
                "success": False,
                "error": f"No active load shedding record found matching '{record_id or 'latest'}'.",
            }

        restored_count = 0
        snapshots = target_record.get("snapshots", {})

        for eid, snap in snapshots.items():
            domain = snap.get("domain", eid.split(".")[0])
            prior_state = snap.get("state")
            prior_attrs = snap.get("attributes", {})

            try:
                if domain == "switch" and prior_state == "on":
                    await self.hass.services.async_call("switch", "turn_on", {"entity_id": eid}, blocking=True)
                    restored_count += 1
                elif domain == "climate":
                    target_temp = prior_attrs.get("temperature")
                    if target_temp:
                        await self.hass.services.async_call(
                            "climate",
                            "set_temperature",
                            {"entity_id": eid, "temperature": target_temp},
                            blocking=True,
                        )
                        restored_count += 1
            except Exception as err:
                _LOGGER.warning("Failed to restore load '%s': %s", eid, err)

        target_record["status"] = "restored"
        target_record["restored_at"] = datetime.now().isoformat()

        return {
            "success": True,
            "record_id": target_record["record_id"],
            "restored_count": restored_count,
            "message": f"Restored {restored_count} load(s) back to standard operation.",
        }

    def get_shed_history(self) -> list[dict[str, Any]]:
        """Return the history of load shedding events."""
        return list(self._shed_history)

    def set_arbitrage_mode(self, mode: str) -> bool:
        """Update active battery arbitrage mode."""
        if mode in VALID_ARBITRAGE_MODES:
            self._arbitrage_mode = mode
            return True
        return False

    def get_arbitrage_mode(self) -> str:
        """Get active battery arbitrage mode."""
        return self._arbitrage_mode

    def set_tou_rates(self, rates: dict[str, float]) -> None:
        """Update custom TOU rates."""
        for k in ("off_peak", "shoulder", "peak"):
            if k in rates and isinstance(rates[k], (int, float)) and rates[k] >= 0:
                self._custom_tou_rates[k] = float(rates[k])

    def get_tou_rates(self) -> dict[str, float]:
        """Return configured TOU electricity rates."""
        return dict(self._custom_tou_rates)

    def estimate_solar_production_profile(
        self, daily_forecast_kwh: float = 24.0, current_solar_w: float = 0.0
    ) -> list[float]:
        """Generate 24 hourly solar generation estimates (kWh) from daily forecast using an astronomical bell curve."""
        if daily_forecast_kwh <= 0:
            return [0.0] * 24

        raw_weights = [0.0] * 24
        # Daytime solar generation curve between 06:00 and 19:00 with peak at 12:30
        for h in range(6, 20):
            frac = (h + 0.5 - 6) / 14.0
            raw_weights[h] = max(0.0, math.sin(frac * math.pi))

        total_weight = sum(raw_weights)
        if total_weight > 0:
            profile = [round((w / total_weight) * daily_forecast_kwh, 3) for w in raw_weights]
        else:
            profile = [0.0] * 24
        return profile

    def estimate_household_consumption_profile(
        self, baseline_kw: float = 0.9
    ) -> list[float]:
        """Generate 24 hourly household consumption estimates (kWh) based on empirical residential patterns."""
        base = max(0.2, baseline_kw)
        # Residential load shape: morning bump, midday plateau, evening peak (cooking/HVAC/lighting), night drop
        multipliers = [
            0.55, 0.50, 0.48, 0.48, 0.52, 0.65,  # 00:00 - 05:00 (Night sleep)
            1.20, 1.55, 1.45, 1.10, 1.00, 1.00,  # 06:00 - 11:00 (Morning prep & breakfast)
            1.05, 1.15, 1.25, 1.35, 1.65, 2.05,  # 12:00 - 17:00 (Afternoon into dinner)
            2.15, 1.95, 1.60, 1.25, 0.90, 0.65,  # 18:00 - 23:00 (Evening peak into bedtime)
        ]
        avg_mult = sum(multipliers) / 24.0
        return [round((m / avg_mult) * base, 3) for m in multipliers]

    def calculate_arbitrage_schedule(
        self,
        current_soc_pct: float = 50.0,
        battery_capacity_kwh: float = 13.5,
        max_charge_kw: float = 5.0,
        max_discharge_kw: float = 5.0,
        min_reserve_soc_pct: float = 20.0,
        mode: str = MODE_AUTO,
        custom_rates: dict[str, float] | None = None,
        daily_solar_kwh: float = 24.0,
        baseline_load_kw: float = 1.0,
        start_dt: datetime | None = None,
    ) -> dict[str, Any]:
        """Simulate and generate an optimal 24-hour battery charge/discharge schedule."""
        now = start_dt or datetime.now()
        start_hour = now.hour
        is_weekend = now.weekday() >= 5
        rates = dict(custom_rates or self._custom_tou_rates)

        cap = max(1.0, battery_capacity_kwh)
        soc = max(0.0, min(100.0, current_soc_pct))
        reserve = max(0.0, min(100.0, min_reserve_soc_pct))
        if mode == MODE_BACKUP_RESERVE:
            reserve = 100.0

        solar_profile = self.estimate_solar_production_profile(daily_solar_kwh)
        load_profile = self.estimate_household_consumption_profile(baseline_load_kw)

        schedule: list[dict[str, Any]] = []
        unmanaged_cost_total = 0.0
        managed_cost_total = 0.0
        total_peak_shave_kwh = 0.0
        sim_soc = soc

        for step in range(24):
            sim_hour = (start_hour + step) % 24
            # Determine tariff period for sim_hour
            sim_is_weekend = is_weekend if (start_hour + step) < 24 else ((now.weekday() + 1) % 7 >= 5)
            if sim_is_weekend:
                period = "off_peak"
            else:
                if 14 <= sim_hour < 19:
                    period = "peak"
                elif (7 <= sim_hour < 14) or (19 <= sim_hour < 22):
                    period = "shoulder"
                else:
                    period = "off_peak"

            rate = rates.get(period, 0.15)
            solar_kwh = solar_profile[sim_hour]
            load_kwh = load_profile[sim_hour]
            net_surplus = round(solar_kwh - load_kwh, 3)

            # Baseline unmanaged exchange without battery
            if net_surplus < 0:
                unmanaged_cost_total += abs(net_surplus) * rate
            else:
                unmanaged_cost_total -= net_surplus * 0.04  # wholesale export credit

            # Battery Arbitrage Decision Engine
            battery_flow_kwh = 0.0
            action = ACTION_IDLE
            reason = ""

            headroom_kwh = max(0.0, ((100.0 - sim_soc) / 100.0) * cap)
            available_discharge_kwh = max(0.0, ((sim_soc - reserve) / 100.0) * cap)

            if mode == MODE_BACKUP_RESERVE:
                # Top up battery to 100% and keep it full
                if headroom_kwh > 0.05:
                    if net_surplus > 0:
                        charge = min(net_surplus, max_charge_kw, headroom_kwh)
                        action = ACTION_STORE_SOLAR
                        battery_flow_kwh = charge
                        reason = "Absorb solar generation to reach full emergency backup reserve."
                    elif period == "off_peak":
                        charge = min(max_charge_kw, headroom_kwh)
                        action = ACTION_CHARGE_GRID
                        battery_flow_kwh = charge
                        reason = "Top up battery from low-cost grid to achieve 100% outage protection."
                    else:
                        action = ACTION_HOLD_RESERVE
                        reason = "Preserve maximum stored energy for emergency grid resilience."
                else:
                    action = ACTION_HOLD_RESERVE
                    reason = "Battery is 100% full; holding reserve for potential grid outage."

            elif mode == MODE_SELF_CONSUMPTION:
                if net_surplus > 0 and headroom_kwh > 0.05:
                    charge = min(net_surplus, max_charge_kw, headroom_kwh)
                    action = ACTION_STORE_SOLAR
                    battery_flow_kwh = charge
                    reason = "Store daytime solar generation on-site to minimize later grid dependency."
                elif net_surplus < 0 and available_discharge_kwh > 0.05:
                    discharge = min(abs(net_surplus), max_discharge_kw, available_discharge_kwh)
                    action = ACTION_DISCHARGE_PEAK if period == "peak" else ACTION_DISCHARGE_SELF_CONSUMPTION
                    battery_flow_kwh = -discharge
                    reason = "Discharge stored solar energy to cover household deficit."
                else:
                    action = ACTION_HOLD_RESERVE if sim_soc <= reserve else ACTION_IDLE
                    reason = "No surplus solar available and reserve floor reached."

            else:  # MODE_AUTO or MODE_PEAK_ARBITRAGE
                if period == "peak":
                    # In peak hours, discharge battery to eliminate high-rate grid purchases
                    if net_surplus < 0 and available_discharge_kwh > 0.05:
                        discharge = min(abs(net_surplus), max_discharge_kw, available_discharge_kwh)
                        action = ACTION_DISCHARGE_PEAK
                        battery_flow_kwh = -discharge
                        total_peak_shave_kwh += discharge
                        reason = f"Discharge at peak rate (${rate:.2f}/kWh) to eliminate expensive grid import."
                    elif net_surplus > 0 and headroom_kwh > 0.05:
                        charge = min(net_surplus, max_charge_kw, headroom_kwh)
                        action = ACTION_STORE_SOLAR
                        battery_flow_kwh = charge
                        reason = "Absorb surplus solar during peak rate window."
                    else:
                        action = ACTION_HOLD_RESERVE
                        reason = "Holding reserve floor during peak rate window."

                elif period == "off_peak":
                    # Pre-charge battery during cheap off-peak hours if tomorrow's solar is insufficient or SoC is low
                    precharge_target_soc = 85.0 if daily_solar_kwh < 20.0 else 65.0
                    target_headroom = max(0.0, ((precharge_target_soc - sim_soc) / 100.0) * cap)
                    if net_surplus > 0 and headroom_kwh > 0.05:
                        charge = min(net_surplus, max_charge_kw, headroom_kwh)
                        action = ACTION_STORE_SOLAR
                        battery_flow_kwh = charge
                        reason = "Capture off-peak solar generation."
                    elif sim_soc < precharge_target_soc and target_headroom > 0.05:
                        charge = min(max_charge_kw, target_headroom)
                        action = ACTION_CHARGE_GRID
                        battery_flow_kwh = charge
                        reason = f"Pre-charge from cheap grid (${rate:.2f}/kWh) before peak rates start."
                    else:
                        action = ACTION_IDLE
                        reason = f"SoC ({sim_soc:.0f}%) is optimized for upcoming peak tariff."

                else:  # shoulder
                    if net_surplus > 0 and headroom_kwh > 0.05:
                        charge = min(net_surplus, max_charge_kw, headroom_kwh)
                        action = ACTION_STORE_SOLAR
                        battery_flow_kwh = charge
                        reason = "Store surplus solar during shoulder window in anticipation of 2PM peak."
                    elif net_surplus < 0 and sim_hour >= 19 and available_discharge_kwh > 0.05:
                        # Post-peak evening shoulder: gently discharge remaining energy down to reserve
                        discharge = min(abs(net_surplus), max_discharge_kw * 0.6, available_discharge_kwh)
                        action = ACTION_DISCHARGE_EVENING
                        battery_flow_kwh = -discharge
                        reason = "Discharge residual energy to cover evening household consumption."
                    else:
                        action = ACTION_HOLD_RESERVE if sim_hour < 14 else ACTION_IDLE
                        reason = "Hold stored battery capacity for the high-cost peak period."

            # Update battery SoC for next hour
            delta_pct = (battery_flow_kwh / cap) * 100.0
            sim_soc = max(0.0, min(100.0, round(sim_soc + delta_pct, 1)))

            # Managed financial calculation
            net_grid_flow = load_kwh - solar_kwh + battery_flow_kwh
            if net_grid_flow > 0:
                managed_cost_total += net_grid_flow * rate
            else:
                managed_cost_total -= abs(net_grid_flow) * 0.04

            schedule.append({
                "step": step,
                "hour": sim_hour,
                "time_label": f"{sim_hour:02d}:00",
                "tariff_period": period,
                "rate_per_kwh": rate,
                "solar_kwh": solar_kwh,
                "load_kwh": load_kwh,
                "net_surplus_kwh": net_surplus,
                "action": action,
                "battery_flow_kw": round(battery_flow_kwh, 2),
                "ending_soc_pct": sim_soc,
                "reason": reason,
            })

        projected_savings = max(0.0, round(unmanaged_cost_total - managed_cost_total, 2))
        current_step = schedule[0]

        return {
            "mode": mode,
            "current_soc_pct": round(soc, 1),
            "battery_capacity_kwh": cap,
            "min_reserve_soc_pct": reserve,
            "daily_solar_forecast_kwh": round(daily_solar_kwh, 1),
            "baseline_load_kw": baseline_load_kw,
            "projected_savings_usd": projected_savings,
            "projected_peak_shave_kwh": round(total_peak_shave_kwh, 2),
            "unmanaged_cost_usd": round(max(0.0, unmanaged_cost_total), 2),
            "managed_cost_usd": round(max(0.0, managed_cost_total), 2),
            "current_action": current_step["action"],
            "current_reason": current_step["reason"],
            "current_battery_flow_kw": current_step["battery_flow_kw"],
            "schedule": schedule,
            "timestamp": now.isoformat(),
        }

    async def async_get_arbitrage_plan(
        self,
        battery_entity: str | None = None,
        mode: str | None = None,
        battery_capacity_kwh: float | None = None,
        min_reserve_soc_pct: float | None = None,
        custom_rates: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Discover live battery state, solar forecasts, and household load to produce a real-time arbitrage plan."""
        topo = await self.async_discover_energy_topology()
        chosen_mode = mode or self._arbitrage_mode

        # 1. Resolve current battery State of Charge
        soc = 50.0
        if battery_entity:
            st = self.hass.states.get(battery_entity)
            if st and st.state not in ("unavailable", "unknown"):
                try:
                    soc = float(st.state)
                except (ValueError, TypeError):
                    pass
        else:
            # Check topology battery sensors
            for b in topo.get("battery_sensors", []):
                eid = b["entity_id"]
                if any(k in eid for k in ("powerwall", "enphase", "solar_battery", "home_battery", "ups")):
                    try:
                        soc = float(b["state"])
                        break
                    except (ValueError, TypeError):
                        pass

        # 2. Resolve daily solar forecast
        solar_forecast_kwh = 24.0
        for s_eid in (
            "sensor.energy_production_today",
            "sensor.solar_forecast_today",
            "sensor.forecast_solar_energy_today",
            "sensor.solcast_pv_forecast_today",
        ):
            st = self.hass.states.get(s_eid)
            if st and st.state not in ("unavailable", "unknown"):
                try:
                    solar_forecast_kwh = float(st.state)
                    break
                except (ValueError, TypeError):
                    pass

        # 3. Resolve baseline household load in kW
        summary = await self.async_get_energy_summary()
        baseline_kw = round(max(0.5, summary["total_power_w"] / 1000.0), 2)

        plan = self.calculate_arbitrage_schedule(
            current_soc_pct=soc,
            battery_capacity_kwh=battery_capacity_kwh or self._battery_capacity_kwh,
            max_charge_kw=self._max_charge_kw,
            max_discharge_kw=self._max_discharge_kw,
            min_reserve_soc_pct=min_reserve_soc_pct or self._min_reserve_soc_pct,
            mode=chosen_mode,
            custom_rates=custom_rates,
            daily_solar_kwh=solar_forecast_kwh,
            baseline_load_kw=baseline_kw,
        )

        self._cached_arbitrage_plan = plan
        return plan

