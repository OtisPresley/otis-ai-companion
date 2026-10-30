"""Unit tests for the rebuilt AI Router core."""
# ruff: noqa: E402, F841
import sys
import os
import asyncio
import tempfile
import unittest
import types
from unittest.mock import MagicMock, AsyncMock

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

# Define dummy base classes for ConfigFlow and OptionsFlow
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

# Create homeassistant package
homeassistant = types.ModuleType('homeassistant')
homeassistant.__path__ = []

# Create homeassistant.helpers package
helpers = types.ModuleType('homeassistant.helpers')
helpers.__path__ = []

# Create homeassistant.components package
components = types.ModuleType('homeassistant.components')
components.__path__ = []

sys.modules['voluptuous'] = mock_voluptuous
sys.modules['homeassistant'] = homeassistant
sys.modules['homeassistant.core'] = mock_ha_core
sys.modules['homeassistant.helpers'] = helpers
sys.modules['homeassistant.helpers.config_validation'] = mock_ha_helpers.config_validation
sys.modules['homeassistant.helpers.selector'] = MagicMock()
sys.modules['homeassistant.config_entries'] = mock_ha_entries
sys.modules['homeassistant.data_entry_flow'] = MagicMock()
sys.modules['homeassistant.components'] = components
sys.modules['homeassistant.helpers.area_registry'] = MagicMock()
sys.modules['homeassistant.helpers.entity_registry'] = MagicMock()
sys.modules['homeassistant.helpers.device_registry'] = MagicMock()
sys.modules['homeassistant.helpers.intent'] = MagicMock()
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
sys.modules['homeassistant.helpers.storage'] = mock_storage
sys.modules['homeassistant.components.conversation'] = mock_conversation
sys.modules['homeassistant.components.http'] = MagicMock()
mock_aiohttp_client = MagicMock()
mock_aiohttp_client.async_get_clientsession = MagicMock()
sys.modules['homeassistant.helpers.aiohttp_client'] = mock_aiohttp_client
mock_aiohttp = MagicMock()
mock_aiohttp.web = MagicMock()
sys.modules['aiohttp'] = mock_aiohttp
sys.modules['aiohttp.web'] = mock_aiohttp.web
sys.modules['homeassistant.util'] = MagicMock()
sys.modules['homeassistant.util.yaml'] = MagicMock()
# -----------------------------------------------------------

# Add repository root to path to import the custom component
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from custom_components.otis_ai import (
    DiscoveryEngine,
)
from custom_components.otis_ai.config_flow import OtisAIConfigFlow
from custom_components.otis_ai.const import (
    DOMAIN,
    CONF_CONVERSATION_AGENT,
    CONF_SPATIAL_MAP_PATH,
    CONF_THEME_NAME,
)

class MockState:
    """Mock state object."""
    def __init__(self, entity_id, state, attributes=None):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}

class MockAgentInfo:
    """Mock AgentInfo object."""
    def __init__(self, agent_id, name):
        self.id = agent_id
        self.name = name

