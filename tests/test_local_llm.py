"""Tests for Otis AI Companion Local LLM Manager and Edge Inference."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.otis_ai.local_llm import (
    DEFAULT_LOCAL_LLM_MODEL,
    DEFAULT_LOCAL_LLM_URL,
    LocalLLMManager,
    select_relevant_tools,
)
from custom_components.otis_ai.sentinel_manager import SentinelManager


def test_local_llm_manager_init():
    """Test LocalLLMManager initialization with defaults."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass)
    assert mgr.url == DEFAULT_LOCAL_LLM_URL
    assert mgr.model == DEFAULT_LOCAL_LLM_MODEL
    assert mgr.api_key is None


def test_health_check_ollama_online():
    """Test health check when Ollama native endpoint /api/tags succeeds."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass, url="http://10.0.12.228:11434", model="qwen2.5:1.5b")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "models": [{"name": "qwen2.5:1.5b"}, {"name": "llama3.2:3b"}]
    })

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("custom_components.otis_ai.local_llm.async_get_clientsession", return_value=mock_session):
        res = asyncio.run(mgr.async_health_check())
        assert res["status"] == "online"
        assert res["provider"] == "ollama"
        assert res["model_ready"] is True
        assert "qwen2.5:1.5b" in res["models"]
        assert res["latency_ms"] >= 0.0


def test_health_check_ollama_autodetect_installed_model():
    """Test health check auto-detects and adopts installed model when configured model is absent."""
    hass = MagicMock()
    # Configure with default qwen2.5:3b, but server only has qwen2.5:1.5b
    mgr = LocalLLMManager(hass, url="http://10.0.12.228:11434", model="qwen2.5:3b")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "models": [{"name": "qwen2.5:1.5b"}]
    })

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("custom_components.otis_ai.local_llm.async_get_clientsession", return_value=mock_session):
        res = asyncio.run(mgr.async_health_check())
        assert res["status"] == "online"
        assert res["provider"] == "ollama"
        assert res["model_ready"] is True
        assert res["active_model"] == "qwen2.5:1.5b"
        assert mgr.model == "qwen2.5:1.5b"


def test_health_check_openai_compatible_online():
    """Test health check when Ollama fails but /v1/models succeeds (e.g. vLLM / LocalAI)."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass, url="http://10.0.12.228:8000", model="qwen2.5:1.5b")

    mock_resp_v1 = AsyncMock()
    mock_resp_v1.status = 200
    mock_resp_v1.json = AsyncMock(return_value={
        "data": [{"id": "qwen2.5:1.5b"}]
    })

    # First call (/api/tags) raises, second call (/v1/models) succeeds
    mock_session = MagicMock()
    mock_session.get.side_effect = [
        Exception("Connection refused"),
        AsyncMock(__aenter__=AsyncMock(return_value=mock_resp_v1), __aexit__=AsyncMock(return_value=None)),
    ]

    with patch("custom_components.otis_ai.local_llm.async_get_clientsession", return_value=mock_session):
        res = asyncio.run(mgr.async_health_check())
        assert res["status"] == "online"
        assert res["provider"] == "openai_compatible"
        assert res["model_ready"] is True


def test_health_check_offline():
    """Test health check when server is offline."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass, url="http://10.0.12.999:11434")

    mock_session = MagicMock()
    mock_session.get.side_effect = Exception("Host unreachable")

    with patch("custom_components.otis_ai.local_llm.async_get_clientsession", return_value=mock_session):
        res = asyncio.run(mgr.async_health_check())
        assert res["status"] == "offline"
        assert res["provider"] == "unreachable"
        assert res["model_ready"] is False
        assert "unreachable" in res["error"].lower()


def test_generate_ollama_success():
    """Test text generation via Ollama /api/chat."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass, model="qwen2.5:1.5b")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "message": {"content": "Turn on bathroom ventilation fan to reduce humidity."},
        "eval_count": 45,
        "prompt_eval_count": 20,
        "eval_duration": 1500000000,  # 1.5s in ns -> 30 tokens/sec
    })

    mock_session = MagicMock()
    mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.post.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("custom_components.otis_ai.local_llm.async_get_clientsession", return_value=mock_session):
        res = asyncio.run(mgr.async_generate(prompt="Test humidity prompt"))
        assert res["success"] is True
        assert "ventilation fan" in res["response"]
        assert res["tokens_generated"] == 45
        assert res["tokens_per_sec"] == 30.0
        assert res["provider"] == "ollama"


