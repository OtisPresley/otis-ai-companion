"""Otis AI Companion: Local LLM & Edge Inference Connector.

Provides zero-cloud, privacy-first local LLM integration for Assist Co-Pilot
and Sentinel anomaly auditing with benchmark telemetry and transparent cloud failover.
Compatible with Ollama, vLLM, LocalAI, and OpenAI-compatible inference servers.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import time
from typing import Any

from aiohttp import ClientSession, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, DEFAULT_LOCAL_MAX_TOKENS

_LOGGER = logging.getLogger(__name__)

DEFAULT_LOCAL_LLM_URL = "http://127.0.0.1:11434"
DEFAULT_LOCAL_LLM_MODEL = "qwen2.5:3b"
DEFAULT_LOCAL_VISION_MODEL = "llama3.2-vision:latest"
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
                        "description": "Home Assistant entity ID to pin (e.g., 'light.ceiling').",
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
                        "description": "Target camera entity ID (e.g. 'camera.porch').",
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
    {
        "type": "function",
        "function": {
            "name": "optimize_battery_schedule",
            "description": "Calculate and optimize a 24-hour battery charge/discharge schedule based on solar generation forecasts and TOU peak pricing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["auto", "peak_arbitrage", "self_consumption", "backup_reserve"],
                        "description": "Arbitrage strategy: 'auto', 'peak_arbitrage' (shave peak), 'self_consumption' (store solar), or 'backup_reserve' (hold 100% outage reserve).",
                    },
                    "battery_entity": {
                        "type": "string",
                        "description": "Optional battery sensor entity ID (e.g. 'sensor.battery_level').",
                    },
                    "battery_capacity_kwh": {
                        "type": "number",
                        "description": "Usable battery capacity in kWh (default: 13.5).",
                    },
                    "min_reserve_soc_pct": {
                        "type": "number",
                        "description": "Minimum reserve State of Charge percentage preserved for emergencies (default: 20).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_energy_arbitrage_plan",
            "description": "Retrieve current battery arbitrage status, active action, tariff window, and 24-hour cost savings plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["auto", "peak_arbitrage", "self_consumption", "backup_reserve"],
                        "description": "Strategy mode override.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_backup_configuration",
            "description": "Inspect Home Assistant backups, historical archives, and configuration snapshots to find complete or uncorrupted versions of an overwritten, missing, or broken automation, script, or blueprint.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "Name, alias, or entity ID of the target automation or script (e.g. 'notify_router', 'Notify Router').",
                    },
                    "item_type": {
                        "type": "string",
                        "enum": ["script", "automation", "blueprint"],
                        "description": "Configuration item type.",
                    },
                },
                "required": ["item_name"],
            },
        },
    },
]


ALLOWED_TOOL_NAMES = {
    "pin_floorplan_entity",
    "unpin_floorplan_entity",
    "run_sentinel_watchdog",
    "turn_off_stuck_actuator",
    "restart_ble_proxy",
    "heal_mesh_node",
    "regenerate_dashboards",
    "analyze_camera",
    "execute_macro",
    "call_ha_service",
    "query_knowledge_base",
    "optimize_battery_schedule",
    "get_energy_arbitrage_plan",
    "inspect_backup_configuration",
}

ALLOWED_SERVICE_DOMAINS = {
    "light",
    "switch",
    "climate",
    "cover",
    "fan",
    "media_player",
    "scene",
    "script",
    "vacuum",
    "lock",
    "otis_ai",
}


def select_relevant_tools(user_text: str) -> list[dict[str, Any]]:
    """Select only the subset of DEFAULT_OTIS_TOOLS relevant to the user's message.

    Avoids injecting ~2,500 tokens of tool JSON schemas into Local Edge LLM prompts
    for informational, status, guidance, or YAML-authoring queries.
    """
    text_low = (user_text or "").strip().lower()
    if not text_low:
        return []

    # Informational / guidance / YAML-generation queries do not execute direct tools
    if any(
        text_low.startswith(p)
        for p in (
            "what ",
            "how ",
            "why ",
            "where ",
            "when ",
            "who ",
            "explain ",
            "describe ",
            "write ",
            "create an automation",
            "create a script",
            "draft ",
            "tell me ",
            "list ",
        )
    ) and not any(k in text_low for k in ("manual", "handbook", "spec", "reset", "backup", "restore", "recover", "overwritten", "missing")):
        return []

    tool_by_name = {
        t["function"]["name"]: t
        for t in DEFAULT_OTIS_TOOLS
        if isinstance(t, dict) and isinstance(t.get("function"), dict) and t["function"].get("name")
    }
    selected: list[str] = []

    if any(k in text_low for k in ("backup", "restore", "snapshot", "rollback", "recover", "overwritten", "missing")):
        selected.append("inspect_backup_configuration")

    if any(k in text_low for k in ("unpin", "remove pin")):
        selected.append("unpin_floorplan_entity")
    elif any(k in text_low for k in ("pin ", "floorplan", "floor plan")):
        selected.append("pin_floorplan_entity")

    if any(k in text_low for k in ("sentinel", "anomaly", "anomalies", "watchdog")):
        selected.append("run_sentinel_watchdog")
    if any(k in text_low for k in ("stuck", "runaway", "left on")):
        selected.append("turn_off_stuck_actuator")
    if any(k in text_low for k in ("ble proxy", "bluetooth proxy")):
        selected.append("restart_ble_proxy")
    if any(k in text_low for k in ("heal ", "z-wave", "zwave", "zigbee", "mesh")):
        selected.append("heal_mesh_node")
    if any(k in text_low for k in ("regenerate", "rebuild")) and any(
        k in text_low for k in ("dashboard", "command center", "studio")
    ):
        selected.append("regenerate_dashboards")
    if any(k in text_low for k in ("camera", "snapshot", "doorbell", "porch")):
        selected.append("analyze_camera")
    if any(k in text_low for k in ("macro", "movie night", "goodnight", "party mode", "lockdown")):
        selected.append("execute_macro")
    if any(k in text_low for k in ("manual", "documentation", "reset", "troubleshoot")):
        selected.append("query_knowledge_base")
    if any(k in text_low for k in ("battery", "arbitrage", "solar", "tou")):
        selected.extend(["optimize_battery_schedule", "get_energy_arbitrage_plan"])
    if any(
        k in text_low
        for k in (
            "turn on",
            "turn off",
            "switch on",
            "switch off",
            "toggle",
            "dim ",
            "brighten",
            "set temperature",
            "set thermostat",
            "lock ",
            "unlock ",
            "open ",
            "close ",
            "volume",
            "mute",
            "pause",
            "play ",
        )
    ):
        selected.append("call_ha_service")

    return [tool_by_name[name] for name in selected if name in tool_by_name]


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


def normalize_image_base64(image_data: str) -> tuple[str, str]:
    """Normalize base64 image data into (raw_base64, data_uri)."""
    cleaned = (image_data or "").strip()
    if cleaned.startswith("data:"):
        parts = cleaned.split(",", 1)
        raw_b64 = parts[1] if len(parts) > 1 else ""
        data_uri = cleaned
    else:
        raw_b64 = cleaned
        data_uri = f"data:image/jpeg;base64,{cleaned}"
    return raw_b64, data_uri


class LocalLLMManager:
    """Manages local LLM communication, health monitoring, benchmarking, and inference."""

    def __init__(
        self,
        hass: HomeAssistant,
        url: str = DEFAULT_LOCAL_LLM_URL,
        model: str = DEFAULT_LOCAL_LLM_MODEL,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = DEFAULT_LOCAL_MAX_TOKENS,
        embedding_model: str | None = None,
        rag_manager: Any | None = None,
    ) -> None:
        """Initialize the Local LLM Manager."""
        self.hass = hass
        self.url = (url or DEFAULT_LOCAL_LLM_URL).rstrip("/")
        self.model = model or DEFAULT_LOCAL_LLM_MODEL
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens or DEFAULT_LOCAL_MAX_TOKENS
        self.embedding_model = embedding_model
        self.rag_manager = rag_manager
        self._last_health: dict[str, Any] = {"status": "unknown"}
        self._embedding_unavailable_until: float = 0.0
        self._last_benchmark: dict[str, Any] | None = None
        self._metrics: dict[str, Any] = {
            "total_requests": 0,
            "last_tokens_per_sec": 0.0,
            "avg_tokens_per_sec": 0.0,
            "last_latency_s": 0.0,
            "avg_latency_s": 0.0,
            "last_model": "",
        }
        self._last_status: dict[str, Any] | None = None
        self._last_status_ts: float = 0.0
        self._last_suitability: dict[str, Any] | None = None
        self._last_suitability_ts: float = 0.0

    def _record_inference_telemetry(self, model_name: str, tokens_per_sec: float, duration_s: float) -> None:
        """Record local LLM inference speed and latency telemetry for suitability recommendations."""
        try:
            prev_n = int(self._metrics.get("total_requests", 0))
            prev_model = str(self._metrics.get("last_model") or "")
            if prev_model and prev_model.lower() != str(model_name or "").lower():
                prev_n = 0
            n = prev_n + 1
            prev_avg_tps = float(self._metrics.get("avg_tokens_per_sec", 0.0)) if prev_n > 0 else 0.0
            prev_avg_lat = float(self._metrics.get("avg_latency_s", 0.0)) if prev_n > 0 else 0.0
            self._metrics = {
                "total_requests": n,
                "last_tokens_per_sec": round(float(tokens_per_sec), 1),
                "avg_tokens_per_sec": round(((prev_avg_tps * prev_n) + float(tokens_per_sec)) / n, 1),
                "last_latency_s": round(float(duration_s), 2),
                "avg_latency_s": round(((prev_avg_lat * prev_n) + float(duration_s)) / n, 2),
                "last_model": str(model_name or self.model or ""),
            }
        except Exception:
            pass

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

        # 3. If default check failed on a legacy URL, auto-probe local add-on endpoints
        if target_url is None:
            for cand_url in ("http://local-otis-ollama:11434", "http://127.0.0.1:11434"):
                if cand_url.rstrip("/") == base_url:
                    continue
                cand_res = await self.async_health_check(target_url=cand_url)
                if cand_res.get("status") == "online":
                    self.url = cand_url
                    self._persist_config_options()
                    self._last_health = cand_res
                    return cand_res

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

    async def async_delete_model(self, model_name: str, target_url: str | None = None) -> dict[str, Any]:
        """Delete a model from the local Ollama instance."""
        base_url = (target_url or self.url).rstrip("/")
        session = self._get_session()
        headers = self._get_headers()
        try:
            ollama_url = f"{base_url}/api/delete"
            async with session.delete(
                ollama_url,
                json={"name": model_name},
                headers=headers,
                timeout=ClientTimeout(total=30.0),
            ) as resp:
                if resp.status == 200:
                    await self.async_health_check(target_url=base_url)
                    return {"success": True, "model": model_name, "status": "deleted"}
                err_text = await resp.text()
                return {"success": False, "model": model_name, "error": f"HTTP {resp.status}: {err_text[:200]}"}
        except Exception as err:
            return {"success": False, "model": model_name, "error": str(err)}

    async def async_get_running_models(self, target_url: str | None = None) -> list[dict[str, Any]]:
        """Query Ollama /api/ps for models currently loaded in RAM/VRAM."""
        base_url = (target_url or self.url).rstrip("/")
        session = self._get_session()
        headers = self._get_headers()
        try:
            async with session.get(
                f"{base_url}/api/ps",
                headers=headers,
                timeout=ClientTimeout(total=3.0),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    loaded = []
                    for m in data.get("models", []):
                        if isinstance(m, dict):
                            size_mb = round((m.get("size") or 0) / (1024 * 1024), 1)
                            vram_mb = round((m.get("size_vram") or 0) / (1024 * 1024), 1)
                            loaded.append({
                                "name": m.get("name"),
                                "size_mb": size_mb,
                                "vram_mb": vram_mb,
                                "expires_at": m.get("expires_at"),
                            })
                    return loaded
        except Exception:
            pass
        return []

    @staticmethod
    def _probe_host_hardware_sync() -> dict[str, Any]:
        """Inspect host CPU, RAM, disk, and GPU capabilities synchronously (run via executor)."""
        cpu_model = "Unknown CPU"
        cpu_cores = os.cpu_count() or 1
        try:
            if os.path.exists("/proc/cpuinfo"):
                with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if "model name" in line or "Hardware" in line or "Processor" in line:
                            parts = line.split(":", 1)
                            if len(parts) > 1 and parts[1].strip():
                                cpu_model = parts[1].strip()
                                break
        except Exception:
            pass

        ram_total_gb = 0.0
        ram_available_gb = 0.0
        try:
            if os.path.exists("/proc/meminfo"):
                with open("/proc/meminfo", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            kb = int(re.findall(r"\d+", line)[0])
                            ram_total_gb = round(kb / (1024 * 1024), 1)
                        elif line.startswith("MemAvailable:"):
                            kb = int(re.findall(r"\d+", line)[0])
                            ram_available_gb = round(kb / (1024 * 1024), 1)
        except Exception:
            pass

        disk_free_gb = 0.0
        try:
            target_path = "/config" if os.path.exists("/config") else "/"
            usage = shutil.disk_usage(target_path)
            disk_free_gb = round(usage.free / (1024 ** 3), 1)
        except Exception:
            pass

        gpu_detected = os.path.exists("/dev/dri/renderD128") or os.path.exists("/dev/nvidia0")
        gpu_type = (
            "NVIDIA GPU"
            if os.path.exists("/dev/nvidia0")
            else ("Intel/DRM iGPU (/dev/dri/renderD128)" if os.path.exists("/dev/dri/renderD128") else "CPU Only")
        )
        return {
            "cpu_model": cpu_model,
            "cpu_cores": cpu_cores,
            "ram_total_gb": ram_total_gb,
            "ram_available_gb": ram_available_gb,
            "disk_free_gb": disk_free_gb,
            "gpu_detected": gpu_detected,
            "gpu_type": gpu_type,
        }

    async def async_assess_host_ollama_suitability(self, force_refresh: bool = False) -> dict[str, Any]:
        """Verify whether the local Home Assistant host can, and is recommended to, run the Otis Ollama Add-on."""
        now = time.monotonic()
        if not force_refresh and self._last_suitability is not None and (now - self._last_suitability_ts) < 30.0:
            return dict(self._last_suitability)

        if self.hass and hasattr(self.hass, "async_add_executor_job"):
            hw_res = self.hass.async_add_executor_job(self._probe_host_hardware_sync)
            hw = await hw_res if asyncio.iscoroutine(hw_res) or hasattr(hw_res, "__await__") else self._probe_host_hardware_sync()
        else:
            hw = self._probe_host_hardware_sync()

        supervisor_available = bool(
            hasattr(self.hass, "config")
            and "hassio" in getattr(self.hass.config, "components", set())
        )
        addon_installed = False
        addon_state = "not_installed"
        addon_slug = "local_otis_ollama"
        addon_version = None

        # Detect local Ollama add-on via direct HTTP health probe (no Supervisor API calls)
        try:
            probe_health = await self.async_health_check(target_url="http://local-otis-ollama:11434")
            if probe_health.get("status") == "online":
                addon_installed = True
                addon_state = "started"
        except Exception:
            pass

        cpu_cores = int(hw.get("cpu_cores", 1))
        ram_total = float(hw.get("ram_total_gb", 0.0))
        ram_avail = float(hw.get("ram_available_gb", hw.get("ram_avail_gb", 0.0)))
        disk_free = float(hw.get("disk_free_gb", 0.0))
        gpu_detected = bool(hw.get("gpu_detected", False))

        can_run = bool(
            cpu_cores >= 4
            and ram_total >= 6.0
            and disk_free >= 6.0
        )
        recommended = bool(
            can_run
            and cpu_cores >= 6
            and ram_total >= 7.5
            and ram_avail >= 2.5
            and disk_free >= 10.0
        )

        if ram_total >= 12.0 and cpu_cores >= 8:
            recommended_model = "qwen2.5:3b"
            model_recommendation_reason = (
                f"Host hardware ({hw.get('cpu_model')}, {cpu_cores} threads, {ram_total} GB RAM) "
                "supports higher-reasoning 'qwen2.5:3b' local inference."
            )
        else:
            recommended_model = "qwen2.5:1.5b"
            model_recommendation_reason = (
                f"Host memory/CPU profile ({cpu_cores} threads, {ram_total} GB RAM) "
                "is best suited for the fast, lightweight 'qwen2.5:1.5b' model."
            )

        # Evaluate recent benchmark or live inference telemetry for CPU responsiveness overrides
        bench = getattr(self, "_last_benchmark", None)
        metrics = getattr(self, "_metrics", None) or {}
        measured_model = ""
        measured_tps = 0.0
        measured_lat = 0.0
        if isinstance(bench, dict) and bench.get("success"):
            measured_model = str(bench.get("model") or "")
            measured_tps = float(bench.get("tokens_per_second") or 0.0)
            measured_lat = float(bench.get("total_latency_seconds") or 0.0)
        elif int(metrics.get("total_requests", 0)) >= 2:
            measured_model = str(metrics.get("last_model") or "")
            measured_tps = float(metrics.get("avg_tokens_per_sec") or 0.0)
            measured_lat = float(metrics.get("avg_latency_s") or 0.0)

        if measured_model and any(sz in measured_model.lower() for sz in ("3b", "7b", "8b", "14b", "32b")):
            if (0.0 < measured_tps < 10.0) or (measured_lat > 10.0):
                recommended_model = "qwen2.5:1.5b"
                model_recommendation_reason = (
                    f"Recent local inference telemetry on '{measured_model}' measured {measured_tps:.1f} tok/s "
                    f"({measured_lat:.1f}s latency). Switching to 'qwen2.5:1.5b' roughly doubles local Edge AI responsiveness on CPU."
                )

        active_model = (self.model or "").strip()
        model_switch_recommended = bool(
            can_run
            and active_model
            and active_model.lower() != recommended_model.lower()
        )

        reasons: list[str] = []
        if not supervisor_available:
            reasons.append("Home Assistant Supervisor API not detected (Container/Core-only install).")
        if cpu_cores < 4:
            reasons.append(f"Insufficient CPU cores ({cpu_cores} detected, minimum 4 required).")
        if ram_total < 7.5:
            reasons.append(f"Total RAM ({ram_total} GB) is below the 8 GB recommended threshold.")
        if ram_avail < 2.5:
            reasons.append(f"Available free RAM ({ram_avail} GB) is below the 2.5 GB safety margin.")
        if disk_free < 10.0:
            reasons.append(f"Free storage ({disk_free} GB) is below the 10 GB recommended threshold.")

        if recommended:
            summary = (
                f"Recommended — {hw.get('cpu_model')} ({cpu_cores} threads), "
                f"{ram_total} GB RAM ({ram_avail} GB free), {disk_free} GB free storage, {hw.get('gpu_type', 'CPU/iGPU')}."
            )
        elif can_run:
            summary = f"Capable (Light Model Only) — {', '.join(reasons) or 'Meets minimum requirements.'}"
        else:
            summary = f"Not Recommended — {' '.join(reasons) or 'Hardware or Supervisor requirements not met.'}"

        gpu_devices = hw.get("gpu_devices") or (["renderD128"] if gpu_detected else [])
        res = {
            **hw,
            "ram_available_gb": ram_avail,
            "ram_avail_gb": ram_avail,
            "gpu_devices": gpu_devices,
            "supervisor_available": supervisor_available,
            "can_run": can_run,
            "recommended": recommended,
            "recommended_model": recommended_model,
            "active_model": active_model,
            "model_switch_recommended": model_switch_recommended,
            "model_recommendation_reason": model_recommendation_reason,
            "last_benchmark": getattr(self, "_last_benchmark", None),
            "metrics": getattr(self, "_metrics", None),
            "addon_slug": addon_slug,
            "addon_installed": addon_installed,
            "addon_state": addon_state,
            "addon_version": addon_version,
            "reasons": reasons,
            "blockers": reasons if not can_run else [],
            "summary": summary,
        }
        self._last_suitability = res
        self._last_suitability_ts = now
        return res

    async def async_get_ollama_status(self, force_refresh: bool = False) -> dict[str, Any]:
        """Return comprehensive GUI status combining endpoint health, loaded models (/api/ps), host suitability, and Supervisor add-on telemetry."""
        now = time.monotonic()
        if not force_refresh and self._last_status is not None and (now - self._last_status_ts) < 20.0:
            return dict(self._last_status)

        suitability = await self.async_assess_host_ollama_suitability(force_refresh=force_refresh)
        health = await self.async_health_check()

        # If configured URL is offline and local Supervisor add-on is started, auto-probe local add-on URLs
        if health.get("status") != "online" and suitability.get("addon_state") == "started":
            for candidate_url in ("http://local-otis-ollama:11434", "http://127.0.0.1:11434", "http://172.30.32.1:11434"):
                cand_health = await self.async_health_check(target_url=candidate_url)
                if cand_health.get("status") == "online":
                    self.url = candidate_url
                    self._persist_config_options()
                    health = cand_health
                    break

        is_online = health.get("status") == "online"
        running_models = await self.async_get_running_models() if is_online else []
        addon_stats: dict[str, Any] = {}

        res = {
            "online": is_online,
            "provider": health.get("provider", "ollama"),
            "endpoint_url": health.get("url") or self.url,
            "active_model": health.get("active_model") or self.model,
            "available_models": health.get("models") or [],
            "latency_ms": health.get("latency_ms", 0.0),
            "health": health,
            "running_models": running_models,
            "suitability": suitability,
            "addon_stats": addon_stats,
            "configured_url": self.url,
            "configured_model": self.model,
        }
        self._last_status = res
        self._last_status_ts = now
        return res

    def _persist_config_options(self) -> None:
        """Persist active local_llm_url and local_llm_model into the Otis AI config entry options."""
        try:
            if (
                self.hass is not None
                and hasattr(self.hass, "config_entries")
                and hasattr(self.hass.config_entries, "async_entries")
                and hasattr(self.hass.config_entries, "async_update_entry")
            ):
                entries = self.hass.config_entries.async_entries(DOMAIN)
                if isinstance(entries, list) and entries:
                    entry = entries[0]
                    opts = dict(getattr(entry, "options", None) or {})
                    opts["local_llm_enabled"] = True
                    opts["local_llm_url"] = self.url
                    opts["local_llm_model"] = self.model
                    self.hass.config_entries.async_update_entry(entry, options=opts)
        except Exception as err:
            _LOGGER.debug("Could not persist local LLM config options: %s", err)

    async def async_manage_ollama_addon(self, action: str, model: str | None = None) -> dict[str, Any]:
        """Manage the Otis Edge AI (Ollama) Supervisor Add-on lifecycle and models."""
        act = (action or "status").strip().lower()
        if act == "suitability":
            suit = await self.async_assess_host_ollama_suitability(force_refresh=True)
            return {"success": True, "action": act, "suitability": suit, "message": suit.get("summary")}

        if act == "status":
            st = await self.async_get_ollama_status(force_refresh=True)
            return {"success": True, "action": act, "status": st, **st}

        if act == "delete_model" and model:
            del_res = await self.async_delete_model(model)
            st = await self.async_get_ollama_status(force_refresh=True)
            return {
                **del_res,
                "action": act,
                "status": st,
                "message": f"Deleted model '{model}'." if del_res.get("success") else del_res.get("error"),
                **st,
            }

        if act in ("pull_model", "pull") and model:
            pull_res = await self.async_pull_model(model.strip())
            if pull_res.get("success"):
                self.model = model.strip()
                self._persist_config_options()
            st = await self.async_get_ollama_status(force_refresh=True)
            return {
                **pull_res,
                "action": act,
                "status": st,
                "message": f"Pulled and activated model '{model.strip()}'." if pull_res.get("success") else pull_res.get("error"),
                **st,
            }

        if act in ("set_model", "switch_model") and model:
            self.model = model.strip()
            self._persist_config_options()
            st = await self.async_get_ollama_status(force_refresh=True)
            return {
                "success": True,
                "action": act,
                "active_model": self.model,
                "status": st,
                "message": f"Active Local Edge AI model set to '{self.model}'.",
                **st,
            }

        if act in ("install", "start", "stop", "restart", "uninstall"):
            addon_url = "/hassio/addon/local_otis_ollama"
            st = await self.async_get_ollama_status(force_refresh=True)
            return {
                "success": True,
                "action": act,
                "addon_url": addon_url,
                "deep_link": addon_url,
                "status": st,
                "message": f"Manage Otis Edge AI (Ollama) add-on directly in the Home Assistant Add-on Store: {addon_url}",
                **st,
            }

        return {"success": False, "action": act, "error": f"Unsupported action: {act}"}

    async def async_get_embedding(
        self,
        text: str,
        model: str | None = None,
        timeout: float = 2.0,
    ) -> list[float] | None:
        """Generate a dense vector embedding using the local LLM server (Ollama /embed or /v1/embeddings)."""
        if time.monotonic() < getattr(self, "_embedding_unavailable_until", 0.0):
            return None

        chosen_model = model or self.embedding_model or self.model
        if not model and not self.embedding_model:
            installed_models = self._last_health.get("models") if isinstance(self._last_health, dict) else None
            if isinstance(installed_models, list) and installed_models:
                embed_candidates = [
                    m for m in installed_models
                    if isinstance(m, str) and any(k in m.lower() for k in ("embed", "minilm", "bge", "nomic", "mxbai"))
                ]
                if embed_candidates:
                    chosen_model = embed_candidates[0]
                elif not any(k in str(chosen_model).lower() for k in ("embed", "minilm", "bge", "nomic", "mxbai")):
                    self._embedding_unavailable_until = time.monotonic() + 600.0
                    return None
            elif not any(k in str(chosen_model).lower() for k in ("embed", "minilm", "bge", "nomic", "mxbai")):
                # Chat models (e.g. qwen2.5:3b) on CPU take 15-45s per embedding call; use fast deterministic fallback
                return None

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

        self._embedding_unavailable_until = time.monotonic() + 300.0
        return None

    async def async_generate(
        self,
        prompt: str = "",
        system_prompt: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        timeout: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        images: list[str] | None = None,
    ) -> dict[str, Any]:
        """Send a prompt or message list to the local LLM and return structured output, tool calls, and metrics."""
        chosen_model = model or self.model
        req_timeout = timeout or self.timeout
        effective_max_tokens = max_tokens if max_tokens is not None else getattr(self, "max_tokens", DEFAULT_LOCAL_MAX_TOKENS)
        session = self._get_session()
        headers = self._get_headers()
        t0 = time.perf_counter()

        # Build message history
        if messages is not None:
            msg_list = [dict(m) for m in messages]
        else:
            msg_list = []
            if system_prompt:
                msg_list.append({"role": "system", "content": system_prompt})
            if prompt:
                msg_list.append({"role": "user", "content": prompt})

        # Process images for Ollama native format
        clean_images = [normalize_image_base64(img)[0] for img in images] if images else []
        if clean_images and msg_list:
            # Attach to the last user message
            for i in reversed(range(len(msg_list))):
                if msg_list[i].get("role") == "user":
                    existing = msg_list[i].get("images", [])
                    msg_list[i]["images"] = list(existing) + clean_images
                    break

        # Try Ollama /api/chat (skip if server was already identified as openai_compatible)
        known_provider = self._last_health.get("provider") if isinstance(self._last_health, dict) else None
        ollama_endpoint = f"{self.url}/api/chat"
        payload: dict[str, Any] = {
            "model": chosen_model,
            "messages": msg_list,
            "stream": False,
            "keep_alive": "15m",
            "options": {
                "temperature": temperature,
                "num_predict": effective_max_tokens,
                "num_ctx": 4096,
                "stop": ["<|im_end|>", "<|endoftext|>", "Observation:", "User:"],
            },
        }
        if tools:
            payload["tools"] = tools

        if known_provider != "openai_compatible":
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
                        if eval_count > 0:
                            self._record_inference_telemetry(chosen_model, tokens_per_sec, total_time)

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
                    if known_provider == "ollama" and resp.status not in (404, 405, 501):
                        err_text = await resp.text()
                        return {
                            "success": False,
                            "error": f"HTTP {resp.status}: {err_text[:200]}",
                            "model": chosen_model,
                            "total_duration_s": round(time.perf_counter() - t0, 2),
                        }
            except (asyncio.TimeoutError, TimeoutError):
                return {
                    "success": False,
                    "error": f"Local LLM request timed out after {int(req_timeout)}s",
                    "model": chosen_model,
                    "total_duration_s": round(time.perf_counter() - t0, 2),
                }
            except Exception as err:
                if known_provider == "ollama":
                    return {
                        "success": False,
                        "error": str(err),
                        "model": chosen_model,
                        "total_duration_s": round(time.perf_counter() - t0, 2),
                    }
                _LOGGER.debug("Ollama /api/chat attempt failed: %s; trying OpenAI format", err)

        # Fallback to OpenAI-compatible /v1/chat/completions
        try:
            # Format vision content for OpenAI compatibility if images are present
            openai_messages: list[dict[str, Any]] = []
            for m in msg_list:
                m_copy = dict(m)
                m_imgs = m_copy.pop("images", None)
                if m_imgs:
                    content_parts: list[dict[str, Any]] = [{"type": "text", "text": m_copy.get("content", "")}]
                    for img in m_imgs:
                        _, data_uri = normalize_image_base64(img)
                        content_parts.append({"type": "image_url", "image_url": {"url": data_uri}})
                    m_copy["content"] = content_parts
                openai_messages.append(m_copy)

            v1_endpoint = f"{self.url}/v1/chat/completions"
            v1_payload: dict[str, Any] = {
                "model": chosen_model,
                "messages": openai_messages,
                "temperature": temperature,
                "max_tokens": effective_max_tokens,
                "stream": False,
            }
            if tools:
                v1_payload["tools"] = tools

            async with session.post(
                v1_endpoint,
                json=v1_payload,
                headers=headers,
                timeout=ClientTimeout(total=req_timeout),
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
                    if completion_tokens > 0:
                        self._record_inference_telemetry(chosen_model, tokens_per_sec, total_time)

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
        self, tool_calls: list[dict[str, Any]], context: Any = None
    ) -> list[dict[str, Any]]:
        """Execute a structured autonomous tool plan against Home Assistant services with context propagation."""
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

            if name not in ALLOWED_TOOL_NAMES:
                if "." in name:
                    d, _ = name.split(".", 1)
                    if d not in ALLOWED_SERVICE_DOMAINS:
                        execution_results.append({
                            "tool": name,
                            "parameters": params,
                            "success": False,
                            "error": f"Domain '{d}' is not in the authorized service domains allowlist",
                            "duration_s": 0.0,
                        })
                        continue
                else:
                    execution_results.append({
                        "tool": name,
                        "parameters": params,
                        "success": False,
                        "error": f"Tool '{name}' is not in the authorized tool allowlist",
                        "duration_s": 0.0,
                    })
                    continue

            try:
                if name == "query_knowledge_base" and hasattr(self, "rag_manager") and self.rag_manager:
                    res_data = await self.rag_manager.async_query_knowledge(
                        query=params.get("query", ""),
                        limit=params.get("limit", 3),
                        category=params.get("category"),
                    )
                elif name == "inspect_backup_configuration":
                    item_name = params.get("item_name") or params.get("name", "")
                    item_type = params.get("item_type") or "script"
                    auto_mgr = getattr(self, "automation_manager", None)
                    if not auto_mgr and hasattr(self.hass, "data") and "otis_ai" in self.hass.data:
                        auto_mgr = getattr(self.hass.data["otis_ai"].get("coordinator"), "automation_manager", None)
                    if auto_mgr and hasattr(auto_mgr, "async_inspect_backups_for_item"):
                        res_data = await auto_mgr.async_inspect_backups_for_item(item_name, item_type)
                    else:
                        res_data = {"found": False, "error": "AutomationManager unavailable"}
                elif name == "call_ha_service":
                    domain = params.pop("domain", "")
                    service = params.pop("service", "")
                    sdata = params.pop("service_data", {}) or params
                    if domain not in ALLOWED_SERVICE_DOMAINS:
                        execution_results.append({
                            "tool": name,
                            "parameters": sdata,
                            "success": False,
                            "error": f"Domain '{domain}' is not in the authorized service domains allowlist",
                            "duration_s": 0.0,
                        })
                        continue
                    await self.hass.services.async_call(
                        domain, service, sdata, blocking=True, context=context
                    )
                    res_data = {"service": f"{domain}.{service}", "data": sdata}
                elif "." in name:
                    domain, service = name.split(".", 1)
                    await self.hass.services.async_call(
                        domain, service, params, blocking=True, context=context
                    )
                    res_data = {"service": name, "data": params}
                else:
                    await self.hass.services.async_call(
                        "otis_ai", name, params, blocking=True, context=context
                    )
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
        max_tokens: int | None = None,
        max_iterations: int = 3,
        auto_execute: bool = True,
        timeout: float | None = None,
        context: Any = None,
    ) -> dict[str, Any]:
        """Autonomous multi-turn tool-calling loop using local LLMs."""
        chosen_tools = tools if tools is not None else select_relevant_tools(prompt)
        effective_max_tokens = max_tokens if max_tokens is not None else getattr(self, "max_tokens", DEFAULT_LOCAL_MAX_TOKENS)
        default_sys = (
            "You are Otis AI, the ultimate smart home butler and co-pilot. "
            "You have direct access to smart home tools to inspect cameras, heal network nodes, "
            "pin or unpin devices on the floorplan, run sentinel audits, inspect backups, and control devices. "
            "When a user asks to find or restore an overwritten, missing, or broken automation or script from a backup, "
            "NEVER tell the user to manually extract or edit files. Always use the inspect_backup_configuration tool "
            "to retrieve the complete historical YAML and present it directly for co-pilot deployment. "
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
                max_tokens=effective_max_tokens,
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
            exec_results = await self.async_execute_tool_plan(tool_calls, context=context)
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

        bench_res = {
            "success": result.get("success", False),
            "model": result.get("model", target_model),
            "provider": result.get("provider", health.get("provider")),
            "tokens_per_second": result.get("tokens_per_sec", 0.0),
            "tokens_generated": result.get("tokens_generated", 0),
            "total_latency_seconds": total_time,
            "endpoint_health": health,
            "sample_output": result.get("response", result.get("error", "")),
            "timestamp": time.time(),
        }
        self._last_benchmark = bench_res
        return bench_res

    def _parse_vision_response(self, text: str) -> dict[str, Any]:
        """Parse structured detection, perimeter zone, and anomaly results from vision LLM response."""
        data: dict[str, Any] = {}
        cleaned = text.strip()

        # 1. Try JSON extraction from code block or raw JSON
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
            except Exception:
                data = {}
        if not data and cleaned.startswith("{") and cleaned.endswith("}"):
            try:
                data = json.loads(cleaned)
            except Exception:
                data = {}

        # 2. If valid JSON object found, extract and validate fields
        if isinstance(data, dict) and data:
            detected_objects = data.get("detected_objects", [])
            if not isinstance(detected_objects, list):
                detected_objects = [str(detected_objects)]
            detected_objects = [str(o).lower().strip() for o in detected_objects if o]

            perimeter_zone = str(data.get("perimeter_zone", "perimeter")).lower().strip()
            anomaly_detected = bool(data.get("anomaly_detected", False))
            anomaly_type = data.get("anomaly_type")
            if anomaly_type is not None:
                anomaly_type = str(anomaly_type).lower().strip()
                if anomaly_type in ("none", "null", ""):
                    anomaly_type = None

            severity = str(data.get("severity", "normal")).lower().strip()
            if severity not in ("normal", "low", "medium", "high", "critical"):
                severity = "medium" if anomaly_detected else "normal"

            try:
                confidence = float(data.get("confidence", 0.85))
                confidence = max(0.0, min(1.0, confidence))
            except (ValueError, TypeError):
                confidence = 0.85

            summary = str(data.get("summary") or "").strip()
            if not summary:
                summary = f"Visual audit: {len(detected_objects)} object(s) detected in {perimeter_zone}."

            recommended_action = data.get("recommended_action")
            if recommended_action:
                recommended_action = str(recommended_action).strip()
                if recommended_action.lower() in ("none", "null", ""):
                    recommended_action = None

            return {
                "detected_objects": detected_objects,
                "perimeter_zone": perimeter_zone,
                "anomaly_detected": anomaly_detected,
                "anomaly_type": anomaly_type,
                "severity": severity,
                "confidence": confidence,
                "summary": summary,
                "recommended_action": recommended_action,
            }

        # 3. Fallback heuristic parsing from unstructured text
        text_lower = cleaned.lower()
        detected_objects = []
        for obj in ("person", "vehicle", "car", "truck", "package", "animal", "dog", "cat", "bicycle"):
            if obj in text_lower:
                canonical = "vehicle" if obj in ("car", "truck") else obj
                if canonical not in detected_objects:
                    detected_objects.append(canonical)

        zone = "perimeter"
        for z in ("driveway", "porch", "front_door", "doorstep", "backyard", "yard", "gate", "garage", "patio"):
            if z in text_lower:
                zone = z
                break

        anomaly_detected = False
        anomaly_type = None
        severity = "normal"
        action = None

        if any(w in text_lower for w in ("intruder", "breach", "prowler", "trespassing", "break-in", "burglar")):
            anomaly_detected = True
            anomaly_type = "perimeter_breach"
            severity = "critical"
            action = "notify_security"
        elif any(w in text_lower for w in ("loiter", "suspicious", "unknown person", "nighttime motion", "unauthorized")):
            anomaly_detected = True
            anomaly_type = "loitering"
            severity = "high"
            action = "turn_on_floodlights"
        elif any(w in text_lower for w in ("open gate", "gate open", "door open", "ajar")):
            anomaly_detected = True
            anomaly_type = "open_gate"
            severity = "medium"
            action = "check_perimeter_gate"
        elif "package" in detected_objects or "package" in text_lower:
            anomaly_detected = False
            severity = "low"
            action = "log_delivery"

        summary = cleaned[:200] if cleaned else "Visual scan completed."

        return {
            "detected_objects": detected_objects,
            "perimeter_zone": zone,
            "anomaly_detected": anomaly_detected,
            "anomaly_type": anomaly_type,
            "severity": severity,
            "confidence": 0.70 if detected_objects else 0.50,
            "summary": summary,
            "recommended_action": action,
        }

    async def async_analyze_vision(
        self,
        image_bytes: bytes | None = None,
        image_base64: str | None = None,
        prompt: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        context: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Analyze an image or camera snapshot using a local multimodal vision LLM (Ollama or OpenAI-compatible).

        Performs object recognition, perimeter zone classification, and security anomaly detection.
        """
        t0 = time.perf_counter()

        # 1. Resolve raw base64 data
        resolved_b64 = image_base64
        if not resolved_b64 and image_bytes:
            if len(image_bytes) > 262144 and hasattr(self.hass, "async_add_executor_job"):
                resolved_b64 = await self.hass.async_add_executor_job(
                    lambda: base64.b64encode(image_bytes).decode("utf-8")
                )
            else:
                resolved_b64 = base64.b64encode(image_bytes).decode("utf-8")

        if not resolved_b64:
            return {
                "success": False,
                "error": "No image data provided for vision analysis",
                "detected_objects": [],
                "anomaly_detected": False,
                "severity": "normal",
                "confidence": 0.0,
            }

        # 2. Select appropriate vision model
        chosen_model = model
        if not chosen_model:
            if any(k in self.model.lower() for k in ("vision", "llava", "moondream", "vl", "minicpm")):
                chosen_model = self.model
            else:
                health = await self.async_health_check()
                models = health.get("models", [])
                vision_models = [
                    m for m in models
                    if isinstance(m, str) and any(k in m.lower() for k in ("vision", "llava", "moondream", "vl", "minicpm"))
                ]
                if vision_models:
                    chosen_model = vision_models[0]
                else:
                    chosen_model = DEFAULT_LOCAL_VISION_MODEL

        # 3. Construct perimeter anomaly prompt
        sys_prompt = system_prompt or (
            "You are Otis, an edge AI vision sentinel. You analyze real-time home security and perimeter camera snapshots. "
            "Examine the image thoroughly and return ONLY a valid JSON object with the following fields:\n"
            "{\n"
            '  "detected_objects": ["person", "vehicle", "package", "animal"],\n'
            '  "perimeter_zone": "driveway|porch|front_door|backyard|side_yard|perimeter|garage",\n'
            '  "anomaly_detected": true/false,\n'
            '  "anomaly_type": "loitering|perimeter_breach|open_gate|unattended_package|prowler|none",\n'
            '  "severity": "normal|low|medium|high|critical",\n'
            '  "confidence": 0.0 to 1.0,\n'
            '  "summary": "Concise natural language description of what is visible",\n'
            '  "recommended_action": "turn_on_floodlights|notify_security|sound_chime|log_delivery|none"\n'
            "}"
        )

        user_prompt = prompt or (
            "Analyze this camera snapshot for perimeter activity, persons, vehicles, deliveries, or safety anomalies."
        )

        # 4. Invoke LLM with image
        clean_b64, _ = normalize_image_base64(resolved_b64)
        gen_result = await self.async_generate(
            prompt=user_prompt,
            system_prompt=sys_prompt,
            model=chosen_model,
            images=[clean_b64],
            temperature=0.1,
            max_tokens=512,
            timeout=timeout or self.timeout,
        )

        if not gen_result.get("success"):
            return {
                "success": False,
                "error": gen_result.get("error", "Vision model inference failed"),
                "model": chosen_model,
                "detected_objects": [],
                "anomaly_detected": False,
                "severity": "normal",
                "confidence": 0.0,
                "total_duration_s": round(time.perf_counter() - t0, 2),
            }

        raw_response = gen_result.get("response", "").strip()

        # 5. Parse structured output
        parsed = self._parse_vision_response(raw_response)
        parsed["success"] = True
        parsed["model"] = chosen_model
        parsed["raw_response"] = raw_response
        parsed["tokens_per_sec"] = gen_result.get("tokens_per_sec", 0.0)
        parsed["total_duration_s"] = gen_result.get("total_duration_s", round(time.perf_counter() - t0, 2))
        parsed["provider"] = gen_result.get("provider", "ollama")

        return parsed

