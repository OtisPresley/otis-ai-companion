"""Sensor platform for Otis AI Companion backed entities."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _cb_fallback(fn: Any) -> Any:
    return fn


if not callable(callback(lambda: None)):
    callback = _cb_fallback

# Canonical Otis sensor definitions
SENSOR_DEFINITIONS: list[dict[str, Any]] = [
    {
        "key": "spatial_migration",
        "name": "Otis Spatial Migration",
        "icon": "mdi:walk",
        "default_state": "idle",
    },
    {
        "key": "fused_presence",
        "name": "Otis Fused Presence",
        "icon": "mdi:account-multiple-check",
        "default_state": "idle",
    },
    {
        "key": "multi_agent_orchestrator",
        "name": "Otis Multi-Agent Orchestrator",
        "icon": "mdi:robot",
        "default_state": "ready",
    },
    {
        "key": "voice_satellites",
        "name": "Otis Voice Satellites",
        "icon": "mdi:microphone-outline",
        "default_state": "online",
    },
    {
        "key": "mesh_health",
        "name": "Otis Mesh Health",
        "icon": "mdi:graphql",
        "default_state": "healthy",
    },
    {
        "key": "rules_engine",
        "name": "Otis Rules Engine",
        "icon": "mdi:tune",
        "default_state": "active",
    },
    {
        "key": "perimeter_sentinel",
        "name": "Otis Perimeter Sentinel",
        "icon": "mdi:shield-check",
        "default_state": "normal",
    },
    {
        "key": "intruder_tracks",
        "name": "Otis Intruder Tracks",
        "icon": "mdi:target-account",
        "default_state": "idle",
    },
    {
        "key": "rag_knowledge",
        "name": "Otis RAG Knowledge",
        "icon": "mdi:database-search",
        "default_state": "indexed",
    },
    {
        "key": "knowledge_rag",
        "name": "Otis Knowledge & RAG Vector Store",
        "icon": "mdi:brain",
        "default_state": "0",
    },
    {
        "key": "energy_arbitrage",
        "name": "Otis Energy Arbitrage",
        "icon": "mdi:flash-outline",
        "default_state": "balanced",
    },
    {
        "key": "federation_cluster",
        "name": "Otis Federation Cluster",
        "icon": "mdi:server-network",
        "default_state": "standalone",
    },
    {
        "key": "federation_node",
        "name": "Otis Federation Node",
        "icon": "mdi:server",
        "default_state": "local",
    },
]


def async_update_entity_state(
    hass: HomeAssistant,
    entity_id: str,
    state_val: Any,
    attributes: dict[str, Any] | None = None,
) -> None:
    """Update state on the backed platform entity, or fallback gracefully for testing environments."""
    updated = False
    if hasattr(hass, "data") and isinstance(hass.data, dict):
        otis_data = hass.data.get(DOMAIN, {})
        if isinstance(otis_data, dict):
            for entry_data in otis_data.values():
                if isinstance(entry_data, dict) and "entities" in entry_data:
                    ent = entry_data["entities"].get(entity_id)
                    if ent is not None and hasattr(ent, "async_set_state"):
                        ent.async_set_state(state_val, attributes)
                        updated = True
                        break
    if not updated and hasattr(hass, "states") and hasattr(hass.states, "async_set"):
        try:
            hass.states.async_set(entity_id, state_val, attributes or {})
        except Exception:
            pass


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Otis AI sensor platform entities."""
    entry_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    entities_map = entry_data.setdefault("entities", {})

    sensors: list[OtisSensorEntity] = []
    for s_def in SENSOR_DEFINITIONS:
        s_ent = OtisSensorEntity(hass, entry, s_def)
        sensors.append(s_ent)
        entities_map[s_ent.entity_id] = s_ent

    async_add_entities(sensors)
    _LOGGER.info("Registered %d Otis AI platform sensor entities", len(sensors))


class OtisSensorEntity(SensorEntity):
    """Platform-backed Otis AI sensor entity."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, sensor_def: dict[str, Any]) -> None:
        """Initialize the sensor entity."""
        self.hass = hass
        self._entry_id = entry.entry_id
        self._key = sensor_def["key"]
        self.entity_id = f"sensor.otis_{self._key}"
        self._attr_unique_id = f"{entry.entry_id}_{self._key}"
        self._attr_name = sensor_def["name"]
        self._attr_icon = sensor_def.get("icon", "mdi:eye")
        self._attr_native_value = sensor_def.get("default_state", "idle")
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Otis AI Companion",
            manufacturer="Otis AI",
            model="Local Edge AI Coordinator",
        )

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return self._attr_extra_state_attributes

    @callback
    def async_set_state(self, new_state: Any, attributes: dict[str, Any] | None = None) -> None:
        """Update sensor state and attributes from Otis coordinators."""
        self._attr_native_value = new_state
        if attributes is not None:
            self._attr_extra_state_attributes = dict(attributes)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register entity in entry store on addition."""
        await super().async_added_to_hass()
        otis_data = self.hass.data.setdefault(DOMAIN, {}).setdefault(self._entry_id, {})
        otis_data.setdefault("entities", {})[self.entity_id] = self

    async def async_will_remove_from_hass(self) -> None:
        """Deregister entity from entry store on removal."""
        otis_data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        if "entities" in otis_data:
            otis_data["entities"].pop(self.entity_id, None)
        await super().async_will_remove_from_hass()
