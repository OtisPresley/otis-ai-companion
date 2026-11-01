"""Otis AI Companion: Local LLM & Edge Inference Connector.

Provides zero-cloud, privacy-first local LLM integration for Assist Co-Pilot
and Sentinel anomaly auditing with benchmark telemetry and transparent cloud failover.
Compatible with Ollama, vLLM, LocalAI, and OpenAI-compatible inference servers.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from aiohttp import ClientSession, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

DEFAULT_LOCAL_LLM_URL = "http://10.0.12.228:11434"
DEFAULT_LOCAL_LLM_MODEL = "qwen2.5:3b"
DEFAULT_TIMEOUT_SECONDS = 60.0


class LocalLLMManager:
    """Manages local LLM communication, health monitoring, benchmarking, and inference."""

    def __init__(
        self,
        hass: HomeAssistant,
        url: str = DEFAULT_LOCAL_LLM_URL,
        model: str = DEFAULT_LOCAL_LLM_MODEL,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Initialize the Local LLM Manager."""
        self.hass = hass
        self.url = (url or DEFAULT_LOCAL_LLM_URL).rstrip("/")
        self.model = model or DEFAULT_LOCAL_LLM_MODEL
        self.api_key = api_key
        self.timeout = timeout
        self._last_health: dict[str, Any] = {"status": "unknown"}

    def _get_headers(self) -> dict[str, str]:
        """Build request headers."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get_session(self) -> ClientSession:
        """Retrieve the Home Assistant aiohttp ClientSession."""
        if self.hass is not None:
            return async_get_clientsession(self.hass)
        return ClientSession()

    async def async_health_check(self, target_url: str | None = None) -> dict[str, Any]:
        """Perform a low-overhead health check and discover active models."""
        base_url = (target_url or self.url).rstrip("/")
        session = self._get_session()
        headers = self._get_headers()
        t0 = time.perf_counter()

        # 1. Attempt Ollama-native endpoint /api/tags
        try:
            ollama_url = f"{base_url}/api/tags"
            async with session.get(ollama_url, headers=headers, timeout=ClientTimeout(total=4.0)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
                    models = [m.get("name") for m in data.get("models", []) if isinstance(m, dict)]
                    matching = [m for m in models if self.model == m or (self.model and self.model in m)]
                    if matching:
                        active_model = matching[0]
                        model_ready = True
                    elif models:
                        active_model = models[0]
                        _LOGGER.info(
                            "Configured local LLM model '%s' not present on %s; auto-detected and selected installed model: '%s'",
                            self.model, base_url, active_model
                        )
                        self.model = active_model
                        model_ready = True
                    else:
                        active_model = self.model
                        model_ready = False

                    result = {
                        "status": "online",
                        "provider": "ollama",
                        "latency_ms": latency_ms,
                        "url": base_url,
                        "models": models,
                        "active_model": active_model,
                        "model_ready": model_ready,
                    }
                    self._last_health = result
                    return result
        except Exception as err:
            _LOGGER.debug("Ollama /api/tags check failed at %s: %s", base_url, err)

        # 2. Attempt OpenAI-compatible /v1/models (vLLM / LocalAI / LM Studio)
        try:
            t0 = time.perf_counter()
            v1_url = f"{base_url}/v1/models"
            async with session.get(v1_url, headers=headers, timeout=ClientTimeout(total=4.0)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
                    models = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
                    matching = [m for m in models if self.model == m or (self.model and self.model in m)]
                    if matching:
                        active_model = matching[0]
                        model_ready = True
                    elif models:
                        active_model = models[0]
                        _LOGGER.info(
                            "Configured local LLM model '%s' not present on %s; auto-detected and selected installed model: '%s'",
                            self.model, base_url, active_model
                        )
                        self.model = active_model
                        model_ready = True
                    else:
                        active_model = self.model
                        model_ready = False

                    result = {
                        "status": "online",
                        "provider": "openai_compatible",
                        "latency_ms": latency_ms,
                        "url": base_url,
                        "models": models,
                        "active_model": active_model,
                        "model_ready": model_ready,
                    }
                    self._last_health = result
                    return result
        except Exception as err:
            _LOGGER.debug("OpenAI /v1/models check failed at %s: %s", base_url, err)

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        result = {
            "status": "offline",
            "provider": "unreachable",
            "latency_ms": latency_ms,
            "url": base_url,
            "models": [],
            "active_model": self.model,
            "model_ready": False,
            "error": "Server unreachable or connection timed out",
        }
        self._last_health = result
        return result

    async def async_generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """Send a prompt to the local LLM and return structured output and metrics."""
        chosen_model = model or self.model
        session = self._get_session()
        headers = self._get_headers()
        t0 = time.perf_counter()

        # Try Ollama /api/chat or /api/generate
        ollama_endpoint = f"{self.url}/api/chat"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": chosen_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            async with session.post(
                ollama_endpoint,
                json=payload,
                headers=headers,
                timeout=ClientTimeout(total=self.timeout),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    total_time = max(0.001, time.perf_counter() - t0)
                    msg = data.get("message", {}).get("content", "")
                    eval_count = data.get("eval_count", 0)
                    prompt_eval_count = data.get("prompt_eval_count", 0)
                    eval_duration = data.get("eval_duration", 0) / 1e9  # nanoseconds to seconds
                    tokens_per_sec = (
                        round(eval_count / eval_duration, 1) if eval_duration > 0 else round(eval_count / total_time, 1)
                    )

                    return {
                        "success": True,
                        "response": msg,
                        "model": chosen_model,
                        "tokens_generated": eval_count,
                        "tokens_evaluated": prompt_eval_count,
                        "tokens_per_sec": tokens_per_sec,
                        "total_duration_s": round(total_time, 2),
                        "provider": "ollama",
                    }
        except Exception as err:
            _LOGGER.debug("Ollama /api/chat attempt failed: %s; trying OpenAI format", err)

        # Fallback to OpenAI-compatible /v1/chat/completions
        try:
            v1_endpoint = f"{self.url}/v1/chat/completions"
            v1_payload = {
                "model": chosen_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }
            async with session.post(
                v1_endpoint,
                json=v1_payload,
                headers=headers,
                timeout=ClientTimeout(total=self.timeout),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    total_time = max(0.001, time.perf_counter() - t0)
                    choices = data.get("choices", [])
                    content = choices[0].get("message", {}).get("content", "") if choices else ""
                    usage = data.get("usage", {})
                    completion_tokens = usage.get("completion_tokens", len(content.split()) * 1.3)
                    tokens_per_sec = round(completion_tokens / total_time, 1)

                    return {
                        "success": True,
                        "response": content,
                        "model": chosen_model,
                        "tokens_generated": int(completion_tokens),
                        "tokens_evaluated": usage.get("prompt_tokens", 0),
                        "tokens_per_sec": tokens_per_sec,
                        "total_duration_s": round(total_time, 2),
                        "provider": "openai_compatible",
                    }
                err_text = await resp.text()
                return {
                    "success": False,
                    "error": f"HTTP {resp.status}: {err_text[:200]}",
                    "model": chosen_model,
                    "total_duration_s": round(time.perf_counter() - t0, 2),
                }
        except Exception as err:
            return {
                "success": False,
                "error": str(err),
                "model": chosen_model,
                "total_duration_s": round(time.perf_counter() - t0, 2),
            }

    async def async_benchmark(self, prompt: str | None = None) -> dict[str, Any]:
        """Run a standardized smart home reasoning benchmark against the local LLM."""
        test_prompt = prompt or (
            "You are Otis AI, a smart home co-pilot. "
            "Living Room: Motion detected, ambient light is 15 lux, temperature is 74F, target is 71F. "
            "Output a 2-sentence actionable recommendation."
        )
        t0 = time.perf_counter()
        result = await self.async_generate(
            prompt=test_prompt,
            system_prompt="You are a smart home automation expert. Be concise and actionable.",
            max_tokens=150,
        )
        total_time = round(time.perf_counter() - t0, 2)
        health = await self.async_health_check()

        return {
            "success": result.get("success", False),
            "model": result.get("model", self.model),
            "provider": result.get("provider", health.get("provider")),
            "tokens_per_second": result.get("tokens_per_sec", 0.0),
            "tokens_generated": result.get("tokens_generated", 0),
            "total_latency_seconds": total_time,
            "endpoint_health": health,
            "sample_output": result.get("response", result.get("error", "")),
        }

