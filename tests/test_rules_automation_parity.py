"""Test suite for user behavioral rules, immediate propagation, and Assist Co-Pilot automation parity."""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from custom_components.otis_ai.agent_orchestrator import AGENT_EXECUTIVE, MultiAgentOrchestrator
from custom_components.otis_ai.const import CONF_REASONING_TIMEOUT
from custom_components.otis_ai.macro_manager import MacroManager
from custom_components.otis_ai.rules_manager import BehavioralRulesManager


class TestRulesAndAutomationParity(unittest.TestCase):
    """Test user behavioral rules, immediate effects, and card vs Assist Co-Pilot automation parity."""

    def setUp(self) -> None:
        """Set up test environment."""
        self.hass = MagicMock()
        self.hass.data = {}
        self.hass.config.config_dir = "/config"
        self.hass.states.async_set = MagicMock()
        self.hass.states.async_all.return_value = []
        self.hass.bus.async_fire = MagicMock()
        self.hass.async_add_executor_job = AsyncMock()

    def test_rules_manager_reasoning_timeout_and_toggles(self) -> None:
        """Verify rules manager defaults and validation for reasoning_timeout, presence_room_cards, and voice toggles."""
        rm = BehavioralRulesManager(self.hass)
        mock_store = AsyncMock()
        mock_store.async_load.return_value = None
        mock_store.async_save = AsyncMock()
        rm._store = mock_store

        rules = asyncio.run(rm.async_load())
        self.assertEqual(rules.get("reasoning_timeout"), 60)
        self.assertTrue(rules.get("presence_room_cards"))
        self.assertTrue(rules.get("voice_announcements_enabled"))
        self.assertTrue(rules.get("voice_filter_passersby"))

        # Save with valid updates and volume/timeout clamping
        saved = asyncio.run(rm.async_save({
            "reasoning_timeout": 120,
            "presence_room_cards": False,
            "voice_announcements_enabled": False,
            "voice_filter_passersby": False,
        }))
        self.assertEqual(saved["reasoning_timeout"], 120)
        self.assertFalse(saved["presence_room_cards"])
        self.assertFalse(saved["voice_announcements_enabled"])
        self.assertFalse(saved["voice_filter_passersby"])

        # Clamping below min (10) and above max (300)
        clamped_low = asyncio.run(rm.async_save({"reasoning_timeout": 2}))
        self.assertEqual(clamped_low["reasoning_timeout"], 10)

        clamped_high = asyncio.run(rm.async_save({"reasoning_timeout": 500}))
        self.assertEqual(clamped_high["reasoning_timeout"], 300)

    def test_macro_manager_safety_inspect_respects_rules(self) -> None:
        """Verify MacroManager dynamically checks rules_manager for autonomy and confirmations."""
        mock_rm = MagicMock()
        mock_rm.get_rules.return_value = {
            "autonomy_level": "balanced",
            "require_lock_confirmation": True,
            "require_security_confirmation": True,
        }

        mm = MacroManager(self.hass, rules_manager=mock_rm)

        steps = [
            {"domain": "light", "service": "turn_on", "name": "Living Room Lights"},
            {"domain": "lock", "service": "unlock", "name": "Front Door Deadbolt"},
        ]

        # 1. Balanced with require_lock_confirmation = True -> requires confirmation
        safety = mm.inspect_safety(steps)
        self.assertTrue(safety["requires_confirmation"])
        self.assertEqual(len(safety["critical_steps"]), 1)

        # 2. Balanced with require_lock_confirmation = False -> bypasses confirmation for lock
        mock_rm.get_rules.return_value = {
            "autonomy_level": "balanced",
            "require_lock_confirmation": False,
            "require_security_confirmation": True,
        }
        safety = mm.inspect_safety(steps)
        self.assertFalse(safety["requires_confirmation"])

        # 3. High autonomy with require_lock = False -> executes immediately
        mock_rm.get_rules.return_value = {
            "autonomy_level": "high",
            "require_lock_confirmation": False,
            "require_security_confirmation": False,
        }
        safety = mm.inspect_safety(steps)
        self.assertFalse(safety["requires_confirmation"])

        # 4. Strict autonomy -> requires confirmation even for lighting
        mock_rm.get_rules.return_value = {
            "autonomy_level": "strict",
            "require_lock_confirmation": False,
            "require_security_confirmation": False,
        }
        safety = mm.inspect_safety([{"domain": "light", "service": "turn_on"}])
        self.assertTrue(safety["requires_confirmation"])

    def test_multi_agent_orchestrator_receives_rules_snippet(self) -> None:
        """Verify MultiAgentOrchestrator incorporates behavioral rules into specialist prompts."""
        mock_rm = MagicMock()
        mock_rm.get_system_prompt_snippet.return_value = "### Persona: Butler. Tone: formal."

        mock_llm = MagicMock()
        mock_llm.model = "mock-model"
        mock_llm.async_generate = AsyncMock(return_value={"success": True, "response": "Acknowledged."})

        orch = MultiAgentOrchestrator(self.hass, local_llm_manager=mock_llm, rules_manager=mock_rm)

        res = asyncio.run(orch._async_invoke_specialist(
            agent_id=AGENT_EXECUTIVE,
            prompt="Turn off the patio lights",
            conversation_id="conv_1",
            context=None,
            timeout=10.0,
        ))

        self.assertEqual(res["agent"], AGENT_EXECUTIVE)
        mock_llm.async_generate.assert_called_once()
        call_kwargs = mock_llm.async_generate.call_args[1]
        self.assertIn("Butler", call_kwargs["system_prompt"])
        self.assertIn("formal", call_kwargs["system_prompt"])

    def test_assist_copilot_automation_parity_matching(self) -> None:
        """Verify Assist Co-Pilot matches proactive suggestions and applies exact same automation payload."""
        from custom_components.otis_ai import OtisAIConversationAgent

        mock_engine = MagicMock()
        mock_auto_mgr = MagicMock()
        mock_auto_mgr.async_write_automation = AsyncMock(return_value="auto_cinema_123")
        mock_auto_mgr.async_reload_automations = AsyncMock()

        mock_rm = MagicMock()
        mock_rm.get_dismissed_recommendations.return_value = []
        mock_rm.async_dismiss_recommendation = AsyncMock(return_value=["cinema_lighting_shade_coordinator"])
        mock_rm.async_reset_dismissed_recommendations = AsyncMock()

        # Vetted suggestion payload identical to card
        cinema_suggestion = {
            "id": "cinema_lighting_shade_coordinator",
            "title": "Cinema Mode Lighting & Shade Coordinator (Living Room TV)",
            "description": "Dim lights when TV plays and restore on pause.",
            "category": "media",
            "action_type": "create_automation",
            "action_payload": {
                "alias": "Cinema Mode Coordinator: Living Room TV",
                "trigger": [{"platform": "state", "entity_id": "media_player.living_room_tv", "to": "playing"}],
                "action": [{"service": "light.turn_on", "target": {"entity_id": "light.living_room"}}],
                "mode": "single",
            },
        }

        mock_engine.async_build_capability_map = AsyncMock(return_value={
            "proactive_suggestions": [cinema_suggestion],
            "entities": [],
            "orphaned_entities": [],
        })
        mock_engine.invalidate_cache = MagicMock()

        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry"
        mock_entry.options = {CONF_REASONING_TIMEOUT: 60}
        mock_entry.data = {}

        agent = OtisAIConversationAgent(
            self.hass,
            mock_entry,
            mock_engine,
            mock_auto_mgr,
            rules_manager=mock_rm,
        )

        # 1. Test listing recommendations conversationally
        user_input_list = MagicMock()
        user_input_list.text = "What recommendations do you have?"
        user_input_list.conversation_id = "test_conv"
        user_input_list.agent_id = "test_entry"
        user_input_list.create_response = MagicMock()

        asyncio.run(agent.async_process(user_input_list))
        speech_list = user_input_list.create_response.call_args[1]["speech"]
        self.assertIn("Cinema Mode Lighting & Shade Coordinator", speech_list)
        self.assertIn("cinema_lighting_shade_coordinator", speech_list)

        # 2. Test applying suggestion via Assist Co-Pilot (high autonomy / explicit apply)
        mock_rm.get_rules.return_value = {"autonomy_level": "high"}
        user_input_apply = MagicMock()
        user_input_apply.text = "apply suggestion 1"
        user_input_apply.conversation_id = "test_conv"
        user_input_apply.agent_id = "test_entry"
        user_input_apply.create_response = MagicMock()

        asyncio.run(agent.async_process(user_input_apply))
        speech_apply = user_input_apply.create_response.call_args[1]["speech"]
        self.assertIn("Automation Created and Enabled!", speech_apply)
        self.assertIn("Cinema Mode Coordinator: Living Room TV", speech_apply)

        # Verify exact same payload was passed to AutomationManager as card apply_suggestion
        mock_auto_mgr.async_write_automation.assert_called_once_with(cinema_suggestion["action_payload"])
        mock_auto_mgr.async_reload_automations.assert_called_once()
        mock_rm.async_dismiss_recommendation.assert_called_once_with("cinema_lighting_shade_coordinator")

        # 3. Test balanced autonomy creates staging with exact YAML and asks for confirmation
        mock_auto_mgr.async_write_automation.reset_mock()
        mock_rm.get_rules.return_value = {"autonomy_level": "balanced"}

        user_input_create = MagicMock()
        user_input_create.text = "can you create cinema mode lighting automation?"
        user_input_create.conversation_id = "test_conv_2"
        user_input_create.agent_id = "test_entry"
        user_input_create.create_response = MagicMock()

        asyncio.run(agent.async_process(user_input_create))
        speech_create = user_input_create.create_response.call_args[1]["speech"]
        self.assertIn("```yaml", speech_create)
        self.assertIn("media_player.living_room_tv", speech_create)
        self.assertIn("Would you like me to create and enable this automation", speech_create)
        self.assertIn("Say 'yes' or 'apply' to confirm", speech_create)
        mock_auto_mgr.async_write_automation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
