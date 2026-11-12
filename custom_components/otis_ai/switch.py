"""Switch platform for Otis AI Companion backed entities."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
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

SWITCH_DEFINITIONS: list[dict[str, Any]] = [
    {
        "key": "audio_follow",
        "name": "Otis Audio Follow-Me",
        "icon": "mdi:cast-connected",
        "rule_key": "audio_follow_enabled",
        "default": True,
    },
    {
        "key": "voice_announcements",
        "name": "Otis Proactive Voice Announcements",
        "icon": "mdi:volume-high",
        "rule_key": "voice_announcements_enabled",
        "default": True,
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Otis AI switch platform entities."""
    entry_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    entities_map = entry_data.setdefault("entities", {})
    rules_mgr = entry_data.get("rules_manager")

    switches: list[OtisSwitchEntity] = []
    for s_def in SWITCH_DEFINITIONS:
        s_ent = OtisSwitchEntity(hass, entry, s_def, rules_mgr)
        switches.append(s_ent)
        entities_map[s_ent.entity_id] = s_ent

    async_add_entities(switches)
    _LOGGER.info("Registered %d Otis AI platform switch entities", len(switches))


class OtisSwitchEntity(SwitchEntity):
    """Platform-backed Otis AI switch entity."""

    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        switch_def: dict[str, Any],
        rules_manager: Any = None,
    ) -> None:
        """Initialize the switch entity."""
        self.hass = hass
        self._entry_id = entry.entry_id
        self._key = switch_def["key"]
        self._rule_key = switch_def["rule_key"]
        self._rules_manager = rules_manager
        self.entity_id = f"switch.otis_{self._key}"
        self._attr_unique_id = f"{entry.entry_id}_{self._key}"
        self._attr_name = switch_def["name"]
        self._attr_icon = switch_def.get("icon", "mdi:toggle-switch")
        self._attr_is_on = bool(switch_def.get("default", True))
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Otis AI Companion",
            manufacturer="Otis AI",
            model="Local Edge AI Coordinator",
        )

        if self._rules_manager and hasattr(self._rules_manager, "get_rules"):
            rules = self._rules_manager.get_rules()
            if self._rule_key in rules:
                self._attr_is_on = bool(rules[self._rule_key])

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._attr_is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        self._attr_is_on = True
        if self._rules_manager and hasattr(self._rules_manager, "async_save"):
            await self._rules_manager.async_save({self._rule_key: True})
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        self._attr_is_on = False
        if self._rules_manager and hasattr(self._rules_manager, "async_save"):
            await self._rules_manager.async_save({self._rule_key: False})
        self.async_write_ha_state()

    @callback
    def async_set_state(self, new_state: Any, attributes: dict[str, Any] | None = None) -> None:
        """Update switch state from Otis coordinators."""
        if isinstance(new_state, bool):
            self._attr_is_on = new_state
        elif isinstance(new_state, str):
            self._attr_is_on = new_state.lower() in ("on", "true", "1")
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