def test_generate_openai_compatible_fallback():
    """Test text generation falling back to OpenAI format when Ollama chat fails."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass, model="qwen2.5:1.5b")

    mock_resp_v1 = AsyncMock()
    mock_resp_v1.status = 200
    mock_resp_v1.json = AsyncMock(return_value={
        "choices": [{"message": {"content": "OpenAI format response"}}],
        "usage": {"completion_tokens": 10, "prompt_tokens": 5},
    })

    mock_session = MagicMock()
    mock_session.post.side_effect = [
        Exception("Ollama endpoint 404"),
        AsyncMock(__aenter__=AsyncMock(return_value=mock_resp_v1), __aexit__=AsyncMock(return_value=None)),
    ]

    with patch("custom_components.otis_ai.local_llm.async_get_clientsession", return_value=mock_session):
        res = asyncio.run(mgr.async_generate(prompt="Test fallback"))
        assert res["success"] is True
        assert res["response"] == "OpenAI format response"
        assert res["provider"] == "openai_compatible"


def test_benchmark_execution():
    """Test benchmark execution aggregating health and throughput."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass, model="qwen2.5:1.5b")

    mgr.async_generate = AsyncMock(return_value={
        "success": True,
        "response": "Benchmark passed: adjust setpoint.",
        "model": "qwen2.5:1.5b",
        "tokens_generated": 25,
        "tokens_per_sec": 35.5,
        "total_duration_s": 0.7,
        "provider": "ollama",
    })
    mgr.async_health_check = AsyncMock(return_value={
        "status": "online",
        "provider": "ollama",
        "latency_ms": 2.5,
    })

    res = asyncio.run(mgr.async_benchmark())
    assert res["success"] is True
    assert res["tokens_per_second"] == 35.5
    assert res["tokens_generated"] == 25
    assert res["endpoint_health"]["status"] == "online"


def test_sentinel_anomaly_diagnosis_local_llm():
    """Test Sentinel watchdog using Local LLM for root-cause diagnosis."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass, model="qwen2.5:1.5b")
    mgr.async_generate = AsyncMock(return_value={
        "success": True,
        "response": "Root Cause: High humidity in Bathroom. Immediate Action: Turn on exhaust fan.",
        "model": "qwen2.5:1.5b",
        "tokens_per_sec": 40.0,
        "total_duration_s": 0.5,
    })

    sentinel = SentinelManager(hass, local_llm_manager=mgr)
    sentinel._anomalies = {
        "bathroom_humidity": {
            "title": "Elevated Humidity",
            "description": "Humidity at 85%",
            "severity": "high",
            "category": "climate",
            "details": {"humidity": 85},
        }
    }

    diag = asyncio.run(sentinel.async_diagnose_anomaly("bathroom_humidity"))
    assert diag["success"] is True
    assert "Root Cause" in diag["diagnosis"]
    assert diag["model"] == "qwen2.5:1.5b"
    assert diag["tokens_per_sec"] == 40.0


def test_pull_local_llm_model_success():
    """Test pulling an edge model via Ollama /api/pull."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass, url="http://10.0.12.228:11434")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"status": "success"})

    mock_session = MagicMock()
    mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_session.post.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("custom_components.otis_ai.local_llm.async_get_clientsession", return_value=mock_session), \
         patch.object(mgr, "async_health_check", return_value={"status": "online"}):
        res = asyncio.run(mgr.async_pull_model("qwen2.5:3b"))
        assert res["success"] is True
        assert res["model"] == "qwen2.5:3b"
        assert res["status"] == "success"


def test_list_local_llm_models():
    """Test listing installed models from health check."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass)

    with patch.object(mgr, "async_health_check", return_value={"status": "online", "models": ["qwen2.5:3b", "qwen2.5:1.5b"]}):
        models = asyncio.run(mgr.async_list_models())
        assert "qwen2.5:3b" in models
        assert "qwen2.5:1.5b" in models


def test_benchmark_custom_model():
    """Test running benchmark targeting a specific local edge model."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass, model="qwen2.5:1.5b")
    mgr.async_generate = AsyncMock(return_value={
        "success": True,
        "response": "Adjust temperature to 71F and dim lights.",
        "model": "qwen2.5:3b",
        "tokens_per_sec": 18.5,
        "tokens_generated": 15,
    })
    mgr.async_health_check = AsyncMock(return_value={"status": "online", "provider": "ollama"})

    res = asyncio.run(mgr.async_benchmark(model="qwen2.5:3b"))
    assert res["success"] is True
    assert res["model"] == "qwen2.5:3b"
    assert res["tokens_per_second"] == 18.5
    mgr.async_generate.assert_called_once()
    assert mgr.async_generate.call_args[1]["model"] == "qwen2.5:3b"


