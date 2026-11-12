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
from homeassistant.util import dt as dt_util

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
ACTION_EV_SOLAR_CHARGE = "smart_ev_solar_charge"
ACTION_EV_OFFPEAK_CHARGE = "smart_ev_offpeak_charge"
ACTION_EV_PAUSE_PEAK = "ev_charge_pause_peak"

DEFAULT_EV_TARGET_SOC_PCT = 80.0
DEFAULT_EV_CAPACITY_KWH = 77.0
DEFAULT_EV_MAX_CHARGE_KW = 9.6
DEFAULT_EV_DEPARTURE_HOUR = 7  # 07:00 AM


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
        # Smart EV configuration defaults
        self._ev_target_soc_pct: float = DEFAULT_EV_TARGET_SOC_PCT
        self._ev_battery_capacity_kwh: float = DEFAULT_EV_CAPACITY_KWH
        self._ev_max_charge_kw: float = DEFAULT_EV_MAX_CHARGE_KW
        self._ev_departure_hour: int = DEFAULT_EV_DEPARTURE_HOUR
        self._ev_prefer_solar: bool = True
        self._cached_ev_plan: dict[str, Any] | None = None

    def get_tariff_window(self, dt: datetime | None = None) -> dict[str, Any]:
        """Calculate the current electrical tariff window (Peak, Shoulder, Off-Peak)."""
        now = dt or datetime.now()
        hour = now.hour
        is_weekend = now.weekday() >= 5  # Saturday=5, Sunday=6

        # Check if an external grid tariff sensor exists
        if hasattr(self.hass, "states") and hasattr(self.hass.states, "async_all"):
            for state in self.hass.states.async_all("sensor"):
                if state.state not in ("unavailable", "unknown") and any(k in state.entity_id for k in ("tariff", "rate_period", "electricity_rate")):
                    val = state.state.lower()
                    return {
                        "period": val,
                        "is_peak": "peak" in val and "off" not in val,
                        "source": state.entity_id,
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

    def get_hourly_tariffs(
        self,
        start_dt: datetime | None = None,
        custom_rates: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Compute 24 hourly tariff rates and periods using dynamic sensors or TOU curve."""
        now = start_dt or datetime.now()
        start_hour = now.hour
        is_weekend = now.weekday() >= 5
        rates = dict(custom_rates or self._custom_tou_rates)

        # 1. Attempt to discover dynamic spot price sensors
        dynamic_hourly_rates: dict[int, float] = {}
        found_dynamic = False

        if hasattr(self.hass, "states") and hasattr(self.hass.states, "async_all"):
            for st in self.hass.states.async_all("sensor"):
                if st.state not in ("unavailable", "unknown") and any(k in st.entity_id for k in ("price", "spot", "tariff", "nordpool", "tibber", "amber", "electricity")):
                    attrs = st.attributes or {}
                    raw_prices = attrs.get("raw_today") or attrs.get("prices") or attrs.get("today")
                    if isinstance(raw_prices, list) and len(raw_prices) >= 24:
                        try:
                            for idx, p in enumerate(raw_prices[:24]):
                                if isinstance(p, dict):
                                    val = float(p.get("value", p.get("price", 0.15)))
                                else:
                                    val = float(p)
                                dynamic_hourly_rates[idx] = round(val, 4)
                            found_dynamic = True
                            break
                        except (ValueError, TypeError):
                            pass

        avg_rate = (
            sum(dynamic_hourly_rates.values()) / len(dynamic_hourly_rates)
            if found_dynamic and dynamic_hourly_rates
            else rates.get("shoulder", 0.15)
        )

        schedule: list[dict[str, Any]] = []
        for step in range(24):
            sim_hour = (start_hour + step) % 24
            sim_is_weekend = is_weekend if (start_hour + step) < 24 else ((now.weekday() + 1) % 7 >= 5)

            if found_dynamic and sim_hour in dynamic_hourly_rates:
                rate = dynamic_hourly_rates[sim_hour]
                if rate < 0:
                    period = "negative"
                    is_peak = False
                elif rate >= avg_rate * 1.35:
                    period = "peak"
                    is_peak = True
                elif rate <= avg_rate * 0.75:
                    period = "off_peak"
                    is_peak = False
                else:
                    period = "shoulder"
                    is_peak = False
            else:
                if sim_is_weekend:
                    period = "off_peak"
                    is_peak = False
                else:
                    if 14 <= sim_hour < 19:
                        period = "peak"
                        is_peak = True
                    elif (7 <= sim_hour < 14) or (19 <= sim_hour < 22):
                        period = "shoulder"
                        is_peak = False
                    else:
                        period = "off_peak"
                        is_peak = False
                rate = rates.get(period, 0.15)

            schedule.append({
                "step": step,
                "hour": sim_hour,
                "time_label": f"{sim_hour:02d}:00",
                "period": period,
                "rate_per_kwh": rate,
                "is_peak": is_peak,
                "is_negative": rate < 0,
            })

        return schedule

    def get_hourly_solar_forecast(
        self,
        start_dt: datetime | None = None,
        daily_forecast_kwh: float = 24.0,
    ) -> list[dict[str, Any]]:
        """Compile a 24-hour solar generation forecast using detailed attributes or astronomical profile."""
        now = start_dt or datetime.now()
        start_hour = now.hour

        hourly_values: dict[int, float] = {}
        source = "astronomical_bell_curve"

        solar_candidates = []
        if hasattr(self.hass, "states") and hasattr(self.hass.states, "async_all"):
            try:
                solar_candidates = [
                    s for s in self.hass.states.async_all("sensor")
                    if getattr(s, "state", None) not in ("unavailable", "unknown")
                    and any(k in getattr(s, "entity_id", "") for k in ("solar", "pv", "production", "energy"))
                ]
            except Exception:
                solar_candidates = []
        if not solar_candidates and hasattr(self.hass, "states") and hasattr(self.hass.states, "get"):
            for s_eid in (
                "sensor.forecast_solar_energy_today",
                "sensor.solar_forecast_today",
                "sensor.energy_production_today",
                "sensor.solcast_pv_forecast_today",
            ):
                st = self.hass.states.get(s_eid)
                if st and getattr(st, "state", None) not in ("unavailable", "unknown"):
                    solar_candidates.append(st)
        for st in solar_candidates:

            attrs = st.attributes or {}
            detailed = attrs.get("detailed_forecast") or attrs.get("forecast") or attrs.get("detailedHourly")
            if isinstance(detailed, list) and detailed:
                try:
                    for entry in detailed:
                        if isinstance(entry, dict):
                            dt_str = entry.get("datetime") or entry.get("period_start")
                            val = float(entry.get("pv_estimate", entry.get("value", entry.get("watts", 0))))
                            if dt_str:
                                if "T" in dt_str:
                                    h = int(dt_str.split("T")[1][:2])
                                elif " " in dt_str:
                                    h = int(dt_str.split(" ")[1][:2])
                                else:
                                    h = 0
                                if val > 100:
                                    val = val / 1000.0
                                hourly_values[h] = round(val, 3)
                    if hourly_values:
                        source = f"provider_telemetry_{st.entity_id}"
                        break
                except (ValueError, TypeError):
                    pass

        if not hourly_values:
            bell_curve = self.estimate_solar_production_profile(daily_forecast_kwh)
            for h in range(24):
                hourly_values[h] = bell_curve[h]

        schedule: list[dict[str, Any]] = []
        for step in range(24):
            sim_hour = (start_hour + step) % 24
            val = hourly_values.get(sim_hour, 0.0)
            schedule.append({
                "step": step,
                "hour": sim_hour,
                "time_label": f"{sim_hour:02d}:00",
                "solar_kwh": val,
                "source": source,
            })

        return schedule

    async def async_discover_energy_topology(self) -> dict[str, Any]:
        """Discover power sensors, energy meters, solar inverters, batteries, and sheddable loads."""
        power_sensors: list[dict[str, Any]] = []
        energy_sensors: list[dict[str, Any]] = []
        solar_sensors: list[dict[str, Any]] = []
        battery_sensors: list[dict[str, Any]] = []
        sheddable_loads: list[dict[str, Any]] = []
        ev_chargers: list[dict[str, Any]] = []
        ev_vehicles: list[dict[str, Any]] = []

        all_states = self.hass.states.async_all()

        for st in all_states:
            eid = st.entity_id
            domain = eid.split(".")[0]
            attrs = st.attributes or {}
            unit = str(attrs.get("unit_of_measurement") or "")
            device_class = str(attrs.get("device_class") or "")
            friendly_name = attrs.get("friendly_name") or eid
            eid_lower = eid.lower()
            name_lower = friendly_name.lower()

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
            if any(k in eid_lower for k in ("solar", "inverter", "photovoltaic", "pv_generation")):
                solar_sensors.append({
                    "entity_id": eid,
                    "name": friendly_name,
                    "state": st.state,
                    "unit": unit,
                })

            # 4. Battery & UPS Storage
            if (
                device_class == "battery"
                or "ups" in eid_lower
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
                # Critical appliances that must NOT be shed
                if any(c in eid_lower for c in ("fridge", "refrigerator", "freezer", "alarm", "network", "router", "core")):
                    pass
                elif any(t in eid_lower or t in name_lower for t in (
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

            # Exclude personal/mobile devices, wearables, computers, and Bluetooth beacons from EV detection
            is_personal_or_mobile = any(
                p in eid_lower or p in name_lower
                for p in (
                    "phone", "watch", "tablet", "mobile", "wearos", "chromebook",
                    "laptop", "macbook", "ipad", "iphone", "android", "pixel",
                    "ibeacon", "beacon", "key_", "plug", "led", "auto_update", "auto_off",
                    "signal_strength", "signal_level", "headphone", "earbud", "dock",
                    "connector_type", "charger_type", "vendor",
                )
            )

            # 6. EV Chargers & EVSE Infrastructure (Dedicated EV chargers only)
            if not is_personal_or_mobile and any(
                k in eid_lower or k in name_lower
                for k in (
                    "evse", "wallbox", "easee", "zaptec", "chargepoint",
                    "tesla_wall_connector", "juicebox", "grizzl_e", "ocpp",
                    "ev_charger", "car_charger", "wall_charger", "rivian_charger", "tesla_charger",
                )
            ):
                if domain == "switch":
                    ev_chargers.append({
                        "entity_id": eid,
                        "name": friendly_name,
                        "type": "charger_switch",
                        "state": st.state,
                    })
                elif domain in ("number", "select") and any(a in eid_lower for a in ("amperage", "current", "rate", "limit")):
                    ev_chargers.append({
                        "entity_id": eid,
                        "name": friendly_name,
                        "type": "charge_rate_selector",
                        "state": st.state,
                    })
                elif domain == "sensor" and any(p in eid_lower for p in ("power", "energy", "voltage", "current")):
                    ev_chargers.append({
                        "entity_id": eid,
                        "name": friendly_name,
                        "type": "charger_telemetry",
                        "state": st.state,
                        "unit": unit,
                    })

            # 7. Connected Electric Vehicles
            if not is_personal_or_mobile and any(
                b in eid_lower or b in name_lower
                for b in ("rivian", "tesla", "model_3", "model_y", "model_s", "model_x", "ioniq", "mach_e", "polestar", "ev_battery")
            ):
                if domain == "sensor" and (device_class == "battery" or "battery" in eid_lower or "soc" in eid_lower or "battery_level" in eid_lower):
                    try:
                        ev_soc = float(st.state) if st.state not in ("unavailable", "unknown") else 0.0
                    except (ValueError, TypeError):
                        ev_soc = 0.0
                    ev_vehicles.append({
                        "entity_id": eid,
                        "name": friendly_name,
                        "type": "battery_soc",
                        "soc_pct": ev_soc,
                        "state": st.state,
                    })
                elif domain in ("number", "slider") and "limit" in eid_lower:
                    ev_vehicles.append({
                        "entity_id": eid,
                        "name": friendly_name,
                        "type": "charge_limit",
                        "state": st.state,
                    })

        return {
            "power_sensors": power_sensors,
            "energy_sensors": energy_sensors,
            "solar_sensors": solar_sensors,
            "battery_sensors": battery_sensors,
            "sheddable_loads": sheddable_loads,
            "ev_chargers": ev_chargers,
            "ev_vehicles": ev_vehicles,
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
        solar_azimuth = None
        sun_st = self.hass.states.get("sun.sun") if hasattr(self.hass, "states") and hasattr(self.hass.states, "get") else None
        if sun_st and getattr(sun_st, "attributes", None):
            attrs = sun_st.attributes or {}
            if "elevation" in attrs:
                try:
                    solar_elevation = round(float(attrs["elevation"]), 1)
                except (ValueError, TypeError):
                    pass
            if "azimuth" in attrs:
                try:
                    solar_azimuth = round(float(attrs["azimuth"]), 1)
                except (ValueError, TypeError):
                    pass
        if solar_elevation is None and hasattr(self.hass, "states") and hasattr(self.hass.states, "async_all"):
            for s in self.hass.states.async_all("sensor"):
                if "solar_elevation" in s.entity_id and s.state not in ("unavailable", "unknown"):
                    try:
                        solar_elevation = round(float(s.state), 1)
                        break
                    except (ValueError, TypeError):
                        pass

        if solar_elevation is None:
            # Fallback approximation from time of day (peaks at ~60° around 13:00)
            now = dt_util.utcnow()
            hour_float = now.hour + now.minute / 60.0
            rad = (hour_float - 13.0) * (math.pi / 12.0)
            solar_elevation = round(60.0 * math.cos(rad), 1)

        solar_watts = 0.0
        has_solar_system = len(topo.get("solar_sensors", [])) > 0
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
            raw_eid = b["entity_id"].lower()
            if "ups" in raw_eid or "battery" in raw_eid:
                clean_key = (
                    b["entity_id"]
                    .split(".", 1)[-1]
                    .replace("ups_", "")
                    .replace("battery_", "")
                )
                ups_data[clean_key] = b["state"]

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
                "has_solar_system": has_solar_system,
                "production_w": round(solar_watts, 1) if has_solar_system else 0.0,
                "solar_elevation_deg": solar_elevation,
                "solar_azimuth_deg": solar_azimuth,
                "has_surplus": (solar_watts > total_current_power_w) if (has_solar_system and solar_watts > 0) else False,
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

    def calculate_ev_charging_schedule(
        self,
        current_soc_pct: float = 45.0,
        target_soc_pct: float = 80.0,
        battery_capacity_kwh: float = 77.0,
        max_charge_rate_kw: float = 9.6,
        target_departure_hour: int = 7,
        prefer_solar_surplus: bool = True,
        solar_profile: list[float] | None = None,
        load_profile: list[float] | None = None,
        tariff_schedule: list[dict[str, Any]] | None = None,
        start_dt: datetime | None = None,
    ) -> dict[str, Any]:
        """Compute an optimized 24-hour EV charging schedule balancing solar surplus and low-cost off-peak tariffs."""
        now = start_dt or datetime.now()
        start_hour = now.hour
        cap = max(10.0, battery_capacity_kwh)
        soc = max(0.0, min(100.0, current_soc_pct))
        target_soc = max(soc, min(100.0, target_soc_pct))
        max_kw = max(1.0, max_charge_rate_kw)

        energy_needed_kwh = max(0.0, round(((target_soc - soc) / 100.0) * cap, 2))
        hours_needed = math.ceil(energy_needed_kwh / max_kw) if energy_needed_kwh > 0 else 0

        if solar_profile is None:
            solar_profile = self.estimate_solar_production_profile(24.0)
        if load_profile is None:
            load_profile = self.estimate_household_consumption_profile(1.0)
        if tariff_schedule is None:
            tariff_schedule = self.get_hourly_tariffs(now)

        sim_soc = soc
        remaining_needed = energy_needed_kwh
        schedule: list[dict[str, Any]] = []
        total_solar_utilized_kwh = 0.0
        total_grid_utilized_kwh = 0.0
        total_ev_cost_usd = 0.0

        candidate_hours = []
        for step in range(24):
            sim_hour = (start_hour + step) % 24
            t_info = tariff_schedule[step]
            solar_kwh = solar_profile[sim_hour]
            load_kwh = load_profile[sim_hour]
            net_surplus = max(0.0, round(solar_kwh - load_kwh, 3))
            is_before_departure = step < ((target_departure_hour - start_hour) % 24 or 24)
            candidate_hours.append({
                "step": step,
                "hour": sim_hour,
                "rate": t_info["rate_per_kwh"],
                "period": t_info["period"],
                "net_surplus": net_surplus,
                "is_before_departure": is_before_departure,
            })

        allocations: dict[int, dict[str, Any]] = {}

        # 1. Allocate solar surplus first if enabled
        if prefer_solar_surplus and remaining_needed > 0.05:
            for cand in candidate_hours:
                if remaining_needed <= 0.05:
                    break
                surplus = cand["net_surplus"]
                if surplus > 0.5:
                    charge_kw = min(surplus, max_kw, remaining_needed)
                    allocations[cand["step"]] = {
                        "charge_kw": round(charge_kw, 2),
                        "action": ACTION_EV_SOLAR_CHARGE,
                        "source": "solar",
                        "cost": 0.0,
                        "reason": f"Absorbing {round(charge_kw, 1)} kW excess solar generation.",
                    }
                    remaining_needed -= charge_kw
                    total_solar_utilized_kwh += charge_kw

        # 2. Allocate remaining energy to cheapest tariff hours before departure
        if remaining_needed > 0.05:
            pre_departure = [c for c in candidate_hours if c["step"] not in allocations and c["is_before_departure"]]
            pre_departure.sort(key=lambda x: (x["rate"], x["period"] == "peak"))

            for cand in pre_departure:
                if remaining_needed <= 0.05:
                    break
                if cand["period"] == "peak" and len(pre_departure) > hours_needed:
                    continue
                charge_kw = min(max_kw, remaining_needed)
                cost = charge_kw * cand["rate"]
                allocations[cand["step"]] = {
                    "charge_kw": round(charge_kw, 2),
                    "action": ACTION_EV_OFFPEAK_CHARGE,
                    "source": "grid",
                    "cost": cost,
                    "reason": f"Charging at low-cost tariff (${cand['rate']:.2f}/kWh) before departure.",
                }
                remaining_needed -= charge_kw
                total_grid_utilized_kwh += charge_kw
                total_ev_cost_usd += cost

        # Build final 24-hour step timeline
        for step in range(24):
            sim_hour = (start_hour + step) % 24
            t_info = tariff_schedule[step]
            alloc = allocations.get(step)

            if alloc:
                charge_kw = alloc["charge_kw"]
                action = alloc["action"]
                source = alloc["source"]
                reason = alloc["reason"]
                cost = alloc["cost"]
            else:
                charge_kw = 0.0
                if t_info["period"] == "peak":
                    action = ACTION_EV_PAUSE_PEAK
                    reason = "Charging paused to avoid high peak tariff."
                else:
                    action = ACTION_IDLE
                    reason = "Idle; target SoC reached or scheduled for later window."
                source = "none"
                cost = 0.0

            if charge_kw > 0:
                delta_soc = (charge_kw / cap) * 100.0
                sim_soc = min(100.0, round(sim_soc + delta_soc, 1))

            schedule.append({
                "step": step,
                "hour": sim_hour,
                "time_label": f"{sim_hour:02d}:00",
                "ev_charge_kw": round(charge_kw, 2),
                "action": action,
                "source": source,
                "cost_usd": round(cost, 2),
                "ending_soc_pct": sim_soc,
                "reason": reason,
            })

        current_step = schedule[0]
        return {
            "current_soc_pct": round(soc, 1),
            "target_soc_pct": round(target_soc, 1),
            "battery_capacity_kwh": cap,
            "energy_needed_kwh": energy_needed_kwh,
            "target_departure_hour": target_departure_hour,
            "hours_needed": hours_needed,
            "solar_kwh_utilized": round(total_solar_utilized_kwh, 2),
            "grid_kwh_utilized": round(total_grid_utilized_kwh, 2),
            "projected_cost_usd": round(total_ev_cost_usd, 2),
            "current_action": current_step["action"],
            "current_ev_charge_kw": current_step["ev_charge_kw"],
            "current_reason": current_step["reason"],
            "schedule": schedule,
            "timestamp": now.isoformat(),
        }

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
        ev_current_soc_pct: float = 45.0,
        ev_target_soc_pct: float = 80.0,
        ev_battery_capacity_kwh: float = 77.0,
        ev_max_charge_kw: float = 9.6,
        ev_departure_hour: int = 7,
        ev_prefer_solar: bool = True,
        solar_forecast_table: list[float] | None = None,
        has_ev: bool = True,
    ) -> dict[str, Any]:
        """Simulate and generate an optimal 24-hour battery charge/discharge & EV schedule."""
        now = start_dt or datetime.now()
        start_hour = now.hour
        rates = dict(custom_rates or self._custom_tou_rates)

        cap = max(1.0, battery_capacity_kwh)
        soc = max(0.0, min(100.0, current_soc_pct))
        reserve = max(0.0, min(100.0, min_reserve_soc_pct))
        if mode == MODE_BACKUP_RESERVE:
            reserve = 100.0

        tariff_schedule = self.get_hourly_tariffs(now, custom_rates=rates)
        if solar_forecast_table is not None and len(solar_forecast_table) == 24:
            solar_profile = list(solar_forecast_table)
        else:
            solar_profile = self.estimate_solar_production_profile(daily_solar_kwh)

        load_profile = self.estimate_household_consumption_profile(baseline_load_kw)

        # Smart EV Schedule Co-Optimization (only if EV is integrated)
        if has_ev:
            ev_schedule = self.calculate_ev_charging_schedule(
                current_soc_pct=ev_current_soc_pct,
                target_soc_pct=ev_target_soc_pct,
                battery_capacity_kwh=ev_battery_capacity_kwh,
                max_charge_rate_kw=ev_max_charge_kw,
                target_departure_hour=ev_departure_hour,
                prefer_solar_surplus=ev_prefer_solar,
                solar_profile=solar_profile,
                load_profile=load_profile,
                tariff_schedule=tariff_schedule,
                start_dt=now,
            )
        else:
            ev_schedule = None

        schedule: list[dict[str, Any]] = []
        unmanaged_cost_total = 0.0
        managed_cost_total = 0.0
        total_peak_shave_kwh = 0.0
        sim_soc = soc

        for step in range(24):
            sim_hour = (start_hour + step) % 24
            t_info = tariff_schedule[step]
            period = t_info["period"]
            rate = t_info["rate_per_kwh"]

            solar_kwh = solar_profile[sim_hour]
            load_kwh = load_profile[sim_hour]

            ev_step = ev_schedule["schedule"][step] if (ev_schedule and "schedule" in ev_schedule and step < len(ev_schedule["schedule"])) else {}
            ev_kw = ev_step.get("ev_charge_kw", 0.0)

            # Net surplus after basic household consumption
            net_surplus = round(solar_kwh - load_kwh, 3)

            # Available solar surplus for stationary battery after EV solar soak
            solar_available_for_battery = max(0.0, round(net_surplus - (ev_kw if ev_step.get("source") == "solar" else 0.0), 3))

            # Baseline unmanaged exchange without battery or smart orchestration
            unmanaged_net = load_kwh + ev_kw - solar_kwh
            if unmanaged_net > 0:
                unmanaged_cost_total += unmanaged_net * rate
            else:
                unmanaged_cost_total -= abs(unmanaged_net) * 0.04

            # Stationary Battery Arbitrage Decision Engine
            battery_flow_kwh = 0.0
            action = ACTION_IDLE
            reason = ""

            headroom_kwh = max(0.0, ((100.0 - sim_soc) / 100.0) * cap)
            available_discharge_kwh = max(0.0, ((sim_soc - reserve) / 100.0) * cap)

            if mode == MODE_BACKUP_RESERVE:
                if headroom_kwh > 0.05:
                    if solar_available_for_battery > 0:
                        charge = min(solar_available_for_battery, max_charge_kw, headroom_kwh)
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
                if solar_available_for_battery > 0 and headroom_kwh > 0.05:
                    charge = min(solar_available_for_battery, max_charge_kw, headroom_kwh)
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
                    if net_surplus < 0 and available_discharge_kwh > 0.05:
                        discharge = min(abs(net_surplus), max_discharge_kw, available_discharge_kwh)
                        action = ACTION_DISCHARGE_PEAK
                        battery_flow_kwh = -discharge
                        total_peak_shave_kwh += discharge
                        reason = f"Discharge at peak rate (${rate:.2f}/kWh) to eliminate expensive grid import."
                    elif solar_available_for_battery > 0 and headroom_kwh > 0.05:
                        charge = min(solar_available_for_battery, max_charge_kw, headroom_kwh)
                        action = ACTION_STORE_SOLAR
                        battery_flow_kwh = charge
                        reason = "Absorb surplus solar during peak rate window."
                    else:
                        action = ACTION_HOLD_RESERVE
                        reason = "Holding reserve floor during peak rate window."

                elif period == "off_peak":
                    precharge_target_soc = 85.0 if daily_solar_kwh < 20.0 else 65.0
                    target_headroom = max(0.0, ((precharge_target_soc - sim_soc) / 100.0) * cap)
                    if solar_available_for_battery > 0 and headroom_kwh > 0.05:
                        charge = min(solar_available_for_battery, max_charge_kw, headroom_kwh)
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
                    if solar_available_for_battery > 0 and headroom_kwh > 0.05:
                        charge = min(solar_available_for_battery, max_charge_kw, headroom_kwh)
                        action = ACTION_STORE_SOLAR
                        battery_flow_kwh = charge
                        reason = "Store surplus solar during shoulder window in anticipation of 2PM peak."
                    elif net_surplus < 0 and sim_hour >= 19 and available_discharge_kwh > 0.05:
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
            net_grid_flow = load_kwh + (ev_kw if ev_step.get("source") == "grid" else 0.0) - solar_kwh + battery_flow_kwh
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
                "ev_charge_kw": ev_kw,
                "ev_action": ev_step.get("action", ACTION_IDLE),
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
            "has_ev": bool(has_ev),
            "ev_charging_plan": ev_schedule,
            "schedule": schedule,
            "timestamp": now.isoformat(),
        }

    def publish_energy_arbitrage_telemetry(self, plan: dict[str, Any]) -> None:
        """Publish real-time telemetry to sensor.otis_energy_arbitrage."""
        if not plan:
            return
        state = plan.get("current_action", ACTION_IDLE)
        attrs = {
            "mode": plan.get("mode", MODE_AUTO),
            "current_soc_pct": plan.get("current_soc_pct", 50.0),
            "battery_capacity_kwh": plan.get("battery_capacity_kwh", 13.5),
            "min_reserve_soc_pct": plan.get("min_reserve_soc_pct", 20.0),
            "daily_solar_forecast_kwh": plan.get("daily_solar_forecast_kwh", 24.0),
            "baseline_load_kw": plan.get("baseline_load_kw", 1.0),
            "projected_savings_usd": plan.get("projected_savings_usd", 0.0),
            "projected_peak_shave_kwh": plan.get("projected_peak_shave_kwh", 0.0),
            "ev_charging": plan.get("ev_charging_plan", {}),
            "schedule_summary": plan.get("schedule", [])[:6],
            "last_updated": plan.get("timestamp", datetime.now().isoformat()),
        }
        try:
            from .sensor import async_update_entity_state
            async_update_entity_state(self.hass, "sensor.otis_energy_arbitrage", state, attrs)
        except Exception as err:
            _LOGGER.debug("Entity state update notice: %s", err)

    async def async_get_arbitrage_plan(
        self,
        battery_entity: str | None = None,
        mode: str | None = None,
        battery_capacity_kwh: float | None = None,
        min_reserve_soc_pct: float | None = None,
        custom_rates: dict[str, float] | None = None,
        ev_entity: str | None = None,
        ev_target_soc_pct: float | None = None,
        ev_departure_hour: int | None = None,
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
            for b in topo.get("battery_sensors", []):
                eid = b["entity_id"]
                if any(k in eid for k in ("powerwall", "enphase", "solar_battery", "home_battery", "ups")):
                    try:
                        soc = float(b["state"])
                        break
                    except (ValueError, TypeError):
                        pass

        # 2. Resolve daily solar forecast & hourly forecast table
        solar_forecast_kwh = 24.0
        if hasattr(self.hass, "states") and hasattr(self.hass.states, "async_all"):
            try:
                for st in self.hass.states.async_all("sensor"):
                    if (
                        any(k in getattr(st, "entity_id", "") for k in ("solar_forecast", "energy_production", "forecast_solar"))
                        and getattr(st, "state", None) not in ("unavailable", "unknown")
                    ):
                        try:
                            solar_forecast_kwh = float(st.state)
                            break
                        except (ValueError, TypeError):
                            pass
            except Exception:
                pass
        if solar_forecast_kwh == 24.0 and hasattr(self.hass, "states") and hasattr(self.hass.states, "get"):
            for s_eid in (
                "sensor.energy_production_today",
                "sensor.solar_forecast_today",
                "sensor.forecast_solar_energy_today",
                "sensor.solcast_pv_forecast_today",
            ):
                st = self.hass.states.get(s_eid)
                if st and getattr(st, "state", None) not in ("unavailable", "unknown"):
                    try:
                        solar_forecast_kwh = float(st.state)
                        break
                    except (ValueError, TypeError):
                        pass

        hourly_solar = self.get_hourly_solar_forecast(daily_forecast_kwh=solar_forecast_kwh)
        solar_table = [s["solar_kwh"] for s in hourly_solar]

        # 3. Resolve baseline household load in kW
        summary = await self.async_get_energy_summary()
        baseline_kw = round(max(0.5, summary["total_power_w"] / 1000.0), 2)

        # 4. Resolve EV SoC
        ev_soc = 45.0
        if ev_entity:
            st = self.hass.states.get(ev_entity)
            if st and st.state not in ("unavailable", "unknown"):
                try:
                    ev_soc = float(st.state)
                except (ValueError, TypeError):
                    pass
        else:
            for v in topo.get("ev_vehicles", []):
                if v.get("type") == "battery_soc":
                    ev_soc = float(v.get("soc_pct", 45.0))
                    break

        has_ev = bool(topo.get("ev_chargers") or topo.get("ev_vehicles"))

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
            ev_current_soc_pct=ev_soc,
            ev_target_soc_pct=ev_target_soc_pct if ev_target_soc_pct is not None else self._ev_target_soc_pct,
            ev_departure_hour=ev_departure_hour if ev_departure_hour is not None else self._ev_departure_hour,
            solar_forecast_table=solar_table,
            has_ev=has_ev,
        )

        self._cached_arbitrage_plan = plan
        self.publish_energy_arbitrage_telemetry(plan)
        return plan

    async def async_schedule_ev_charging(
        self,
        target_soc_pct: float | None = None,
        target_departure_time: str | None = None,
        battery_capacity_kwh: float | None = None,
        max_charge_rate_kw: float | None = None,
        prefer_solar_surplus: bool | None = None,
        ev_entity: str | None = None,
    ) -> dict[str, Any]:
        """Compute and return an optimized EV charging schedule based on live energy telemetry."""
        topo = await self.async_discover_energy_topology()

        soc = 45.0
        if ev_entity:
            st = self.hass.states.get(ev_entity)
            if st and st.state not in ("unavailable", "unknown"):
                try:
                    soc = float(st.state)
                except (ValueError, TypeError):
                    pass
        else:
            for v in topo.get("ev_vehicles", []):
                if v.get("type") == "battery_soc":
                    soc = float(v.get("soc_pct", 45.0))
                    break

        dep_hour = self._ev_departure_hour
        if target_departure_time:
            try:
                dep_hour = int(target_departure_time.split(":")[0])
            except (ValueError, IndexError):
                pass

        solar_forecast = self.get_hourly_solar_forecast()
        solar_profile = [s["solar_kwh"] for s in solar_forecast]

        summary = await self.async_get_energy_summary()
        baseline_kw = round(max(0.5, summary["total_power_w"] / 1000.0), 2)
        load_profile = self.estimate_household_consumption_profile(baseline_kw)

        tariff_schedule = self.get_hourly_tariffs()

        plan = self.calculate_ev_charging_schedule(
            current_soc_pct=soc,
            target_soc_pct=target_soc_pct if target_soc_pct is not None else self._ev_target_soc_pct,
            battery_capacity_kwh=battery_capacity_kwh if battery_capacity_kwh is not None else self._ev_battery_capacity_kwh,
            max_charge_rate_kw=max_charge_rate_kw if max_charge_rate_kw is not None else self._ev_max_charge_kw,
            target_departure_hour=dep_hour,
            prefer_solar_surplus=prefer_solar_surplus if prefer_solar_surplus is not None else self._ev_prefer_solar,
            solar_profile=solar_profile,
            load_profile=load_profile,
            tariff_schedule=tariff_schedule,
        )

        self._cached_ev_plan = plan
        return plan

    async def async_execute_energy_arbitrage(
        self,
        apply_ev_schedule: bool = True,
        apply_battery_mode: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Dispatch real-time load, EV charging, and storage commands based on current schedule action."""
        plan = await self.async_get_arbitrage_plan()
        ev_plan = plan.get("ev_charging_plan") or {}
        topo = await self.async_discover_energy_topology()

        current_action = plan.get("current_action", ACTION_IDLE)
        ev_action = ev_plan.get("current_action", ACTION_IDLE)
        ev_kw = ev_plan.get("current_ev_charge_kw", 0.0)

        dispatched_actions: list[dict[str, Any]] = []

        if apply_ev_schedule and topo.get("ev_chargers"):
            for charger in topo["ev_chargers"]:
                c_id = charger["entity_id"]
                c_type = charger.get("type")

                if c_type == "charger_switch":
                    if ev_action in (ACTION_EV_SOLAR_CHARGE, ACTION_EV_OFFPEAK_CHARGE):
                        dispatched_actions.append({
                            "entity_id": c_id,
                            "domain": "switch",
                            "service": "turn_on",
                            "action": ev_action,
                            "reason": ev_plan.get("current_reason", "Scheduled EV charging active"),
                        })
                        if not dry_run:
                            try:
                                await self.hass.services.async_call("switch", "turn_on", {"entity_id": c_id}, blocking=True)
                            except Exception as err:
                                _LOGGER.warning("Failed to turn on EV charger %s: %s", c_id, err)
                    elif ev_action == ACTION_EV_PAUSE_PEAK:
                        dispatched_actions.append({
                            "entity_id": c_id,
                            "domain": "switch",
                            "service": "turn_off",
                            "action": ev_action,
                            "reason": "Paused EV charging during peak tariff window",
                        })
                        if not dry_run:
                            try:
                                await self.hass.services.async_call("switch", "turn_off", {"entity_id": c_id}, blocking=True)
                            except Exception as err:
                                _LOGGER.warning("Failed to pause EV charger %s: %s", c_id, err)

                elif c_type == "charge_rate_selector" and ev_kw > 0:
                    target_amps = round((ev_kw * 1000.0) / 240.0)
                    dispatched_actions.append({
                        "entity_id": c_id,
                        "domain": "number",
                        "service": "set_value",
                        "value": target_amps,
                        "action": ev_action,
                        "reason": f"Adjusted charging rate to {target_amps}A ({round(ev_kw, 1)}kW)",
                    })
                    if not dry_run:
                        try:
                            await self.hass.services.async_call("number", "set_value", {"entity_id": c_id, "value": target_amps}, blocking=True)
                        except Exception as err:
                            _LOGGER.warning("Failed to adjust EV charge amperage %s: %s", c_id, err)

        return {
            "success": True,
            "dry_run": dry_run,
            "current_battery_action": current_action,
            "current_ev_action": ev_action,
            "dispatched_count": len(dispatched_actions),
            "dispatches": dispatched_actions,
            "message": f"Successfully evaluated arbitrage dispatch: {len(dispatched_actions)} action(s) processed.",
        }

