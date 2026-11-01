"""Tests for Otis AI Companion Local LLM Manager and Edge Inference."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.otis_ai.local_llm import (
    DEFAULT_LOCAL_LLM_MODEL,
    DEFAULT_LOCAL_LLM_URL,
    LocalLLMManager,
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