def test_default_otis_tools_schema():
    """Test standard Otis AI JSON schema tool definitions."""
    from custom_components.otis_ai.local_llm import DEFAULT_OTIS_TOOLS

    assert len(DEFAULT_OTIS_TOOLS) >= 9
    tool_names = [t["function"]["name"] for t in DEFAULT_OTIS_TOOLS]
    assert "pin_floorplan_entity" in tool_names
    assert "unpin_floorplan_entity" in tool_names
    assert "run_sentinel_watchdog" in tool_names
    assert "turn_off_stuck_actuator" in tool_names
    assert "restart_ble_proxy" in tool_names
    assert "heal_mesh_node" in tool_names
    assert "regenerate_dashboards" in tool_names
    assert "analyze_camera" in tool_names
    assert "call_ha_service" in tool_names
    assert "query_knowledge_base" in tool_names
    assert "optimize_battery_schedule" in tool_names
    assert "get_energy_arbitrage_plan" in tool_names

    # Check pin_floorplan_entity parameters
    pin_tool = next(t for t in DEFAULT_OTIS_TOOLS if t["function"]["name"] == "pin_floorplan_entity")
    assert "entity_id" in pin_tool["function"]["parameters"]["properties"]
    assert "view_mode" in pin_tool["function"]["parameters"]["properties"]
    assert "room" in pin_tool["function"]["parameters"]["properties"]


def test_extract_tool_calls_native_ollama_and_openai():
    """Test extracting tool calls from native Ollama and OpenAI response structures."""
    from custom_components.otis_ai.local_llm import extract_tool_calls

    # Native Ollama structure with dict arguments
    ollama_raw = [
        {
            "function": {
                "name": "pin_floorplan_entity",
                "arguments": {"entity_id": "light.kitchen_pendant", "room": "kitchen", "view_mode": "3d"},
            }
        }
    ]
    calls = extract_tool_calls("", ollama_raw)
    assert len(calls) == 1
    assert calls[0]["name"] == "pin_floorplan_entity"
    assert calls[0]["parameters"]["entity_id"] == "light.kitchen_pendant"
    assert calls[0]["parameters"]["view_mode"] == "3d"

    # Native OpenAI structure with stringified JSON arguments
    openai_raw = [
        {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "run_sentinel_watchdog",
                "arguments": '{"auto_remediate": true}',
            },
        }
    ]
    calls2 = extract_tool_calls("", openai_raw)
    assert len(calls2) == 1
    assert calls2[0]["name"] == "run_sentinel_watchdog"
    assert calls2[0]["parameters"]["auto_remediate"] is True


def test_extract_tool_calls_fallback_formats():
    """Test fallback extraction from markdown JSON code blocks, XML tags, and inline syntax."""
    from custom_components.otis_ai.local_llm import extract_tool_calls

    # Format 1: XML <tool_call> tag
    xml_text = (
        "I'll heal that mesh node for you.\n"
        "<tool_call>{\"name\": \"heal_mesh_node\", \"arguments\": {\"entity_id\": \"switch.patio_plug\"}}</tool_call>"
    )
    calls1 = extract_tool_calls(xml_text)
    assert len(calls1) == 1
    assert calls1[0]["name"] == "heal_mesh_node"
    assert calls1[0]["parameters"]["entity_id"] == "switch.patio_plug"

    # Format 2: Markdown ```json code block
    md_text = (
        "Here is the plan:\n"
        "```json\n"
        "[\n"
        "  {\"tool\": \"turn_off_stuck_actuator\", \"parameters\": {\"entity_id\": \"switch.heater\"}},\n"
        "  {\"tool\": \"regenerate_dashboards\", \"parameters\": {\"layout_type\": \"sections\"}}\n"
        "]\n"
        "```"
    )
    calls2 = extract_tool_calls(md_text)
    assert len(calls2) == 2
    assert calls2[0]["name"] == "turn_off_stuck_actuator"
    assert calls2[0]["parameters"]["entity_id"] == "switch.heater"
    assert calls2[1]["name"] == "regenerate_dashboards"
    assert calls2[1]["parameters"]["layout_type"] == "sections"

    # Format 3: Inline syntax
    inline_text = "Executing: [TOOL_CALL: restart_ble_proxy({\"device_id\": \"esp32_hallway\"})]"
    calls3 = extract_tool_calls(inline_text)
    assert len(calls3) == 1
    assert calls3[0]["name"] == "restart_ble_proxy"
    assert calls3[0]["parameters"]["device_id"] == "esp32_hallway"