class TestOtisAICore(unittest.TestCase):
    """Test suite for the rebuilt core of AI Router."""

    def setUp(self):
        self.hass = MagicMock()
        self.hass.data = {}
        
        async def mock_async_add_executor_job(func, *args, **kwargs):
            return func(*args, **kwargs)
        self.hass.async_add_executor_job = AsyncMock(side_effect=mock_async_add_executor_job)

        self.hass.config = MagicMock()
        self.temp_test_dir = tempfile.TemporaryDirectory()
        self.hass.config.path = lambda *args: os.path.join(self.temp_test_dir.name, *args)
        self.hass.config.components = ["sensor", "light", "conversation", "webostv", "hue", "mqtt"]
        self.hass.config_entries = MagicMock()
        self.hass.config_entries.async_entries = MagicMock(return_value=[])

        # Setup registries
        self.area_reg = MagicMock()
        self.device_reg = MagicMock()
        self.entity_reg = MagicMock()

        import homeassistant.helpers.area_registry as ar
        import homeassistant.helpers.device_registry as dr
        import homeassistant.helpers.entity_registry as er
        
        ar.async_get = MagicMock(return_value=self.area_reg)
        dr.async_get = MagicMock(return_value=self.device_reg)
        er.async_get = MagicMock(return_value=self.entity_reg)

        # Mock Registry entries
        self.area_reg.async_list_areas = MagicMock(return_value=[])
        self.device_reg.devices = {}
        self.entity_reg.entities = {}
        mock_conversation.get_agent_manager = MagicMock(side_effect=Exception("Mocked get_agent_manager"))

    def test_config_flow_no_agents(self):
        """Test config flow when no conversation agents are configured (Onboarding)."""
        mock_conversation.async_get_agent_info = MagicMock(return_value=[])

        flow = OtisAIConfigFlow()
        flow.hass = self.hass

        # Step 1: User triggers setup, gets onboarding form
        import asyncio
        result = asyncio.run(flow.async_step_user())
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "onboarding")

        # Step 2: User completes onboarding
        result2 = asyncio.run(flow.async_step_onboarding({"understand_limitations": True}))
        self.assertEqual(result2["type"], "create_entry")
        self.assertEqual(result2["title"], "Otis AI Companion (Limited)")
        self.assertIsNone(result2["data"][CONF_CONVERSATION_AGENT])

    def test_config_flow_with_agents(self):
        """Test config flow when conversation agents are available."""
        agent = MockAgentInfo("google_generative_ai", "Google Gemini")
        mock_conversation.async_get_agent_info = MagicMock(return_value=[agent])

        flow = OtisAIConfigFlow()
        flow.hass = self.hass

        # Step 1: User triggers setup, gets agent selection form
        import asyncio
        result = asyncio.run(flow.async_step_user())
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "user")

        # Step 2: User selects agent
        result2 = asyncio.run(flow.async_step_user({
            CONF_CONVERSATION_AGENT: "google_generative_ai",
            CONF_SPATIAL_MAP_PATH: "custom_map.json",
            CONF_THEME_NAME: "custom_theme",
        }))
        self.assertEqual(result2["type"], "create_entry")
        self.assertEqual(result2["title"], "Otis AI Companion")
        self.assertEqual(result2["data"][CONF_CONVERSATION_AGENT], "google_generative_ai")
        self.assertEqual(result2["data"][CONF_SPATIAL_MAP_PATH], "custom_map.json")
        self.assertEqual(result2["data"][CONF_THEME_NAME], "custom_theme")

    def test_discovery_engine(self):
        """Test the DiscoveryEngine builds a correct capability map."""
        # 1. Setup Areas
        area_lr = MagicMock()
        area_lr.id = "living_room"
        area_lr.name = "Living Room"
        area_lr.aliases = ["lounge"]

        area_kit = MagicMock()
        area_kit.id = "kitchen"
        area_kit.name = "Kitchen"
        area_kit.aliases = []

        self.area_reg.async_list_areas.return_value = [area_lr, area_kit]

        # 2. Setup Devices
        device_tv = MagicMock()
        device_tv.id = "device_tv"
        device_tv.name = "Living Room TV"
        device_tv.name_by_user = None
        device_tv.model = "OLED65"
        device_tv.manufacturer = "LG"
        device_tv.area_id = "living_room"
        device_tv.identifiers = {("media_player", "lg_tv_123")}
        device_tv.via_device_id = None

        self.device_reg.devices = {"device_tv": device_tv}
        self.device_reg.async_get = MagicMock(side_effect=lambda device_id: device_tv if device_id == "device_tv" else None)

        # 3. Setup Entities
        # Entity 1: Active entity belonging to TV device in Living Room
        ent_tv = MagicMock()
        ent_tv.entity_id = "media_player.living_room_tv"
        ent_tv.name = None
        ent_tv.original_name = "Living Room TV"
        ent_tv.domain = "media_player"
        ent_tv.platform = "webostv"
        ent_tv.device_id = "device_tv"
        ent_tv.area_id = None  # Inherits from device
        ent_tv.disabled_by = None
        ent_tv.hidden_by = None
        ent_tv.config_entry_id = "entry_webostv"

        # Entity 2: Active entity in Kitchen (assigned directly in registry)
        ent_light = MagicMock()
        ent_light.entity_id = "light.kitchen_ceiling"
        ent_light.name = "Kitchen Ceiling Light"
        ent_light.original_name = "Ceiling Light"
        ent_light.domain = "light"
        ent_light.platform = "hue"
        ent_light.device_id = None
        ent_light.area_id = "kitchen"
        ent_light.disabled_by = None
        ent_light.hidden_by = None
        ent_light.config_entry_id = "entry_hue"

        # Entity 3: Orphaned entity (belongs to removed config entry)
        ent_orphan_1 = MagicMock()
        ent_orphan_1.entity_id = "light.old_bulb"
        ent_orphan_1.name = "Old Bulb"
        ent_orphan_1.original_name = "Old Bulb"
        ent_orphan_1.domain = "light"
        ent_orphan_1.platform = "lifx"
        ent_orphan_1.device_id = None
        ent_orphan_1.area_id = "living_room"
        ent_orphan_1.disabled_by = None
        ent_orphan_1.hidden_by = None
        ent_orphan_1.config_entry_id = "entry_lifx_removed"

        # Entity 4: Orphan entity whose legacy platform was deleted
        ent_orphan_2 = MagicMock()
        ent_orphan_2.entity_id = "sensor.legacy_weather"
        ent_orphan_2.name = "Legacy Weather"
        ent_orphan_2.original_name = "Legacy Weather"
        ent_orphan_2.domain = "sensor"
        ent_orphan_2.platform = "deleted_custom_platform"
        ent_orphan_2.device_id = None
        ent_orphan_2.area_id = "kitchen"
        ent_orphan_2.disabled_by = None
        ent_orphan_2.hidden_by = None
        ent_orphan_2.config_entry_id = None

        # Entity 5: Offline/disconnected entity belonging to an INSTALLED integration (MUST NOT BE ORPHAN)
        ent_disconnected = MagicMock()
        ent_disconnected.entity_id = "sensor.temperature"
        ent_disconnected.name = "Temperature"
        ent_disconnected.original_name = "Temperature"
        ent_disconnected.domain = "sensor"
        ent_disconnected.platform = "mqtt"
        ent_disconnected.device_id = None
        ent_disconnected.area_id = "kitchen"
        ent_disconnected.disabled_by = None
        ent_disconnected.hidden_by = None
        ent_disconnected.config_entry_id = "entry_mqtt"

        self.entity_reg.entities = {
            "media_player.living_room_tv": ent_tv,
            "light.kitchen_ceiling": ent_light,
            "light.old_bulb": ent_orphan_1,
            "sensor.legacy_weather": ent_orphan_2,
            "sensor.temperature": ent_disconnected,
        }

        # Mock states
        state_tv = MockState("media_player.living_room_tv", "playing")
        state_light = MockState("light.kitchen_ceiling", "on")
        state_restored = MockState("sensor.temperature", "unavailable", {"restored": True})
        
        def mock_get_state(entity_id):
            if entity_id == "media_player.living_room_tv":
                return state_tv
            if entity_id == "light.kitchen_ceiling":
                return state_light
            if entity_id == "sensor.temperature":
                return state_restored
            return None

        self.hass.states.get = MagicMock(side_effect=mock_get_state)
        self.hass.is_running = True

        # Mock active config entries
        active_entry_hue = MagicMock()
        active_entry_hue.entry_id = "entry_hue"
        active_entry_webostv = MagicMock()
        active_entry_webostv.entry_id = "entry_webostv"
        active_entry_mqtt = MagicMock()
        active_entry_mqtt.entry_id = "entry_mqtt"
        self.hass.config_entries.async_entries.return_value = [
            active_entry_hue,
            active_entry_webostv,
            active_entry_mqtt,
        ]

        # Execute Discovery
        engine = DiscoveryEngine(self.hass)
        import asyncio
        capability_map = asyncio.run(engine.async_build_capability_map())

        # Assertions
        self.assertIn("sensor", capability_map["integrations"])
        self.assertIn("living_room", capability_map["areas"])
        self.assertIn("kitchen", capability_map["areas"])

        # Check Living Room area contents (TV device and entity)
        self.assertIn("device_tv", capability_map["areas"]["living_room"]["devices"])
        self.assertIn("media_player.living_room_tv", capability_map["areas"]["living_room"]["entities"])

        # Check active entities list
        active_ids = [e["entity_id"] for e in capability_map["entities"]]
        self.assertIn("media_player.living_room_tv", active_ids)
        self.assertIn("light.kitchen_ceiling", active_ids)
        # Disconnected entity with installed config entry MUST be preserved in active list!
        self.assertIn("sensor.temperature", active_ids)
        self.assertNotIn("light.old_bulb", active_ids)
        self.assertNotIn("sensor.legacy_weather", active_ids)

        # Check orphaned entities list
        orphan_ids = [e["entity_id"] for e in capability_map["orphaned_entities"]]
        self.assertIn("light.old_bulb", orphan_ids)
        self.assertIn("sensor.legacy_weather", orphan_ids)
        self.assertNotIn("sensor.temperature", orphan_ids)

        # Check reasons
        orphans_by_id = {e["entity_id"]: e for e in capability_map["orphaned_entities"]}
        self.assertEqual(orphans_by_id["light.old_bulb"]["orphan_reason"], "config_entry_removed")
        self.assertEqual(orphans_by_id["sensor.legacy_weather"]["orphan_reason"], "platform_not_loaded")

        # Test orphan suppression during startup
        self.hass.is_running = False
        startup_map = asyncio.run(engine.async_build_capability_map())
        self.assertEqual(len(startup_map["orphaned_entities"]), 0)
        self.hass.is_running = True

    def test_conversation_agent_no_llm(self):
        """Test conversation agent when no LLM agent is discovered or configured."""
        from custom_components.otis_ai import OtisAIConversationAgent
        from unittest.mock import patch
        
        entry = MagicMock()
        entry.options = {}
        entry.data = {CONF_CONVERSATION_AGENT: None}
        
        engine = MagicMock()
        agent = OtisAIConversationAgent(self.hass, entry, engine, MagicMock())
        
        user_input = MagicMock()
        user_input.text = "Hello"
        user_input.conversation_id = "test_conv_id"
        user_input.create_response = MagicMock(return_value="response_mock")
        
        import asyncio
        with patch("custom_components.otis_ai.config_flow._get_agents", return_value=[]):
            result = asyncio.run(agent.async_process(user_input))
        
        self.assertEqual(result.conversation_id, "test_conv_id")
        user_input.create_response.assert_called_once()
        self.assertIn("No AI conversation agent is installed or active", user_input.create_response.call_args[1]["speech"])

    def test_conversation_agent_success(self):
        """Test conversation agent successfully delegates to LLM with capability map."""
        from custom_components.otis_ai import OtisAIConversationAgent
        
        entry = MagicMock()
        entry.options = {CONF_CONVERSATION_AGENT: "conversation.mock_llm"}
        entry.data = {}
        
        engine = MagicMock()
        mock_map = {
            "integrations": ["light"],
            "areas": {"living_room": {"name": "Living Room", "entities": [], "devices": []}},
            "entities": [],
            "orphaned_entities": []
        }
        engine.async_build_capability_map = AsyncMock(return_value=mock_map)
        
        agent = OtisAIConversationAgent(self.hass, entry, engine, MagicMock())
        
        user_input = MagicMock()
        user_input.text = "Help me automate my lights"
        user_input.conversation_id = "test_conv_id"
        user_input.context = "test_context"
        user_input.language = "en"
        user_input.device_id = None
        
        mock_llm_response = MagicMock()
        mock_llm_response.response.speech = {"plain": {"speech": "I can help you with your lights."}}
        mock_conversation.async_converse = AsyncMock(return_value=mock_llm_response)
        
        import asyncio
        result = asyncio.run(agent.async_process(user_input))
        
        # Verify capability map was built
        engine.async_build_capability_map.assert_called_once()
        
        # Verify conversation was forwarded to the LLM with injected prompt
        mock_conversation.async_converse.assert_called_once()
        call_kwargs = mock_conversation.async_converse.call_args[1]
        self.assertEqual(call_kwargs["agent_id"], "conversation.mock_llm")
        self.assertIn("You are the Otis AI Companion", call_kwargs["text"])
        self.assertIn("Help me automate my lights", call_kwargs["text"])
        self.assertEqual(result, mock_llm_response)

    def test_conversation_agent_error(self):
        """Test conversation agent handles LLM exceptions gracefully when all agents fail."""
        from custom_components.otis_ai import OtisAIConversationAgent
        
        entry = MagicMock()
        entry.options = {CONF_CONVERSATION_AGENT: "conversation.mock_llm"}
        entry.data = {}
        
        engine = MagicMock()
        engine.async_build_capability_map = AsyncMock(return_value={"integrations": [], "areas": {}, "entities": [], "orphaned_entities": []})
        
        agent = OtisAIConversationAgent(self.hass, entry, engine, MagicMock())
        
        user_input = MagicMock()
        user_input.text = "Hello"
        user_input.conversation_id = "test_conv_id"
        user_input.create_response = MagicMock(return_value="error_response_mock")
        
        mock_conversation.async_converse = AsyncMock(side_effect=RuntimeError("LLM offline"))
        
        import asyncio
        from unittest.mock import patch
        with patch("custom_components.otis_ai.config_flow._get_agents", return_value=[]):
            result = asyncio.run(agent.async_process(user_input))
        
        self.assertEqual(result.conversation_id, "test_conv_id")
        user_input.create_response.assert_called_once()
        self.assertIn("All available AI services are currently experiencing high demand or downtime", user_input.create_response.call_args[1]["speech"])

    def test_conversation_agent_failover_503(self):
        """Test transparent failover when primary agent returns 503 high demand error."""
        from custom_components.otis_ai import OtisAIConversationAgent
        from unittest.mock import patch
        
        entry = MagicMock()
        entry.options = {CONF_CONVERSATION_AGENT: "agent_primary"}
        entry.data = {}
        
        engine = MagicMock()
        engine.async_build_capability_map = AsyncMock(return_value={"integrations": [], "areas": {}, "entities": [], "orphaned_entities": []})
        
        agent = OtisAIConversationAgent(self.hass, entry, engine, MagicMock())
        
        user_input = MagicMock()
        user_input.text = "Turn on the fan"
        user_input.conversation_id = "test_conv_id"
        user_input.context = "test_context"
        user_input.language = "en"
        user_input.device_id = None
        
        # 1st call (primary) returns Google 503 error text
        resp_503 = MagicMock()
        resp_503.response.speech = {
            "plain": {
                "speech": 'Sorry, I had a problem getting a response from Google Generative AI.: {"error": {"code": 503, "message": "This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.", "status": "UNAVAILABLE"}}'
            }
        }
        
        # 2nd call (fallback) returns successful response
        resp_success = MagicMock()
        resp_success.response.speech = {
            "plain": {
                "speech": "I have created the requested automation for your fan."
            }
        }
        
        mock_conversation.async_converse = AsyncMock(side_effect=[resp_503, resp_success])
        
        mock_agent_primary = MagicMock()
        mock_agent_primary.id = "agent_primary"
        mock_agent_fallback = MagicMock()
        mock_agent_fallback.id = "agent_fallback"
        
        import asyncio
        with patch("custom_components.otis_ai.config_flow._get_agents", return_value=[mock_agent_primary, mock_agent_fallback]):
            result = asyncio.run(agent.async_process(user_input))
        
        # Verify async_converse was called twice (failover occurred)
        self.assertEqual(mock_conversation.async_converse.call_count, 2)
        # 1st call targeted primary
        self.assertEqual(mock_conversation.async_converse.call_args_list[0][1]["agent_id"], "agent_primary")
        # 2nd call targeted fallback
        self.assertEqual(mock_conversation.async_converse.call_args_list[1][1]["agent_id"], "agent_fallback")
        # Result matches the successful fallback response
        self.assertEqual(result, resp_success)

    def test_automation_manager(self):
        """Test the AutomationManager class."""
        from custom_components.otis_ai.automation_manager import AutomationManager
        
        self.hass.config.path = MagicMock(side_effect=lambda x: f"/config/{x}")
        manager = AutomationManager(self.hass)
        
        # Mock load_yaml and save_yaml
        import custom_components.otis_ai.automation_manager as am
        am.yaml_util.load_yaml = MagicMock(return_value=[])
        am.yaml_util.save_yaml = MagicMock()
        
        # Test writing automation
        import asyncio
        auto_data = {"alias": "Test Auto", "trigger": [], "action": []}
        auto_id = asyncio.run(manager.async_write_automation(auto_data))
        
        self.assertIsNotNone(auto_id)
        self.assertEqual(auto_data["id"], auto_id)
        am.yaml_util.save_yaml.assert_called_once()
        
        # Test reloading
        self.hass.services.async_call = AsyncMock()
        asyncio.run(manager.async_reload_automations())
        self.hass.services.async_call.assert_called_with("automation", "reload")

    def test_conversation_agent_wizard_proposal(self):
        """Test that the agent parses proposed YAML from the LLM and stores it."""
        from custom_components.otis_ai import OtisAIConversationAgent
        
        entry = MagicMock()
        entry.options = {CONF_CONVERSATION_AGENT: "conversation.mock_llm"}
        entry.data = {}
        
        engine = MagicMock()
        engine.async_build_capability_map = AsyncMock(return_value={"integrations": [], "areas": {}, "entities": [], "orphaned_entities": []})
        
        manager = MagicMock()
        agent = OtisAIConversationAgent(self.hass, entry, engine, manager)
        
        user_input = MagicMock()
        user_input.text = "Create a fan automation"
        user_input.conversation_id = "test_conv_id"
        
        mock_llm_response = MagicMock()
        mock_llm_response.response.speech = {
            "plain": {
                "speech": "Here is the automation:\n```yaml\nalias: \"Turn on fan\"\ntrigger:\n  platform: state\n  entity_id: sensor.temp\naction:\n  service: fan.turn_on\n```"
            }
        }
        mock_conversation.async_converse = AsyncMock(return_value=mock_llm_response)
        
        import asyncio
        result = asyncio.run(agent.async_process(user_input))
        
        # Verify pending_yaml was stored in the session
        sessions = self.hass.data[DOMAIN]["sessions"]
        self.assertIn("test_conv_id", sessions)
        self.assertIn("pending_yaml", sessions["test_conv_id"])
        pending = sessions["test_conv_id"]["pending_yaml"]
        self.assertEqual(pending["type"], "automation")
        self.assertEqual(pending["yaml_data"]["alias"], "Turn on fan")
        
        # Verify confirmation prompt was appended
        self.assertIn("Would you like me to create and enable this automation", result.response.speech["plain"]["speech"])

    def test_conversation_agent_wizard_confirm(self):
        """Test that the agent applies the pending YAML when the user says yes."""
        from custom_components.otis_ai import OtisAIConversationAgent
        
        entry = MagicMock()
        engine = MagicMock()
        manager = MagicMock()
        manager.async_write_automation = AsyncMock(return_value="12345")
        manager.async_reload_automations = AsyncMock()
        
        agent = OtisAIConversationAgent(self.hass, entry, engine, manager)
        
        # Pre-populate session with pending YAML
        self.hass.data[DOMAIN] = {
            "sessions": {
                "test_conv_id": {
                    "pending_yaml": {
                        "type": "automation",
                        "yaml_data": {"alias": "Turn on fan", "trigger": [], "action": []}
                    }
                }
            }
        }
        
        user_input = MagicMock()
        user_input.text = "Yes"
        user_input.conversation_id = "test_conv_id"
        user_input.create_response = MagicMock(return_value="confirm_response")
        
        import asyncio
        result = asyncio.run(agent.async_process(user_input))
        
        # Verify automation manager was called
        manager.async_write_automation.assert_called_once()
        manager.async_reload_automations.assert_called_once()
        
        # Verify pending_yaml was cleared
        sessions = self.hass.data[DOMAIN]["sessions"]
        self.assertNotIn("pending_yaml", sessions["test_conv_id"])
        
        # Verify speech response
        user_input.create_response.assert_called_once()
        self.assertIn("successfully created and enabled the automation", user_input.create_response.call_args[1]["speech"])

    def test_conversation_agent_wizard_reject(self):
        """Test that the agent discards the pending YAML when the user says no."""
        from custom_components.otis_ai import OtisAIConversationAgent
        
        entry = MagicMock()
        engine = MagicMock()
        manager = MagicMock()
        
        agent = OtisAIConversationAgent(self.hass, entry, engine, manager)
        
        # Pre-populate session with pending YAML
        self.hass.data[DOMAIN] = {
            "sessions": {
                "test_conv_id": {
                    "pending_yaml": {
                        "type": "automation",
                        "yaml_data": {"alias": "Turn on fan", "trigger": [], "action": []}
                    }
                }
            }
        }
        
        user_input = MagicMock()
        user_input.text = "No"
        user_input.conversation_id = "test_conv_id"
        user_input.create_response = MagicMock(return_value="discard_response")
        
        import asyncio
        result = asyncio.run(agent.async_process(user_input))
        
        # Verify automation manager was NOT called
        manager.async_write_automation.assert_not_called()
        
        # Verify pending_yaml was cleared
        sessions = self.hass.data[DOMAIN]["sessions"]
        self.assertNotIn("pending_yaml", sessions["test_conv_id"])
        
        # Verify speech response
        user_input.create_response.assert_called_once()
        self.assertIn("discarded the proposed configuration", user_input.create_response.call_args[1]["speech"])

    def test_proactive_suggestions_generation(self):
        """Test that DiscoveryEngine generates rich proactive suggestions from capability map."""
        import asyncio
        from custom_components.otis_ai import DiscoveryEngine

        engine = DiscoveryEngine(self.hass)
        test_cap_map = {
            "integrations": ["light", "climate", "lock"],
            "areas": {
                "kitchen": {
                    "name": "Kitchen",
                    "entities": ["light.kitchen_island", "binary_sensor.kitchen_motion"],
                }
            },
            "entities": [
                {"entity_id": "light.kitchen_island", "domain": "light", "name": "Kitchen Island"},
                {"entity_id": "binary_sensor.kitchen_motion", "domain": "binary_sensor", "name": "Kitchen Motion"},
                {"entity_id": "climate.living_room", "domain": "climate", "name": "Living Room AC"},
                {"entity_id": "binary_sensor.patio_door_opening", "domain": "binary_sensor", "name": "Patio Door"},
                {"entity_id": "lock.front_door", "domain": "lock", "name": "Front Door Lock"},
            ],
            "orphaned_entities": [
                {"entity_id": "switch.dead_plug_1", "domain": "switch"},
                {"entity_id": "sensor.dead_temp_2", "domain": "sensor"},
            ],
        }

        suggestions = asyncio.run(engine.async_generate_proactive_suggestions(test_cap_map))
        s_ids = {s["id"] for s in suggestions}

        # Verify orphan cleanup suggestion generated
        self.assertIn("cleanup_orphans_2", s_ids)
        cleanup_s = next(s for s in suggestions if s["id"] == "cleanup_orphans_2")
        self.assertEqual(cleanup_s["category"], "cleanup")
        self.assertEqual(cleanup_s["action_type"], "cleanup_orphans")
        self.assertEqual(cleanup_s["action_payload"]["entity_ids"], ["switch.dead_plug_1", "sensor.dead_temp_2"])

        # Verify area motion light suggestion generated with auto-off after 5 minutes
        self.assertIn("motion_light_kitchen", s_ids)
        motion_s = next(s for s in suggestions if s["id"] == "motion_light_kitchen")
        self.assertEqual(motion_s["category"], "automation")
        self.assertEqual(motion_s["action_payload"]["trigger"][0]["entity_id"], "binary_sensor.kitchen_motion")
        self.assertEqual(motion_s["action_payload"]["mode"], "restart")
        self.assertEqual(len(motion_s["action_payload"]["action"]), 3)
        self.assertIn("wait_for_trigger", motion_s["action_payload"]["action"][1])
        self.assertEqual(motion_s["action_payload"]["action"][2]["service"], "light.turn_off")

        # Verify O(1) cached suggestion lookup
        self.assertEqual(engine.get_cached_suggestion("motion_light_kitchen"), motion_s)
        self.assertIsNone(engine.get_cached_suggestion("nonexistent_id"))

        # Verify climate open-door energy guard suggestion generated
        self.assertIn("climate_door_window_guard", s_ids)
        climate_s = next(s for s in suggestions if s["id"] == "climate_door_window_guard")
        self.assertEqual(climate_s["category"], "energy")
        self.assertEqual(climate_s["action_payload"]["trigger"][0]["entity_id"], "binary_sensor.patio_door_opening")

        # Verify bedtime routine suggestion generated
        self.assertIn("bedtime_goodnight_routine", s_ids)

    def test_apply_suggestion_services(self):
        """Test async_setup_entry registers and executes apply_suggestion service."""
        import asyncio
        from custom_components.otis_ai import async_setup_entry, DOMAIN

        entry = MagicMock()
        entry.entry_id = "test_entry_suggestions"
        entry.data = {}
        entry.options = {}

        # Reset hass registered services
        registered_services = {}
        def mock_register(domain, service, handler, **kwargs):
            registered_services[(domain, service)] = handler
        self.hass.services.async_register = mock_register

        asyncio.run(async_setup_entry(self.hass, entry))

        # Check services were registered
        self.assertIn((DOMAIN, "get_capability_map"), registered_services)
        self.assertIn((DOMAIN, "get_suggestions"), registered_services)
        self.assertIn((DOMAIN, "apply_suggestion"), registered_services)
        self.assertIn((DOMAIN, "chat"), registered_services)

        # Test get_capability_map includes conversation_agent_id
        cap_handler = registered_services[(DOMAIN, "get_capability_map")]
        cap_call = MagicMock()
        cap_res = asyncio.run(cap_handler(cap_call))
        self.assertEqual(cap_res.get("conversation_agent_id"), entry.entry_id)

        # Test chat service handler
        chat_handler = registered_services[(DOMAIN, "chat")]
        agent = self.hass.data[DOMAIN][entry.entry_id]["agent"]
        mock_chat_result = MagicMock()
        mock_chat_result.response.speech = {"plain": {"speech": "I am Otis, your smart home co-pilot."}}
        mock_chat_result.conversation_id = "conv_thread_1"
        agent.async_process = AsyncMock(return_value=mock_chat_result)

        chat_call = MagicMock()
        chat_call.data = {"text": "hello otis", "conversation_id": "conv_thread_1"}
        chat_call.context = MagicMock()
        chat_res = asyncio.run(chat_handler(chat_call))
        self.assertIn("I am Otis", chat_res["response"])
        self.assertEqual(chat_res["conversation_id"], "conv_thread_1")

        # Test apply_suggestion handler for creating automation
        apply_handler = registered_services[(DOMAIN, "apply_suggestion")]
        auto_mgr = self.hass.data[DOMAIN][entry.entry_id]["automation_manager"]
        auto_mgr.async_write_automation = AsyncMock(return_value="auto_12345")
        auto_mgr.async_reload_automations = AsyncMock(return_value=True)

        # Mock capability map returning a suggestion
        engine = MagicMock()
        engine.async_build_capability_map = AsyncMock(return_value={
            "proactive_suggestions": [{
                "id": "motion_light_kitchen",
                "title": "Motion-Activated Lighting in Kitchen",
                "action_type": "create_automation",
                "action_payload": {"alias": "Motion Kitchen", "trigger": [], "action": []}
            }]
        })

        # Replace engine in setup closure test
        self.hass.data[DOMAIN][entry.entry_id]["engine"] = engine
        call = MagicMock()
        call.data = {"suggestion_id": "motion_light_kitchen"}

        # Running apply_suggestion with our mock call
        res = asyncio.run(apply_handler(call))
        self.assertTrue(res["success"])
        self.assertIn("auto_12345", res["id"])
        auto_mgr.async_write_automation.assert_called_once()
        auto_mgr.async_reload_automations.assert_called_once()

    def test_async_setup_frontend_path(self):
        """Test async_setup registers the frontend static path for the Lovelace card."""
        import asyncio
        from custom_components.otis_ai import async_setup

        self.hass.http = MagicMock()
        self.hass.http.register_static_path = MagicMock()
        self.hass.http.async_register_static_paths = AsyncMock()

        res = asyncio.run(async_setup(self.hass, {}))
        self.assertTrue(res)

    def test_config_flow_import(self):
        """Test config flow import step creates entry with defaults."""
        import asyncio
        from custom_components.otis_ai.config_flow import OtisAIConfigFlow

        flow = OtisAIConfigFlow()
        flow.hass = self.hass

        res = asyncio.run(flow.async_step_import({"theme_name": "custom_glass"}))
        self.assertEqual(res["type"], "create_entry")
    def test_cluster_sequences_to_routines(self):
        """Test clustering temporal state sequences into automated routine proposals."""
        from custom_components.otis_ai import cluster_sequences_to_routines

        base_time = 1779966000.0  # Morning ~7:00 AM Eastern
        synthetic_rows = []
        for day in range(3):
            day_offset = day * 86400
            synthetic_rows.extend([
                ("binary_sensor.sleepnumber_super_sleep_resident_is_in_bed", "off", base_time + day_offset),
                ("binary_sensor.gym_motion", "on", base_time + day_offset + 60),
                ("select.gym_diffuser", "on", base_time + day_offset + 120),
            ])

        proposals = cluster_sequences_to_routines(synthetic_rows)
        self.assertTrue(len(proposals) > 0)
        gym_prop = next((p for p in proposals if "Morning Gym" in p["name"]), None)
        self.assertIsNotNone(gym_prop)
        self.assertEqual(gym_prop["trigger_entity"], "binary_sensor.sleepnumber_super_sleep_resident_is_in_bed")
        self.assertEqual(gym_prop["trigger_state"], "off")
        self.assertTrue(any(act["entity_id"] == "binary_sensor.gym_motion" for act in gym_prop["actions"]))
        self.assertEqual(gym_prop["action_type"], "create_automation")
        self.assertIn("alias", gym_prop["action_payload"])

        # Ensure sensor-only or opposite-side (backyard -> frontdoor) sequences are rejected
        bad_rows = []
        for day in range(3):
            day_offset = day * 86400
            bad_rows.extend([
                ("binary_sensor.backyard_motion", "on", base_time + day_offset),
                ("binary_sensor.frontdoor_motion", "on", base_time + day_offset + 30),
                ("light.frontdoor_porch", "on", base_time + day_offset + 45),
            ])
        bad_proposals = cluster_sequences_to_routines(bad_rows)
        self.assertEqual(len(bad_proposals), 0)

    def test_discovery_engine_mine_historical_habits(self):
        """Test DiscoveryEngine querying SQLite recorder database for habit routines."""
        import asyncio
        import tempfile
        import sqlite3
        import time
        from custom_components.otis_ai import DiscoveryEngine

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # Create mock HA recorder SQLite schema
            conn = sqlite3.connect(tmp_path)
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE states_meta (
                    metadata_id INTEGER PRIMARY KEY,
                    entity_id VARCHAR(255) UNIQUE
                )
            """)
            cur.execute("""
                CREATE TABLE states (
                    state_id INTEGER PRIMARY KEY,
                    metadata_id INTEGER,
                    state VARCHAR(255),
                    last_updated_ts FLOAT
                )
            """)
            cur.execute("INSERT INTO states_meta VALUES (1, 'binary_sensor.bedroom_motion')")
            cur.execute("INSERT INTO states_meta VALUES (2, 'light.kitchen')")

            base_ts = time.time() - (3 * 86400)
            for d in range(3):
                offset = d * 86400
                # Day event: motion turns on, light turns on
                cur.execute("INSERT INTO states VALUES (NULL, 1, 'on', ?)", (base_ts + offset,))
                cur.execute("INSERT INTO states VALUES (NULL, 2, 'on', ?)", (base_ts + offset + 45,))
                # After 300s: motion turns off, light turns off
                cur.execute("INSERT INTO states VALUES (NULL, 1, 'off', ?)", (base_ts + offset + 600,))
                cur.execute("INSERT INTO states VALUES (NULL, 2, 'off', ?)", (base_ts + offset + 1200,))

            conn.commit()
            conn.close()

            # Mock hass.config.path to return our temp db
            self.hass.config.path = MagicMock(return_value=tmp_path)
            async def fake_executor(func, *args):
                return func(*args)

            self.hass.async_add_executor_job = fake_executor

            engine = DiscoveryEngine(self.hass)
            routines = asyncio.run(engine.async_mine_historical_habits(days=7))

            self.assertTrue(len(routines) > 0)
            self.assertEqual(routines[0]["trigger_entity"], "binary_sensor.bedroom_motion")
            self.assertEqual(routines[0]["trigger_state"], "on")
            self.assertEqual(routines[0]["actions"][0]["entity_id"], "light.kitchen")

        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def tearDown(self):
        if hasattr(self, "temp_test_dir"):
            self.temp_test_dir.cleanup()


class TestSpatialGraphManager(unittest.TestCase):
    """Test suite for the SpatialGraphManager and topological area connection engine."""

    def setUp(self):
        self.hass = MagicMock()
        self.hass.data = {}
        self.hass.config = MagicMock()
        self.hass.config.components = ["light", "binary_sensor"]

        # Setup mock areas in area_registry
        area_reg = MagicMock()
        foyer = MagicMock(id="foyer", name="Foyer", aliases=[])
        hallway = MagicMock(id="hallway", name="Hallway", aliases=[])
        master = MagicMock(id="master", name="Master", aliases=[])
        master_bath = MagicMock(id="master_bath", name="Master Bath", aliases=[])
        kitchen = MagicMock(id="kitchen", name="Kitchen", aliases=[])
        great_room = MagicMock(id="great_room", name="Great Room", aliases=[])

        area_reg.async_list_areas.return_value = [foyer, hallway, master, master_bath, kitchen, great_room]
        sys.modules["homeassistant.helpers.area_registry"].async_get.return_value = area_reg

    def test_spatial_graph_default_inference_and_crud(self):
        """Verify spatial graph infers defaults and allows connecting/disconnecting rooms."""
        from custom_components.otis_ai.spatial_manager import SpatialGraphManager

        mgr = SpatialGraphManager(self.hass, storage_key="test_spatial_graph_1")
        graph = asyncio.run(mgr.async_load())

        self.assertIn("connections", graph)
        self.assertIn("adjacencies", graph)
        self.assertTrue(len(graph["connections"]) > 0)

        # Verify Foyer connects to Hallway and Great Room by default
        foyer_neighbors = mgr.get_adjacent_areas("foyer")
        self.assertIn("hallway", foyer_neighbors)
        self.assertIn("great_room", foyer_neighbors)

        # Test adding a custom connection: Kitchen <-> Hallway
        updated = asyncio.run(mgr.async_update_connection("kitchen", "hallway", connected=True, connection_type="door"))
        self.assertIn("hallway", mgr.get_adjacent_areas("kitchen"))
        self.assertIn("kitchen", mgr.get_adjacent_areas("hallway"))

        # Test removing a connection: Foyer <-> Great Room
        asyncio.run(mgr.async_update_connection("foyer", "great_room", connected=False))
        self.assertNotIn("great_room", mgr.get_adjacent_areas("foyer"))

    def test_spatial_graph_pathfinding(self):
        """Verify BFS pathfinding traverses adjacent rooms correctly."""
        from custom_components.otis_ai.spatial_manager import SpatialGraphManager

        mgr = SpatialGraphManager(self.hass, storage_key="test_spatial_graph_2")
        asyncio.run(mgr.async_load())

        # Path from foyer to master_bath: foyer -> hallway -> master -> master_bath
        path = mgr.find_path("foyer", "master_bath")
        self.assertEqual(path, ["foyer", "hallway", "master", "master_bath"])

        # Path to self
        self.assertEqual(mgr.find_path("kitchen", "kitchen"), ["kitchen"])

        # Non-existent area
        self.assertEqual(mgr.find_path("foyer", "non_existent_room"), [])

    def test_discovery_engine_spatial_integration(self):
        """Verify DiscoveryEngine embeds spatial_graph and adjacent_areas into capability_map."""
        from custom_components.otis_ai.spatial_manager import SpatialGraphManager

        mgr = SpatialGraphManager(self.hass, storage_key="test_spatial_graph_3")
        engine = DiscoveryEngine(self.hass, spatial_manager=mgr)

        cap_map = asyncio.run(engine.async_build_capability_map())
        self.assertIn("spatial_graph", cap_map)
        self.assertIn("adjacencies", cap_map["spatial_graph"])
        self.assertIn("foyer", cap_map["areas"])
        self.assertIn("adjacent_areas", cap_map["areas"]["foyer"])

    def test_contextual_pathway_lighting_suggestion(self):
        """Verify DiscoveryEngine suggests contextual pathway lighting for adjacent rooms."""
        from custom_components.otis_ai.spatial_manager import SpatialGraphManager

        mgr = SpatialGraphManager(self.hass, storage_key="test_spatial_graph_4")
        engine = DiscoveryEngine(self.hass, spatial_manager=mgr)

        # Setup entities: Foyer has motion sensor, connected Hallway has light
        mock_cap_map = {
            "integrations": ["light", "binary_sensor"],
            "areas": {
                "foyer": {
                    "name": "Foyer",
                    "entities": ["binary_sensor.foyer_motion"],
                },
                "hallway": {
                    "name": "Hallway",
                    "entities": ["light.hallway_ceiling"],
                },
            },
            "entities": [
                {"entity_id": "binary_sensor.foyer_motion", "name": "Foyer Motion", "domain": "binary_sensor"},
                {"entity_id": "light.hallway_ceiling", "name": "Hallway Ceiling", "domain": "light"},
            ],
            "orphaned_entities": [],
            "spatial_graph": {
                "adjacencies": {
                    "foyer": ["hallway"],
                    "hallway": ["foyer"],
                }
            },
        }

        suggestions = asyncio.run(engine.async_generate_proactive_suggestions(mock_cap_map))
        pathway_suggestions = [s for s in suggestions if s.get("id", "").startswith("spatial_pathway_")]
        self.assertTrue(len(pathway_suggestions) > 0)
        self.assertEqual(pathway_suggestions[0]["action_payload"]["action"][0]["target"]["entity_id"], "light.hallway_ceiling")

    def test_shared_entity_and_area_helpers_and_cache(self):
        """Verify shared classify_area_entities, build_area_lookup_map, and DiscoveryEngine TTL caching."""
        from custom_components.otis_ai.spatial_manager import (
            SpatialGraphManager,
            build_area_lookup_map,
            classify_area_entities,
            resolve_area_identifier,
        )

        lookup = build_area_lookup_map([
            {"id": "great_room", "name": "Great Room"},
            {"id": "home_office", "name": "Home Office"},
        ])
        self.assertEqual(resolve_area_identifier("Great Room", lookup), "great_room")
        self.assertEqual(resolve_area_identifier("Home Office", lookup), "home_office")
        self.assertEqual(resolve_area_identifier("unknown_room", lookup), "")

        buckets = classify_area_entities([
            "light.kitchen_spots",
            "binary_sensor.kitchen_motion",
            "binary_sensor.back_door_contact",
            "climate.downstairs",
            "media_player.kitchen",
            "camera.kitchen_cam",
            "lock.back_door",
            "cover.garage_door",
            "switch.disposal",
        ])
        self.assertEqual(buckets["lights"], ["light.kitchen_spots"])
        self.assertEqual(buckets["motion"], ["binary_sensor.kitchen_motion"])
        self.assertEqual(buckets["contact"], ["binary_sensor.back_door_contact"])
        self.assertEqual(buckets["climates"], ["climate.downstairs"])
        self.assertEqual(buckets["media"], ["media_player.kitchen"])
        self.assertEqual(buckets["cameras"], ["camera.kitchen_cam"])
        self.assertEqual(buckets["locks"], ["lock.back_door"])
        self.assertEqual(buckets["covers"], ["cover.garage_door"])
        self.assertEqual(buckets["switches"], ["switch.disposal"])

        mgr = SpatialGraphManager(self.hass, storage_key="test_spatial_graph_cache")
        engine = DiscoveryEngine(self.hass, spatial_manager=mgr)
        map1 = asyncio.run(engine.async_build_capability_map())
        self.assertIsNotNone(engine._cached_cap_map)
        map2 = asyncio.run(engine.async_build_capability_map())
        self.assertEqual(map1["areas"], map2["areas"])
        engine.invalidate_cache()
        self.assertIsNone(engine._cached_cap_map)


class TestFloorplanParser(unittest.TestCase):
    """Test suite for the multimodal FloorplanParser engine."""

    def setUp(self):
        self.hass = MagicMock()
        self.hass.data = {}
        self.hass.config = MagicMock()
        self.hass.config.components = ["light", "binary_sensor"]

        tmp_dir = "/tmp/otis_test_floorplan"
        os.makedirs(tmp_dir, exist_ok=True)
        storage_dir = os.path.join(tmp_dir, ".storage")
        if os.path.isdir(storage_dir):
            import shutil
            shutil.rmtree(storage_dir, ignore_errors=True)
        for stale in ("automations.yaml", "scripts.yaml", "configuration.yaml"):
            sp = os.path.join(tmp_dir, stale)
            if os.path.exists(sp):
                os.remove(sp)
        self.hass.config.path = lambda p: os.path.join(tmp_dir, p)
        self.hass.async_add_executor_job = lambda f, *args: asyncio.sleep(0, result=f(*args)) if asyncio.iscoroutinefunction(f) else asyncio.get_event_loop().run_in_executor(None, f, *args)

    def test_classify_area_zone(self):
        """Verify area zone classification (outdoor vs upper vs main)."""
        from custom_components.otis_ai.floorplan_parser import classify_area_zone

        self.assertEqual(classify_area_zone("backyard", "Backyard"), "outdoor")
        self.assertEqual(classify_area_zone("pool", "Pool"), "outdoor")
        self.assertEqual(classify_area_zone("frontyard", "Frontyard"), "outdoor")
        self.assertEqual(classify_area_zone("master", "Master Bedroom"), "upper")
        self.assertEqual(classify_area_zone("master_bath", "Master Bath"), "upper")
        self.assertEqual(classify_area_zone("theater", "Theater"), "upper")
        self.assertEqual(classify_area_zone("foyer", "Foyer"), "main")
        self.assertEqual(classify_area_zone("kitchen", "Kitchen"), "main")
        self.assertEqual(classify_area_zone("great_room", "Great Room"), "main")

    def test_parse_speech_callouts(self):
        """Verify sequential extraction of spoken room names from walkthrough transcript."""
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        parser = FloorplanParser(self.hass)
        areas = [
            {"id": "foyer", "name": "Foyer"},
            {"id": "great_room", "name": "Great Room"},
            {"id": "kitchen", "name": "Kitchen"},
            {"id": "backyard", "name": "Backyard"},
            {"id": "pool", "name": "Pool"},
        ]

        sample_transcript = (
            "Starting our walkthrough here in the Foyer. "
            "Now moving directly into the Great Room, and over on the left is our Kitchen. "
            "Next we step outside through the sliding doors to the Backyard, and right over here is the Pool."
        )

        callouts = parser.parse_speech_callouts(sample_transcript, areas)
        self.assertEqual(len(callouts), 5)
        self.assertEqual([c["area_id"] for c in callouts], ["foyer", "great_room", "kitchen", "backyard", "pool"])

    def test_svg_floorplan_generation(self):
        """Verify vector SVG floorplan generation and Lovelace card YAML synthesis."""
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        parser = FloorplanParser(self.hass)
        mock_cap_map = {
            "areas": {
                "foyer": {"name": "Foyer", "entities": ["light.foyer_lights"]},
                "great_room": {"name": "Great Room", "entities": ["light.great_room", "binary_sensor.motion_gr"]},
                "kitchen": {"name": "Kitchen", "entities": ["light.kitchen"]},
                "master": {"name": "Master", "entities": ["light.master"]},
                "backyard": {"name": "Backyard", "entities": ["light.floodlight"]},
            },
            "entities": [
                {"entity_id": "light.foyer_lights", "name": "Foyer Lights", "domain": "light"},
                {"entity_id": "light.great_room", "name": "Great Room Lights", "domain": "light"},
                {"entity_id": "binary_sensor.motion_gr", "name": "Great Room Motion", "domain": "binary_sensor"},
                {"entity_id": "light.kitchen", "name": "Kitchen", "domain": "light"},
                {"entity_id": "light.master", "name": "Master", "domain": "light"},
                {"entity_id": "light.floodlight", "name": "Floodlight", "domain": "light"},
            ],
            "spatial_graph": {
                "adjacencies": {
                    "foyer": ["great_room"],
                    "great_room": ["foyer", "kitchen", "backyard"],
                    "kitchen": ["great_room"],
                    "backyard": ["great_room"],
                }
            },
        }

        # Run SVG generation
        res = asyncio.run(parser.async_generate_svg_floorplan(mock_cap_map, output_relative_path="test_fp.svg"))
        self.assertTrue(res["success"])
        self.assertEqual(res["room_count"], 5)
        self.assertIn("main", res["zones"])
        self.assertIn("lovelace_yaml", res)

        # Verify output file content
        svg_file_path = self.hass.config.path("test_fp.svg")
        self.assertTrue(os.path.exists(svg_file_path))

        with open(svg_file_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("<svg", content)
        self.assertIn("data-area-id=\"foyer\"", content)
        self.assertIn("data-area-id=\"great_room\"", content)
        self.assertIn("Ground / Main Floor", content)
        self.assertIn("Outdoor &amp; Perimeter", content)

    def test_update_floorplan_layout(self):
        """Verify Phase 4 interactive layout update: device pin repositioning and room boundary resizing."""
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        parser = FloorplanParser(self.hass)
        mock_cap_map = {
            "areas": {
                "foyer": {"name": "Foyer", "entities": ["light.foyer_lights"]},
                "kitchen": {"name": "Kitchen", "entities": ["light.kitchen"]},
            },
            "entities": [
                {"entity_id": "light.foyer_lights", "name": "Foyer Lights", "domain": "light"},
                {"entity_id": "light.kitchen", "name": "Kitchen", "domain": "light"},
            ],
            "spatial_graph": {"adjacencies": {"foyer": ["kitchen"]}},
        }

        # 1. Generate baseline SVG
        asyncio.run(parser.async_generate_svg_floorplan(mock_cap_map, output_relative_path="test_edit_fp.svg"))

        # 2. Update layout with new marker coordinates and resized room footprint
        update_res = asyncio.run(
            parser.async_update_floorplan_layout(
                badges=[{"entity_id": "light.foyer_lights", "x": 120.5, "y": 250.5}],
                rooms=[{"id": "foyer", "x": 55.0, "y": 65.0, "width": 210.0, "height": 190.0, "name": "Grand Foyer"}],
                svg_relative_path="test_edit_fp.svg",
            )
        )
        self.assertTrue(update_res["success"])
        self.assertEqual(update_res["updated_badges"], 1)
        self.assertEqual(update_res["updated_rooms"], 1)

        # 3. Verify changes persisted directly into SVG markup
        svg_file_path = self.hass.config.path("test_edit_fp.svg")
        with open(svg_file_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('data-entity-id="light.foyer_lights"', content)
        self.assertIn('transform="translate(120.5, 250.5)"', content)
        self.assertIn('x="55.0" y="65.0" width="210.0" height="190.0"', content)
        self.assertIn("Grand Foyer", content)

        # 4. Graceful handling when SVG file not found
        err_res = asyncio.run(
            parser.async_update_floorplan_layout(
                badges=[{"entity_id": "light.nonexistent", "x": 0, "y": 0}],
                svg_relative_path="nonexistent_fp.svg",
            )
        )
        self.assertFalse(err_res["success"])
        self.assertIn("not found", err_res["error"])

    def test_delete_room_layout(self):
        """Verify FloorplanParser room deletion from SVG and metadata tracking."""
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        parser = FloorplanParser(self.hass)
        mock_cap_map = {
            "areas": {
                "foyer": {"name": "Foyer", "entities": ["light.foyer_lights"]},
                "garage": {"name": "Garage", "entities": ["light.garage_lights"]},
            },
            "entities": [
                {"entity_id": "light.foyer_lights", "name": "Foyer Lights", "area_id": "foyer", "domain": "light", "state": "on"},
                {"entity_id": "light.garage_lights", "name": "Garage Lights", "area_id": "garage", "domain": "light", "state": "on"},
            ],
            "spatial_graph": {"adjacencies": {}},
        }

        # Generate baseline SVG
        asyncio.run(parser.async_generate_svg_floorplan(mock_cap_map, output_relative_path="test_del_fp.svg"))

        # Verify garage is in SVG initially
        svg_file = self.hass.config.path("test_del_fp.svg")
        with open(svg_file, "r") as f:
            self.assertIn('data-area-id="garage"', f.read())

        # Delete garage
        res = asyncio.run(
            parser.async_update_floorplan_layout(
                deleted_rooms=["garage"],
                svg_relative_path="test_del_fp.svg",
            )
        )
        self.assertTrue(res["success"])
        self.assertGreater(res["deleted_rooms"], 0)
        self.assertIn("garage", parser._metadata.get("deleted_rooms", []))

        # Verify garage is removed from SVG
        with open(svg_file, "r") as f:
            content = f.read()
            self.assertNotIn('data-area-id="garage"', content)
            self.assertIn('data-area-id="foyer"', content)

    def test_delete_badge_layout(self):
        """Verify FloorplanParser badge entity deletion from SVG and custom layout metadata."""
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        parser = FloorplanParser(self.hass)
        mock_cap_map = {
            "areas": {
                "foyer": {"name": "Foyer", "entities": ["light.foyer_lights"]},
            },
            "entities": [
                {"entity_id": "light.foyer_lights", "name": "Foyer Lights", "area_id": "foyer", "domain": "light", "state": "on"},
            ],
            "spatial_graph": {"adjacencies": {}},
        }

        # Generate baseline SVG
        asyncio.run(parser.async_generate_svg_floorplan(mock_cap_map, output_relative_path="test_badge_del.svg"))

        # Verify badge is in SVG
        svg_file = self.hass.config.path("test_badge_del.svg")
        with open(svg_file, "r") as f:
            self.assertIn('data-entity-id="light.foyer_lights"', f.read())

        # Delete badge
        res = asyncio.run(
            parser.async_update_floorplan_layout(
                badges=[{"entity_id": "light.foyer_lights", "delete": True}],
                svg_relative_path="test_badge_del.svg",
            )
        )
        self.assertTrue(res["success"])

        # Verify badge is removed from SVG
        with open(svg_file, "r") as f:
            content = f.read()
            self.assertNotIn('data-entity-id="light.foyer_lights"', content)

    def test_floorplan_svg_sanitization_and_subzone_sync(self):
        """Verify FloorplanParser repairs corrupted SVG text and synchronizes subzone pills."""
        from custom_components.otis_ai.floorplan_parser import (
            FloorplanParser,
            sanitize_corrupted_svg_text,
            find_room_group_span,
        )

        corrupted_sample = (
            '<svg><g class="room-group" data-area-id="frontyard">'
            '<rect x="257.0" y="586.0" width="922.0" height="102.0" class="room-box outdoor-box" />'
            '<text class="room-header"> x="271.0" y="608.0">Frontyard</text>'
            '<text class="subzone-pill"> x="273.0" y="626.0">▪ Front Porch &amp; Doorbell Cam</text>'
            '<g class="entity-badge" data-entity-id="light.front"><circle cx="0" cy="0" r="9" /><text>💡</text></g>'
            '</g></svg>'
        )

        # 1. Verify sanitizer cleans corrupted tags into valid SVG attributes
        repaired = sanitize_corrupted_svg_text(corrupted_sample)
        self.assertIn('<text x="271.0" y="608.0" class="room-header">Frontyard</text>', repaired)
        self.assertIn('<text x="273.0" y="626.0" class="subzone-pill">▪ Front Porch &amp; Doorbell Cam</text>', repaired)

        # 2. Verify find_room_group_span matches the full room group despite nested entity-badge </g>
        span = find_room_group_span(repaired, "frontyard")
        self.assertIsNotNone(span)
        start_idx, end_idx, header, inner = span
        self.assertIn('data-entity-id="light.front"', inner)
        self.assertTrue(repaired[start_idx:end_idx].endswith("</g>"))

        # 3. Test async_update_floorplan_layout on corrupted SVG file
        test_path = self.hass.config.path("test_corrupted_fp.svg")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(corrupted_sample)

        parser = FloorplanParser(self.hass)
        res = asyncio.run(
            parser.async_update_floorplan_layout(
                rooms=[{"id": "frontyard", "x": 260.0, "y": 590.0, "width": 900.0, "height": 110.0, "name": "Front Yard"}],
                svg_relative_path="test_corrupted_fp.svg",
            )
        )
        self.assertTrue(res["success"])
        with open(test_path, "r", encoding="utf-8") as f:
            updated_content = f.read()

        # Check valid attributes and text placement
        self.assertIn('<text x="274.0" y="612.0" class="room-header">Front Yard</text>', updated_content)
        self.assertIn('<text x="276.0" y="630.0" class="subzone-pill">▪ Front Porch &amp; Doorbell Cam</text>', updated_content)
        self.assertNotIn('> x="', updated_content)

    def test_proactive_floorplan_suggestion(self):
        """Verify that DiscoveryEngine suggests recording a walkthrough when no floorplan exists."""
        from custom_components.otis_ai import DiscoveryEngine
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        parser = FloorplanParser(self.hass)
        engine = DiscoveryEngine(self.hass, floorplan_parser=parser)

        # Mock capability map with no floorplan
        cap_map = {
            "areas": {"foyer": {"name": "Foyer", "entities": []}},
            "entities": [],
            "orphaned_entities": [],
            "spatial_graph": {"adjacencies": {}},
        }

        suggestions = asyncio.run(engine.async_generate_proactive_suggestions(cap_map))
        walkthrough_sugg = next((s for s in suggestions if s["id"] == "record_walkthrough_floorplan"), None)
        self.assertIsNotNone(walkthrough_sugg)
        self.assertEqual(walkthrough_sugg["action_type"], "upload_walkthrough")
        self.assertEqual(walkthrough_sugg["category"], "visualization")

    def test_floorplan_walkthrough_status_and_keyword_args(self):
        """Verify that FloorplanParser handles video_path and spoken_order without error and tracks walkthrough status."""
        from custom_components.otis_ai import DiscoveryEngine
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        parser = FloorplanParser(self.hass)
        self.assertFalse(parser.has_walkthrough())

        mock_cap_map = {
            "areas": {
                "foyer": {"name": "Foyer", "entities": ["light.foyer"]},
                "kitchen": {"name": "Kitchen", "entities": ["light.kitchen"]},
            },
            "entities": [{"entity_id": "light.foyer", "name": "Foyer", "domain": "light"}],
            "spatial_graph": {"adjacencies": {}},
        }

        # Test generation with video_path and spoken_order keyword arguments
        res = asyncio.run(parser.async_generate_svg_floorplan(
            mock_cap_map,
            output_relative_path="test_walkthrough_fp.svg",
            video_path="/tmp/mock_video.mp4",
            spoken_order="foyer, kitchen",
        ))
        self.assertTrue(res["success"])
        self.assertTrue(res["walkthrough_completed"])
        self.assertTrue(parser.has_walkthrough())
        self.assertIn("lovelace_yaml", res)

        # Test DiscoveryEngine with completed walkthrough - should not recommend walkthrough
        engine = DiscoveryEngine(self.hass, floorplan_parser=parser)
        suggestions = asyncio.run(engine.async_generate_proactive_suggestions(mock_cap_map))
        walkthrough_sugg = next((s for s in suggestions if s["id"] == "record_walkthrough_floorplan"), None)
        self.assertIsNone(walkthrough_sugg)

    def test_proactive_suggestions_priority_ordering(self):
        """Verify that proactive suggestions in the Feed are strictly sorted High -> Medium -> Low."""
        from custom_components.otis_ai import DiscoveryEngine
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        parser = FloorplanParser(self.hass)
        engine = DiscoveryEngine(self.hass, floorplan_parser=parser)

        cap_map = {
            "areas": {
                "kitchen": {
                    "name": "Kitchen",
                    "entities": ["light.kitchen", "binary_sensor.kitchen_motion"],
                }
            },
            "entities": [
                {"entity_id": "light.kitchen", "name": "Kitchen Light", "domain": "light"},
                {"entity_id": "light.foyer", "name": "Foyer Light", "domain": "light"},
                {"entity_id": "binary_sensor.kitchen_motion", "name": "Kitchen Motion", "domain": "binary_sensor"},
                {"entity_id": "climate.main", "name": "Main HVAC", "domain": "climate"},
                {"entity_id": "binary_sensor.front_door_contact", "name": "Front Door", "domain": "binary_sensor"},
            ],
            "orphaned_entities": [{"entity_id": "sensor.orphan_1"}],
            "spatial_graph": {"adjacencies": {}},
        }

        suggestions = asyncio.run(engine.async_generate_proactive_suggestions(cap_map))
        priorities = [s.get("priority") for s in suggestions]
        priority_rank = {"high": 0, "medium": 1, "low": 2}
        ranks = [priority_rank[p] for p in priorities]

        # Ensure we have high, medium, and low priorities represented and sorted monotonically
        self.assertIn("high", priorities)
        self.assertIn("medium", priorities)
        self.assertIn("low", priorities)
        self.assertEqual(ranks, sorted(ranks))

    def test_floorplan_layout_no_overlaps_across_zones(self):
        """Verify that 19 areas across Main, Upper, and Outdoor zones never overlap bounding boxes."""
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        parser = FloorplanParser(self.hass)
        zones = {
            "main": [
                {"id": f"main_{i}", "name": f"Main {i}", "entities": [], "adjacent_areas": []}
                for i in range(12)
            ],
            "upper": [
                {"id": f"upper_{i}", "name": f"Upper {i}", "entities": [], "adjacent_areas": []}
                for i in range(4)
            ],
            "outdoor": [
                {"id": f"outdoor_{i}", "name": f"Outdoor {i}", "entities": [], "adjacent_areas": []}
                for i in range(3)
            ],
        }
        layout = parser._calculate_orthogonal_layout(zones)
        all_rooms = layout["main"] + layout["upper"] + layout["outdoor"]
        self.assertEqual(len(all_rooms), 19)

        # Verify no two room bounding boxes overlap
        for i in range(len(all_rooms)):
            r1 = all_rooms[i]
            for j in range(i + 1, len(all_rooms)):
                r2 = all_rooms[j]
                overlap_x = (r1["x"] < r2["x"] + r2["width"]) and (r2["x"] < r1["x"] + r1["width"])
                overlap_y = (r1["y"] < r2["y"] + r2["height"]) and (r2["y"] < r1["y"] + r1["height"])
                self.assertFalse(
                    overlap_x and overlap_y,
                    f"Room {r1['id']} ({r1['x']},{r1['y']}) overlaps with {r2['id']} ({r2['x']},{r2['y']})",
                )

    def test_cleanup_previous_uploads_and_spoken_order_persistence(self):
        """Verify that previous walkthrough files are cleaned up and spoken_order persists in metadata."""
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        parser = FloorplanParser(self.hass)
        upload_dir = self.hass.config.path("www")
        os.makedirs(upload_dir, exist_ok=True)

        old_vid = os.path.join(upload_dir, "walkthrough_upload_2.mp4")
        old_aud = os.path.join(upload_dir, "walkthrough_audio_2.mp3")
        keep_svg = os.path.join(upload_dir, "otis_floorplan.svg")
        with open(old_vid, "wb") as f:
            f.write(b"123")
        with open(old_aud, "wb") as f:
            f.write(b"456")
        with open(keep_svg, "w", encoding="utf-8") as f:
            f.write("<svg></svg>")

        removed = parser.cleanup_previous_uploads(upload_dir)
        self.assertGreaterEqual(removed, 2)
        self.assertFalse(os.path.exists(old_vid))
        self.assertFalse(os.path.exists(old_aud))
        self.assertTrue(os.path.exists(keep_svg))

        mock_cap_map = {
            "areas": {
                "foyer": {"name": "Foyer", "entities": []},
                "kitchen": {"name": "Kitchen", "entities": []},
            },
            "entities": [],
            "spatial_graph": {"adjacencies": {}},
        }
        res1 = asyncio.run(
            parser.async_generate_svg_floorplan(
                mock_cap_map,
                output_relative_path="test_persist_fp.svg",
                spoken_order=["kitchen", "foyer"],
                walkthrough_completed=True,
                transcripts=["Walking into Kitchen then Foyer"],
            )
        )
        self.assertEqual(res1["spoken_order"], ["kitchen", "foyer"])

        # Subsequent call without spoken_order should preserve stored spoken_order
        res2 = asyncio.run(
            parser.async_generate_svg_floorplan(
                mock_cap_map,
                output_relative_path="test_persist_fp.svg",
            )
        )
        self.assertEqual(res2["spoken_order"], ["kitchen", "foyer"])
        self.assertEqual(res2["zones"]["main"], ["Kitchen", "Foyer"])

    def test_control4_matrix_media_and_security_topology_discovery(self):
        """Verify Control4 Matrix Amp 8-zone discovery, SleepNumber security coordinator, and maturity scoring."""
        from custom_components.otis_ai import DiscoveryEngine
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        parser = FloorplanParser(self.hass)
        engine = DiscoveryEngine(self.hass, floorplan_parser=parser)

        shared_sources = ["Bridge", "Gym Bridge", "Server", "Home Assistant"]
        zone_names = [
            ("back_deck", "Back Deck"),
            ("home_office", "Home Office"),
            ("great_room", "Great Room"),
            ("guest_room", "Guest Room"),
            ("gym_room", "Gym Room"),
            ("master", "Master"),
            ("master_bath", "Master Bath"),
            ("study", "Study"),
        ]
        areas = {
            aid: {"name": name, "entities": [f"media_player.{aid}", f"light.{aid}", f"binary_sensor.{aid}_motion"]}
            for aid, name in zone_names
        }
        entities = []
        for aid, name in zone_names:
            entities.append({
                "entity_id": f"media_player.{aid}",
                "name": f"{name} Speaker",
                "domain": "media_player",
                "platform": "control4",
                "area_id": aid,
                "state": "idle",
                "attributes": {"source_list": shared_sources},
            })
            entities.append({"entity_id": f"light.{aid}", "name": f"{name} Light", "domain": "light", "area_id": aid})
            entities.append({
                "entity_id": f"binary_sensor.{aid}_motion",
                "name": f"{name} Motion",
                "domain": "binary_sensor",
                "area_id": aid,
            })

        # Add upstream input bridges + Theater TV + Security + SleepNumber sensors + unassigned device entity
        entities.extend([
            {"entity_id": "media_player.bridge", "name": "Bridge", "domain": "media_player", "state": "idle"},
            {"entity_id": "media_player.gym_bridge", "name": "Gym Bridge", "domain": "media_player", "state": "idle"},
            {
                "entity_id": "media_player.theater_tv",
                "name": "Theater TV",
                "domain": "media_player",
                "attributes": {"device_class": "tv"},
            },
            {"entity_id": "alarm_control_panel.alarmo", "name": "Alarmo", "domain": "alarm_control_panel"},
            {"entity_id": "lock.front_door_lock", "name": "Front Door Lock", "domain": "lock"},
            {"entity_id": "cover.smart_garage_door", "name": "Garage Door", "domain": "cover"},
            {"entity_id": "siren.foyer_siren", "name": "Foyer Siren", "domain": "siren"},
            {"entity_id": "person.resident_1", "name": "Resident 1", "domain": "person"},
            {"entity_id": "person.resident_2", "name": "Resident 2", "domain": "person"},
            {
                "entity_id": "binary_sensor.sleepnumber_resident_1_is_in_bed",
                "name": "Resident 1 In Bed",
                "domain": "binary_sensor",
            },
            {
                "entity_id": "binary_sensor.sleepnumber_resident_2_is_in_bed",
                "name": "Resident 2 In Bed",
                "domain": "binary_sensor",
            },
            {
                "entity_id": "sensor.master_bath_temperature",
                "name": "Master Bath Temp",
                "domain": "sensor",
                "area_id": None,
            },
        ])

        integrations = [{"domain": "control4"}, {"domain": "hassio"}]
        media_topo = engine._discover_media_topology(areas, entities, integrations)
        self.assertTrue(media_topo["matrix_amp_detected"])
        self.assertEqual(len(media_topo["matrix_zones"]), 8)
        self.assertEqual(len(media_topo["input_streamers"]), 2)
        self.assertEqual(len(media_topo["tv_cinema_zones"]), 1)

        sec_topo = engine._discover_security_topology(areas, entities, integrations)
        self.assertEqual(sec_topo["alarm_panels"], ["alarm_control_panel.alarmo"])
        self.assertEqual(len(sec_topo["bed_occupancy_sensors"]), 2)
        self.assertTrue(sec_topo["ready_for_unified_coordinator"])

        maturity = engine._discover_system_maturity(
            areas,
            {"dev_unassigned": {"name": "Study Desk Lamp", "area_id": None}},
            entities,
            [],
            integrations,
            True,
            True,
            media_topo,
            sec_topo,
        )
        self.assertIn("score", maturity)
        self.assertEqual(maturity["inferred_device_assignments"].get("dev_unassigned"), "study")
        self.assertEqual(
            maturity["inferred_entity_assignments"].get("sensor.master_bath_temperature"),
            "master_bath",
        )

        cap_map = {
            "integrations": integrations,
            "areas": areas,
            "devices": {"dev_unassigned": {"name": "Study Desk Lamp", "area_id": None}},
            "entities": entities,
            "orphaned_entities": [],
            "spatial_graph": {"adjacencies": {}},
            "media_topology": media_topo,
            "security_topology": sec_topo,
            "maturity": maturity,
        }
        suggestions = asyncio.run(engine.async_generate_proactive_suggestions(cap_map))
        sugg_ids = {s["id"] for s in suggestions}
        self.assertIn("matrix_audio_router_package", sugg_ids)
        self.assertIn("cinema_lighting_shade_coordinator", sugg_ids)
        self.assertIn("unified_security_presence_coordinator", sugg_ids)
        self.assertIn("whole_home_lighting_coordinator", sugg_ids)
        self.assertIn("auto_assign_device_areas", sugg_ids)
        self.assertIn("automated_nightly_backup", sugg_ids)

    def test_existing_automation_audit_system_config_and_admin_dashboard(self):
        """Verify existing automation overlap suppression, broken entity repair, config optimization, and Admin dashboard creation."""
        from custom_components.otis_ai import DiscoveryEngine
        from custom_components.otis_ai.automation_manager import AutomationManager
        from custom_components.otis_ai.dashboard_manager import DashboardManager
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        # Write sample automations.yaml, scripts.yaml, and configuration.yaml in hass config path
        autos_yaml = self.hass.config.path("automations.yaml")
        scripts_yaml = self.hass.config.path("scripts.yaml")
        config_yaml = self.hass.config.path("configuration.yaml")
        self.hass.services = MagicMock()
        self.hass.services.async_call = AsyncMock()

        with open(autos_yaml, "w", encoding="utf-8") as f:
            f.write(
                "- id: '1711562763498'\n"
                "  alias: 'Area: Study'\n"
                "  trigger:\n"
                "    - platform: state\n"
                "      entity_id: binary_sensor.study_motion\n"
                "  action:\n"
                "    - service: media_player.turn_on\n"
                "      target:\n"
                "        entity_id:\n"
                "          - media_player.matrix_amp_1_sstudy\n"
                "          - media_player.matrix_amp_1_study\n"
                "  mode: queued\n"
                "- id: '1757434440996'\n"
                "  alias: 'Security: Alarm System'\n"
                "  trigger:\n"
                "    - platform: state\n"
                "      entity_id: alarm_control_panel.alarmo\n"
                "    - platform: state\n"
                "      entity_id: person.resident_1\n"
                "    - platform: state\n"
                "      entity_id: person.resident_2\n"
                "    - platform: state\n"
                "      entity_id: lock.front_door\n"
                "  action:\n"
                "    - service: lock.lock\n"
                "      target:\n"
                "        entity_id: lock.front_door\n"
                "- id: '1773171676975'\n"
                "  alias: 'Maintenance: Media Catalog + Helper Sync'\n"
                "  trigger:\n"
                "    - platform: homeassistant\n"
                "      event: start\n"
                "  action:\n"
                "    - service: input_select.select_option\n"
                "      data:\n"
                "        option: 'Loading ...'\n"
                "  mode: single\n"
                "- id: '1755210557941'\n"
                "  alias: 'Climate: Thermostat Upstairs'\n"
                "  use_blueprint:\n"
                "    path: climate/climate.yaml\n"
                "    input:\n"
                "      thermostat_selection: climate.upstairs\n"
                "- id: '1700336834436'\n"
                "  alias: 'Area: It''s Time'\n"
                "  triggers:\n"
                "    - trigger: light.turned_on\n"
                "      target:\n"
                "        entity_id: light.amy_s_light\n"
                "  actions:\n"
                "    - action: media_player.play_media\n"
                "      target:\n"
                "        entity_id:\n"
                "          - media_player.matrix_amp_1_study\n"
                "          - light.lower_porch\n"
                "  mode: single\n"
            )

        with open(scripts_yaml, "w", encoding="utf-8") as f:
            f.write(
                "media_router:\n"
                "  alias: Media Router\n"
                "  sequence: []\n"
                "lighting_router:\n"
                "  alias: Lighting Router\n"
                "  sequence: []\n"
            )

        with open(config_yaml, "w", encoding="utf-8") as f:
            f.write(
                "default_config:\n\n"
                "logger:\n"
                "  default: info\n"
                "  filters:\n"
                "    homeassistant.helpers.frame:\n"
                '      - "meross_lan"\n\n'
                "recorder:\n"
                "  purge_keep_days: 10\n"
                "  exclude:\n"
                "    entities:\n"
                "      - input_select.media_ma_favorite_picker\n"
            )

        d_mgr = DashboardManager(self.hass)
        admin_dash = asyncio.run(d_mgr.async_ensure_admin_companion_dashboard())
        self.assertTrue(admin_dash["success"])
        self.assertEqual(admin_dash["url_path"], "otis-ai")
        self.assertTrue(admin_dash["require_admin"])

        dashboards_json = self.hass.config.path(".storage/lovelace_dashboards")
        self.assertTrue(os.path.exists(dashboards_json))
        otis_dash_json = self.hass.config.path(".storage/lovelace.otis_ai")
        with open(otis_dash_json, "r", encoding="utf-8") as f:
            otis_dash_data = f.read()
            self.assertIn('"type": "panel"', otis_dash_data)
            self.assertIn('"panel": true', otis_dash_data)
            self.assertIn('"theme_preset": "ha_native"', otis_dash_data)
            self.assertIn('"subview": true', otis_dash_data)
            self.assertIn('"path": "media"', otis_dash_data)
            self.assertIn('"path": "security"', otis_dash_data)
            self.assertIn('"path": "climate"', otis_dash_data)
            self.assertIn('"path": "floorplan"', otis_dash_data)

        parser = FloorplanParser(self.hass)
        engine = DiscoveryEngine(self.hass, floorplan_parser=parser, dashboard_manager=d_mgr)
        active_eids = {
            "media_player.matrix_amp_1_study",
            "binary_sensor.study_motion",
            "alarm_control_panel.alarmo",
            "lock.front_door",
            "climate.upstairs",
            "light.amy_s_light",
        }
        audit = engine._inspect_config_files_sync(active_eids)
        imp_ids = {s["id"] for s in audit["improvement_suggestions"]}
        sys_ids = {s["id"] for s in audit["system_suggestions"]}

        self.assertIn("fix_input_select_option_1773171676975", imp_ids)
        self.assertIn("fix_broken_entity_1711562763498_matrix_amp_1_sstudy", imp_ids)
        self.assertIn("upgrade_mode_queued_1757434440996", imp_ids)
        # Ensure blueprint paths, actions, triggers, and non-typo offline entities are never falsely flagged
        self.assertFalse(any("yaml" in sid for sid in imp_ids))
        self.assertFalse(any("play_media" in sid for sid in imp_ids))
        self.assertFalse(any("turned_on" in sid for sid in imp_ids))
        self.assertFalse(any("lower_porch" in sid for sid in imp_ids))
        self.assertIn("optimize_recorder_commit_interval", sys_ids)
        self.assertIn("suppress_recorder_32kb_call_service_warning", sys_ids)

        # Verify AutomationManager 1-click execution of improve_automation & optimize_system_config
        a_mgr = AutomationManager(self.hass)
        res1 = asyncio.run(
            a_mgr.async_improve_automation({
                "automation_id": "1711562763498",
                "replace_map": {"media_player.matrix_amp_1_sstudy": "media_player.matrix_amp_1_study"},
            })
        )
        self.assertTrue(res1["success"])
        with open(autos_yaml, "r", encoding="utf-8") as f:
            updated_autos = f.read()
            self.assertNotIn("matrix_amp_1_sstudy", updated_autos)
            self.assertIn("climate/climate.yaml", updated_autos)
            self.assertIn("media_player.play_media", updated_autos)
            self.assertIn("light.turned_on", updated_autos)

        res2 = asyncio.run(
            a_mgr.async_optimize_system_config({"optimization_type": "recorder_commit_interval"})
        )
        self.assertTrue(res2["success"])
        with open(config_yaml, "r", encoding="utf-8") as f:
            self.assertIn("commit_interval: 30", f.read())

        for fpath in (autos_yaml, scripts_yaml, config_yaml):
            if os.path.exists(fpath):
                os.remove(fpath)

    def test_hub_and_spoke_subviews_and_room_generation(self):
        """Test dynamic room subview generation and standalone Hub-and-Spoke dashboards."""
        import asyncio
        import json
        from custom_components.otis_ai.dashboard_manager import DashboardManager

        d_mgr = DashboardManager(self.hass)

        capability_map = {
            "areas": {
                "living_room": {"name": "Living Room", "entities": ["light.living_room_ceiling", "media_player.living_room_tv"]},
                "master_bedroom": {"name": "Master Bedroom", "entities": ["light.bedroom_lamp", "climate.bedroom_ac", "lock.balcony_door"]},
                "study": {"name": "Study Room", "entities": ["switch.study_desk", "sensor.study_temp", "binary_sensor.study_motion"]},
            },
            "entities": [
                {"entity_id": "light.living_room_ceiling", "domain": "light", "state": "on", "area_id": "living_room"},
                {"entity_id": "media_player.living_room_tv", "domain": "media_player", "state": "playing", "area_id": "living_room"},
                {"entity_id": "light.bedroom_lamp", "domain": "light", "state": "off", "area_id": "master_bedroom"},
                {"entity_id": "climate.bedroom_ac", "domain": "climate", "state": "cool", "area_id": "master_bedroom"},
                {"entity_id": "lock.balcony_door", "domain": "lock", "state": "locked", "area_id": "master_bedroom"},
                {"entity_id": "switch.study_desk", "domain": "switch", "state": "on", "area_id": "study"},
                {"entity_id": "sensor.study_temp", "domain": "sensor", "state": "72", "area_id": "study", "attributes": {"device_class": "temperature"}},
                {"entity_id": "binary_sensor.study_motion", "domain": "binary_sensor", "state": "off", "area_id": "study"},
                {"entity_id": "camera.front_porch", "domain": "camera", "state": "idle", "area_id": None},
            ],
            "media_topology": {
                "matrix_zones": [{"entity_id": "media_player.living_room_tv"}],
                "input_streamers": [],
                "tv_cinema_zones": [{"entity_id": "media_player.living_room_tv"}],
            },
            "security_topology": {
                "alarm_panels": [],
                "locks": ["lock.balcony_door"],
                "garage_covers": [],
                "cameras": ["camera.front_porch"],
                "bed_occupancy_sensors": [],
                "persons": [],
                "perimeter_contact_sensors": [],
            },
        }

        # 1. Test Otis Companion Dashboard Room Subviews
        admin_dash_cfg = d_mgr._build_otis_companion_dashboard_config(capability_map)
        paths = [v.get("path") for v in admin_dash_cfg["views"]]
        self.assertIn("default_view", paths)
        self.assertIn("media", paths)
        self.assertIn("security", paths)
        self.assertIn("climate", paths)
        self.assertIn("floorplan", paths)
        self.assertIn("area_living_room", paths)
        self.assertIn("area_master_bedroom", paths)
        self.assertIn("area_study", paths)

        # Verify room subviews have subview: True and categorized cards
        room_subviews = {v["path"]: v for v in admin_dash_cfg["views"] if v.get("path", "").startswith("area_")}
        lr_subview = room_subviews["area_living_room"]
        self.assertTrue(lr_subview.get("subview"))
        lr_card_titles = [c.get("title") for c in lr_subview["cards"] if isinstance(c, dict)]
        self.assertIn("Lighting", lr_card_titles)
        self.assertIn("Media & Audio", lr_card_titles)

        mb_subview = room_subviews["area_master_bedroom"]
        self.assertTrue(mb_subview.get("subview"))
        mb_card_types = [c.get("type") for c in mb_subview["cards"] if isinstance(c, dict)]
        self.assertIn("thermostat", mb_card_types)
        mb_card_titles = [c.get("title") for c in mb_subview["cards"] if isinstance(c, dict)]
        self.assertIn("Access & Covers", mb_card_titles)

        # 2. Test Dashboard Gap Analysis proposing Whole Home (before creation)
        gaps = asyncio.run(d_mgr.async_analyze_dashboard_gaps(capability_map))
        proposals = {p["id"]: p for p in gaps["proposals"]}
        self.assertIn("pro_dashboard_whole_home_hub", proposals)
        self.assertEqual(proposals["pro_dashboard_whole_home_hub"]["template"], "whole_home")

        # 3. Test Standalone Hub-and-Spoke Dashboards
        # Media Studio
        media_dash = asyncio.run(
            d_mgr.async_create_professional_dashboard(
                {"template": "media_studio", "url_path": "otis-media-studio", "title": "Media Studio"},
                capability_map,
            )
        )
        self.assertTrue(media_dash["success"])
        media_json = self.hass.config.path(".storage/lovelace.otis_media_studio")
        with open(media_json, "r", encoding="utf-8") as f:
            data = json.load(f)
            vpaths = [v["path"] for v in data["data"]["config"]["views"]]
            self.assertEqual(vpaths, ["default_view", "zones", "streamers", "cinema"])
            self.assertTrue(data["data"]["config"]["views"][1]["subview"])

        # Whole-Home Hub
        whole_home_dash = asyncio.run(
            d_mgr.async_create_professional_dashboard(
                {"template": "whole_home", "url_path": "otis-whole-home", "title": "Whole Home"},
                capability_map,
            )
        )
        self.assertTrue(whole_home_dash["success"])
        wh_json = self.hass.config.path(".storage/lovelace.otis_whole_home")
        with open(wh_json, "r", encoding="utf-8") as f:
            data = json.load(f)
            vpaths = [v["path"] for v in data["data"]["config"]["views"]]
            self.assertIn("default_view", vpaths)
            self.assertIn("area_living_room", vpaths)
            self.assertIn("area_master_bedroom", vpaths)
            self.assertIn("area_study", vpaths)

        # Gap analysis after creation should no longer propose whole_home
        gaps_after = asyncio.run(d_mgr.async_analyze_dashboard_gaps(capability_map))
        proposals_after = {p["id"]: p for p in gaps_after["proposals"]}
        self.assertNotIn("pro_dashboard_whole_home_hub", proposals_after)


class TestThemeManager(unittest.TestCase):
    """Test suite for Phase 2 Dynamic Themes & Collaborative AI Styling."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.hass = MagicMock()
        self.hass.config = MagicMock()
        self.hass.config.path = lambda *args: os.path.join(self.temp_dir.name, *args)
        self.hass.services = MagicMock()
        self.hass.services.has_service = MagicMock(return_value=True)

        async def _mock_call(domain, service, service_data=None, blocking=True):
            return True

        self.hass.services.async_call = MagicMock(side_effect=_mock_call)

        def _mock_executor(fn, *args):
            return fn(*args)

        self.hass.async_add_executor_job = MagicMock(side_effect=_mock_executor)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_synthesize_presets(self):
        """Verify baseline presets generate valid Home Assistant CSS tokens."""
        from custom_components.otis_ai.theme_manager import ThemeManager

        tm = ThemeManager(self.hass)

        # 1. Cyberpunk Neon
        cp = tm.synthesize_theme_from_prompt("cyberpunk neon", base_palette="cyberpunk")
        self.assertTrue(cp["dark_mode"])
        self.assertEqual(cp["vars"]["primary-color"], "#00f0ff")
        self.assertIn("0 0 16px", cp["vars"]["ha-card-box-shadow"])

        # 2. Nordic Frost (Light mode)
        nf = tm.synthesize_theme_from_prompt("clean daylight scandinavian theme", base_palette="nordic_frost")
        self.assertFalse(nf["dark_mode"])
        self.assertEqual(nf["vars"]["primary-background-color"], "#f8fafc")

        # 3. High Contrast
        hc = tm.synthesize_theme_from_prompt("accessible high contrast", base_palette="high_contrast")
        self.assertEqual(hc["vars"]["ha-card-border-width"], "2px")
        self.assertEqual(hc["vars"]["ha-card-border-radius"], "4px")

    def test_prompt_custom_token_synthesis(self):
        """Verify natural language prompt parsing extracts hex colors, radius, and glow."""
        from custom_components.otis_ai.theme_manager import ThemeManager

        tm = ThemeManager(self.hass)

        # Custom hex color + radius + glow
        res = tm.synthesize_theme_from_prompt(
            "Create a glowing violet #8b5cf6 theme with 20px rounded cards and #ec4899 accent",
            name="Neon Violet",
        )
        self.assertEqual(res["title"], "Neon Violet")
        self.assertEqual(res["slug"], "neon_violet")
        self.assertEqual(res["theme_key"], "otis_neon_violet")
        self.assertEqual(res["vars"]["primary-color"], "#8b5cf6")
        self.assertEqual(res["vars"]["accent-color"], "#ec4899")
        self.assertEqual(res["vars"]["ha-card-border-radius"], "20px")
        self.assertIn("0 0 16px", res["vars"]["ha-card-box-shadow"])

        # Sharp borders keyword
        sharp_res = tm.synthesize_theme_from_prompt("Brutalist sharp square theme")
        self.assertEqual(sharp_res["vars"]["ha-card-border-radius"], "0px")

    def test_save_list_apply_delete_lifecycle(self):
        """Verify end-to-end theme creation, file writing, frontend reload, list, apply, and delete."""
        from custom_components.otis_ai.theme_manager import ThemeManager

        tm = ThemeManager(self.hass)

        # 1. Generate & save theme
        save_res = asyncio.run(
            tm.async_generate_and_save_theme(
                prompt="Cyberpunk neon with glowing cyan",
                name="Otis Cyber Matrix",
                base_palette="cyberpunk",
                apply_immediately=True,
            )
        )
        self.assertTrue(save_res["success"])
        self.assertEqual(save_res["theme_key"], "otis_cyber_matrix")
        self.assertTrue(os.path.exists(save_res["file_path"]))

        # Verify YAML content structure
        with open(save_res["file_path"], "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("otis_cyber_matrix:", content)
            self.assertIn("primary-color:", content)

        # 2. List themes
        themes_list = asyncio.run(tm.async_list_otis_themes())
        self.assertEqual(len(themes_list), 1)
        self.assertEqual(themes_list[0]["theme_key"], "otis_cyber_matrix")
        self.assertEqual(themes_list[0]["preview"]["primary"], "#06b6d4")

        # 3. Apply theme
        applied = asyncio.run(tm.async_apply_theme("otis_cyber_matrix"))
        self.assertTrue(applied)
        self.hass.services.async_call.assert_any_call("frontend", "set_theme", {"name": "otis_cyber_matrix"}, blocking=True)

        # 4. Delete theme
        deleted = asyncio.run(tm.async_delete_theme("otis_cyber_matrix"))
        self.assertTrue(deleted)
        self.assertFalse(os.path.exists(save_res["file_path"]))
        themes_after = asyncio.run(tm.async_list_otis_themes())
        self.assertEqual(len(themes_after), 0)


class TestSentinelManager(unittest.TestCase):
    """Test suite for Phase 3 Otis Sentinel Telemetry Watchdog & Self-Healing."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.hass = MagicMock()
        self.hass.config = MagicMock()
        self.hass.config.path = lambda *args: os.path.join(self.temp_dir.name, *args)
        self.hass.data = {DOMAIN: {"sessions": {}}}
        self.hass.states = MagicMock()
        self.hass.services = MagicMock()
        self.hass.services.has_service = MagicMock(return_value=True)

        async def _mock_call(domain, service, service_data=None, blocking=True):
            return True

        self.hass.services.async_call = MagicMock(side_effect=_mock_call)

        self.hass.config_entries = MagicMock()

        async def _mock_reload(entry_id):
            return True

        self.hass.config_entries.async_reload = MagicMock(side_effect=_mock_reload)

    def test_battery_watchdog(self):
        """Verify critical and low battery detection."""
        from custom_components.otis_ai.sentinel_manager import SentinelManager

        s_crit = MagicMock()
        s_crit.entity_id = "sensor.front_door_lock_battery"
        s_crit.state = "6"
        s_crit.attributes = {"device_class": "battery", "friendly_name": "Front Door Lock Battery"}

        s_low = MagicMock()
        s_low.entity_id = "sensor.living_room_motion_battery"
        s_low.state = "18"
        s_low.attributes = {"device_class": "battery", "friendly_name": "Living Room Motion Battery"}

        self.hass.states.async_all.return_value = [s_crit, s_low]

        sm = SentinelManager(self.hass)
        anomalies = asyncio.run(sm.async_scan_all_anomalies())
        self.assertEqual(len(anomalies), 2)

        a_crit = next(a for a in anomalies if a["entity_id"] == "sensor.front_door_lock_battery")
        self.assertEqual(a_crit["severity"], "high")
        self.assertIn("Critical Battery", a_crit["title"])

        a_low = next(a for a in anomalies if a["entity_id"] == "sensor.living_room_motion_battery")
        self.assertEqual(a_low["severity"], "medium")

    def test_perimeter_access_watchdog(self):
        """Verify stuck unlocked lock and open garage doors > 60m are detected."""
        from custom_components.otis_ai.sentinel_manager import SentinelManager
        from datetime import datetime, timezone, timedelta

        past_time = datetime.now(timezone.utc) - timedelta(minutes=75)

        s_lock = MagicMock()
        s_lock.entity_id = "lock.front_door"
        s_lock.state = "unlocked"
        s_lock.last_changed = past_time
        s_lock.attributes = {"friendly_name": "Front Door"}

        s_garage = MagicMock()
        s_garage.entity_id = "cover.garage_door"
        s_garage.state = "open"
        s_garage.last_changed = past_time
        s_garage.attributes = {"device_class": "garage", "friendly_name": "Main Garage Door"}

        self.hass.states.async_all.return_value = [s_lock, s_garage]

        sm = SentinelManager(self.hass)
        anomalies = asyncio.run(sm.async_scan_all_anomalies())
        self.assertEqual(len(anomalies), 2)
        self.assertTrue(all(a["severity"] == "high" for a in anomalies))

    def test_failed_integration_watchdog(self):
        """Verify failed integration entries trigger actionable alerts."""
        from custom_components.otis_ai.sentinel_manager import SentinelManager

        mock_entry = MagicMock()
        mock_entry.entry_id = "entry_12345"
        mock_entry.title = "Unifi Protect"
        mock_entry.state = "setup_error"
        mock_entry.domain = "unifiprotect"

        self.hass.states.async_all.return_value = []
        self.hass.config_entries.async_entries.return_value = [mock_entry]

        sm = SentinelManager(self.hass)
        anomalies = asyncio.run(sm.async_scan_all_anomalies())
        self.assertEqual(len(anomalies), 1)
        self.assertIn("Integration Error", anomalies[0]["title"])
        self.assertEqual(anomalies[0]["remediation_action"], "reload_config_entry")

    def test_self_healing_remediation_lifecycle(self):
        """Verify 1-click self-healing execution and anomaly resolution."""
        from custom_components.otis_ai.sentinel_manager import SentinelManager
        from datetime import datetime, timezone, timedelta

        s_lock = MagicMock()
        s_lock.entity_id = "lock.back_door"
        s_lock.state = "unlocked"
        s_lock.last_changed = datetime.now(timezone.utc) - timedelta(minutes=90)
        s_lock.attributes = {"friendly_name": "Back Door"}

        self.hass.states.async_all.return_value = [s_lock]
        self.hass.config_entries.async_entries.return_value = []

        sm = SentinelManager(self.hass)
        anomalies = asyncio.run(sm.async_scan_all_anomalies())
        self.assertEqual(len(anomalies), 1)
        anom_id = anomalies[0]["id"]

        # Remediate via 1-click action
        res = asyncio.run(sm.async_remediate_anomaly(anom_id))
        self.assertTrue(res["success"])
        self.hass.services.async_call.assert_any_call("lock", "lock", {"entity_id": "lock.back_door"}, blocking=True)
        self.assertEqual(len(sm.get_active_anomalies()), 0)

    def test_battery_filtering_rejects_setpoints_and_config(self):
        """Verify diagnostic setpoints/thresholds are strictly filtered out of battery watchdog."""
        from custom_components.otis_ai.sentinel_manager import SentinelManager

        # Diagnostic UPS setpoint (should be ignored!)
        s_ups_setpoint = MagicMock()
        s_ups_setpoint.entity_id = "sensor.ups_theater_low_battery_setpoint"
        s_ups_setpoint.object_id = "ups_theater_low_battery_setpoint"
        s_ups_setpoint.state = "10"
        s_ups_setpoint.attributes = {"unit_of_measurement": "%", "friendly_name": "Ups-Theater Low battery setpoint"}

        # Number domain setpoint (should be ignored!)
        s_number_setpoint = MagicMock()
        s_number_setpoint.entity_id = "number.battery_cutoff_threshold"
        s_number_setpoint.object_id = "battery_cutoff_threshold"
        s_number_setpoint.state = "15"
        s_number_setpoint.attributes = {"unit_of_measurement": "%", "friendly_name": "Battery Cutoff Threshold"}

        # Actual device battery (should be detected as critical!)
        s_real_battery = MagicMock()
        s_real_battery.entity_id = "sensor.side_hose_timer_battery_level"
        s_real_battery.object_id = "side_hose_timer_battery_level"
        s_real_battery.state = "0"
        s_real_battery.attributes = {"device_class": "battery", "unit_of_measurement": "%", "friendly_name": "Side Hose Timer Battery level"}

        self.hass.states.async_all.return_value = [s_ups_setpoint, s_number_setpoint, s_real_battery]
        self.hass.config_entries.async_entries.return_value = []

        sm = SentinelManager(self.hass)
        anomalies = asyncio.run(sm.async_scan_all_anomalies())
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0]["entity_id"], "sensor.side_hose_timer_battery_level")
        self.assertEqual(anomalies[0]["severity"], "critical")

        # Verify proactive suggestions formatting
        sugs = sm.convert_anomalies_to_proactive_suggestions()
        self.assertEqual(len(sugs), 1)
        self.assertEqual(sugs[0]["action_type"], "sentinel_alert_actions")
        self.assertEqual(sugs[0]["anomaly_type"], "battery")

    def test_sentinel_ignore_alert_and_category(self):
        """Verify muting a single alert and muting all battery alerts."""
        from custom_components.otis_ai.sentinel_manager import SentinelManager

        s1 = MagicMock()
        s1.entity_id = "sensor.lock_battery"
        s1.object_id = "lock_battery"
        s1.state = "5"
        s1.attributes = {"device_class": "battery", "friendly_name": "Front Lock Battery"}

        s2 = MagicMock()
        s2.entity_id = "sensor.remote_battery"
        s2.object_id = "remote_battery"
        s2.state = "8"
        s2.attributes = {"device_class": "battery", "friendly_name": "Remote Battery"}

        self.hass.states.async_all.return_value = [s1, s2]
        self.hass.config_entries.async_entries.return_value = []

        sm = SentinelManager(self.hass)
        anomalies = asyncio.run(sm.async_scan_all_anomalies())
        self.assertEqual(len(anomalies), 2)

        # Ignore single alert
        anom_id = anomalies[0]["id"]
        asyncio.run(sm.async_ignore_anomaly(anom_id))
        self.assertEqual(len(sm.get_active_anomalies()), 1)

        # Ignore entire category
        asyncio.run(sm.async_ignore_category("battery"))
        self.assertEqual(len(sm.get_active_anomalies()), 0)

    def test_user_command_center_dashboard_generation(self):
        """Verify non-admin user command center dashboard creation."""
        from custom_components.otis_ai.dashboard_manager import DashboardManager

        dm = DashboardManager(self.hass)
        cap_map = {
            "areas": {
                "living_room": {"name": "Living Room", "entities": ["light.living_room"]},
                "kitchen": {"name": "Kitchen", "entities": ["light.kitchen"]},
            },
            "entities": [
                {"entity_id": "light.living_room", "area_id": "living_room", "state": "on", "domain": "light"},
                {"entity_id": "light.kitchen", "area_id": "kitchen", "state": "off", "domain": "light"},
            ],
        }

        res = asyncio.run(dm.async_ensure_user_command_center_dashboard(cap_map))
        self.assertTrue(res["success"])
        self.assertEqual(res["url_path"], "command-center")
        self.assertFalse(res["require_admin"])

    def test_dashboard_user_card_settings_preservation_and_safe_storage(self):
        """Verify view 0 is preserved across dashboard updates and empty lovelace_dashboards is handled safely."""
        import json
        import os
        from custom_components.otis_ai.dashboard_manager import DashboardManager

        dm = DashboardManager(self.hass)
        storage_dir = self.hass.config.path(".storage")
        os.makedirs(storage_dir, exist_ok=True)

        # 1. Test empty lovelace_dashboards file handling
        dashboards_file = os.path.join(storage_dir, "lovelace_dashboards")
        with open(dashboards_file, "w", encoding="utf-8") as f:
            f.write("   \n")  # Empty whitespace that previously crashed with Expecting value: line 1 column 1 (char 0)

        # 2. Setup existing lovelace.otis_ai with user-customized card in view 0
        dash_file = os.path.join(storage_dir, "lovelace.otis_ai")
        user_custom_view = {
            "title": "Home",
            "path": "default_view",
            "icon": "mdi:home-heart",
            "cards": [
                {
                    "type": "custom:otis-companion-card",
                    "title": "My Custom Title",
                    "custom_user_option": True,
                },
                {
                    "type": "weather-forecast",
                    "entity": "weather.home",
                },
            ],
        }
        user_custom_subview = {
            "title": "My Custom Room",
            "path": "user_custom_room",
            "cards": [{"type": "entities", "entities": ["light.living_room"]}],
        }
        with open(dash_file, "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "minor_version": 1,
                "key": "lovelace.otis_ai",
                "data": {"config": {"views": [user_custom_view, user_custom_subview]}},
            }, f)

        # 3. Build a new dashboard config as if a new version deployed
        new_config = dm._build_otis_companion_dashboard_config({})
        # View 0 in generated config is the default template
        self.assertEqual(len(new_config["views"][0]["cards"]), 1)
        self.assertEqual(new_config["views"][0]["cards"][0].get("title"), "Otis AI Companion")

        # 4. Merge preserving user views
        merged = dm._merge_dashboard_config_preserving_user_views(storage_dir, "otis_ai", new_config)

        # Assert view 0 was preserved exactly as customized by user
        self.assertEqual(len(merged["views"][0]["cards"]), 2)
        self.assertEqual(merged["views"][0]["cards"][0]["title"], "My Custom Title")
        self.assertTrue(merged["views"][0]["cards"][0].get("custom_user_option"))
        self.assertEqual(merged["views"][0]["cards"][1]["type"], "weather-forecast")

        # Assert custom user subview was preserved
        paths = [v.get("path") for v in merged["views"]]
        self.assertIn("user_custom_room", paths)

    def test_floorplan_subview_uses_native_picture_elements(self):
        """Verify Floor Plan subview in both Admin and Command Center uses native picture-elements and NOT custom:otis-companion-card."""
        from custom_components.otis_ai.dashboard_manager import DashboardManager

        dm = DashboardManager(self.hass)
        cap_map = {
            "areas": {"living_room": {"name": "Living Room", "entities": ["light.living_room"]}},
            "entities": [{"entity_id": "light.living_room", "area_id": "living_room", "state": "on", "domain": "light"}],
        }

        # Check Admin config
        admin_cfg = dm._build_otis_companion_dashboard_config(cap_map)
        fp_view_admin = next(v for v in admin_cfg["views"] if v.get("path") == "floorplan")
        self.assertTrue(fp_view_admin.get("subview"))
        for card in fp_view_admin["cards"]:
            self.assertNotEqual(card.get("type"), "custom:otis-companion-card")
            self.assertIn(card.get("type"), ("picture-elements", "markdown"))

        # Check User Command Center config
        user_cfg = dm._build_user_command_center_dashboard_config(cap_map)
        fp_view_user = next(v for v in user_cfg["views"] if v.get("path") == "floorplan")
        self.assertTrue(fp_view_user.get("subview"))
        for card in fp_view_user["cards"]:
            self.assertNotEqual(card.get("type"), "custom:otis-companion-card")
            self.assertIn(card.get("type"), ("picture-elements", "markdown"))

    def test_room_view_intelligence_and_clutter_filtering(self):
        """Verify intelligent filtering of camera config switches, SNMP ports, vacuum maps, and multi-stream cameras."""
        from custom_components.otis_ai.dashboard_manager import DashboardManager

        dm = DashboardManager(self.hass)
        room_entities = [
            # Real lights
            {"entity_id": "light.foyer_chandelier", "domain": "light", "name": "Foyer Chandelier", "state": "on"},
            # Status / AP LEDs (should be excluded from lighting)
            {"entity_id": "light.ap_entry_led", "domain": "light", "name": "AP Entry LED", "state": "on"},
            {"entity_id": "light.foyer_led_indicator", "domain": "light", "name": "Foyer LED Indicator", "state": "off"},
            # Real power switches
            {"entity_id": "switch.foyer_outlet_top", "domain": "switch", "name": "Foyer Outlet Top", "state": "on"},
            {"entity_id": "switch.foyer_outlet_bottom", "domain": "switch", "name": "Foyer Outlet Bottom", "state": "off"},
            # Camera config toggles (should be excluded from Power & Outlets)
            {"entity_id": "switch.foyer_detect", "domain": "switch", "name": "Foyer Detect", "state": "on", "entity_category": "config"},
            {"entity_id": "switch.foyer_recordings", "domain": "switch", "name": "Foyer Recordings", "state": "on"},
            {"entity_id": "switch.foyer_snapshots", "domain": "switch", "name": "Foyer Snapshots", "state": "on"},
            {"entity_id": "switch.foyer_audio_detection", "domain": "switch", "name": "Foyer Audio Detection", "state": "on"},
            {"entity_id": "switch.foyer_infrared_lights", "domain": "switch", "name": "Foyer Infrared Lights", "state": "on"},
            # SNMP / Firewall switches (should be excluded from Power & Outlets)
            {"entity_id": "switch.hades_filter_rules_101", "domain": "switch", "name": "Hades Filter Rules", "state": "on"},
            {"entity_id": "switch.switch_foyer_port_1", "domain": "switch", "name": "Switch Foyer Port 1", "state": "on"},
            # Vacuum map camera (should be excluded from Cameras)
            {"entity_id": "camera.larry_poppins_saved_map", "domain": "camera", "name": "Larry Poppins Saved Map", "state": "idle"},
            # Multi-stream RTSP cameras (should be deduplicated to 1 primary stream)
            {"entity_id": "camera.foyer_recording", "domain": "camera", "name": "Foyer Recording", "state": "idle", "device_id": "cam_foyer_1"},
            {"entity_id": "camera.foyer_fluent", "domain": "camera", "name": "Foyer Fluent", "state": "idle", "device_id": "cam_foyer_1"},
            {"entity_id": "camera.foyer_clear", "domain": "camera", "name": "Foyer Clear", "state": "idle", "device_id": "cam_foyer_1"},
            # AI counter sensors (should be excluded from Occupancy & Sensors)
            {"entity_id": "sensor.foyer_person_count", "domain": "sensor", "name": "Foyer Person Count", "state": "0"},
            {"entity_id": "sensor.foyer_dog_count", "domain": "sensor", "name": "Foyer Dog Count", "state": "0"},
            # Real occupancy binary sensor
            {"entity_id": "binary_sensor.foyer_motion", "domain": "binary_sensor", "name": "Foyer Motion", "state": "on", "device_class": "motion"},
            {"entity_id": "binary_sensor.front_door", "domain": "binary_sensor", "name": "Front Door", "state": "off", "device_class": "door"},
        ]

        subview = dm._build_room_subview("foyer", {"name": "Foyer"}, room_entities)
        self.assertIsNotNone(subview)
        cards_by_title = {c.get("title"): c for c in subview["cards"] if isinstance(c, dict)}

        # Lighting check: Only genuine chandelier, LEDs excluded
        lighting_card = cards_by_title["Lighting"]
        lighting_eids = [tile["entity"] for tile in lighting_card["cards"]]
        self.assertIn("light.foyer_chandelier", lighting_eids)
        self.assertNotIn("light.ap_entry_led", lighting_eids)
        self.assertNotIn("light.foyer_led_indicator", lighting_eids)

        # Power & Outlets check: Only real outlets, camera config & SNMP excluded
        power_card = cards_by_title["Power & Outlets"]
        power_eids = [tile["entity"] for tile in power_card["cards"]]
        self.assertIn("switch.foyer_outlet_top", power_eids)
        self.assertIn("switch.foyer_outlet_bottom", power_eids)
        self.assertNotIn("switch.foyer_detect", power_eids)
        self.assertNotIn("switch.foyer_recordings", power_eids)
        self.assertNotIn("switch.foyer_audio_detection", power_eids)
        self.assertNotIn("switch.hades_filter_rules_101", power_eids)
        self.assertNotIn("switch.switch_foyer_port_1", power_eids)

        # Cameras check: Vacuum maps excluded, deduplicated to 1 stream
        cameras_card = cards_by_title["Cameras"]
        camera_eids = [card["entity"] for card in cameras_card["cards"]]
        self.assertNotIn("camera.larry_poppins_saved_map", camera_eids)
        self.assertEqual(len(camera_eids), 1)
        self.assertEqual(camera_eids[0], "camera.foyer_clear")

        # Occupancy & Sensors check: Person/dog counters excluded, real motion/door included
        sensors_card = cards_by_title["Occupancy & Sensors"]
        sensor_eids = sensors_card["entities"]
        self.assertIn("binary_sensor.foyer_motion", sensor_eids)
        self.assertIn("binary_sensor.front_door", sensor_eids)
        self.assertNotIn("sensor.foyer_person_count", sensor_eids)
        self.assertNotIn("sensor.foyer_dog_count", sensor_eids)

        # Contextual icon check
        self.assertEqual(subview["icon"], "mdi:door")
        self.assertEqual(dm._get_room_icon("Theater", "theater"), "mdi:theater")
        self.assertEqual(dm._get_room_icon("Backyard", "backyard"), "mdi:tree")
        self.assertEqual(dm._get_room_icon("Amy's Office", "office"), "mdi:desk")
        self.assertEqual(dm._get_room_icon("Downstairs Bath", "bath"), "mdi:shower")

    def test_floorplan_view_cards_picture_elements(self):
        """Verify Floor Plan view builds interactive picture-elements card with elements and cache buster."""
        from custom_components.otis_ai.dashboard_manager import DashboardManager
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        fp = FloorplanParser(self.hass)
        dm = DashboardManager(self.hass, floorplan_parser=fp)

        mock_cap_map = {
            "areas": {
                "foyer": {"name": "Foyer", "entities": ["light.foyer_lights"]},
                "theater": {"name": "Theater", "entities": ["light.theater_lights"]},
            },
            "entities": [
                {"entity_id": "light.foyer_lights", "name": "Foyer Lights", "area_id": "foyer", "domain": "light", "state": "on"},
                {"entity_id": "light.theater_lights", "name": "Theater Lights", "area_id": "theater", "domain": "light", "state": "off"},
            ],
        }
        # Mock svg file existence
        self.hass.config.path = lambda p: "/config/www/otis_floorplan.svg" if "otis_floorplan.svg" in p else p
        with unittest.mock.patch("os.path.exists", return_value=True), \
             unittest.mock.patch("os.path.getmtime", return_value=1730225708):
            cards = dm._build_floorplan_view_cards(
                mock_cap_map, dashboard_url_path="command-center"
            )

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["type"], "picture-elements")
        self.assertIn("otis_floorplan.svg?v=1730225708", cards[0]["image"])
        self.assertGreater(len(cards[0]["elements"]), 0)

        # Check room icon navigation
        labels = [e for e in cards[0]["elements"] if e["type"] == "icon"]
        self.assertGreater(len(labels), 0)
        nav_paths = [lbl["tap_action"]["navigation_path"] for lbl in labels]
        self.assertTrue(any(p.startswith("/command-center/area_") for p in nav_paths))

    def test_sentinel_ignore_anomaly_indexing(self):
        """Verify Sentinel indexes anomaly entity_id and prefix variations."""
        import asyncio
        from custom_components.otis_ai.sentinel_manager import SentinelManager

        sm = SentinelManager(self.hass)
        with unittest.mock.patch.object(sm._store, "async_load", return_value=None), \
             unittest.mock.patch.object(sm._store, "async_save", return_value=None):
            asyncio.run(sm.async_ignore_anomaly("sentinel_battery_critical_sensor.side_hose_timer_battery_level"))

        # Entity ID and prefix variations should be ignored
        self.assertIn("sensor.side_hose_timer_battery_level", sm._ignored_anomaly_ids)
        self.assertIn("sentinel_battery_low_sensor.side_hose_timer_battery_level", sm._ignored_anomaly_ids)
        self.assertIn("sentinel_battery_critical_sensor.side_hose_timer_battery_level", sm._ignored_anomaly_ids)

    def test_intelligent_room_controls_selection(self):
        """Verify intelligent controllable device selection filters clutter and provides domain diversity."""
        from custom_components.otis_ai.dashboard_manager import DashboardManager

        dm = DashboardManager(self.hass)
        valid_eids = {
            "light.dining_room_chandelier",
            "switch.mary_poppins_customized_cleaning",
            "switch.sleepnumber_super_sleep_pause_mode",
            "media_player.dining_room_sonos",
            "switch.dining_room_accent_plug",
            "fan.dining_room_ceiling_fan",
        }
        room_ents = [
            {"entity_id": "switch.mary_poppins_customized_cleaning", "name": "Mary Poppins Customized Cleaning", "domain": "switch"},
            {"entity_id": "switch.sleepnumber_super_sleep_pause_mode", "name": "Sleep Number Pause Mode", "domain": "switch"},
            {"entity_id": "light.dining_room_chandelier", "name": "Dining Room Chandelier", "domain": "light"},
            {"entity_id": "media_player.dining_room_sonos", "name": "Dining Room Sonos", "domain": "media_player"},
            {"entity_id": "switch.dining_room_accent_plug", "name": "Dining Room Lamp Plug", "domain": "switch"},
            {"entity_id": "fan.dining_room_ceiling_fan", "name": "Dining Room Fan", "domain": "fan"},
        ]

        selected = dm._select_intelligent_room_controls(
            room_ents, valid_eids, area_name="Dining Room", area_id="dining_room", max_controls=3
        )

        selected_eids = [s["entity"] for s in selected]
        # Vacuum sub-switches and sleepnumber toggles must be filtered out
        self.assertNotIn("switch.mary_poppins_customized_cleaning", selected_eids)
        self.assertNotIn("switch.sleepnumber_super_sleep_pause_mode", selected_eids)

        # High-utility primary devices must be prioritized
        self.assertIn("light.dining_room_chandelier", selected_eids)
        # Check domain diversity (should have media_player or fan as second control)
        self.assertTrue(
            "media_player.dining_room_sonos" in selected_eids or "fan.dining_room_ceiling_fan" in selected_eids
        )
        self.assertLessEqual(len(selected), 3)

    def test_room_header_navigation_hotspot(self):
        """Verify Floor Plan view elements include clickable transparent hotspots for room names."""
        from custom_components.otis_ai.dashboard_manager import DashboardManager
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        fp = FloorplanParser(self.hass)
        dm = DashboardManager(self.hass, floorplan_parser=fp)

        mock_cap_map = {
            "areas": {
                "foyer": {"name": "Foyer", "entities": ["light.foyer_lights"]},
            },
            "entities": [
                {"entity_id": "light.foyer_lights", "name": "Foyer Lights", "area_id": "foyer", "domain": "light", "state": "on"},
            ],
        }
        self.hass.config.path = lambda p: "/config/www/otis_floorplan.svg" if "otis_floorplan.svg" in p else p
        with unittest.mock.patch("os.path.exists", return_value=True), \
             unittest.mock.patch("os.path.getmtime", return_value=1730225708):
            cards = dm._build_floorplan_view_cards(mock_cap_map, dashboard_url_path="otis-ai")

        elements = cards[0]["elements"]
        # Find transparent image navigation hotspots
        img_hotspots = [
            e for e in elements
            if e.get("type") == "image" and e.get("tap_action", {}).get("action") == "navigate"
        ]
        self.assertGreater(len(img_hotspots), 0)
        self.assertIn("/otis-ai/area_foyer", [h["tap_action"]["navigation_path"] for h in img_hotspots])

    def test_command_center_syncs_studios_and_rooms_from_otis_ai(self):
        """Verify Command Center automatically inherits Studio/Room edits and rewrites URLs."""
        import json
        import os
        import tempfile
        from custom_components.otis_ai.dashboard_manager import DashboardManager

        dm = DashboardManager(self.hass)
        with tempfile.TemporaryDirectory() as tmp_dir:
            # 1. Create mock lovelace.otis_ai with custom cards in Media Studio and a Room view
            admin_data = {
                "version": 1,
                "data": {
                    "config": {
                        "views": [
                            {"path": "default_view", "title": "AI Command Center", "cards": []},
                            {
                                "path": "media",
                                "title": "Media Studio",
                                "cards": [
                                    {"type": "markdown", "content": "Custom Admin Media Studio"},
                                    {"type": "button", "name": "Back", "tap_action": {"action": "navigate", "navigation_path": "/otis-ai/area_theater"}},
                                ],
                            },
                            {
                                "path": "area_theater",
                                "title": "Home Theater",
                                "cards": [
                                    {"type": "media-control", "entity": "media_player.theater_avr"},
                                    {"type": "button", "name": "Return", "tap_action": {"action": "navigate", "navigation_path": "/otis-ai/media"}},
                                ],
                            },
                        ]
                    }
                }
            }
            with open(os.path.join(tmp_dir, "lovelace.otis_ai"), "w") as f:
                json.dump(admin_data, f)

            # 2. Command Center newly generated config
            new_cc_config = {
                "title": "Command Center",
                "views": [
                    {
                        "path": "home",
                        "title": "Home",
                        "cards": [
                            {"type": "markdown", "content": "Header"},
                            {"type": "grid", "title": "Studios", "cards": [{"name": "Media Studio"}]},
                            {"type": "grid", "title": "Rooms", "cards": [{"name": "Home Theater"}]},
                        ],
                    },
                    {"path": "media", "title": "Media Studio", "cards": []},
                    {"path": "area_theater", "title": "Home Theater", "cards": []},
                ],
            }

            merged = dm._merge_dashboard_config_preserving_user_views(
                storage_dir=tmp_dir,
                dash_id="command-center",
                new_config=new_cc_config,
            )

            # Verify Media Studio inherited the admin cards and URL was rewritten to /command-center/
            media_view = next(v for v in merged["views"] if v["path"] == "media")
            self.assertEqual(len(media_view["cards"]), 2)
            self.assertEqual(media_view["cards"][0]["content"], "Custom Admin Media Studio")
            self.assertEqual(
                media_view["cards"][1]["tap_action"]["navigation_path"],
                "/command-center/area_theater",
            )

            # Verify Room subview inherited the admin cards and URL was rewritten
            theater_view = next(v for v in merged["views"] if v["path"] == "area_theater")
            self.assertEqual(len(theater_view["cards"]), 2)
            self.assertEqual(
                theater_view["cards"][1]["tap_action"]["navigation_path"],
                "/command-center/media",
            )

    def tearDown(self):
        if hasattr(self, "temp_dir"):
            self.temp_dir.cleanup()


class TestMacroManager(unittest.TestCase):
    """Test suite for Phase 5 Dynamic Macro Orchestrator & Multi-Step Assist Pipelines."""

    def setUp(self):
        self.hass = MagicMock()
        self.hass.data = {DOMAIN: {"sessions": {}}}
        self.hass.states = MagicMock()
        self.hass.services = MagicMock()
        self.hass.services.has_service = MagicMock(return_value=True)

        async def _mock_call(domain, service, service_data=None, blocking=True, context=None):
            return True

        self.hass.services.async_call = MagicMock(side_effect=_mock_call)

    def test_smart_macro_builder(self):
        """Verify dynamic macro synthesis from hardware topology."""
        from custom_components.otis_ai.macro_manager import MacroManager

        light_living = MagicMock()
        light_living.entity_id = "light.living_room_ceiling"
        light_living.state = "on"
        light_living.attributes = {"friendly_name": "Living Room Ceiling"}

        tv = MagicMock()
        tv.entity_id = "media_player.living_room_tv"
        tv.state = "off"
        tv.attributes = {"friendly_name": "Living Room TV"}

        climate = MagicMock()
        climate.entity_id = "climate.thermostat"
        climate.state = "heat"
        climate.attributes = {"temperature": 72}

        self.hass.states.async_all.return_value = [light_living, tv, climate]

        mm = MacroManager(self.hass)
        macro = mm.build_smart_macro("movie_night")
        self.assertEqual(macro["name"], "Movie Night Mode")
        self.assertTrue(len(macro["steps"]) >= 3)

        # Check light dim step
        step_light = next(s for s in macro["steps"] if s["domain"] == "light")
        self.assertEqual(step_light["data"]["brightness_pct"], 15)

        # Check climate step
        step_clim = next(s for s in macro["steps"] if s["domain"] == "climate")
        self.assertEqual(step_clim["data"]["temperature"], 68)

    def test_safety_inspector(self):
        """Verify critical security & access steps trigger pre-flight confirmation."""
        from custom_components.otis_ai.macro_manager import MacroManager

        mm = MacroManager(self.hass)

        safe_steps = [
            {"domain": "light", "service": "turn_on", "target": {"entity_id": "light.living"}},
            {"domain": "climate", "service": "set_temperature", "target": {"entity_id": "climate.main"}},
        ]
        safety_safe = mm.inspect_safety(safe_steps)
        self.assertFalse(safety_safe["requires_confirmation"])
        self.assertEqual(len(safety_safe["safety_warnings"]), 0)

        critical_steps = [
            {"domain": "lock", "service": "unlock", "target": {"entity_id": "lock.front_door"}},
            {"domain": "alarm_control_panel", "service": "alarm_disarm", "target": {"entity_id": "alarm_control_panel.home"}},
            {"domain": "cover", "service": "open_cover", "target": {"entity_id": "cover.garage"}},
        ]
        safety_crit = mm.inspect_safety(critical_steps)
        self.assertTrue(safety_crit["requires_confirmation"])
        self.assertEqual(len(safety_crit["critical_steps"]), 3)
        self.assertEqual(len(safety_crit["safety_warnings"]), 3)

    def test_macro_execution_with_atomic_snapshot(self):
        """Verify atomic snapshot capturing prior state and sequential step execution."""
        from custom_components.otis_ai.macro_manager import MacroManager

        state_light = MagicMock()
        state_light.state = "on"
        state_light.attributes = {"brightness": 255, "friendly_name": "Living Light"}

        state_clim = MagicMock()
        state_clim.state = "cool"
        state_clim.attributes = {"temperature": 74}

        def mock_get_state(eid):
            if eid == "light.living":
                return state_light
            if eid == "climate.main":
                return state_clim
            return None

        self.hass.states.get.side_effect = mock_get_state

        mm = MacroManager(self.hass)
        steps = [
            {"domain": "light", "service": "turn_on", "target": {"entity_id": "light.living"}, "data": {"brightness_pct": 20}},
            {"domain": "climate", "service": "set_temperature", "target": {"entity_id": "climate.main"}, "data": {"temperature": 68}},
        ]

        res = asyncio.run(mm.async_execute_macro(macro_name="Test Macro", steps=steps, confirmed=True))
        self.assertTrue(res["success"])
        self.assertEqual(res["steps_executed"], 2)
        self.assertEqual(res["snapshot_entities_count"], 2)

        history = mm.get_history()
        self.assertEqual(len(history), 1)
        record = history[0]
        self.assertEqual(record["status"], "executed")
        self.assertEqual(record["snapshot"]["light.living"]["state"], "on")
        self.assertEqual(record["snapshot"]["light.living"]["attributes"]["brightness"], 255)

    def test_macro_confirmation_guard(self):
        """Verify unconfirmed macro with critical steps is guarded until confirmed."""
        from custom_components.otis_ai.macro_manager import MacroManager

        mm = MacroManager(self.hass)
        steps = [
            {"domain": "lock", "service": "unlock", "target": {"entity_id": "lock.front_door"}},
        ]

        # First run: unconfirmed
        res = asyncio.run(mm.async_execute_macro(macro_name="Unlock Arrival", steps=steps, confirmed=False))
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "requires_confirmation")
        m_id = res["macro_id"]
        self.assertIsNotNone(mm.get_pending_macro(m_id))

        # Second run: confirmed
        res_conf = asyncio.run(mm.async_execute_macro(macro_name="Unlock Arrival", steps=steps, confirmed=True, macro_id=m_id))
        self.assertTrue(res_conf["success"])
        self.assertIsNone(mm.get_pending_macro(m_id))

    def test_macro_rollback(self):
        """Verify complete state restoration on rollback."""
        from custom_components.otis_ai.macro_manager import MacroManager

        state_light = MagicMock()
        state_light.state = "on"
        state_light.attributes = {"brightness": 200, "color_temp": 300}

        state_clim = MagicMock()
        state_clim.state = "cool"
        state_clim.attributes = {"temperature": 75}

        state_mp = MagicMock()
        state_mp.state = "playing"
        state_mp.attributes = {"source": "Spotify Bridge", "volume_level": 0.25}

        state_lock = MagicMock()
        state_lock.state = "locked"
        state_lock.attributes = {}

        def mock_get_state(eid):
            if eid == "light.living":
                return state_light
            if eid == "climate.thermostat":
                return state_clim
            if eid == "media_player.great_room":
                return state_mp
            if eid == "lock.front_door":
                return state_lock
            return None

        self.hass.states.get.side_effect = mock_get_state

        mm = MacroManager(self.hass)
        steps = [
            {"domain": "light", "service": "turn_off", "target": {"entity_id": "light.living"}},
            {"domain": "climate", "service": "set_temperature", "target": {"entity_id": "climate.thermostat"}, "data": {"temperature": 66}},
            {"domain": "media_player", "service": "volume_set", "target": {"entity_id": "media_player.great_room"}, "data": {"volume_level": 0.5}},
            {"domain": "lock", "service": "unlock", "target": {"entity_id": "lock.front_door"}},
        ]

        exec_res = asyncio.run(mm.async_execute_macro(macro_name="Night Lockdown", steps=steps, confirmed=True))
        self.assertTrue(exec_res["success"])

        # Execute rollback
        rb_res = asyncio.run(mm.async_rollback_macro())
        self.assertTrue(rb_res["success"])
        self.assertEqual(rb_res["restored_count"], 4)
        self.assertIn("light.living", rb_res["restored_entities"])
        self.assertIn("climate.thermostat", rb_res["restored_entities"])
        self.assertIn("media_player.great_room", rb_res["restored_entities"])
        self.assertIn("lock.front_door", rb_res["restored_entities"])

        # Attempting rollback again should fail gracefully
        rb_again = asyncio.run(mm.async_rollback_macro())
        self.assertFalse(rb_again["success"])
        self.assertIn("already been rolled back", rb_again["error"])

    def test_conversational_macro_execution_and_rollback(self):
        """Verify conversational macro trigger ('prep movie night') and rollback ('undo')."""
        from custom_components.otis_ai import OtisAIConversationAgent
        from custom_components.otis_ai.macro_manager import MacroManager

        light = MagicMock()
        light.entity_id = "light.living_room_ceiling"
        light.state = "on"
        light.attributes = {"friendly_name": "Living Room Ceiling", "brightness": 255}

        tv = MagicMock()
        tv.entity_id = "media_player.living_room_tv"
        tv.state = "off"
        tv.attributes = {"friendly_name": "Living Room TV"}

        climate = MagicMock()
        climate.entity_id = "climate.thermostat"
        climate.state = "heat"
        climate.attributes = {"temperature": 72}

        self.hass.states.async_all.return_value = [light, tv, climate]
        self.hass.states.get.side_effect = lambda eid: {
            "light.living_room_ceiling": light,
            "media_player.living_room_tv": tv,
            "climate.thermostat": climate,
        }.get(eid)

        entry = MagicMock()
        engine = MagicMock()
        engine.async_build_capability_map = AsyncMock(return_value={"media_topology": {}})
        manager = MagicMock()
        macro_manager = MacroManager(self.hass)

        agent = OtisAIConversationAgent(
            self.hass, entry, engine, manager, macro_manager=macro_manager
        )

        # 1. Trigger "prep movie night"
        user_input_1 = MagicMock()
        user_input_1.text = "Prep home for movie night"
        user_input_1.conversation_id = "conv_movie"
        user_input_1.create_response = MagicMock(return_value="mock_resp")

        asyncio.run(agent.async_process(user_input_1))
        speech_1 = user_input_1.create_response.call_args[1]["speech"]
        self.assertIn("Movie Night Mode Activated", speech_1)
        self.assertIn("State snapshot saved", speech_1)

        # Verify history has 1 executed macro
        self.assertEqual(len(macro_manager.get_history()), 1)
        self.assertEqual(macro_manager.get_history()[0]["status"], "executed")

        # 2. Trigger "undo"
        user_input_2 = MagicMock()
        user_input_2.text = "undo macro"
        user_input_2.conversation_id = "conv_movie"
        user_input_2.create_response = MagicMock(return_value="mock_resp")

        asyncio.run(agent.async_process(user_input_2))
        speech_2 = user_input_2.create_response.call_args[1]["speech"]
        self.assertIn("Macro Rolled Back Successfully", speech_2)
        self.assertEqual(macro_manager.get_history()[0]["status"], "rolled_back")

    def test_conversational_macro_safety_confirmation(self):
        """Verify conversational macro with safety critical steps requires confirmation."""
        from custom_components.otis_ai import OtisAIConversationAgent
        from custom_components.otis_ai.macro_manager import MacroManager

        lock = MagicMock()
        lock.entity_id = "lock.front_door"
        lock.state = "locked"
        lock.attributes = {"friendly_name": "Front Door"}

        alarm = MagicMock()
        alarm.entity_id = "alarm_control_panel.security"
        alarm.state = "armed_home"
        alarm.attributes = {}

        self.hass.states.async_all.return_value = [lock, alarm]
        self.hass.states.get.side_effect = lambda eid: {
            "lock.front_door": lock,
            "alarm_control_panel.security": alarm,
        }.get(eid)

        entry = MagicMock()
        engine = MagicMock()
        engine.async_build_capability_map = AsyncMock(return_value={})
        manager = MagicMock()
        macro_manager = MacroManager(self.hass)

        agent = OtisAIConversationAgent(
            self.hass, entry, engine, manager, macro_manager=macro_manager
        )

        # 1. Trigger "welcome home" (contains unlock / disarm)
        user_input_1 = MagicMock()
        user_input_1.text = "I'm home"
        user_input_1.conversation_id = "conv_welcome"
        user_input_1.create_response = MagicMock(return_value="mock_resp")

        asyncio.run(agent.async_process(user_input_1))
        speech_1 = user_input_1.create_response.call_args[1]["speech"]
        self.assertIn("Safety Checks", speech_1)
        self.assertIn("Say 'yes' or 'confirm' to execute", speech_1)

        # Verify session holds pending_macro
        sessions = self.hass.data[DOMAIN]["sessions"]
        self.assertIn("conv_welcome", sessions)
        self.assertIn("pending_macro", sessions["conv_welcome"])

        # 2. Say "confirm"
        user_input_2 = MagicMock()
        user_input_2.text = "confirm"
        user_input_2.conversation_id = "conv_welcome"
        user_input_2.create_response = MagicMock(return_value="mock_resp")

        asyncio.run(agent.async_process(user_input_2))
        speech_2 = user_input_2.create_response.call_args[1]["speech"]
        self.assertIn("Activated", speech_2)
        self.assertNotIn("pending_macro", sessions["conv_welcome"])

    def test_audio_handoff_manager_discovery(self):
        """Test AudioHandoffManager discovers matrix amp zones, input streamers, and TV players."""
        from custom_components.otis_ai.audio_manager import AudioHandoffManager

        class MockMediaState:
            def __init__(self, entity_id, state="on", attributes=None):
                self.entity_id = entity_id
                self.state = state
                self.attributes = attributes or {}

        states = [
            MockMediaState("media_player.matrix_amp_1_great_room", "playing", {"source": "Bridge", "volume_level": 0.4}),
            MockMediaState("media_player.matrix_amp_1_study", "off", {"source": "Input 1", "volume_level": 0.2}),
            MockMediaState("media_player.bridge", "playing", {"friendly_name": "Bridge Streamer"}),
            MockMediaState("media_player.great_room_tv_4", "off", {"friendly_name": "Great Room TV"}),
        ]
        self.hass.states.async_all = MagicMock(return_value=states)

        mgr = AudioHandoffManager(self.hass)
        zones = asyncio.run(mgr.async_get_active_media_zones())
        self.assertTrue(zones["has_matrix_amp"])
        self.assertEqual(len(zones["matrix_zones"]), 2)
        self.assertEqual(len(zones["input_streamers"]), 1)
        self.assertEqual(len(zones["tv_cinema_players"]), 1)

    def test_audio_handoff_execution(self):
        """Test audio handoff routes source, volume, and releases departed room zone."""
        from custom_components.otis_ai.audio_manager import AudioHandoffManager

        class MockMediaState:
            def __init__(self, entity_id, state="on", attributes=None):
                self.entity_id = entity_id
                self.state = state
                self.attributes = attributes or {}

        states = [
            MockMediaState("media_player.matrix_amp_1_great_room", "playing", {"friendly_name": "Great Room", "source": "Bridge", "volume_level": 0.35}),
            MockMediaState("media_player.matrix_amp_1_study", "off", {"friendly_name": "Study", "source": "Input 1", "volume_level": 0.15}),
            MockMediaState("media_player.bridge", "playing", {"friendly_name": "Bridge"}),
        ]
        self.hass.states.async_all = MagicMock(return_value=states)
        self.hass.services.has_service = MagicMock(return_value=True)

        spatial_mock = MagicMock()
        spatial_mock.async_get_graph = AsyncMock(return_value={
            "named_adjacencies": {"great_room": ["study"], "study": ["great_room"]}
        })

        mgr = AudioHandoffManager(self.hass, spatial_manager=spatial_mock)
        res = asyncio.run(mgr.async_audio_handoff(
            source_area="great_room",
            target_area="study",
            mode="handoff",
            idle_power_guard=False,
        ))

        self.assertTrue(res["success"])
        self.assertTrue(res["spatially_adjacent"])
        self.assertEqual(res["source_player"], "media_player.matrix_amp_1_great_room")
        self.assertEqual(res["target_player"], "media_player.matrix_amp_1_study")

        calls = self.hass.services.async_call.call_args_list
        called = [(c[0][0], c[0][1], c[0][2].get("entity_id")) for c in calls]
        self.assertIn(("media_player", "turn_on", "media_player.matrix_amp_1_study"), called)
        self.assertIn(("media_player", "select_source", "media_player.matrix_amp_1_study"), called)
        self.assertIn(("media_player", "turn_off", "media_player.matrix_amp_1_great_room"), called)

    def test_audio_handoff_release_idle_sources(self):
        """Test idle guard pauses streamers when no matrix zones are listening."""
        from custom_components.otis_ai.audio_manager import AudioHandoffManager

        class MockMediaState:
            def __init__(self, entity_id, state="on", attributes=None):
                self.entity_id = entity_id
                self.state = state
                self.attributes = attributes or {}

        states = [
            MockMediaState("media_player.matrix_amp_1_great_room", "off", {"source": "Bridge"}),
            MockMediaState("media_player.bridge", "playing", {"friendly_name": "Bridge"}),
        ]
        self.hass.states.async_all = MagicMock(return_value=states)

        mgr = AudioHandoffManager(self.hass)
        res = asyncio.run(mgr.async_release_idle_sources())
        self.assertTrue(res["success"])
        self.assertIn("media_player.bridge", res["streamers_paused"])

        calls = self.hass.services.async_call.call_args_list
        pause_calls = [c for c in calls if c[0][1] == "media_pause"]
        self.assertEqual(len(pause_calls), 1)

    def test_audio_handoff_voice_notify(self):
        """Test voice feedback routed through script.notify_router."""
        from custom_components.otis_ai.audio_manager import AudioHandoffManager

        self.hass.services.has_service = MagicMock(return_value=True)
        mgr = AudioHandoffManager(self.hass)

        res = asyncio.run(mgr.async_notify_voice(
            message="Motion detected on Front Porch",
            area_id="great_room",
            announce=True,
        ))

        self.assertTrue(res["success"])
        self.assertEqual(res["routed_via"], "script.notify_router")

    def test_energy_manager_discovery_and_summary(self):
        """Test EnergyManager discovers power sensors, solar, UPS, and computes telemetry."""
        from custom_components.otis_ai.energy_manager import EnergyManager

        class MockEntityState:
            def __init__(self, entity_id, state="0", attributes=None):
                self.entity_id = entity_id
                self.state = state
                self.attributes = attributes or {}

        states = [
            MockEntityState("sensor.fridge_kitchen_power", "180.5", {"unit_of_measurement": "W", "device_class": "power", "friendly_name": "Kitchen Fridge"}),
            MockEntityState("sensor.shelf_dimmer_power", "45.0", {"unit_of_measurement": "W", "friendly_name": "Shelf Dimmer"}),
            MockEntityState("sensor.fridge_kitchen_energy", "12.4", {"unit_of_measurement": "kWh", "device_class": "energy"}),
            MockEntityState("sensor.ups_theater_battery_charge", "100", {"unit_of_measurement": "%"}),
            MockEntityState("sensor.ups_theater_battery_runtime", "3200", {"unit_of_measurement": "s"}),
            MockEntityState("switch.amp_power", "on", {"friendly_name": "Main Amplifier"}),
            MockEntityState("switch.pool_pump", "on", {"friendly_name": "Pool Pump"}),
        ]
        self.hass.states.async_all = MagicMock(return_value=states)
        self.hass.states.get = MagicMock(side_effect=lambda eid: next((s for s in states if s.entity_id == eid), None))

        mgr = EnergyManager(self.hass)
        summary = asyncio.run(mgr.async_get_energy_summary())

        self.assertAlmostEqual(summary["total_power_w"], 225.5, places=1)
        self.assertEqual(summary["active_power_sensors_count"], 2)
        self.assertEqual(len(summary["top_consumers"]), 2)
        self.assertEqual(summary["top_consumers"][0]["entity_id"], "sensor.fridge_kitchen_power")
        self.assertIn("tariff", summary)
        self.assertIn("period", summary["tariff"])
        self.assertIn("load_shedding", summary)
        self.assertGreaterEqual(summary["load_shedding"]["active_sheddable_loads_count"], 1)

    def test_energy_manager_load_shed_and_restore(self):
        """Test EnergyManager executes load shedding and restores previous states."""
        from custom_components.otis_ai.energy_manager import EnergyManager

        class MockEntityState:
            def __init__(self, entity_id, state="on", attributes=None):
                self.entity_id = entity_id
                self.state = state
                self.attributes = attributes or {}

        states = [
            MockEntityState("switch.amp_power", "on", {"friendly_name": "Main Amplifier"}),
            MockEntityState("switch.pool_pump", "on", {"friendly_name": "Pool Pump"}),
            MockEntityState("climate.living_room", "heat", {"temperature": 70, "friendly_name": "Living Room HVAC"}),
        ]
        self.hass.states.async_all = MagicMock(return_value=states)
        self.hass.states.get = MagicMock(side_effect=lambda eid: next((s for s in states if s.entity_id == eid), None))

        mgr = EnergyManager(self.hass)

        # 1. Execute load shed Tier 1
        res = asyncio.run(mgr.async_execute_load_shed(tier=1))
        self.assertTrue(res["success"])
        self.assertGreaterEqual(res["shed_count"], 1)
        self.assertIn("switch.pool_pump", res["executed_entities"])

        calls = self.hass.services.async_call.call_args_list
        turn_off_calls = [c for c in calls if c[0][1] == "turn_off"]
        self.assertTrue(any(c[0][2].get("entity_id") == "switch.pool_pump" for c in turn_off_calls))

        # 2. Restore shedded loads
        res_restore = asyncio.run(mgr.async_restore_shed_loads())
        self.assertTrue(res_restore["success"])
        self.assertGreaterEqual(res_restore["restored_count"], 1)

        calls_after = self.hass.services.async_call.call_args_list
        turn_on_calls = [c for c in calls_after if c[0][1] == "turn_on"]
        self.assertTrue(any(c[0][2].get("entity_id") == "switch.pool_pump" for c in turn_on_calls))

    def test_conversational_energy_commands(self):
        """Test natural language energy queries and conversational load shedding in OtisAIConversationAgent."""
        from custom_components.otis_ai import OtisAIConversationAgent
        from custom_components.otis_ai.energy_manager import EnergyManager

        class MockEntityState:
            def __init__(self, entity_id, state="on", attributes=None):
                self.entity_id = entity_id
                self.state = state
                self.attributes = attributes or {}

        states = [
            MockEntityState("sensor.fridge_kitchen_power", "150.0", {"unit_of_measurement": "W", "device_class": "power", "friendly_name": "Kitchen Fridge"}),
            MockEntityState("switch.pool_pump", "on", {"friendly_name": "Pool Pump"}),
        ]
        self.hass.states.async_all = MagicMock(return_value=states)
        self.hass.states.get = MagicMock(side_effect=lambda eid: next((s for s in states if s.entity_id == eid), None))

        entry = MagicMock()
        entry.options = {}
        entry.data = {}
        engine = MagicMock()
        manager = MagicMock()
        energy_manager = EnergyManager(self.hass)

        agent = OtisAIConversationAgent(
            self.hass, entry, engine, manager, energy_manager=energy_manager
        )

        # 1. Query energy summary
        u1 = MagicMock()
        u1.text = "How much power is the house using right now?"
        u1.conversation_id = "test_conv_energy"
        u1.create_response = MagicMock(return_value="mock_resp")
        asyncio.run(agent.async_process(u1))
        speech1 = u1.create_response.call_args[1]["speech"]
        self.assertIn("Otis Energy & Load Orchestrator", speech1)
        self.assertIn("150.0 W", speech1)

        # 2. Trigger load shed
        u2 = MagicMock()
        u2.text = "Shed non-essential loads for peak hours"
        u2.conversation_id = "test_conv_energy"
        u2.create_response = MagicMock(return_value="mock_resp")
        asyncio.run(agent.async_process(u2))
        speech2 = u2.create_response.call_args[1]["speech"]
        self.assertIn("Dynamic Load Shedding Executed", speech2)
        self.assertIn("switch.pool_pump", speech2)

        # 3. Restore shedded loads
        u3 = MagicMock()
        u3.text = "Restore shedded loads"
        u3.conversation_id = "test_conv_energy"
        u3.create_response = MagicMock(return_value="mock_resp")
        asyncio.run(agent.async_process(u3))
        speech3 = u3.create_response.call_args[1]["speech"]
        self.assertIn("Restored", speech3)

    def test_smart_home_maturity_tips_and_proactive_recommendations(self):
        """Verify that smart home maturity calculates tips and guarantees proactive recommendations for <20/20 scores."""
        from custom_components.otis_ai import DiscoveryEngine
        from custom_components.otis_ai.floorplan_parser import FloorplanParser

        parser = FloorplanParser(self.hass)
        engine = DiscoveryEngine(self.hass, floorplan_parser=parser)

        # 1. Test _discover_system_maturity tips and gaps calculation
        areas_map = {
            "kitchen": {"name": "Kitchen", "entities": ["light.kitchen"]},
        }
        devices_map = {
            "dev_unassigned": {"id": "dev_unassigned", "name": "Kitchen Outlet", "area_id": None}
        }
        entities_list = [
            {"entity_id": "light.kitchen", "name": "Kitchen Light", "domain": "light", "area_id": "kitchen"}
        ]
        orphaned = [{"entity_id": "switch.dead_plug"}]
        active_integrations = []
        media_topology = {"matrix_amp_detected": False, "total_media_players": 0}
        security_topology = {"alarm_panels": [], "locks": [], "persons": []}

        maturity = engine._discover_system_maturity(
            areas_map=areas_map,
            devices_map=devices_map,
            entities_list=entities_list,
            orphaned_entities=orphaned,
            active_integrations=active_integrations,
            has_walkthrough=False,
            has_floorplan=False,
            media_topology=media_topology,
            security_topology=security_topology,
        )

        self.assertIn("tips", maturity)
        self.assertIn("gaps", maturity)
        tips = maturity["tips"]
        bd = maturity["breakdown"]

        for cat in ("spatial", "hygiene", "automation", "security", "media"):
            self.assertIn(cat, tips)
            if bd[cat] < 20:
                self.assertIn("To reach 20/20:", tips[cat])
            else:
                self.assertIn("20/20 (Perfect)", tips[cat])

        # 2. Test async_generate_proactive_suggestions generates maturity goal cards
        cap_map = {
            "areas": areas_map,
            "devices": devices_map,
            "entities": entities_list,
            "orphaned_entities": orphaned,
            "integrations": active_integrations,
            "media_topology": media_topology,
            "security_topology": security_topology,
            "maturity": maturity,
            "spatial_graph": {"adjacencies": {}},
        }
        suggestions = asyncio.run(engine.async_generate_proactive_suggestions(cap_map))
        s_ids = {s["id"] for s in suggestions}

        # Spatial maturity card or walkthrough recommendation should exist
        self.assertTrue("record_walkthrough_floorplan" in s_ids or "maturity_reach_20_spatial" in s_ids)
        # Hygiene maturity card or orphan cleanup should exist
        self.assertTrue("cleanup_orphans_1" in s_ids or "maturity_reach_20_hygiene" in s_ids)
        # Automation maturity card should exist
        self.assertTrue("maturity_reach_20_automation" in s_ids or any(s.get("category") == "automation" for s in suggestions))
        # Security maturity card should exist
        self.assertTrue("maturity_reach_20_security" in s_ids or any(s.get("category") == "security" for s in suggestions))
        # Media maturity card should exist
        self.assertTrue("maturity_reach_20_media" in s_ids or any(s.get("category") == "media" for s in suggestions))


if __name__ == "__main__":
    unittest.main()






