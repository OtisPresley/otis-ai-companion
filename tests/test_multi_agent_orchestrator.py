"""Unit tests for Otis Multi-Agent Conversational Orchestration & Voice Satellites (Phase 9)."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from custom_components.otis_ai.agent_orchestrator import (
    AGENT_AUTOMATOR,
    AGENT_ENERGY,
    AGENT_EXECUTIVE,
    AGENT_MEDIA_SPATIAL,
    AGENT_SENTINEL,
    AGENT_SPECIFICATIONS,
    ALL_AGENTS,
    MultiAgentOrchestrator,
)


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = MagicMock()
    states_dict = {}

    def mock_set(entity_id, state, attributes=None):
        mock_state = MagicMock()
        mock_state.entity_id = entity_id
        mock_state.state = state
        mock_state.attributes = attributes or {}
        states_dict[entity_id] = mock_state

    def mock_get(entity_id):
        return states_dict.get(entity_id)

    def mock_all(domain=None):
        if domain:
            prefix = f"{domain}."
            return [s for eid, s in states_dict.items() if eid.startswith(prefix)]
        return list(states_dict.values())

    from custom_components.otis_ai.const import DOMAIN

    class _EntityMap(dict):
        def get(self, key, default=None):
            if key not in self:
                ent = MagicMock()
                ent.async_set_state = lambda state, attributes=None, _eid=key: mock_set(_eid, state, attributes)
                self[key] = ent
            return super().get(key, default)

    hass.data = {DOMAIN: {"test_entry": {"entities": _EntityMap()}}}
    hass.states.async_set = mock_set
    hass.states.get = mock_get
    hass.states.async_all = mock_all
    return hass


@pytest.fixture
def mock_sentinel():
    """Mock Sentinel Manager."""
    sentinel = MagicMock()
    sentinel.async_audit_perimeter = AsyncMock(return_value={
        "status": "secure",
        "unlocked_doors": [],
        "open_windows": [],
    })
    return sentinel


@pytest.fixture
def mock_energy():
    """Mock Energy Manager."""
    energy = MagicMock()
    energy.discover_energy_topology = MagicMock(return_value={
        "current_solar_power_w": 4200.0,
        "battery_average_soc": 85.0,
    })
    return energy


@pytest.fixture
def mock_presence():
    """Mock Presence Fusion Manager."""
    presence = MagicMock()
    presence.get_presence_summary = MagicMock(return_value={
        "occupied_areas": ["kitchen", "living_room"],
        "micro_presence_areas": [],
    })
    return presence


@pytest.fixture
def orchestrator(mock_hass, mock_sentinel, mock_energy, mock_presence):
    """Instantiate MultiAgentOrchestrator with mocked dependencies."""
    orch = MultiAgentOrchestrator(
        hass=mock_hass,
        sentinel_manager=mock_sentinel,
        energy_manager=mock_energy,
        presence_fusion_manager=mock_presence,
    )
    # Mock storage so it does not perform filesystem operations
    orch._store = MagicMock()
    orch._store.async_load = AsyncMock(return_value=None)
    orch._store.async_save = AsyncMock()
    return orch


class TestMultiAgentOrchestrator:
    """Test suite for MultiAgentOrchestrator."""

    def test_agent_specifications_completeness(self):
        """Verify all 5 specialized agents are defined with complete specifications."""
        assert len(ALL_AGENTS) == 5
        for agent_id in ALL_AGENTS:
            assert agent_id in AGENT_SPECIFICATIONS
            spec = AGENT_SPECIFICATIONS[agent_id]
            assert "name" in spec
            assert "role" in spec
            assert "domains" in spec
            assert "system_prompt" in spec
            assert "priority" in spec

    def test_intent_classification_single_domains(self, orchestrator):
        """Verify single domain prompts route to the appropriate specialist persona."""
        # Sentinel
        agents = orchestrator.classify_intent("Is the front door deadbolt locked?")
        assert AGENT_SENTINEL in agents

        # Energy
        agents = orchestrator.classify_intent("What is our solar battery charging state and TOU tariff?")
        assert AGENT_ENERGY in agents

        # Media / Spatial
        agents = orchestrator.classify_intent("Play jazz music in the kitchen and follow me to the bedroom")
        assert AGENT_MEDIA_SPATIAL in agents

        # Automator
        agents = orchestrator.classify_intent("Create a blueprint automation routine for movie night")
        assert AGENT_AUTOMATOR in agents

        # Executive (general/status/greetings)
        agents = orchestrator.classify_intent("Good morning Otis, what's on the schedule today?")
        assert AGENT_EXECUTIVE in agents

    def test_intent_classification_composite_multi_domain(self, orchestrator):
        """Verify composite queries route to multiple specialized agents."""
        prompt = "Lock the perimeter deadbolts, check tomorrow's solar forecast, and automate lights off"
        agents = orchestrator.classify_intent(prompt)
        assert AGENT_SENTINEL in agents
        assert AGENT_ENERGY in agents
        assert AGENT_AUTOMATOR in agents
        assert len(agents) >= 3

    @pytest.mark.asyncio
    async def test_async_orchestrate_single_agent(self, orchestrator):
        """Verify single agent orchestration returns localized specialist response and updates metrics."""
        res = await orchestrator.async_orchestrate(
            prompt="Is the perimeter secure?",
            mode="single",
        )
        assert res["success"] is True
        assert res["primary_agent"] == AGENT_SENTINEL
        assert res["is_collaboration"] is False
        assert AGENT_SENTINEL in res["agent_responses"]
        assert "Sentinel Security Specialist" in res["synthesized_response"]
        assert orchestrator._metrics["single_agent_routes"] == 1
        assert orchestrator._metrics["total_requests"] == 1

    @pytest.mark.asyncio
    async def test_async_orchestrate_collaborative_synthesis(self, orchestrator):
        """Verify multi-agent collaborative synthesis across multiple specialists."""
        prompt = "Prepare the house for departure: lock doors and maximize solar battery storage"
        res = await orchestrator.async_orchestrate(
            prompt=prompt,
            requested_agents=[AGENT_SENTINEL, AGENT_ENERGY],
        )
        assert res["success"] is True
        assert res["is_collaboration"] is True
        assert len(res["selected_agents"]) == 2
        assert AGENT_SENTINEL in res["agent_responses"]
        assert AGENT_ENERGY in res["agent_responses"]
        assert "**Otis Multi-Agent Synthesis**" in res["synthesized_response"]
        assert "Sentinel Security Specialist" in res["synthesized_response"]
        assert "Energy & Resource Architect" in res["synthesized_response"]
        assert orchestrator._metrics["multi_agent_collaborations"] == 1
        assert orchestrator._metrics["total_requests"] == 1

    @pytest.mark.asyncio
    async def test_satellite_discovery_and_configuration(self, mock_hass, orchestrator):
        """Verify assist_satellite discovery and localized configuration."""
        # Set up a mock assist satellite state in HA
        mock_hass.states.async_set(
            "assist_satellite.kitchen_box",
            "idle",
            {"friendly_name": "Kitchen Satellite Box", "area_id": "kitchen"},
        )

        sats = orchestrator.get_discovered_satellites()
        assert len(sats) == 1
        assert sats[0]["entity_id"] == "assist_satellite.kitchen_box"
        assert sats[0]["area_id"] == "kitchen"
        assert sats[0]["wake_word"] == "Hey Otis"

        # Configure custom localized wake word and persona
        cfg_res = await orchestrator.async_configure_satellite(
            satellite_id="assist_satellite.kitchen_box",
            area_id="kitchen",
            assigned_agent=AGENT_AUTOMATOR,
            wake_word="Computer",
            wake_word_engine="openwakeword",
            preferred_speaker="media_player.kitchen_speaker",
        )
        assert cfg_res["success"] is True
        assert cfg_res["config"]["wake_word"] == "Computer"
        assert cfg_res["config"]["assigned_agent"] == AGENT_AUTOMATOR

        # Verify discovery reflects updated settings
        updated_sats = orchestrator.get_discovered_satellites()
        assert updated_sats[0]["wake_word"] == "Computer"
        assert updated_sats[0]["assigned_agent"] == AGENT_AUTOMATOR
        assert updated_sats[0]["preferred_speaker"] == "media_player.kitchen_speaker"

    def test_acoustic_arbitration_single_candidate(self, orchestrator):
        """Verify arbitration returns 1.0 confidence when only one satellite heard audio."""
        candidates = [{"satellite_id": "assist_satellite.living_room", "area_id": "living_room"}]
        res = orchestrator.arbitrate_satellite_audio(candidates, utterance="Turn on lights")
        assert res["success"] is True
        assert res["winning_satellite_id"] == "assist_satellite.living_room"
        assert res["confidence"] == 1.0
        assert res["suppressed_satellites"] == []

    def test_acoustic_arbitration_multi_candidate_deduplication(self, mock_hass, orchestrator):
        """Verify competing satellites are arbitrated using RSSI, SNR, and room presence."""
        # Living room has active presence
        mock_hass.states.async_set("binary_sensor.otis_presence_living_room", "on")

        candidates = [
            {
                "satellite_id": "assist_satellite.hallway",
                "area_id": "hallway",
                "rssi": -78.0,
                "snr": 10.0,
                "timestamp": 1000.0,
            },
            {
                "satellite_id": "assist_satellite.living_room",
                "area_id": "living_room",
                "rssi": -48.0,
                "snr": 24.0,
                "timestamp": 1000.1,
            },
            {
                "satellite_id": "assist_satellite.kitchen",
                "area_id": "kitchen",
                "rssi": -82.0,
                "snr": 8.0,
                "timestamp": 1000.2,
            },
        ]

        res = orchestrator.arbitrate_satellite_audio(candidates, utterance="Dim the lights")
        assert res["success"] is True
        assert res["winning_satellite_id"] == "assist_satellite.living_room"
        assert res["winning_area_id"] == "living_room"
        assert "assist_satellite.hallway" in res["suppressed_satellites"]
        assert "assist_satellite.kitchen" in res["suppressed_satellites"]
        assert len(res["suppressed_satellites"]) == 2
        assert res["confidence"] > 0.70

    @pytest.mark.asyncio
    async def test_telemetry_sensor_publication(self, mock_hass, orchestrator):
        """Verify sensor.otis_multi_agent_orchestrator and sensor.otis_voice_satellites state publication."""
        await orchestrator.async_publish_telemetry()

        # Orchestrator sensor
        orch_state = mock_hass.states.get("sensor.otis_multi_agent_orchestrator")
        assert orch_state is not None
        assert orch_state.state in ("idle", "active")
        assert orch_state.attributes["primary_coordinator"] == AGENT_EXECUTIVE
        assert len(orch_state.attributes["active_agents"]) == 5

        # Satellites sensor
        sat_state = mock_hass.states.get("sensor.otis_voice_satellites")
        assert sat_state is not None
        assert "Satellites" in sat_state.state
        assert sat_state.attributes["arbitration_mode"] == "presence_fused"

    @pytest.mark.asyncio
    async def test_conversational_assist_multi_agent_status(self, mock_hass, orchestrator):
        """Test Assist conversation intent for multi-agent orchestrator status."""
        from custom_components.otis_ai import OtisAIConversationAgent

        entry = MagicMock()
        entry.entry_id = "test_entry"
        entry.data = {}
        entry.options = {}

        # Set up a satellite
        mock_hass.states.async_set(
            "assist_satellite.study",
            "idle",
            {"friendly_name": "Study Voice Satellite", "area_id": "study"},
        )
        await orchestrator.async_configure_satellite(
            satellite_id="assist_satellite.study",
            area_id="study",
            assigned_agent=AGENT_EXECUTIVE,
            wake_word="Hey Otis",
        )

        agent = OtisAIConversationAgent(
            mock_hass,
            entry,
            engine=MagicMock(),
            automation_manager=MagicMock(),
            agent_orchestrator=orchestrator,
        )

        user_input = MagicMock()
        user_input.text = "What is the multi-agent status?"
        user_input.conversation_id = "conv_orch_1"
        user_input.create_response = MagicMock(return_value=MagicMock(conversation_id="conv_orch_1"))

        result = await agent.async_process(user_input)
        assert result.conversation_id == "conv_orch_1"
        user_input.create_response.assert_called_once()
        speech = user_input.create_response.call_args[1]["speech"]
        assert "Otis Multi-Agent Orchestration & Voice Satellites" in speech
        assert "Active Specialists" in speech
        assert "Executive Butler" in speech
        assert "Sentinel Security" in speech
        assert "Configured Voice Satellites" in speech

    @pytest.mark.asyncio
    async def test_local_llm_specialist_integration(self, mock_hass, mock_sentinel):
        """Verify specialist delegation calls local LLM when available."""
        mock_llm = MagicMock()
        mock_llm.model = "llama3:8b"
        mock_llm.async_generate = AsyncMock(return_value={
            "success": True,
            "response": "Sentinel: Front deadbolt secured. Perimeter integrity verified.",
        })

        orch = MultiAgentOrchestrator(
            hass=mock_hass,
            local_llm_manager=mock_llm,
            sentinel_manager=mock_sentinel,
        )
        orch._store = MagicMock()
        orch._store.async_load = AsyncMock(return_value=None)
        orch._store.async_save = AsyncMock()

        res = await orch.async_orchestrate(
            prompt="Is the front door secured?",
            requested_agents=[AGENT_SENTINEL],
            mode="single",
        )
        assert res["success"] is True
        assert res["agent_responses"][AGENT_SENTINEL]["response"] == "Sentinel: Front deadbolt secured. Perimeter integrity verified."
        mock_llm.async_generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_satellite_persistence_load(self, mock_hass):
        """Verify stored satellite configs are restored on load."""
        stored_data = {
            "satellites": {
                "assist_satellite.workshop": {
                    "area_id": "workshop",
                    "assigned_agent": AGENT_AUTOMATOR,
                    "wake_word": "Jarvis",
                    "wake_word_engine": "wyoming",
                    "preferred_speaker": "media_player.workshop_amp",
                }
            }
        }
        orch = MultiAgentOrchestrator(hass=mock_hass)
        orch._store = MagicMock()
        orch._store.async_load = AsyncMock(return_value=stored_data)
        orch._store.async_save = AsyncMock()

        await orch.async_load()
        sats = orch.get_discovered_satellites()
        assert len(sats) == 1
        assert sats[0]["entity_id"] == "assist_satellite.workshop"
        assert sats[0]["wake_word"] == "Jarvis"
        assert sats[0]["assigned_agent"] == AGENT_AUTOMATOR