def test_validate_tool_call():
    """Test validation of tool call structures."""
    from custom_components.otis_ai.local_llm import validate_tool_call

    valid, err = validate_tool_call({"name": "pin_floorplan_entity", "parameters": {"entity_id": "light.lamp"}})
    assert valid is True
    assert err is None

    # Missing name
    valid, err = validate_tool_call({"parameters": {}})
    assert valid is False

    # Disallowed tool
    valid, err = validate_tool_call(
        {"name": "malicious_tool", "parameters": {}},
        allowed_tools=["pin_floorplan_entity", "run_sentinel_watchdog"],
    )
    assert valid is False
    assert "not in allowed tools list" in err


def test_async_execute_tool_plan():
    """Test executing a multi-step structured tool plan against Home Assistant services."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()

    mgr = LocalLLMManager(hass)
    mock_rag = MagicMock()
    mock_rag.async_query_knowledge = AsyncMock(return_value=[{"title": "Dimmer Manual", "content": "Reset instructions"}])
    mgr.rag_manager = mock_rag

    plan = [
        {"name": "pin_floorplan_entity", "parameters": {"entity_id": "light.office_desk", "room": "office"}},
        {"name": "turn_off_stuck_actuator", "parameters": {"entity_id": "switch.sump_pump"}},
        {"name": "light.turn_on", "parameters": {"entity_id": "light.living_room", "brightness": 128}},
        {
            "name": "call_ha_service",
            "parameters": {"domain": "climate", "service": "set_temperature", "service_data": {"temperature": 70}},
        },
        {"name": "query_knowledge_base", "parameters": {"query": "How to reset dimmer?"}},
    ]

    results = asyncio.run(mgr.async_execute_tool_plan(plan))
    assert len(results) == 5
    assert all(r["success"] is True for r in results)
    assert results[4]["result"][0]["title"] == "Dimmer Manual"
    mock_rag.async_query_knowledge.assert_called_once()

    # Check that Home Assistant services were called
    calls = hass.services.async_call.call_args_list
    assert len(calls) == 4

    # 1. otis_ai.pin_floorplan_entity
    assert calls[0][0][0] == "otis_ai"
    assert calls[0][0][1] == "pin_floorplan_entity"
    assert calls[0][0][2]["entity_id"] == "light.office_desk"

    # 2. otis_ai.turn_off_stuck_actuator
    assert calls[1][0][0] == "otis_ai"
    assert calls[1][0][1] == "turn_off_stuck_actuator"

    # 3. light.turn_on
    assert calls[2][0][0] == "light"
    assert calls[2][0][1] == "turn_on"

    # 4. climate.set_temperature
    assert calls[3][0][0] == "climate"
    assert calls[3][0][1] == "set_temperature"


def test_async_chat_with_tools_multi_turn():
    """Test autonomous multi-turn tool calling loop with local LLM."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    mgr = LocalLLMManager(hass, model="qwen2.5:3b")

    # Turn 1: Model requests a tool call to run_sentinel_watchdog
    # Turn 2: After receiving observation, model provides final textual response
    mgr.async_generate = AsyncMock()
    mgr.async_generate.side_effect = [
        {
            "success": True,
            "response": "I will run the sentinel watchdog to check for anomalies.",
            "tool_calls": [{"name": "run_sentinel_watchdog", "parameters": {"auto_remediate": True}}],
            "raw_tool_calls": [],
            "tokens_generated": 20,
            "model": "qwen2.5:3b",
            "provider": "ollama",
        },
        {
            "success": True,
            "response": "Sentinel watchdog completed. All network nodes and actuators are normal.",
            "tool_calls": [],
            "raw_tool_calls": [],
            "tokens_generated": 18,
            "model": "qwen2.5:3b",
            "provider": "ollama",
        },
    ]

    chat_res = asyncio.run(mgr.async_chat_with_tools(
        prompt="Audit system health and heal anything stuck.",
        max_iterations=3,
        auto_execute=True,
    ))

    assert chat_res["success"] is True
    assert chat_res["iterations"] == 2
    assert len(chat_res["executed_tools"]) == 1
    assert chat_res["executed_tools"][0]["tool"] == "run_sentinel_watchdog"
    assert "Sentinel watchdog completed" in chat_res["response"]
    assert hass.services.async_call.called


