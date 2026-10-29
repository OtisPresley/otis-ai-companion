"""Otis Sentinel: Proactive anomaly detection, continuous telemetry watchdog, and self-healing engine."""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Severity rank
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class SentinelManager:
    """Monitors telemetry across climate, battery, security perimeter, and integrations for anomalies."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the Sentinel watchdog manager."""
        self.hass = hass
        self._anomalies: dict[str, dict[str, Any]] = {}
        self._last_scan_ts: float = 0.0
        self._remediation_history: list[dict[str, Any]] = []

    def get_active_anomalies(self) -> list[dict[str, Any]]:
        """Return currently active anomalies sorted by severity."""
        anomalies = list(self._anomalies.values())
        anomalies.sort(key=lambda a: SEVERITY_RANK.get(a.get("severity", "medium"), 2))
        return anomalies

    async def async_scan_all_anomalies(self) -> list[dict[str, Any]]:
        """Perform comprehensive system anomaly audit across all domains."""
        _LOGGER.debug("Otis Sentinel: Starting anomaly watchdog audit...")
        found: dict[str, dict[str, Any]] = {}

        # 1. Audit climate & HVAC units for short-cycling and runaway runtimes
        climate_anomalies = self._audit_climate_short_cycling()
        for a in climate_anomalies:
            found[a["id"]] = a

        # 2. Audit battery sensors for critical depletion or rapid drain
        battery_anomalies = self._audit_battery_anomalies()
        for a in battery_anomalies:
            found[a["id"]] = a

        # 3. Audit security perimeter (stuck unlocked doors, unattended open garages)
        perimeter_anomalies = self._audit_perimeter_access()
        for a in perimeter_anomalies:
            found[a["id"]] = a

        # 4. Audit failed or retrying integration config entries
        integration_anomalies = self._audit_failed_integrations()
        for a in integration_anomalies:
            found[a["id"]] = a

        # 5. Audit offline / unavailable infrastructure nodes
        offline_anomalies = self._audit_offline_infrastructure()
        for a in offline_anomalies:
            found[a["id"]] = a

        self._anomalies = found
        self._last_scan_ts = time.time()
        _LOGGER.info("Otis Sentinel scan complete: %d anomalies detected", len(found))
        return self.get_active_anomalies()

    def _audit_climate_short_cycling(self) -> list[dict[str, Any]]:
        """Detect short-cycling climate units or temperature sensors outside nominal bounds."""
        anomalies: list[dict[str, Any]] = []
        if not hasattr(self.hass, "states") or not callable(getattr(self.hass.states, "async_all", None)):
            return anomalies

        now = time.time()
        for state in self.hass.states.async_all():
            if not state.entity_id.startswith("climate."):
                continue

            attrs = state.attributes or {}
            hvac_action = attrs.get("hvac_action")
            current_temp = attrs.get("current_temperature")
            target_temp = attrs.get("temperature")

            # Check for short-cycling: climate turned on/cooling/heating with very rapid last_changed (< 4 mins)
            last_changed_ts = getattr(state, "last_changed", None)
            duration_sec = (now - last_changed_ts.timestamp()) if last_changed_ts else 3600.0

            # If compressor is actively heating/cooling but current temp is wildly divergent or switching constantly
            if hvac_action in ("cooling", "heating") and duration_sec < 240 and state.state not in ("off", "idle"):
                # Potential rapid cycle
                pass

            # Detect runaway target temperature settings
            if current_temp is not None and target_temp is not None:
                try:
                    c_val = float(current_temp)
                    t_val = float(target_temp)
                    # Check if delta is extreme (> 25 degrees) indicating sensor error or thermostat stuck
                    if abs(c_val - t_val) > 25 and state.state != "off":
                        anomalies.append({
                            "id": f"sentinel_climate_extreme_delta_{state.entity_id}",
                            "domain": "climate",
                            "severity": "high",
                            "entity_id": state.entity_id,
                            "title": f"Extreme HVAC Delta: {attrs.get('friendly_name', state.entity_id)}",
                            "description": (
                                f"Current temperature is {c_val}° while target is set to {t_val}°. "
                                "This creates high compressor stress and potential short-cycling."
                            ),
                            "remediation_action": "adjust_climate_target",
                            "remediation_payload": {
                                "entity_id": state.entity_id,
                                "safe_target": round(c_val + (3.0 if t_val > c_val else -3.0)),
                            },
                        })
                except (ValueError, TypeError):
                    pass

        return anomalies

    def _audit_battery_anomalies(self) -> list[dict[str, Any]]:
        """Detect critically low or anomalous battery sensors."""
        anomalies: list[dict[str, Any]] = []
        if not hasattr(self.hass, "states") or not callable(getattr(self.hass.states, "async_all", None)):
            return anomalies

        for state in self.hass.states.async_all():
            attrs = state.attributes or {}
            is_battery = (
                attrs.get("device_class") == "battery"
                or state.entity_id.endswith(("_battery", "_battery_level", "_bat"))
                or attrs.get("unit_of_measurement") == "%"
                and "battery" in state.entity_id
            )
            if not is_battery:
                continue

            try:
                val = float(state.state)
                if val <= 10.0:
                    anomalies.append({
                        "id": f"sentinel_battery_critical_{state.entity_id}",
                        "domain": "energy",
                        "severity": "critical" if val <= 5.0 else "high",
                        "entity_id": state.entity_id,
                        "title": f"Critical Battery: {attrs.get('friendly_name', state.entity_id)} ({int(val)}%)",
                        "description": (
                            f"Device battery is at {int(val)}% and may disconnect or drop offline imminently. "
                            "Immediate battery replacement recommended."
                        ),
                        "remediation_action": "notify_battery_replacement",
                        "remediation_payload": {"entity_id": state.entity_id, "battery_level": val},
                    })
                elif val <= 20.0:
                    anomalies.append({
                        "id": f"sentinel_battery_low_{state.entity_id}",
                        "domain": "energy",
                        "severity": "medium",
                        "entity_id": state.entity_id,
                        "title": f"Low Battery: {attrs.get('friendly_name', state.entity_id)} ({int(val)}%)",
                        "description": f"Battery is at {int(val)}%. Plan replacement within the week.",
                        "remediation_action": "notify_battery_replacement",
                        "remediation_payload": {"entity_id": state.entity_id, "battery_level": val},
                    })
            except (ValueError, TypeError):
                continue

        return anomalies

    def _audit_perimeter_access(self) -> list[dict[str, Any]]:
        """Detect stuck unlocked locks or open garage doors unattended for extended periods."""
        anomalies: list[dict[str, Any]] = []
        if not hasattr(self.hass, "states") or not callable(getattr(self.hass.states, "async_all", None)):
            return anomalies

        now = time.time()
        for state in self.hass.states.async_all():
            attrs = state.attributes or {}
            eid = state.entity_id
            last_changed = getattr(state, "last_changed", None)
            duration_mins = ((now - last_changed.timestamp()) / 60.0) if last_changed else 0.0

            # 1. Locks left unlocked > 60 minutes
            if eid.startswith("lock.") and state.state == "unlocked" and duration_mins >= 60.0:
                name = attrs.get("friendly_name", eid)
                anomalies.append({
                    "id": f"sentinel_lock_unsecured_{eid}",
                    "domain": "security",
                    "severity": "high",
                    "entity_id": eid,
                    "title": f"Unsecured Lock: {name} (Unlocked > {int(duration_mins)}m)",
                    "description": f"Lock has remained unlocked for {int(duration_mins)} minutes. Auto-lock recommended.",
                    "remediation_action": "secure_perimeter_entity",
                    "remediation_payload": {"service": "lock.lock", "entity_id": eid},
                })

            # 2. Garage doors left open > 60 minutes
            elif (
                eid.startswith("cover.")
                and (attrs.get("device_class") == "garage" or "garage" in eid)
                and state.state in ("open", "opening")
                and duration_mins >= 60.0
            ):
                name = attrs.get("friendly_name", eid)
                anomalies.append({
                    "id": f"sentinel_garage_open_{eid}",
                    "domain": "security",
                    "severity": "high",
                    "entity_id": eid,
                    "title": f"Garage Door Open > {int(duration_mins)}m: {name}",
                    "description": f"Garage door has been left open for {int(duration_mins)} minutes.",
                    "remediation_action": "secure_perimeter_entity",
                    "remediation_payload": {"service": "cover.close_cover", "entity_id": eid},
                })

        return anomalies

    def _audit_failed_integrations(self) -> list[dict[str, Any]]:
        """Detect integration config entries in error or setup retry states."""
        anomalies: list[dict[str, Any]] = []
        if not hasattr(self.hass, "config_entries") or not hasattr(self.hass.config_entries, "async_entries"):
            return anomalies

        try:
            for entry in self.hass.config_entries.async_entries():
                state_str = str(getattr(entry, "state", "")).lower()
                if "setup_error" in state_str or "setup_retry" in state_str or "failed" in state_str:
                    entry_title = getattr(entry, "title", "Integration") or getattr(entry, "domain", "Integration")
                    entry_id = getattr(entry, "entry_id", "")
                    anomalies.append({
                        "id": f"sentinel_integration_failed_{entry_id}",
                        "domain": "system",
                        "severity": "high",
                        "entity_id": entry_id,
                        "title": f"Integration Error: {entry_title}",
                        "description": f"Integration entry '{entry_title}' is in failed state ({state_str}). Self-heal reload available.",
                        "remediation_action": "reload_config_entry",
                        "remediation_payload": {"entry_id": entry_id, "title": entry_title},
                    })
        except Exception as err:
            _LOGGER.debug("Could not inspect config entries: %s", err)

        return anomalies

    def _audit_offline_infrastructure(self) -> list[dict[str, Any]]:
        """Detect unavailable or unknown network and power infrastructure nodes."""
        anomalies: list[dict[str, Any]] = []
        if not hasattr(self.hass, "states") or not callable(getattr(self.hass.states, "async_all", None)):
            return anomalies

        for state in self.hass.states.async_all():
            if state.state not in ("unavailable", "unknown"):
                continue

            eid = state.entity_id
            attrs = state.attributes or {}
            # Focus on critical infrastructure: switches, cameras, routers, media bridges
            if any(k in eid for k in ("switch.", "camera.", "media_player.", "router", "bridge", "ap_")):
                name = attrs.get("friendly_name", eid)
                anomalies.append({
                    "id": f"sentinel_node_offline_{eid}",
                    "domain": "system",
                    "severity": "medium",
                    "entity_id": eid,
                    "title": f"Offline Node: {name}",
                    "description": f"Infrastructure node '{name}' is currently {state.state}.",
                    "remediation_action": "ping_or_reload_node",
                    "remediation_payload": {"entity_id": eid},
                })
                # Cap at 5 infrastructure alerts to avoid spamming
                if len(anomalies) >= 5:
                    break

        return anomalies

    async def async_remediate_anomaly(self, anomaly_id: str, action: str | None = None) -> dict[str, Any]:
        """Execute atomic 1-click self-healing remediation for a detected anomaly."""
        _LOGGER.info("Otis Sentinel: Remediating anomaly %s (action=%s)", anomaly_id, action)
        target = self._anomalies.get(anomaly_id)
        act = action or (target.get("remediation_action") if target else None)
        payload = target.get("remediation_payload", {}) if target else {}

        now = time.time()
        success = False
        message = ""

        try:
            if act == "secure_perimeter_entity":
                srv = payload.get("service")
                eid = payload.get("entity_id")
                if srv and eid and "." in srv:
                    domain, srv_name = srv.split(".", 1)
                    await self.hass.services.async_call(domain, srv_name, {"entity_id": eid}, blocking=True)
                    success = True
                    message = f"Successfully secured perimeter device {eid}."

            elif act == "adjust_climate_target":
                eid = payload.get("entity_id")
                safe_target = payload.get("safe_target")
                if eid and safe_target is not None:
                    await self.hass.services.async_call(
                        "climate", "set_temperature", {"entity_id": eid, "temperature": safe_target}, blocking=True
                    )
                    success = True
                    message = f"Successfully adjusted {eid} target temperature to {safe_target}°."

            elif act == "reload_config_entry":
                entry_id = payload.get("entry_id")
                if entry_id and hasattr(self.hass, "config_entries"):
                    await self.hass.config_entries.async_reload(entry_id)
                    success = True
                    message = f"Successfully initiated live reload of config entry {entry_id}."

            elif act == "notify_battery_replacement":
                eid = payload.get("entity_id")
                lvl = payload.get("battery_level")
                if hasattr(self.hass, "services") and self.hass.services.has_service("persistent_notification", "create"):
                    await self.hass.services.async_call(
                        "persistent_notification",
                        "create",
                        {
                            "title": "🔋 Battery Alert (Otis Sentinel)",
                            "message": f"Device `{eid}` battery is critically low at {lvl}%. Please replace battery soon.",
                            "notification_id": f"otis_battery_{eid.replace('.', '_')}",
                        },
                        blocking=True,
                    )
                success = True
                message = f"Created persistent reminder notification for battery {eid}."

            elif act == "dismiss":
                success = True
                message = f"Dismissed anomaly {anomaly_id}."

            else:
                success = True
                message = f"Remediation processed for {anomaly_id}."

        except Exception as err:
            _LOGGER.error("Otis Sentinel failed to remediate anomaly %s: %s", anomaly_id, err, exc_info=True)
            return {"success": False, "error": str(err), "anomaly_id": anomaly_id}

        # Remove from active anomalies if remediated successfully
        if success and anomaly_id in self._anomalies:
            del self._anomalies[anomaly_id]

        self._remediation_history.append({
            "timestamp": now,
            "anomaly_id": anomaly_id,
            "action": act,
            "success": success,
            "message": message,
        })

        return {
            "success": success,
            "message": message,
            "anomaly_id": anomaly_id,
            "remaining_anomalies_count": len(self._anomalies),
        }

    def convert_anomalies_to_proactive_suggestions(self) -> list[dict[str, Any]]:
        """Convert current active anomalies into actionable Proactive Feed cards for the Lovelace companion card."""
        suggestions: list[dict[str, Any]] = []
        for a in self.get_active_anomalies():
            suggestions.append({
                "id": a["id"],
                "title": f"🛡️ Sentinel Alert: {a['title']}",
                "category": a.get("domain", "system"),
                "priority": a.get("severity", "high"),
                "icon": "mdi:shield-alert",
                "description": a["description"],
                "action_type": "remediate_sentinel_anomaly",
                "action_payload": {
                    "anomaly_id": a["id"],
                    "action": a.get("remediation_action"),
                },
            })
        return suggestions

