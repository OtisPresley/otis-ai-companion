"""Otis AI Companion: Local LLM & Edge Inference Connector.

Provides zero-cloud, privacy-first local LLM integration for Assist Co-Pilot
and Sentinel anomaly auditing with benchmark telemetry and transparent cloud failover.
Compatible with Ollama, vLLM, LocalAI, and OpenAI-compatible inference servers.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from aiohttp import ClientSession, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

DEFAULT_LOCAL_LLM_URL = "http://10.0.12.228:11434"
DEFAULT_LOCAL_LLM_MODEL = "qwen2.5:3b"
DEFAULT_TIMEOUT_SECONDS = 60.0

DEFAULT_OTIS_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "pin_floorplan_entity",
            "description": "Pin or update an entity badge on the 2D or 3D floorplan in a specified room or at explicit coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Home Assistant entity ID to pin (e.g., 'light.living_room_ceiling').",
                    },
                    "room": {
                        "type": "string",
                        "description": "Target room or area name (e.g., 'living_room', 'gym', 'kitchen').",
                    },
                    "view_mode": {
                        "type": "string",
                        "enum": ["2d", "3d"],
                        "description": "Target floorplan view layer: '2d' (orthogonal blueprint) or '3d' (isometric).",
                    },
                    "x": {
                        "type": "number",
                        "description": "Optional explicit X coordinate.",
                    },
                    "y": {
                        "type": "number",
                        "description": "Optional explicit Y coordinate.",
                    },
                },
                "required": ["entity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unpin_floorplan_entity",
            "description": "Remove an entity badge from the interactive floorplan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Home Assistant entity ID to unpin.",
                    },
                },
                "required": ["entity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_sentinel_watchdog",
            "description": "Audit Home Assistant for stuck actuators, offline BLE proxies, mesh anomalies, and failing batteries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "auto_remediate": {
                        "type": "boolean",
                        "description": "Whether to automatically remediate detected anomalies (e.g. shut off stuck switches, heal mesh).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "turn_off_stuck_actuator",
            "description": "Turn off an actuator or device that has been running abnormally or left unattended.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Entity ID of the stuck device.",
                    },
                },
                "required": ["entity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "restart_ble_proxy",
            "description": "Restart a stalled or disconnected Bluetooth / ESPHome proxy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Target BLE proxy device ID.",
                    },
                    "entity_id": {
                        "type": "string",
                        "description": "Optional proxy entity ID.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "heal_mesh_node",
            "description": "Heal, re-interview, or ping a lagging or offline Z-Wave or Zigbee mesh node.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Entity ID of the mesh node to heal.",
                    },
                    "node_id": {
                        "type": "string",
                        "description": "Optional physical hardware node ID.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "regenerate_dashboards",
            "description": "Regenerate Otis AI Lovelace dashboards (Command Center, Studio views, Room subviews) with current layout settings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layout_type": {
                        "type": "string",
                        "enum": ["sections", "grid"],
                        "description": "Dashboard layout type: 'sections' (Modern Sections) or 'grid' (Classic Grid).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_camera",
            "description": "Analyze a camera image or security snapshot using computer vision intelligence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "camera_entity_id": {
                        "type": "string",
                        "description": "Target camera entity ID (e.g. 'camera.front_doorbell').",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Question or analysis query (e.g., 'Is there a package on the porch?').",
                    },
                },
                "required": ["camera_entity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_macro",
            "description": "Execute a predefined Otis AI smart home macro or preset routine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "macro_id": {
                        "type": "string",
                        "description": "Macro ID to execute.",
                    },
                },
                "required": ["macro_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_ha_service",
            "description": "Execute any Home Assistant service (e.g., light.turn_on, switch.turn_off, climate.set_temperature).",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Home Assistant service domain (e.g., 'light', 'climate', 'media_player').",
                    },
                    "service": {
                        "type": "string",
                        "description": "Service name to call (e.g., 'turn_on', 'set_temperature').",
                    },
                    "service_data": {
                        "type": "object",
                        "description": "Payload/parameters dictionary for the service call.",
                    },
                },
                "required": ["domain", "service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_knowledge_base",
            "description": "Search local smart home user manuals, device specifications, troubleshooting guides, and historical event logs using semantic RAG retrieval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search question or keywords (e.g. 'How do I factory reset kitchen smart dimmer?', 'Why did the heater trigger anomaly?').",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of relevant knowledge snippets to return (default: 3).",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category filter (e.g. 'manual', 'event_history', 'troubleshooting').",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


def extract_tool_calls(
    text: str = "", raw_tool_calls: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Extract and normalize tool calls from native API responses or text fallbacks."""
    calls: list[dict[str, Any]] = []

    # 1. Native API tool calls (Ollama / OpenAI)
    if raw_tool_calls:
        for item in raw_tool_calls:
            if not isinstance(item, dict):
                continue
            if "function" in item and isinstance(item["function"], dict):
                fn = item["function"]
                name = fn.get("name", "")
                args = fn.get("arguments", {})
            else:
                name = item.get("name") or item.get("tool") or item.get("action", "")
                args = item.get("parameters") or item.get("arguments") or item.get("args", {})

            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if name:
                calls.append({"name": str(name).strip(), "parameters": args if isinstance(args, dict) else {}})

    if calls:
        return calls

    if not text or not isinstance(text, str):
        return []

    # 2. XML tag format: <tool_call>...</tool_call>
    xml_matches = re.findall(r"<tool_call>(.*?)</tool_call>", text, flags=re.DOTALL | re.IGNORECASE)
    for match in xml_matches:
        try:
            parsed = json.loads(match.strip())
            if isinstance(parsed, dict):
                name = parsed.get("name") or parsed.get("tool") or parsed.get("action")
                params = parsed.get("parameters") or parsed.get("arguments") or parsed.get("args") or {}
                if isinstance(params, str):
                    try:
                        params = json.loads(params)
                    except Exception:
                        params = {}
                if name:
                    calls.append({"name": str(name).strip(), "parameters": params if isinstance(params, dict) else {}})
        except Exception:
            pass

    if calls:
        return calls

    # 3. Code fence JSON format: ```json ... ``` or bare JSON containing tool indicators
    code_blocks = re.findall(r"```(?:json)?\s*([\{\[].*?[\}\]])\s*```", text, flags=re.DOTALL)
    candidate_json = code_blocks or re.findall(
        r"(\{(?:[^{}]|(?:\{[^{}]*\}))*\"(?:tool|action|function|calls|plan)\"[^{}]*\})",
        text,
        flags=re.DOTALL,
    )

    for block in candidate_json:
        try:
            parsed = json.loads(block.strip())
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        name = item.get("name") or item.get("tool") or item.get("action") or item.get("function")
                        params = item.get("parameters") or item.get("arguments") or item.get("args") or {}
                        if isinstance(params, str):
                            try:
                                params = json.loads(params)
                            except Exception:
                                params = {}
                        if name:
                            calls.append({"name": str(name).strip(), "parameters": params if isinstance(params, dict) else {}})
            elif isinstance(parsed, dict):
                if "plan" in parsed and isinstance(parsed["plan"], list):
                    for item in parsed["plan"]:
                        if isinstance(item, dict):
                            name = item.get("name") or item.get("tool") or item.get("action")
                            params = item.get("parameters") or item.get("arguments") or item.get("args") or {}
                            if name:
                                calls.append({"name": str(name).strip(), "parameters": params if isinstance(params, dict) else {}})
                elif "calls" in parsed and isinstance(parsed["calls"], list):
                    for item in parsed["calls"]:
                        if isinstance(item, dict):
                            name = item.get("name") or item.get("tool")
                            params = item.get("parameters") or item.get("arguments") or {}
                            if name:
                                calls.append({"name": str(name).strip(), "parameters": params if isinstance(params, dict) else {}})
                else:
                    name = parsed.get("name") or parsed.get("tool") or parsed.get("action") or parsed.get("function")
                    params = parsed.get("parameters") or parsed.get("arguments") or parsed.get("args") or {}
                    if isinstance(params, str):
                        try:
                            params = json.loads(params)
                        except Exception:
                            params = {}
                    if name:
                        calls.append({"name": str(name).strip(), "parameters": params if isinstance(params, dict) else {}})
        except Exception:
            pass

    if calls:
        return calls

    # 4. Inline syntax: [TOOL_CALL: name(args)]
    inline_matches = re.findall(r"\[TOOL_CALL:\s*([a-zA-Z0-9_\.]+)\s*\((.*?)\)\]", text)
    for in_name, in_args in inline_matches:
        try:
            parsed_args = json.loads(in_args.strip()) if in_args.strip().startswith("{") else {}
        except Exception:
            parsed_args = {}
        calls.append({"name": in_name.strip(), "parameters": parsed_args})

    return calls