def test_select_relevant_tools_filtering():
    """Test that informational queries skip tool schema bloat while action queries select targeted tools."""
    assert select_relevant_tools("What is the current status of Home Assistant Core?") == []
    assert (
        select_relevant_tools(
            "How do I 🎯 Vision False-Positive Filter Calibrated (Great Room)? Give me step-by-step guidance."
        )
        == []
    )
    pin_tools = select_relevant_tools("Pin light.chandelier to dining room on the floorplan")
    assert len(pin_tools) == 1
    assert pin_tools[0]["function"]["name"] == "pin_floorplan_entity"

    svc_tools = select_relevant_tools("Turn on the study lights")
    assert any(t["function"]["name"] == "call_ha_service" for t in svc_tools)


def test_generate_timeout_does_not_duplicate_request():
    """Test that a timeout on Ollama /api/chat does not fire a second duplicate /v1/chat/completions call."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass, model="qwen2.5:3b")

    mock_session = MagicMock()
    mock_session.post.side_effect = asyncio.TimeoutError("Request timed out")

    with patch("custom_components.otis_ai.local_llm.async_get_clientsession", return_value=mock_session):
        res = asyncio.run(mgr.async_generate(prompt="Test timeout", timeout=10.0))
        assert res["success"] is False
        assert "timed out" in res["error"].lower()
        assert mock_session.post.call_count == 1


def test_assess_host_ollama_suitability_recommended():
    """Test hardware suitability verification confirms capable & recommended HA server."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(
        return_value={
            "cpu_model": "12th Gen Intel(R) Core(TM) i7-12650H",
            "cpu_cores": 16,
            "ram_total_gb": 15.6,
            "ram_avail_gb": 7.2,
            "disk_free_gb": 1400.0,
            "gpu_detected": True,
            "gpu_devices": ["card0", "renderD128"],
        }
    )
    hass.config.components = {"hassio"}
    mgr = LocalLLMManager(hass, model="qwen2.5:3b")

    with patch.object(mgr, "async_health_check", AsyncMock(return_value={"status": "offline"})):
        suit = asyncio.run(mgr.async_assess_host_ollama_suitability())
        assert suit["can_run"] is True
        assert suit["recommended"] is True
        assert suit["supervisor_available"] is True
        assert suit["cpu_cores"] == 16
        assert suit["gpu_detected"] is True
        assert suit["recommended_model"] == "qwen2.5:3b"


def test_assess_host_ollama_suitability_insufficient_hardware():
    """Test hardware suitability verification rejects low-RAM / low-CPU systems."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(
        return_value={
            "cpu_model": "ARM Cortex-A53",
            "cpu_cores": 2,
            "ram_total_gb": 2.0,
            "ram_avail_gb": 0.8,
            "disk_free_gb": 3.5,
            "gpu_detected": False,
            "gpu_devices": [],
        }
    )
    mgr = LocalLLMManager(hass, model="qwen2.5:3b")

    with patch.dict("os.environ", {}, clear=False):
        suit = asyncio.run(mgr.async_assess_host_ollama_suitability())
        assert suit["can_run"] is False
        assert suit["recommended"] is False
        assert len(suit["blockers"]) >= 2


def test_manage_ollama_addon_set_model():
    """Test manage_ollama_addon set_model updates active model and returns status."""
    hass = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[])
    mgr = LocalLLMManager(hass, model="qwen2.5:1.5b")
    mgr.async_get_ollama_status = AsyncMock(
        return_value={"online": True, "active_model": "qwen2.5:3b"}
    )

    res = asyncio.run(mgr.async_manage_ollama_addon(action="set_model", model="qwen2.5:3b"))
    assert res["success"] is True
    assert mgr.model == "qwen2.5:3b"
    assert res["status"]["active_model"] == "qwen2.5:3b"


def test_ollama_status_caching():
    """Test that async_get_ollama_status caches results within TTL."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass, model="qwen2.5:3b")
    mgr.async_assess_host_ollama_suitability = AsyncMock(
        return_value={"can_run": True, "recommended": True}
    )
    mgr.async_health_check = AsyncMock(
        return_value={"status": "online", "provider": "ollama", "models": ["qwen2.5:3b"]}
    )
    mgr.async_get_running_models = AsyncMock(return_value=[])

    st1 = asyncio.run(mgr.async_get_ollama_status())
    assert st1["online"] is True
    assert mgr.async_health_check.call_count == 1

    # Second call within TTL should return cached status
    st2 = asyncio.run(mgr.async_get_ollama_status())
    assert st2["online"] is True
    assert mgr.async_health_check.call_count == 1

    # Force refresh bypasses cache
    st3 = asyncio.run(mgr.async_get_ollama_status(force_refresh=True))
    assert st3["online"] is True
    assert mgr.async_health_check.call_count == 2


