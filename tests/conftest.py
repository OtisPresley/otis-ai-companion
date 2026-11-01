"""Global pytest fixtures and Home Assistant mocks for Otis AI Companion tests."""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

# --- Patching Home Assistant modules for local execution ---
mock_voluptuous = MagicMock()
mock_voluptuous.Schema = MagicMock(return_value=lambda x: x)

mock_ha_core = MagicMock()
mock_ha_core.HomeAssistant = MagicMock
mock_ha_core.ServiceCall = MagicMock
mock_ha_core.ServiceResponse = dict


class MockSupportsResponse:
    NONE = 0
    OPTIONAL = 1
    ONLY = 2


mock_ha_core.SupportsResponse = MockSupportsResponse

mock_ha_helpers = MagicMock()
mock_ha_helpers.config_validation = MagicMock()
mock_ha_helpers.config_validation.string = MagicMock()
mock_ha_helpers.config_validation.boolean = MagicMock()


class DummyConfigFlow:
    hass = None

    def __init_subclass__(cls, domain=None, **kwargs):
        pass

    def _async_current_entries(self):
        return []

    def async_abort(self, reason):
        return {"type": "abort", "reason": reason}

    def async_create_entry(self, title, data, description_placeholders=None):
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(self, step_id, data_schema=None, errors=None, description_placeholders=None):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema}


class DummyOptionsFlow:
    def __init__(self, config_entry=None):
        self.config_entry = config_entry

    def async_create_entry(self, title, data):
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(self, step_id, data_schema=None, errors=None):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema}


mock_ha_entries = MagicMock()
mock_ha_entries.ConfigEntry = MagicMock
mock_ha_entries.ConfigFlow = DummyConfigFlow
mock_ha_entries.OptionsFlow = DummyOptionsFlow

mock_conversation = MagicMock()


class DummyAbstractAgent:
    pass


mock_conversation.AbstractAgent = DummyAbstractAgent


class DummyConversationResult:
    def __init__(self, response, conversation_id):
        self.response = response
        self.conversation_id = conversation_id


mock_conversation.ConversationResult = DummyConversationResult

homeassistant = types.ModuleType("homeassistant")
homeassistant.__path__ = []

helpers = types.ModuleType("homeassistant.helpers")
helpers.__path__ = []

components = types.ModuleType("homeassistant.components")
components.__path__ = []

sys.modules.setdefault("voluptuous", mock_voluptuous)
sys.modules.setdefault("homeassistant", homeassistant)
sys.modules.setdefault("homeassistant.core", mock_ha_core)
sys.modules.setdefault("homeassistant.helpers", helpers)
sys.modules.setdefault("homeassistant.helpers.config_validation", mock_ha_helpers.config_validation)
sys.modules.setdefault("homeassistant.helpers.selector", MagicMock())
sys.modules.setdefault("homeassistant.config_entries", mock_ha_entries)
sys.modules.setdefault("homeassistant.data_entry_flow", MagicMock())
sys.modules.setdefault("homeassistant.components", components)
sys.modules.setdefault("homeassistant.helpers.area_registry", MagicMock())
sys.modules.setdefault("homeassistant.helpers.entity_registry", MagicMock())
sys.modules.setdefault("homeassistant.helpers.device_registry", MagicMock())
sys.modules.setdefault("homeassistant.helpers.intent", MagicMock())

mock_storage = MagicMock()


class DummyStore:
    def __init__(self, hass, version, key):
        self.hass = hass
        self.version = version
        self.key = key
        self._data = None

    async def async_load(self):
        return self._data

    async def async_save(self, data):
        self._data = data


mock_storage.Store = DummyStore
sys.modules.setdefault("homeassistant.helpers.storage", mock_storage)
sys.modules.setdefault("homeassistant.components.conversation", mock_conversation)
sys.modules.setdefault("homeassistant.components.http", MagicMock())

mock_aiohttp_client = MagicMock()
mock_aiohttp_client.async_get_clientsession = MagicMock()
sys.modules.setdefault("homeassistant.helpers.aiohttp_client", mock_aiohttp_client)

mock_aiohttp = MagicMock()
mock_aiohttp.web = MagicMock()
mock_aiohttp.ClientSession = MagicMock
mock_aiohttp.ClientTimeout = MagicMock
sys.modules.setdefault("aiohttp", mock_aiohttp)
sys.modules.setdefault("aiohttp.web", mock_aiohttp.web)

sys.modules.setdefault("homeassistant.util", MagicMock())
sys.modules.setdefault("homeassistant.util.yaml", MagicMock())