def validate_tool_call(call: dict[str, Any], allowed_tools: list[str] | None = None) -> tuple[bool, str | None]:
    """Validate a parsed tool call structure and its parameters."""
    if not isinstance(call, dict):
        return False, "Tool call must be a dictionary"
    name = call.get("name")
    if not name or not isinstance(name, str):
        return False, "Missing or invalid tool name"
    if allowed_tools is not None and name not in allowed_tools:
        return False, f"Tool '{name}' is not in allowed tools list"
    params = call.get("parameters")
    if params is not None and not isinstance(params, dict):
        return False, "Tool parameters must be a dictionary"
    return True, None


class LocalLLMManager:
    """Manages local LLM communication, health monitoring, benchmarking, and inference."""

    def __init__(
        self,
        hass: HomeAssistant,
        url: str = DEFAULT_LOCAL_LLM_URL,
        model: str = DEFAULT_LOCAL_LLM_MODEL,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        embedding_model: str | None = None,
        rag_manager: Any | None = None,
    ) -> None:
        """Initialize the Local LLM Manager."""
        self.hass = hass
        self.url = (url or DEFAULT_LOCAL_LLM_URL).rstrip("/")
        self.model = model or DEFAULT_LOCAL_LLM_MODEL
        self.api_key = api_key
        self.timeout = timeout
        self.embedding_model = embedding_model
        self.rag_manager = rag_manager
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

    async def async_list_models(self, target_url: str | None = None) -> list[str]:
        """Discover installed models from the local LLM server."""
        health = await self.async_health_check(target_url=target_url)
        return health.get("models", [])

    async def async_pull_model(self, model_name: str, target_url: str | None = None) -> dict[str, Any]:
        """Pull/download a model onto the local Ollama instance."""
        base_url = (target_url or self.url).rstrip("/")
        session = self._get_session()
        headers = self._get_headers()
        t0 = time.perf_counter()

        try:
            ollama_url = f"{base_url}/api/pull"
            _LOGGER.info("Initiating local model pull '%s' on %s...", model_name, base_url)
            async with session.post(
                ollama_url,
                json={"name": model_name, "stream": False},
                headers=headers,
                timeout=ClientTimeout(total=600.0),
            ) as resp:
                elapsed = round(time.perf_counter() - t0, 1)
                if resp.status == 200:
                    data = await resp.json()
                    status = data.get("status", "success")
                    _LOGGER.info("Successfully pulled local model '%s' in %ss", model_name, elapsed)
                    # Refresh health/models cache
                    await self.async_health_check(target_url=base_url)
                    return {
                        "success": True,
                        "model": model_name,
                        "status": status,
                        "duration_s": elapsed,
                    }
                err_text = await resp.text()
                return {
                    "success": False,
                    "model": model_name,
                    "error": f"HTTP {resp.status}: {err_text[:200]}",
                    "duration_s": elapsed,
                }
        except Exception as err:
            elapsed = round(time.perf_counter() - t0, 1)
            _LOGGER.error("Failed to pull local model '%s': %s", model_name, err)
            return {
                "success": False,
                "model": model_name,
                "error": str(err),
                "duration_s": elapsed,
            }

    async def async_get_embedding(
        self,
        text: str,
        model: str | None = None,
        timeout: float = 15.0,
    ) -> list[float] | None:
        """Generate a dense vector embedding using the local LLM server (Ollama /embed or /v1/embeddings)."""
        chosen_model = model or self.embedding_model or self.model
        session = self._get_session()
        headers = self._get_headers()
        req_timeout = ClientTimeout(total=timeout)

        # 1. Try Ollama /api/embed (Ollama v0.1.34+)
        try:
            ollama_embed_url = f"{self.url}/api/embed"
            async with session.post(
                ollama_embed_url,
                json={"model": chosen_model, "input": text},
                headers=headers,
                timeout=req_timeout,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    embeddings = data.get("embeddings", [])
                    if embeddings and isinstance(embeddings, list) and isinstance(embeddings[0], list):
                        return embeddings[0]
        except Exception as err:
            _LOGGER.debug("Ollama /api/embed attempt failed: %s; trying legacy /api/embeddings", err)

        # 2. Try legacy Ollama /api/embeddings
        try:
            ollama_url = f"{self.url}/api/embeddings"
            async with session.post(
                ollama_url,
                json={"model": chosen_model, "prompt": text},
                headers=headers,
                timeout=req_timeout,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    embedding = data.get("embedding", [])
                    if embedding and isinstance(embedding, list):
                        return embedding
        except Exception as err:
            _LOGGER.debug("Ollama /api/embeddings attempt failed: %s; trying /v1/embeddings", err)

        # 3. Fallback to OpenAI-compatible /v1/embeddings
        try:
            v1_url = f"{self.url}/v1/embeddings"
            async with session.post(
                v1_url,
                json={"model": chosen_model, "input": text},
                headers=headers,
                timeout=req_timeout,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    data_items = data.get("data", [])
                    if data_items and isinstance(data_items[0], dict):
                        return data_items[0].get("embedding")
        except Exception as err:
            _LOGGER.debug("OpenAI /v1/embeddings attempt failed: %s", err)

        return None

    async def async_generate(
        self,
        prompt: str = "",
        system_prompt: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        timeout: float | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send a prompt or message list to the local LLM and return structured output, tool calls, and metrics."""
        chosen_model = model or self.model
        req_timeout = timeout or self.timeout
        session = self._get_session()
        headers = self._get_headers()
        t0 = time.perf_counter()

        # Build message history
        if messages is not None:
            msg_list = list(messages)
        else:
            msg_list = []
            if system_prompt:
                msg_list.append({"role": "system", "content": system_prompt})
            if prompt:
                msg_list.append({"role": "user", "content": prompt})

        # Try Ollama /api/chat
        ollama_endpoint = f"{self.url}/api/chat"
        payload: dict[str, Any] = {
            "model": chosen_model,
            "messages": msg_list,
            "stream": False,
            "keep_alive": "15m",
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": 8192,
                "stop": ["<|im_end|>", "<|endoftext|>", "Observation:", "User:"],
            },
        }
        if tools:
            payload["tools"] = tools

        try:
            async with session.post(
                ollama_endpoint,
                json=payload,
                headers=headers,
                timeout=ClientTimeout(total=req_timeout),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    total_time = max(0.001, time.perf_counter() - t0)
                    msg_obj = data.get("message", {})
                    msg = msg_obj.get("content", "") or ""
                    raw_tools = msg_obj.get("tool_calls", [])
                    extracted_tools = extract_tool_calls(msg, raw_tools)

                    eval_count = data.get("eval_count", 0)
                    prompt_eval_count = data.get("prompt_eval_count", 0)
                    eval_duration = data.get("eval_duration", 0) / 1e9  # nanoseconds to seconds
                    tokens_per_sec = (
                        round(eval_count / eval_duration, 1) if eval_duration > 0 else round(eval_count / total_time, 1)
                    )

                    return {
                        "success": True,
                        "response": msg,
                        "tool_calls": extracted_tools,
                        "raw_tool_calls": raw_tools,
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
            v1_payload: dict[str, Any] = {
                "model": chosen_model,
                "messages": msg_list,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }
            if tools:
                v1_payload["tools"] = tools

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
                    choice_msg = choices[0].get("message", {}) if choices else {}
                    content = choice_msg.get("content", "") or ""
                    raw_tools = choice_msg.get("tool_calls", [])
                    extracted_tools = extract_tool_calls(content, raw_tools)

                    usage = data.get("usage", {})
                    completion_tokens = usage.get("completion_tokens", len(content.split()) * 1.3)
                    tokens_per_sec = round(completion_tokens / total_time, 1)

                    return {
                        "success": True,
                        "response": content,
                        "tool_calls": extracted_tools,
                        "raw_tool_calls": raw_tools,
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

    async def async_execute_tool_plan(
        self, tool_calls: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Execute a structured autonomous tool plan against Home Assistant services."""
        if not self.hass:
            return [{"success": False, "error": "Home Assistant instance not available"}]

        execution_results: list[dict[str, Any]] = []
        for call in tool_calls:
            valid, err_msg = validate_tool_call(call)
            if not valid:
                execution_results.append({
                    "tool": call.get("name", "unknown") if isinstance(call, dict) else "unknown",
                    "success": False,
                    "error": err_msg,
                })
                continue

            name = str(call["name"]).strip()
            params = dict(call.get("parameters") or {})
            t_start = time.perf_counter()

            try:
                if name == "query_knowledge_base" and hasattr(self, "rag_manager") and self.rag_manager:
                    res_data = await self.rag_manager.async_query_knowledge(
                        query=params.get("query", ""),
                        limit=params.get("limit", 3),
                        category=params.get("category"),
                    )
                elif name == "call_ha_service":
                    domain = params.pop("domain", "")
                    service = params.pop("service", "")
                    sdata = params.pop("service_data", {}) or params
                    await self.hass.services.async_call(domain, service, sdata, blocking=True)
                    res_data = {"service": f"{domain}.{service}", "data": sdata}
                elif "." in name:
                    domain, service = name.split(".", 1)
                    await self.hass.services.async_call(domain, service, params, blocking=True)
                    res_data = {"service": name, "data": params}
                else:
                    await self.hass.services.async_call("otis_ai", name, params, blocking=True)
                    res_data = {"service": f"otis_ai.{name}", "data": params}

                elapsed = round(time.perf_counter() - t_start, 3)
                execution_results.append({
                    "tool": name,
                    "parameters": params,
                    "success": True,
                    "result": res_data,
                    "duration_s": elapsed,
                })
            except Exception as err:
                elapsed = round(time.perf_counter() - t_start, 3)
                _LOGGER.warning("Tool execution error for '%s': %s", name, err)
                execution_results.append({
                    "tool": name,
                    "parameters": params,
                    "success": False,
                    "error": str(err),
                    "duration_s": elapsed,
                })

        return execution_results

    async def async_chat_with_tools(
        self,
        prompt: str,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        max_iterations: int = 3,
        auto_execute: bool = True,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Autonomous multi-turn tool-calling loop using local LLMs."""
        chosen_tools = tools if tools is not None else DEFAULT_OTIS_TOOLS
        default_sys = (
            "You are Otis AI, the ultimate smart home butler and co-pilot. "
            "You have direct access to smart home tools to inspect cameras, heal network nodes, "
            "pin or unpin devices on the floorplan, run sentinel audits, and control devices. "
            "When a user request requires action, call the appropriate tool. "
            "When answering, be concise, direct, and actionable."
        )
        sys_prompt = system_prompt or default_sys
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt},
        ]

        all_executed_tools: list[dict[str, Any]] = []
        total_tokens = 0
        t0 = time.perf_counter()
        gen_res: dict[str, Any] = {}

        for iteration in range(1, max_iterations + 1):
            gen_res = await self.async_generate(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                tools=chosen_tools,
            )
            if not gen_res.get("success"):
                return {
                    "success": False,
                    "error": gen_res.get("error", "Local LLM generation failed"),
                    "iterations": iteration,
                    "executed_tools": all_executed_tools,
                    "total_duration_s": round(time.perf_counter() - t0, 2),
                }

            total_tokens += gen_res.get("tokens_generated", 0)
            tool_calls = gen_res.get("tool_calls", [])

            if not tool_calls:
                # No tool calls needed; assistant provided final answer
                return {
                    "success": True,
                    "response": gen_res.get("response", ""),
                    "iterations": iteration,
                    "executed_tools": all_executed_tools,
                    "model": gen_res.get("model", model or self.model),
                    "provider": gen_res.get("provider"),
                    "total_tokens": total_tokens,
                    "total_duration_s": round(time.perf_counter() - t0, 2),
                }

            # Tool calls detected
            if not auto_execute:
                return {
                    "success": True,
                    "response": gen_res.get("response", ""),
                    "tool_calls": tool_calls,
                    "iterations": iteration,
                    "executed_tools": [],
                    "auto_execute": False,
                    "model": gen_res.get("model", model or self.model),
                    "total_duration_s": round(time.perf_counter() - t0, 2),
                }

            # Execute tool plan
            exec_results = await self.async_execute_tool_plan(tool_calls)
            all_executed_tools.extend(exec_results)

            # Append assistant turn and tool execution result to message history for subsequent reasoning
            messages.append({
                "role": "assistant",
                "content": gen_res.get("response", "") or f"Invoked {len(tool_calls)} tool(s).",
            })
            messages.append({
                "role": "user",
                "content": f"Observation / Tool Output: {json.dumps(exec_results)}",
            })

        # Completed max iterations
        return {
            "success": True,
            "response": gen_res.get("response", "") or f"Executed {len(all_executed_tools)} tool action(s).",
            "iterations": max_iterations,
            "executed_tools": all_executed_tools,
            "model": gen_res.get("model", model or self.model),
            "provider": gen_res.get("provider"),
            "total_tokens": total_tokens,
            "total_duration_s": round(time.perf_counter() - t0, 2),
        }

    async def async_benchmark(self, prompt: str | None = None, model: str | None = None) -> dict[str, Any]:
        """Run a standardized smart home reasoning benchmark against the local LLM."""
        target_model = model or self.model
        test_prompt = prompt or (
            "You are Otis AI, a smart home co-pilot. "
            "Living Room: Motion detected, ambient light is 15 lux, temperature is 74F, target is 71F. "
            "Output a 2-sentence actionable recommendation."
        )
        t0 = time.perf_counter()
        result = await self.async_generate(
            prompt=test_prompt,
            system_prompt="You are a smart home automation expert. Be concise and actionable.",
            model=target_model,
            max_tokens=150,
        )
        total_time = round(time.perf_counter() - t0, 2)
        health = await self.async_health_check()

        return {
            "success": result.get("success", False),
            "model": result.get("model", target_model),
            "provider": result.get("provider", health.get("provider")),
            "tokens_per_second": result.get("tokens_per_sec", 0.0),
            "tokens_generated": result.get("tokens_generated", 0),
            "total_latency_seconds": total_time,
            "endpoint_health": health,
            "sample_output": result.get("response", result.get("error", "")),
        }