def test_local_llm_max_tokens_budgeting():
    """Test that max_tokens defaults to 2048 and passes to Ollama payload."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass, max_tokens=3072)
    assert mgr.max_tokens == 3072

    captured_payload = {}
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"message": {"content": "ok"}})

    mock_session = MagicMock()
    class MockContextManager:
        async def __aenter__(self):
            return mock_resp
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_post(url, json=None, **kwargs):
        captured_payload.update(json or {})
        return MockContextManager()

    mock_session.post = mock_post
    with patch("custom_components.otis_ai.local_llm.async_get_clientsession", return_value=mock_session):
        res = asyncio.run(mgr.async_generate(prompt="hello"))
        assert res["success"] is True
        assert captured_payload["options"]["num_predict"] == 3072


def test_inspect_backup_configuration_tool():
    """Test inspect_backup_configuration tool selection and execution."""
    from custom_components.otis_ai.local_llm import select_relevant_tools, LocalLLMManager
    from unittest.mock import AsyncMock, MagicMock

    tools = select_relevant_tools("Notify Router was overwritten! Find the latest backup and restore it.")
    assert any(t["function"]["name"] == "inspect_backup_configuration" for t in tools)

    hass = MagicMock()
    mgr = LocalLLMManager(hass)
    mock_auto_mgr = MagicMock()
    mock_auto_mgr.async_inspect_backups_for_item = AsyncMock(return_value={
        "found": True,
        "best_candidate": {"name": "Notify Router", "lines": 726},
    })
    mgr.automation_manager = mock_auto_mgr

    plan = [{
        "name": "inspect_backup_configuration",
        "parameters": {"item_name": "notify_router", "item_type": "script"},
    }]
    results = asyncio.run(mgr.async_execute_tool_plan(plan))
    assert len(results) == 1
    assert results[0]["success"] is True
    assert results[0]["result"]["found"] is True
    assert results[0]["result"]["best_candidate"]["lines"] == 726


def test_select_relevant_tools_extracts_user_request_from_compact_prompt():
    """Ensure system instructions mentioning backup/floorplan/sentinel do not trigger tools."""
    compact_prompt = (
        "You are Otis AI, the smart home co-pilot.\n"
        "Never tell the user to manually download, extract, or edit backups or YAML files.\n"
        "System State:\n"
        "- Notable Integrations: ['sentinel', 'floorplan', 'camera', 'battery']\n"
        "\nUser Request: What is the temperature in the study?"
    )
    assert select_relevant_tools(compact_prompt) == []

    action_prompt = (
        "You are Otis AI.\n"
        "Never tell the user to manually extract backups.\n"
        "\nUser Request: Turn on the study lights"
    )
    tools = select_relevant_tools(action_prompt)
    assert [t["function"]["name"] for t in tools] == ["call_ha_service"]


def test_async_generate_empty_response_returns_error():
    """HTTP 200 with empty content and no tool calls should fail with a clear error."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass, url="http://127.0.0.1:11434", model="qwen2.5:3b")
    mgr._detected_provider = "ollama"

    fake_resp = AsyncMock()
    fake_resp.status = 200
    fake_resp.json = AsyncMock(return_value={
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "done_reason": "length",
        "eval_count": 512,
        "prompt_eval_count": 4593,
    })

    fake_ctx = AsyncMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_resp)
    fake_ctx.__aexit__ = AsyncMock(return_value=False)

    fake_session = MagicMock()
    fake_session.post = MagicMock(return_value=fake_ctx)

    with patch("custom_components.otis_ai.local_llm.async_get_clientsession", return_value=fake_session):
        res = asyncio.run(mgr.async_generate(prompt="hello"))

    assert res["success"] is False
    assert "empty response" in res["error"].lower()
    assert "done_reason=length" in res["error"]
    assert "eval_count=512" in res["error"]








