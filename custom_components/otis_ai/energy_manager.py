"""Otis AI Companion: Energy & Predictive Load Orchestrator (Phase 7).

Coordinates energy monitoring, solar surplus utilization, battery/UPS storage tracking,
grid tariff awareness, dynamic load-shedding, and appliance sequencing across Home Assistant.
"""

from __future__ import annotations

from datetime import datetime
import logging
import time
from typing import Any
import uuid

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class EnergyManager:
    """Manages energy topology discovery, live load telemetry, and dynamic load shedding."""

    def __init__(self, hass: HomeAssistant, spatial_manager=None) -> None:
        """Initialize the Energy Manager."""
        self.hass = hass
        self.spatial_manager = spatial_manager
        self._shed_history: list[dict[str, Any]] = []

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

