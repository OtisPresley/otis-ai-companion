"""Binary sensor platform for Otis AI Companion backed entities."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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

BINARY_SENSOR_DEFINITIONS: list[dict[str, Any]] = [
    {
        "key": "active_occupancy",
        "name": "Otis Active Occupancy",
        "device_class": BinarySensorDeviceClass.OCCUPANCY,
        "icon": "mdi:home-account",
        "default_state": False,
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Otis AI binary sensor platform entities."""
    entry_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    entities_map = entry_data.setdefault("entities", {})

    binary_sensors: list[OtisBinarySensorEntity] = []
    for b_def in BINARY_SENSOR_DEFINITIONS:
        b_ent = OtisBinarySensorEntity(hass, entry, b_def)
        binary_sensors.append(b_ent)
        entities_map[b_ent.entity_id] = b_ent

    async_add_entities(binary_sensors)
    _LOGGER.info("Registered %d Otis AI platform binary sensor entities", len(binary_sensors))


class OtisBinarySensorEntity(BinarySensorEntity):
    """Platform-backed Otis AI binary sensor entity."""

    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, sensor_def: dict[str, Any]) -> None:
        """Initialize the binary sensor entity."""
        self.hass = hass
        self._entry_id = entry.entry_id
        self._key = sensor_def["key"]
        self.entity_id = f"binary_sensor.otis_{self._key}"
        self._attr_unique_id = f"{entry.entry_id}_{self._key}"
        self._attr_name = sensor_def["name"]
        self._attr_icon = sensor_def.get("icon", "mdi:home-account")
        self._attr_device_class = sensor_def.get("device_class")
        self._attr_is_on = bool(sensor_def.get("default_state", False))
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Otis AI Companion",
            manufacturer="Otis AI",
            model="Local Edge AI Coordinator",
        )

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        return self._attr_is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return self._attr_extra_state_attributes

    @callback
    def async_set_state(self, new_state: Any, attributes: dict[str, Any] | None = None) -> None:
        """Update binary sensor state and attributes from Otis coordinators."""
        if isinstance(new_state, bool):
            self._attr_is_on = new_state
        elif isinstance(new_state, str):
            self._attr_is_on = new_state.lower() in ("on", "true", "1", "occupied", "home")
        else:
            self._attr_is_on = bool(new_state)

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
