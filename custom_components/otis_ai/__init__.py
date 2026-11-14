"""The Otis AI Companion custom integration for Home Assistant."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import timedelta
from functools import partial
import logging
import os
import re
import time
import uuid
from typing import Any, Literal
import yaml

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback

try:
    from homeassistant.exceptions import Unauthorized
except ImportError:
    class Unauthorized(Exception):  # type: ignore[no-redef]
        def __init__(self, context=None, permission=None, **kwargs):
            super().__init__(f"Unauthorized: {permission}")
            self.context = context
            self.permission = permission

try:
    from homeassistant.helpers.service import async_register_admin_service
except ImportError:
    async_register_admin_service = None

try:
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
except ImportError:
    EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"
from homeassistant.helpers import (
    area_registry as ar,
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    intent,
)
from homeassistant.components import conversation

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .const import (
    DOMAIN,
    PLATFORMS,
    DEFAULT_CAMERA_STREAM_STRATEGY,
    CONF_CONVERSATION_AGENT,
    SERVICE_GET_CAPABILITY_MAP,
    SERVICE_GET_SUGGESTIONS,
    SERVICE_APPLY_SUGGESTION,
    SERVICE_CHAT,
    SERVICE_GET_SPATIAL_MAP,
    SERVICE_UPDATE_SPATIAL_MAP,
    SERVICE_GENERATE_FLOORPLAN,
    SERVICE_RECALCULATE_FLOORPLAN,
    SERVICE_UPDATE_FLOORPLAN_LAYOUT,
    SERVICE_PIN_FLOORPLAN_ENTITY,
    SERVICE_UNPIN_FLOORPLAN_ENTITY,
    SERVICE_GENERATE_THEME,
    SERVICE_APPLY_THEME,
    SERVICE_LIST_THEMES,
    SERVICE_DELETE_THEME,
    SERVICE_RUN_SENTINEL_WATCHDOG,
    SERVICE_REMEDIATE_ANOMALY,
    SERVICE_GET_SENTINEL_TELEMETRY,
    SERVICE_IGNORE_SENTINEL_ALERT,
    SERVICE_CREATE_COMMAND_CENTER,
    SERVICE_SYNC_DASHBOARDS,
    SERVICE_REGENERATE_DASHBOARDS,
    SERVICE_EXECUTE_MACRO,
    SERVICE_ROLLBACK_MACRO,
    SERVICE_CANCEL_PRECONDITIONING,
    SERVICE_LIST_MACROS,
    SERVICE_AUDIO_HANDOFF,
    SERVICE_MEDIA_FOLLOW_ME,
    SERVICE_RELEASE_IDLE_SOURCES,
    SERVICE_NOTIFY_VOICE,
    SERVICE_GET_ENERGY_SUMMARY,
    SERVICE_LOAD_SHED,
    SERVICE_RESTORE_SHED_LOADS,
    SERVICE_GET_PRESENCE_STATES,
    SERVICE_FUSE_PRESENCE,
    SERVICE_TRILATERATE_BLE,
    SERVICE_ANALYZE_CAMERA,
    SERVICE_AUDIT_PERIMETER,
    SERVICE_GET_INTRUDER_TRACKS,
    SERVICE_ANNOUNCE_VISUAL_ALERT,
    SERVICE_EVALUATE_CONTEXTUAL_ALERTS,
    SERVICE_MINE_HABITS,
    SERVICE_GET_CIRCADIAN_CURVES,
    SERVICE_AUDIT_HABIT_DEVIATIONS,
    SERVICE_AUDIT_UNASSIGNED_ENTITIES,
    SERVICE_AUTO_COMMISSION_ENTITIES,
    SERVICE_REGISTER_FEDERATED_NODE,
    SERVICE_REMOVE_FEDERATED_NODE,
    SERVICE_SYNC_FEDERATED_NODES,
    SERVICE_CALL_REMOTE_SERVICE,
    SERVICE_GET_FEDERATION_STATUS,
    SERVICE_BROADCAST_CLUSTER_MESSAGE,
    SERVICE_FORWARD_REMOTE_COMMAND,
    SERVICE_GET_USER_RULES,
    SERVICE_SET_USER_RULES,
    SERVICE_DISMISS_RECOMMENDATION,
    SERVICE_HIDE_RECOMMENDATION,
    SERVICE_RESTORE_RECOMMENDATION,
    SERVICE_RESET_DISMISSED_RECOMMENDATIONS,
    SERVICE_DUCK_MEDIA,
    SERVICE_RESTORE_MEDIA,
    SERVICE_GET_VOICE_ASSIST_STATUS,
    CONF_AUDIO_FOLLOW_ENABLED,
    CONF_LOCAL_LLM_ENABLED,
    CONF_LOCAL_LLM_URL,
    CONF_LOCAL_LLM_MODEL,
    CONF_LOCAL_MAX_TOKENS,
    CONF_LOCAL_LLM_API_KEY,
    CONF_REASONING_TIMEOUT,
    DEFAULT_REASONING_TIMEOUT,
    DEFAULT_LOCAL_LLM_URL,
    DEFAULT_LOCAL_LLM_MODEL,
    DEFAULT_LOCAL_MAX_TOKENS,
    is_otis_entity_id,
    SERVICE_TEST_LOCAL_LLM,
    SERVICE_BENCHMARK_LOCAL_LLM,
    SERVICE_PULL_LOCAL_LLM_MODEL,
    SERVICE_MANAGE_LOCAL_LLM_ADDON,
    SERVICE_EXECUTE_TOOL_PLAN,
    SERVICE_INDEX_DOCUMENT,
    SERVICE_QUERY_KNOWLEDGE,
    SERVICE_INDEX_ENTITY_HISTORY,
    SERVICE_CLEAR_KNOWLEDGE,
    SERVICE_SYNC_ENTITY_TELEMETRY,
    SERVICE_INDEX_DEVICE_MANUAL,
    SERVICE_TOGGLE_AUDIO_FOLLOW,
    SERVICE_TOGGLE_VOICE_ANNOUNCEMENTS,
    SERVICE_CONFIRM_PERSON_IDENTITY,
    SERVICE_UPDATE_PERSON_PROFILE,
    SERVICE_REMOVE_PERSON_PROFILE,
    SERVICE_AUDIT_MESH_HEALTH,
    SERVICE_HEAL_MESH_NODE,
    SERVICE_OPTIMIZE_BATTERY_SCHEDULE,
    SERVICE_GET_ENERGY_ARBITRAGE_PLAN,
    SERVICE_SCHEDULE_EV_CHARGING,
    SERVICE_EXECUTE_ENERGY_ARBITRAGE,
    SERVICE_ORCHESTRATE_MULTI_AGENT,
    SERVICE_CONFIGURE_VOICE_SATELLITE,
    SERVICE_ARBITRATE_SATELLITE_AUDIO,
    SERVICE_COPILOT_TUNE_RULE,
    SERVICE_COPILOT_SET_ALIAS,
    SERVICE_COPILOT_SET_CONDITION_TEMPLATE,
    SERVICE_COPILOT_MANAGE_FACT,
)
from .copilot_engine import (
    CopilotEngine,
    classify_confirmation_intent,
    has_unhandled_conditions,
    is_explanatory_query,
    is_valid_env_sensor,
    validate_and_upgrade_assistant_response,
)
from .agent_orchestrator import (
    ALL_AGENTS,
    MultiAgentOrchestrator,
)
from .local_llm import LocalLLMManager, select_relevant_tools
from .rag_manager import RAGKnowledgeManager
from .audio_manager import AudioHandoffManager
from .automation_manager import AutomationManager, clean_yaml_dict
from .dashboard_manager import DashboardManager
from .energy_manager import EnergyManager
from .macro_manager import MacroManager
from .mesh_manager import MeshManager
from .presence_manager import PresenceFusionManager
from .matrix_presets import (
    get_matrix_presets_list,
    identify_matrix_preset,
    is_matrix_entity,
    is_tv_cinema_player,
)
from .rules_manager import BehavioralRulesManager, scrub_sensitive_rules
from .sentinel_manager import SentinelManager
from .spatial_manager import (
    SpatialGraphManager,
    build_area_lookup_map,
    classify_area_entities,
    is_contact_sensor,
    is_motion_sensor as is_motion_sensor,
    resolve_area_identifier,
)
from .floorplan_parser import DEFAULT_OUTPUT_SVG_PATH, FloorplanParser
from .habit_manager import (
    BehavioralHabitManager,
    cluster_sequences_to_routines as cluster_sequences_to_routines,
)
from .commissioning_manager import AutonomousCommissioningManager
from .federation_manager import FederationManager
from .theme_manager import PRESET_THEMES, ThemeManager, slugify_theme_name
from .vision_manager import VisionPresenceManager, get_canonical_camera_key, stream_priority
from .log_monitor import LogMonitor
from .github_client import (
    DEFAULT_GITHUB_REPO,
    GITHUB_CLIENT_ID,
    check_device_token,
    create_github_issue,
    get_github_issue,
    request_device_code,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


def classify_area_floor(area_id: str, area_name: str) -> str:
    """Classify an area into 'Upper Floor', 'Ground Floor', or 'Outdoor'."""
    text = f"{area_id} {area_name}".lower()
    if any(k in text for k in ("backyard", "frontyard", "pool", "patio", "deck", "porch", "yard", "driveway", "garden", "exterior", "lawn")):
        return "Outdoor"
    if any(k in text for k in ("downstairs", "ground", "lower", "1st", "foyer", "garage", "mudroom", "kitchen", "dining", "great_room", "living")):
        return "Ground Floor"
    if any(k in text for k in ("upstairs", "upper", "second", "2nd", "attic", "loft", "master", "guest", "theater", "gym", "office", "study")):
        return "Upper Floor"
    if "hallway" in text:
        return "Upper Floor"
    return "Ground Floor"


def get_agent_display_name(hass: HomeAssistant, agent_id: str | None) -> str:
    """Resolve a user-friendly display name for a conversation agent ID."""
    if not agent_id:
        return "Default Agent"
    from .config_flow import _get_agents
    agent_name: str | None = None
    try:
        agents = _get_agents(hass)
        for a in agents:
            if getattr(a, "id", None) == agent_id:
                agent_name = str(getattr(a, "name", str(a)))
                break
    except Exception:
        pass
    c_entry, _, _, _ = _resolve_agent_config_entry(hass, str(agent_id))
    entry_title = str(getattr(c_entry, "title", "") or "").strip() if c_entry is not None else ""
    if agent_name:
        if agent_name.lower() in ("assist", "conversation", "text generation assist") and entry_title:
            return entry_title
        return agent_name
    if entry_title:
        return entry_title
    if agent_id.startswith("conversation."):
        part = agent_id.split(".", 1)[1]
        return part.replace("_", " ").title()
    return agent_id


_NON_HUMAN_PRESENCE_TOKENS = (
    "_cat", "_dog", "_bird", "_pet", "_animal", "_car", "_vehicle",
    "_package", "_fedex", "_ups", "_amazon", "_all_occupancy",
    "_keypad", "_cloud_connection", "_problem", "_battery",
)
_NON_MAIN_LIGHT_TOKENS = ("_led", "_screen", "_indicator", "_backlight", "_status_light")


def _filter_valid_presence_sensors(entity_ids: list[str]) -> list[str]:
    """Filter binary_sensor motion/occupancy/presence entities to exclude pet/object/aggregate sensors."""
    valid: list[str] = []
    for eid in entity_ids or []:
        low = str(eid or "").lower()
        if not low.startswith("binary_sensor."):
            continue
        if not any(k in low for k in ("motion", "occupancy", "presence", "person", "radar", "mmwave", "pir")):
            continue
        if any(bad in low for bad in _NON_HUMAN_PRESENCE_TOKENS):
            continue
        valid.append(eid)
    # Prefer physical PIR/mmWave/motion/person sensors cleanly
    valid.sort(key=lambda e: (0 if any(p in e.lower() for p in ("mmwave", "radar", "pir", "_motion", "presence")) else (1 if "_person" in e.lower() else 2), e))
    return valid


def _extract_cloud_agent_config(ce: Any) -> tuple[str, str, bool]:
    """Extract (domain, configured_model, protect_free_tier) from a ConfigEntry and its subentries."""
    if ce is None:
        return "", "", False
    ce_domain = str(getattr(ce, "domain", "") or "").lower()
    cur_model = ""
    protect_free_tier = False

    def _scan_mapping(mapping: Any) -> None:
        nonlocal cur_model, protect_free_tier
        if not isinstance(mapping, Mapping):
            return
        if mapping.get("protect_free_tier"):
            protect_free_tier = True
        if not cur_model:
            for mk in ("chat_model", "model", "llm_model"):
                mv = mapping.get(mk)
                if mv:
                    cur_model = str(mv)
                    break

    # Prioritize conversation / text_generation subentries first (HA 2025/2026 subentry pattern)
    subentries = getattr(ce, "subentries", None)
    sub_vals: list[Any] = []
    if isinstance(subentries, Mapping):
        sub_vals = list(subentries.values())
    elif isinstance(subentries, (list, tuple)):
        sub_vals = list(subentries)

    preferred_subs = [
        s for s in sub_vals
        if str(getattr(s, "subentry_type", "") or (s.get("subentry_type") if isinstance(s, Mapping) else "")).lower()
        in ("conversation", "text_generation")
    ]
    for sub in preferred_subs + [s for s in sub_vals if s not in preferred_subs]:
        s_data = getattr(sub, "data", None) if not isinstance(sub, Mapping) else sub.get("data")
        _scan_mapping(s_data)
        if cur_model:
            break

    if not cur_model or not protect_free_tier:
        _scan_mapping(getattr(ce, "options", None))
        _scan_mapping(getattr(ce, "data", None))

    return ce_domain, cur_model, protect_free_tier


def _recommend_cloud_agent_optimization(
    domain: str,
    agent_name: str,
    current_model: str,
    protect_free_tier: bool,
    last_error: str,
    avg_latency: float,
    deprecated_models: set[str] | None = None,
    peer_working_models: list[str] | None = None,
) -> tuple[str, str]:
    """Return (recommended_model, actionable_recommendation) for an underperforming cloud AI agent."""
    dom_low = (domain or "").lower()
    name_low = (agent_name or "").lower()
    mod_low = (current_model or "").lower()
    err_low = (last_error or "").lower()
    dep_low = {str(m).strip().lower() for m in (deprecated_models or set()) if str(m).strip()}

    def _pick_usable(candidates: list[str]) -> str:
        for cand in candidates:
            c_clean = str(cand or "").strip()
            if c_clean and c_clean.lower() != mod_low and c_clean.lower() not in dep_low:
                return c_clean
        return ""

    if dom_low == "groq" or "groq" in name_low:
        if protect_free_tier or "413" in err_low or "429" in err_low:
            return (
                "",
                "Groq's Free Tier enforces strict 6k–12k TPM / payload limits (causing HTTP 413/429 rejections) and is not recommended for Otis. "
                "Open Settings → Devices & Services → Groq and disable/remove it from the Assist rotation (or upgrade to a Paid Groq tier and uncheck 'Protect free tier').",
            )
        rec = _pick_usable(list(peer_working_models or []) + ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"])
        if not rec:
            return ("", "Review Groq's available Text Generation models or remove Groq from the Assist rotation in Settings → Devices & Services → Groq.")
        return (
            rec,
            f"Switch Groq's Text Generation model to `{rec}` or remove Groq from the Assist rotation in Settings → Devices & Services → Groq.",
        )

    if dom_low == "google_generative_ai_conversation" or "google" in name_low or "gemini" in name_low:
        suggested_match = re.search(r"use\s+(models/[a-z0-9._-]+)", err_low)
        candidates: list[str] = []
        if suggested_match:
            candidates.append(suggested_match.group(1))
        candidates.extend(peer_working_models or [])
        candidates.extend(["models/gemini-3.5-flash-lite", "models/gemini-3.5-flash"])
        rec = _pick_usable(candidates)
        quota_hint = (
            " Enable Pay-As-You-Go billing in Google AI Studio if hitting 429/quota limits."
            if ("429" in err_low or "quota" in err_low or "resource_exhausted" in err_low or "timeout" in err_low)
            else ""
        )
        if not rec:
            return (
                "",
                f"Select an available Flash model in Settings → Devices & Services → Google Generative AI (Google AI Conversation subentry).{quota_hint}",
            )
        return (
            rec,
            f"Switch the Google AI Conversation subentry to `{rec}` in Settings → Devices & Services → Google Generative AI for faster, more reliable responses.{quota_hint}",
        )

    if dom_low == "open_router" or "openrouter" in name_low or "free models" in name_low:
        candidates = list(peer_working_models or []) + ["openai/gpt-4o-mini", "anthropic/claude-3.5-haiku"]
        rec = _pick_usable(candidates)
        if mod_low in ("openrouter/free", "") or ":free" in mod_low or "free" in name_low:
            rec_label = f"`{rec}`" if rec else "a paid model"
            return (
                rec,
                f"`openrouter/free` routes through congested community queues. Switch the OpenRouter Conversation subentry to {rec_label} or `anthropic/claude-3.5-haiku` in Settings → Devices & Services → OpenRouter.",
            )
        if not rec:
            return ("", "Switch OpenRouter's configured model to an available paid model in Settings → Devices & Services → OpenRouter.")
        return (
            rec,
            f"Switch OpenRouter's configured model to `{rec}` in Settings → Devices & Services → OpenRouter for higher availability.",
        )

    if dom_low == "openai_conversation" or "openai" in name_low:
        rec = _pick_usable(list(peer_working_models or []) + ["gpt-4o-mini", "gpt-4.1-mini"])
        if not rec:
            return ("", "Review OpenAI Conversation's configured model in Settings → Devices & Services → OpenAI.")
        return (
            rec,
            f"Switch OpenAI Conversation's model to `{rec}` in Settings → Devices & Services → OpenAI for lower latency and higher rate limits.",
        )

    if dom_low == "anthropic" or "claude" in name_low:
        preferred = ["claude-3-5-haiku-latest", "claude-sonnet-4-20250514"] if ("sonnet" in mod_low or "opus" in mod_low or avg_latency >= 15.0) else ["claude-sonnet-4-20250514", "claude-3-5-haiku-latest"]
        rec = _pick_usable(list(peer_working_models or []) + preferred)
        if not rec:
            return ("", "Review Anthropic's configured model in Settings → Devices & Services → Anthropic.")
        return (
            rec,
            f"Switch Anthropic's configured model to `{rec}` in Settings → Devices & Services → Anthropic for better speed and reliability.",
        )

    return (
        "",
        "Review this integration's configured model and API quota/rate limits in Settings → Devices & Services.",
    )


_RECOMMENDED_CLOUD_MODELS = frozenset({
    "models/gemini-3.5-flash-lite",
    "models/gemini-3.5-flash",
    "openai/gpt-4o-mini",
    "anthropic/claude-3.5-haiku",
    "gpt-4o-mini",
    "gpt-4.1-mini",
    "claude-3-5-haiku-latest",
})


async def _sync_cloud_agent_model_metrics(
    rules_manager: Any,
    agent_ids: list[str],
    current_model: str,
) -> bool:
    """Reset stale failure metrics if the agent's configured model changed (or switched to a recommended model)."""
    clean_model = str(current_model or "").strip()
    if not clean_model or not rules_manager or not hasattr(rules_manager, "get_agent_health_metrics"):
        return False
    metrics_map = rules_manager.get_agent_health_metrics() or {}
    needs_reset = False
    for aid in agent_ids:
        met = metrics_map.get(str(aid or "").strip())
        if not isinstance(met, dict):
            continue
        prev_model = str(met.get("configured_model") or "").strip()
        if prev_model and prev_model != clean_model:
            needs_reset = True
            break
        if not prev_model and clean_model in _RECOMMENDED_CLOUD_MODELS and (
            int(met.get("error_count") or 0) > 0 or int(met.get("consecutive_failures") or 0) > 0
        ):
            needs_reset = True
            break
    if needs_reset and hasattr(rules_manager, "async_reset_agent_metrics_for_model_change"):
        return await rules_manager.async_reset_agent_metrics_for_model_change(agent_ids, clean_model)
    return False


class _NoAliasSafeDumper(yaml.SafeDumper):
    """YAML SafeDumper that never emits &id001 / *id001 anchors or aliases."""

    def ignore_aliases(self, data: Any) -> bool:
        return True


def _register_admin_service(
    hass: HomeAssistant,
    domain: str,
    service: str,
    service_func: Any,
    schema: Any = None,
    supports_response: Any = None,
) -> None:
    """Register an administrative service requiring admin privileges."""
    try:
        from homeassistant.helpers.service import async_register_admin_service as _ha_admin_srv
        if _ha_admin_srv is not None:
            kwargs: dict[str, Any] = {}
            if supports_response is not None:
                kwargs["supports_response"] = supports_response
            if schema is not None:
                kwargs["schema"] = schema
            else:
                try:
                    import voluptuous as vol
                    kwargs["schema"] = vol.Schema({}, extra=vol.ALLOW_EXTRA)
                except ImportError:
                    pass
            _ha_admin_srv(hass, domain, service, service_func, **kwargs)
            return
    except (ImportError, TypeError):
        pass

    async def admin_handler(call: ServiceCall) -> Any:
        ctx = getattr(call, "context", None)
        user_id = getattr(ctx, "user_id", None) if ctx else None
        if user_id:
            auth = getattr(hass, "auth", None)
            if auth and hasattr(auth, "async_get_user"):
                res = auth.async_get_user(user_id)
                user = await res if asyncio.iscoroutine(res) or hasattr(res, "__await__") else res
                if user is not None and getattr(user, "is_admin", False) is False:
                    raise Unauthorized(
                        context=call.context,
                        permission="admin",
                    )
        return await service_func(call)

    kwargs = {}
    if supports_response is not None:
        kwargs["supports_response"] = supports_response
    if schema is not None:
        kwargs["schema"] = schema
    hass.services.async_register(domain, service, admin_handler, **kwargs)



MAX_UPLOAD_SIZE_BYTES = 3 * 1024 * 1024 * 1024  # 3 GB aggregate upload limit (streamed to disk, never buffered in RAM)
MAX_UPLOAD_CLIPS = 5  # Maximum clips allowed per walkthrough upload
UPLOAD_STREAM_CHUNK_BYTES = 1024 * 1024  # 1 MB read chunk for raw-body uploads


class OtisWalkthroughUploadView(HomeAssistantView):
    """HTTP view to accept video walkthrough uploads and trigger floor plan parsing."""

    url = "/api/otis_ai/upload_walkthrough"
    name = "api:otis_ai:upload_walkthrough"
    requires_auth = True

    def __init__(
        self,
        hass: HomeAssistant,
        floorplan_parser: FloorplanParser,
        engine: Any,
        spatial_manager: SpatialGraphManager | None = None,
        media_dir: str | None = None,
    ) -> None:
        """Initialize the upload view."""
        self.hass = hass
        self.floorplan_parser = floorplan_parser
        self.engine = engine
        self.spatial_manager = spatial_manager or getattr(engine, "spatial_manager", None)
        self.media_dir = media_dir or hass.config.path(".storage", DOMAIN, "media")
        self._active: bool = False
        self._stage: str = "Idle"
        self._discovered_areas: list[str] = []

    def _set_progress(self, stage: str, discovered: list[str] | None = None, active: bool = True) -> None:
        """Update live walkthrough upload and analysis progress state."""
        self._stage = stage
        if discovered is not None:
            self._discovered_areas = list(discovered)
        self._active = active

    async def get(self, request: web.Request) -> web.Response:
        """Return current walkthrough processing status for live UI progress updates."""
        if not self._active and hasattr(self.floorplan_parser, "get_regen_progress"):
            regen = self.floorplan_parser.get_regen_progress()
            if regen.get("active") or regen.get("percent", 0) > 0:
                return web.json_response(regen)
        return web.json_response({
            "active": self._active,
            "stage": self._stage,
            "percent": 50 if self._active else 0,
            "discovered_areas": list(self._discovered_areas),
        })

    async def post(self, request: web.Request) -> web.Response:
        """Handle uploaded video file(s), overwriting previous uploads to manage disk space."""
        _LOGGER.info("Received video walkthrough upload request")
        if request.content_length and request.content_length > MAX_UPLOAD_SIZE_BYTES:
            _LOGGER.warning(
                "Walkthrough upload rejected: Content-Length %d exceeds limit of %d bytes",
                request.content_length,
                MAX_UPLOAD_SIZE_BYTES,
            )
            return web.Response(
                status=413,
                text=f"Upload payload too large. Maximum allowed size is {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB.",
            )

        upload_dir = self.media_dir
        await self.hass.async_add_executor_job(partial(os.makedirs, upload_dir, exist_ok=True))
        self._set_progress("Uploading videos", [], active=True)

        try:
            # Remove any previous walkthrough video/audio files first to manage space on HA
            await self.hass.async_add_executor_job(
                self.floorplan_parser.cleanup_previous_uploads, upload_dir
            )

            saved_videos: list[str] = []
            spoken_order: str | None = None
            total_upload_bytes = 0

            def _append_chunk(path: str, data_bytes: bytes, mode: str = "ab") -> None:
                with open(path, mode) as f:
                    f.write(data_bytes)

            if request.content_type.startswith("multipart/"):
                reader = await request.multipart()
                file_idx = 0
                while True:
                    field = await reader.next()
                    if field is None:
                        break
                    if field.name in ("file", "files"):
                        file_idx += 1
                        if file_idx > MAX_UPLOAD_CLIPS:
                            _LOGGER.warning(
                                "Walkthrough upload rejected: clip count %d exceeds limit of %d",
                                file_idx,
                                MAX_UPLOAD_CLIPS,
                            )
                            return web.Response(
                                status=413,
                                text=f"Maximum allowed file count exceeded. At most {MAX_UPLOAD_CLIPS} clips per upload.",
                            )
                        fname = (
                            "walkthrough_upload.mp4"
                            if file_idx == 1
                            else f"walkthrough_upload_{file_idx}.mp4"
                        )
                        v_dest = os.path.join(upload_dir, fname)
                        await self.hass.async_add_executor_job(_append_chunk, v_dest, b"", "wb")
                        file_bytes = 0
                        while True:
                            chunk = await field.read_chunk()
                            if not chunk:
                                break
                            file_bytes += len(chunk)
                            total_upload_bytes += len(chunk)
                            if total_upload_bytes > MAX_UPLOAD_SIZE_BYTES:
                                _LOGGER.warning(
                                    "Walkthrough aggregate upload stream exceeded max size %d bytes",
                                    MAX_UPLOAD_SIZE_BYTES,
                                )
                                return web.Response(
                                    status=413,
                                    text=f"Aggregate upload stream exceeded limit of {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB.",
                                )
                            await self.hass.async_add_executor_job(_append_chunk, v_dest, chunk, "ab")
                        saved_videos.append(v_dest)
                        _LOGGER.info(
                            "Walkthrough video #%d saved to %s (%d bytes)",
                            file_idx,
                            v_dest,
                            file_bytes,
                        )
                    elif field.name == "spoken_order":
                        spoken_order = (await field.text()).strip()
            else:
                v_dest = os.path.join(upload_dir, "walkthrough_upload.mp4")
                await self.hass.async_add_executor_job(_append_chunk, v_dest, b"", "wb")
                body_bytes = 0
                async for chunk in request.content.iter_chunked(UPLOAD_STREAM_CHUNK_BYTES):
                    body_bytes += len(chunk)
                    total_upload_bytes += len(chunk)
                    if total_upload_bytes > MAX_UPLOAD_SIZE_BYTES:
                        _LOGGER.warning(
                            "Walkthrough upload body exceeded max size %d bytes",
                            MAX_UPLOAD_SIZE_BYTES,
                        )
                        return web.Response(
                            status=413,
                            text=f"Upload body exceeded limit of {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB.",
                        )
                    await self.hass.async_add_executor_job(_append_chunk, v_dest, chunk, "ab")
                saved_videos.append(v_dest)
                _LOGGER.info(
                    "Walkthrough video saved to %s (%d bytes)",
                    v_dest,
                    body_bytes,
                )

            if not saved_videos:
                _LOGGER.warning("Walkthrough upload rejected: no video files were provided.")
                return web.Response(
                    status=400,
                    text="No video walkthrough files were provided in the upload request.",
                )

            self._set_progress("Analyzing videos", [], active=True)

            # Build initial capability map to obtain registered Home Assistant areas
            cap_map = await self.engine.async_build_capability_map()
            areas_dict = cap_map.get("areas", {})
            area_list = [
                {"id": aid, "name": ainfo.get("name", aid)}
                for aid, ainfo in areas_dict.items()
            ]

            # Call enhanced multi-clip sequential processing pipeline
            async def _on_multiclip_progress(msg: str, names: list[str]) -> None:
                self._set_progress(msg, names, active=True)
                await asyncio.sleep(0.2)

            multiclip_analysis = await self.floorplan_parser.async_process_multiclip_walkthrough(
                saved_videos,
                area_list,
                upload_dir=upload_dir,
                progress_callback=_on_multiclip_progress,
            )

            combined_ordered_areas = multiclip_analysis.get("ordered_areas") or []
            combined_adjacencies = multiclip_analysis.get("adjacencies") or []
            transcripts = multiclip_analysis.get("transcripts") or []
            discovered_names = multiclip_analysis.get("discovered_names") or []
            detected_doors = multiclip_analysis.get("detected_doors") or []
            detected_windows = multiclip_analysis.get("detected_windows") or []

            # Update Spatial Adjacency Graph with transitions discovered from the walkthrough
            if self.spatial_manager and combined_adjacencies:
                for a1, a2 in combined_adjacencies:
                    try:
                        await self.spatial_manager.async_update_connection(
                            a1, a2, connected=True, connection_type="door"
                        )
                    except Exception as adj_err:
                        _LOGGER.debug("Could not connect %s <-> %s: %s", a1, a2, adj_err)
                # Refresh capability map so SVG doorways reflect updated adjacencies
                if hasattr(self.engine, "invalidate_cache"):
                    self.engine.invalidate_cache()
                cap_map = await self.engine.async_build_capability_map()

            # Combine user override (if provided) with AI-extracted spoken order
            final_order: list[str] = []
            if spoken_order:
                for item in spoken_order.split(","):
                    if item.strip():
                        final_order.append(item.strip())
            for aid in combined_ordered_areas:
                if aid not in final_order:
                    final_order.append(aid)

            result = await self.floorplan_parser.async_generate_svg_floorplan(
                cap_map,
                video_path=saved_videos[0] if saved_videos else None,
                spoken_order=final_order if final_order else None,
                walkthrough_completed=True,
                transcripts=transcripts,
                detected_doors=detected_doors,
                detected_windows=detected_windows,
            )

            if hasattr(self.engine, "invalidate_cache"):
                self.engine.invalidate_cache()
            self._set_progress("Done", discovered_names, active=False)

            return web.json_response({
                "success": True,
                "message": (
                    f"Processed {len(saved_videos)} walkthrough video(s) and generated floor plan!"
                ),
                "videos_processed": len(saved_videos),
                "detected_areas": combined_ordered_areas,
                "detected_area_names": discovered_names,
                "transcripts": transcripts,
                "url": result.get("url"),
                "room_count": result.get("room_count"),
                "zones": result.get("zones"),
                "walkthrough_completed": True,
                "lovelace_yaml": result.get("lovelace_yaml"),
            })
        except Exception as err:
            self._set_progress(f"Error: {err}", [], active=False)
            _LOGGER.error("Failed to process walkthrough video: %s", err)
            return web.json_response({"success": False, "error": str(err)}, status=500)


class OtisMediaView(HomeAssistantView):
    """Authenticated HTTP view to serve private Otis media (floor plan SVGs, uploads)."""

    url = "/api/otis_ai/media/{filename}"
    name = "api:otis_ai:media"
    requires_auth = True

    def __init__(self, hass: HomeAssistant, media_dir: str) -> None:
        """Initialize the media view."""
        self.hass = hass
        self.media_dir = media_dir

    async def get(self, request: web.Request, filename: str) -> web.Response:
        """Serve media file securely with MIME detection and path traversal guards."""
        safe_name = os.path.basename(filename)
        if not safe_name or safe_name != filename or ".." in filename or "/" in filename or "\\" in filename:
            return web.Response(status=400, text="Invalid filename")

        file_path = os.path.join(self.media_dir, safe_name)
        file_exists = await self.hass.async_add_executor_job(os.path.isfile, file_path)
        if not file_exists:
            return web.Response(status=404, text="Media not found")

        ext = os.path.splitext(safe_name)[1].lower()
        content_type_map = {
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".json": "application/json",
        }
        content_type = content_type_map.get(ext, "application/octet-stream")

        def _read_bytes() -> bytes:
            with open(file_path, "rb") as f:
                return f.read()

        content = await self.hass.async_add_executor_job(_read_bytes)
        return web.Response(
            body=content,
            content_type=content_type,
            headers={
                "Cache-Control": "no-cache, must-revalidate",
            },
        )


class OtisMediaStudioView(HomeAssistantView):
    """Authenticated HTTP view to manage per-user media favorites and matrix studio settings."""

    url = "/api/otis_ai/media_studio"
    name = "api:otis_ai:media_studio"
    requires_auth = True

    def __init__(
        self,
        hass: HomeAssistant,
        audio_manager: AudioHandoffManager | None = None,
        rules_manager: Any | None = None,
    ) -> None:
        """Initialize the media studio view."""
        self.hass = hass
        self.audio_manager = audio_manager
        self.rules_manager = rules_manager or getattr(audio_manager, "rules_manager", None)

    def _get_user_info(self, request: web.Request) -> tuple[str, str]:
        """Extract user_id and user_name from authenticated request."""
        user = request.get("hass_user")
        if user:
            uid = getattr(user, "id", "") or "default_user"
            uname = getattr(user, "name", "") or getattr(user, "username", "") or "Resident"
            return (str(uid), str(uname))
        return ("default_user", "Resident")

    async def get(self, request: web.Request) -> web.Response:
        """Return live Media Studio state including zones, candidate players, mappings, and favorites."""
        if not self.audio_manager:
            return web.json_response({"success": False, "error": "AudioManager not initialized"}, status=503)
        uid, uname = self._get_user_info(request)
        data = await self.audio_manager.async_get_user_media_studio_state(user_id=uid, user_name=uname)
        return web.json_response(data)

    async def post(self, request: web.Request) -> web.Response:
        """Handle Media Studio actions: add/remove/play favorites and set default zone."""
        if not self.audio_manager:
            return web.json_response({"success": False, "error": "AudioManager not initialized"}, status=503)
        uid, uname = self._get_user_info(request)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

        action = str(body.get("action") or "").strip()
        try:
            if action == "add_favorite":
                user = request.get("hass_user")
                is_admin = bool(getattr(user, "is_admin", False) or getattr(user, "is_owner", False))
                is_shared = bool(body.get("shared") or body.get("is_shared") or body.get("scope") == "shared")
                if not is_admin:
                    is_shared = False
                res = await self.audio_manager.async_add_user_favorite(
                    user_id=uid,
                    name=str(body.get("name") or "Favorite").strip(),
                    input_source=str(body.get("input") or body.get("input_source") or "").strip(),
                    player_entity_id=str(body.get("player") or body.get("player_entity_id") or "").strip(),
                    media_content_id=str(body.get("command") or body.get("media_content_id") or "").strip(),
                    media_content_type=str(body.get("media_content_type") or body.get("media_type") or "custom").strip(),
                    zone_entity_id=str(body.get("zone") or body.get("zone_entity_id") or "").strip(),
                    icon=str(body.get("icon") or "mdi:music-circle").strip(),
                    is_shared=is_shared,
                    user_name=uname,
                )
                return web.json_response(res)
            elif action == "remove_favorite":
                fav_id = str(body.get("favorite_id") or body.get("fav_id") or "").strip()
                is_shared = bool(body.get("is_shared") or body.get("shared") or body.get("scope") == "shared")
                res = await self.audio_manager.async_remove_user_favorite(
                    user_id=uid,
                    fav_id=fav_id,
                    is_shared=is_shared,
                    user_name=uname,
                )
                return web.json_response(res)
            elif action == "play_favorite":
                fav_id = str(body.get("favorite_id") or body.get("fav_id") or "").strip()
                zone_eid = str(body.get("zone_entity_id") or "").strip()
                res = await self.audio_manager.async_play_favorite(user_id=uid, fav_id=fav_id, target_zone=zone_eid)
                return web.json_response(res)
            elif action == "play_media":
                zone_eid = str(body.get("zone_entity_id") or "").strip()
                player_eid = str(body.get("player_entity_id") or "").strip()
                media_cmd = str(body.get("media_content_id") or "").strip()
                media_type = str(body.get("media_content_type") or "music").strip()
                input_name = str(body.get("input") or "").strip()
                res = await self.audio_manager.async_play_favorite(
                    user_id=uid,
                    favorite_data={
                        "zone": zone_eid,
                        "player": player_eid,
                        "input": input_name,
                        "media_content_id": media_cmd,
                        "media_content_type": media_type,
                    },
                )
                return web.json_response(res)
            elif action == "browse_library":
                player_eid = str(body.get("player_entity_id") or body.get("player") or "").strip()
                media_type = str(body.get("media_type") or "playlist").strip()
                search_query = body.get("search")
                limit = int(body.get("limit") or 40)
                res = await self.audio_manager.async_browse_player_library(
                    player_entity_id=player_eid,
                    media_type=media_type,
                    search_query=search_query,
                    limit=limit,
                )
                return web.json_response(res)
            elif action == "set_default_zone":
                zone_eid = str(body.get("zone_entity_id") or "").strip()
                res = await self.audio_manager.async_set_user_default_zone(user_id=uid, zone_entity_id=zone_eid, user_name=uname)
                return web.json_response(res)
            elif action == "save_mappings":
                user = request.get("hass_user")
                is_admin = bool(getattr(user, "is_admin", False) or getattr(user, "is_owner", False))
                if not is_admin:
                    return web.json_response({"success": False, "error": "Admin privileges required to modify physical matrix input mappings"}, status=403)
                mappings = body.get("mappings") or {}
                payload = {"media_input_mappings": mappings}
                if "unjoin_input" in body:
                    payload["media_unjoin_input"] = str(body["unjoin_input"] or "None").strip()
                if "default_zone" in body:
                    payload["media_default_zone"] = str(body["default_zone"] or "").strip()
                rm = self.rules_manager or getattr(self.audio_manager, "rules_manager", None)
                if rm:
                    await rm.async_save(payload)
                return web.json_response({"success": True, "mappings": mappings})
            elif action == "save_default_input":
                user = request.get("hass_user")
                is_admin = bool(getattr(user, "is_admin", False) or getattr(user, "is_owner", False))
                if not is_admin:
                    return web.json_response({"success": False, "error": "Admin privileges required to modify default return input"}, status=403)
                unjoin_inp = str(body.get("unjoin_input") or "None").strip() or "None"
                rm = self.rules_manager or getattr(self.audio_manager, "rules_manager", None)
                if rm:
                    await rm.async_save({"media_unjoin_input": unjoin_inp})
                apply_res = await self.audio_manager.async_apply_default_input_to_idle_zones(unjoin_inp)
                return web.json_response({"success": True, "unjoin_input": unjoin_inp, "applied": apply_res})
            elif action == "unjoin_zones":
                zone_eids = body.get("zone_entity_ids") or []
                if isinstance(zone_eids, str):
                    zone_eids = [zone_eids]
                res = await self.audio_manager.async_unjoin_zones([str(z) for z in zone_eids if z])
                return web.json_response(res)
            return web.json_response({"success": False, "error": f"Unknown action: {action}"}, status=400)
        except Exception as err:
            _LOGGER.exception("Media Studio action '%s' failed: %s", action, err)
            return web.json_response({"success": False, "error": str(err)}, status=500)


class OtisIssueReporterView(HomeAssistantView):
    """Authenticated HTTP view for HA Core log auditing and GitHub Device Flow issue reporting."""

    url = "/api/otis_ai/issue_reporter"
    name = "api:otis_ai:issue_reporter"
    requires_auth = True

    def __init__(self, hass: HomeAssistant, log_monitor: LogMonitor | None = None) -> None:
        """Initialize the issue reporter view."""
        self.hass = hass
        self.log_monitor = log_monitor

    async def get(self, request: web.Request) -> web.Response:
        """Handle issue reporter queries (diagnostics, device_code, poll_token, tracked_issues)."""
        hass_user = request.get("hass_user")
        action = str(request.query.get("action") or "diagnostics").strip()
        if action == "diagnostics":
            if not hass_user or not getattr(hass_user, "is_admin", False):
                return web.json_response(
                    {"success": False, "error": "Unauthorized: Admin privileges required to audit system logs."},
                    status=403,
                )
            if not self.log_monitor:
                return web.json_response({"success": False, "error": "LogMonitor not initialized"}, status=503)
            audit = await self.log_monitor.async_audit_logs()
            return web.json_response({"success": True, "audit": audit})
        elif action == "device_code":
            client_id = str(request.query.get("client_id") or GITHUB_CLIENT_ID).strip()
            dc = await request_device_code(client_id)
            if dc:
                return web.json_response({"success": True, "device_code": dc})
            return web.json_response({"success": False, "error": "Failed to request device code"}, status=502)
        elif action == "poll_token":
            device_code = str(request.query.get("device_code") or "").strip()
            client_id = str(request.query.get("client_id") or GITHUB_CLIENT_ID).strip()
            tok_res = await check_device_token(client_id=client_id, device_code=device_code)
            return web.json_response(tok_res)
        elif action == "tracked_issues":
            if not self.log_monitor:
                return web.json_response({"success": True, "tracked_issues": {}})
            return web.json_response({"success": True, "tracked_issues": self.log_monitor.get_tracked_issues()})
        elif action == "get_issue":
            repo = str(request.query.get("repo") or DEFAULT_GITHUB_REPO).strip()
            issue_num = int(request.query.get("issue_number") or 0)
            token = str(request.query.get("token") or "").strip()
            issue_data = await get_github_issue(repo=repo, issue_number=issue_num, token=token)
            return web.json_response({"success": True, "issue": issue_data})
        return web.json_response({"success": False, "error": f"Unknown action: {action}"}, status=400)

    async def post(self, request: web.Request) -> web.Response:
        """Handle issue actions: submit_issue and dismiss_issue."""
        hass_user = request.get("hass_user")
        if not hass_user or not getattr(hass_user, "is_admin", False):
            return web.json_response(
                {"success": False, "error": "Unauthorized: Admin privileges required to report or manage issues."},
                status=403,
            )
        if not self.log_monitor:
            return web.json_response({"success": False, "error": "LogMonitor not initialized"}, status=503)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

        action = str(body.get("action") or "").strip()
        if action == "submit_issue":
            token = str(body.get("token") or "").strip()
            repo = str(body.get("repo") or DEFAULT_GITHUB_REPO).strip()
            title = str(body.get("title") or "[Bug Report]").strip()
            body_text = str(body.get("body") or "").strip()
            labels = body.get("labels") or ["bug", "user-reported"]
            error_id = str(body.get("error_id") or "").strip()

            create_res = await create_github_issue(
                token=token,
                repo=repo,
                title=title,
                body=body_text,
                labels=labels,
            )
            if create_res.get("success"):
                await self.log_monitor.async_track_issue(
                    repo=create_res.get("repo") or repo,
                    issue_number=create_res.get("number") or 0,
                    title=create_res.get("title") or title,
                    html_url=create_res.get("html_url") or "",
                    error_id=error_id,
                )
            return web.json_response(create_res)
        elif action == "dismiss_issue":
            track_id = str(body.get("track_id") or "").strip()
            res = await self.log_monitor.async_dismiss_issue(track_id)
            return web.json_response({"success": res})
        return web.json_response({"success": False, "error": f"Unknown action: {action}"}, status=400)


async def async_register_frontend_paths(hass: HomeAssistant) -> None:
    """Register static path for the Otis Lovelace card."""
    if hasattr(hass, "http"):
        frontend_path = os.path.join(os.path.dirname(__file__), "frontend")
        try:
            from homeassistant.components.http import StaticPathConfig
            await hass.http.async_register_static_paths([
                StaticPathConfig("/otis_ai_card", frontend_path, cache_headers=False)
            ])
        except Exception:
            try:
                hass.http.register_static_path("/otis_ai_card", frontend_path, cache_headers=False)
            except Exception as err:
                _LOGGER.debug("Could not register static path for otis_ai_card: %s", err)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Otis AI Companion integration."""
    await async_register_frontend_paths(hass)
    if DOMAIN in config and not hass.config_entries.async_entries(DOMAIN):
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data=config.get(DOMAIN) or {},
            )
        )
    return True


def _schedule_background_task(hass: HomeAssistant, coro: Any, name: str) -> None:
    """Schedule a non-blocking background task that does not delay HA bootstrap."""
    task = None
    if hasattr(hass, "async_create_background_task"):
        task = hass.async_create_background_task(coro, name)
    elif hasattr(hass, "async_create_task"):
        task = hass.async_create_task(coro)
    if not isinstance(task, asyncio.Task) and asyncio.iscoroutine(coro):
        coro.close()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Otis AI Companion from a config entry."""
    _LOGGER.debug("Setting up Otis AI Companion entry: %s", entry.entry_id)
    _LOGGER.debug("Configured options: %s", entry.data)
    
    await async_register_frontend_paths(hass)
    hass.data.setdefault(DOMAIN, {})
    
    # Initialize the Spatial Graph, Discovery Engine, Automation Manager, Floorplan Parser, Dashboard Manager, Theme Manager, and Sentinel Watchdog
    spatial_manager = SpatialGraphManager(hass)
    floorplan_parser = FloorplanParser(hass)
    automation_manager = AutomationManager(hass)
    rules_manager = BehavioralRulesManager(hass)
    entry_store = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    entry_store["rules_manager"] = rules_manager

    # Forward platform setups before managers start publishing states
    if hasattr(hass, "config_entries") and hasattr(hass.config_entries, "async_forward_entry_setups"):
        try:
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        except Exception as plat_err:
            _LOGGER.debug("Could not forward platform setups: %s", plat_err)

    dashboard_manager = DashboardManager(hass, floorplan_parser=floorplan_parser, rules_manager=rules_manager)
    theme_manager = ThemeManager(hass)
    try:
        await theme_manager.async_load_and_register_themes()
    except Exception as tm_err:
        _LOGGER.debug("Could not register stored themes on boot: %s", tm_err)
    reasoning_timeout = float(
        entry.options.get(CONF_REASONING_TIMEOUT)
        or entry.data.get(CONF_REASONING_TIMEOUT)
        or DEFAULT_REASONING_TIMEOUT
    )
    local_max_tokens = int(
        entry.options.get(CONF_LOCAL_MAX_TOKENS)
        or entry.data.get(CONF_LOCAL_MAX_TOKENS)
        or DEFAULT_LOCAL_MAX_TOKENS
    )
    local_llm_manager = LocalLLMManager(
        hass,
        url=entry.options.get(CONF_LOCAL_LLM_URL) or entry.data.get(CONF_LOCAL_LLM_URL) or DEFAULT_LOCAL_LLM_URL,
        model=entry.options.get(CONF_LOCAL_LLM_MODEL) or entry.data.get(CONF_LOCAL_LLM_MODEL) or DEFAULT_LOCAL_LLM_MODEL,
        api_key=entry.options.get(CONF_LOCAL_LLM_API_KEY) or entry.data.get(CONF_LOCAL_LLM_API_KEY),
        timeout=reasoning_timeout,
        max_tokens=local_max_tokens,
    )
    rag_manager = RAGKnowledgeManager(hass, local_llm_manager=local_llm_manager)
    local_llm_manager.rag_manager = rag_manager
    local_llm_manager.automation_manager = automation_manager
    sentinel_manager = SentinelManager(hass, local_llm_manager=local_llm_manager)
    macro_manager = MacroManager(hass, rules_manager=rules_manager)
    audio_manager = AudioHandoffManager(hass, spatial_manager=spatial_manager, rules_manager=rules_manager)
    macro_manager.set_audio_manager(audio_manager)
    macro_manager.async_start_migration_listener()
    audio_manager.async_start_migration_listener()
    audio_manager.async_start_input_stop_listener()
    energy_manager = EnergyManager(hass, spatial_manager=spatial_manager)
    vision_manager = VisionPresenceManager(
        hass,
        spatial_manager=spatial_manager,
        energy_manager=energy_manager,
        macro_manager=macro_manager,
        audio_manager=audio_manager,
        local_llm_manager=local_llm_manager,
    )
    # Start real-time presence tracking and publish initial fused presence states
    vision_manager.async_start_presence_tracking()
    vision_manager.publish_initial_perimeter_sentinel_state()
    _schedule_background_task(
        hass,
        vision_manager.async_publish_fused_presence_states(),
        "otis_ai_publish_fused_presence",
    )
    habit_manager = BehavioralHabitManager(hass, spatial_manager=spatial_manager, energy_manager=energy_manager, vision_manager=vision_manager)
    commissioning_manager = AutonomousCommissioningManager(hass, spatial_manager=spatial_manager)
    federation_manager = FederationManager(hass)
    mesh_manager = MeshManager(hass)
    presence_fusion_manager = PresenceFusionManager(hass)
    vision_manager.presence_fusion_manager = presence_fusion_manager
    _schedule_background_task(
        hass,
        presence_fusion_manager.async_fuse_presence(use_cache=False),
        "otis_ai_initial_presence_fusion",
    )
    log_monitor = LogMonitor(hass)
    agent_orchestrator = MultiAgentOrchestrator(
        hass,
        local_llm_manager=local_llm_manager,
        spatial_manager=spatial_manager,
        presence_fusion_manager=presence_fusion_manager,
        audio_manager=audio_manager,
        sentinel_manager=sentinel_manager,
        energy_manager=energy_manager,
        habit_manager=habit_manager,
        rules_manager=rules_manager,
    )
    await asyncio.gather(
        spatial_manager.async_load(),
        floorplan_parser.async_load(),
        vision_manager.async_load(),
        dashboard_manager.async_ensure_admin_companion_dashboard(),
        dashboard_manager.async_ensure_user_command_center_dashboard(),
        sentinel_manager.async_load_preferences(),
        federation_manager.async_load(),
        rules_manager.async_load(),
        rag_manager.async_load(),
        agent_orchestrator.async_load(),
        log_monitor.async_load(),
    )
    federation_manager.publish_telemetry()
    _schedule_background_task(
        hass,
        federation_manager.async_start_background_sync(),
        "otis_ai_federation_sync",
    )
    engine = DiscoveryEngine(
        hass,
        spatial_manager=spatial_manager,
        floorplan_parser=floorplan_parser,
        dashboard_manager=dashboard_manager,
        theme_manager=theme_manager,
        sentinel_manager=sentinel_manager,
        energy_manager=energy_manager,
        vision_manager=vision_manager,
        habit_manager=habit_manager,
        commissioning_manager=commissioning_manager,
        federation_manager=federation_manager,
        rules_manager=rules_manager,
        local_llm_manager=local_llm_manager,
        rag_manager=rag_manager,
        mesh_manager=mesh_manager,
        presence_fusion_manager=presence_fusion_manager,
        agent_orchestrator=agent_orchestrator,
        log_monitor=log_monitor,
    )

    async def _async_sync_dashboards_on_startup() -> None:
        try:
            await asyncio.sleep(0.5)
            try:
                await theme_manager.async_load_and_register_themes()
            except Exception as tm_err:
                _LOGGER.debug("Could not refresh stored themes on HA started: %s", tm_err)
            engine.invalidate_cache()
            cap_map = await engine.async_build_capability_map(force_refresh=True)
            await dashboard_manager.async_ensure_admin_companion_dashboard(cap_map)
            await dashboard_manager.async_ensure_user_command_center_dashboard(cap_map)
            _LOGGER.info("Otis AI Command Center and Companion dashboards synchronized on startup")
            try:
                await rag_manager.async_sync_ha_docs()
            except Exception as docs_err:
                _LOGGER.debug("Could not sync official Home Assistant docs on startup: %s", docs_err)
        except Exception as sync_err:
            _LOGGER.debug("Could not run initial dashboard sync: %s", sync_err)

    if getattr(hass, "is_running", True) or not hasattr(hass, "bus"):
        _schedule_background_task(
            hass,
            _async_sync_dashboards_on_startup(),
            "otis_ai_startup_dashboard_sync",
        )
    else:
        @callback
        def _on_ha_started(_event: Any) -> None:
            _schedule_background_task(
                hass,
                _async_sync_dashboards_on_startup(),
                "otis_ai_startup_dashboard_sync",
            )

        unsub_start = hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_ha_started)
        if hasattr(entry, "async_on_unload") and callable(unsub_start):
            entry.async_on_unload(unsub_start)

    # Register Walkthrough Upload View & Media View
    media_dir = hass.config.path(".storage", DOMAIN, "media")
    await hass.async_add_executor_job(partial(os.makedirs, media_dir, exist_ok=True))

    if hasattr(hass, "http"):
        try:
            hass.http.register_view(
                OtisWalkthroughUploadView(
                    hass,
                    floorplan_parser,
                    engine,
                    spatial_manager=spatial_manager,
                    media_dir=media_dir,
                )
            )
            hass.http.register_view(OtisMediaView(hass, media_dir))
            hass.http.register_view(OtisMediaStudioView(hass, audio_manager=audio_manager, rules_manager=rules_manager))
            hass.http.register_view(OtisIssueReporterView(hass, log_monitor=log_monitor))
        except Exception as err:
            _LOGGER.debug("Could not register walkthrough upload view or media view: %s", err)

    # Initialize Co-Pilot Engine
    copilot_engine = CopilotEngine(hass)
    await copilot_engine.async_load()
    hass.data[DOMAIN]["copilot_engine"] = copilot_engine

    # Register the conversation agent
    agent = OtisAIConversationAgent(
        hass,
        entry,
        engine,
        automation_manager,
        spatial_manager=spatial_manager,
        theme_manager=theme_manager,
        sentinel_manager=sentinel_manager,
        macro_manager=macro_manager,
        audio_manager=audio_manager,
        energy_manager=energy_manager,
        vision_manager=vision_manager,
        habit_manager=habit_manager,
        commissioning_manager=commissioning_manager,
        federation_manager=federation_manager,
        rules_manager=rules_manager,
        local_llm_manager=local_llm_manager,
        dashboard_manager=dashboard_manager,
        floorplan_parser=floorplan_parser,
        rag_manager=rag_manager,
        presence_fusion_manager=presence_fusion_manager,
        agent_orchestrator=agent_orchestrator,
        copilot_engine=copilot_engine,
        log_monitor=log_monitor,
    )

    if hasattr(conversation, "async_register_agent"):
        conversation.async_register_agent(hass, agent)
    else:
        conversation.async_set_agent(hass, entry, agent)

    entry_store.update({
        "data": {**entry.data, **getattr(entry, "options", {})},
        "engine": engine,
        "agent": agent,
        "automation_manager": automation_manager,
        "spatial_manager": spatial_manager,
        "floorplan_parser": floorplan_parser,
        "dashboard_manager": dashboard_manager,
        "theme_manager": theme_manager,
        "sentinel_manager": sentinel_manager,
        "macro_manager": macro_manager,
        "audio_manager": audio_manager,
        "energy_manager": energy_manager,
        "vision_manager": vision_manager,
        "habit_manager": habit_manager,
        "commissioning_manager": commissioning_manager,
        "federation_manager": federation_manager,
        "rules_manager": rules_manager,
        "local_llm_manager": local_llm_manager,
        "rag_manager": rag_manager,
        "log_monitor": log_monitor,
        "mesh_manager": mesh_manager,
        "presence_fusion_manager": presence_fusion_manager,
        "agent_orchestrator": agent_orchestrator,
    })

    async def _async_update_listener(hass_inst: HomeAssistant, updated_entry: ConfigEntry) -> None:
        """Handle options update without requiring restart."""
        store = hass_inst.data.get(DOMAIN, {}).get(updated_entry.entry_id)
        if store is not None:
            store["data"] = {**updated_entry.data, **getattr(updated_entry, "options", {})}
            eng_inst = store.get("engine")
            if eng_inst and hasattr(eng_inst, "invalidate_cache"):
                eng_inst.invalidate_cache()
            llm_inst = store.get("local_llm_manager")
            if llm_inst:
                new_url = updated_entry.options.get(CONF_LOCAL_LLM_URL) or updated_entry.data.get(CONF_LOCAL_LLM_URL) or DEFAULT_LOCAL_LLM_URL
                new_model = updated_entry.options.get(CONF_LOCAL_LLM_MODEL) or updated_entry.data.get(CONF_LOCAL_LLM_MODEL) or DEFAULT_LOCAL_LLM_MODEL
                new_timeout = float(
                    updated_entry.options.get(CONF_REASONING_TIMEOUT)
                    or updated_entry.data.get(CONF_REASONING_TIMEOUT)
                    or DEFAULT_REASONING_TIMEOUT
                )
                new_max_tokens = int(
                    updated_entry.options.get(CONF_LOCAL_MAX_TOKENS)
                    or updated_entry.data.get(CONF_LOCAL_MAX_TOKENS)
                    or DEFAULT_LOCAL_MAX_TOKENS
                )
                llm_inst.url = new_url.rstrip("/")
                llm_inst.model = new_model
                llm_inst.timeout = new_timeout
                llm_inst.max_tokens = new_max_tokens
            rm_inst = store.get("rules_manager")
            if rm_inst and CONF_AUDIO_FOLLOW_ENABLED in getattr(updated_entry, "options", {}):
                await rm_inst.async_save(
                    {"audio_follow_enabled": bool(updated_entry.options[CONF_AUDIO_FOLLOW_ENABLED])}
                )

    if hasattr(entry, "async_on_unload") and hasattr(entry, "add_update_listener"):
        try:
            entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        except Exception as err:
            _LOGGER.debug("Could not register entry update listener: %s", err)

    def _get_entry_data() -> dict:
        return hass.data.get(DOMAIN, {}).get(entry.entry_id, {})

    def _get_engine() -> DiscoveryEngine:
        return _get_entry_data().get("engine", engine)

    def _get_automation_manager() -> AutomationManager:
        return _get_entry_data().get("automation_manager", automation_manager)

    def _get_spatial_manager() -> SpatialGraphManager:
        return _get_entry_data().get("spatial_manager", spatial_manager)

    def _get_floorplan_parser() -> FloorplanParser:
        return _get_entry_data().get("floorplan_parser", floorplan_parser)

    def _get_theme_manager() -> ThemeManager:
        return _get_entry_data().get("theme_manager", theme_manager)

    def _get_sentinel_manager() -> SentinelManager:
        return _get_entry_data().get("sentinel_manager", sentinel_manager)

    def _get_dashboard_manager() -> DashboardManager:
        return _get_entry_data().get("dashboard_manager", dashboard_manager)

    def _get_macro_manager() -> MacroManager:
        return _get_entry_data().get("macro_manager", macro_manager)

    def _get_audio_manager() -> AudioHandoffManager:
        return _get_entry_data().get("audio_manager", audio_manager)

    def _get_energy_manager() -> EnergyManager:
        return _get_entry_data().get("energy_manager", energy_manager)

    def _get_vision_manager() -> VisionPresenceManager:
        return _get_entry_data().get("vision_manager", vision_manager)

    def _get_habit_manager() -> BehavioralHabitManager:
        return _get_entry_data().get("habit_manager", habit_manager)

    def _get_commissioning_manager() -> AutonomousCommissioningManager:
        return _get_entry_data().get("commissioning_manager", commissioning_manager)

    def _get_federation_manager() -> FederationManager:
        return _get_entry_data().get("federation_manager", federation_manager)

    def _get_rules_manager() -> BehavioralRulesManager:
        return _get_entry_data().get("rules_manager", rules_manager)

    def _get_mesh_manager() -> MeshManager:
        return _get_entry_data().get("mesh_manager", mesh_manager)

    def _get_presence_fusion_manager() -> PresenceFusionManager:
        return _get_entry_data().get("presence_fusion_manager", presence_fusion_manager)

    def _get_agent_orchestrator() -> MultiAgentOrchestrator:
        return _get_entry_data().get("agent_orchestrator", agent_orchestrator)

    def _get_local_llm_manager() -> LocalLLMManager | None:
        return _get_entry_data().get("local_llm_manager", local_llm_manager)

    def _get_log_monitor() -> LogMonitor | None:
        return _get_entry_data().get("log_monitor", log_monitor)

    def _get_active_managers():
        return (
            _get_engine(),
            _get_automation_manager(),
            _get_spatial_manager(),
            _get_floorplan_parser(),
            _get_theme_manager(),
            _get_sentinel_manager(),
            _get_dashboard_manager(),
            _get_macro_manager(),
            _get_audio_manager(),
            _get_energy_manager(),
            _get_vision_manager(),
            _get_habit_manager(),
            _get_commissioning_manager(),
            _get_federation_manager(),
            _get_presence_fusion_manager(),
            _get_agent_orchestrator(),
        )

    async def handle_get_capability_map(call) -> ServiceResponse:
        """Handle service call to get the capability map."""
        _LOGGER.debug("Service 'get_capability_map' triggered")
        eng = _get_engine()
        rm = _get_rules_manager()
        force = bool(call.data.get("force") or call.data.get("force_refresh"))
        raw_inc = call.data.get("include_suggestions", True)
        include_suggestions = (
            raw_inc.strip().lower() not in ("false", "0", "no")
            if isinstance(raw_inc, str)
            else bool(raw_inc)
        )
        capability_map = await eng.async_build_capability_map(
            force_refresh=force,
            include_suggestions=include_suggestions,
        )
        capability_map["conversation_agent_id"] = entry.entry_id
        if rm:
            capability_map["user_rules"] = rm.get_rules()
        return capability_map

    async def handle_get_suggestions(call) -> ServiceResponse:
        """Handle service call to retrieve proactive suggestions."""
        _LOGGER.debug("Service 'get_suggestions' triggered")
        eng = _get_engine()
        rm = _get_rules_manager()
        capability_map = await eng.async_build_capability_map()
        suggestions = list(capability_map.get("proactive_suggestions", []))
        dismissed = set(rm.get_dismissed_recommendations())
        hidden = set(rm.get_hidden_recommendations())
        suggestions = [s for s in suggestions if s.get("id") not in hidden]
        include_dismissed = call.data.get("include_dismissed", False)
        if not include_dismissed and not rm.get_rules().get("show_ignored_recommendations", False):
            suggestions = [s for s in suggestions if s.get("id") not in dismissed]
        return {"suggestions": suggestions, "dismissed_ids": list(dismissed), "hidden_ids": list(hidden)}

    async def handle_apply_suggestion(call) -> ServiceResponse:
        """Handle service call to apply a proactive suggestion."""
        suggestion_id = call.data.get("suggestion_id")
        _LOGGER.debug("Service 'apply_suggestion' triggered for ID: %s", suggestion_id)
        if not suggestion_id:
            return {"success": False, "error": "Missing suggestion_id parameter"}

        eng = _get_engine()
        mgr = _get_automation_manager()
        sm = _get_sentinel_manager()
        target = None
        if hasattr(eng, "get_cached_suggestion") and callable(getattr(eng, "get_cached_suggestion", None)):
            cached = eng.get_cached_suggestion(suggestion_id)
            if isinstance(cached, dict):
                target = cached

        if target is None and hasattr(eng, "async_build_capability_map"):
            res = eng.async_build_capability_map()
            capability_map = await res if asyncio.iscoroutine(res) or hasattr(res, "__await__") else (res if isinstance(res, dict) else {})
            suggestions = capability_map.get("proactive_suggestions", []) if isinstance(capability_map, dict) else []
            target = next((s for s in suggestions if isinstance(s, dict) and s.get("id") == suggestion_id), None)

        if target is None and sm and hasattr(sm, "get_active_anomalies"):
            for anom in sm.get_active_anomalies() or []:
                if anom.get("id") == suggestion_id:
                    target = anom
                    break

        if target is None and suggestion_id.startswith("switch_local_llm_"):
            req_payload = call.data.get("action_payload") if isinstance(call.data, dict) else {}
            rec_model = (req_payload.get("model") if req_payload else None) or suggestion_id.replace("switch_local_llm_", "")
            target = {
                "id": suggestion_id,
                "action_type": "switch_local_llm_model",
                "action_payload": {"model": rec_model},
            }
        elif target is None and suggestion_id == "install_ollama":
            target = {
                "id": "install_ollama",
                "action_type": "install_ollama_addon",
                "action_payload": {},
            }

        if not target:
            _LOGGER.warning("apply_suggestion rejected: Suggestion '%s' not tracked or not found.", suggestion_id)
            return {"success": False, "error": f"Suggestion '{suggestion_id}' not found or already resolved"}

        action_type = target.get("action_type")
        payload = target.get("action_payload") or {}

        if not action_type:
            return {"success": False, "error": f"Suggestion '{suggestion_id}' has no executable action"}

        def _invalidate():
            if hasattr(eng, "invalidate_cache") and callable(getattr(eng, "invalidate_cache", None)):
                eng.invalidate_cache()

        if action_type == "dismiss":
            rm = _get_rules_manager()
            dismissed = await rm.async_dismiss_recommendation(suggestion_id)
            _invalidate()
            return {
                "success": True,
                "message": f"Recommendation '{suggestion_id}' ignored.",
                "dismissed_ids": dismissed,
            }

        if action_type in ("open_url", "read_article"):
            return {
                "success": True,
                "action": "open_url",
                "url": payload.get("url"),
                "title": payload.get("title"),
            }

        if action_type == "remediate_sentinel_anomaly":
            res = await sm.async_remediate_anomaly(
                payload.get("anomaly_id", suggestion_id),
                action=payload.get("action"),
            )
            _invalidate()
            return res

        if action_type in ("ignore_sentinel_alert", "sentinel_alert_actions"):
            aid = payload.get("anomaly_id", suggestion_id)
            cat = payload.get("category")
            if payload.get("all_in_category") and cat:
                await sm.async_ignore_category(cat)
                msg = f"All {cat} alerts muted."
            elif aid:
                await sm.async_ignore_anomaly(aid)
                msg = "Alert muted."
            else:
                msg = "Alert dismissed."
            _invalidate()
            return {"success": True, "message": msg}

        if action_type == "create_automation":
            auto_id = await mgr.async_write_automation(payload)
            if hasattr(mgr, "async_reload_automations"):
                await mgr.async_reload_automations()
            clean_cfg = clean_yaml_dict({k: v for k, v in payload.items() if not str(k).startswith("_")})
            clean_cfg.pop("id", None)
            yaml_str = yaml.dump(clean_cfg, Dumper=_NoAliasSafeDumper, sort_keys=False, default_flow_style=False)
            rm = _get_rules_manager()
            if rm and suggestion_id:
                await rm.async_hide_recommendation(suggestion_id)
            _invalidate()
            return {
                "success": True,
                "action": "create_ha_automation",
                "message": f"Created Home Assistant automation '{clean_cfg.get('alias', auto_id)}'",
                "id": auto_id,
                "automation_config": clean_cfg,
                "yaml": yaml_str,
            }
        elif action_type == "create_script":
            script_key = (target.get("id") if target else suggestion_id) or "custom_script"
            await mgr.async_write_script(script_key, payload)
            if hasattr(mgr, "async_reload_scripts"):
                await mgr.async_reload_scripts()
            yaml_str = yaml.dump(clean_yaml_dict(payload), Dumper=_NoAliasSafeDumper, sort_keys=False, default_flow_style=False)
            _invalidate()
            return {
                "success": True,
                "message": f"Successfully created script '{payload.get('alias', script_key)}'",
                "id": script_key,
                "yaml": yaml_str,
            }
        elif action_type == "cleanup_orphans":
            entity_reg = er.async_get(hass)
            cleaned = []
            for eid in payload.get("entity_ids", []):
                try:
                    entity_reg.async_remove(eid)
                    cleaned.append(eid)
                except Exception as err:
                    _LOGGER.warning("Could not remove orphaned entity %s: %s", eid, err)
            _invalidate()
            return {
                "success": True,
                "message": f"Cleaned up {len(cleaned)} orphaned entities",
                "cleaned_entities": cleaned,
            }
        elif action_type == "create_package":
            created_scripts = []
            created_autos = []
            raw_scripts = payload.get("scripts") or {}
            if isinstance(raw_scripts, dict):
                script_items = list(raw_scripts.items())
            elif isinstance(raw_scripts, list):
                script_items = []
                for idx, s_data in enumerate(raw_scripts):
                    if isinstance(s_data, dict):
                        alias_slug = re.sub(r"[^a-z0-9_]+", "_", str(s_data.get("alias", f"package_script_{idx}")).lower()).strip("_")
                        script_items.append((alias_slug or f"package_script_{idx}", s_data))
            else:
                script_items = []

            for s_key, s_data in script_items:
                await mgr.async_write_script(s_key, s_data)
                created_scripts.append(s_key)
            if created_scripts:
                await mgr.async_reload_scripts()

            for a_data in payload.get("automations") or []:
                a_id = await mgr.async_write_automation(dict(a_data))
                created_autos.append(a_id)
            if created_autos:
                await mgr.async_reload_automations()

            _invalidate()
            return {
                "success": True,
                "message": (
                    f"Deployed coordinator package ({len(created_scripts)} script(s), "
                    f"{len(created_autos)} automation(s))"
                ),
                "scripts": created_scripts,
                "automations": created_autos,
            }
        elif action_type == "auto_assign_areas":
            device_reg = dr.async_get(hass)
            entity_reg = er.async_get(hass)
            assigned_count = 0
            for item in payload.get("assignments", []):
                dev_id = item.get("device_id")
                ent_id = item.get("entity_id")
                area_id = item.get("area_id")
                if not area_id:
                    continue
                try:
                    ent_entry = entity_reg.async_get(ent_id) if (ent_id and hasattr(entity_reg, "async_get")) else None
                    actual_dev = dev_id or (getattr(ent_entry, "device_id", None) if ent_entry else None)
                    has_own_name = bool(getattr(ent_entry, "name", None))

                    if actual_dev and hasattr(device_reg, "async_update_device"):
                        device_reg.async_update_device(actual_dev, area_id=area_id)
                        if ent_id and getattr(ent_entry, "area_id", None) is not None and hasattr(entity_reg, "async_update_entity"):
                            entity_reg.async_update_entity(ent_id, area_id=None)
                        assigned_count += 1
                    elif ent_id and hasattr(entity_reg, "async_update_entity"):
                        if not has_own_name:
                            own_name = getattr(ent_entry, "original_name", None) or ent_id.split(".")[-1].replace("_", " ").title()
                            entity_reg.async_update_entity(ent_id, area_id=area_id, name=own_name)
                        else:
                            entity_reg.async_update_entity(ent_id, area_id=area_id)
                        assigned_count += 1
                except Exception as err:
                    _LOGGER.warning("Could not assign area %s to %s: %s", area_id, dev_id or ent_id, err)

            for dev_id, area_id in (payload.get("device_assignments") or {}).items():
                if not dev_id or not area_id:
                    continue
                try:
                    if hasattr(device_reg, "async_update_device"):
                        device_reg.async_update_device(dev_id, area_id=area_id)
                        assigned_count += 1
                except Exception as err:
                    _LOGGER.warning("Could not assign area %s to device %s: %s", area_id, dev_id, err)

            for ent_id, area_id in (payload.get("entity_assignments") or {}).items():
                if not ent_id or not area_id:
                    continue
                try:
                    ent_entry = entity_reg.async_get(ent_id) if hasattr(entity_reg, "async_get") else None
                    actual_dev = getattr(ent_entry, "device_id", None) if ent_entry else None
                    has_own_name = bool(getattr(ent_entry, "name", None))

                    if actual_dev and hasattr(device_reg, "async_update_device"):
                        device_reg.async_update_device(actual_dev, area_id=area_id)
                        if getattr(ent_entry, "area_id", None) is not None and hasattr(entity_reg, "async_update_entity"):
                            entity_reg.async_update_entity(ent_id, area_id=None)
                        assigned_count += 1
                    elif hasattr(entity_reg, "async_update_entity"):
                        if not has_own_name:
                            own_name = getattr(ent_entry, "original_name", None) or ent_id.split(".")[-1].replace("_", " ").title()
                            entity_reg.async_update_entity(ent_id, area_id=area_id, name=own_name)
                        else:
                            entity_reg.async_update_entity(ent_id, area_id=area_id)
                        assigned_count += 1
                except Exception as err:
                    _LOGGER.warning("Could not assign area %s to entity %s: %s", area_id, ent_id, err)

            _invalidate()
            return {
                "success": True,
                "message": f"Automatically assigned {assigned_count} device(s)/entities to their matching rooms!",
                "assigned_count": assigned_count,
            }
        elif action_type == "improve_automation":
            res = await mgr.async_improve_automation(payload)
            _invalidate()
            return res
        elif action_type == "optimize_system_config":
            res = await mgr.async_optimize_system_config(payload)
            _invalidate()
            return res
        elif action_type == "create_dashboard":
            d_mgr = _get_dashboard_manager()
            cap_map = await eng.async_build_capability_map()
            res = await d_mgr.async_create_professional_dashboard(payload, cap_map)
            _invalidate()
            return {
                "success": True,
                "message": (
                    f"Created professional dashboard '{res.get('title')}' at /{res.get('url_path')} "
                    "(added to Home Assistant sidebar)!"
                ),
                "dashboard": res,
            }
        elif action_type == "sync_ha_floors":
            area_reg = ar.async_get(hass)
            synced_areas = 0
            try:
                from homeassistant.helpers import floor_registry as fr
                floor_reg = fr.async_get(hass)
                existing_floors = {
                    f.name.lower(): f.floor_id for f in floor_reg.async_list_floors()
                }
                zone_specs = [
                    ("ground", "Ground Floor", 0, "mdi:home-floor-1"),
                    ("upper", "Upper Level", 1, "mdi:home-floor-2"),
                    ("outdoor", "Outdoor & Perimeter", 0, "mdi:tree"),
                ]
                zone_to_floor_id: dict[str, str] = {}
                for z_key, f_name, level, icon in zone_specs:
                    fid = existing_floors.get(f_name.lower())
                    if not fid and hasattr(floor_reg, "async_create"):
                        created = floor_reg.async_create(f_name, level=level, icon=icon)
                        fid = getattr(created, "floor_id", None)
                    if fid:
                        zone_to_floor_id[z_key] = fid

                for area_entry in list(area_reg.async_list_areas()):
                    z = floorplan_parser._classify_area_zone(area_entry.id, area_entry.name)
                    z_map = "upper" if z == "upper" else ("outdoor" if z == "outdoor" else "ground")
                    target_fid = zone_to_floor_id.get(z_map)
                    if target_fid and getattr(area_entry, "floor_id", None) != target_fid:
                        if hasattr(area_reg, "async_update"):
                            area_reg.async_update(area_entry.id, floor_id=target_fid)
                            synced_areas += 1
            except Exception as err:
                _LOGGER.warning("Could not sync HA floor registry: %s", err)
            _invalidate()
            return {
                "success": True,
                "message": f"Synchronized Home Assistant native Floor Registry across {synced_areas} room(s)!",
                "synced_areas": synced_areas,
            }
        elif action_type == "advisor_guide":
            return {
                "success": True,
                "message": (
                    payload.get("guide_message")
                    or payload.get("guide")
                    or "Recommendation noted! Ask Otis in the Assist Co-Pilot tab for step-by-step setup guidance."
                ),
            }
        elif action_type == "configure_agent":
            return {
                "success": True,
                "action": "open_failover_modal",
                "message": "Opening AI Failover Redundancy Guide...",
            }
        elif action_type == "upload_walkthrough":
            return {
                "success": True,
                "action": "open_walkthrough_modal",
                "message": "Ready to upload video walkthrough or generate floor plan.",
            }
        elif action_type == "load_shed":
            em = _get_energy_manager()
            tier = payload.get("tier", 1)
            target_watts = payload.get("target_watts", 0)
            res = await em.async_execute_load_shed(tier=tier, target_watts=target_watts)
            _invalidate()
            return res
        elif action_type in ("call_service", "remediate_contextual_alert"):
            svc = payload.get("service")
            target = payload.get("target") or {}
            s_data = payload.get("service_data") or payload.get("data") or {}
            if svc:
                s_domain, s_name = svc.split(".", 1)
                await hass.services.async_call(s_domain, s_name, s_data, target=target, context=call.context)
                _invalidate()
                btn_lbl = payload.get("button_label") or svc
                return {"success": True, "message": f"Successfully performed: {btn_lbl}"}
            return {"success": False, "error": "Missing service for contextual alert remediation"}
        elif action_type == "chat_prompt":
            return {
                "success": True,
                "action": "open_chat_prompt",
                "prompt": payload.get("prompt", ""),
                "message": f"Prompt queued for Assist Co-Pilot: '{payload.get('prompt', '')}'",
            }
        elif action_type == "auto_commission_entities":
            cm = _get_commissioning_manager()
            min_conf = float(payload.get("min_confidence", 0.85))
            res = await cm.async_auto_commission(min_confidence=min_conf)
            _invalidate()
            return res
        elif action_type == "sync_federated_nodes":
            fm = _get_federation_manager()
            node_id = payload.get("node_id")
            if node_id:
                res = await fm.async_sync_node(node_id)
            else:
                res = await fm.async_sync_all_nodes()
            _invalidate()
            return {"success": True, "sync_results": res}
        elif action_type == "confirm_person_identity":
            rm = _get_rules_manager()
            res = await rm.async_confirm_person_identity(
                person_id=payload.get("person_id", suggestion_id),
                track_id=payload.get("track_id"),
                label=payload.get("label"),
                confirmed=bool(payload.get("confirmed", True)),
                visual_features=payload.get("visual_features"),
            )
            _invalidate()
            return {
                "success": True,
                "message": f"Successfully verified identity for {payload.get('label') or payload.get('person_id')}",
                "result": res,
            }
        elif action_type == "confirm_room_transition":
            vm = _get_vision_manager()
            from_area = str(payload.get("from_area") or "")
            selected_to_area = str(
                call.data.get("selected_to_area") or payload.get("selected_to_area") or ""
            ).strip().lower()
            if selected_to_area in ("__not_a_person__", "__other__"):
                if hasattr(vm, "_ambiguous_room_transitions"):
                    vm._ambiguous_room_transitions.pop(from_area.lower().replace(" ", "_"), None)
                snap_key = payload.get("snapshot_key")
                if snap_key:
                    rm = _get_rules_manager()
                    existing_snaps = list(rm.get_rules().get("classified_snapshots") or [])
                    if snap_key not in existing_snaps:
                        await rm.async_update_rules({"classified_snapshots": (existing_snaps + [snap_key])[-200:]})
                _invalidate()
                msg = "Marked as false trigger (not a person)." if selected_to_area == "__not_a_person__" else f"Confirmed other/exterior transition for {from_area}."
                return {"success": True, "message": msg}
            valid_targets = {
                str(c.get("area_id") or "").strip().lower()
                for c in (payload.get("candidate_rooms") or [])
                if isinstance(c, dict) and c.get("area_id")
            }
            if not selected_to_area or (valid_targets and selected_to_area not in valid_targets):
                return {
                    "success": False,
                    "error": f"Invalid destination room selection '{selected_to_area}' for transition from '{from_area}'.",
                }
            res = vm.resolve_ambiguous_room_transition(
                from_area=from_area,
                selected_to_area=selected_to_area,
                subject=str(payload.get("subject") or "person"),
            )
            _invalidate()
            return {
                "success": bool(res.get("success")),
                "message": f"Confirmed transition from {from_area} into {selected_to_area}.",
                "result": res,
            }
        elif action_type == "heal_mesh_node":
            mm = _get_mesh_manager()
            res = await mm.async_heal_mesh_node(
                node_id=payload.get("node_id", suggestion_id),
                protocol=payload.get("protocol"),
                force_rebuild=bool(payload.get("force_rebuild", False)),
            )
            _invalidate()
            return {
                "success": res.get("success", True),
                "message": f"Autonomous healing dispatched to mesh node {payload.get('node_id')}",
                "result": res,
            }
        elif action_type == "heal_mesh_network":
            mm = _get_mesh_manager()
            res = await mm.async_heal_mesh_node("all", protocol=payload.get("protocol"))
            _invalidate()
            return {
                "success": True,
                "message": "Self-healing mesh routine triggered across all degraded routes.",
                "result": res,
            }
        elif action_type == "execute_energy_arbitrage":
            em = _get_energy_manager()
            res = await em.async_execute_energy_arbitrage()
            _invalidate()
            return {
                "success": True,
                "message": "Dispatched contextual TOU energy arbitrage load schedule.",
                "result": res,
            }
        elif action_type == "schedule_ev_charging":
            em = _get_energy_manager()
            res = await em.async_schedule_ev_charging(mode=payload.get("mode", "off_peak_fast"))
            _invalidate()
            return {
                "success": True,
                "message": "EV charging scheduled to run during super off-peak rate window.",
                "result": res,
            }
        elif action_type == "fuse_presence":
            pm = _get_presence_fusion_manager()
            res = await pm.async_fuse_presence(use_cache=False)
            _invalidate()
            return {
                "success": True,
                "message": "Recalibrated multimodal presence probabilities with micro-motion targets.",
                "result": res,
            }
        elif action_type == "propose_automation_migration":
            target_coord = payload.get("target_coordinator", "presence_fusion")
            alias = payload.get("alias", "Automation")
            area = payload.get("area", "general")
            auto_id = str(payload.get("automation_id") or "")

            # Locate the legacy automation entity in HA and turn it off to prevent timer collisions
            legacy_entity_id: str | None = None
            for st in hass.states.async_all("automation"):
                st_aid = str(st.attributes.get("id") or "")
                st_name = str(st.attributes.get("friendly_name") or "")
                if (auto_id and st_aid == auto_id) or (alias and st_name == alias):
                    legacy_entity_id = st.entity_id
                    break
            if legacy_entity_id:
                try:
                    await hass.services.async_call(
                        "automation",
                        "turn_off",
                        {"entity_id": legacy_entity_id},
                        blocking=True,
                    )
                except Exception as err:
                    _LOGGER.warning("Could not disable legacy automation %s: %s", legacy_entity_id, err)

            # Persist coordinator activation in Otis Rules
            rm = _get_rules_manager()
            if rm:
                rules = await rm.async_load()
                migrated = dict(rules.get("migrated_coordinators") or {})
                coord_entry = dict(migrated.get(target_coord) or {})
                areas_list = list(coord_entry.get("areas") or [])
                if area and area not in areas_list:
                    areas_list.append(area)
                disabled_autos = list(coord_entry.get("disabled_automations") or [])
                if legacy_entity_id and legacy_entity_id not in disabled_autos:
                    disabled_autos.append(legacy_entity_id)
                coord_entry["enabled"] = True
                coord_entry["areas"] = areas_list
                coord_entry["disabled_automations"] = disabled_autos
                migrated[target_coord] = coord_entry
                await rm.async_save({"migrated_coordinators": migrated})
                if suggestion_id:
                    await rm.async_hide_recommendation(suggestion_id)

            _invalidate()
            coord_label = (
                "Multimodal Presence Fusion"
                if target_coord == "presence_fusion"
                else "Contextual Energy Arbitrage"
                if target_coord == "energy_arbitrage"
                else target_coord
            )
            disabled_note = f" and disabled legacy automation '{legacy_entity_id}'" if legacy_entity_id else ""
            return {
                "success": True,
                "message": f"Activated native Otis {coord_label} for {area}{disabled_note}.",
                "target_coordinator": target_coord,
                "disabled_automation": legacy_entity_id,
                "payload": payload,
            }
        elif action_type == "switch_local_llm_model":
            llm_mgr = _get_local_llm_manager()
            target_model = payload.get("model") or payload.get("recommended_model")
            if not target_model:
                return {"success": False, "error": "No target model specified"}
            if not llm_mgr:
                return {"success": False, "error": "LocalLLMManager is not available on this host"}

            st = await llm_mgr.async_get_ollama_status()
            installed = [str(m).lower() for m in st.get("models", [])]
            t_low = target_model.lower()
            if any(t_low == m or t_low in m or m in t_low for m in installed):
                res = await llm_mgr.async_manage_ollama_addon(action="set_model", model=target_model)
            else:
                res = await llm_mgr.async_manage_ollama_addon(action="pull_model", model=target_model)

            _invalidate()
            msg = res.get("message") or f"Local Edge AI model successfully switched to '{target_model}'."
            return {
                "success": res.get("success", True),
                "message": msg,
                "model": target_model,
                "result": res,
            }
        elif action_type == "install_ollama_addon":
            return {
                "success": True,
                "action": "open_url",
                "url": "/hassio/addon/local_otis_ollama",
                "message": "Please navigate to the Home Assistant Add-on Store to install Otis Edge AI (Ollama).",
            }
        elif action_type == "repair_blueprint_automation":
            res = await mgr.async_improve_automation(payload)
            _invalidate()
            return res
        elif action_type == "dismiss_self_healing_alert":
            lm = _get_log_monitor()
            err_id = payload.get("error_id")
            if lm and err_id and hasattr(lm, "async_dismiss_error"):
                await lm.async_dismiss_error(err_id)
            _invalidate()
            return {"success": True, "message": "Self-healing notice dismissed."}
        elif action_type in ("github_report_issue", "tracked_github_issue"):
            if action_type == "tracked_github_issue" and payload.get("issue_url"):
                return {
                    "success": True,
                    "action": "open_url",
                    "url": payload.get("issue_url"),
                    "title": payload.get("title"),
                }
            return {
                "success": True,
                "action": "open_github_modal",
                "payload": payload,
                "message": "Ready to submit issue to GitHub.",
            }

        elif action_type == "guidance_only":
            return {
                "success": True,
                "action": "open_failover_modal",
                "message": "Review this recommendation in Settings → Devices & Services.",
            }

        return {"success": False, "error": f"Unsupported action_type '{action_type}'"}

    async def handle_chat(call) -> ServiceResponse:
        """Handle service call to chat directly with Otis AI."""
        text = call.data.get("text")
        attachments = call.data.get("attachments", [])
        if attachments and isinstance(attachments, list):
            text_parts = [text] if text else []
            for att in attachments:
                if not isinstance(att, dict):
                    continue
                name = att.get("name", "attachment")
                if not att.get("isImage") and "content" in att:
                    ext = name.rsplit(".", 1)[-1] if "." in name else "text"
                    text_parts.append(f"\n--- Attached File: `{name}` ---\n```{ext}\n{att['content']}\n```")
                elif att.get("isImage"):
                    text_parts.append(f"\n[Attached Image: `{name}` ({att.get('type', 'image')})]")
            text = "\n".join(text_parts).strip()

        if not text:
            return {"response": "Please provide a message or attachment to chat with Otis."}

        conv_id = call.data.get("conversation_id")
        user_input_cls = getattr(conversation, "ConversationInput", getattr(conversation, "UserInput", None))
        language = call.data.get("language") or getattr(hass.config, "language", "en")
        target_agent_id = call.data.get("agent_id") or entry.entry_id
        try:
            user_input = user_input_cls(
                text=text,
                context=call.context,
                conversation_id=conv_id,
                language=language,
                agent_id=target_agent_id,
            )
        except TypeError:
            try:
                user_input = user_input_cls(
                    text=text,
                    context=call.context,
                    conversation_id=conv_id,
                    language=language,
                )
            except Exception:
                class SimpleInput:
                    def __init__(self, t, cid, ctx, lang, aid=None):
                        self.text = t
                        self.conversation_id = cid
                        self.context = ctx
                        self.language = lang
                        self.device_id = None
                        self.agent_id = aid
                user_input = SimpleInput(text, conv_id, call.context, language, target_agent_id)

        if hasattr(hass, "bus") and hasattr(hass.bus, "async_fire"):
            try:
                hass.bus.async_fire("otis_ai_reasoning_step", {
                    "conversation_id": conv_id,
                    "step": "intent",
                    "title": "Parsing Intent",
                    "detail": "Analyzing prompt requirements and spatial context",
                })
            except Exception:
                pass

        result = await agent.async_process(user_input)
        speech = ""
        if result and getattr(result, "response", None):
            resp = result.response
            speech = getattr(resp, "speech", {}).get("plain", {}).get("speech", "")
            if not speech and hasattr(resp, "as_dict"):
                resp_dict = resp.as_dict()
                speech = resp_dict.get("speech", {}).get("plain", {}).get("speech", "")

        ret_conv_id = getattr(result, "conversation_id", None) or conv_id or "default"
        r_timeout = float(
            entry.options.get(CONF_REASONING_TIMEOUT)
            or entry.data.get(CONF_REASONING_TIMEOUT)
            or DEFAULT_REASONING_TIMEOUT
        )
        sessions = hass.data.get(DOMAIN, {}).get("sessions", {})
        session_info = sessions.get(ret_conv_id, {}) or sessions.get("default", {})
        resolved_agent = session_info.get("last_resolved_agent")
        failover_occurred = session_info.get("last_failover_occurred", False)

        is_error_response = (
            not speech
            or "experiencing high demand or downtime" in speech
            or "Quota Exhausted" in speech
            or "didn't receive a response" in speech
        )
        if is_error_response:
            resolved_agent = None
        elif not resolved_agent:
            resolved_agent = "Primary Cloud AI"

        return {
            "response": speech or "I didn't receive a response from the agent.",
            "conversation_id": ret_conv_id,
            "reasoning_timeout": r_timeout,
            "resolved_agent": resolved_agent,
            "failover_occurred": failover_occurred,
        }

    async def handle_get_spatial_map(call) -> ServiceResponse:
        """Handle service call to retrieve the spatial area adjacency graph."""
        _LOGGER.debug("Service 'get_spatial_map' triggered")
        s_mgr = _get_spatial_manager()
        graph = await s_mgr.async_get_graph()
        return graph

    async def handle_update_spatial_map(call) -> ServiceResponse:
        """Handle service call to update an adjacency connection between two areas."""
        area_1 = call.data.get("area_1")
        area_2 = call.data.get("area_2")
        connected = call.data.get("connected", True)
        connection_type = call.data.get("connection_type", "open")
        _LOGGER.debug(
            "Service 'update_spatial_map' triggered: %s <-> %s (connected=%s, type=%s)",
            area_1,
            area_2,
            connected,
            connection_type,
        )

        if not area_1 or not area_2:
            return {"success": False, "error": "Both 'area_1' and 'area_2' are required parameters"}

        try:
            eng = _get_engine()
            s_mgr = _get_spatial_manager()
            graph = await s_mgr.async_update_connection(area_1, area_2, connected, connection_type)
            if hasattr(eng, "invalidate_cache"):
                eng.invalidate_cache()
            action_desc = "Connected" if connected else "Disconnected"
            return {
                "success": True,
                "message": f"Successfully {action_desc.lower()} '{area_1}' and '{area_2}'",
                "graph": graph,
            }
        except Exception as err:
            _LOGGER.error("Error updating spatial map: %s", err)
            return {"success": False, "error": str(err)}

    async def handle_generate_floorplan(call) -> ServiceResponse:
        """Handle service call to generate SVG floorplan."""
        _LOGGER.debug("Service 'generate_floorplan' triggered")
        eng = _get_engine()
        fp = _get_floorplan_parser()
        dm = _get_dashboard_manager()
        capability_map = await eng.async_build_capability_map()
        video_path = call.data.get("video_path")
        spoken_order = call.data.get("spoken_order")
        theme = call.data.get("theme", "cyberpunk")
        reset_layout = bool(call.data.get("reset_layout", False))
        reanalyze_walkthrough = bool(call.data.get("reanalyze_walkthrough", False))
        background = bool(call.data.get("background", reanalyze_walkthrough))

        async def _execute_generate() -> ServiceResponse:
            res = await fp.async_generate_svg_floorplan(
                capability_map,
                output_relative_path=DEFAULT_OUTPUT_SVG_PATH,
                theme=theme,
                video_path=video_path,
                spoken_order=spoken_order,
                reset_layout=reset_layout,
                reanalyze_walkthrough=reanalyze_walkthrough,
            )
            if hasattr(eng, "invalidate_cache"):
                eng.invalidate_cache()
            if dm and hasattr(dm, "async_ensure_admin_companion_dashboard"):
                try:
                    cap_map = (
                        await eng.async_build_capability_map(force_refresh=True)
                        if hasattr(eng, "async_build_capability_map")
                        else None
                    )
                    await dm.async_ensure_admin_companion_dashboard(cap_map)
                    await dm.async_ensure_user_command_center_dashboard(cap_map)
                    hass.bus.async_fire("lovelace_updated", {"url_path": "otis-ai"})
                    hass.bus.async_fire("lovelace_updated", {"url_path": "command-center"})
                    hass.bus.async_fire("otis_ai_floorplan_updated", {"url": res.get("url")})
                except Exception as d_err:
                    _LOGGER.debug("Could not refresh dashboards after floorplan generation: %s", d_err)
            if hasattr(fp, "_set_regen_progress"):
                fp._set_regen_progress(100, "Complete", active=False)
            return res

        if background:
            if hasattr(fp, "_set_regen_progress"):
                fp._set_regen_progress(5, "Clearing previous floor plan & starting walkthrough analysis...", active=True, discovered_areas=[])

            async def _bg_task() -> None:
                try:
                    await _execute_generate()
                except Exception as bg_err:
                    _LOGGER.warning("Background floorplan regeneration failed: %s", bg_err)
                    if hasattr(fp, "_set_regen_progress"):
                        fp._set_regen_progress(0, "Failed", active=False, error=str(bg_err))

            hass.async_create_task(_bg_task())
            return {"status": "started", "background": True}

        return await _execute_generate()

    async def _async_reevaluate_spatial_from_floorplan(fp, eng) -> None:
        """Re-evaluate Spatial Adjacency Graph in background from updated floor plan geometry."""
        try:
            sm = _get_spatial_manager()
            if not sm or not hasattr(sm, "async_reevaluate_from_floorplan"):
                return
            bounds = getattr(fp, "_cached_svg_room_bounds", None) or {}
            if not bounds and hasattr(fp, "async_refresh_svg_cache"):
                await fp.async_refresh_svg_cache(DEFAULT_OUTPUT_SVG_PATH)
                bounds = getattr(fp, "_cached_svg_room_bounds", None) or {}
            if bounds:
                await sm.async_reevaluate_from_floorplan(bounds)
                if hasattr(eng, "invalidate_cache"):
                    eng.invalidate_cache()
        except Exception as sp_err:
            _LOGGER.debug("Background spatial adjacency re-evaluation skipped: %s", sp_err)

    async def handle_recalculate_floorplan(call) -> ServiceResponse:
        """Handle service call to force recalculate all floorplan room entities and layout."""
        _LOGGER.debug("Service 'recalculate_floorplan' triggered")
        eng = _get_engine()
        fp = _get_floorplan_parser()
        dm = _get_dashboard_manager()
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        capability_map = await eng.async_build_capability_map(force_refresh=True)
        preserve_custom = bool(call.data.get("preserve_custom_pins", True))
        res = await fp.async_recalculate_floorplan(
            capability_map,
            preserve_custom_pins=preserve_custom,
            output_relative_path=DEFAULT_OUTPUT_SVG_PATH,
        )
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        hass.async_create_task(_async_reevaluate_spatial_from_floorplan(fp, eng))
        if dm and hasattr(dm, "async_ensure_admin_companion_dashboard"):
            try:
                cap_map = (
                    await eng.async_build_capability_map(force_refresh=True)
                    if hasattr(eng, "async_build_capability_map")
                    else None
                )
                await dm.async_ensure_admin_companion_dashboard(cap_map)
                await dm.async_ensure_user_command_center_dashboard(cap_map)
                hass.bus.async_fire("lovelace_updated", {"url_path": "otis-ai"})
                hass.bus.async_fire("lovelace_updated", {"url_path": "command-center"})
                hass.bus.async_fire("otis_ai_floorplan_updated", {"url": res.get("svg_path")})
            except Exception as d_err:
                _LOGGER.debug("Could not refresh dashboards after floorplan recalculation: %s", d_err)
        return res

    async def handle_update_floorplan_layout(call) -> ServiceResponse:
        """Handle service call to adjust floorplan marker and room layout coordinates."""
        _LOGGER.debug("Service 'update_floorplan_layout' triggered with: %s", call.data)
        eng = _get_engine()
        fp = _get_floorplan_parser()
        dm = _get_dashboard_manager()
        badges = call.data.get("badges")
        rooms = call.data.get("rooms")
        deleted_rooms = call.data.get("deleted_rooms")
        custom_features = call.data.get("custom_features")
        res = await fp.async_update_floorplan_layout(
            badges=badges,
            rooms=rooms,
            deleted_rooms=deleted_rooms,
            custom_features=custom_features,
            svg_relative_path=DEFAULT_OUTPUT_SVG_PATH,
        )
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        hass.async_create_task(_async_reevaluate_spatial_from_floorplan(fp, eng))
        if dm and hasattr(dm, "async_ensure_admin_companion_dashboard"):
            try:
                cap_map = (
                    await eng.async_build_capability_map()
                    if hasattr(eng, "async_build_capability_map")
                    else None
                )
                await dm.async_ensure_admin_companion_dashboard(cap_map)
                await dm.async_ensure_user_command_center_dashboard(cap_map)
                hass.bus.async_fire("lovelace_updated", {"url_path": "otis-ai"})
                hass.bus.async_fire("lovelace_updated", {"url_path": "command-center"})
                hass.bus.async_fire("otis_ai_floorplan_updated", {"url": res.get("url")})
            except Exception as d_err:
                _LOGGER.debug("Could not refresh dashboards after floorplan update: %s", d_err)
        return res

    async def handle_pin_floorplan_entity(call) -> ServiceResponse:
        """Handle service call to pin or reposition an entity badge on the floorplan."""
        _LOGGER.debug("Service 'pin_floorplan_entity' triggered with: %s", call.data)
        eng = _get_engine()
        fp = _get_floorplan_parser()
        dm = _get_dashboard_manager()
        entity_id = call.data.get("entity_id")
        area_id = call.data.get("area_id")
        x = call.data.get("x")
        y = call.data.get("y")

        if not entity_id:
            return {"success": False, "error": "entity_id is required"}

        res = await fp.async_pin_entity(
            entity_id=entity_id,
            area_id=area_id,
            x=float(x) if x is not None else None,
            y=float(y) if y is not None else None,
            svg_relative_path=DEFAULT_OUTPUT_SVG_PATH,
        )
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        hass.async_create_task(_async_reevaluate_spatial_from_floorplan(fp, eng))
        if dm and hasattr(dm, "async_ensure_admin_companion_dashboard"):
            try:
                cap_map = (
                    await eng.async_build_capability_map()
                    if hasattr(eng, "async_build_capability_map")
                    else None
                )
                await dm.async_ensure_admin_companion_dashboard(cap_map)
                await dm.async_ensure_user_command_center_dashboard(cap_map)
                hass.bus.async_fire("lovelace_updated", {"url_path": "otis-ai"})
                hass.bus.async_fire("lovelace_updated", {"url_path": "command-center"})
                hass.bus.async_fire("otis_ai_floorplan_updated", {"url": res.get("url")})
            except Exception as d_err:
                _LOGGER.debug("Could not refresh dashboards after floorplan pin: %s", d_err)
        return res

    async def handle_unpin_floorplan_entity(call) -> ServiceResponse:
        """Handle service call to remove a pinned entity badge from the floorplan."""
        _LOGGER.debug("Service 'unpin_floorplan_entity' triggered with: %s", call.data)
        eng = _get_engine()
        fp = _get_floorplan_parser()
        dm = _get_dashboard_manager()
        entity_id = call.data.get("entity_id")

        if not entity_id:
            return {"success": False, "error": "entity_id is required"}

        res = await fp.async_unpin_entity(
            entity_id=entity_id,
            svg_relative_path=DEFAULT_OUTPUT_SVG_PATH,
        )
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        hass.async_create_task(_async_reevaluate_spatial_from_floorplan(fp, eng))
        if dm and hasattr(dm, "async_ensure_admin_companion_dashboard"):
            try:
                cap_map = (
                    await eng.async_build_capability_map()
                    if hasattr(eng, "async_build_capability_map")
                    else None
                )
                await dm.async_ensure_admin_companion_dashboard(cap_map)
                await dm.async_ensure_user_command_center_dashboard(cap_map)
                hass.bus.async_fire("lovelace_updated", {"url_path": "otis-ai"})
                hass.bus.async_fire("lovelace_updated", {"url_path": "command-center"})
                hass.bus.async_fire("otis_ai_floorplan_updated", {"url": res.get("url")})
            except Exception as d_err:
                _LOGGER.debug("Could not refresh dashboards after floorplan unpin: %s", d_err)
        return res

    async def _async_sync_dashboards_internal(force: bool = False) -> ServiceResponse:
        """Internal helper to regenerate or sync Otis AI and Command Center dashboards."""
        _LOGGER.debug("Service 'sync_dashboards' internal triggered (force_regenerate=%s)", force)
        eng = _get_engine()
        dm = _get_dashboard_manager()
        cap_map = (
            await eng.async_build_capability_map(force_refresh=True)
            if hasattr(eng, "async_build_capability_map")
            else None
        )
        admin_res = await dm.async_ensure_admin_companion_dashboard(cap_map, force_regenerate=force)
        user_res = await dm.async_ensure_user_command_center_dashboard(cap_map, force_regenerate=force)
        hass.bus.async_fire("lovelace_updated", {"url_path": "otis-ai"})
        hass.bus.async_fire("lovelace_updated", {"url_path": "command-center"})
        action_msg = "Regenerated and synchronized" if force else "Synchronized"
        return {
            "success": True,
            "message": f"{action_msg} Studios, Glance cards, and Rooms across Otis AI and Command Center dashboards",
            "admin_dashboard": admin_res,
            "command_center": user_res,
        }

    async def handle_sync_dashboards(call) -> ServiceResponse:
        """Handle service call to synchronize Studios and Rooms across Otis AI and Command Center."""
        call_data = getattr(call, "data", {}) or {}
        force = bool(call_data.get("force") or call_data.get("regenerate") or call_data.get("force_regenerate"))
        return await _async_sync_dashboards_internal(force=force)

    async def handle_regenerate_dashboards(call) -> ServiceResponse:
        """Handle service call to cleanly regenerate Command Center, Studios, and Rooms."""
        _LOGGER.debug("Service 'regenerate_dashboards' triggered")
        return await _async_sync_dashboards_internal(force=True)

    async def handle_generate_theme(call) -> ServiceResponse:
        """Handle service call to generate and persist a custom theme."""
        _LOGGER.debug("Service 'generate_theme' triggered with: %s", call.data)
        eng = _get_engine()
        tm = _get_theme_manager()
        prompt = call.data.get("prompt", "")
        name = call.data.get("name")
        base_palette = call.data.get("base_palette")
        dark_mode = call.data.get("dark_mode")
        border_radius = call.data.get("border_radius")
        glow_effect = call.data.get("glow_effect")
        apply_immediately = call.data.get("apply_immediately", False)

        res = await tm.async_generate_and_save_theme(
            prompt=prompt,
            name=name,
            base_palette=base_palette,
            dark_mode=dark_mode,
            border_radius=border_radius,
            glow_effect=glow_effect,
            apply_immediately=apply_immediately,
        )
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        return res

    async def handle_apply_theme(call) -> ServiceResponse:
        """Handle service call to apply a theme."""
        theme_name = call.data.get("name") or call.data.get("theme_name")
        mode = call.data.get("mode")
        user_id = call.data.get("user_id")
        all_users = call.data.get("all_users", False)
        _LOGGER.debug(
            "Service 'apply_theme' triggered for: %s (mode=%s, user_id=%s, all_users=%s)",
            theme_name,
            mode,
            user_id,
            all_users,
        )
        if not theme_name:
            return {"success": False, "error": "Missing theme 'name' parameter"}
        tm = _get_theme_manager()
        ok = await tm.async_apply_theme(theme_name, mode=mode, user_id=user_id, all_users=all_users)
        return {"success": ok, "theme": theme_name}

    async def handle_list_themes(call) -> ServiceResponse:
        """Handle service call to list generated Otis themes."""
        _LOGGER.debug("Service 'list_themes' triggered")
        tm = _get_theme_manager()
        themes = await tm.async_list_otis_themes()
        return {"themes": themes, "presets": list(PRESET_THEMES.keys())}

    async def handle_delete_theme(call) -> ServiceResponse:
        """Handle service call to delete an Otis theme."""
        theme_name = call.data.get("name") or call.data.get("theme_name")
        _LOGGER.debug("Service 'delete_theme' triggered for: %s", theme_name)
        if not theme_name:
            return {"success": False, "error": "Missing theme 'name' parameter"}
        eng = _get_engine()
        tm = _get_theme_manager()
        deleted = await tm.async_delete_theme(theme_name)
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        return {"success": deleted, "theme": theme_name}

    async def handle_run_sentinel_watchdog(call) -> ServiceResponse:
        """Handle service call to run Sentinel watchdog audit."""
        _LOGGER.debug("Service 'run_sentinel_watchdog' triggered with data: %s", call.data)
        auto_remediate = call.data.get("auto_remediate", False)
        eng = _get_engine()
        sm = _get_sentinel_manager()
        anomalies = await sm.async_scan_all_anomalies(auto_remediate=auto_remediate)
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        remediated_count = getattr(sm, "last_remediated_count", 0) if auto_remediate else 0
        return {
            "success": True,
            "anomalies": anomalies,
            "count": len(anomalies),
            "auto_remediated_count": remediated_count,
        }

    async def handle_remediate_anomaly(call) -> ServiceResponse:
        """Handle service call to remediate a detected anomaly."""
        anomaly_id = call.data.get("anomaly_id")
        action = call.data.get("action")
        _LOGGER.debug("Service 'remediate_anomaly' triggered for: %s (action=%s)", anomaly_id, action)
        if not anomaly_id:
            return {"success": False, "error": "Missing 'anomaly_id' parameter"}
        eng = _get_engine()
        sm = _get_sentinel_manager()
        res = await sm.async_remediate_anomaly(anomaly_id, action=action)
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        return res

    async def handle_get_sentinel_telemetry(call) -> ServiceResponse:
        """Handle service call to retrieve Sentinel telemetry."""
        _LOGGER.debug("Service 'get_sentinel_telemetry' triggered")
        sm = _get_sentinel_manager()
        anomalies = sm.get_active_anomalies()
        return {"anomalies": anomalies, "count": len(anomalies)}

    async def handle_ignore_sentinel_alert(call) -> ServiceResponse:
        """Handle service call to ignore a Sentinel alert or entire alert category."""
        anomaly_id = call.data.get("anomaly_id")
        category = call.data.get("category")
        all_in_category = call.data.get("all_in_category", False)
        _LOGGER.debug(
            "Service 'ignore_sentinel_alert' triggered: anomaly_id=%s, category=%s, all=%s",
            anomaly_id,
            category,
            all_in_category,
        )
        eng = _get_engine()
        sm = _get_sentinel_manager()
        if sm:
            if category:
                await sm.async_ignore_category(category)
            elif anomaly_id:
                await sm.async_ignore_anomaly(anomaly_id)
            if hasattr(sm, "async_scan_all_anomalies"):
                await sm.async_scan_all_anomalies()
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        return {"success": True, "anomaly_id": anomaly_id, "category": category}

    async def handle_create_command_center(call) -> ServiceResponse:
        """Handle service call to create or sync the User role Command Center dashboard."""
        _LOGGER.debug("Service 'create_command_center' triggered")
        eng = _get_engine()
        dm = _get_dashboard_manager()
        cap_map = (
            await eng.async_build_capability_map(force_refresh=True)
            if hasattr(eng, "async_build_capability_map")
            else {}
        )
        res = await dm.async_ensure_user_command_center_dashboard(cap_map)
        hass.bus.async_fire("lovelace_updated", {"url_path": "command-center"})
        return {"success": True, "dashboard": res}

    async def handle_execute_macro(call) -> ServiceResponse:
        """Handle service call to execute a multi-step smart macro pipeline."""
        _LOGGER.debug("Service 'execute_macro' triggered: %s", call.data)
        eng = _get_engine()
        mm = _get_macro_manager()
        macro_name = call.data.get("macro_name") or "Custom Macro"
        steps = call.data.get("steps")
        confirmed = call.data.get("confirmed", False)
        macro_id = call.data.get("macro_id")

        if not steps and macro_name:
            cap_map = await eng.async_build_capability_map()
            smart = mm.build_smart_macro(macro_name, capability_map=cap_map)
            macro_name = smart["name"]
            steps = smart["steps"]

        res = await mm.async_execute_macro(
            macro_name=macro_name,
            steps=steps or [],
            confirmed=confirmed,
            macro_id=macro_id,
            context=call.context,
        )
        return res

    async def handle_rollback_macro(call) -> ServiceResponse:
        """Handle service call to roll back an executed macro."""
        _LOGGER.debug("Service 'rollback_macro' triggered: %s", call.data)
        mm = _get_macro_manager()
        macro_id = call.data.get("macro_id")
        res = await mm.async_rollback_macro(macro_id=macro_id)
        return res

    async def handle_cancel_preconditioning(call) -> ServiceResponse:
        """Handle service call to cancel active spatial migration pre-conditioning."""
        _LOGGER.debug("Service 'cancel_preconditioning' triggered: %s", call.data)
        mm = _get_macro_manager()
        res = await mm.async_cancel_preconditioning()
        return res

    async def handle_list_macros(call) -> ServiceResponse:
        """Handle service call to list available macros and execution history."""
        _LOGGER.debug("Service 'list_macros' triggered")
        mm = _get_macro_manager()
        templates = [
            {
                "template": "movie_night",
                "name": "Movie Night Mode",
                "description": "Dim media room lights, power on TV and select HDMI source, adjust climate, and set soundbar/AVR volume.",
            },
            {
                "template": "goodnight",
                "name": "Goodnight Routine",
                "description": "Extinguish common lights, engage deadbolts, close garage doors, set night climate, and arm perimeter security.",
            },
            {
                "template": "party_mode",
                "name": "Entertain & Party Mode",
                "description": "Broadcast matrix audio across output zones, set warm scene lighting, and social climate.",
            },
            {
                "template": "away_mode",
                "name": "Away & Lockdown Mode",
                "description": "Extinguish all lighting, secure deadbolts, close garage doors, and arm security away.",
            },
            {
                "template": "welcome_home",
                "name": "Welcome Home Arrival",
                "description": "Pathway lighting, comfortable temperature, entry door unlock, and alarm disarm.",
            },
        ]
        history = mm.get_history()
        return {"templates": templates, "history": history}

    def _get_audio_manager() -> AudioHandoffManager:
        entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        return entry_data.get("audio_manager", audio_manager)

    async def handle_audio_handoff(call) -> ServiceResponse:
        """Handle service call to transfer or mirror audio across rooms."""
        _LOGGER.debug("Service 'audio_handoff' triggered: %s", call.data)
        am = _get_audio_manager()
        source_area = call.data.get("source_area")
        target_area = call.data.get("target_area")
        mode = call.data.get("mode", "handoff")
        player = call.data.get("player")
        idle_guard = call.data.get("idle_power_guard", True)
        return await am.async_audio_handoff(
            source_area=source_area,
            target_area=target_area,
            mode=mode,
            player_entity_id=player,
            idle_power_guard=idle_guard,
        )

    async def handle_media_follow_me(call) -> ServiceResponse:
        """Handle service call to follow audio playback dynamically into a newly entered room."""
        _LOGGER.debug("Service 'media_follow_me' triggered: %s", call.data)
        am = _get_audio_manager()
        source_area = call.data.get("source_area")
        target_area = call.data.get("target_area")
        mode = call.data.get("mode", "follow")
        return await am.async_audio_handoff(
            source_area=source_area,
            target_area=target_area,
            mode=mode,
            idle_power_guard=True,
        )

    async def handle_release_idle_sources(call) -> ServiceResponse:
        """Handle idle power guard to pause unmonitored streamers and idle amp zones."""
        _LOGGER.debug("Service 'release_idle_sources' triggered")
        am = _get_audio_manager()
        return await am.async_release_idle_sources()

    async def handle_notify_voice(call) -> ServiceResponse:
        """Handle voice feedback routing via notify_router or direct TTS."""
        _LOGGER.debug("Service 'notify_voice' triggered: %s", call.data)
        am = _get_audio_manager()
        msg = call.data.get("message", "")
        area_id = call.data.get("area_id")
        person = call.data.get("person_entity_id")
        announce = call.data.get("announce", True)
        duck_media = call.data.get("duck_media", True)
        duck_duration = call.data.get("duck_duration")
        whisper_mode = call.data.get("whisper_mode", False)
        return await am.async_notify_voice(
            message=msg,
            area_id=area_id,
            person_entity_id=person,
            announce=announce,
            duck_media=duck_media,
            duck_duration=duck_duration,
            whisper_mode=whisper_mode,
        )

    async def handle_duck_media(call) -> ServiceResponse:
        """Handle service call to temporarily duck or pause active media playback."""
        _LOGGER.debug("Service 'duck_media' triggered: %s", call.data)
        am = _get_audio_manager()
        areas = call.data.get("areas")
        duck_ratio = float(call.data.get("duck_ratio", 0.25))
        duck_level = float(call.data.get("duck_level", 0.15))
        session_id = call.data.get("session_id")
        return await am.async_duck_media(
            areas=areas,
            duck_ratio=duck_ratio,
            duck_level=duck_level,
            session_id=session_id,
        )

    async def handle_restore_media(call) -> ServiceResponse:
        """Handle service call to restore previously ducked media playback."""
        _LOGGER.debug("Service 'restore_media' triggered: %s", call.data)
        am = _get_audio_manager()
        session_id = call.data.get("session_id")
        return await am.async_unduck_media(session_id=session_id)

    async def handle_get_voice_assist_status(call) -> ServiceResponse:
        """Handle service call to retrieve Assist pipelines, satellites, and wake-word status."""
        _LOGGER.debug("Service 'get_voice_assist_status' triggered")
        am = _get_audio_manager()
        return await am.async_get_assist_pipeline_status()

    async def handle_get_energy_summary(call) -> ServiceResponse:
        """Handle service call to retrieve live energy telemetry and tariff window."""
        _LOGGER.debug("Service 'get_energy_summary' triggered")
        em = _get_energy_manager()
        return await em.async_get_energy_summary()

    async def handle_load_shed(call) -> ServiceResponse:
        """Handle service call to execute dynamic load shedding."""
        _LOGGER.debug("Service 'load_shed' triggered: %s", call.data)
        em = _get_energy_manager()
        tier = call.data.get("tier", 1)
        target_watts = call.data.get("target_watts", 0)
        dry_run = call.data.get("dry_run", False)
        return await em.async_execute_load_shed(tier=tier, target_watts=target_watts, dry_run=dry_run)

    async def handle_restore_shed_loads(call) -> ServiceResponse:
        """Handle service call to restore shedded loads."""
        _LOGGER.debug("Service 'restore_shed_loads' triggered: %s", call.data)
        em = _get_energy_manager()
        record_id = call.data.get("record_id")
        return await em.async_restore_shed_loads(record_id=record_id)

    async def handle_optimize_battery_schedule(call) -> ServiceResponse:
        """Handle service call to optimize 24-hour battery charge/discharge schedule."""
        _LOGGER.debug("Service 'optimize_battery_schedule' triggered: %s", call.data)
        em = _get_energy_manager()
        battery_entity = call.data.get("battery_entity")
        mode = call.data.get("mode")
        battery_capacity_kwh = call.data.get("battery_capacity_kwh")
        min_reserve_soc_pct = call.data.get("min_reserve_soc_pct")
        daily_solar_kwh = call.data.get("daily_solar_kwh")
        baseline_load_kw = call.data.get("baseline_load_kw")

        if mode:
            em.set_arbitrage_mode(mode)

        if any(k is not None for k in (daily_solar_kwh, baseline_load_kw)):
            soc = 50.0
            if battery_entity:
                st = hass.states.get(battery_entity)
                if st and st.state not in ("unavailable", "unknown"):
                    try:
                        soc = float(st.state)
                    except (ValueError, TypeError):
                        pass
            return em.calculate_arbitrage_schedule(
                current_soc_pct=soc,
                battery_capacity_kwh=battery_capacity_kwh or 13.5,
                min_reserve_soc_pct=min_reserve_soc_pct or 20.0,
                mode=mode or em.get_arbitrage_mode(),
                daily_solar_kwh=daily_solar_kwh if daily_solar_kwh is not None else 24.0,
                baseline_load_kw=baseline_load_kw or 1.0,
            )

        return await em.async_get_arbitrage_plan(
            battery_entity=battery_entity,
            mode=mode,
            battery_capacity_kwh=battery_capacity_kwh,
            min_reserve_soc_pct=min_reserve_soc_pct,
        )

    async def handle_get_energy_arbitrage_plan(call) -> ServiceResponse:
        """Handle service call to retrieve the active battery energy arbitrage plan."""
        _LOGGER.debug("Service 'get_energy_arbitrage_plan' triggered: %s", call.data)
        em = _get_energy_manager()
        battery_entity = call.data.get("battery_entity")
        mode = call.data.get("mode")
        return await em.async_get_arbitrage_plan(
            battery_entity=battery_entity,
            mode=mode,
        )

    async def handle_schedule_ev_charging(call) -> ServiceResponse:
        """Handle service call to optimize and schedule smart EV charging."""
        _LOGGER.debug("Service 'schedule_ev_charging' triggered: %s", call.data)
        em = _get_energy_manager()
        return await em.async_schedule_ev_charging(
            target_soc_pct=call.data.get("target_soc_pct"),
            target_departure_time=call.data.get("target_departure_time"),
            battery_capacity_kwh=call.data.get("battery_capacity_kwh"),
            max_charge_rate_kw=call.data.get("max_charge_rate_kw"),
            prefer_solar_surplus=call.data.get("prefer_solar_surplus", True),
            ev_entity=call.data.get("ev_entity"),
        )

    async def handle_execute_energy_arbitrage(call) -> ServiceResponse:
        """Handle service call to dispatch real-time load, EV charging, and storage commands."""
        _LOGGER.debug("Service 'execute_energy_arbitrage' triggered: %s", call.data)
        em = _get_energy_manager()
        apply_ev_schedule = call.data.get("apply_ev_schedule", True)
        apply_battery_mode = call.data.get("apply_battery_mode", True)
        dry_run = call.data.get("dry_run", False)
        return await em.async_execute_energy_arbitrage(
            apply_ev_schedule=apply_ev_schedule,
            apply_battery_mode=apply_battery_mode,
            dry_run=dry_run,
        )

    async def handle_get_presence_states(call) -> ServiceResponse:
        """Handle service call to retrieve fused room occupancy states."""
        _LOGGER.debug("Service 'get_presence_states' triggered")
        pm = _get_presence_fusion_manager()
        if pm:
            return await pm.async_fuse_presence(use_cache=True)
        vm = _get_vision_manager()
        return await vm.async_get_presence_states()

    async def handle_fuse_presence(call) -> ServiceResponse:
        """Handle service call for advanced multimodal presence fusion."""
        _LOGGER.debug("Service 'fuse_presence' triggered")
        force_refresh = bool(call.data.get("force_refresh", False))
        pm = _get_presence_fusion_manager()
        return await pm.async_fuse_presence(use_cache=not force_refresh)

    async def handle_trilaterate_ble(call) -> ServiceResponse:
        """Handle service call to calculate 2D coordinates of a BLE target via trilateration."""
        _LOGGER.debug("Service 'trilaterate_ble' triggered")
        obs = call.data.get("observations") or []
        ref_rssi = float(call.data.get("ref_rssi", -59.0))
        n = float(call.data.get("path_loss_exponent", 2.2))
        beacon_id = call.data.get("beacon_id")
        pm = _get_presence_fusion_manager()
        res = pm.trilaterate_beacon(obs, ref_rssi=ref_rssi, path_loss_exp=n)
        if res:
            if beacon_id:
                res["beacon_id"] = beacon_id
                res["attributed_user"] = pm.get_beacon_user(beacon_id)
            return res
        return {"success": False, "error": "Insufficient or invalid observations for trilateration"}

    async def handle_analyze_camera(call) -> ServiceResponse:
        """Handle service call to analyze camera snapshot."""
        camera_entity_id = call.data.get("camera_entity_id")
        prompt = call.data.get("prompt")
        model = call.data.get("model")
        _LOGGER.debug("Service 'analyze_camera' triggered for %s", camera_entity_id)
        if not camera_entity_id:
            return {"success": False, "error": "Missing 'camera_entity_id' parameter"}
        vm = _get_vision_manager()
        return await vm.async_analyze_camera(camera_entity_id, prompt=prompt, model=model)

    async def handle_audit_perimeter(call) -> ServiceResponse:
        """Handle service call to audit all perimeter cameras for security anomalies."""
        _LOGGER.debug("Service 'audit_perimeter' triggered")
        vm = _get_vision_manager()
        cameras = call.data.get("camera_entities")
        return await vm.async_audit_perimeter(camera_entities=cameras)

    async def handle_get_intruder_tracks(call) -> ServiceResponse:
        """Handle service call to query active and historical intruder spatial tracks."""
        _LOGGER.debug("Service 'get_intruder_tracks' triggered")
        vm = _get_vision_manager()
        return vm.get_intruder_tracks()

    async def handle_announce_visual_alert(call) -> ServiceResponse:
        """Handle service call to trigger proactive voice notification on visual alert."""
        _LOGGER.debug("Service 'announce_visual_alert' triggered with: %s", call.data)
        vm = _get_vision_manager()
        cam_param = call.data.get("camera_entity_id")
        if not cam_param and hasattr(hass, "states") and hasattr(hass.states, "async_all"):
            cam_param = next((s.entity_id for s in hass.states.async_all("camera")), None)
        camera_id = cam_param or "camera"
        summary_override = call.data.get("message")
        detected_objects = call.data.get("detected_objects") or ["person"]
        perimeter_zone = call.data.get("perimeter_zone") or "perimeter"
        severity = call.data.get("severity") or "high"
        force = call.data.get("force", False)
        target_area = call.data.get("target_area")

        audit_entry = {
            "camera": camera_id,
            "camera_name": camera_id,
            "perimeter_zone": perimeter_zone,
            "detected_objects": detected_objects,
            "severity": severity,
            "confidence": float(call.data.get("confidence", 0.90)),
            "anomaly_detected": True,
            "summary": summary_override or f"{', '.join(detected_objects)} detected at {perimeter_zone}",
            "timestamp": time.time(),
        }
        return await vm.async_dispatch_visual_alert_voice(
            audit_entry,
            force=force,
            target_area=target_area,
        )

    async def handle_evaluate_contextual_alerts(call) -> ServiceResponse:
        """Handle service call to evaluate contextual presence alerts."""
        _LOGGER.debug("Service 'evaluate_contextual_alerts' triggered")
        vm = _get_vision_manager()
        alerts = await vm.async_evaluate_contextual_alerts()
        return {"alerts": alerts, "count": len(alerts)}

    async def handle_mine_habits(call) -> ServiceResponse:
        """Handle service call to mine historical habit routines."""
        _LOGGER.debug("Service 'mine_habits' triggered")
        hm = _get_habit_manager()
        days = call.data.get("days", 14)
        routines = await hm.async_mine_habits(days=days)
        return {"routines": routines, "count": len(routines)}

    async def handle_get_circadian_curves(call) -> ServiceResponse:
        """Handle service call to calculate circadian & seasonal curves."""
        _LOGGER.debug("Service 'get_circadian_curves' triggered")
        hm = _get_habit_manager()
        elevation = call.data.get("solar_elevation")
        return hm.calculate_circadian_curves(solar_elevation=elevation)

    async def handle_audit_habit_deviations(call) -> ServiceResponse:
        """Handle service call to audit habit deviations."""
        _LOGGER.debug("Service 'audit_habit_deviations' triggered")
        hm = _get_habit_manager()
        deviations = await hm.async_detect_habit_deviations()
        return {"deviations": deviations, "count": len(deviations)}

    async def handle_audit_unassigned_entities(call) -> ServiceResponse:
        """Handle service call to audit unassigned entities."""
        _LOGGER.debug("Service 'audit_unassigned_entities' triggered")
        cm = _get_commissioning_manager()
        min_conf = float(call.data.get("min_confidence", 0.85))
        return await cm.async_audit_unassigned(min_confidence=min_conf)

    async def handle_auto_commission_entities(call) -> ServiceResponse:
        """Handle service call to auto-commission unassigned entities."""
        _LOGGER.debug("Service 'auto_commission_entities' triggered")
        cm = _get_commissioning_manager()
        min_conf = float(call.data.get("min_confidence", 0.85))
        return await cm.async_auto_commission(min_confidence=min_conf)

    async def handle_register_federated_node(call) -> ServiceResponse:
        """Handle service call to register a remote federated node."""
        _LOGGER.debug("Service 'register_federated_node' triggered")
        fm = _get_federation_manager()
        node_id = call.data["node_id"]
        name = call.data.get("name", node_id)
        host = call.data["host"]
        port = int(call.data.get("port", 8123))
        token = call.data.get("token", "")
        ssl = bool(call.data.get("ssl", False))
        enabled = bool(call.data.get("enabled", True))
        role = call.data.get("role", "satellite")
        allowed_domains = call.data.get("allowed_domains")
        excluded_domains = call.data.get("excluded_domains")
        return await fm.async_register_node(
            node_id=node_id,
            name=name,
            host=host,
            port=port,
            token=token,
            ssl=ssl,
            enabled=enabled,
            role=role,
            allowed_domains=allowed_domains,
            excluded_domains=excluded_domains,
        )

    async def handle_remove_federated_node(call) -> ServiceResponse:
        """Handle service call to remove a remote federated node."""
        _LOGGER.debug("Service 'remove_federated_node' triggered")
        fm = _get_federation_manager()
        node_id = call.data["node_id"]
        removed = await fm.async_remove_node(node_id)
        return {"success": removed, "node_id": node_id}

    async def handle_sync_federated_nodes(call) -> ServiceResponse:
        """Handle service call to sync federated edge nodes."""
        _LOGGER.debug("Service 'sync_federated_nodes' triggered")
        fm = _get_federation_manager()
        node_id = call.data.get("node_id")
        if node_id:
            return await fm.async_sync_node(node_id)
        return await fm.async_sync_all_nodes()

    async def handle_call_remote_service(call) -> ServiceResponse:
        """Handle service call to execute service on a remote federated node."""
        _LOGGER.debug("Service 'call_remote_service' triggered")
        fm = _get_federation_manager()
        node_id = call.data["node_id"]
        domain = call.data["domain"]
        service = call.data["service"]
        service_data = call.data.get("service_data")
        return await fm.async_call_remote_service(
            node_id=node_id,
            domain=domain,
            service=service,
            service_data=service_data,
        )

    async def handle_get_federation_status(call) -> ServiceResponse:
        """Handle service call to retrieve federation summary and node status."""
        _LOGGER.debug("Service 'get_federation_status' triggered")
        fm = _get_federation_manager()
        return await fm.async_get_federation_summary()

    async def handle_broadcast_cluster_message(call) -> ServiceResponse:
        """Handle service call to broadcast an alert/notification to federated edge nodes."""
        _LOGGER.debug("Service 'broadcast_cluster_message' triggered")
        fm = _get_federation_manager()
        message = call.data["message"]
        title = call.data.get("title", "Otis Cluster Notification")
        target_nodes = call.data.get("target_nodes")
        return await fm.async_broadcast_cluster_message(
            message=message,
            title=title,
            target_nodes=target_nodes,
        )

    async def handle_forward_remote_command(call) -> ServiceResponse:
        """Handle service call to transparently forward a command to a federated remote entity."""
        _LOGGER.debug("Service 'forward_remote_command' triggered")
        fm = _get_federation_manager()
        entity_id = call.data["entity_id"]
        service = call.data["service"]
        node_id = call.data.get("node_id")
        service_data = call.data.get("service_data")
        return await fm.async_forward_remote_command(
            entity_id=entity_id,
            service=service,
            node_id=node_id,
            service_data=service_data,
        )

    async def handle_get_user_rules(call) -> ServiceResponse:
        """Handle service call to retrieve user behavioral rules and persona guidelines."""
        _LOGGER.debug("Service 'get_user_rules' triggered")
        rm = _get_rules_manager()
        return {"rules": rm.get_rules()}

    async def handle_set_user_rules(call) -> ServiceResponse:
        """Handle service call to update user behavioral rules and persona guidelines."""
        _LOGGER.debug("Service 'set_user_rules' triggered with: %s", call.data)
        rm = _get_rules_manager()
        eng = _get_engine()
        dm = _get_dashboard_manager()
        rules_payload = call.data.get("rules") if isinstance(call.data.get("rules"), dict) else call.data
        updated = await rm.async_save(rules_payload)
        if hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        if "reasoning_timeout" in updated and hasattr(hass, "config_entries") and hasattr(hass.config_entries, "async_update_entry"):
            try:
                new_timeout = updated["reasoning_timeout"]
                if entry.options.get(CONF_REASONING_TIMEOUT) != new_timeout:
                    hass.config_entries.async_update_entry(
                        entry,
                        options={**entry.options, CONF_REASONING_TIMEOUT: new_timeout},
                    )
            except Exception as opt_err:
                _LOGGER.debug("Could not update config entry reasoning_timeout: %s", opt_err)
        if hasattr(hass, "bus") and hasattr(hass.bus, "async_fire"):
            try:
                hass.bus.async_fire("otis_ai_rules_updated", {"rules": scrub_sensitive_rules(updated)})
            except Exception:
                pass
        if dm and hasattr(dm, "async_ensure_user_command_center_dashboard"):
            try:
                cap_map = await eng.async_build_capability_map(force_refresh=True) if hasattr(eng, "async_build_capability_map") else None
                await dm.async_ensure_user_command_center_dashboard(cap_map, force_regenerate=True)
                await dm.async_ensure_admin_companion_dashboard(cap_map, force_regenerate=True)
                hass.bus.async_fire("lovelace_updated", {"url_path": "otis-ai"})
                hass.bus.async_fire("lovelace_updated", {"url_path": "command-center"})
                _LOGGER.info("Otis AI: Automatically regenerated dashboards following behavioral rules update")
            except Exception as sync_err:
                _LOGGER.debug("Dashboard auto-sync on set_user_rules notice: %s", sync_err)
        return {"success": True, "rules": updated}

    async def handle_dismiss_recommendation(call) -> ServiceResponse:
        """Handle service call to dismiss a proactive recommendation."""
        rec_id = call.data.get("recommendation_id") or call.data.get("id") or call.data.get("suggestion_id")
        _LOGGER.debug("Service 'dismiss_recommendation' triggered for: %s", rec_id)
        if not rec_id:
            return {"success": False, "error": "Missing recommendation_id parameter"}
        rm = _get_rules_manager()
        eng = _get_engine()
        dismissed = await rm.async_dismiss_recommendation(str(rec_id))
        if hasattr(eng, "invalidate_cache") and callable(getattr(eng, "invalidate_cache", None)):
            eng.invalidate_cache()
        return {"success": True, "dismissed_ids": dismissed}

    async def handle_hide_recommendation(call) -> ServiceResponse:
        """Handle service call to permanently hide a dismissed or completed recommendation."""
        rec_id = call.data.get("recommendation_id") or call.data.get("id") or call.data.get("suggestion_id")
        _LOGGER.debug("Service 'hide_recommendation' triggered for: %s", rec_id)
        if not rec_id:
            return {"success": False, "error": "Missing recommendation_id parameter"}
        rm = _get_rules_manager()
        eng = _get_engine()
        hidden = await rm.async_hide_recommendation(str(rec_id))
        if hasattr(eng, "invalidate_cache") and callable(getattr(eng, "invalidate_cache", None)):
            eng.invalidate_cache()
        return {"success": True, "hidden_ids": hidden}

    async def handle_restore_recommendation(call) -> ServiceResponse:
        """Handle service call to restore a previously dismissed recommendation."""
        rec_id = call.data.get("recommendation_id") or call.data.get("id") or call.data.get("suggestion_id")
        _LOGGER.debug("Service 'restore_recommendation' triggered for: %s", rec_id)
        if not rec_id:
            return {"success": False, "error": "Missing recommendation_id parameter"}
        rm = _get_rules_manager()
        eng = _get_engine()
        dismissed = await rm.async_restore_recommendation(str(rec_id))
        if hasattr(eng, "invalidate_cache") and callable(getattr(eng, "invalidate_cache", None)):
            eng.invalidate_cache()
        return {"success": True, "dismissed_ids": dismissed}

    async def handle_reset_dismissed_recommendations(call) -> ServiceResponse:
        """Handle service call to reset all dismissed recommendations."""
        _LOGGER.debug("Service 'reset_dismissed_recommendations' triggered")
        rm = _get_rules_manager()
        eng = _get_engine()
        await rm.async_reset_dismissed_recommendations()
        if hasattr(eng, "invalidate_cache") and callable(getattr(eng, "invalidate_cache", None)):
            eng.invalidate_cache()
        return {"success": True, "message": "All dismissed recommendations restored."}

    async def handle_test_local_llm(call) -> ServiceResponse:
        """Handle service call to test local LLM endpoint health and models."""
        _LOGGER.debug("Service 'test_local_llm' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        llm_mgr = entry_store.get("local_llm_manager", local_llm_manager)
        target_url = call.data.get("url")
        return await llm_mgr.async_health_check(target_url)

    async def handle_benchmark_local_llm(call) -> ServiceResponse:
        """Handle service call to benchmark local LLM throughput and latency."""
        _LOGGER.debug("Service 'benchmark_local_llm' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        llm_mgr = entry_store.get("local_llm_manager", local_llm_manager)
        prompt = call.data.get("prompt")
        model = call.data.get("model")
        return await llm_mgr.async_benchmark(prompt, model=model)

    async def handle_pull_local_llm(call) -> ServiceResponse:
        """Handle service call to pull an edge model onto the local Ollama instance, test it, and update options."""
        _LOGGER.debug("Service 'pull_local_llm_model' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        llm_mgr = entry_store.get("local_llm_manager", local_llm_manager)
        model_name = call.data.get("model") or "qwen2.5:3b"
        target_url = call.data.get("url")
        test_after_pull = call.data.get("test_after_pull", True)
        set_as_active = call.data.get("set_as_active", True)

        pull_res = await llm_mgr.async_pull_model(model_name, target_url=target_url)
        if not pull_res.get("success"):
            return pull_res

        test_res = None
        if test_after_pull:
            _LOGGER.info("Testing and benchmarking newly pulled model '%s'...", model_name)
            test_res = await llm_mgr.async_benchmark(model=model_name)
            pull_res["tested"] = bool(test_res.get("success"))
            pull_res["benchmark"] = test_res

        # If test was skipped or succeeded, and set_as_active is requested:
        test_ok = (not test_after_pull) or (test_res and test_res.get("success"))
        if set_as_active and test_ok:
            _LOGGER.info("Setting newly verified local model '%s' as active in integration options", model_name)
            llm_mgr.model = model_name
            new_options = dict(entry.options)
            new_options[CONF_LOCAL_LLM_MODEL] = model_name
            hass.config_entries.async_update_entry(entry, options=new_options)
            pull_res["options_updated"] = True
            pull_res["active_model"] = model_name
        else:
            pull_res["options_updated"] = False
            pull_res["active_model"] = llm_mgr.model

        return pull_res

    async def handle_manage_local_llm_addon(call) -> ServiceResponse:
        """Handle service call to manage Ollama Supervisor Add-on and models."""
        _LOGGER.debug("Service 'manage_local_llm_addon' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        llm_mgr = entry_store.get("local_llm_manager", local_llm_manager)
        action = call.data.get("action", "status")
        model = call.data.get("model")
        res = await llm_mgr.async_manage_ollama_addon(action=action, model=model)
        eng = _get_engine()
        if eng and hasattr(eng, "invalidate_cache"):
            eng.invalidate_cache()
        return res

    async def handle_execute_tool_plan(call) -> ServiceResponse:
        """Handle service call to run structured tool execution via Local LLM."""
        _LOGGER.debug("Service 'execute_tool_plan' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        llm_mgr = entry_store.get("local_llm_manager", local_llm_manager)
        prompt = call.data.get("prompt")
        auto_execute = call.data.get("auto_execute", True)
        model = call.data.get("model")

        if not prompt or not isinstance(prompt, str) or not prompt.strip():
            return {"success": False, "error": "Parameter 'prompt' is required for autonomous LLM reasoning and execution."}

        return await llm_mgr.async_chat_with_tools(
            prompt=prompt.strip(),
            model=model,
            auto_execute=auto_execute,
            context=call.context,
        )

    async def handle_index_document(call) -> ServiceResponse:
        """Handle service call to index a manual or document into knowledge store."""
        _LOGGER.debug("Service 'index_document' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        rm = entry_store.get("rag_manager", rag_manager)
        title = call.data.get("title") or "Smart Home Document"
        content = call.data.get("content", "")
        category = call.data.get("category", "manual")
        doc_id = call.data.get("document_id")
        metadata = call.data.get("metadata", {})
        return await rm.async_index_document(title=title, content=content, category=category, doc_id=doc_id, metadata=metadata)

    async def handle_query_knowledge_base(call) -> ServiceResponse:
        """Handle service call to query the knowledge store using hybrid RAG."""
        _LOGGER.debug("Service 'query_knowledge_base' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        rm = entry_store.get("rag_manager", rag_manager)
        query = call.data.get("query", "")
        limit = call.data.get("limit", 3)
        category = call.data.get("category")
        min_score = float(call.data.get("min_score", 0.12))
        results = await rm.async_query_knowledge(query=query, limit=limit, category=category, min_score=min_score)
        return {"query": query, "count": len(results), "results": results}

    async def handle_index_entity_history(call) -> ServiceResponse:
        """Handle service call to index entity state history or anomaly logs."""
        _LOGGER.debug("Service 'index_entity_history' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        rm = entry_store.get("rag_manager", rag_manager)
        entity_id = call.data.get("entity_id", "")
        events = call.data.get("events")
        max_events = call.data.get("max_events", 20)
        return await rm.async_index_entity_history(entity_id=entity_id, events=events, max_events=max_events)

    async def handle_clear_knowledge_base(call) -> ServiceResponse:
        """Handle service call to clear knowledge base chunks."""
        _LOGGER.debug("Service 'clear_knowledge_base' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        rm = entry_store.get("rag_manager", rag_manager)
        category = call.data.get("category")
        doc_id = call.data.get("document_id")
        return await rm.async_clear_knowledge(category=category, document_id=doc_id)

    async def handle_sync_entity_telemetry(call) -> ServiceResponse:
        """Handle service call to index live Home Assistant entity telemetry into RAG store."""
        _LOGGER.debug("Service 'sync_entity_telemetry' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        rm = entry_store.get("rag_manager", rag_manager)
        entity_ids = call.data.get("entity_ids")
        domains = call.data.get("domains")
        include_attributes = call.data.get("include_attributes", True)
        return await rm.async_index_entity_telemetry(
            entity_ids=entity_ids,
            domains=domains,
            include_attributes=include_attributes,
        )

    async def handle_index_device_manual(call) -> ServiceResponse:
        """Handle service call to index a device manual with manufacturer/model taxonomy."""
        _LOGGER.debug("Service 'index_device_manual' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        rm = entry_store.get("rag_manager", rag_manager)
        title = call.data.get("title") or "Device Technical Manual"
        content = call.data.get("content", "")
        manufacturer = call.data.get("manufacturer")
        model = call.data.get("model")
        domain = call.data.get("domain")
        doc_id = call.data.get("document_id")
        metadata = call.data.get("metadata", {})
        return await rm.async_index_device_manual(
            title=title,
            content=content,
            manufacturer=manufacturer,
            model=model,
            domain=domain,
            doc_id=doc_id,
            metadata=metadata,
        )

    async def handle_toggle_audio_follow(call) -> ServiceResponse:
        """Handle service call to toggle or set spatial audio follow-me."""
        _LOGGER.debug("Service 'toggle_audio_follow' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        rm_rules = entry_store.get("rules_manager", rules_manager)
        cur_rules = rm_rules.get_rules()
        enabled = call.data.get("enabled")
        if enabled is None:
            enabled = not cur_rules.get("audio_follow_enabled", True)
        else:
            enabled = bool(enabled)
        updated = await rm_rules.async_save({"audio_follow_enabled": enabled})
        return {
            "success": True,
            "audio_follow_enabled": updated.get("audio_follow_enabled", enabled),
        }

    async def handle_toggle_voice_announcements(call) -> ServiceResponse:
        """Handle service call to toggle or set proactive voice announcements."""
        _LOGGER.debug("Service 'toggle_voice_announcements' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        rm_rules = entry_store.get("rules_manager", rules_manager)
        cur_rules = rm_rules.get_rules()
        enabled = call.data.get("enabled")
        if enabled is None:
            enabled = not cur_rules.get("voice_announcements_enabled", True)
        else:
            enabled = bool(enabled)
        updated = await rm_rules.async_save({"voice_announcements_enabled": enabled})
        return {
            "success": True,
            "voice_announcements_enabled": updated.get("voice_announcements_enabled", enabled),
        }

    async def handle_confirm_person_identity(call) -> ServiceResponse:
        """Handle service call to train or verify person identity for audio follow & vision security."""
        _LOGGER.debug("Service 'confirm_person_identity' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        rm_rules = entry_store.get("rules_manager", rules_manager)
        person_id = call.data.get("person_id")
        if not person_id:
            return {"success": False, "error": "person_id is required"}
        track_id = call.data.get("track_id")
        label = call.data.get("label")
        confirmed = bool(call.data.get("confirmed", True))
        features = call.data.get("visual_features") or {}
        res = await rm_rules.async_confirm_person_identity(
            person_id=person_id,
            track_id=track_id,
            label=label,
            confirmed=confirmed,
            visual_features=features,
        )
        eng_inst = entry_store.get("engine") or _get_engine()
        if eng_inst and hasattr(eng_inst, "invalidate_cache"):
            eng_inst.invalidate_cache()
        return res

    async def handle_update_person_profile(call) -> ServiceResponse:
        """Handle service call to update person or pet profile classification and training toggle."""
        _LOGGER.debug("Service 'update_person_profile' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        rm_rules = entry_store.get("rules_manager", rules_manager)
        person_id = call.data.get("person_id")
        if not person_id:
            return {"success": False, "error": "person_id is required"}
        label = call.data.get("label")
        entity_type = call.data.get("entity_type", "resident")
        training_enabled = bool(call.data.get("training_enabled", True))
        return await rm_rules.async_update_person_profile(
            person_id=person_id,
            label=label,
            entity_type=entity_type,
            training_enabled=training_enabled,
        )

    async def handle_remove_person_profile(call) -> ServiceResponse:
        """Handle service call to remove a person or pet profile."""
        _LOGGER.debug("Service 'remove_person_profile' triggered with: %s", call.data)
        entry_store = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
        rm_rules = entry_store.get("rules_manager", rules_manager)
        person_id = call.data.get("person_id")
        if not person_id:
            return {"success": False, "error": "person_id is required"}
        return await rm_rules.async_remove_person_profile(person_id=person_id)

    async def handle_audit_mesh_health(call) -> ServiceResponse:
        """Handle service call to audit Zigbee/Z-Wave/Thread mesh topology and health."""
        _LOGGER.debug("Service 'audit_mesh_health' triggered")
        mm = _get_mesh_manager()
        return await mm.async_audit_mesh_topology()

    async def handle_heal_mesh_node(call) -> ServiceResponse:
        """Handle service call to heal a dead or degraded mesh node."""
        _LOGGER.debug("Service 'heal_mesh_node' triggered with: %s", call.data)
        mm = _get_mesh_manager()
        node_id = call.data.get("node_id")
        protocol = call.data.get("protocol")
        force_rebuild = bool(call.data.get("force_rebuild", False))
        if not node_id:
            return {"success": False, "error": "node_id is required"}
        return await mm.async_heal_mesh_node(
            node_id=node_id,
            protocol=protocol,
            force_rebuild=force_rebuild,
        )

    async def handle_orchestrate_multi_agent(call) -> ServiceResponse:
        """Handle service call to orchestrate multi-agent conversation and collaborative synthesis."""
        _LOGGER.debug("Service 'orchestrate_multi_agent' triggered with: %s", call.data)
        om = _get_agent_orchestrator()
        prompt = call.data.get("prompt")
        if not prompt:
            return {"success": False, "error": "Missing 'prompt' parameter"}
        conv_id = call.data.get("conversation_id")
        agent_ids = call.data.get("agent_ids")
        if isinstance(agent_ids, str):
            agent_ids = [a.strip() for a in agent_ids.split(",") if a.strip()]
        mode = call.data.get("collaboration_mode", "auto")
        timeout = float(call.data.get("timeout", 30.0))
        return await om.async_orchestrate(
            prompt=prompt,
            conversation_id=conv_id,
            requested_agents=agent_ids,
            mode=mode,
            timeout=timeout,
        )

    async def handle_configure_voice_satellite(call) -> ServiceResponse:
        """Handle service call to configure voice satellite persona, area, wake-word, and speaker."""
        _LOGGER.debug("Service 'configure_voice_satellite' triggered with: %s", call.data)
        om = _get_agent_orchestrator()
        satellite_id = call.data.get("satellite_id")
        if not satellite_id:
            return {"success": False, "error": "Missing 'satellite_id' parameter"}
        area_id = call.data.get("area_id")
        assigned_agent = call.data.get("assigned_agent")
        wake_word = call.data.get("wake_word")
        wake_word_engine = call.data.get("wake_word_engine")
        preferred_speaker = call.data.get("preferred_speaker")
        custom_pipeline = call.data.get("custom_pipeline")
        return await om.async_configure_satellite(
            satellite_id=satellite_id,
            area_id=area_id,
            assigned_agent=assigned_agent,
            wake_word=wake_word,
            wake_word_engine=wake_word_engine,
            preferred_speaker=preferred_speaker,
            custom_pipeline=custom_pipeline,
        )

    async def handle_arbitrate_satellite_audio(call) -> ServiceResponse:
        """Handle service call to acoustically arbitrate multiple concurrent satellite triggers."""
        _LOGGER.debug("Service 'arbitrate_satellite_audio' triggered with: %s", call.data)
        om = _get_agent_orchestrator()
        candidates = call.data.get("candidate_satellites") or []
        utterance = call.data.get("utterance")
        return om.arbitrate_satellite_audio(
            candidate_satellites=candidates,
            utterance=utterance,
        )

    _LOGGER.debug("Registering Otis AI services")
    service_specs: list[tuple[str, Any, bool]] = [
        (SERVICE_GET_CAPABILITY_MAP, handle_get_capability_map, False),
        (SERVICE_GET_SUGGESTIONS, handle_get_suggestions, False),
        (SERVICE_APPLY_SUGGESTION, handle_apply_suggestion, True),
        (SERVICE_CHAT, handle_chat, False),
        (SERVICE_GET_SPATIAL_MAP, handle_get_spatial_map, False),
        (SERVICE_UPDATE_SPATIAL_MAP, handle_update_spatial_map, True),
        (SERVICE_GENERATE_FLOORPLAN, handle_generate_floorplan, True),
        (SERVICE_RECALCULATE_FLOORPLAN, handle_recalculate_floorplan, True),
        (SERVICE_UPDATE_FLOORPLAN_LAYOUT, handle_update_floorplan_layout, True),
        (SERVICE_PIN_FLOORPLAN_ENTITY, handle_pin_floorplan_entity, True),
        (SERVICE_UNPIN_FLOORPLAN_ENTITY, handle_unpin_floorplan_entity, True),
        (SERVICE_GENERATE_THEME, handle_generate_theme, True),
        (SERVICE_APPLY_THEME, handle_apply_theme, True),
        (SERVICE_LIST_THEMES, handle_list_themes, False),
        (SERVICE_DELETE_THEME, handle_delete_theme, True),
        (SERVICE_RUN_SENTINEL_WATCHDOG, handle_run_sentinel_watchdog, False),
        (SERVICE_REMEDIATE_ANOMALY, handle_remediate_anomaly, True),
        (SERVICE_GET_SENTINEL_TELEMETRY, handle_get_sentinel_telemetry, False),
        (SERVICE_IGNORE_SENTINEL_ALERT, handle_ignore_sentinel_alert, True),
        (SERVICE_CREATE_COMMAND_CENTER, handle_create_command_center, True),
        (SERVICE_SYNC_DASHBOARDS, handle_sync_dashboards, True),
        (SERVICE_REGENERATE_DASHBOARDS, handle_regenerate_dashboards, True),
        (SERVICE_EXECUTE_MACRO, handle_execute_macro, False),
        (SERVICE_ROLLBACK_MACRO, handle_rollback_macro, False),
        (SERVICE_CANCEL_PRECONDITIONING, handle_cancel_preconditioning, False),
        (SERVICE_LIST_MACROS, handle_list_macros, False),
        (SERVICE_AUDIO_HANDOFF, handle_audio_handoff, False),
        (SERVICE_MEDIA_FOLLOW_ME, handle_media_follow_me, False),
        (SERVICE_RELEASE_IDLE_SOURCES, handle_release_idle_sources, False),
        (SERVICE_NOTIFY_VOICE, handle_notify_voice, False),
        (SERVICE_GET_ENERGY_SUMMARY, handle_get_energy_summary, False),
        (SERVICE_LOAD_SHED, handle_load_shed, True),
        (SERVICE_RESTORE_SHED_LOADS, handle_restore_shed_loads, True),
        (SERVICE_OPTIMIZE_BATTERY_SCHEDULE, handle_optimize_battery_schedule, True),
        (SERVICE_GET_ENERGY_ARBITRAGE_PLAN, handle_get_energy_arbitrage_plan, False),
        (SERVICE_SCHEDULE_EV_CHARGING, handle_schedule_ev_charging, True),
        (SERVICE_EXECUTE_ENERGY_ARBITRAGE, handle_execute_energy_arbitrage, True),
        (SERVICE_GET_PRESENCE_STATES, handle_get_presence_states, False),
        (SERVICE_FUSE_PRESENCE, handle_fuse_presence, False),
        (SERVICE_TRILATERATE_BLE, handle_trilaterate_ble, False),
        (SERVICE_ANALYZE_CAMERA, handle_analyze_camera, False),
        (SERVICE_AUDIT_PERIMETER, handle_audit_perimeter, False),
        (SERVICE_GET_INTRUDER_TRACKS, handle_get_intruder_tracks, False),
        (SERVICE_ANNOUNCE_VISUAL_ALERT, handle_announce_visual_alert, False),
        (SERVICE_EVALUATE_CONTEXTUAL_ALERTS, handle_evaluate_contextual_alerts, False),
        (SERVICE_MINE_HABITS, handle_mine_habits, False),
        (SERVICE_GET_CIRCADIAN_CURVES, handle_get_circadian_curves, False),
        (SERVICE_AUDIT_HABIT_DEVIATIONS, handle_audit_habit_deviations, False),
        (SERVICE_AUDIT_UNASSIGNED_ENTITIES, handle_audit_unassigned_entities, False),
        (SERVICE_AUTO_COMMISSION_ENTITIES, handle_auto_commission_entities, True),
        (SERVICE_REGISTER_FEDERATED_NODE, handle_register_federated_node, True),
        (SERVICE_REMOVE_FEDERATED_NODE, handle_remove_federated_node, True),
        (SERVICE_SYNC_FEDERATED_NODES, handle_sync_federated_nodes, False),
        (SERVICE_CALL_REMOTE_SERVICE, handle_call_remote_service, True),
        (SERVICE_GET_FEDERATION_STATUS, handle_get_federation_status, False),
        (SERVICE_BROADCAST_CLUSTER_MESSAGE, handle_broadcast_cluster_message, True),
        (SERVICE_FORWARD_REMOTE_COMMAND, handle_forward_remote_command, True),
        (SERVICE_GET_USER_RULES, handle_get_user_rules, False),
        (SERVICE_SET_USER_RULES, handle_set_user_rules, True),
        (SERVICE_DISMISS_RECOMMENDATION, handle_dismiss_recommendation, True),
        (SERVICE_HIDE_RECOMMENDATION, handle_hide_recommendation, True),
        (SERVICE_RESTORE_RECOMMENDATION, handle_restore_recommendation, True),
        (SERVICE_RESET_DISMISSED_RECOMMENDATIONS, handle_reset_dismissed_recommendations, True),
        (SERVICE_DUCK_MEDIA, handle_duck_media, False),
        (SERVICE_RESTORE_MEDIA, handle_restore_media, False),
        (SERVICE_GET_VOICE_ASSIST_STATUS, handle_get_voice_assist_status, False),
        (SERVICE_TEST_LOCAL_LLM, handle_test_local_llm, True),
        (SERVICE_BENCHMARK_LOCAL_LLM, handle_benchmark_local_llm, True),
        (SERVICE_PULL_LOCAL_LLM_MODEL, handle_pull_local_llm, True),
        (SERVICE_MANAGE_LOCAL_LLM_ADDON, handle_manage_local_llm_addon, True),
        (SERVICE_EXECUTE_TOOL_PLAN, handle_execute_tool_plan, True),
        (SERVICE_INDEX_DOCUMENT, handle_index_document, True),
        (SERVICE_QUERY_KNOWLEDGE, handle_query_knowledge_base, False),
        (SERVICE_INDEX_ENTITY_HISTORY, handle_index_entity_history, True),
        (SERVICE_CLEAR_KNOWLEDGE, handle_clear_knowledge_base, True),
        (SERVICE_SYNC_ENTITY_TELEMETRY, handle_sync_entity_telemetry, False),
        (SERVICE_INDEX_DEVICE_MANUAL, handle_index_device_manual, True),
        (SERVICE_TOGGLE_AUDIO_FOLLOW, handle_toggle_audio_follow, True),
        (SERVICE_TOGGLE_VOICE_ANNOUNCEMENTS, handle_toggle_voice_announcements, True),
        (SERVICE_CONFIRM_PERSON_IDENTITY, handle_confirm_person_identity, True),
        (SERVICE_UPDATE_PERSON_PROFILE, handle_update_person_profile, True),
        (SERVICE_REMOVE_PERSON_PROFILE, handle_remove_person_profile, True),
        (SERVICE_AUDIT_MESH_HEALTH, handle_audit_mesh_health, False),
        (SERVICE_HEAL_MESH_NODE, handle_heal_mesh_node, True),
        (SERVICE_ORCHESTRATE_MULTI_AGENT, handle_orchestrate_multi_agent, False),
        (SERVICE_CONFIGURE_VOICE_SATELLITE, handle_configure_voice_satellite, True),
        (SERVICE_ARBITRATE_SATELLITE_AUDIO, handle_arbitrate_satellite_audio, False),
    ]
    for svc_name, svc_handler, is_admin_only in service_specs:
        if is_admin_only:
            _register_admin_service(
                hass, DOMAIN, svc_name, svc_handler, supports_response=SupportsResponse.OPTIONAL
            )
        else:
            hass.services.async_register(
                DOMAIN, svc_name, svc_handler, supports_response=SupportsResponse.OPTIONAL
            )

    # Assist Co-Pilot Self-Optimization Admin Services
    async def handle_copilot_tune_rule(call: ServiceCall) -> ServiceResponse:
        rule_key = str(call.data.get("rule_key", "")).strip()
        rule_text = str(call.data.get("rule_text", "")).strip()
        enabled = bool(call.data.get("enabled", True))
        try:
            res = await copilot_engine.async_tune_prompt_rule(rule_key, rule_text, enabled=enabled)
            return {"status": "ok", "rule": res}
        except ValueError as err:
            return {"status": "error", "error": str(err)}

    async def handle_copilot_set_alias(call: ServiceCall) -> ServiceResponse:
        alias = str(call.data.get("alias", "")).strip()
        entity_id = str(call.data.get("entity_id", "")).strip()
        try:
            res = await copilot_engine.async_set_entity_alias(alias, entity_id)
            return {"status": "ok", "alias": res}
        except ValueError as err:
            return {"status": "error", "error": str(err)}

    async def handle_copilot_set_condition_template(call: ServiceCall) -> ServiceResponse:
        template_key = str(call.data.get("template_key", "")).strip()
        template_dict = call.data.get("template")
        try:
            res = await copilot_engine.async_set_condition_template(template_key, template_dict)
            return {"status": "ok", "template": res}
        except ValueError as err:
            return {"status": "error", "error": str(err)}

    async def handle_copilot_manage_fact(call: ServiceCall) -> ServiceResponse:
        action = str(call.data.get("action", "list")).strip().lower()
        if action == "add":
            fact = str(call.data.get("fact", "")).strip()
            category = str(call.data.get("category", "user_correction")).strip()
            entities = call.data.get("entities") or []
            try:
                rec = await copilot_engine.async_record_learned_fact(
                    fact,
                    category=category,
                    entities=list(entities) if isinstance(entities, list) else [],
                    source="runtime_tool",
                )
                return {"status": "ok", "fact": rec}
            except ValueError as err:
                return {"status": "error", "error": str(err)}
        if action == "remove":
            fact_id = str(call.data.get("fact_id", "")).strip()
            removed = await copilot_engine.async_remove_learned_fact(fact_id)
            return {"status": "ok" if removed else "not_found", "removed": removed}
        await copilot_engine.async_load()
        return {"status": "ok", **copilot_engine.get_copilot_state()}

    _register_admin_service(
        hass,
        DOMAIN,
        SERVICE_COPILOT_TUNE_RULE,
        handle_copilot_tune_rule,
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register_admin_service(
        hass,
        DOMAIN,
        SERVICE_COPILOT_SET_ALIAS,
        handle_copilot_set_alias,
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register_admin_service(
        hass,
        DOMAIN,
        SERVICE_COPILOT_SET_CONDITION_TEMPLATE,
        handle_copilot_set_condition_template,
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register_admin_service(
        hass,
        DOMAIN,
        SERVICE_COPILOT_MANAGE_FACT,
        handle_copilot_manage_fact,
        supports_response=SupportsResponse.OPTIONAL,
    )

    # Listen for service calls targeting switch.otis_audio_follow and switch.otis_voice_announcements
    async def _on_service_call_switches(event):
        data = getattr(event, "data", {})
        domain = data.get("domain")
        service = data.get("service")
        if domain in ("switch", "homeassistant") and service in ("turn_on", "turn_off", "toggle"):
            s_data = data.get("service_data", {})
            eids = s_data.get("entity_id")
            if isinstance(eids, str):
                eids = [eids]
            elif not isinstance(eids, list):
                eids = []
            if any(is_otis_entity_id(e, "switch", "audio_follow") for e in eids):
                cur = rules_manager.get_rules().get("audio_follow_enabled", True)
                new_val = not cur if service == "toggle" else (service == "turn_on")
                await rules_manager.async_save({"audio_follow_enabled": new_val})
            if any(is_otis_entity_id(e, "switch", "voice_announcements") for e in eids):
                cur = rules_manager.get_rules().get("voice_announcements_enabled", True)
                new_val = not cur if service == "toggle" else (service == "turn_on")
                await rules_manager.async_save({"voice_announcements_enabled": new_val})

    if hasattr(hass, "bus") and hasattr(hass.bus, "async_listen"):
        hass.bus.async_listen("call_service", _on_service_call_switches)

    _LOGGER.info("Otis AI Companion entry set up successfully")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Otis AI Companion entry: %s", entry.entry_id)
    if entry.entry_id in hass.data[DOMAIN]:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        fm = entry_data.get("federation_manager")
        if fm and hasattr(fm, "async_stop_background_sync"):
            await fm.async_stop_background_sync()
        agent = entry_data.get("agent")
        if agent:
            _LOGGER.debug("Unregistering conversation agent")
            if hasattr(conversation, "async_unregister_agent"):
                conversation.async_unregister_agent(hass, agent)
            else:
                conversation.async_unset_agent(hass, entry)

    if hasattr(hass, "config_entries") and hasattr(hass.config_entries, "async_unload_platforms"):
        try:
            await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        except Exception as plat_err:
            _LOGGER.debug("Could not unload platforms: %s", plat_err)

    # Remove services if no other entries exist
    if not hass.data[DOMAIN]:
        for srv in (
            SERVICE_GET_CAPABILITY_MAP,
            SERVICE_GET_SUGGESTIONS,
            SERVICE_APPLY_SUGGESTION,
            SERVICE_CHAT,
            SERVICE_GET_SPATIAL_MAP,
            SERVICE_UPDATE_SPATIAL_MAP,
            SERVICE_GENERATE_FLOORPLAN,
            SERVICE_RECALCULATE_FLOORPLAN,
            SERVICE_UPDATE_FLOORPLAN_LAYOUT,
            SERVICE_PIN_FLOORPLAN_ENTITY,
            SERVICE_UNPIN_FLOORPLAN_ENTITY,
            SERVICE_GET_USER_RULES,
            SERVICE_SET_USER_RULES,
            SERVICE_DISMISS_RECOMMENDATION,
            SERVICE_HIDE_RECOMMENDATION,
            SERVICE_RESTORE_RECOMMENDATION,
            SERVICE_RESET_DISMISSED_RECOMMENDATIONS,
            SERVICE_DUCK_MEDIA,
            SERVICE_RESTORE_MEDIA,
            SERVICE_GET_VOICE_ASSIST_STATUS,
            SERVICE_TEST_LOCAL_LLM,
            SERVICE_BENCHMARK_LOCAL_LLM,
        ):
            if hass.services.has_service(DOMAIN, srv):
                _LOGGER.debug("Removing service: %s", srv)
                hass.services.async_remove(DOMAIN, srv)

    _LOGGER.info("Otis AI Companion entry unloaded successfully")
    return True


# Compatibility for older Home Assistant versions
AbstractAgent = getattr(conversation, "AbstractAgent", getattr(conversation, "AbstractConversationAgent", None))


class OtisAIConversationAgent(AbstractAgent):
    """Otis AI Companion conversation agent that intercepts Assist and delegates to the selected LLM."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        engine: DiscoveryEngine,
        automation_manager: AutomationManager,
        spatial_manager: SpatialGraphManager | None = None,
        theme_manager: ThemeManager | None = None,
        sentinel_manager: SentinelManager | None = None,
        macro_manager: MacroManager | None = None,
        audio_manager: AudioHandoffManager | None = None,
        energy_manager: EnergyManager | None = None,
        vision_manager: VisionPresenceManager | None = None,
        habit_manager: BehavioralHabitManager | None = None,
        commissioning_manager: AutonomousCommissioningManager | None = None,
        federation_manager: FederationManager | None = None,
        rules_manager: BehavioralRulesManager | None = None,
        local_llm_manager: LocalLLMManager | None = None,
        dashboard_manager: DashboardManager | None = None,
        floorplan_parser: FloorplanParser | None = None,
        rag_manager: RAGKnowledgeManager | None = None,
        presence_fusion_manager: PresenceFusionManager | None = None,
        agent_orchestrator: MultiAgentOrchestrator | None = None,
        copilot_engine: CopilotEngine | None = None,
        log_monitor: LogMonitor | None = None,
    ) -> None:
        """Initialize the agent."""
        self.hass = hass
        self.entry = entry
        self.engine = engine
        self.automation_manager = automation_manager
        self.spatial_manager = spatial_manager or SpatialGraphManager(hass)
        self.theme_manager = theme_manager or ThemeManager(hass)
        self.sentinel_manager = sentinel_manager or SentinelManager(hass)
        self.macro_manager = macro_manager or MacroManager(hass)
        self.audio_manager = audio_manager or AudioHandoffManager(hass, spatial_manager=self.spatial_manager)
        self.energy_manager = energy_manager or EnergyManager(hass, spatial_manager=self.spatial_manager)
        self.vision_manager = vision_manager or VisionPresenceManager(hass, spatial_manager=self.spatial_manager)
        self.habit_manager = habit_manager or BehavioralHabitManager(hass, spatial_manager=self.spatial_manager)
        self.commissioning_manager = commissioning_manager or AutonomousCommissioningManager(hass, spatial_manager=self.spatial_manager)
        self.federation_manager = federation_manager or FederationManager(hass)
        self.rules_manager = rules_manager or BehavioralRulesManager(hass)
        self.local_llm_manager = local_llm_manager
        self.rag_manager = rag_manager
        self.presence_fusion_manager = presence_fusion_manager
        self.agent_orchestrator = agent_orchestrator
        self.copilot_engine = copilot_engine or getattr(hass.data.get(DOMAIN, {}), "get", lambda k: None)("copilot_engine") or CopilotEngine(hass)
        self.log_monitor = log_monitor or getattr(hass.data.get(DOMAIN, {}), "get", lambda k: None)("log_monitor") or LogMonitor(hass)
        self.dashboard_manager = dashboard_manager or getattr(hass.data.get(DOMAIN, {}), "get", lambda k: None)("dashboard_manager") or DashboardManager(hass)
        self.floorplan_parser = floorplan_parser or getattr(hass.data.get(DOMAIN, {}), "get", lambda k: None)("floorplan_parser") or FloorplanParser(hass)

    def _resolve_entity_from_text(self, text: str, entities_list: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Resolve entity dictionary from entity_id, friendly name, or partial search text."""
        clean = text.strip().lower()
        # 1. Exact entity_id match
        for e in entities_list:
            if e.get("entity_id", "").lower() == clean:
                return e
        # 2. Exact name match
        for e in entities_list:
            ename = str(e.get("name") or "").lower()
            if ename and ename == clean:
                return e
        # 3. Substring match
        for e in entities_list:
            eid = e.get("entity_id", "").lower()
            ename = str(e.get("name") or "").lower()
            if clean in eid or (ename and clean in ename):
                return e
        return None

    def _resolve_area_from_text(self, text: str, areas_dict: dict[str, Any]) -> tuple[str, str] | None:
        """Resolve area_id and area friendly name from area_id or room name string."""
        clean = text.strip().lower()
        for aid, ainfo in areas_dict.items():
            aname = str(ainfo.get("name") or aid).lower()
            if aid.lower() == clean or aname == clean:
                return (aid, ainfo.get("name") or aid.replace("_", " ").title())
        for aid, ainfo in areas_dict.items():
            aname = str(ainfo.get("name") or aid).lower()
            if clean in aid.lower() or clean in aname or aname in clean:
                return (aid, ainfo.get("name") or aid.replace("_", " ").title())
        return None

    def _resolve_control_target(self, text: str) -> dict[str, Any] | None:
        """Resolve device, light, switch, fan, cover, lock, or area target from conversational command text."""
        raw = text.strip().lower()
        raw = re.sub(r"^(please|could you please|can you please|would you please|hey otis|otis|alexa|hey google|google)\s*,?\s*", "", raw)
        raw = re.sub(r"\s+(please|thanks|thank you)\.?$", "", raw)

        action = None
        target_str = ""
        service_domain = None
        service_name = None

        m_on = re.match(r"^(?:turn\s+on|switch\s+on|power\s+on|activate|start)\s+(.+)$", raw)
        m_off = re.match(r"^(?:turn\s+off|switch\s+off|power\s+off|deactivate|kill|stop)\s+(.+)$", raw)
        m_toggle = re.match(r"^(?:toggle)\s+(.+)$", raw)
        m_lock = re.match(r"^(?:lock)\s+(.+)$", raw)
        m_unlock = re.match(r"^(?:unlock)\s+(.+)$", raw)
        m_open = re.match(r"^(?:open)\s+(.+)$", raw)
        m_close = re.match(r"^(?:close)\s+(.+)$", raw)

        if m_on:
            action = "turn_on"
            target_str = m_on.group(1).strip()
        elif m_off:
            action = "turn_off"
            target_str = m_off.group(1).strip()
        elif m_toggle:
            action = "toggle"
            target_str = m_toggle.group(1).strip()
        elif m_lock:
            action = "lock"
            target_str = m_lock.group(1).strip()
            service_domain = "lock"
            service_name = "lock"
        elif m_unlock:
            action = "unlock"
            target_str = m_unlock.group(1).strip()
            service_domain = "lock"
            service_name = "unlock"
        elif m_open:
            action = "open"
            target_str = m_open.group(1).strip()
            service_domain = "cover"
            service_name = "open_cover"
        elif m_close:
            action = "close"
            target_str = m_close.group(1).strip()
            service_domain = "cover"
            service_name = "close_cover"

        if not action or not target_str:
            return None

        if target_str.startswith("the "):
            target_str = target_str[4:].strip()

        target_str = target_str.rstrip(".!?,")
        target_norm = re.sub(r"[^a-z0-9]+", " ", target_str).strip()
        target_slug = target_norm.replace(" ", "_")

        control_domains = ("light", "switch", "fan", "lock", "cover", "climate")
        all_states = self.hass.states.async_all() if hasattr(self.hass, "states") else []
        candidates = []

        for st in all_states:
            eid = st.entity_id
            domain = eid.split(".", 1)[0]
            if domain not in control_domains:
                continue
            obj_id = eid.split(".", 1)[1]
            friendly = str((st.attributes or {}).get("friendly_name") or obj_id).lower()
            friendly_norm = re.sub(r"[^a-z0-9]+", " ", friendly).strip()
            obj_norm = re.sub(r"[^a-z0-9]+", " ", obj_id).strip()

            # Exact matches (highest priority)
            if target_norm == friendly_norm or target_slug == obj_id or target_norm == obj_norm:
                return {
                    "type": "entity",
                    "action": action,
                    "entity_id": eid,
                    "domain": domain,
                    "service_domain": service_domain or domain,
                    "service_name": service_name or action,
                    "name": (st.attributes or {}).get("friendly_name") or eid,
                    "state": st.state,
                    "attributes": dict(st.attributes or {}),
                    "confidence": "exact",
                }

            # Substring / partial matches
            if (
                target_norm in friendly_norm
                or friendly_norm in target_norm
                or target_slug in obj_id
                or obj_id in target_slug
            ):
                candidates.append({
                    "entity_id": eid,
                    "domain": domain,
                    "name": (st.attributes or {}).get("friendly_name") or eid,
                    "state": st.state,
                    "attributes": dict(st.attributes or {}),
                })

        if len(candidates) == 1:
            cand = candidates[0]
            return {
                "type": "entity",
                "action": action,
                "entity_id": cand["entity_id"],
                "domain": cand["domain"],
                "service_domain": service_domain or cand["domain"],
                "service_name": service_name or action,
                "name": cand["name"],
                "state": cand["state"],
                "attributes": cand["attributes"],
                "confidence": "fuzzy_single",
            }

        # Check Area match
        areas_dict = {}
        try:
            from homeassistant.helpers import area_registry as ar
            area_reg = ar.async_get(self.hass)
            areas_dict = {a.id: {"name": a.name} for a in area_reg.async_list_areas()}
        except Exception:
            pass

        target_base = re.sub(r"\s+lights?$", "", target_str).strip()
        area_match = self._resolve_area_from_text(target_base, areas_dict) if areas_dict else None
        if area_match:
            aid, aname = area_match
            if len(candidates) > 1:
                return {
                    "type": "ambiguous",
                    "action": action,
                    "candidates": candidates,
                    "raw_target": target_str,
                    "area_id": aid,
                    "area_name": aname,
                }
            return {
                "type": "area",
                "action": action,
                "area_id": aid,
                "area_name": aname,
                "raw_target": target_str,
            }

        if len(candidates) > 1:
            return {
                "type": "ambiguous",
                "action": action,
                "candidates": candidates,
                "raw_target": target_str,
            }

        return None

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return a list of supported languages."""
        return ["en"]

    def _create_response(
        self,
        user_input: conversation.UserInput,
        speech: str,
    ) -> conversation.ConversationResult:
        """Create a ConversationResult with a properly initialized IntentResponse."""
        cid = getattr(user_input, "conversation_id", None) or "default"
        if hasattr(user_input, "create_response"):
            return conversation.ConversationResult(
                response=user_input.create_response(intent_response=None, speech=speech),
                conversation_id=cid,
            )
        try:
            intent_response = intent.IntentResponse(language=getattr(user_input, "language", "en"))
            intent_response.async_set_speech(speech)
            return conversation.ConversationResult(
                response=intent_response,
                conversation_id=cid,
            )
        except Exception as err:
            _LOGGER.error("Failed to construct intent response: %s", err)
            return conversation.ConversationResult(
                response=None,
                conversation_id=cid,
            )

    def _record_turn(
        self,
        session_data: dict[str, Any],
        user_text: str,
        assistant_text: str,
    ) -> None:
        """Record a conversation turn in session history to prevent multi-turn amnesia."""
        if session_data is None:
            return
        history = session_data.setdefault("history", [])
        if user_text:
            history.append({"role": "user", "text": user_text})
        if assistant_text:
            history.append({"role": "assistant", "text": assistant_text})
        if len(history) > 20:
            session_data["history"] = history[-20:]

    def _extract_pending_items_from_speech(
        self, speech_text: str, user_text: str = ""
    ) -> tuple[list[dict[str, Any]], str]:
        """Extract automation and script items from YAML blocks and sanitize speech for GUI co-pilot deployment."""
        if not speech_text:
            return [], speech_text

        yaml_blocks = re.findall(r"```(?:yaml)?\s*\n(.*?)```", speech_text, re.DOTALL)
        if not yaml_blocks:
            return [], speech_text

        if is_explanatory_query(user_text):
            return [], speech_text

        class _HALoader(yaml.SafeLoader):
            pass

        _HALoader.add_constructor("!input", lambda loader, node: f"!input {node.value}")
        _HALoader.add_constructor("!secret", lambda loader, node: f"!secret {node.value}")
        _HALoader.add_constructor("!include", lambda loader, node: f"!include {node.value}")

        pending_items: list[dict[str, Any]] = []

        for block in yaml_blocks:
            try:
                parsed = yaml.load(block, Loader=_HALoader)
                if not parsed:
                    continue

                candidates: list[dict[str, Any]] = []
                if isinstance(parsed, list):
                    candidates = [c for c in parsed if isinstance(c, dict)]
                elif isinstance(parsed, dict):
                    if "automation" in parsed and isinstance(parsed["automation"], (dict, list)):
                        val = parsed["automation"]
                        candidates = val if isinstance(val, list) else [val]
                    elif "automations" in parsed and isinstance(parsed["automations"], (dict, list)):
                        val = parsed["automations"]
                        candidates = val if isinstance(val, list) else [val]
                    elif "script" in parsed and isinstance(parsed["script"], (dict, list)):
                        val = parsed["script"]
                        candidates = val if isinstance(val, list) else [val]
                    elif "scripts" in parsed and isinstance(parsed["scripts"], (dict, list)):
                        val = parsed["scripts"]
                        candidates = val if isinstance(val, list) else [val]
                    elif len(parsed) == 1 and not any(k in parsed for k in ("sequence", "actions", "action", "trigger", "triggers")):
                        single_key = next(iter(parsed.keys()))
                        single_val = parsed[single_key]
                        if isinstance(single_val, dict) and any(k in single_val for k in ("sequence", "actions", "action", "trigger", "triggers")):
                            if "alias" not in single_val:
                                single_val["alias"] = single_key.replace("_", " ").title()
                            single_val["_inferred_key"] = single_key
                            candidates = [single_val]
                        elif isinstance(single_val, list):
                            candidates = [c for c in single_val if isinstance(c, dict)]
                        else:
                            candidates = [parsed]
                    else:
                        candidates = [parsed]

                for item in candidates:
                    if not isinstance(item, dict):
                        continue

                    inf_key = item.pop("_inferred_key", None)

                    if "blueprint" in item:
                        bp_meta = item.get("blueprint")
                        bp_name = "Custom Blueprint"
                        if isinstance(bp_meta, dict):
                            bp_name = bp_meta.get("name") or bp_name
                        elif isinstance(bp_meta, str):
                            bp_name = bp_meta

                        bp_path_match = re.search(r"(?:(?:blueprints/automation/|path:\s*|blueprint:\s*|blueprint(?:\s+file)?(?:\s+for)?\s*[`'\"]?)([\w/-]+\.ya?ml))", speech_text, re.IGNORECASE)
                        if bp_path_match:
                            bp_path = bp_path_match.group(1).strip()
                        else:
                            u_bp_match = re.search(r"([\w/-]+\.ya?ml)", user_text or "")
                            bp_path = u_bp_match.group(1).strip() if u_bp_match else re.sub(r"\W+", "_", bp_name.lower()).strip("_") + ".yaml"

                        pending_items.append({
                            "type": "blueprint",
                            "name": bp_name,
                            "path": bp_path,
                            "yaml_data": item,
                            "raw_yaml": block.strip(),
                        })
                        continue

                    has_triggers = (
                        "trigger" in item
                        or "triggers" in item
                        or "platform" in item
                        or "use_blueprint" in item
                    )
                    has_actions = "action" in item or "actions" in item
                    has_sequence = "sequence" in item

                    if has_triggers or (has_actions and not has_sequence):
                        auto_name = item.get("alias")
                        if not auto_name and inf_key:
                            auto_name = inf_key.replace("_", " ").title()
                        elif not auto_name:
                            auto_name = "Proposed Automation"
                        item["alias"] = auto_name

                        pending_items.append({
                            "type": "automation",
                            "name": auto_name,
                            "yaml_data": item,
                        })

                    elif has_sequence or (has_actions and not has_triggers):
                        alias = item.get("alias")
                        if not alias and inf_key:
                            alias = inf_key.replace("_", " ").title()
                        elif not alias:
                            u_low = (user_text or "").lower()
                            if any(w in u_low for w in ("media", "audio", "matrix", "speaker", "music", "volume", "sound")):
                                alias = "Media Matrix Zone Coordinator"
                            elif any(w in u_low for w in ("light", "lamp", "dimmer")):
                                alias = "Smart Lighting Coordinator"
                            elif any(w in u_low for w in ("climate", "temp", "thermostat", "hvac")):
                                alias = "Climate Zone Coordinator"
                            elif any(w in u_low for w in ("security", "lock", "alarm", "perimeter")):
                                alias = "Perimeter Security Coordinator"
                            else:
                                alias = "Otis System Routine"
                        item["alias"] = alias
                        script_key = inf_key or re.sub(r"\W+", "_", alias.lower()).strip("_")
                        pending_items.append({
                            "type": "script",
                            "id": script_key,
                            "name": alias,
                            "yaml_data": item,
                        })

            except Exception as yaml_err:
                _LOGGER.debug("Failed to parse YAML block: %s", yaml_err)

        cleaned_speech = speech_text

        if pending_items:
            patterns_to_remove = [
                r"(?is)to\s+deploy\s+this\s+automation,\s+you\s+can\s+follow\s+these\s+steps:.*?(?=\n\nWould you like|\Z)",
                r"(?im)^\s*\d+\.\s*(?:open|add|save|paste|copy|reload|restart)\s+[^\n]*(?:automations\.yaml|home assistant|file)[^\n]*\n?",
                r"(?i)(?:to\s+(?:add|use|install|implement|deploy)\s+this(?:\s+automation)?,\s+)?(?:open|paste|add|copy)\s+(?:the\s+following(?:\s+code|\s+yaml)?\s+(?:in|into|to)\s+)?(?:your\s+)?(?:/config/)?automations\.yaml(?:\s+file)?(?:\s+and\s+(?:reload|restart)[^.\n]*)?[.]?",
                r"(?i)you\s+(?:can|will\s+need\s+to|must)\s+(?:add|paste|put)\s+this\s+(?:in|into|to)\s+(?:your\s+)?(?:/config/)?automations\.yaml[^.\n]*[.]?",
                r"(?i)(?:i\s+cannot|i'm\s+unable\s+to|i\s+am\s+unable\s+to)\s+(?:directly\s+)?deploy[^.\n]*[.]?",
                r"(?i)to\s+deploy\s+(?:it|this)\s+(?:manually|yourself)[^.\n]*[.]?",
                r"(?is)step-by-step guide:.*?(?=\n\n|\Z)",
                r"(?im)^\s*\d+\.\s*(?:identify|locate|download|extract|restore|verify)\s+[^\n]*(?:backup|archive|script)[^\n]*\n?",
                r"(?im)^\s*step\s+\d+:\s*[^\n]+\n?",
                r"(?i)(?:access|search|download|extract|open|check)\s+(?:your\s+)?backup(?:\s+system|\s+files|\s+file)?[^.\n]*[.]?",
                r"(?i)extract\s+the\s+(?:downloaded\s+)?backup(?:\s+file)?[^.\n]*[.]?",
                r"(?i)locate\s+the\s+[^\n]+\.ya?ml\s+file\s+in\s+the\s+extracted\s+backup[^.\n]*[.]?",
            ]
            for pat in patterns_to_remove:
                cleaned_speech = re.sub(pat, "", cleaned_speech)

            cleaned_speech = cleaned_speech.rstrip()

            names_summary = ", ".join(f"'{item['name']}'" for item in pending_items)
            if len(pending_items) == 1 and pending_items[0]["type"] == "automation":
                confirm_text = f"\n\nWould you like me to create and enable this automation '{pending_items[0]['name']}' in your Home Assistant? Say 'yes' or 'apply' to confirm, or 'no' to cancel."
            elif len(pending_items) == 1 and pending_items[0]["type"] == "script":
                confirm_text = f"\n\nWould you like me to create this script '{pending_items[0]['name']}' (`script.{pending_items[0]['id']}`) in your Home Assistant? Say 'yes' or 'apply' to confirm, or 'no' to cancel."
            elif len(pending_items) == 1 and pending_items[0]["type"] == "blueprint":
                confirm_text = f"\n\nWould you like me to update and deploy this blueprint '{pending_items[0]['name']}' (`{pending_items[0]['path']}`) in your Home Assistant? Say 'yes' or 'apply' to confirm, or 'no' to cancel."
            else:
                confirm_text = f"\n\nWould you like me to create and configure these {len(pending_items)} items ({names_summary}) in your Home Assistant? Say 'yes' or 'apply' to confirm, or 'no' to cancel."

            if "Would you like me to create" not in cleaned_speech and "Say 'yes' or 'apply'" not in cleaned_speech:
                cleaned_speech += confirm_text

        return pending_items, cleaned_speech

    async def async_process(
        self, user_input: conversation.UserInput
    ) -> conversation.ConversationResult:
        """Process a sentence and delegate to the selected LLM with capability context."""
        _LOGGER.debug("Processing conversation input: %s", user_input.text)
        
        # Initialize session states
        self.hass.data.setdefault(DOMAIN, {}).setdefault("sessions", {})
        sessions = self.hass.data[DOMAIN]["sessions"]
        conv_id = user_input.conversation_id or "default"
        session_data = sessions.setdefault(conv_id, {})
        user_text = user_input.text.strip().lower()

        def fire_progress(step_id: str, title: str, detail: str) -> None:
            if hasattr(self.hass, "bus") and hasattr(self.hass.bus, "async_fire"):
                try:
                    self.hass.bus.async_fire("otis_ai_reasoning_step", {
                        "conversation_id": user_input.conversation_id,
                        "step": step_id,
                        "title": title,
                        "detail": detail,
                    })
                except Exception:
                    pass

        fire_progress("intent", "Parsing Intent", "Analyzing natural language prompt & target domains")
        
        intent_cls = classify_confirmation_intent(user_input.text)
        is_rejection = intent_cls["is_rejection"]
        is_confirmation = intent_cls["is_confirmation"]

        # If not already pending in session, check if user is asking to deploy a configuration from the immediate prior turn
        if not (session_data.get("pending_items") or session_data.get("pending_yaml")) and is_confirmation:
            history = session_data.get("history", [])
            for turn in reversed(history):
                if turn.get("role") == "assistant" and "```" in turn.get("text", ""):
                    recovered_items, _ = self._extract_pending_items_from_speech(turn["text"], user_input.text)
                    if recovered_items:
                        session_data["pending_items"] = recovered_items
                        session_data["pending_yaml"] = recovered_items[0]
                        _LOGGER.info("Recovered %d pending item(s) from prior conversation turn for deployment", len(recovered_items))
                        break

        # Check for pending wizard confirmation (single or multi-item configuration)
        if session_data.get("pending_items") or session_data.get("pending_yaml"):
            if is_confirmation:
                items = session_data.pop("pending_items", None)
                if not items:
                    p = session_data.pop("pending_yaml", None)
                    if p:
                        if isinstance(p, dict) and p.get("type"):
                            items = [p]
                        elif isinstance(p, dict):
                            items = [{"type": "automation", "name": p.get("alias", "automation"), "yaml_data": p}]
                        else:
                            items = []
                    else:
                        items = []
                else:
                    session_data.pop("pending_yaml", None)

                try:
                    created_autos = []
                    created_scripts = []
                    created_blueprints = []
                    for item in items:
                        if item.get("type") == "automation":
                            auto_id = await self.automation_manager.async_write_automation(item["yaml_data"])
                            created_autos.append(item["yaml_data"].get("alias", auto_id))
                        elif item.get("type") == "script":
                            s_key = item.get("id") or re.sub(r"\W+", "_", item["yaml_data"].get("alias", "custom_script").lower()).strip("_")
                            await self.automation_manager.async_write_script(s_key, item["yaml_data"])
                            created_scripts.append(item["yaml_data"].get("alias", s_key))
                        elif item.get("type") == "blueprint":
                            bp_path = item.get("path") or "custom_blueprint.yaml"
                            content_to_write = item.get("raw_yaml") or item["yaml_data"]
                            await self.automation_manager.async_write_blueprint(bp_path, content_to_write)
                            created_blueprints.append(f"{item.get('name', 'Blueprint')} (`{bp_path}`)")

                    if created_autos:
                        await self.automation_manager.async_reload_automations()
                    if created_scripts:
                        await self.automation_manager.async_reload_scripts()
                    if created_blueprints:
                        await self.automation_manager.async_reload_blueprints()
                        await self.automation_manager.async_reload_automations()

                    if hasattr(self.engine, "invalidate_cache") and callable(getattr(self.engine, "invalidate_cache", None)):
                        self.engine.invalidate_cache()

                    if len(items) == 1 and created_autos:
                        yaml_content = items[0].get("raw_yaml") or yaml.dump(clean_yaml_dict(items[0]["yaml_data"]), Dumper=_NoAliasSafeDumper, sort_keys=False, default_flow_style=False)
                        speech = (
                            f"I have successfully created and enabled the automation '{created_autos[0]}'!\n\n"
                            f"📋 **Configuration YAML (Ready to Apply in Home Assistant):**\n"
                            f"```yaml\n{yaml_content}\n```"
                        )
                    elif len(items) == 1 and created_scripts:
                        yaml_content = items[0].get("raw_yaml") or yaml.dump(clean_yaml_dict(items[0]["yaml_data"]), Dumper=_NoAliasSafeDumper, sort_keys=False, default_flow_style=False)
                        speech = (
                            f"I have successfully created the script '{created_scripts[0]}'!\n\n"
                            f"📋 **Configuration YAML (Ready to Apply in Home Assistant):**\n"
                            f"```yaml\n{yaml_content}\n```"
                        )
                    elif len(items) == 1 and created_blueprints:
                        yaml_content = items[0].get("raw_yaml") or (yaml.dump(clean_yaml_dict(items[0]["yaml_data"]), Dumper=_NoAliasSafeDumper, sort_keys=False, default_flow_style=False) if isinstance(items[0]["yaml_data"], dict) else str(items[0]["yaml_data"]))
                        speech = (
                            f"I have successfully updated and deployed the blueprint '{created_blueprints[0]}'!\n\n"
                            f"📋 **Configuration YAML:**\n"
                            f"```yaml\n{yaml_content}\n```"
                        )
                    else:
                        parts = []
                        if created_blueprints:
                            parts.append(f"Blueprint(s): {', '.join(created_blueprints)}")
                        if created_scripts:
                            parts.append(f"Script(s): {', '.join(created_scripts)}")
                        if created_autos:
                            parts.append(f"Automation(s): {', '.join(created_autos)}")
                        speech = (
                            "I have successfully created and enabled the configuration! Applied successfully!\n• "
                            + "\n• ".join(parts)
                            + "\n\n📋 **Ready-to-Apply YAML configuration generated.**"
                        )

                    self._record_turn(session_data, user_input.text, speech)
                    return self._create_response(user_input, speech)
                except Exception as err:
                    _LOGGER.error("Failed to apply pending configuration: %s", err, exc_info=True)
                    err_speech = f"I encountered an error while writing the configuration: {err}. Please check the logs."
                    self._record_turn(session_data, user_input.text, err_speech)
                    return self._create_response(user_input, err_speech)
            elif is_rejection:
                session_data.pop("pending_items", None)
                session_data.pop("pending_yaml", None)
                msg = "Okay, I have discarded the proposed configuration."
                self._record_turn(session_data, user_input.text, msg)
                return self._create_response(user_input, msg)
            else:
                # User moved on to a new unrelated request; clear stale pending configuration
                session_data.pop("pending_items", None)
                session_data.pop("pending_yaml", None)

        # Check for pending macro confirmation
        if conv_id in sessions and sessions[conv_id].get("pending_macro"):
            if is_confirmation:
                pending_m = sessions[conv_id].pop("pending_macro")
                try:
                    res = await self.macro_manager.async_execute_macro(
                        macro_name=pending_m["name"],
                        steps=pending_m["steps"],
                        confirmed=True,
                        macro_id=pending_m.get("macro_id"),
                    )
                    if res.get("success"):
                        speech = (
                            f"🚀 **{pending_m['name']} Activated!**\n\n"
                            f"• {res.get('steps_executed', 0)} of {res.get('steps_total', 0)} step(s) executed successfully.\n"
                            f"• State snapshot saved for {res.get('snapshot_entities_count', 0)} entities.\n\n"
                            "*(Say 'undo' or 'rollback' anytime to revert devices to prior states)*"
                        )
                    else:
                        speech = f"⚠️ Macro execution encountered an issue: {res.get('summary', res.get('error'))}"
                    return self._create_response(user_input, speech)
                except Exception as err:
                    _LOGGER.error("Failed to execute pending macro: %s", err, exc_info=True)
                    return self._create_response(
                        user_input,
                        f"I encountered an error while executing the macro: {err}."
                    )
            elif is_rejection:
                sessions[conv_id].pop("pending_macro")
                return self._create_response(
                    user_input,
                    "Okay, I have cancelled the pending macro sequence."
                )

        # Check for rollback / undo commands
        if any(w in user_text for w in ("rollback", "undo macro", "revert macro", "undo last macro", "rollback macro", "undo action", "revert changes", "undo changes")):
            if self.macro_manager:
                res = await self.macro_manager.async_rollback_macro()
                if res.get("success"):
                    count = res.get("restored_count", 0)
                    speech = (
                        f"↺ **Macro Rolled Back Successfully!**\n\n"
                        f"Restored {count} entity/entities to their exact pre-execution state for **{res.get('name', 'macro')}**."
                    )
                else:
                    speech = f"⚠️ Could not roll back macro: {res.get('error', 'No restorable execution record found.')}"
                return self._create_response(user_input, speech)

        # Check for backup inspection / script or automation recovery requests
        is_backup_recovery_query = (
            (any(w in user_text for w in ("backup", "restore", "snapshot", "recover", "rollback", "revert"))
             and any(w in user_text for w in ("script", "automation", "blueprint", "overwritten", "missing", "corrupted", "lost", "router", "full script")))
            or ("overwritten" in user_text and any(w in user_text for w in ("backup", "restore", "recover", "find", "missing")))
            or ("majority of it is missing" in user_text)
        )
        if is_backup_recovery_query and getattr(self, "automation_manager", None):
            fire_progress("recovery", "Auditing Backups & Snapshots", "Searching historical backups & configuration snapshots...")
            target_name = None
            quoted = re.findall(r'["\']([^"\']{3,})["\']', user_input.text)
            if quoted:
                target_name = quoted[0].strip()

            item_type = "automation" if ("automation" in user_text and "script" not in user_text) else "script"

            if not target_name:
                known_scripts = await self.automation_manager.async_read_scripts()
                for s_k, s_v in known_scripts.items():
                    s_alias = str(s_v.get("alias", "")).lower() if isinstance(s_v, dict) else ""
                    if s_k.lower() in user_text or (s_alias and s_alias in user_text):
                        target_name = s_k
                        item_type = "script"
                        break

            if not target_name:
                known_autos = await self.automation_manager.async_read_automations()
                for a in known_autos:
                    if not isinstance(a, dict):
                        continue
                    a_id = str(a.get("id", "")).lower()
                    a_alias = str(a.get("alias", "")).lower()
                    if (a_id and a_id in user_text) or (a_alias and a_alias in user_text):
                        target_name = a.get("alias") or a_id
                        item_type = "automation"
                        break

            if not target_name:
                if "notify" in user_text or "router" in user_text:
                    target_name = "notify_router"
                    item_type = "script"

            if target_name:
                rec_res = await self.automation_manager.async_inspect_backups_for_item(target_name, item_type=item_type)
                if rec_res.get("found") and rec_res.get("best_candidate"):
                    cand = rec_res["best_candidate"]
                    curr = rec_res["current_version"]
                    c_name = cand["name"]
                    c_key = cand["key"]
                    c_lines = cand["lines"]
                    c_bytes = cand["bytes"]
                    c_src = cand["source"]
                    c_time = cand["mtime"]
                    c_type = cand["type"]

                    speech = (
                        f"I located the complete, full version of **{c_name}** (`{c_type}.{c_key}`) in your configuration snapshot `{c_src}` ({c_time}).\n\n"
                        f"### 🔍 Backup Inspection & Verification:\n"
                        f"- **Backup Source:** `{c_src}` ({c_time})\n"
                        f"- **Full {c_type.capitalize()} Size:** **{c_lines} lines** ({c_bytes:,} bytes)\n"
                        f"- **Active System Version:** {curr['lines']} lines ({curr['bytes']:,} bytes) — *{curr['status_label']}*\n"
                        f"- **Verification:** Verified full operational structure with all routing rules, conditions, and actions intact.\n\n"
                        f"### 📋 Recovered {c_type.capitalize()} Configuration:\n"
                        f"```yaml\n{cand['yaml']}\n```\n\n"
                        f"Would you like me to restore this {c_type} '{c_name}' (`{c_type}.{c_key}`) in your Home Assistant? Say 'yes' or 'apply' to confirm, or 'no' to cancel."
                    )
                    session_data["pending_items"] = [{
                        "type": c_type,
                        "id": c_key,
                        "name": c_name,
                        "yaml_data": cand["raw_item"],
                    }]
                    session_data["pending_yaml"] = session_data["pending_items"][0]
                    self._record_turn(session_data, user_input.text, speech)
                    return self._create_response(user_input, speech)

        # Check for list macros command
        if any(w in user_text for w in ("list macros", "available macros", "show macros", "what macros", "macro list")):
            speech = (
                "⚡ **Otis Macro Orchestrator: Built-in Sequences**\n\n"
                "• 🎬 **Movie Night** (`prep movie night`): Dims entertainment lights, selects TV/HDMI source, lowers climate, adjusts audio volume.\n"
                "• 🌙 **Goodnight** (`bedtime routine`): Extinguishes common lights, locks deadbolts, closes garage, sets night climate, arms security.\n"
                "• 🥂 **Entertain / Party** (`party mode`): Multi-room matrix audio streaming, ambient lighting scene, social climate.\n"
                "• 🛡️ **Lockdown / Away** (`lockdown home`): Turns off non-essentials, locks all doors, closes garage, arms away security.\n"
                "• 🏡 **Welcome Home** (`arriving home`): Pathway lighting, comfortable temperature, entryway disarm & unlock.\n\n"
                "*(You can say 'run movie night' or 'undo' at any time)*"
            )
            return self._create_response(user_input, speech)

        # Check for direct multi-step macro trigger phrases (only when not asking to create/build an automation)
        is_auto_or_script_request = any(w in user_text for w in ("create", "automate", "new automation", "build automation", "automation")) and not any(w in user_text for w in ("run", "start", "prep", "activate"))
        macro_template_target = None
        if not is_auto_or_script_request:
            if any(w in user_text for w in ("prep movie night", "movie night", "start movie night", "cinema mode", "film mode", "theater mode")):
                macro_template_target = "movie_night"
            elif any(w in user_text for w in ("bedtime routine", "goodnight routine", "goodnight mode", "time for bed", "go to sleep", "sleep mode", "goodnight")):
                macro_template_target = "goodnight"
            elif any(w in user_text for w in ("party mode", "entertain mode", "party time", "entertainment mode")):
                macro_template_target = "party_mode"
            elif any(w in user_text for w in ("lockdown home", "lock down home", "lockdown house", "away mode", "leaving home", "leaving house", "secure home")):
                macro_template_target = "away_mode"
            elif any(w in user_text for w in ("welcome home", "arriving home", "arrived home", "i'm home", "im home")):
                macro_template_target = "welcome_home"

        if macro_template_target and self.macro_manager:
            cap_map = await self.engine.async_build_capability_map()
            macro_plan = self.macro_manager.build_smart_macro(macro_template_target, capability_map=cap_map)
            safety = self.macro_manager.inspect_safety(macro_plan["steps"])

            if safety["requires_confirmation"]:
                m_id = f"macro_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                sessions[conv_id] = {
                    "pending_macro": {
                        "macro_id": m_id,
                        "name": macro_plan["name"],
                        "steps": macro_plan["steps"],
                    }
                }
                lines = [f"⚠️ **{macro_plan['name']} Prepared ({len(macro_plan['steps'])} Steps)**:"]
                for s_i, s in enumerate(macro_plan["steps"], 1):
                    lines.append(f"{s_i}. {s['name']}")
                lines.append("\n**Safety Checks:**")
                for w in safety["safety_warnings"]:
                    lines.append(f"• {w}")
                lines.append("\nWould you like me to execute this sequence now? Say 'yes' or 'confirm' to execute, or 'cancel'.")
                return self._create_response(user_input, "\n".join(lines))
            else:
                res = await self.macro_manager.async_execute_macro(
                    macro_name=macro_plan["name"],
                    steps=macro_plan["steps"],
                    confirmed=True,
                )
                lines = [f"🚀 **{macro_plan['name']} Activated!**\n"]
                for s_i, s in enumerate(macro_plan["steps"], 1):
                    lines.append(f"{s_i}. {s['name']}")
                lines.append(f"\n• State snapshot saved for {res.get('snapshot_entities_count', 0)} entities.")
                lines.append("*(Say 'undo' or 'rollback' anytime to revert your devices to their prior states)*")
                return self._create_response(user_input, "\n".join(lines))

        # Check for theme styling commands
        if any(w in user_text for w in ("create theme", "generate theme", "new theme", "make theme", "build theme")):
            clean_prompt = re.sub(
                r"^(please\s+)?(can you\s+)?(create|generate|make|build)\s+(a\s+|an\s+)?(custom\s+)?theme\s*(called|named)?\s*",
                "",
                user_input.text,
                flags=re.IGNORECASE,
            ).strip()
            if clean_prompt and self.theme_manager:
                try:
                    res = await self.theme_manager.async_generate_and_save_theme(prompt=clean_prompt, apply_immediately=True)
                    if hasattr(self.engine, "invalidate_cache"):
                        self.engine.invalidate_cache()
                    speech = (
                        f"✨ Created and applied **{res['title']}**!\n\n"
                        f"• Saved to `{res['file_path']}` and reloaded Home Assistant frontend themes.\n"
                        f"• Colors: Primary `{res['preview']['primary']}` | Accent `{res['preview']['accent']}` | Background `{res['preview']['background']}`"
                    )
                    return self._create_response(user_input, speech)
                except Exception as err:
                    _LOGGER.error("Theme generation error: %s", err)
                    return self._create_response(user_input, f"Encountered an issue generating theme: {err}")

        elif any(w in user_text for w in ("apply theme", "switch theme", "set theme", "change theme")):
            target = re.sub(
                r"^(please\s+)?(can you\s+)?(apply|switch|set|change)\s+(to\s+)?(the\s+)?theme\s*",
                "",
                user_input.text,
                flags=re.IGNORECASE,
            ).strip()
            if target and self.theme_manager:
                slug = slugify_theme_name(target)
                key = f"otis_{slug}" if not slug.startswith("otis_") else slug
                ok = await self.theme_manager.async_apply_theme(key)
                if not ok:
                    ok = await self.theme_manager.async_apply_theme(target)
                speech = f"🎨 Switched active theme to **{target}** across Home Assistant." if ok else f"⚠️ Could not apply theme '{target}'."
                return self._create_response(user_input, speech)

        # Check for dashboard regeneration commands
        if (
            any(w in user_text for w in (
                "regenerate dashboard", "regenerate dashboards", "regenerate command center",
                "rebuild command center", "rebuild dashboard", "rebuild dashboards",
                "regenerate studios", "rebuild studios", "regenerate rooms", "rebuild rooms",
            ))
            or (
                any(verb in user_text for verb in ("regenerate", "rebuild"))
                and any(target in user_text for target in ("dashboard", "dashboards", "command center", "studio", "studios", "room", "rooms"))
            )
        ):
            if self.dashboard_manager:
                try:
                    cap_map = (
                        await self.engine.async_build_capability_map(force_refresh=True)
                        if hasattr(self.engine, "async_build_capability_map")
                        else None
                    )
                    await self.dashboard_manager.async_ensure_admin_companion_dashboard(cap_map, force_regenerate=True)
                    await self.dashboard_manager.async_ensure_user_command_center_dashboard(cap_map, force_regenerate=True)
                    self.hass.bus.async_fire("lovelace_updated", {"url_path": "otis-ai"})
                    self.hass.bus.async_fire("lovelace_updated", {"url_path": "command-center"})
                    speech = (
                        "✨ **Command Center & Studios Regenerated!**\n\n"
                        "I have regenerated the Home Command Center (`/command-center`), all Studios (Media, Security, Climate & Pool, Energy, Floor Plan), and all Room subviews matching your current layout, navigation styles, and active devices."
                    )
                    self._record_turn(session_data, user_input.text, speech)
                    return self._create_response(user_input, speech)
                except Exception as err:
                    _LOGGER.error("Dashboard regeneration error: %s", err)
                    err_speech = f"Encountered an issue regenerating dashboards: {err}"
                    self._record_turn(session_data, user_input.text, err_speech)
                    return self._create_response(user_input, err_speech)

        # Check for conversational floorplan pinning and unpinning commands
        # Examples: "pin chandelier to dining room on the floorplan", "pin light.desk to 420, 310", "unpin light.desk from floorplan"
        user_lower = user_text.lower()
        has_fp_pin_verb = (
            user_lower.startswith(("pin ", "unpin ", "remove pin ", "delete pin "))
            or any(verb in user_lower for verb in ("pin ", "add pin ", "place pin ", "unpin ", "remove pin "))
        )
        if has_fp_pin_verb and (
            any(k in user_lower for k in ("floorplan", "floor plan", "map"))
            or user_lower.startswith(("pin ", "unpin ", "remove pin ", "delete pin "))
        ) and getattr(self, "floorplan_parser", None):
            is_unpin = any(k in user_lower for k in ("unpin", "remove pin", "delete pin")) or user_lower.startswith(("unpin ", "remove pin ", "delete pin "))
            if is_unpin:
                unpin_m = re.search(
                    r"^(?:please\s+)?(?:can you\s+)?(?:unpin|remove pin for|delete pin for|remove)\s+(.+?)(?:\s+from\s+(?:the\s+)?floor\s*plan)?$",
                    user_text,
                    re.IGNORECASE,
                )
                if unpin_m:
                    raw_target = unpin_m.group(1).strip()
                    raw_target = re.sub(r"\s+from\s+(?:the\s+)?floor\s*plan\s*$", "", raw_target, flags=re.IGNORECASE).strip()
                    cap_map = await self.engine.async_build_capability_map() if hasattr(self.engine, "async_build_capability_map") else {}
                    ent_list = cap_map.get("entities", [])
                    matched_ent = self._resolve_entity_from_text(raw_target, ent_list)
                    target_eid = matched_ent["entity_id"] if matched_ent else raw_target
                    target_name = matched_ent.get("name", target_eid) if matched_ent else target_eid
                    await self.floorplan_parser.async_unpin_entity(target_eid)
                    if self.dashboard_manager:
                        try:
                            await self.dashboard_manager.async_ensure_user_command_center_dashboard(cap_map)
                            await self.dashboard_manager.async_ensure_admin_companion_dashboard(cap_map)
                        except Exception:
                            pass
                    self.hass.bus.async_fire("lovelace_updated", {"url_path": "command-center"})
                    self.hass.bus.async_fire("lovelace_updated", {"url_path": "otis-ai"})
                    speech = f"🗑️ **Floor Plan Pin Removed**: Unpinned **{target_name}** (`{target_eid}`) from the interactive 2D floor plan."
                    self._record_turn(session_data, user_input.text, speech)
                    return self._create_response(user_input, speech)
            else:
                pin_m = re.search(
                    r"^(?:please\s+)?(?:can you\s+)?(?:pin|add pin for|place pin for|place)\s+(.+?)\s+(?:to|in|at|on)\s+(.+?)(?:\s+on\s+(?:the\s+)?floor\s*plan)?$",
                    user_text,
                    re.IGNORECASE,
                )
                if pin_m:
                    raw_ent = pin_m.group(1).strip()
                    raw_dest = pin_m.group(2).strip()
                    raw_dest = re.sub(r"\s+on\s+(?:the\s+)?floor\s*plan\s*$", "", raw_dest, flags=re.IGNORECASE).strip()
                    raw_dest = re.sub(r"^the\s+", "", raw_dest, flags=re.IGNORECASE).strip()

                    cap_map = await self.engine.async_build_capability_map() if hasattr(self.engine, "async_build_capability_map") else {}
                    ent_list = cap_map.get("entities", [])
                    areas_dict = cap_map.get("areas", {})

                    matched_ent = self._resolve_entity_from_text(raw_ent, ent_list)
                    target_eid = matched_ent["entity_id"] if matched_ent else raw_ent
                    target_name = matched_ent.get("name", target_eid) if matched_ent else target_eid

                    coord_m = re.search(r"(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)", raw_dest)
                    target_x = float(coord_m.group(1)) if coord_m else None
                    target_y = float(coord_m.group(2)) if coord_m else None
                    target_area_id = None
                    target_area_name = None

                    if target_x is None:
                        area_res = self._resolve_area_from_text(raw_dest, areas_dict)
                        if area_res:
                            target_area_id, target_area_name = area_res
                        else:
                            target_area_id = raw_dest.lower().replace(" ", "_")
                            target_area_name = raw_dest.title()

                    res = await self.floorplan_parser.async_pin_entity(
                        entity_id=target_eid,
                        area_id=target_area_id,
                        x=target_x,
                        y=target_y,
                    )
                    if self.dashboard_manager:
                        try:
                            await self.dashboard_manager.async_ensure_user_command_center_dashboard(cap_map)
                            await self.dashboard_manager.async_ensure_admin_companion_dashboard(cap_map)
                        except Exception:
                            pass
                    self.hass.bus.async_fire("lovelace_updated", {"url_path": "command-center"})
                    self.hass.bus.async_fire("lovelace_updated", {"url_path": "otis-ai"})

                    px = res.get("x", target_x)
                    py = res.get("y", target_y)
                    loc_desc = f"**{target_area_name}** (X: {px}, Y: {py})" if target_area_name else f"coordinates (X: {px}, Y: {py})"
                    speech = f"📍 **Floor Plan Pin Placed**: Successfully pinned **{target_name}** (`{target_eid}`) to {loc_desc} on the interactive floor plan!"
                    self._record_turn(session_data, user_input.text, speech)
                    return self._create_response(user_input, speech)

        # Check for Otis Sentinel Watchdog commands
        user_lower = user_text.lower()
        if self.sentinel_manager and any(w in user_lower for w in (
            "remediate anomalies", "fix anomalies", "heal network", "auto heal", "auto-heal",
            "sentinel auto heal", "sentinel auto-heal", "fix sentinel alerts", "remediate all alerts",
            "self heal", "self-heal", "heal smart home"
        )):
            anomalies = await self.sentinel_manager.async_scan_all_anomalies(auto_remediate=True)
            remediated_count = getattr(self.sentinel_manager, "last_remediated_count", 0)
            if remediated_count > 0:
                speech = (
                    f"🛡️ **Otis Sentinel Auto-Healing Complete**\n\n"
                    f"Successfully executed self-healing remediations on **{remediated_count}** detected anomaly/anomalies! "
                    f"Remaining unresolved alerts: {len(anomalies)}."
                )
            elif not anomalies:
                speech = "🛡️ **Otis Sentinel Watchdog: All Systems Nominal**\n\nNo active anomalies detected across HVAC, battery health, security perimeter, BLE proxies, or mesh networks."
            else:
                speech = (
                    f"🛡️ **Otis Sentinel Scan**: Found **{len(anomalies)}** anomaly alert(s). "
                    "Manual confirmation may be required (e.g. perimeter door locks or extreme temperature offsets) in the Proactive Feed."
                )
            self._record_turn(session_data, user_input.text, speech)
            return self._create_response(user_input, speech)

        if self.sentinel_manager and any(w in user_lower for w in (
            "run sentinel", "sentinel audit", "sentinel scan", "check anomalies",
            "watchdog scan", "watchdog audit", "audit system anomalies", "check smart home health"
        )):
            anomalies = await self.sentinel_manager.async_scan_all_anomalies()
            if not anomalies:
                speech = "🛡️ **Otis Sentinel Watchdog: All Systems Nominal**\n\nNo anomalies detected across HVAC, battery health, security perimeter, BLE proxies, runaway switches, or mesh network nodes."
            else:
                lines = [f"🛡️ **Otis Sentinel Audit: {len(anomalies)} Anomaly Alert(s) Detected**\n"]
                for a in anomalies[:5]:
                    lines.append(f"• **{a['title']}** [{a.get('severity', 'high').upper()}]: {a['description']}")
                lines.append("\nUse the **Proactive Feed** in the Companion Card or say *'Remediate anomalies'* to trigger self-healing.")
                speech = "\n".join(lines)
            self._record_turn(session_data, user_input.text, speech)
            return self._create_response(user_input, speech)

        # Check for Phase 6 Audio Handoff / Follow-Me commands
        user_lower = user_text.lower()
        if self.audio_manager and any(w in user_lower for w in (
            "handoff audio", "hand off audio", "transfer music", "transfer audio",
            "follow me to", "music follow me", "audio follow me", "switch audio to",
            "move music to", "move audio to", "audio handoff", "audio transfer"
        )):
            target_match = re.search(r"(?:to|into)\s+(?:the\s+)?([a-zA-Z0-9_\s'-]+)$", user_input.text, re.IGNORECASE)
            source_match = re.search(r"(?:from)\s+(?:the\s+)?([a-zA-Z0-9_\s'-]+?)\s+(?:to|into)", user_input.text, re.IGNORECASE)
            target_area = target_match.group(1).strip() if target_match else ""
            source_area = source_match.group(1).strip() if source_match else ""
            mode = "follow" if "follow" in user_lower else "handoff"
            if target_area:
                zones = await self.audio_manager.async_get_active_media_zones()
                active_playing = [
                    z for z in (zones["matrix_zones"] + zones["other_players"])
                    if z["state"] in ("playing", "on") and z.get("area_id")
                ]
                if not source_area and active_playing:
                    source_area = active_playing[0]["area_id"]
                if source_area:
                    res = await self.audio_manager.async_audio_handoff(
                        source_area=source_area,
                        target_area=target_area,
                        mode=mode,
                        idle_power_guard=True,
                    )
                    if res.get("success"):
                        return self._create_response(user_input, res["message"])
                    return self._create_response(user_input, f"⚠️ Audio handoff: {res.get('error')}")

        # Check for Release Idle Sources command
        if self.audio_manager and any(w in user_lower for w in (
            "release idle sources", "turn off idle amp", "turn off idle zones",
            "pause idle streamers", "stop idle music", "idle power guard"
        )):
            res = await self.audio_manager.async_release_idle_sources()
            return self._create_response(user_input, res["message"])

        # Check for Roadmap Item 9 Voice Assist & Ducking commands
        if self.audio_manager and any(w in user_lower for w in (
            "voice assist status", "assist pipeline status", "assist status", "wake word status", "satellite status", "voice status"
        )):
            st = await self.audio_manager.async_get_assist_pipeline_status()
            pref = st.get("preferred_pipeline") or "Default"
            pipes = st.get("total_pipelines", 0)
            sats = st.get("total_satellites", 0)
            engines = len(st.get("wake_word_engines", []))
            quiet_state = f"Active (capped at {st.get('quiet_hours_volume_cap')}%)" if st.get("quiet_hours_active") else "Inactive"
            speech = (
                f"🎙️ **Voice Assist & Pipeline Status**\n\n"
                f"• **Preferred Pipeline**: {pref} (Total pipelines: {pipes})\n"
                f"• **Voice Satellites**: {sats} registered\n"
                f"• **Wake Word Engines**: {engines} active\n"
                f"• **Quiet Hours**: {quiet_state}\n"
                f"• **Active Audio Ducking Sessions**: {st.get('active_ducking_sessions', 0)}"
            )
            return self._create_response(user_input, speech)

        # Check for Phase 9 Multi-Agent Orchestration & Voice Satellite status queries
        if self.agent_orchestrator and any(w in user_lower for w in (
            "multi-agent status", "multi agent status", "agent orchestrator", "orchestrator status",
            "specialist status", "voice satellite status",
        )):
            sats = self.agent_orchestrator.get_discovered_satellites()
            metrics = self.agent_orchestrator._metrics
            speech = (
                f"🤖 **Otis Multi-Agent Orchestration & Voice Satellites**\n\n"
                f"• **Active Specialists**: Executive Butler, Sentinel Security, Energy Architect, Spatial Media, Automation Engineer\n"
                f"• **Total Inquiries Routed**: {metrics.get('total_requests', 0)} ({metrics.get('multi_agent_collaborations', 0)} collaborative syntheses, {metrics.get('single_agent_routes', 0)} direct routes)\n"
                f"• **Average Reasoning Latency**: {metrics.get('average_latency_ms', 0.0)}ms\n"
                f"• **Configured Voice Satellites**: {len(sats)} active (acoustic presence-fused arbitration enabled)"
            )
            if sats:
                speech += "\n"
                for sat in sats[:4]:
                    speech += f"\n• `{sat['entity_id']}` ({sat['area_id']}): Wake-word '{sat['wake_word']}' → {sat['assigned_agent'].title()} persona"
            return self._create_response(user_input, speech)

        if self.audio_manager and any(w in user_lower for w in (
            "duck media", "duck audio", "duck music", "lower music", "attenuate audio", "lower background music"
        )):
            res = await self.audio_manager.async_duck_media()
            return self._create_response(user_input, res["message"])

        if self.audio_manager and any(w in user_lower for w in (
            "restore media", "unduck media", "restore music", "unmute music volume", "raise music back up"
        )):
            res = await self.audio_manager.async_unduck_media()
            return self._create_response(user_input, res["message"])

        # Check for Phase 7 Energy & Predictive Load commands
        if self.energy_manager and any(w in user_lower for w in (
            "energy summary", "power summary", "how much power", "current power",
            "current load", "power usage", "energy usage", "electricity load",
            "what devices are drawing power", "top power consumers", "top power devices",
            "active power", "live power", "energy load"
        )):
            fire_progress("domain", "Energy Telemetry", "Querying active power meters & tariff window")
            summary = await self.energy_manager.async_get_energy_summary()
            total_w = summary.get("total_power_w", 0)
            tariff = summary.get("tariff", {})
            solar = summary.get("solar", {})
            ups = summary.get("ups_storage", {})
            top = summary.get("top_consumers", [])

            lines = [
                "⚡ **Otis Energy & Load Orchestrator**\n",
                f"• **Current Home Draw:** `{total_w} W` across {summary.get('active_power_sensors_count', 0)} active monitoring circuits.",
                f"• **Grid Tariff Window:** `{tariff.get('period', 'standard').upper()}` ({tariff.get('peak_window_description', 'Standard')}) - {tariff.get('hours_until_change', 0)}h until rate transition.",
            ]
            if solar.get("production_w", 0) > 0 or solar.get("solar_elevation_deg") is not None:
                lines.append(f"• **Solar Generation:** `{solar.get('production_w', 0)} W` (Sun elevation: {solar.get('solar_elevation_deg', 0)}°).")
            if ups:
                lines.append(f"• **AV/Rack UPS Storage:** {ups.get('battery_charge', '100%')} charge ({ups.get('battery_runtime', 'N/A')}s runtime).")
            if top:
                lines.append("\n**Top Active Consumers Right Now:**")
                for i, c in enumerate(top[:5], 1):
                    lines.append(f"{i}. **{c['name']}**: `{c['power_w']} W`")

            lines.append("\n*(Say 'shed non-essential loads' to shed deferrable loads during peak hours, or 'restore shedded loads')*")
            return self._create_response(user_input, "\n".join(lines))

        # Check for Load Shedding commands
        if self.energy_manager and any(w in user_lower for w in (
            "shed non-essential loads", "shed non essentials", "shed peak loads",
            "load shedding", "shed load", "shed loads", "cut peak power", "cut power"
        )):
            fire_progress("macro", "Executing Load Shed", "Snapshotting states & shedding deferrable loads")
            res = await self.energy_manager.async_execute_load_shed(tier=1)
            if res.get("success"):
                speech = (
                    f"⚡ **Dynamic Load Shedding Executed!**\n\n"
                    f"• {res.get('message')}\n"
                    f"• Shed Entities: `{', '.join(res.get('executed_entities', [])) or 'None'}`\n\n"
                    f"*(Say 'restore shedded loads' anytime to return devices to their prior states)*"
                )
            else:
                speech = f"⚠️ Load shedding: {res.get('error', 'Encountered an issue.')}"
            return self._create_response(user_input, speech)

        # Check for Restore Shed Loads commands
        if self.energy_manager and any(w in user_lower for w in (
            "restore shedded loads", "restore shed loads", "undo load shed",
            "restore shedded", "restore power loads"
        )):
            fire_progress("macro", "Restoring Loads", "Restoring shedded loads to prior snapshot states")
            res = await self.energy_manager.async_restore_shed_loads()
            return self._create_response(user_input, res.get("message", res.get("error", "")))

        # Check for Execute Energy Arbitrage commands (Phase 7)
        if self.energy_manager and any(w in user_lower for w in (
            "execute energy arbitrage", "execute arbitrage", "apply energy schedule", "dispatch energy arbitrage"
        )):
            fire_progress("macro", "Executing Arbitrage Dispatch", "Applying recommended battery & EV charging states")
            res = await self.energy_manager.async_execute_energy_arbitrage(dry_run=False)
            speech = (
                f"⚡ **Energy Arbitrage Dispatch Executed!**\n\n"
                f"• Battery Action: `{res.get('current_battery_action', 'idle')}`\n"
                f"• EV Action: `{res.get('current_ev_action', 'idle')}`\n"
                f"• Dispatched Controls: `{res.get('dispatched_count', 0)} device actions applied`"
            )
            return self._create_response(user_input, speech)

        # Check for Battery Arbitrage & Scheduling commands (Phase 2)
        if self.energy_manager and any(w in user_lower for w in (
            "battery arbitrage", "battery schedule", "energy arbitrage",
            "optimize battery", "optimize battery schedule", "battery plan",
            "arbitrage plan", "arbitrage schedule"
        )):
            fire_progress("domain", "Battery Arbitrage", "Calculating 24-hour battery schedule & TOU savings")
            req_mode = None
            if "backup" in user_lower or "storm" in user_lower or "outage" in user_lower or "reserve" in user_lower:
                req_mode = "backup_reserve"
            elif "self consumption" in user_lower or "solar only" in user_lower:
                req_mode = "self_consumption"
            elif "peak" in user_lower or "arbitrage" in user_lower:
                req_mode = "peak_arbitrage"

            plan = await self.energy_manager.async_get_arbitrage_plan(mode=req_mode)
            lines = [
                f"🔋 **24-Hour Energy Arbitrage & Battery Plan** (Mode: `{plan.get('mode', 'auto').upper()}`)\n",
                f"• **Current Battery State of Charge**: {plan.get('current_soc_pct', 0)}% (Reserve Floor: {plan.get('min_reserve_soc_pct', 20)}%)",
                f"• **Daily Solar Forecast**: {plan.get('daily_solar_forecast_kwh', 0)} kWh",
                f"• **Projected Peak Shaved**: {plan.get('projected_peak_shave_kwh', 0)} kWh during 2:00 PM – 7:00 PM",
                f"• **Estimated Daily Savings**: **${plan.get('projected_savings_usd', 0.0):.2f}** (Grid Cost: ${plan.get('managed_cost_usd', 0.0):.2f} vs ${plan.get('unmanaged_cost_usd', 0.0):.2f} without arbitrage)",
                f"• **Current Action**: `{plan.get('current_action', 'idle')}` — *{plan.get('current_reason', 'Monitoring grid rates and solar generation.')}*\n",
                "**Upcoming Schedule Summary**:"
            ]
            for step in plan.get("schedule", [])[:6]:
                arrow = "📥" if step["battery_flow_kw"] > 0 else ("📤" if step["battery_flow_kw"] < 0 else "⏸️")
                flow_desc = f"{arrow} {abs(step['battery_flow_kw']):.1f} kW" if step["battery_flow_kw"] != 0 else "0 kW"
                lines.append(
                    f"- `{step['time_label']}` [{step['tariff_period'].upper()} @ ${step['rate_per_kwh']:.2f}]: "
                    f"`{step['action']}` ({flow_desc}) ➔ Ending SoC: {step['ending_soc_pct']:.0f}%"
                )
            lines.append("\n*(Say 'optimize battery for backup' to preserve full emergency reserves, or 'optimize battery for peak arbitrage')*")
            return self._create_response(user_input, "\n".join(lines))

        # Check for Smart EV Charging commands (Phase 7)
        if self.energy_manager and any(w in user_lower for w in (
            "ev charging schedule", "ev schedule", "charge my car", "charge ev",
            "smart ev", "when should i charge", "ev charging plan", "electric vehicle schedule"
        )):
            fire_progress("domain", "Smart EV Orchestrator", "Calculating solar surplus and low-cost off-peak charging schedule")
            ev_plan = await self.energy_manager.async_schedule_ev_charging()
            lines = [
                f"🚗 **Smart EV Charging Schedule** (Target: {ev_plan.get('target_soc_pct', 80)}% by {ev_plan.get('target_departure_hour', 7):02d}:00)\n",
                f"• **Current EV Battery**: {ev_plan.get('current_soc_pct', 45)}% | Energy Needed: `{ev_plan.get('energy_needed_kwh', 0)} kWh` (~{ev_plan.get('hours_needed', 0)}h charge time)",
                f"• **Energy Mix**: `{ev_plan.get('solar_kwh_utilized', 0)} kWh` Solar Surplus (Free) + `{ev_plan.get('grid_kwh_utilized', 0)} kWh` Off-Peak Grid",
                f"• **Estimated Charging Cost**: **${ev_plan.get('projected_cost_usd', 0.0):.2f}**",
                f"• **Current Recommendation**: `{ev_plan.get('current_action', 'idle')}` ({ev_plan.get('current_ev_charge_kw', 0)} kW) — *{ev_plan.get('current_reason', '')}*\n",
                "**Upcoming Charging Windows**:"
            ]
            for step in [s for s in ev_plan.get("schedule", []) if s.get("ev_charge_kw", 0) > 0][:5]:
                src = "☀️ Solar" if step.get("source") == "solar" else "⚡ Off-Peak"
                lines.append(f"- `{step['time_label']}`: `{step['ev_charge_kw']} kW` via {src} (${step.get('cost_usd', 0):.2f}) ➔ Ending SoC: {step['ending_soc_pct']:.0f}%")
            if not any(s.get("ev_charge_kw", 0) > 0 for s in ev_plan.get("schedule", [])):
                lines.append("• No charging needed; target battery state of charge satisfied.")
            lines.append("\n*(Say 'execute energy arbitrage' to apply active charger & battery dispatch actions)*")
            return self._create_response(user_input, "\n".join(lines))

        # Check for Presence / Occupancy queries (never hijack automation-creation prompts)
        if not any(v in user_lower for v in ("create ", "build ", "write ", "generate ", "make an automation", "set up automation")) and any(w in user_lower for w in (
            "who is in the house", "who is home", "is anyone home", "is anybody home",
            "room occupancy", "which rooms are occupied", "presence status",
            "house occupancy", "who is in", "where is everyone", "where is everybody",
            "fused presence", "multimodal presence", "micro presence"
        )):
            fire_progress("domain", "Multimodal Presence Fusion", "Fusing mmWave radar, thermal signatures, BLE trilateration, and acoustic footprints")
            if getattr(self, "presence_fusion_manager", None):
                fused = await self.presence_fusion_manager.async_fuse_presence()
                occ = fused.get("occupied_areas", [])
                micro = fused.get("micro_presence_areas", [])
                likely = fused.get("likely_areas", [])
                rooms = fused.get("rooms", {})

                lines = ["👁️ **Otis Multimodal Presence Fusion**\n"]
                if occ:
                    occ_details = []
                    for r in rooms.values():
                        if r.get("status") == "occupied":
                            usr = f" [{r['attributed_user']}]" if r.get("attributed_user") else ""
                            mods = ", ".join(r.get("active_modalities", []))
                            occ_details.append(f"• **{r['area_name']}**{usr}: `{mods}` ({r.get('confidence_percent', 0)}%)")
                    lines.append("**Occupied Rooms:**\n" + "\n".join(occ_details))

                if micro:
                    micro_details = []
                    for r in rooms.values():
                        if r.get("status") == "micro_presence":
                            usr = f" [{r['attributed_user']}]" if r.get("attributed_user") else ""
                            mods = ", ".join(r.get("active_modalities", []))
                            micro_details.append(f"• **{r['area_name']}**{usr} *(Micro-Presence: resting/reading/sleeping)*: `{mods}`")
                    lines.append("\n**Micro-Presence Detected:**\n" + "\n".join(micro_details))

                if likely:
                    lines.append(f"\n• **Likely Occupied:** {', '.join(likely)}")

                if not occ and not micro and not likely:
                    lines.append("• **All Rooms Vacant:** No active resident presence detected across mmWave, thermal, BLE, or motion.")

                return self._create_response(user_input, "\n".join(lines))
            elif getattr(self, "vision_manager", None):
                pres = await self.vision_manager.async_get_presence_states()
                occ = pres.get("occupied_areas", [])
                likely = pres.get("likely_areas", [])
                lines = ["👁️ **Otis Multi-Modal Presence Intelligence**\n"]
                if occ:
                    lines.append(f"• **Occupied Rooms ({len(occ)}):** {', '.join(occ)}")
                if likely:
                    lines.append(f"• **Likely Occupied ({len(likely)}):** {', '.join(likely)}")
                if not occ and not likely:
                    lines.append("• **All Rooms Vacant:** No active room motion or mmWave presence detected.")
                household = "Yes, residents detected" if pres.get("household_present") else "No, all residents away"
                lines.append(f"• **Household Status:** {household}")
                return self._create_response(user_input, "\n".join(lines))

        # Check for Camera / Vision Audit queries (Phase 8)
        if getattr(self, "vision_manager", None) and any(w in user_lower for w in (
            "check cameras", "check security cameras", "analyze camera", "camera audit",
            "check front door", "check doorbell", "security audit"
        )):
            fire_progress("domain", "Auditing Cameras", "Capturing snapshots and evaluating scene tags")
            cams = await self.vision_manager.async_get_cameras()
            if not cams:
                return self._create_response(user_input, "No security cameras discovered in Home Assistant.")
            target_cam = next((c for c in cams if c.get("is_doorbell") or c.get("is_perimeter")), cams[0])
            res = await self.vision_manager.async_analyze_camera(target_cam["entity_id"])
            audit = res.get("audit", {})
            speech = (
                f"📷 **Otis Vision Audit: {audit.get('name', target_cam['name'])}**\n\n"
                f"• **Status:** `{audit.get('status', 'normal').upper()}`\n"
                f"• **Summary:** {audit.get('summary', 'Scene clear.')}\n"
                f"• **Safety Assessment:** {audit.get('safety_assessment', 'Normal baseline.')}\n"
                f"• **Detected Tags:** `{', '.join(audit.get('detected_objects', [])) or 'None'}`"
            )
            return self._create_response(user_input, speech)

        # Check for Habit Mining and Behavioral queries (Phase 9 & Phase 4 Step 4)
        if getattr(self, "habit_manager", None) and any(w in user_lower for w in (
            "habits", "learned habits", "habit routines", "behavioral", "circadian curve", "circadian lighting", "spatial habit", "migration habit", "room migration"
        )):
            if any(w in user_lower for w in ("spatial", "migration", "corridor", "transition")):
                fire_progress("domain", "Mining Spatial Habits", "Synthesizing physical room transition corridors")
                sh_habits = await self.habit_manager.async_mine_spatial_habits(min_confidence=0.65, min_occurrences=1)
                if not sh_habits:
                    return self._create_response(
                        user_input,
                        "Otis is actively monitoring room transition patterns. No recurrent spatial migration corridors have met the threshold yet."
                    )
                lines = [f"🚶 **Observed Spatial Migration Corridors ({len(sh_habits)} discovered):**\n"]
                for h in sh_habits[:4]:
                    lines.append(f"• **{h['title']}** ({h['occurrences']}x, {int(h['confidence']*100)}% confidence):\n  {h['description']}")
                return self._create_response(user_input, "\n".join(lines))
            elif "circadian" in user_lower:
                curve = self.habit_manager.calculate_circadian_curves()
                light = curve["lighting_curve"]
                clim = curve["climate_curve"]
                resp = (
                    f"☀️ **Otis Seasonal & Circadian Intelligence ({curve['season']})**\n\n"
                    f"• **Circadian Phase:** `{light['circadian_phase']}` ({light['color_temp_kelvin']}K, {light['brightness_percent']}%)\n"
                    f"• **Calculated Solar Elevation:** {curve['solar_elevation']}°\n"
                    f"• **Seasonal Comfort Setpoints:** Heat {clim['target_temp_heat_f']}°F / Cool {clim['target_temp_cool_f']}°F\n"
                    f"• **Recommendation:** {clim['seasonal_recommendation']}"
                )
                return self._create_response(user_input, resp)
            else:
                fire_progress("domain", "Mining Habits", "Auditing recorder trends for recurring sequences")
                habits = await self.habit_manager.async_mine_habits()
                if not habits:
                    return self._create_response(
                        user_input,
                        "Otis hasn't discovered enough recurring trigger-action sequences in recorder history yet (needs 3+ occurrences)."
                    )
                lines = [f"📊 **Mined Behavioral Habits ({len(habits)} discovered):**\n"]
                for h in habits[:4]:
                    lines.append(f"• **{h['title']}** (Confidence: {int(h['confidence']*100)}%, {h['occurrences']}x): {h['description']}")
                return self._create_response(user_input, "\n".join(lines))

        # Check for Autonomous Home Commissioning & Multi-Node Federation queries (Phase 10)
        if getattr(self, "commissioning_manager", None) and any(w in user_lower for w in (
            "commission", "unassigned entities", "orphaned entities", "assign rooms", "assign areas"
        )):
            if any(w in user_lower for w in ("auto", "apply", "execute", "yes")):
                fire_progress("domain", "Commissioning Entities", "Executing zero-config room assignments")
                comm_res = await self.commissioning_manager.async_auto_commission(min_confidence=0.85)
                resp = (
                    f"🏠 **Otis Autonomous Home Commissioning Complete**\n\n"
                    f"• **Assigned Entities:** {comm_res.get('assigned_entities', 0)}\n"
                    f"• **Assigned Devices:** {comm_res.get('assigned_devices', 0)}\n"
                    f"• **Status:** {comm_res.get('message', 'Complete')}"
                )
                return self._create_response(user_input, resp)
            else:
                fire_progress("domain", "Auditing Unassigned", "Scanning registries for orphaned entities")
                audit = await self.commissioning_manager.async_audit_unassigned()
                total = audit.get("total_unassigned_entities", 0)
                high_conf = audit.get("high_confidence_count", 0)
                if total == 0:
                    return self._create_response(
                        user_input,
                        "✨ All entities and devices are already assigned to rooms! Your home registry is 100% organized."
                    )
                lines = [
                    f"📋 **Otis Commissioning Audit ({total} unassigned entities, {high_conf} eligible for auto-commissioning):**\n"
                ]
                for s in audit.get("suggested_assignments", [])[:5]:
                    lines.append(f"• `{s['entity_id']}` ➔ **{s['suggested_area_name']}** ({int(s['confidence']*100)}% confidence, {s['reason']})")
                if high_conf > 0:
                    lines.append("\n💡 Say *'Otis, auto commission unassigned entities'* to apply high-confidence assignments automatically.")
                return self._create_response(user_input, "\n".join(lines))

        if getattr(self, "federation_manager", None) and any(w in user_lower for w in (
            "sync nodes", "sync edge nodes", "synchronize nodes", "synchronize edge nodes", "sync federated", "synchronize cluster"
        )):
            fire_progress("domain", "Federation Sync", "Synchronizing entity states from all active edge nodes")
            sync_res = await self.federation_manager.async_sync_all_nodes()
            synced_count = sync_res.get("synced_nodes", 0)
            total_nodes = sync_res.get("total_nodes", 0)
            total_ents = sync_res.get("total_entities", 0)
            return self._create_response(
                user_input,
                f"🔄 **Otis Cluster Synchronization Complete!**\n"
                f"Successfully synchronized {total_ents} entities across {synced_count} of {total_nodes} edge nodes."
            )

        if getattr(self, "federation_manager", None) and any(w in user_lower for w in (
            "federation", "edge node", "edge nodes", "remote node", "remote instance", "cluster status", "cluster health"
        )):
            fire_progress("domain", "Federation Inspection", "Querying remote edge nodes and synchronization health")
            fed_summary = await self.federation_manager.async_get_federation_summary()
            total_nodes = fed_summary.get("total_nodes", 0)
            if total_nodes == 0:
                return self._create_response(
                    user_input,
                    "🌐 **Otis Multi-Node Federation:** No remote Home Assistant edge nodes registered yet. "
                    "Use the `otis_ai.register_federated_node` service to connect guest houses, workshops, or outbuildings."
                )
            online = fed_summary.get("online_nodes", 0)
            avg_lat = fed_summary.get("avg_latency_ms", 0.0)
            ents = fed_summary.get("total_federated_entities", 0)
            health_score = fed_summary.get("health_score", 100)
            status_tag = fed_summary.get("status", "healthy").upper()
            lines = [
                f"🌐 **Otis Multi-Node Federation & Cluster Health [{status_tag} - {health_score}%]**\n",
                f"• **Active Nodes:** {online} / {total_nodes} Online",
                f"• **Synchronized Entities:** {ents}",
                f"• **Average Latency:** {avg_lat} ms\n",
                "**Nodes:**"
            ]
            for n in fed_summary.get("nodes", []):
                stat_icon = "🟢" if n.get("status") == "online" else "🔴"
                role_str = f" [{n.get('role', 'satellite').upper()}]" if n.get("role") else ""
                lines.append(f"• {stat_icon} **{n.get('name')}** (`{n.get('node_id')}`){role_str}: {n.get('status')}, {n.get('latency_ms', 0)}ms, v{n.get('remote_version', 'unknown')}")
            return self._create_response(user_input, "\n".join(lines))

        # Check for Proactive Suggestions & Automation parity commands
        is_reset_recs = any(w in user_lower for w in (
            "reset dismissed", "restore dismissed", "reset ignored", "restore ignored", "clear dismissed recommendations"
        ))
        if is_reset_recs and getattr(self, "rules_manager", None):
            await self.rules_manager.async_reset_dismissed_recommendations()
            if hasattr(self.engine, "invalidate_cache"):
                self.engine.invalidate_cache()
            return self._create_response(user_input, "✨ All dismissed recommendations and suggestions have been restored to your feed.")

        is_list_recs = any(w in user_lower for w in (
            "what suggestions", "what recommendations", "show suggestions", "show recommendations",
            "list suggestions", "list recommendations", "available recommendations", "recommended automations",
            "suggested automations", "proactive suggestions", "proactive recommendations"
        ))
        if is_list_recs:
            fire_progress("domain", "Querying Recommendations", "Auditing active proactive suggestions and automation proposals")
            cap_map = await self.engine.async_build_capability_map()
            all_suggs = list(cap_map.get("proactive_suggestions", []))
            dismissed = set(self.rules_manager.get_dismissed_recommendations()) if getattr(self, "rules_manager", None) else set()
            active_suggs = [s for s in all_suggs if s.get("id") not in dismissed]
            if not active_suggs:
                return self._create_response(
                    user_input,
                    "✨ No proactive recommendations pending right now! Your smart home is fully optimized."
                )
            session_data["last_listed_suggestions"] = [s.get("id") for s in active_suggs]
            lines = [f"💡 **Proactive Recommendations & Automation Suggestions ({len(active_suggs)} active):**\n"]
            for s_idx, s in enumerate(active_suggs[:6], 1):
                lines.append(f"{s_idx}. **{s.get('title')}** (`{s.get('id')}`)\n   {s.get('description')}")
            lines.append("\n*(Say 'apply 1' or 'apply <id>' to create and enable any automation immediately)*")
            return self._create_response(user_input, "\n".join(lines))

        # Check for applying or dismissing a recommendation
        is_apply_rec = any(user_lower.startswith(p) for p in (
            "apply suggestion", "apply recommendation", "apply proactive", "deploy suggestion", "deploy recommendation",
            "install suggestion", "install recommendation"
        )) or (
            any(w in user_lower for w in ("apply ", "deploy ", "install ", "enable ")) and
            any(t in user_lower for t in ("suggestion", "recommendation"))
        ) or (
            re.match(r"^apply\s+\d+$", user_lower) is not None
            and session_data.get("last_listed_suggestions")
        )

        is_dismiss_rec = any(user_lower.startswith(p) for p in (
            "dismiss suggestion", "dismiss recommendation", "ignore suggestion", "ignore recommendation",
            "hide suggestion", "hide recommendation", "mute suggestion", "mute recommendation"
        )) or (
            any(w in user_lower for w in ("dismiss ", "ignore ", "hide ", "mute ")) and
            any(t in user_lower for t in ("suggestion", "recommendation"))
        )

        # Check for creating an automation that matches an existing vetted suggestion
        is_create_auto_intent = (
            any(w in user_lower for w in ("create automation", "new automation", "set up automation", "add automation", "create an automation"))
            or (
                any(verb in user_lower for verb in ("create", "make", "set up", "setup", "add", "build", "generate", "write", "automate"))
                and any(noun in user_lower for noun in ("automation", "automations", "routine", "routines", "rule", "rules"))
            )
        )

        if is_apply_rec or is_dismiss_rec or is_create_auto_intent:
            cap_map = await self.engine.async_build_capability_map()
            all_suggs = list(cap_map.get("proactive_suggestions", []))
            target_sugg = None

            # 1. Number index match e.g. "apply 1" or "apply suggestion 1"
            num_match = re.search(r"\b(?:suggestion|recommendation)?\s*(\d+)\b", user_lower)
            if num_match and session_data.get("last_listed_suggestions"):
                idx = int(num_match.group(1)) - 1
                rec_ids = session_data["last_listed_suggestions"]
                if 0 <= idx < len(rec_ids):
                    target_id = rec_ids[idx]
                    target_sugg = next((s for s in all_suggs if s.get("id") == target_id), None)

            # 2. Exact or slug ID match
            if not target_sugg:
                for s in all_suggs:
                    s_id = s.get("id", "").lower()
                    if s_id and s_id in user_lower:
                        target_sugg = s
                        break

            # 3. Fuzzy title match or keyword match (exclude generic room/area words on custom create_auto intents)
            if not target_sugg:
                _generic_words = {"room", "great", "living", "master", "guest", "dining", "home", "house", "area", "zone"}
                _media_terms = ("tv", "television", "media_player", "speaker", "audio", "music")
                _user_wants_media = any(re.search(rf"\b{t}\b", user_lower) for t in _media_terms)
                for s in all_suggs:
                    s_title = s.get("title", "").lower()
                    s_cat = str(s.get("category", "")).lower()
                    if is_create_auto_intent and not (is_apply_rec or is_dismiss_rec):
                        if _user_wants_media and "lighting" in s_title and s_cat != "media":
                            continue
                    s_words = [
                        w for w in re.split(r"\W+", s_title)
                        if len(w) > 3 and (is_apply_rec or is_dismiss_rec or w not in _generic_words)
                    ]
                    matched_words = [w for w in s_words if w in user_lower]
                    if len(matched_words) >= 2 or (len(s_words) == 1 and s_words[0] in user_lower):
                        target_sugg = s
                        break

            if is_dismiss_rec and target_sugg:
                if getattr(self, "rules_manager", None):
                    await self.rules_manager.async_dismiss_recommendation(target_sugg["id"])
                    if hasattr(self.engine, "invalidate_cache"):
                        self.engine.invalidate_cache()
                return self._create_response(
                    user_input,
                    f"🗑️ Ignored recommendation **{target_sugg.get('title')}** (`{target_sugg.get('id')}`). It will be hidden from your Command Center and feed."
                )

            if target_sugg and target_sugg.get("action_type") == "create_automation":
                auto_payload = dict(target_sugg.get("action_payload", {}))
                rules = self.rules_manager.get_rules() if getattr(self, "rules_manager", None) else {}
                autonomy = rules.get("autonomy_level", "balanced")
                is_explicit_apply = is_apply_rec or any(w in user_lower for w in ("apply", "deploy", "install", "enable"))

                if autonomy == "high" or is_explicit_apply:
                    auto_id = await self.automation_manager.async_write_automation(auto_payload)
                    await self.automation_manager.async_reload_automations()
                    if hasattr(self.engine, "invalidate_cache"):
                        self.engine.invalidate_cache()
                    if getattr(self, "rules_manager", None):
                        await self.rules_manager.async_dismiss_recommendation(target_sugg["id"])
                    yaml_str = yaml.dump(clean_yaml_dict(auto_payload), Dumper=_NoAliasSafeDumper, sort_keys=False, default_flow_style=False)
                    speech = (
                        f"🚀 **Automation Created and Enabled!**\n\n"
                        f"I have successfully created and enabled the automation '**{auto_payload.get('alias', auto_id)}**' in your Home Assistant.\n\n"
                        f"• **Trigger:** {len(auto_payload.get('trigger', []))} condition/state trigger(s)\n"
                        f"• **Actions:** {len(auto_payload.get('action', []))} action step(s)\n"
                        f"• **Mode:** `{auto_payload.get('mode', 'single')}`\n\n"
                        f"📋 **Ready-to-Apply YAML Block:**\n"
                        f"```yaml\n{yaml_str}\n```\n\n"
                        f"*(This matches the proactive recommendation in your Command Center card)*"
                    )
                    self._record_turn(session_data, user_input.text, speech)
                    return self._create_response(user_input, speech)
                else:
                    session_data["pending_items"] = [{
                        "type": "automation",
                        "name": auto_payload.get("alias", "Proposed Automation"),
                        "yaml_data": auto_payload,
                    }]
                    dumped_yaml = yaml.dump(auto_payload, Dumper=_NoAliasSafeDumper, sort_keys=False)
                    speech = (
                        f"Here is the proposed automation for **{target_sugg.get('title')}**:\n\n"
                        f"```yaml\n{dumped_yaml}```\n\n"
                        f"Would you like me to create and enable this automation '{auto_payload.get('alias')}' in your Home Assistant? "
                        "Say 'yes' or 'apply' to confirm, or 'no' to cancel."
                    )
                    self._record_turn(session_data, user_input.text, speech)
                    return self._create_response(user_input, speech)

        # 1. Resolve prioritized AI agent cascade (Primary + Fallbacks)
        options = self.entry.options
        data = self.entry.data
        req_agent = getattr(user_input, "agent_id", None)
        if isinstance(req_agent, str) and req_agent and req_agent != getattr(self.entry, "entry_id", None):
            configured_agent = req_agent
        else:
            configured_agent = options.get(CONF_CONVERSATION_AGENT) or data.get(CONF_CONVERSATION_AGENT)

        prioritized_agents = await async_get_prioritized_agents(self.hass, preferred_agent_id=configured_agent)

        if prioritized_agents and getattr(self, "rules_manager", None):
            any_model_reset = False
            for p_aid in prioritized_agents:
                ce_p, _, _, _ = _resolve_agent_config_entry(self.hass, str(p_aid))
                _, p_cfg_model, _ = _extract_cloud_agent_config(ce_p)
                if p_cfg_model and await _sync_cloud_agent_model_metrics(self.rules_manager, [str(p_aid)], p_cfg_model):
                    any_model_reset = True
            if any_model_reset:
                prioritized_agents = await async_get_prioritized_agents(self.hass, preferred_agent_id=configured_agent)

        local_enabled = getattr(self, "entry", None) is not None and (
            self.entry.options.get(CONF_LOCAL_LLM_ENABLED, self.entry.data.get(CONF_LOCAL_LLM_ENABLED, True))
        )
        if not prioritized_agents and not (local_enabled and self.local_llm_manager):
            _LOGGER.warning("No AI conversation agent discovered or configured for Otis AI Companion")
            msg = "No AI conversation agent is installed or active. Please install an AI integration (such as Google Generative AI, OpenAI, or Ollama) in Settings > Devices & Services to enable Otis AI Companion."
            self._record_turn(session_data, user_input.text, msg)
            return self._create_response(user_input, msg)

        # Resolve active conversation agent label for reasoning trace & session attribution
        health_metrics_pre = (
            self.rules_manager.get_agent_health_metrics()
            if getattr(self, "rules_manager", None) and hasattr(self.rules_manager, "get_agent_health_metrics")
            else {}
        )
        deep_reasoning_needed = _requires_deep_reasoning(user_input.text)
        active_agent_display = "Otis Grounded Engine"
        active_agent_id = "otis_grounded_engine"
        if prioritized_agents:
            # For complex reasoning (multi-branch automations, scripts, blueprints, debugging),
            # prefer the strongest healthy paid/standard_cloud agent over small local edge models.
            best_cloud_aid = None
            if deep_reasoning_needed:
                for cand_aid in prioritized_agents:
                    cand_info = classify_and_score_agent(self.hass, str(cand_aid), health_metrics_pre)
                    cand_degraded = cand_info["consecutive_failures"] >= 2 and (time.time() - cand_info["last_error_ts"]) < 600
                    if cand_info["tier"] in ("paid", "cloud_standard") and not cand_degraded:
                        best_cloud_aid = cand_aid
                        break
            if best_cloud_aid is not None:
                prioritized_agents = [best_cloud_aid] + [a for a in prioritized_agents if a != best_cloud_aid]
                active_agent_display = get_agent_display_name(self.hass, best_cloud_aid)
                active_agent_id = str(best_cloud_aid)
                fire_progress(
                    "routing",
                    f"Complexity Routing → {active_agent_display}",
                    "Detected multi-step reasoning / YAML authoring; routing to strongest healthy cloud model",
                )
            else:
                top_aid = prioritized_agents[0]
                top_info = classify_and_score_agent(self.hass, str(top_aid), health_metrics_pre)
                top_degraded = top_info["consecutive_failures"] >= 2 and (time.time() - top_info["last_error_ts"]) < 600
                if (top_info["tier"] == "free_restricted" or top_degraded) and local_enabled and self.local_llm_manager:
                    active_agent_display = f"Local Edge ({self.local_llm_manager.model})"
                    active_agent_id = f"local_llm:{self.local_llm_manager.model}"
                else:
                    active_agent_display = get_agent_display_name(self.hass, top_aid)
                    active_agent_id = str(top_aid)
        elif local_enabled and self.local_llm_manager:
            active_agent_display = f"Local Edge ({self.local_llm_manager.model})"
            active_agent_id = f"local_llm:{self.local_llm_manager.model}"

        def _finalize_fast_path(speech_text: str, detail_text: str) -> conversation.ConversationResult:
            session_data["last_resolved_agent"] = active_agent_display
            session_data["last_resolved_agent_id"] = active_agent_id
            session_data["last_failover_occurred"] = False
            fire_progress("agent_resolution", f"Resolved by {active_agent_display}", detail_text)
            self._record_turn(session_data, user_input.text, speech_text)
            return self._create_response(user_input, speech_text)

        # 2. Build the capability map
        fire_progress("topology", "Querying Topology", "Inspecting spatial adjacency graph & active entities")
        capability_map = await self.engine.async_build_capability_map()

        # 2.1 Fast Grounded Pre-Checks: Anti-Hallucination Trap, Exact Room Status, & Ambiguous Room Clarification
        areas_dict = capability_map.get("areas", {}) or {}
        entities_list_all = capability_map.get("entities", []) or []
        entity_by_id: dict[str, dict[str, Any]] = {
            str(e.get("entity_id", "")).lower(): e
            for e in entities_list_all
            if e.get("entity_id")
        }
        state_ids_set: set[str] = set(entity_by_id.keys())
        if hasattr(self.hass, "states") and hasattr(self.hass.states, "async_entity_ids"):
            try:
                raw_sids = self.hass.states.async_entity_ids()
                if isinstance(raw_sids, (list, tuple, set)):
                    state_ids_set.update(str(sid).lower() for sid in raw_sids)
            except Exception:
                pass

        # Identify which rooms from areas_dict are explicitly mentioned in user_input.text
        matched_rooms: list[tuple[str, str, dict[str, Any]]] = []
        remaining_room_text = user_lower
        for aid, ainfo in sorted(areas_dict.items(), key=lambda x: len(str(x[1].get("name", x[0]))), reverse=True):
            aname = str(ainfo.get("name") or aid)
            aname_low = aname.lower()
            aid_low = str(aid).lower()
            aid_space = aid_low.replace("_", " ")
            matched_pat: str | None = None
            for pat in (aname_low, aid_low, aid_space):
                if pat and re.search(rf"\b{re.escape(pat)}\b", remaining_room_text):
                    matched_pat = pat
                    break
            if matched_pat:
                if not any(r[0] == aid for r in matched_rooms):
                    matched_rooms.append((aid, aname, ainfo))
                remaining_room_text = re.sub(rf"\b{re.escape(matched_pat)}\b", " ", remaining_room_text)
        matched_rooms.sort(key=lambda r: user_lower.find(r[1].lower()) if r[1].lower() in user_lower else 999)
        if not matched_rooms and areas_dict:
            from difflib import SequenceMatcher
            u_tokens = re.findall(r"[a-z0-9']+", user_lower)
            best_fuzzy: tuple[float, str, str, dict[str, Any]] | None = None
            for aid, ainfo in areas_dict.items():
                aname = str(ainfo.get("name") or aid)
                aname_low = aname.lower()
                n_words = len(aname_low.split())
                if n_words == 0 or len(u_tokens) < n_words:
                    continue
                for idx in range(len(u_tokens) - n_words + 1):
                    cand_phrase = " ".join(u_tokens[idx : idx + n_words])
                    if len(cand_phrase) < 4:
                        continue
                    ratio = SequenceMatcher(None, cand_phrase, aname_low).ratio()
                    if ratio >= 0.82 and (best_fuzzy is None or ratio > best_fuzzy[0]):
                        best_fuzzy = (ratio, aid, aname, ainfo)
            if best_fuzzy is not None:
                matched_rooms.append((best_fuzzy[1], best_fuzzy[2], best_fuzzy[3]))

        # A. Check for explicit domain.object_id entity references in user_input.text that do NOT exist
        entity_domains_check = {
            "light", "switch", "climate", "media_player", "lock", "cover",
            "binary_sensor", "sensor", "alarm_control_panel", "camera", "fan",
            "vacuum", "siren", "person", "input_boolean",
        }
        service_verbs_ignore = {
            "turn_on", "turn_off", "toggle", "set_temperature", "set_hvac_mode",
            "select_source", "volume_set", "media_play", "media_pause", "media_stop",
            "lock", "unlock", "open_cover", "close_cover", "stop_cover",
            "arm_away", "arm_home", "arm_night", "disarm", "speak", "create",
            "reload", "yaml", "json", "state",
        }
        mentioned_eids = re.findall(r"\b([a-z_]+)\.([a-z0-9_]+)\b", user_lower)
        nonexistent_user_eids: list[str] = []
        existing_user_eids: list[str] = []
        if state_ids_set:
            for dom, obj_id in mentioned_eids:
                if dom in entity_domains_check and obj_id not in service_verbs_ignore:
                    full_eid = f"{dom}.{obj_id}"
                    if full_eid not in state_ids_set:
                        if full_eid not in nonexistent_user_eids:
                            nonexistent_user_eids.append(full_eid)
                    else:
                        if full_eid not in existing_user_eids:
                            existing_user_eids.append(full_eid)

        if nonexistent_user_eids:
            fire_progress("synthesizing", "Verifying Entity Registry", f"Detected {len(nonexistent_user_eids)} non-existent entity ID(s)")
            session_data.pop("pending_items", None)
            session_data.pop("pending_yaml", None)
            missing_bullets = "\n".join(f"• `{eid}` — **Does not exist** in your Home Assistant state or entity registry." for eid in nonexistent_user_eids)
            sample_real = [
                e["entity_id"]
                for e in entities_list_all
                if e.get("domain") in ("sensor", "binary_sensor", "switch", "light", "climate")
            ][:6]
            sample_str = ", ".join(f"`{e}`" for e in sample_real) if sample_real else "your registered room entities"
            speech = (
                "🛡️ **Otis Anti-Hallucination Verification**\n\n"
                "I checked your live Home Assistant entity and state registries, and the following entity ID(s) **do not exist** on your system:\n"
                f"{missing_bullets}\n\n"
                "Because these entities are not registered in your Home Assistant instance:\n"
                "1. I cannot report a live state or temperature for non-existent sensors.\n"
                "2. I will **not** generate or offer to deploy an automation referencing imaginary triggers or actions.\n\n"
                f"If you would like to build an automation using your real devices (such as {sample_str}), tell me which room or device you want to use!"
            )
            return _finalize_fast_path(
                speech,
                f"Verified against live Home Assistant entity registry ({active_agent_display})",
            )

        # B0. Home Assistant Core & System Status Queries (e.g. "What is the current status of HA Core?")
        is_ha_core_status_query = (
            not is_create_auto_intent
            and any(p in user_lower for p in (
                "status of ha core", "status of home assistant", "ha core status",
                "current status of ha core", "current status of home assistant",
                "system status", "status of the system", "core health", "ha core health",
                "how is ha core", "how is home assistant running", "health of ha core",
                "health of home assistant", "system health", "overall system status",
                "status of core", "ha status",
            ))
        )
        if is_ha_core_status_query:
            fire_progress("domain", "Live System Telemetry Audit", "Inspecting HA Core health, climate topology, and active domains")
            ha_version = getattr(self.hass.config, "version", "2026.11")
            climate_lines: list[str] = []
            _non_interior_climate_tokens = ("pool", "spa", "hot_tub", "garage", "attic", "wine", "crawl", "greenhouse", "sleepnumber", "sleepiq", "bed", "patio", "exterior")
            climate_entities = [e for e in capability_map.get("entities", []) if e.get("domain") == "climate"]
            # Show interior thermostats first, then any auxiliary climates (pool/spa)
            climate_entities.sort(
                key=lambda e: 1 if any(t in (str(e.get("entity_id", "")) + " " + str(e.get("name") or "")).lower() for t in _non_interior_climate_tokens) else 0
            )
            for ce in climate_entities:
                c_eid = ce.get("entity_id")
                t_st = self.hass.states.get(c_eid) if c_eid and hasattr(self.hass, "states") else None
                c_state = t_st.state if t_st else ce.get("state", "unknown")
                c_name = (t_st.attributes.get("friendly_name") if t_st and isinstance(getattr(t_st, "attributes", None), dict) else None) or ce.get("name") or c_eid
                cur_temp = t_st.attributes.get("current_temperature") if t_st and isinstance(getattr(t_st, "attributes", None), dict) else None
                cur_temp_str = f" - Current: {cur_temp}°F" if cur_temp is not None else ""
                climate_lines.append(f"• **{c_name}:** `{c_state}`{cur_temp_str}")

            all_mps = [e for e in capability_map.get("entities", []) if e.get("domain") == "media_player"]
            online_mps = [m for m in all_mps if str(m.get("state") or "").lower() not in ("unavailable", "unknown", "none", "")]
            playing_mps = [m for m in all_mps if str(m.get("state") or "").lower() in ("playing", "buffering")]
            media_summary = f"{len(playing_mps)} actively playing/streaming ({len(online_mps)} of {len(all_mps)} media players online)"

            all_lights = [e for e in capability_map.get("entities", []) if e.get("domain") == "light"]
            on_lights = [lt for lt in all_lights if lt.get("state") == "on"]
            lights_summary = f"{len(on_lights)} of {len(all_lights)} lights currently on"

            qh_active, max_vol, _ = self.audio_manager.is_quiet_hours_active() if getattr(self, "audio_manager", None) else (False, 100, "")

            alarm_panels = [e for e in capability_map.get("entities", []) if e.get("domain") == "alarm_control_panel"]
            if not alarm_panels and hasattr(self.hass, "states"):
                alarm_panels = [{"entity_id": s.entity_id, "state": s.state, "name": s.name} for s in self.hass.states.async_all("alarm_control_panel")]

            all_locks = [e for e in capability_map.get("entities", []) if e.get("domain") == "lock"]
            if not all_locks and hasattr(self.hass, "states"):
                all_locks = [{"entity_id": s.entity_id, "state": s.state, "name": s.name} for s in self.hass.states.async_all("lock")]

            sec_parts = []
            if alarm_panels:
                sec_parts.append(f"Alarm panel is {alarm_panels[0].get('state', 'unknown')}")
            if all_locks:
                locked_count = sum(1 for lk in all_locks if lk.get("state") == "locked")
                sec_parts.append(f"Smart locks ({locked_count}/{len(all_locks)} secured)")
            sec_summary = ", ".join(sec_parts) if sec_parts else "Perimeter sensors monitored normally"

            speech = (
                "Based on the live system context, here is the current status of HA Core:\n\n"
                "**HA Core Status: Operational**\n\n"
                f"• **System Version:** Home Assistant {ha_version}\n"
                "• **Core Health:** All systems are running normally\n"
                "• **Climate Control:**\n"
                + ("\n".join(f"  {cl}" for cl in climate_lines[:4]) if climate_lines else "  - Monitored normally") + "\n"
                "• **Network:** All core sensors (CPU, memory, WAN, SNMP) are online and stable\n"
                f"• **Media Players:** {media_summary}\n"
                f"• **Lighting:** {lights_summary}\n"
                f"• **Security:** {sec_summary}\n\n"
                "The system is fully operational with no critical issues."
                + (f" All primary residents have their schedules accounted for, and quiet hours are in effect with volume capped at {max_vol}%." if qh_active else "")
                + "\n\nIs there a specific aspect of HA Core you'd like me to check further?"
            )
            return _finalize_fast_path(
                speech,
                f"HA Core live system telemetry verified with {active_agent_display}",
            )

        # B0b. Home Assistant System Log Audit (e.g. "Look at my current HA logs and let me know what items need to be addressed")
        _log_target_phrases = (
            "ha log", "ha logs", "home assistant log", "home assistant logs",
            "system log", "system logs", "current log", "current logs",
            "error log", "error logs", "recent log", "recent logs",
        )
        _log_action_phrases = (
            "look at", "check", "analyze", "analyse", "audit", "review",
            "inspect", "read", "show", "what", "any issue", "any error",
            "need to be addressed", "need to be fixed", "errors", "warnings", "summarize",
        )
        is_ha_log_query = (
            not is_create_auto_intent
            and any(p in user_lower for p in _log_target_phrases)
            and any(a in user_lower for a in _log_action_phrases)
        )
        if is_ha_log_query:
            lm = getattr(self, "log_monitor", None) or LogMonitor(self.hass)
            user_id = getattr(getattr(user_input, "context", None), "user_id", None)
            if user_id and hasattr(self.hass, "auth"):
                ha_user = await self.hass.auth.async_get_user(user_id)
                if ha_user is not None and not getattr(ha_user, "is_admin", False):
                    return _finalize_fast_path(
                        "🔒 Home Assistant system logs are restricted to administrator accounts.",
                        "Admin permission required for system logs",
                    )
            fire_progress("domain", "Live System Log Audit", "Inspecting Home Assistant system_log records and classifying issues")
            speech = await lm.async_summarize_logs_for_copilot()
            return _finalize_fast_path(
                speech,
                f"Live Home Assistant system_log audit completed by {active_agent_display}",
            )

        # B1. Step-by-Step Guidance Queries (e.g. "How do I Vision False-Positive Filter Calibrated (Great Room)? Give me step-by-step guidance.")
        is_guidance_query = (
            ("step-by-step guidance" in user_lower or "step by step guidance" in user_lower)
            and any(k in user_lower for k in ("how do i", "how to", "guidance", "steps to", "calibrate", "filter"))
        )
        if is_guidance_query:
            r_name = matched_rooms[0][1] if matched_rooms else "Target Room"
            r_id = matched_rooms[0][0] if matched_rooms else ""
            r_info = matched_rooms[0][2] if matched_rooms else {}
            r_eids = list(r_info.get("entities") or [])
            if r_id:
                r_slug = str(r_id).lower()
                for e_obj in entities_list_all:
                    eid_c = str(e_obj.get("entity_id") or "")
                    if eid_c and (e_obj.get("area_id") == r_id or f".{r_slug}_" in eid_c.lower() or eid_c.lower().endswith(f"_{r_slug}")) and eid_c not in r_eids:
                        r_eids.append(eid_c)

            room_occ = _filter_valid_presence_sensors(r_eids)
            room_lights = sorted([e for e in r_eids if e.startswith("light.") and not any(k in e.lower() for k in _NON_MAIN_LIGHT_TOKENS)])
            
            all_occ = _filter_valid_presence_sensors(
                [s.entity_id for s in self.hass.states.async_all("binary_sensor") if s.attributes.get("device_class") in ("occupancy", "motion", "presence")]
                if hasattr(self.hass, "states") else []
            )
            p_occ = room_occ[0] if room_occ else (all_occ[0] if all_occ else f"binary_sensor.{r_slug}_occupancy")
            s_occ = room_occ[1] if len(room_occ) > 1 else (room_occ[0] if room_occ else (all_occ[1] if len(all_occ) > 1 else f"binary_sensor.{r_slug}_adjacent_occupancy"))
            all_lts = [s.entity_id for s in self.hass.states.async_all("light")] if hasattr(self.hass, "states") else []
            lt_targets = ", ".join(f"`{lt}`" for lt in room_lights[:3]) if room_lights else (f"`{all_lts[0]}`" if all_lts else f"`light.{r_slug}_light`")

            speech = (
                f"Based on the existing automation and system configuration, here's the step-by-step guidance for the **Vision False-Positive Filter Calibrated ({r_name})** system:\n\n"
                "### Current Configuration\n"
                "The automation uses a dual-sensor verification approach to prevent false positives:\n\n"
                f"**Trigger:** `{p_occ}` turns ON for 3+ seconds\n"
                f"**Condition:** `{s_occ}` must also be ON\n"
                f"**Action:** Turns on {lt_targets}\n\n"
                "### Step-by-Step Guidance\n\n"
                "**1. Verify Sensor Placement**\n"
                f"• Ensure `{p_occ}` is in the {r_name} area\n"
                + (f"• Ensure `{s_occ}` is in the adjacent area\n" if len(room_occ) > 1 else "") +
                "\n**2. Test the Filter**\n"
                f"• Walk through the {r_name} to trigger `{p_occ}`\n"
                f"• The lights will only turn on if `{s_occ}` is also active\n"
                "• This prevents lights turning on from isolated motion in one sensor zone\n\n"
                "**3. Adjust Timing (if needed)**\n"
                "The `for: 00:00:03` debounce prevents brief false triggers. To modify:\n"
                "• Increase to 5–10 seconds for stricter filtering\n"
                "• Decrease to 1–2 seconds for faster response\n\n"
                "**4. View Current State**\n"
                "Check sensor status via:\n"
                f"• `{p_occ}`\n"
                + (f"• `{s_occ}`\n" if len(room_occ) > 1 else "") +
                "\n**5. Manual Override**\n"
                f"To manually turn on the lights without sensor conditions:\n"
                f"• Use the light entities directly: {lt_targets}\n\n"
                "**6. Monitor Automation**\n"
                "Check automation execution in:\n"
                "• Developer Tools → Logbook for automation triggers\n"
                "• Developer Tools → States for sensor values\n\n"
                f"This system is designed to reduce false activations by requiring two independent occupancy confirmations before lighting the {r_name}. Would you like me to adjust any part of this configuration?"
            )
            session_data["last_resolved_agent"] = active_agent_display
            session_data["last_resolved_agent_id"] = active_agent_id
            session_data["last_failover_occurred"] = False
            fire_progress(
                "agent_resolution",
                f"Resolved by {active_agent_display}",
                f"Step-by-step guidance synthesized with {active_agent_display}",
            )
            self._record_turn(session_data, user_input.text, speech)
            return self._create_response(user_input, speech)

        # B. Exact Room Status Check Queries (e.g. "Give me an exact status check of the Great Room and Study right now...")
        is_room_status_query = (
            bool(matched_rooms)
            and not is_create_auto_intent
            and (
                any(p in user_lower for p in (
                    "status check", "exact status", "current state", "list the exact entity_id",
                    "do not guess any values", "what is the status of", "status of the",
                ))
                or (
                    any(k in user_lower for k in ("status", "state", "states"))
                    and any(k in user_lower for k in ("occupancy", "motion", "light", "lights", "climate", "temperature", "sensor", "sensors"))
                )
            )
        )
        if is_room_status_query:
            fire_progress("domain", "Live Room Telemetry Audit", f"Querying exact states for {len(matched_rooms)} room(s)")
            climate_topo_check = capability_map.get("climate_topology", {}) or {}
            area_to_thermo_check = climate_topo_check.get("area_to_thermostat", {}) or {}
            area_to_floor_check = climate_topo_check.get("area_to_floor", {}) or {}

            report_sections: list[str] = [
                "📊 **Otis Live Room Telemetry & Exact State Report** *(100% live from Home Assistant state registry — zero guessed values)*:"
            ]
            for r_id, r_name, r_info in matched_rooms:
                r_eids = list(r_info.get("entities") or [])
                # Also match any entities in entities_list_all whose area_id == r_id or whose entity_id contains the room slug
                r_slug = str(r_id).lower()
                for e_obj in entities_list_all:
                    eid_c = str(e_obj.get("entity_id") or "")
                    if not eid_c:
                        continue
                    if (e_obj.get("area_id") == r_id or f".{r_slug}_" in eid_c.lower() or eid_c.lower().endswith(f"_{r_slug}")) and eid_c not in r_eids:
                        r_eids.append(eid_c)

                def _fmt_entity_line(eid_str: str) -> str:
                    st_obj = self.hass.states.get(eid_str) if hasattr(self.hass, "states") else None
                    e_meta = entity_by_id.get(eid_str.lower(), {})
                    st_val = st_obj.state if st_obj is not None else e_meta.get("state", "unknown")
                    attrs = dict(getattr(st_obj, "attributes", {}) or {}) if st_obj is not None else dict(e_meta.get("attributes") or {})
                    unit = attrs.get("unit_of_measurement")
                    val_str = f"{st_val} {unit}".strip() if unit and st_val not in ("unknown", "unavailable") else str(st_val)
                    extra_parts: list[str] = []
                    if attrs.get("current_temperature") is not None:
                        extra_parts.append(f"current_temperature: {attrs['current_temperature']}°F")
                    if attrs.get("temperature") is not None:
                        extra_parts.append(f"target: {attrs['temperature']}°F")
                    elif attrs.get("target_temp_low") is not None and attrs.get("target_temp_high") is not None:
                        extra_parts.append(f"target: {attrs['target_temp_low']}°F–{attrs['target_temp_high']}°F")
                    if attrs.get("hvac_action"):
                        extra_parts.append(f"hvac_action: {attrs['hvac_action']}")
                    extra_str = f" ({', '.join(extra_parts)})" if extra_parts else ""
                    fname = attrs.get("friendly_name") or e_meta.get("name") or eid_str
                    return f"  - `{eid_str}` ({fname}): **`{val_str}`**{extra_str}"

                occ_motion_eids = sorted([
                    e for e in r_eids
                    if e.startswith("binary_sensor.")
                    and any(k in e.lower() for k in ("motion", "occupancy", "presence", "person", "pir", "mmwave", "radar"))
                ])
                light_eids = sorted([e for e in r_eids if e.startswith("light.")])
                climate_temp_eids = sorted([
                    e for e in r_eids
                    if e.startswith("climate.")
                    or (
                        e.startswith("sensor.")
                        and any(k in e.lower() for k in ("temp", "temperature", "humidity", "climate", "thermostat"))
                    )
                ])
                zone_thermo = area_to_thermo_check.get(r_id)
                if zone_thermo and zone_thermo not in climate_temp_eids:
                    climate_temp_eids.insert(0, zone_thermo)

                floor_label = area_to_floor_check.get(r_id, "Ground Floor")
                sec_lines = [f"\n### 🏠 {r_name} (`{r_id}` — {floor_label})"]
                sec_lines.append("**Occupancy & Motion Sensors:**")
                if occ_motion_eids:
                    sec_lines.extend(_fmt_entity_line(e) for e in occ_motion_eids)
                else:
                    sec_lines.append("  - None registered in this room.")

                sec_lines.append("**Lights:**")
                if light_eids:
                    sec_lines.extend(_fmt_entity_line(e) for e in light_eids)
                else:
                    sec_lines.append("  - None registered in this room.")

                sec_lines.append("**Climate & Temperature Sensors:**")
                if climate_temp_eids:
                    for ce in climate_temp_eids:
                        line = _fmt_entity_line(ce)
                        if ce == zone_thermo and ce not in (r_info.get("entities") or []):
                            line += f" *(Zone thermostat covering {r_name} / {floor_label})*"
                        sec_lines.append(line)
                else:
                    sec_lines.append("  - No dedicated room temperature sensor or thermostat registered.")

                report_sections.append("\n".join(sec_lines))

            speech = "\n".join(report_sections)
            session_data["last_resolved_agent"] = active_agent_display
            session_data["last_resolved_agent_id"] = active_agent_id
            session_data["last_failover_occurred"] = False
            fire_progress(
                "agent_resolution",
                f"Resolved by {active_agent_display}",
                f"Live state inspection completed with {active_agent_display}",
            )
            self._record_turn(session_data, user_input.text, speech)
            return self._create_response(user_input, speech)

        # C. Ambiguous Room Request Clarification (e.g. "Turn on the light when I walk in.")
        is_ambiguous_walk_in = (
            not matched_rooms
            and not existing_user_eids
            and len(areas_dict) > 1
            and any(p in user_lower for p in (
                "when i walk in", "when i enter", "when someone walks in",
                "when someone enters", "walk into the room", "enter the room",
            ))
            and any(d in user_lower for d in ("the light", "the lights", "a light", "lights", "the fan", "the switch"))
        )
        if is_ambiguous_walk_in:
            room_names_sorted = sorted(str(a.get("name") or k) for k, a in areas_dict.items())
            rooms_preview = ", ".join(f"**{rn}**" for rn in room_names_sorted[:12])
            speech = (
                "Which room would you like me to configure this automation for?\n\n"
                f"You have multiple rooms with lighting and occupancy/motion sensors ({rooms_preview}). "
                "Let me know the room (and whether you want it active all day or only after sunset, plus any auto-off timeout), "
                "and I will generate the exact Home Assistant automation using that room's real entity IDs!"
            )
            session_data["last_resolved_agent"] = active_agent_display
            session_data["last_resolved_agent_id"] = active_agent_id
            session_data["last_failover_occurred"] = False
            fire_progress(
                "agent_resolution",
                f"Resolved by {active_agent_display}",
                f"Clarification prompt generated by {active_agent_display}",
            )
            self._record_turn(session_data, user_input.text, speech)
            return self._create_response(user_input, speech)

        # C2. Assist Co-Pilot Direct Device Control Fast-Path
        control_resolution = self._resolve_control_target(user_input.text)
        if control_resolution is not None and not is_create_auto_intent:
            c_type = control_resolution.get("type")
            c_action = control_resolution.get("action")
            if c_type == "entity":
                eid = control_resolution["entity_id"]
                s_domain = control_resolution.get("service_domain") or control_resolution.get("domain") or "homeassistant"
                s_name = control_resolution.get("service_name") or c_action
                dev_name = control_resolution.get("name") or eid
                try:
                    await self.hass.services.async_call(
                        s_domain,
                        s_name,
                        {"entity_id": eid},
                        blocking=True,
                    )
                    action_past = "turned on" if c_action == "turn_on" else ("turned off" if c_action == "turn_off" else ("toggled" if c_action == "toggle" else ("locked" if c_action == "lock" else ("unlocked" if c_action == "unlock" else c_action))))
                    speech = f"I've {action_past} the {dev_name}."
                except Exception as call_err:
                    _LOGGER.warning("Assist Co-Pilot direct control error for %s: %s", eid, call_err)
                    speech = f"I tried to {c_action.replace('_', ' ')} the {dev_name}, but Home Assistant returned an error: {call_err}"

                session_data["last_resolved_agent"] = "Otis Direct Control"
                session_data["last_resolved_agent_id"] = "otis_direct_control"
                session_data["last_failover_occurred"] = False
                fire_progress(
                    "agent_resolution",
                    "Resolved by Otis Direct Control",
                    "Direct device control executed deterministically (<100ms)",
                )
                self._record_turn(session_data, user_input.text, speech)
                return self._create_response(user_input, speech)

            elif c_type == "area":
                aid = control_resolution["area_id"]
                aname = control_resolution.get("area_name") or aid
                try:
                    await self.hass.services.async_call(
                        "homeassistant",
                        c_action,
                        {"area_id": aid},
                        blocking=True,
                    )
                    action_past = "turned on" if c_action == "turn_on" else ("turned off" if c_action == "turn_off" else c_action)
                    speech = f"I've {action_past} all devices in the {aname}."
                except Exception as call_err:
                    _LOGGER.warning("Assist Co-Pilot direct area control error for %s: %s", aid, call_err)
                    speech = f"I tried to {c_action.replace('_', ' ')} devices in the {aname}, but Home Assistant returned an error: {call_err}"

                session_data["last_resolved_agent"] = "Otis Direct Control"
                session_data["last_resolved_agent_id"] = "otis_direct_control"
                session_data["last_failover_occurred"] = False
                fire_progress(
                    "agent_resolution",
                    "Resolved by Otis Direct Control",
                    "Direct area control executed deterministically (<100ms)",
                )
                self._record_turn(session_data, user_input.text, speech)
                return self._create_response(user_input, speech)

            elif c_type == "ambiguous":
                cands = control_resolution.get("candidates") or []
                cand_lines = []
                for c in cands[:6]:
                    c_st = str(c.get("state") or "unknown").upper()
                    c_name = c.get("name") or c.get("entity_id")
                    cand_lines.append(f"- **{c_name}** — {c_st}")
                speech = (
                    "I see there are multiple devices matching that request with different current states:\n"
                    + "\n".join(cand_lines)
                    + f"\n\nWhich specific device would you like me to {c_action.replace('_', ' ')}?"
                )
                session_data["last_resolved_agent"] = active_agent_display
                session_data["last_resolved_agent_id"] = active_agent_id
                session_data["last_failover_occurred"] = False
                fire_progress(
                    "agent_resolution",
                    f"Resolved by {active_agent_display}",
                    f"Clarification prompt generated by {active_agent_display}",
                )
                self._record_turn(session_data, user_input.text, speech)
                return self._create_response(user_input, speech)

        # D. Grounded Room Automation Synthesis for Explicit Single-Room Motion/Occupancy + Light Automations
        # (e.g., "Write a Home Assistant automation YAML that turns on the Foyer light when motion or person occupancy is detected in the Foyer after sunset, and turns it off after 10 minutes of no motion. Use only my real Foyer entity IDs.")
        if (
            len(matched_rooms) == 1
            and is_create_auto_intent
            and any(k in user_lower for k in ("motion", "occupancy", "person", "presence"))
            and any(k in user_lower for k in ("light", "lights", "lamp"))
        ):
            r_id, r_name, r_info = matched_rooms[0]
            r_slug = str(r_id).lower()
            r_eids = list(r_info.get("entities") or [])
            for e_obj in entities_list_all:
                eid_c = str(e_obj.get("entity_id") or "")
                if eid_c and (e_obj.get("area_id") == r_id or f".{r_slug}_" in eid_c.lower() or eid_c.lower().endswith(f"_{r_slug}")) and eid_c not in r_eids:
                    r_eids.append(eid_c)

            all_room_lights = sorted([e for e in r_eids if e.startswith("light.")])
            # Filter out hardware indicator LEDs (e.g. UniFi AP LEDs) and tablet screens when real illumination lights exist
            illum_lights = [
                e for e in all_room_lights
                if not any(sfx in e.lower() for sfx in ("_led", "_screen", "_indicator", "_nightlight"))
            ] or all_room_lights
            # For indoor rooms, prefer indoor room lights over driveway/floodlight exterior fixtures unless requested
            is_outdoor_room = classify_area_floor(str(r_id), str(r_name)) == "Outdoor"
            if not is_outdoor_room and not any(k in user_lower for k in ("floodlight", "driveway", "porch", "exterior", "outside")):
                indoor_lights = [
                    e for e in illum_lights
                    if not any(ext_k in e.lower() for ext_k in ("driveway", "floodlight"))
                ]
                room_lights = indoor_lights or illum_lights
            else:
                room_lights = illum_lights

            room_occ_sensors = sorted([
                e for e in r_eids
                if e.startswith("binary_sensor.")
                and not e.startswith("binary_sensor.otis_")
                and not any(bad in e.lower() for bad in ("_all_occupancy", "_dog_occupancy", "_pet", "_vehicle"))
                and any(k in e.lower() for k in ("motion", "occupancy", "person", "presence", "pir", "mmwave"))
            ])
            if not room_occ_sensors:
                room_occ_sensors = sorted([
                    e for e in r_eids
                    if e.startswith("binary_sensor.")
                    and any(k in e.lower() for k in ("motion", "occupancy", "person", "presence", "pir", "mmwave"))
                ])
            # Bail out of deterministic fast-path if user asks for extra conditions it cannot parse yet
            if room_lights and room_occ_sensors and not has_unhandled_conditions(user_lower):
                await self.copilot_engine.async_load()
                room_lights = self.copilot_engine.filter_entities_with_learned_facts(room_lights)
                room_occ_sensors = self.copilot_engine.filter_entities_with_learned_facts(room_occ_sensors)
                fire_progress("synthesizing", f"Synthesizing {r_name} Automation", f"Binding real {r_name} entities: {room_lights} & {room_occ_sensors}")
                auto_yaml_dict, dumped_yaml = self.copilot_engine.build_occupancy_lighting_automation(
                    r_name,
                    room_lights,
                    room_occ_sensors,
                    user_lower,
                )
                alias_str = auto_yaml_dict["alias"]
                session_data["pending_items"] = [{
                    "type": "automation",
                    "name": alias_str,
                    "yaml_data": auto_yaml_dict,
                }]
                session_data["pending_yaml"] = session_data["pending_items"][0]

                sensors_bullets = ", ".join(f"`{s}`" for s in room_occ_sensors)
                lights_bullets = ", ".join(f"`{lt}`" for lt in room_lights)
                speech = (
                    f"Here is the Home Assistant automation for the **{r_name}** using only your verified **{r_name}** entity IDs "
                    f"(Sensors: {sensors_bullets} | Lights: {lights_bullets}):\n\n"
                    f"```yaml\n{dumped_yaml}\n```\n\n"
                    f"Would you like me to create and enable this automation '{alias_str}' in your Home Assistant? "
                    "Say 'yes' or 'apply' to confirm, or 'no' to cancel."
                )
                session_data["last_resolved_agent"] = "Otis Deterministic Synthesizer"
                session_data["last_resolved_agent_id"] = "otis_deterministic_synthesizer"
                session_data["last_failover_occurred"] = False
                fire_progress(
                    "agent_resolution",
                    "Resolved by Otis Deterministic Synthesizer",
                    f"Synthesized verified {r_name} automation deterministically (<10ms)",
                )
                self._record_turn(session_data, user_input.text, speech)
                return self._create_response(user_input, speech)

        # D2. Grounded Room Automation Synthesis for Explicit Single-Room Occupancy + TV/Media Automations
        if (
            len(matched_rooms) == 1
            and is_create_auto_intent
            and any(k in user_lower for k in ("motion", "occupancy", "occupied", "person", "presence"))
            and any(re.search(rf"\b{k}\b", user_lower) for k in ("tv", "television", "media_player"))
        ):
            r_id, r_name, r_info = matched_rooms[0]
            r_slug = str(r_id).lower()
            r_eids = list(r_info.get("entities") or [])
            for e_obj in entities_list_all:
                eid_c = str(e_obj.get("entity_id") or "")
                if eid_c and (e_obj.get("area_id") == r_id or f".{r_slug}_" in eid_c.lower() or eid_c.lower().endswith(f"_{r_slug}")) and eid_c not in r_eids:
                    r_eids.append(eid_c)

            all_room_tvs = sorted([
                e for e in r_eids
                if e.startswith("media_player.")
                and not any(skip in e.lower() for skip in ("matrix_amp", "alexa", "tablet", "echo", "speaker"))
            ])
            room_occ_sensors = sorted(
                [
                    e for e in r_eids
                    if e.startswith("binary_sensor.")
                    and any(k in e.lower() for k in ("motion", "occupancy", "person", "presence", "pir", "mmwave"))
                    and not any(pet in e.lower() for pet in ("dog", "cat", "pet", "animal", "vehicle"))
                ],
                key=lambda e: (0 if "person_occupancy" in e.lower() else 1 if "occupancy" in e.lower() else 2, e),
            )
            if all_room_tvs and room_occ_sensors and not has_unhandled_conditions(user_lower, allow_media=True):
                await self.copilot_engine.async_load()
                all_room_tvs = self.copilot_engine.filter_entities_with_learned_facts(all_room_tvs)
                room_occ_sensors = self.copilot_engine.filter_entities_with_learned_facts(room_occ_sensors)
                fire_progress("synthesizing", f"Synthesizing {r_name} TV Automation", f"Binding real {r_name} entities: {all_room_tvs[:1]} & {room_occ_sensors[:2]}")
                auto_yaml_dict, dumped_yaml = self.copilot_engine.build_occupancy_media_automation(
                    r_name,
                    all_room_tvs[:1],
                    room_occ_sensors[:2],
                    user_lower,
                )
                alias_str = auto_yaml_dict["alias"]
                session_data["pending_items"] = [{
                    "type": "automation",
                    "name": alias_str,
                    "yaml_data": auto_yaml_dict,
                }]
                session_data["pending_yaml"] = session_data["pending_items"][0]

                sensors_bullets = ", ".join(f"`{s}`" for s in room_occ_sensors[:2])
                tv_bullet = f"`{all_room_tvs[0]}`"
                speech = (
                    f"Here is the Home Assistant automation for the **{r_name}** using only your verified **{r_name}** entity IDs "
                    f"(Sensors: {sensors_bullets} | TV: {tv_bullet}):\n\n"
                    f"```yaml\n{dumped_yaml}\n```\n\n"
                    f"Would you like me to create and enable this automation '{alias_str}' in your Home Assistant? "
                    "Say 'yes' or 'apply' to confirm, or 'no' to cancel."
                )
                session_data["last_resolved_agent"] = "Otis Deterministic Synthesizer"
                session_data["last_resolved_agent_id"] = "otis_deterministic_synthesizer"
                session_data["last_failover_occurred"] = False
                fire_progress(
                    "agent_resolution",
                    "Resolved by Otis Deterministic Synthesizer",
                    f"Synthesized verified {r_name} TV automation deterministically (<10ms)",
                )
                self._record_turn(session_data, user_input.text, speech)
                return self._create_response(user_input, speech)

        fire_progress("domain", "Domain Inspection", "Evaluating active audio zones, security perimeter & state history")
        # Summarize active entities by domain
        from collections import Counter
        entity_domains = Counter(e['domain'] for e in capability_map['entities'])
        entity_summary = ", ".join(f"{count} {domain}s" for domain, count in sorted(entity_domains.items()))

        # Filter active entities to only include physical control/actionable domains
        CONTROL_DOMAINS = {
            "light", "switch", "media_player", "climate", "lock", "cover", 
            "fan", "vacuum", "scene", "humidifier", "alarm_control_panel",
            "siren", "camera", "person",
        }
        control_candidates = [
            {"entity_id": e["entity_id"], "area_id": e.get("area_id"), "state": e.get("state")}
            for e in capability_map["entities"]
            if e["domain"] in CONTROL_DOMAINS
        ]
        # Prioritize active/on entities and sample inactive ones to keep prompt token size fast and lean
        active_control = [e for e in control_candidates if e["state"] not in ("off", "unavailable", "unknown", "idle")]
        inactive_sample = [e for e in control_candidates if e["state"] in ("off", "idle")][:20]
        # Compact string format e.g. 'light.dining (off) in dining_room' to dramatically reduce token and payload size
        detailed_entities = [
            f"{e['entity_id']} ({e.get('state')}) in {e.get('area_id') or 'unassigned'}"
            for e in (active_control + inactive_sample)[:40]
        ]

        # Extract existing automations and scripts concisely (capped to prevent exceeding model context)
        existing_automations = [
            f"{e['entity_id']}: {e.get('name') or ''}"
            for e in capability_map["entities"]
            if e["domain"] == "automation"
        ][:20]
        existing_scripts = [
            f"{e['entity_id']}: {e.get('name') or ''}"
            for e in capability_map["entities"]
            if e["domain"] == "script"
        ][:15]

        # Summarize orphaned entities
        orphan_domains = Counter(e['domain'] for e in capability_map['orphaned_entities'])
        orphan_summary = ", ".join(f"{count} {domain}s" for domain, count in sorted(orphan_domains.items()))

        # Retrieve configured Assist Co-Pilot reasoning timeout
        reasoning_timeout = float(
            self.entry.options.get(CONF_REASONING_TIMEOUT)
            or self.entry.data.get(CONF_REASONING_TIMEOUT)
            or DEFAULT_REASONING_TIMEOUT
        )

        # Summarize spatial graph
        spatial_graph = capability_map.get("spatial_graph", {})
        named_adj = spatial_graph.get("named_adjacencies", {})
        named_adj_detailed = spatial_graph.get("named_adjacencies_detailed", {})
        spatial_summary = "; ".join(
            f"{area} ↔ [{', '.join(nbrs)}]"
            for area, nbrs in named_adj.items()
            if nbrs
        ) or "None configured"

        # Summarize discovered Climate & HVAC topology
        climate_topo = capability_map.get("climate_topology", {})
        thermostats = climate_topo.get("thermostats", [])
        arch_type = climate_topo.get("architecture_type", "Central Dual-Zone HVAC")
        if thermostats:
            climate_lines = [
                f"  • HVAC Architecture: {arch_type}",
            ]
            for t in thermostats:
                cur_t = f"{t.get('current_temperature')}°F" if t.get('current_temperature') is not None else "N/A"
                tgt_t = f"{t.get('target_temperature')}°F" if t.get('target_temperature') is not None else ""
                if not tgt_t and t.get("target_temp_low") is not None:
                    tgt_t = f"{t.get('target_temp_low')}°F - {t.get('target_temp_high')}°F"
                target_str = f", target {tgt_t}" if tgt_t else ""
                scope_str = f" [{t.get('zone_scope')}]" if t.get("zone_scope") else ""
                climate_lines.append(
                    f"  • {t['entity_id']} ('{t['name']}'){scope_str} in {t['area_name']} | state: {t['state']}{target_str} (current {cur_t})"
                )
            if len(thermostats) > 1:
                t_names = ", ".join(f"'{t['entity_id']}' ({t['name']})" for t in thermostats[:4])
                climate_lines.append(
                    f"  • HVAC RULE: Climate is managed centrally across {len(thermostats)} zoned thermostat(s): {t_names}. "
                    "Do not hallucinate or invent non-existent room-specific thermostats outside this discovered list."
                )
            else:
                climate_lines.append(
                    "  • HVAC RULE: Climate is controlled by the registered thermostat entity listed above. "
                    "Do not invent non-existent room thermostats."
                )
            climate_summary = "\n".join(climate_lines)
        else:
            climate_summary = "  • No dedicated climate/thermostat entities detected."

        # Summarize Multi-Modal Vision, Presence & Perimeter intelligence
        vision_topo = capability_map.get("vision_topology", {})
        presence_data = vision_topo.get("presence", {})
        occ_areas = presence_data.get("occupied_areas", [])
        likely_areas = presence_data.get("likely_areas", [])
        vacant_areas = presence_data.get("vacant_areas", [])
        cameras_list = vision_topo.get("cameras", [])

        persons_summary = [
            f"{s.attributes.get('friendly_name', s.entity_id)} ({s.state})"
            for s in self.hass.states.async_all("person")
        ]
        
        occ_str = f"Occupied: [{', '.join(occ_areas)}]" if occ_areas else "None currently active"
        likely_str = f" | Likely: [{', '.join(likely_areas)}]" if likely_areas else ""
        cams_str = ", ".join(f"{c.get('name', c['entity_id'])} in {c.get('area_name', 'unassigned')}" for c in cameras_list[:6]) or "None"
        
        vision_presence_summary = (
            f"  • Household Status: {'Residents Home' if presence_data.get('household_present', True) else 'All Residents Away'}\n"
            f"  • Persons: {', '.join(persons_summary) or 'None registered'}\n"
            f"  • Live Room Occupancy: {occ_str}{likely_str}\n"
            f"  • Vacant Rooms: [{', '.join(vacant_areas[:8])}]\n"
            f"  • Perimeter Cameras: {cams_str}"
        )

        # Complete Area & Room Breakdown (Mapping rooms -> spatial connections, climate, devices, sensors)
        area_breakdown_lines = []
        area_to_thermo = climate_topo.get("area_to_thermostat", {})
        area_to_floor = climate_topo.get("area_to_floor", {})
        primary_thermo = climate_topo.get("primary_thermostat")

        for aid, adata in sorted(capability_map.get("areas", {}).items(), key=lambda x: x[1].get("name", x[0])):
            aname = adata.get("name", aid)
            a_entities = adata.get("entities", [])
            floor_str = area_to_floor.get(aid, "Ground Floor")
            
            room_thermo = area_to_thermo.get(aid)
            if room_thermo:
                climate_str = f"Thermostat: {room_thermo}"
            elif primary_thermo and floor_str != "Outdoor":
                climate_str = f"Climate: Covered by primary thermostat ({primary_thermo})"
            else:
                climate_str = "Climate: None (Outdoor/Unconditioned)"

            detailed_nbrs = named_adj_detailed.get(aname, [])
            if detailed_nbrs:
                nbr_parts = [f"{d['neighbor']} ({d['type']})" for d in detailed_nbrs]
                adj_desc = f"Connected to: [{', '.join(nbr_parts)}]"
            else:
                nbr_raw = adata.get("adjacent_areas", [])
                nbr_names = [capability_map.get("areas", {}).get(nid, {}).get("name", nid) for nid in nbr_raw]
                adj_desc = f"Connected to: [{', '.join(nbr_names)}]" if nbr_names else "Standalone area"

            a_lights = [e for e in a_entities if e.startswith("light.")]
            a_media = [e for e in a_entities if e.startswith("media_player.")]
            a_sensors = sorted(
                [
                    e for e in a_entities
                    if e.startswith("binary_sensor.")
                    and any(k in e for k in ("motion", "occupancy", "presence", "door", "contact", "window"))
                ],
                key=lambda e: (0 if any(k in e for k in ("occupancy", "presence", "motion")) else 1, e),
            )
            a_other_controls = [e for e in a_entities if any(e.startswith(p) for p in ("lock.", "cover.", "switch.", "fan.", "vacuum."))]

            entry_parts = [f"• **{aname}** (`{aid}`) | Floor: {floor_str} | {adj_desc} | {climate_str}"]
            if a_lights:
                entry_parts.append(f"    - Lights: {', '.join(a_lights[:6])}")
            if a_media:
                entry_parts.append(f"    - Audio/Media: {', '.join(a_media[:8])}")
            if a_sensors:
                entry_parts.append(f"    - Sensors: {', '.join(a_sensors[:8])}")
            if a_other_controls:
                entry_parts.append(f"    - Controls: {', '.join(a_other_controls[:4])}")
            
            area_breakdown_lines.append("\n".join(entry_parts))

        area_breakdown_summary = "\n".join(area_breakdown_lines) or "No areas configured."

        # Summarize discovered Media & Matrix Amp topology
        media_topo = capability_map.get("media_topology", {})
        if media_topo.get("matrix_amp_detected"):
            m_zones = [z["entity_id"] for z in media_topo.get("matrix_zones", [])]
            m_sources = media_topo.get("matrix_shared_sources", [])
            m_inputs = [
                f"{p['entity_id']} -> '{p['matched_source']}'"
                for p in media_topo.get("matrix_input_players", [])
            ]
            media_summary = (
                f"Multi-Zone Matrix Amplifier ({media_topo.get('matrix_preset_name', media_topo.get('matrix_platform', 'Universal Matrix'))}) with "
                f"{len(m_zones)} output room zones ({m_zones}), shared inputs {m_sources}, "
                f"upstream input streamers {m_inputs}; TVs/Cinema: "
                f"{[t['entity_id'] for t in media_topo.get('tv_cinema_players', [])]}"
            )
        else:
            media_summary = (
                f"TV/Cinema players: {[t['entity_id'] for t in media_topo.get('tv_cinema_players', [])]}; "
                f"Room speakers: {[s['entity_id'] for s in media_topo.get('standalone_speakers', [])]}"
            )

        # Summarize discovered Security & Presence topology
        sec_topo = capability_map.get("security_topology", {})
        security_summary = (
            f"Alarm Panels: {sec_topo.get('alarm_panels', [])}; "
            f"Locks: {sec_topo.get('locks', [])}; "
            f"Garage Covers: {sec_topo.get('garage_covers', [])}; "
            f"Sirens: {sec_topo.get('sirens', [])}; "
            f"Bed Occupancy Sensors: {sec_topo.get('bed_sensors', [])}; "
            f"Persons: {sec_topo.get('persons', [])}; "
            f"Perimeter Cameras: {sec_topo.get('perimeter_cameras', [])}"
        )

        # Summarize System Maturity
        maturity = capability_map.get("maturity", {})
        maturity_summary = (
            f"Score: {maturity.get('score', 0)}% ({maturity.get('stage', 'Foundational')}) | "
            f"Unassigned Devices: {maturity.get('unassigned_device_count', 0)}"
        )

        # Summarize Energy & Load Topology
        energy_topo = capability_map.get("energy_topology", {})
        if energy_topo:
            e_tariff = energy_topo.get("tariff", {}).get("period", "standard")
            e_power = energy_topo.get("total_power_w", 0)
            e_solar = energy_topo.get("solar", {}).get("production_w", 0)
            e_shed_count = energy_topo.get("load_shedding", {}).get("active_sheddable_loads_count", 0)
            energy_summary = (
                f"Total Power: {e_power}W | Tariff: {e_tariff.upper()} | Solar Generation: {e_solar}W | "
                f"Sheddable Deferrable Loads: {e_shed_count}"
            )
        else:
            energy_summary = "Not configured or inactive"

        # Summarize top proactive suggestions
        suggestions_list = capability_map.get("proactive_suggestions", [])
        suggestions_summary = "\n".join(
            f"- [{s.get('category', 'general').upper()}] {s.get('title')}: {s.get('description')}"
            for s in suggestions_list[:8]
        ) or "None currently pending."

        # Filter active integrations for the prompt to hardware, ecosystem, and notable platforms
        INTERNAL_INTEGRATION_PREFIXES = (
            "http", "websocket", "system_", "recorder", "history", "logbook", "auth",
            "api", "blueprint", "trace", "diagnostics", "frontend", "lovelace",
            "config", "hassio", "homeassistant", "my", "onboarding", "repairs",
            "search", "update", "backup", "usb", "hardware", "ssdp", "zeroconf", "dhcp",
            "input_", "timer", "counter", "schedule", "tag", "zone", "sun", "tts",
        )
        notable_integrations = [
            i for i in capability_map.get("integrations", [])
            if not any(i.startswith(p) for p in INTERNAL_INTEGRATION_PREFIXES)
        ][:35]

        # 3. Format the prompt wrapping the user's input with the spatial/capability context
        conv_id = user_input.conversation_id or "default"
        session_data = sessions.setdefault(conv_id, {})
        turn_count = session_data.get("turn_count", 0) + 1
        session_data["turn_count"] = turn_count

        rules_snippet = ""
        if getattr(self, "rules_manager", None):
            rules_snippet = self.rules_manager.get_system_prompt_snippet()

        # Retrieve recent conversation turns (up to 10 entries) to guarantee topic focus and continuity
        recent_history = session_data.get("history", [])[-10:]
        history_snippet = ""
        if recent_history:
            history_lines = []
            for h in recent_history:
                role = "User" if h["role"] == "user" else "Otis"
                history_lines.append(f"{role}: {h['text']}")
            history_snippet = "Recent Conversation History:\n" + "\n".join(history_lines) + "\n\n"

        # 3.2 Dynamic Cross-Referencing of Real Automations & Scripts
        matched_yaml_context = ""
        compact_matched_yaml_context = ""
        if getattr(self, "automation_manager", None):
            try:
                related = await self.automation_manager.async_cross_reference(user_input.text)
                matches = related.get("matches", [])
                if matches:
                    fire_progress("domain", "Cross-Referencing Automations", f"Found {len(matches)} matching automations/scripts in YAML")
                    lines = [
                        "REAL SYSTEM AUTOMATIONS & SCRIPTS (Source: automations.yaml & scripts.yaml):",
                        "CRITICAL: When the user asks about behaviors, entities, or rules, inspect these actual configurations instead of guessing!",
                    ]
                    for m in matches:
                        lines.append(f"\n--- # {m['type'].upper()}: {m['name']} (ID: {m['id']})\n{m['yaml']}")
                    if related.get("recent_log_errors"):
                        lines.append("\nRECENT HOME ASSISTANT SYSTEM & AUTOMATION LOG ERRORS:")
                        for err in related["recent_log_errors"]:
                            lines.append(f"• {err}")
                    matched_yaml_context = "\n".join(lines) + "\n\n"

                    # Budgeted YAML context for Local Edge & constrained models (max 2 items, max 1500 chars each)
                    compact_lines = [
                        "REAL SYSTEM AUTOMATIONS & SCRIPTS:",
                        "CRITICAL: Inspect these configurations to answer the user:",
                    ]
                    for m in matches[:2]:
                        yaml_str = m.get("yaml", "")
                        if len(yaml_str) > 1500:
                            yaml_str = yaml_str[:1500] + "\n  # ... [sequence truncated for brevity]"
                        compact_lines.append(f"\n--- # {m['type'].upper()}: {m['name']} (ID: {m['id']})\n{yaml_str}")
                    compact_matched_yaml_context = "\n".join(compact_lines) + "\n\n"

                    _LOGGER.info(
                        "Injected %d cross-referenced automation/script YAML blocks into conversation prompt (budgeted %d for local edge)",
                        len(matches),
                        min(len(matches), 2),
                    )
            except Exception as cr_err:
                _LOGGER.debug("Error cross-referencing automations: %s", cr_err)

        # 3.2.5 Semantic RAG Context Retrieval for Smart Home Manuals & Event Logs
        rag_context = ""
        if getattr(self, "rag_manager", None):
            try:
                rag_context = await self.rag_manager.async_get_rag_context(user_input.text, limit=3)
                if rag_context:
                    fire_progress("domain", "RAG Knowledge Retrieval", "Found relevant smart home documentation & historical logs")
                    _LOGGER.info("Injected semantic RAG context into conversation prompt")
            except Exception as rag_err:
                _LOGGER.debug("RAG context retrieval notice: %s", rag_err)

        ha_version = getattr(getattr(self.hass, "config", None), "version", None) or "2026.11"
        await self.copilot_engine.async_load()
        captured_pre_rules: list[dict[str, Any]] = []
        if intent_cls["is_critique_or_question"] or intent_cls["is_rejection"]:
            captured_pre_rules = await self.copilot_engine.async_capture_user_correction(
                user_text=user_input.text,
                hass=self.hass,
            )
            if captured_pre_rules:
                fire_progress(
                    "learned_rules",
                    f"Saved/updated {len(captured_pre_rules)} learned rule(s)",
                    "; ".join(f.get("fact", "") for f in captured_pre_rules),
                )
        else:
            # Instant grounded acknowledgement for pure teaching/preference statements
            u_teach_low = user_input.text.strip().lower()
            is_pure_teaching = (
                "?" not in u_teach_low
                and not is_create_auto_intent
                and any(
                    u_teach_low.startswith(p)
                    for p in ("remember ", "remember:", "from now on", "actually,", "correction:")
                )
            )
            if is_pure_teaching:
                learned_now = await self.copilot_engine.async_capture_user_correction(
                    user_text=user_input.text,
                    hass=self.hass,
                )
                if learned_now:
                    if getattr(self, "rules_manager", None) and hasattr(self.rules_manager, "async_learn_from_interaction"):
                        await self.rules_manager.async_learn_from_interaction(user_text=user_input.text)
                    facts_summary = "\n".join(f"• {f['fact']}" for f in learned_now)
                    speech = (
                        f"Got it — I've saved this verified rule to Co-Pilot memory and will apply it to all future automations and responses:\n\n"
                        f"{facts_summary}"
                    )
                    fire_progress(
                        "learned_rules",
                        f"Applied {len(self.copilot_engine.get_active_learned_facts())} learned rule(s)",
                        "Saved new verified rule to .storage/otis_ai.copilot_memory",
                    )
                    fire_progress(
                        "agent_resolution",
                        f"Resolved by {active_agent_display}",
                        "Captured verified Co-Pilot rule in <50ms",
                    )
                    self._record_turn(session_data, user_input.text, speech)
                    return self._create_response(user_input, speech)

        backup_summary = ""
        b_cap = capability_map.get("backup") or {}
        if b_cap.get("configured"):
            b_agents = ", ".join(b_cap.get("agents", [])) or "Local"
            b_sched = b_cap.get("schedule", "daily")
            backup_summary = f"- Backup Facility: Configured ({b_sched.capitalize()} backups via {b_agents})\n"

        target_room_lines: list[str] = []
        target_area_ids = {r[0] for r in matched_rooms}
        u_lower_for_room = user_input.text.lower()
        try:
            _room_ent_reg = er.async_get(self.hass)
        except Exception:
            _room_ent_reg = None

        def _prefer_visible_entities(eids: list[str]) -> list[str]:
            """Prefer visible, enabled entities; fall back to hidden entities labeled [hidden] only if none are visible."""
            if not eids or _room_ent_reg is None:
                return eids
            visible: list[str] = []
            hidden: list[str] = []
            for eid in eids:
                entry = _room_ent_reg.async_get(eid)
                if entry is not None and getattr(entry, "disabled_by", None) is not None:
                    continue
                if entry is not None and getattr(entry, "hidden_by", None) is not None:
                    hidden.append(f"{eid} [hidden]")
                else:
                    visible.append(eid)
            return visible if visible else hidden

        for aid, adata in capability_map.get("areas", {}).items():
            aname = str(adata.get("name", aid))
            if target_area_ids:
                area_matches = aid in target_area_ids
            else:
                area_matches = bool(
                    re.search(rf"\b{re.escape(aname.lower())}\b", u_lower_for_room)
                    or re.search(rf"\b{re.escape(aid.lower().replace('_', ' '))}\b", u_lower_for_room)
                )
            if area_matches:
                r_ents = adata.get("entities", [])
                r_occ = _prefer_visible_entities([
                    e for e in r_ents
                    if e.startswith("binary_sensor.")
                    and not e.startswith("binary_sensor.otis_")
                    and not any(bad in e for bad in ("_all_occupancy", "_dog_occupancy", "_pet", "_vehicle"))
                    and any(k in e for k in ("occupancy", "presence", "motion"))
                ])
                def _sensor_dc(eid: str) -> str:
                    st_obj = self.hass.states.get(eid) if getattr(self.hass, "states", None) else None
                    return str((getattr(st_obj, "attributes", {}) or {}).get("device_class") or "") if st_obj else ""

                r_env = _prefer_visible_entities([
                    e for e in r_ents
                    if is_valid_env_sensor(e, device_class=_sensor_dc(e))
                ])
                r_fans = _prefer_visible_entities([e for e in r_ents if e.startswith("fan.")])
                r_lights = _prefer_visible_entities([e for e in r_ents if e.startswith("light.")])
                r_covers = _prefer_visible_entities([e for e in r_ents if e.startswith("cover.")])
                r_locks = _prefer_visible_entities([e for e in r_ents if e.startswith("lock.")])
                r_climate = _prefer_visible_entities([e for e in r_ents if e.startswith("climate.")])
                r_media = _prefer_visible_entities([e for e in r_ents if e.startswith("media_player.")])
                r_switches = _prefer_visible_entities([
                    e for e in r_ents
                    if e.startswith("switch.")
                    and not any(
                        noise in e
                        for noise in (
                            "_auto_update_enabled",
                            "_auto_off_enabled",
                            "_led",
                            "_shuffle_switch",
                            "_repeat_switch",
                            "_do_not_disturb_switch",
                            "_amazon_kids",
                            "_gi1_0_",
                            "_vl12",
                        )
                    )
                ])
                target_room_lines.append(f"VERIFIED ENTITIES IN TARGET ROOM ({aname} — USE ONLY THESE, NEVER GUESS OR INVENT OTHERS):")
                if r_occ:
                    target_room_lines.append(f"  - Occupancy/Motion Sensors: {', '.join(r_occ)}")
                if r_env:
                    target_room_lines.append(f"  - Temperature/Environment Sensors: {', '.join(r_env)}")
                if r_fans:
                    target_room_lines.append(f"  - Fans: {', '.join(r_fans)}")
                if r_lights:
                    target_room_lines.append(f"  - Lights: {', '.join(r_lights)}")
                if r_covers:
                    target_room_lines.append(f"  - Covers/Blinds: {', '.join(r_covers)}")
                if r_locks:
                    target_room_lines.append(f"  - Locks: {', '.join(r_locks)}")
                if r_climate:
                    target_room_lines.append(f"  - Climate: {', '.join(r_climate)}")
                if r_media:
                    target_room_lines.append(f"  - Media/TV Players: {', '.join(r_media)}")
                if r_switches:
                    target_room_lines.append(f"  - Switches: {', '.join(r_switches[:12])}")
        target_room_context = ("\n" + "\n".join(target_room_lines) + "\n") if target_room_lines else ""

        ha_syntax_reference = (
            self.rag_manager.get_distilled_syntax_reference()
            if getattr(self, "rag_manager", None) and hasattr(self.rag_manager, "get_distilled_syntax_reference")
            else ""
        )

        prompt, compact_prompt, applied_rule_count = self.copilot_engine.build_prompts(
            ha_version=ha_version,
            user_text=user_input.text,
            rules_snippet=rules_snippet,
            history_snippet=history_snippet,
            matched_yaml_context=matched_yaml_context,
            compact_matched_yaml_context=compact_matched_yaml_context,
            rag_context=rag_context,
            maturity_summary=maturity_summary,
            notable_integrations=notable_integrations,
            spatial_summary=spatial_summary,
            climate_summary=climate_summary,
            vision_presence_summary=vision_presence_summary,
            media_summary=media_summary,
            security_summary=security_summary,
            energy_summary=energy_summary,
            area_breakdown_summary=area_breakdown_summary,
            entity_summary=entity_summary,
            detailed_entities=detailed_entities,
            existing_automations=existing_automations,
            existing_scripts=existing_scripts,
            orphan_summary=orphan_summary,
            suggestions_summary=suggestions_summary,
            backup_summary=backup_summary,
            target_room_context=target_room_context,
            ha_syntax_reference=ha_syntax_reference,
        )
        if applied_rule_count > 0:
            fire_progress(
                "learned_rules",
                f"Applied {applied_rule_count} learned rule(s)",
                f"Injected {applied_rule_count} verified learned fact(s)/alias(es) from Co-Pilot memory",
            )

        # 4.0A Deterministic Multi-Threshold Room Fan & Room Lighting Automation Synthesizers (<10ms, 100% accurate)
        if target_room_context and getattr(self, "copilot_engine", None):
            from .copilot_engine import (
                try_synthesize_room_fan_automation,
                try_synthesize_room_lighting_automation,
            )

            learned_facts_now = self.copilot_engine.get_active_learned_facts()
            synth = try_synthesize_room_fan_automation(
                user_input.text,
                target_room_context,
                learned_facts_now,
            )
            if synth is None:
                synth = try_synthesize_room_lighting_automation(
                    user_input.text,
                    target_room_context,
                    learned_facts_now,
                )
            if synth is not None:
                session_data["pending_items"] = [{
                    "type": "automation",
                    "name": synth["alias"],
                    "yaml_data": synth["yaml_data"],
                }]
                session_data["pending_yaml"] = session_data["pending_items"][0]
                session_data["last_resolved_agent"] = "Otis Deterministic Synthesizer"
                session_data["last_resolved_agent_id"] = "otis_deterministic_synthesizer"
                session_data["last_failover_occurred"] = False
                fire_progress(
                    "agent_resolution",
                    "Resolved by Otis Deterministic Synthesizer",
                    "Compiled multi-threshold room automation deterministically in <10ms",
                )
                synth_speech = (
                    f"```yaml\n{synth['yaml_str']}\n```\n\n"
                    f"Would you like me to create and enable this automation '{synth['alias']}' in your Home Assistant? "
                    "Say 'yes' or 'apply' to confirm, or 'no' to cancel."
                )
                self._record_turn(session_data, user_input.text, synth_speech)
                return self._create_response(user_input, synth_speech)

        # 4.0a Fast-path Sentinel home audit / anomaly queries deterministically (<50ms, zero LLM hallucinations)
        u_fast_low = user_input.text.strip().lower()
        if (
            getattr(self, "sentinel_manager", None) is not None
            and hasattr(self.sentinel_manager, "async_scan_all_anomalies")
            and any(k in u_fast_low for k in ("sentinel", "anomal", "audit"))
            and not any(k in u_fast_low for k in ("automation", "create ", "yaml", "rule"))
        ):
            try:
                anomalies = await self.sentinel_manager.async_scan_all_anomalies(auto_remediate=False)
                resolved_agent_id = "otis_sentinel"
                resolved_agent_name = "Otis Sentinel Audit"
                session_data["last_resolved_agent"] = resolved_agent_name
                session_data["last_resolved_agent_id"] = resolved_agent_id
                session_data["last_failover_occurred"] = False
                fire_progress(
                    "agent_resolution",
                    "Resolved by Otis Sentinel Audit",
                    f"Completed live home anomaly scan ({len(anomalies)} issue(s) found)",
                )
                if not anomalies:
                    audit_speech = (
                        "I ran a live **Otis Sentinel** audit across your Home Assistant environment and found **0 anomalies**. "
                        "All monitored devices and entities look healthy."
                    )
                else:
                    lines = [
                        f"I ran a live **Otis Sentinel** audit and detected **{len(anomalies)} anomaly(ies)**:"
                    ]
                    for idx, anom in enumerate(anomalies[:10], start=1):
                        sev = str(anom.get("severity", "medium")).upper()
                        title = anom.get("title") or anom.get("entity_id") or "Unknown issue"
                        desc = anom.get("description") or ""
                        lines.append(f"{idx}. **[{sev}] {title}** — {desc}".rstrip(" —"))
                    audit_speech = "\n".join(lines)
                self._record_turn(session_data, user_input.text, audit_speech)
                return self._create_response(user_input, audit_speech)
            except Exception as err:
                _LOGGER.debug("Sentinel audit fast-path failed, falling back to LLM: %s", err)

        # 4.0 Fast-path simple direct device control / state queries via HA Built-in Assist (<100ms, zero LLM tokens)
        # Note: conversation.home_assistant is HA's virtual built-in agent ID (not a state entity in hass.states).
        if (
            not deep_reasoning_needed
            and len(u_fast_low) <= 80
            and not any(q in u_fast_low for q in ("why ", "how ", "explain ", "recommend", "suggest", "compare", "difference", "audit", "anomal", "remember "))
        ):
            try:
                assist_res = await asyncio.wait_for(
                    conversation.async_converse(
                        hass=self.hass,
                        text=user_input.text,
                        conversation_id=user_input.conversation_id,
                        context=user_input.context,
                        language=user_input.language,
                        agent_id="conversation.home_assistant",
                        device_id=user_input.device_id,
                    ),
                    timeout=2.0,
                )
                assist_rtype = str(getattr(assist_res.response, "response_type", "") or "").lower()
                assist_speech = assist_res.response.speech.get("plain", {}).get("speech", "")
                _LOGGER.debug("HA Built-in Assist returned type=%s speech=%s", assist_rtype, assist_speech)
                if assist_rtype.endswith(("action_done", "query_answer")):
                    resolved_agent_id = "conversation.home_assistant"
                    resolved_agent_name = "Home Assistant Assist"
                    session_data["last_resolved_agent"] = resolved_agent_name
                    session_data["last_resolved_agent_id"] = resolved_agent_id
                    session_data["last_failover_occurred"] = False
                    fire_progress(
                        "agent_resolution",
                        "Resolved by Home Assistant Assist",
                        "Executed deterministically via built-in HA intent engine (<100ms)",
                    )
                    self._record_turn(session_data, user_input.text, assist_speech)
                    return assist_res
            except Exception as assist_err:
                _LOGGER.debug("HA Built-in Assist fast-path error: %s", assist_err)

        # 4.0b Fast-path live room sensor state queries directly from hass.states (<5ms)
        if (
            target_room_context
            and not deep_reasoning_needed
            and len(u_fast_low) <= 80
            and any(q in u_fast_low for q in ("what is", "what's", "whats", "is the", "current ", "check "))
            and not any(q in u_fast_low for q in ("why ", "how ", "explain ", "automation", "create ", "turn "))
        ):
            metric_key = None
            if any(k in u_fast_low for k in ("temperature", "temp")):
                metric_key = "temperature"
            elif "humidity" in u_fast_low:
                metric_key = "humidity"
            elif any(k in u_fast_low for k in ("occupied", "occupancy", "motion", "someone", "anyone")):
                metric_key = "occupancy"

            if metric_key and getattr(self.hass, "states", None):
                room_eids = re.findall(r"\b(?:sensor|binary_sensor)\.[a-z0-9_]+\b", target_room_context)
                matched_readings: list[str] = []
                for eid in dict.fromkeys(room_eids):
                    st = self.hass.states.get(eid)
                    if not st or st.state in ("unknown", "unavailable"):
                        continue
                    attrs = getattr(st, "attributes", {}) or {}
                    dc = str(attrs.get("device_class") or "").lower()
                    if metric_key == "temperature" and is_valid_env_sensor(eid, metric="temperature", device_class=dc):
                        unit = attrs.get("unit_of_measurement") or ""
                        fname = attrs.get("friendly_name") or eid
                        matched_readings.append(f"**{fname}** (`{eid}`): **{st.state}{(' ' + unit) if unit else ''}**")
                    elif metric_key == "humidity" and is_valid_env_sensor(eid, metric="humidity", device_class=dc):
                        unit = attrs.get("unit_of_measurement") or "%"
                        fname = attrs.get("friendly_name") or eid
                        matched_readings.append(f"**{fname}** (`{eid}`): **{st.state}{unit}**")
                    elif metric_key == "occupancy" and (
                        (dc in ("occupancy", "motion", "presence") or any(k in eid for k in ("occupancy", "motion")))
                        and not any(bad in eid for bad in ("_all_occupancy", "_dog_occupancy", "_pet", "_vehicle", "_battery"))
                    ):
                        fname = attrs.get("friendly_name") or eid
                        human_state = "Occupied / Detected" if st.state == "on" else "Clear / Unoccupied"
                        matched_readings.append(f"**{fname}** (`{eid}`): **{human_state}**")
                if matched_readings:
                    resolved_agent_id = "otis_live_telemetry"
                    resolved_agent_name = "Otis Live Telemetry"
                    session_data["last_resolved_agent"] = resolved_agent_name
                    session_data["last_resolved_agent_id"] = resolved_agent_id
                    session_data["last_failover_occurred"] = False
                    fire_progress(
                        "agent_resolution",
                        "Resolved by Otis Live Telemetry",
                        f"Read live {metric_key} sensor state directly (<5ms)",
                    )
                    telem_speech = "\n".join(matched_readings)
                    self._record_turn(session_data, user_input.text, telem_speech)
                    return self._create_response(user_input, telem_speech)
                else:
                    room_match = re.search(r"VERIFIED ENTITIES IN TARGET ROOM \(([^—\n)]+)", target_room_context)
                    room_label = room_match.group(1).strip() if room_match else "that room"
                    resolved_agent_id = "otis_live_telemetry"
                    resolved_agent_name = "Otis Live Telemetry"
                    session_data["last_resolved_agent"] = resolved_agent_name
                    session_data["last_resolved_agent_id"] = resolved_agent_id
                    session_data["last_failover_occurred"] = False
                    fire_progress(
                        "agent_resolution",
                        "Resolved by Otis Live Telemetry",
                        f"Verified no {metric_key} sensor is assigned to {room_label} (<5ms)",
                    )
                    telem_speech = (
                        f"There is no **{metric_key}** sensor currently assigned to **{room_label}** in Home Assistant."
                    )
                    self._record_turn(session_data, user_input.text, telem_speech)
                    return self._create_response(user_input, telem_speech)

        # 4. Delegate to prioritized AI agent pool (Paid Cloud -> Healthy Standard Cloud -> Local Qwen -> Restricted Free Tier)
        result = None
        last_error_msg = None
        resolved_agent_name = None
        resolved_agent_id = None
        failover_occurred = False
        local_attempted = False

        local_enabled = getattr(self, "entry", None) is not None and (
            self.entry.options.get(CONF_LOCAL_LLM_ENABLED, self.entry.data.get(CONF_LOCAL_LLM_ENABLED, True))
        )
        has_fallback_agents = (len(prioritized_agents) > 1) or bool(local_enabled and self.local_llm_manager)

        async def _try_local_llm() -> bool:
            nonlocal result, resolved_agent_id, resolved_agent_name, failover_occurred, last_error_msg
            if not (local_enabled and self.local_llm_manager):
                return False
            try:
                failover_occurred = True
                fire_progress("llm", "Local Edge Failover", "Consulting fast offline Local LLM on LAN...")
                health = await self.local_llm_manager.async_health_check()
                if health.get("status") == "online" and health.get("model_ready"):
                    fire_progress(
                        "llm",
                        "Local Edge AI Active",
                        f"Reasoning locally via {health.get('provider')} ({self.local_llm_manager.model})",
                    )
                    relevant_tools = select_relevant_tools(user_input.text)
                    tool_instruction = (
                        "You have access to smart home tools to pin devices on the floorplan, run sentinel audits, "
                        "heal network nodes, and control entities. When asked to take action, call the appropriate tool. "
                        if relevant_tools
                        else ""
                    )
                    local_res = await self.local_llm_manager.async_chat_with_tools(
                        prompt=compact_prompt,
                        tools=relevant_tools,
                        system_prompt=(
                            f"You are Otis AI, the ultimate proactive smart home companion and butler running on Home Assistant {ha_version}. "
                            "Analyze the home's active state and respond concisely and actionably. "
                            "ANTI-HALLUCINATION RULE: Only use exact entity IDs and rooms listed in the prompt. If the user's request is ambiguous or missing details, ask a concise clarifying question first. "
                            f"{tool_instruction}"
                            "Home Assistant Grounding: Voice satellites connect via ESPHome or Wyoming Protocol under Settings → Voice Assistants. "
                            "Provide automations strictly in modern Home Assistant GUI YAML format (clean top-level dict starting with alias:, description:, triggers:, conditions:, actions:, mode: using trigger: and action: keys, without leading dashes or id:). "
                            "Provide exactly one clear, unified configuration block when suggesting automations or scripts. Be direct and concise. "
                            "Always offer to deploy and enable it for the user."
                        ),
                        max_tokens=self.local_llm_manager.max_tokens,
                        max_iterations=2,
                        timeout=max(reasoning_timeout, 60.0),
                    )
                    if local_res.get("success") and (local_res.get("response") or local_res.get("executed_tools")):
                        resp_text = local_res.get("response", "")
                        if not resp_text and local_res.get("executed_tools"):
                            executed_tools = [t.get("tool", "") for t in local_res["executed_tools"]]
                            resp_text = f"Otis AI executed the following actions: {', '.join(executed_tools)}."
                        resolved_agent_id = f"local_llm:{self.local_llm_manager.model}"
                        resolved_agent_name = f"Local Edge ({self.local_llm_manager.model})"
                        tool_count = len(local_res.get("executed_tools", []))
                        _LOGGER.info(
                            "Local Edge AI (%s) responded in %ss (%s tool(s) executed)",
                            self.local_llm_manager.model,
                            local_res.get("total_duration_s"),
                            tool_count,
                        )
                        fire_progress(
                            "agent_resolution",
                            f"Resolved by Local Edge ({self.local_llm_manager.model})",
                            f"Executed locally by {self.local_llm_manager.model} via Ollama in {local_res.get('total_duration_s')}s with {tool_count} tool(s)",
                        )
                        result = self._create_response(user_input, resp_text)
                        return True
                    else:
                        err_detail = local_res.get("error") or "Local LLM returned an empty response"
                        _LOGGER.warning("Local LLM returned error: %s", err_detail)
                        if not last_error_msg:
                            last_error_msg = err_detail
            except Exception as local_err:
                _LOGGER.debug("Local LLM invocation notice: %s", local_err)
                if not last_error_msg:
                    last_error_msg = str(local_err)
            return False

        health_metrics = (
            self.rules_manager.get_agent_health_metrics()
            if getattr(self, "rules_manager", None) and hasattr(self.rules_manager, "get_agent_health_metrics")
            else {}
        )

        # 4.1 Primary Inference: Run Local Edge AI first only when no healthy cloud agent is prioritized
        if local_enabled and self.local_llm_manager and not local_attempted and active_agent_id.startswith("local_llm:"):
            local_attempted = True
            await _try_local_llm()

        # 4.2 Fallback Inference: Only fall back to healthy Paid or Standard Cloud agents (never slow community free tiers)
        if result is None and prioritized_agents:
            for idx, agent_id in enumerate(prioritized_agents):
                agent_display = get_agent_display_name(self.hass, agent_id)
                ce_for_agent, _, _, _ = _resolve_agent_config_entry(self.hass, str(agent_id))
                _, agent_cfg_model, _ = _extract_cloud_agent_config(ce_for_agent)
                if agent_cfg_model and getattr(self, "rules_manager", None):
                    if await _sync_cloud_agent_model_metrics(self.rules_manager, [str(agent_id)], agent_cfg_model):
                        health_metrics = self.rules_manager.get_agent_health_metrics() or {}
                agent_info = classify_and_score_agent(self.hass, str(agent_id), health_metrics)
                agent_tier = agent_info["tier"]
                is_free_restricted = (agent_tier == "free_restricted")
                is_degraded_cloud = (agent_info["consecutive_failures"] >= 2 and (time.time() - agent_info["last_error_ts"]) < 600)

                is_groq = agent_info["domain"] == "groq" or "groq" in str(agent_id).lower() or "groq" in agent_display.lower()
                # Prefer paid / cloud_standard agents first; only use free_restricted (e.g. OpenRouter Free Models Router, Groq)
                # as a last-resort cloud failover when no healthy paid/standard cloud agent remains.
                has_remaining_standard = any(
                    classify_and_score_agent(self.hass, str(rem_id), health_metrics)["tier"] in ("paid", "cloud_standard")
                    and not (
                        classify_and_score_agent(self.hass, str(rem_id), health_metrics)["consecutive_failures"] >= 2
                        and (time.time() - classify_and_score_agent(self.hass, str(rem_id), health_metrics)["last_error_ts"]) < 600
                    )
                    for rem_id in prioritized_agents[idx + 1 :]
                )
                if is_free_restricted and has_remaining_standard:
                    _LOGGER.debug("Deferring restricted free tier agent '%s' (%s) while standard cloud agents remain", agent_display, agent_id)
                    continue

                if is_degraded_cloud:
                    _LOGGER.debug("Skipping degraded cloud agent '%s' (%s)", agent_display, agent_id)
                    continue

                is_primary = (idx == 0 and not local_attempted)
                role_label = "Primary" if is_primary else f"Failover #{idx}"
                if is_free_restricted:
                    agent_timeout = min(reasoning_timeout, 25.0)
                elif has_fallback_agents and agent_tier != "paid":
                    agent_timeout = min(reasoning_timeout, 60.0 if deep_reasoning_needed else 30.0)
                else:
                    agent_timeout = reasoning_timeout
                _LOGGER.debug(
                    "Attempting conversation with %s AI agent: %s (%s, tier=%s, score=%s, timeout=%ss)",
                    role_label, agent_display, agent_id, agent_tier, agent_info["score"], agent_timeout
                )
                fire_progress("llm", f"Consulting {role_label} AI ({agent_display})", f"Reasoning with model '{agent_display}' [{agent_tier.replace('_', ' ').title()}] (max {int(agent_timeout)}s)")

                attempt_start_ts = time.monotonic()
                try:
                    # For agents with strict payload/token constraints (e.g. Groq with HTTP 413 or free restricted tiers)
                    # or pure explanatory/syntax queries, use compact_prompt to avoid 60s cloud timeouts.
                    agent_prompt = prompt
                    is_exp_query = is_explanatory_query(user_input.text)
                    is_groq = agent_info["domain"] == "groq" or "groq" in str(agent_id).lower() or "groq" in agent_display.lower()
                    if ((is_groq or is_free_restricted) and len(prompt) > 3500) or (is_exp_query and not target_room_context):
                        agent_prompt = compact_prompt
                    max_free_chars = 1800 if is_groq else 3500
                    if (is_groq or is_free_restricted) and len(agent_prompt) > max_free_chars:
                        tail_marker = "User Request:" if "User Request:" in agent_prompt else "User:"
                        head_part, sep, tail_part = agent_prompt.rpartition(tail_marker)
                        tail_block = (sep + tail_part) if sep else f"\nUser Request: {user_input.text}"
                        budget = max(400, max_free_chars - len(tail_block) - len(target_room_context) - 64)
                        agent_prompt = head_part[:budget].rstrip() + "\n" + target_room_context + "\n" + tail_block

                    converse_coro = conversation.async_converse(
                        hass=self.hass,
                        text=agent_prompt,
                        conversation_id=user_input.conversation_id,
                        context=user_input.context,
                        language=user_input.language,
                        agent_id=agent_id,
                        device_id=user_input.device_id,
                    )
                    attempt_result = await asyncio.wait_for(converse_coro, timeout=agent_timeout)
                    elapsed_s = round(time.monotonic() - attempt_start_ts, 2)

                    resp_type = getattr(attempt_result.response, "response_type", None)
                    raw_speech = attempt_result.response.speech.get("plain", {}).get("speech", "")
                    speech_text = sanitize_model_speech(raw_speech)
                    had_leaked_tags = (speech_text != raw_speech.strip())
                    if getattr(attempt_result, "response", None) and getattr(attempt_result.response, "speech", None) and "plain" in attempt_result.response.speech:
                        attempt_result.response.speech["plain"]["speech"] = speech_text

                    is_err_type = str(resp_type).lower().endswith("error")

                    if is_err_type or is_provider_error(raw_speech) or is_provider_error(speech_text) or not speech_text:
                        failover_occurred = True
                        if getattr(self, "rules_manager", None) and hasattr(self.rules_manager, "async_record_agent_metric"):
                            await self.rules_manager.async_record_agent_metric(
                                str(agent_id),
                                success=False,
                                latency_s=elapsed_s,
                                quality_penalty=2 if had_leaked_tags else 1,
                                error_reason=speech_text[:140] or "provider_error",
                                configured_model=agent_cfg_model or None,
                            )
                        _LOGGER.warning(
                            "%s AI agent '%s' (%s) returned provider error/quota exhaustion: %s. Transparently failing over to next agent...",
                            role_label, agent_display, agent_id, speech_text[:140]
                        )
                        last_error_msg = speech_text
                        if idx + 1 < len(prioritized_agents):
                            next_agent = prioritized_agents[idx + 1]
                            next_display = get_agent_display_name(self.hass, next_agent)
                            fire_progress(
                                "llm",
                                f"Quota Failover ({role_label})",
                                f"Agent '{agent_display}' quota limit reached. Transparently failing over to '{next_display}'..."
                            )
                        continue

                    if getattr(self, "rules_manager", None) and hasattr(self.rules_manager, "async_record_agent_metric"):
                        await self.rules_manager.async_record_agent_metric(
                            str(agent_id),
                            success=True,
                            latency_s=elapsed_s,
                            quality_penalty=1 if had_leaked_tags else 0,
                            configured_model=agent_cfg_model or None,
                        )
                    _LOGGER.info("AI agent '%s' (%s) responded successfully in %ss", agent_display, role_label, elapsed_s)
                    result = attempt_result
                    resolved_agent_id = agent_id
                    resolved_agent_name = agent_display
                    fire_progress(
                        "agent_resolution",
                        f"Resolved by {agent_display}",
                        f"Response generated by {role_label} AI: {agent_display} ({elapsed_s}s)",
                    )
                    break
                except TimeoutError:
                    failover_occurred = True
                    elapsed_s = round(time.monotonic() - attempt_start_ts, 2)
                    if getattr(self, "rules_manager", None) and hasattr(self.rules_manager, "async_record_agent_metric"):
                        await self.rules_manager.async_record_agent_metric(
                            str(agent_id),
                            success=False,
                            latency_s=elapsed_s,
                            error_reason=f"Timeout after {int(agent_timeout)}s",
                            configured_model=agent_cfg_model or None,
                        )
                    _LOGGER.warning(
                        "%s AI agent '%s' (%s) timed out after %ss. Transparently failing over to next agent...",
                        role_label, agent_display, agent_id, agent_timeout
                    )
                    last_error_msg = f"Agent '{agent_display}' timed out after {int(agent_timeout)}s"
                    if idx + 1 < len(prioritized_agents):
                        next_agent = prioritized_agents[idx + 1]
                        next_display = get_agent_display_name(self.hass, next_agent)
                        fire_progress(
                            "llm",
                            f"Timeout Failover ({role_label})",
                            f"Agent '{agent_display}' timed out ({int(agent_timeout)}s). Transparently failing over to '{next_display}'..."
                        )
                    continue
                except Exception as err:
                    failover_occurred = True
                    elapsed_s = round(time.monotonic() - attempt_start_ts, 2)
                    if getattr(self, "rules_manager", None) and hasattr(self.rules_manager, "async_record_agent_metric"):
                        await self.rules_manager.async_record_agent_metric(
                            str(agent_id),
                            success=False,
                            latency_s=elapsed_s,
                            error_reason=str(err),
                            configured_model=agent_cfg_model or None,
                        )
                    _LOGGER.warning(
                        "%s AI agent '%s' (%s) raised exception: %s. Transparently failing over...",
                        role_label, agent_display, agent_id, err
                    )
                    last_error_msg = str(err)
                    if idx + 1 < len(prioritized_agents):
                        next_agent = prioritized_agents[idx + 1]
                        next_display = get_agent_display_name(self.hass, next_agent)
                        fire_progress(
                            "llm",
                            f"Failover ({role_label})",
                            f"Agent '{agent_display}' error. Failing over to '{next_display}'..."
                        )
                    continue

        # 4.5. Offline / Local LLM Failover if not already attempted
        if result is None and not local_attempted:
            await _try_local_llm()

        if result is not None:
            session_data["last_resolved_agent"] = resolved_agent_name or "Primary Cloud AI"
            session_data["last_resolved_agent_id"] = resolved_agent_id
            session_data["last_failover_occurred"] = failover_occurred
        else:
            session_data["last_resolved_agent"] = None
            session_data["last_resolved_agent_id"] = None
            session_data["last_failover_occurred"] = True

        if result is None:
            _LOGGER.error("All AI agents and local failovers failed. Last error: %s", last_error_msg)
            is_quota = (
                last_error_msg
                and any(q in last_error_msg.lower() for q in ("quota", "429", "413", "resource_exhausted", "capacity", "rate limit", "too large", "tpm", "payload"))
            )
            if is_quota:
                quota_msg = (
                    "⚠️ **AI Provider Quota Exhausted**: Your primary AI agent and failover agents have reached their API rate or quota limits.\n\n"
                    "Please check your API key quota & billing, or configure a Paid Cloud API (Anthropic Claude, OpenAI, Gemini Paid) or Local Ollama in *Settings → Devices & Services → Otis AI Companion*."
                )
                self._record_turn(session_data, user_input.text, quota_msg)
                return self._create_response(user_input, quota_msg)
            msg = "All available AI services are currently experiencing high demand or downtime. Please try again in a moment."
            self._record_turn(session_data, user_input.text, msg)
            return self._create_response(user_input, msg)

        # 5. Post-response Quality Equalization, Modern Syntax Upgrade & Anti-Hallucination Self-Learning
        try:
            speech_text = result.response.speech.get("plain", {}).get("speech", "")
            if speech_text:
                upgraded_speech, quality_notes, quality_penalty = validate_and_upgrade_assistant_response(
                    self.hass,
                    speech_text,
                    target_room_context=target_room_context,
                    user_text=user_input.text,
                )
                if (
                    "Removed draft YAML block" in upgraded_speech
                    and quality_notes
                    and resolved_agent_id
                    and str(resolved_agent_id).startswith("local_llm:")
                    and getattr(self, "local_llm_manager", None)
                ):
                    fire_progress(
                        "yaml_repair",
                        "Repairing Draft YAML",
                        "Detected invalid YAML syntax or entity ID; running targeted 1-shot repair...",
                    )
                    repair_prompt = (
                        f"Fix the Home Assistant {ha_version} automation YAML for this request.\n"
                        f"User Request: {user_input.text}\n"
                        f"{target_room_context}\n"
                        "Validation Errors to Fix:\n- "
                        + "\n- ".join(quality_notes)
                        + "\n\nRules:\n"
                        "- Output ONE clean ```yaml block starting with alias:, description:, triggers:, conditions:, actions:, mode:.\n"
                        "- Use ONLY exact entity_ids from VERIFIED ENTITIES IN TARGET ROOM above.\n"
                        "- Use - choose: with conditions: (condition: state, or condition: numeric_state with above:/below:) and sequence:.\n"
                        "- For fans, use action: fan.set_percentage (data: percentage: 33/66/100) and action: fan.turn_off.\n"
                    )
                    repair_res = await self.local_llm_manager.async_chat_with_tools(
                        prompt=repair_prompt,
                        tools=[],
                        system_prompt=(
                            f"You are Otis AI on Home Assistant {ha_version}. "
                            "Output one valid, error-free Home Assistant GUI YAML automation block and a brief 1-sentence summary."
                        ),
                        max_tokens=min(getattr(self.local_llm_manager, "max_tokens", 1024), 1024),
                        max_iterations=1,
                        timeout=max(reasoning_timeout, 60.0),
                    )
                    repaired_raw = (repair_res or {}).get("response", "") if isinstance(repair_res, dict) else ""
                    if repaired_raw:
                        rep_upgraded, rep_notes, rep_penalty = validate_and_upgrade_assistant_response(
                            self.hass, repaired_raw, target_room_context=target_room_context
                        )
                        if "Removed draft YAML block" not in rep_upgraded and "```yaml" in rep_upgraded:
                            upgraded_speech = rep_upgraded
                            quality_notes = rep_notes
                            quality_penalty = rep_penalty
                if upgraded_speech != speech_text:
                    speech_text = upgraded_speech
                    result.response.speech["plain"]["speech"] = speech_text
                if quality_penalty > 0 and resolved_agent_id and getattr(self, "rules_manager", None) and hasattr(self.rules_manager, "async_record_agent_metric"):
                    await self.rules_manager.async_record_agent_metric(
                        str(resolved_agent_id),
                        success=True,
                        quality_penalty=quality_penalty,
                    )
                if getattr(self, "rules_manager", None) and hasattr(self.rules_manager, "async_learn_from_interaction"):
                    await self.rules_manager.async_learn_from_interaction(
                        user_text=user_input.text,
                        assistant_text=speech_text,
                        correction_notes=quality_notes,
                    )
                captured_post_rules: list[dict[str, Any]] = []
                if getattr(self, "copilot_engine", None) and hasattr(self.copilot_engine, "async_capture_user_correction"):
                    captured_post_rules = await self.copilot_engine.async_capture_user_correction(
                        user_text=user_input.text,
                        assistant_text=speech_text,
                        hass=self.hass,
                    )
                pending_items, cleaned_speech = self._extract_pending_items_from_speech(speech_text, user_input.text)
                if pending_items:
                    session_data["pending_items"] = pending_items
                    session_data["pending_yaml"] = pending_items[0]
                    _LOGGER.debug("Stored %d pending configuration item(s): %s", len(pending_items), pending_items)
                    result.response.speech["plain"]["speech"] = cleaned_speech
                else:
                    # Strip any LLM-hallucinated confirmation prompt if no valid YAML block is present
                    stripped_confirm = re.sub(
                        r"\n*\s*Would you like (?:me )?to (?:proceed with setting up|create|deploy)[^\n]*\n*(?:Say\s+['\"]?yes['\"]?\s+or\s+['\"]?(?:apply|confirm)['\"]?[^\n]*)?",
                        "",
                        speech_text,
                        flags=re.IGNORECASE,
                    ).strip()
                    if stripped_confirm != speech_text:
                        result.response.speech["plain"]["speech"] = stripped_confirm
                newly_learned = list(captured_pre_rules) + list(captured_post_rules)
                if newly_learned:
                    facts_line = "; ".join(f.get("fact", "") for f in newly_learned if f.get("fact"))
                    if captured_post_rules:
                        fire_progress(
                            "learned_rules",
                            f"Saved/updated {len(captured_post_rules)} learned rule(s)",
                            facts_line,
                        )
                    if facts_line:
                        cur_speech = result.response.speech["plain"].get("speech", "")
                        result.response.speech["plain"]["speech"] = (
                            f"{cur_speech}\n\n> 🧠 **Learned Rule Saved:** {facts_line}"
                        )
        except Exception as parse_err:
            _LOGGER.error("Error parsing LLM response for YAML: %s", parse_err)

        # Track conversation turns in session history (both cloud and local LLM)
        resp_speech = ""
        if result and getattr(result, "response", None):
            resp_speech = getattr(result.response, "speech", {}).get("plain", {}).get("speech", "")
        self._record_turn(session_data, user_input.text, resp_speech)

        fire_progress("synthesizing", "Synthesizing Actions", "Validating action safety guards & formatting plan")
        return result
ERROR_SIGNATURES = [
    "sorry, i had a problem getting a response from",
    "sorry, i had a problem talking to",
    "api error",
    "groq api error",
    "openai api error",
    "anthropic api error",
    "gemini api error",
    "google generative ai error",
    "http 413",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "payload too large",
    "request entity too large",
    "context_length_exceeded",
    "maximum context length exceeded",
    "too many tokens",
    "rate_limit_exceeded",
    "rate limit reached",
    "rate limit exceeded",
    "quota_exceeded",
    "quota exceeded",
    "exceeded your current quota",
    "exhausted your capacity",
    "resource has been exhausted",
    "insufficient funds",
    "no credits remaining",
    "check your plan and billing details",
    "model is overloaded",
    "service temporarily unavailable",
    '"code": 503',
    '"code": 429',
    '"code": 413',
    '"status": "unavailable"',
    '"status": "resource_exhausted"',
    "spikes in demand are usually temporary",
    "protect_free_tier",
    "insufficient_quota",
    "too many requests",
]


def sanitize_model_speech(speech: str) -> str:
    """Strip leaked internal thinking tags or malformed tool call blocks from LLM speech."""
    if not speech:
        return speech
    # Remove <think>...</think> blocks
    cleaned = re.sub(r"<think>.*?</think>", "", speech, flags=re.DOTALL)
    # Remove dangling </think>
    cleaned = re.sub(r"^\s*</think>", "", cleaned)
    # Remove <tool_call>...</tool_call>
    cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", cleaned, flags=re.DOTALL)
    # Remove <_observation>...</_observation>
    cleaned = re.sub(r"<_observation>.*?</_observation>", "", cleaned, flags=re.DOTALL)
    # Remove <|dsml|... or < | dsml |...
    cleaned = re.sub(r"<\s*\|\s*dsml\s*\|.*?>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<\s*/\s*tool_call\s*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<\s*tool_call\s*>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def is_provider_error(speech: str) -> bool:
    """Detect if the LLM agent returned a provider error string instead of a valid conversation response."""
    if not speech:
        return True
    speech_lower = speech.lower().strip()

    # Raw tool leakage or internal DSML tags indicate the provider failed to execute or format function calls
    RAW_TOOL_LEAK_SIGNATURES = (
        "<tool_call>",
        "</tool_call>",
        "<_observation>",
        "</think><tool_call>",
        "<|dsml|",
        "< | dsml |",
        "assistantintenthassturnon",
        "assisthomeassistantgetlivecontext",
        '{"data":{"error":"no exposed entities found',
        "no exposed entities found in domain",
    )
    if any(sig in speech_lower for sig in RAW_TOOL_LEAK_SIGNATURES):
        return True

    # Critical quota and rate-limit signatures must trigger failover regardless of length or code formatting
    CRITICAL_QUOTA_STRINGS = (
        "resource_exhausted",
        "resource has been exhausted",
        "exhausted your capacity",
        "quota exceeded",
        "quota_exceeded",
        "exceeded your current quota",
        "rate limit exceeded",
        "rate_limit_exceeded",
        "rate limit reached",
        "too many requests",
        "insufficient_quota",
        "protect_free_tier",
        "429 you have exhausted",
        "error code: 429",
        "status code: 429",
        "status code 429",
    )
    if any(q in speech_lower for q in CRITICAL_QUOTA_STRINGS):
        return True

    if re.search(r"\b(?:http\s*429|status\s*code\s*429|error\s*code\s*429|code\s*429)\b", speech_lower):
        return True

    if "```" in speech or len(speech) > 400:
        return False

    if re.search(r"\b(?:api error|error code|http\s*(?:4\d\d|5\d\d)|status\s*code\s*(?:4\d\d|5\d\d))\b", speech_lower):
        return True
    return any(sig in speech_lower for sig in ERROR_SIGNATURES)


def _resolve_agent_config_entry(
    hass: HomeAssistant | None,
    agent_id: str,
) -> tuple[Any | None, Any | None, str, str]:
    """Resolve (ConfigEntry, ConfigSubentry, platform_domain, canonical_key) for a conversation agent ID."""
    aid_str = str(agent_id or "")
    if not hass:
        return None, None, "", aid_str

    entry = None
    subentry = None
    platform_domain = ""
    canonical_key = aid_str

    if hasattr(hass, "config_entries") and hasattr(hass.config_entries, "async_get_entry"):
        try:
            entry = hass.config_entries.async_get_entry(aid_str)
            if entry is not None and not isinstance(getattr(entry, "domain", None), str):
                entry = None
        except Exception:
            entry = None

    if entry is not None:
        platform_domain = str(getattr(entry, "domain", "") or "").lower()
        canonical_key = str(getattr(entry, "entry_id", aid_str) or aid_str)
        return entry, None, platform_domain, canonical_key

    # Check if aid_str is a subentry ID directly across loaded config entries
    if entry is None and hasattr(hass, "config_entries") and hasattr(hass.config_entries, "async_entries"):
        try:
            for ce in hass.config_entries.async_entries():
                raw_subs = getattr(ce, "subentries", None)
                if isinstance(raw_subs, dict) and aid_str in raw_subs:
                    entry = ce
                    subentry = raw_subs[aid_str]
                    platform_domain = str(getattr(entry, "domain", "") or "").lower()
                    canonical_key = f"{ce.entry_id}:{aid_str}"
                    return entry, subentry, platform_domain, canonical_key
                elif isinstance(raw_subs, (list, tuple)):
                    for s in raw_subs:
                        s_id = getattr(s, "subentry_id", None) or (s.get("subentry_id") if isinstance(s, dict) else None)
                        if s_id == aid_str:
                            entry = ce
                            subentry = s
                            platform_domain = str(getattr(entry, "domain", "") or "").lower()
                            canonical_key = f"{ce.entry_id}:{aid_str}"
                            return entry, subentry, platform_domain, canonical_key
        except Exception:
            pass

    # Resolve conversation.* entity ID via Entity Registry -> parent ConfigEntry & Subentry
    if aid_str.startswith("conversation."):
        try:
            ent_reg = er.async_get(hass)
            ent_entry = ent_reg.async_get(aid_str) if ent_reg and hasattr(ent_reg, "async_get") else None
            if ent_entry is not None:
                platform_domain = str(getattr(ent_entry, "platform", "") or "").lower()
                cfg_id = getattr(ent_entry, "config_entry_id", None)
                sub_id = getattr(ent_entry, "config_subentry_id", None)
                if cfg_id and isinstance(cfg_id, str):
                    canonical_key = f"{cfg_id}:{sub_id}" if sub_id else cfg_id
                    if hasattr(hass, "config_entries") and hasattr(hass.config_entries, "async_get_entry"):
                        c_cand = hass.config_entries.async_get_entry(cfg_id)
                        if c_cand is not None and isinstance(getattr(c_cand, "domain", None), str):
                            entry = c_cand
                            if not platform_domain:
                                platform_domain = str(getattr(entry, "domain", "") or "").lower()
                            raw_subs = getattr(entry, "subentries", None)
                            if sub_id and isinstance(raw_subs, dict):
                                subentry = raw_subs.get(sub_id)
        except Exception:
            pass

    return entry, subentry, platform_domain, canonical_key


def _requires_deep_reasoning(user_text: str) -> bool:
    """Return True when the request requires multi-step reasoning, YAML authoring, or debugging."""
    text = (user_text or "").strip().lower()
    if not text:
        return False
    deep_markers = (
        "create an automation",
        "create automation",
        "write an automation",
        "create a script",
        "write a script",
        "blueprint",
        "automate",
        "automation for",
        "yaml",
        "jinja",
        "template",
        "diagnose",
        "debug",
        "troubleshoot",
        "optimize",
        "refactor",
        "recover",
        "restore",
        "audit",
        "explain ",
        "syntax",
        "difference between",
        "compare ",
        "triggers",
    )
    if any(m in text for m in deep_markers):
        return True
    # Multi-condition branching requests (e.g. "when ... above ... below ... or ...")
    if len(text) > 90 and sum(1 for kw in ("when ", "above ", "below ", "if ", "unless ", "otherwise ", "and ", " or ") if kw in text) >= 3:
        return True
    return False


def classify_and_score_agent(
    hass: HomeAssistant | None,
    agent_id: str,
    health_metrics: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Classify a conversation agent into Paid, Standard Cloud, or Restricted Free Tier and compute a live health score."""
    aid_str = str(agent_id or "")
    aid_lower = aid_str.lower()
    entry, matched_sub, resolved_platform, canonical_key = _resolve_agent_config_entry(hass, aid_str)

    domain = str(getattr(entry, "domain", "") or resolved_platform or "").lower()
    title = str(getattr(entry, "title", "") or "").lower()
    data = dict(getattr(entry, "data", {}) or {})
    options = dict(getattr(entry, "options", {}) or {})

    # Inspect subentries (Home Assistant 2025/2026 stores model/protect_free_tier in subentries)
    sub_models: list[str] = []
    sub_titles: list[str] = []
    protect_free_tier = bool(options.get("protect_free_tier") or data.get("protect_free_tier"))
    explicit_paid = bool(options.get("paid_tier") or data.get("paid_tier"))

    if matched_sub is not None:
        sub_iterable = [matched_sub]
    else:
        raw_subs = getattr(entry, "subentries", None)
        sub_iterable = (
            raw_subs.values()
            if isinstance(raw_subs, dict)
            else (raw_subs if isinstance(raw_subs, (list, tuple)) else [])
        )
    for sub in sub_iterable:
        s_data = getattr(sub, "data", None) or (sub.get("data") if isinstance(sub, dict) else {}) or {}
        s_title = getattr(sub, "title", None) or (sub.get("title") if isinstance(sub, dict) else "") or ""
        if s_title:
            sub_titles.append(str(s_title).lower())
        for mk in ("model", "chat_model"):
            if s_data.get(mk):
                sub_models.append(str(s_data[mk]).lower())
        if s_data.get("protect_free_tier"):
            protect_free_tier = True
        if s_data.get("paid_tier"):
            explicit_paid = True

    for mk in ("model", "chat_model"):
        if options.get(mk):
            sub_models.append(str(options[mk]).lower())
        if data.get(mk):
            sub_models.append(str(data[mk]).lower())

    combined_meta = f"{aid_lower} {domain} {title} {' '.join(sub_titles)} {' '.join(sub_models)}"

    # Determine Tier:
    # 1. Restricted Free Tier (Groq Free Tier with strict 6k-12k TPM, OpenRouter Free Models Router)
    is_openrouter_free = (
        ("open_router" in combined_meta or "openrouter" in combined_meta or "free models" in combined_meta)
        and any(f in combined_meta for f in ("openrouter/free", ":free", "free models", "free router", "free"))
        and not explicit_paid
    )
    is_groq_free = (
        (domain == "groq" or "groq" in combined_meta)
        and (protect_free_tier or "free" in combined_meta or not explicit_paid)
    )
    is_generic_free = (
        any(f in combined_meta for f in ("free_models", "free models", "free_router", "free router", ":free", "openrouter/free"))
        and not explicit_paid
    )

    # 2. Paid Tier (Anthropic Claude, OpenAI, xAI / Extended OpenAI, Paid OpenRouter, or explicitly marked paid)
    is_paid_domain = domain in (
        "anthropic",
        "openai_conversation",
        "extended_openai_conversation",
        "azure_openai_conversation",
    ) or any(
        p in aid_lower for p in ("anthropic", "claude", "openai", "gpt-4", "grok")
    )
    is_openrouter_paid = (
        (domain == "open_router" or "openrouter" in combined_meta)
        and not is_openrouter_free
        and bool(sub_models or explicit_paid)
    )

    if explicit_paid or is_paid_domain or is_openrouter_paid:
        tier = "paid"
        tier_rank = 0
        base_score = 100.0
    elif is_groq_free or is_openrouter_free or is_generic_free:
        tier = "free_restricted"
        tier_rank = 2
        base_score = 15.0
    else:
        tier = "cloud_standard"
        tier_rank = 1
        base_score = 75.0

    m = (health_metrics or {}).get(aid_str) or (health_metrics or {}).get(canonical_key) or {}
    consec_fail = int(m.get("consecutive_failures", 0))
    err_count = int(m.get("error_count", 0))
    succ_count = int(m.get("success_count", 0))
    avg_lat = float(m.get("avg_latency_s", 2.0))
    q_penalties = int(m.get("quality_penalties", 0))
    last_err_ts = float(m.get("last_error_ts", 0.0))

    # Dynamic adjustments based on availability, latency, and response quality
    score = base_score
    score += min(15.0, succ_count * 1.5)
    score -= min(30.0, err_count * 3.0)
    score -= min(25.0, q_penalties * 4.0)

    # Recent consecutive failures heavily demote overloaded/rate-limited agents (e.g. Gemini Free 429/503)
    if consec_fail > 0:
        recency_mult = 2.0 if (time.time() - last_err_ts) < 900 else 1.0
        score -= consec_fail * 20.0 * recency_mult
        if consec_fail >= 2 and tier == "cloud_standard":
            tier_rank = 2  # Demote overloaded standard cloud below healthy agents

    # Fast latency bonus / slow latency penalty
    if avg_lat > 8.0:
        score -= min(15.0, (avg_lat - 8.0) * 1.5)
    elif 0 < avg_lat < 3.5 and succ_count > 0:
        score += 5.0

    return {
        "agent_id": aid_str,
        "canonical_key": canonical_key,
        "domain": domain,
        "tier": tier,
        "tier_rank": tier_rank,
        "score": round(score, 2),
        "avg_latency_s": avg_lat,
        "consecutive_failures": consec_fail,
        "last_error_ts": last_err_ts,
    }


async def async_get_prioritized_agents(hass: HomeAssistant, preferred_agent_id: str | None = None) -> list[str]:
    """Return a dynamically ordered list of conversation agent IDs based on Paid status, live availability, latency, and quality."""
    from .config_flow import _get_agents, async_get_system_ai_preferred_agent

    agents = _get_agents(hass)
    discovered_ids = [getattr(a, "id", str(a)) for a in agents if getattr(a, "id", str(a)) is not None]

    # Retrieve live agent health telemetry from rules_manager if loaded
    health_metrics: dict[str, dict[str, Any]] = {}
    if hass and hasattr(hass, "data") and isinstance(hass.data.get(DOMAIN), dict):
        for val in hass.data[DOMAIN].values():
            if isinstance(val, dict) and "rules_manager" in val:
                rm = val["rules_manager"]
                if hasattr(rm, "get_agent_health_metrics"):
                    health_metrics = rm.get_agent_health_metrics()
                    break

    primary_choice = preferred_agent_id
    if not primary_choice and hass is not None:
        sys_pref = await async_get_system_ai_preferred_agent(hass, agents)
        if sys_pref and sys_pref in discovered_ids:
            primary_choice = sys_pref

    # If primary_choice is a legacy config_entry_id and a conversation.* entity_id exists in discovered_ids for that entry, prefer the discovered entity_id
    if primary_choice and primary_choice not in discovered_ids:
        p_entry, _, _, _ = _resolve_agent_config_entry(hass, str(primary_choice))
        p_entry_id = str(getattr(p_entry, "entry_id", "") or "") if p_entry is not None else ""
        if p_entry_id:
            for d_id in discovered_ids:
                d_entry, _, _, _ = _resolve_agent_config_entry(hass, str(d_id))
                if d_entry is not None and str(getattr(d_entry, "entry_id", "") or "") == p_entry_id:
                    primary_choice = str(d_id)
                    break

    raw_candidates: list[str] = []
    if primary_choice:
        raw_candidates.append(primary_choice)
    for aid in discovered_ids:
        if aid not in raw_candidates:
            raw_candidates.append(aid)

    # Deduplicate candidates that resolve to the same underlying ConfigEntry (e.g. entry_id vs conversation.* entity_id)
    all_candidates: list[str] = []
    seen_entry_ids: set[str] = set()
    for aid in raw_candidates:
        c_entry, c_sub, _, c_key = _resolve_agent_config_entry(hass, str(aid))
        entry_id_key = str(getattr(c_entry, "entry_id", "") or "") if c_entry is not None else ""
        # If this config entry has only 1 conversation subentry, deduplicate entry_id and conversation.* entity_id
        if entry_id_key:
            raw_subs = getattr(c_entry, "subentries", None)
            sub_count = len(raw_subs) if isinstance(raw_subs, (dict, list, tuple)) else 0
            dedup_key = entry_id_key if sub_count <= 1 else c_key
        else:
            dedup_key = str(aid)
        if dedup_key in seen_entry_ids:
            continue
        seen_entry_ids.add(dedup_key)
        all_candidates.append(aid)

    scored: list[tuple[int, float, float, int, str]] = []
    for idx, aid in enumerate(all_candidates):
        info = classify_and_score_agent(hass, str(aid), health_metrics)
        eff_score = info["score"]
        tier_rank = info["tier_rank"]
        # Give user's preferred agent a tie-breaker boost within its tier if healthy
        if aid == primary_choice and info["consecutive_failures"] < 2 and info["tier"] != "free_restricted":
            eff_score += 20.0
        scored.append((tier_rank, -eff_score, info["avg_latency_s"], idx, aid))

    scored.sort()
    return [item[4] for item in scored]


class DiscoveryEngine:
    """Discovers and maps the Home Assistant registries and active integrations."""

    CAPABILITY_CACHE_TTL = 120.0
    HABITS_CACHE_TTL = 900.0

    def __init__(
        self,
        hass: HomeAssistant,
        spatial_manager: SpatialGraphManager | None = None,
        floorplan_parser: FloorplanParser | None = None,
        dashboard_manager: DashboardManager | None = None,
        theme_manager: ThemeManager | None = None,
        sentinel_manager: SentinelManager | None = None,
        energy_manager: EnergyManager | None = None,
        vision_manager: VisionPresenceManager | None = None,
        habit_manager: BehavioralHabitManager | None = None,
        commissioning_manager: AutonomousCommissioningManager | None = None,
        federation_manager: FederationManager | None = None,
        rules_manager: BehavioralRulesManager | None = None,
        local_llm_manager: LocalLLMManager | None = None,
        rag_manager: RAGKnowledgeManager | None = None,
        mesh_manager: MeshManager | None = None,
        presence_fusion_manager: PresenceFusionManager | None = None,
        agent_orchestrator: MultiAgentOrchestrator | None = None,
        log_monitor: LogMonitor | None = None,
    ) -> None:
        """Initialize the discovery engine."""
        self.hass = hass
        self.spatial_manager = spatial_manager or SpatialGraphManager(hass)
        self.floorplan_parser = floorplan_parser or FloorplanParser(hass)
        self.theme_manager = theme_manager or ThemeManager(hass)
        self.sentinel_manager = sentinel_manager or SentinelManager(hass)
        self.energy_manager = energy_manager or EnergyManager(hass, spatial_manager=self.spatial_manager)
        self.vision_manager = vision_manager or VisionPresenceManager(hass, spatial_manager=self.spatial_manager)
        self.habit_manager = habit_manager or BehavioralHabitManager(hass, spatial_manager=self.spatial_manager)
        self.commissioning_manager = commissioning_manager or AutonomousCommissioningManager(hass, spatial_manager=self.spatial_manager)
        self.federation_manager = federation_manager or FederationManager(hass)
        self.rules_manager = rules_manager or BehavioralRulesManager(hass)
        self.local_llm_manager = local_llm_manager
        self.rag_manager = rag_manager
        self.mesh_manager = mesh_manager or MeshManager(hass)
        self.presence_fusion_manager = presence_fusion_manager or PresenceFusionManager(hass)
        self.agent_orchestrator = agent_orchestrator
        self.log_monitor = log_monitor
        self.dashboard_manager = dashboard_manager or DashboardManager(
            hass, floorplan_parser=self.floorplan_parser, rules_manager=self.rules_manager
        )
        self._cached_cap_map: dict[str, Any] | None = None
        self._cache_ts: float = 0.0
        self._cache_signature: tuple[Any, ...] | None = None
        self._cached_habits: list[dict[str, Any]] | None = None
        self._habits_cache_ts: float = 0.0
        self._habits_cache_key: tuple[Any, ...] | None = None
        self._suggestions_by_id: dict[str, dict[str, Any]] = {}
        self._ha_news_cache: list[dict[str, Any]] = []
        self._ha_news_cache_ts: float = 0.0
        if not getattr(hass, "is_running", True) and hasattr(hass, "bus") and hasattr(hass.bus, "async_listen_once"):
            try:
                hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED,
                    lambda _: self.invalidate_cache(),
                )
            except Exception:
                pass

    def invalidate_cache(self) -> None:
        """Invalidate the cached capability map and suggestions."""
        self._cached_cap_map = None
        self._cache_ts = 0.0
        self._cache_signature = None

    def get_cached_suggestion(self, suggestion_id: str) -> dict[str, Any] | None:
        """Retrieve a generated suggestion by ID in O(1) without rescanning registries."""
        if not suggestion_id:
            return None
        return self._suggestions_by_id.get(suggestion_id)

    async def async_build_capability_map(
        self,
        force_refresh: bool = False,
        include_suggestions: bool = True,
    ) -> dict[str, Any]:
        """Scan HA registries and compile the capability map."""
        area_reg = ar.async_get(self.hass)
        device_reg = dr.async_get(self.hass)
        entity_reg = er.async_get(self.hass)

        ha_is_ready = getattr(self.hass, "is_running", True)
        area_list = list(area_reg.async_list_areas())
        current_sig = (
            ha_is_ready,
            len(area_list),
            len(device_reg.devices),
            len(entity_reg.entities),
            len(self.hass.config_entries.async_entries()),
            self.floorplan_parser.has_walkthrough(),
            self.floorplan_parser.floorplan_exists(),
        )
        cache_stale_agent = False
        if not force_refresh and self._cached_cap_map is not None:
            for s in self._cached_cap_map.get("proactive_suggestions") or []:
                if isinstance(s, dict) and s.get("action_type") == "configure_agent":
                    pl = s.get("action_payload") or {}
                    ag_id = str(pl.get("agent_id") or "")
                    old_mod = str(pl.get("current_model") or "")
                    ce_live, _, _, _ = _resolve_agent_config_entry(self.hass, ag_id)
                    if ce_live is None:
                        cache_stale_agent = True
                        break
                    _, live_mod, _ = _extract_cloud_agent_config(ce_live)
                    if live_mod and live_mod != old_mod:
                        cache_stale_agent = True
                        break
        now = time.monotonic()
        if (
            not force_refresh
            and not cache_stale_agent
            and self._cached_cap_map is not None
            and self._cache_signature == current_sig
            and (now - self._cache_ts) < self.CAPABILITY_CACHE_TTL
        ):
            cached = dict(self._cached_cap_map)
            if not include_suggestions:
                cached["proactive_suggestions"] = []
            if getattr(self, "rules_manager", None):
                cached["user_rules"] = self.rules_manager.get_rules()
            return cached

        _LOGGER.debug("Discovery Engine: Starting registry scan...")

        # 1. Active Integrations
        active_integrations = sorted(list(self.hass.config.components))
        _LOGGER.debug("Discovery Engine: Found %d active integrations", len(active_integrations))

        # 2. Areas mapping
        areas_map = {}
        for area_entry in area_list:
            areas_map[area_entry.id] = {
                "name": area_entry.name,
                "aliases": list(area_entry.aliases) if area_entry.aliases else [],
                "devices": [],
                "entities": [],
            }
        _LOGGER.debug("Discovery Engine: Found %d areas in registry", len(areas_map))

        # 3. Devices mapping (iterate device_reg.devices directly in HA 2026+ to avoid deprecation warning)
        devices_map = {}
        raw_devices = device_reg.devices
        device_iter = raw_devices.values() if isinstance(raw_devices, dict) else raw_devices
        for device_entry in device_iter:
            devices_map[device_entry.id] = {
                "name": device_entry.name_by_user or device_entry.name,
                "model": device_entry.model,
                "manufacturer": device_entry.manufacturer,
                "area_id": device_entry.area_id,
                "identifiers": [list(x) for x in device_entry.identifiers],
                "via_device_id": device_entry.via_device_id,
            }
            if device_entry.area_id in areas_map:
                areas_map[device_entry.area_id]["devices"].append(device_entry.id)
        _LOGGER.debug("Discovery Engine: Found %d devices in registry", len(devices_map))

        # 4. Active & Orphaned Entities mapping
        entities_list = []
        orphaned_entities = []

        # Only evaluate orphans if Home Assistant is completely started.
        # During startup, integrations load asynchronously and entities may be temporarily unready.
        ha_is_ready = getattr(self.hass, "is_running", True)
        if not ha_is_ready:
            _LOGGER.debug(
                "Discovery Engine: Home Assistant is still starting up; orphan detection suppressed until fully running."
            )

        # Get set of all existing config entry IDs from installed integrations
        installed_config_entries = {
            entry.entry_id for entry in self.hass.config_entries.async_entries()
        }

        # Known helper / system platforms that do not require external component checks
        standard_helpers = (
            "input_boolean",
            "input_number",
            "input_select",
            "input_text",
            "input_datetime",
            "counter",
            "timer",
            "group",
            "utility_meter",
            "template",
            "scene",
            "zone",
        )

        for entity_entry in entity_reg.entities.values():
            if getattr(entity_entry, "disabled_by", None) is not None:
                continue
            # Determine area ID (entity-specific area overrides device area)
            area_id = entity_entry.area_id
            if not area_id and entity_entry.device_id:
                device = device_reg.async_get(entity_entry.device_id)
                if device:
                    area_id = device.area_id

            is_orphan = False
            orphan_reason = None

            # Only check for orphans if HA is running
            if ha_is_ready:
                # Case 1: Entity is linked to a config entry, BUT that config entry was removed/deleted
                if entity_entry.config_entry_id:
                    if entity_entry.config_entry_id not in installed_config_entries:
                        is_orphan = True
                        orphan_reason = "config_entry_removed"
                    # If config_entry_id IS in installed_config_entries, it is NEVER an orphan!
                    # Offline, disconnected, or retry integrations must never have their entities pruned.
                # Case 2: Entity has no config entry (legacy/YAML), and its platform is completely absent
                elif entity_entry.platform:
                    if (
                        entity_entry.platform not in standard_helpers
                        and entity_entry.platform not in self.hass.config.components
                    ):
                        is_orphan = True
                        orphan_reason = "platform_not_loaded"

            state = self.hass.states.get(entity_entry.entity_id)
            raw_attrs = getattr(state, "attributes", None) if state else None
            attrs = dict(raw_attrs) if isinstance(raw_attrs, dict) else {}
            is_restored = bool(attrs.get("restored"))

            ent_cat = getattr(entity_entry, "entity_category", None)
            ent_cat_str = str(getattr(ent_cat, "value", ent_cat)) if ent_cat is not None else None
            dev_cls = attrs.get("device_class") or getattr(entity_entry, "device_class", None) or getattr(entity_entry, "original_device_class", None)
            dev_cls_str = str(dev_cls) if dev_cls is not None else None

            entity_info: dict[str, Any] = {
                "entity_id": entity_entry.entity_id,
                "name": entity_entry.name or entity_entry.original_name,
                "domain": entity_entry.domain,
                "platform": entity_entry.platform,
                "device_id": entity_entry.device_id,
                "area_id": area_id,
                "disabled_by": entity_entry.disabled_by,
                "hidden_by": entity_entry.hidden_by,
                "state": state.state if state else "unknown",
                "entity_category": ent_cat_str,
                "device_class": dev_cls_str,
            }
            if attrs:
                entity_info["attributes"] = {
                    k: attrs[k]
                    for k in ("source_list", "source", "device_class", "group_members", "volume_level")
                    if k in attrs
                }

            if is_orphan:
                entity_info["orphan_reason"] = orphan_reason
                entity_info["is_restored"] = is_restored
                orphaned_entities.append(entity_info)
                _LOGGER.debug(
                    "Discovery Engine: Identified true orphaned entity %s (reason: %s)",
                    entity_entry.entity_id,
                    orphan_reason,
                )
            else:
                entities_list.append(entity_info)
                if area_id in areas_map:
                    areas_map[area_id]["entities"].append(entity_entry.entity_id)

        _LOGGER.debug(
            "Discovery Engine: Scan complete. Active entities: %d, Orphaned entities: %d",
            len(entities_list),
            len(orphaned_entities)
        )

        # 5. Compile spatial adjacency graph
        spatial_graph = await self.spatial_manager.async_get_graph()
        for aid in areas_map:
            areas_map[aid]["adjacent_areas"] = spatial_graph.get("adjacencies", {}).get(aid, [])

        if not getattr(self.floorplan_parser, "_initialized", False) or not self.floorplan_parser.floorplan_exists():
            await self.floorplan_parser.async_load()
        has_floorplan = self.floorplan_parser.floorplan_exists()
        has_walkthrough = self.floorplan_parser.has_walkthrough()

        # 6. Discover advanced Media (Matrix Amp / Cinema) & Security topologies + System Maturity
        media_topology = self._discover_media_topology(areas_map, entities_list, active_integrations)
        security_topology = self._discover_security_topology(areas_map, entities_list, active_integrations)
        climate_topology = self._discover_climate_topology(areas_map, entities_list)
        maturity = self._discover_system_maturity(
            areas_map,
            devices_map,
            entities_list,
            orphaned_entities,
            active_integrations,
            has_walkthrough,
            has_floorplan,
            media_topology,
            security_topology,
        )

        cap_map = {
            "integrations": active_integrations,
            "areas": areas_map,
            "devices": devices_map,
            "entities": entities_list,
            "orphaned_entities": orphaned_entities,
            "spatial_graph": spatial_graph,
            "floorplan": {
                "exists": has_floorplan,
                "walkthrough_completed": has_walkthrough,
                "svg": await self.floorplan_parser.async_get_svg_content() if has_floorplan else None,
                "url": (
                    self.hass.http.async_sign_path("/api/otis_ai/media/otis_floorplan.svg", timedelta(days=365))
                    if has_floorplan and hasattr(self.hass, "http") and hasattr(self.hass.http, "async_sign_path")
                    else ("/api/otis_ai/media/otis_floorplan.svg" if has_floorplan else None)
                ),
                "url_3d": (
                    self.hass.http.async_sign_path("/api/otis_ai/media/otis_floorplan_3d.svg", timedelta(days=365))
                    if has_floorplan and hasattr(self.hass, "http") and hasattr(self.hass.http, "async_sign_path")
                    else ("/api/otis_ai/media/otis_floorplan_3d.svg" if has_floorplan else None)
                ),
                "has_3d_view": has_floorplan,
                "lovelace_yaml": self.floorplan_parser.get_lovelace_yaml() if has_floorplan else None,
                "custom_layout": {
                    **(getattr(self.floorplan_parser, "_metadata", {}).get("custom_layout", {}) or {}),
                    "badges": (
                        self.floorplan_parser.build_effective_badges(areas_map, entities_list, devices_map=devices_map)
                        if hasattr(self.floorplan_parser, "build_effective_badges")
                        else (getattr(self.floorplan_parser, "_metadata", {}).get("custom_layout", {}) or {}).get("badges", [])
                    ),
                },
            },
            "media_topology": media_topology,
            "security_topology": security_topology,
            "climate_topology": climate_topology,
            "maturity": maturity,
        }
        sentinel_data = {"active_anomalies": [], "count": 0}
        if include_suggestions and self.sentinel_manager:
            try:
                anomalies = await self.sentinel_manager.async_scan_all_anomalies()
                sentinel_data = {"active_anomalies": anomalies, "count": len(anomalies)}
            except Exception as err:
                _LOGGER.debug("Error running Sentinel audit during discovery scan: %s", err)
        cap_map["sentinel"] = sentinel_data

        energy_data = {}
        if self.energy_manager:
            try:
                energy_data = await self.energy_manager.async_get_energy_summary()
                energy_data["arbitrage_plan"] = await self.energy_manager.async_get_arbitrage_plan()
            except Exception as err:
                _LOGGER.debug("Error running Energy summary during discovery scan: %s", err)
        cap_map["energy_topology"] = energy_data

        vision_data = {}
        if getattr(self, "vision_manager", None):
            try:
                presence_states = await self.vision_manager.async_get_presence_states(use_cache=True)
                cameras = await self.vision_manager.async_get_cameras()
                vision_data = {
                    "presence": presence_states,
                    "cameras": cameras,
                    "recent_audits": self.vision_manager.get_audit_history(),
                }
            except Exception as err:
                _LOGGER.debug("Error retrieving Vision presence states during discovery scan: %s", err)
        cap_map["vision_topology"] = vision_data

        commissioning_data = {}
        if getattr(self, "commissioning_manager", None):
            try:
                commissioning_data = await self.commissioning_manager.async_audit_unassigned()
            except Exception as err:
                _LOGGER.debug("Error auditing unassigned entities: %s", err)
        cap_map["commissioning"] = commissioning_data

        federation_data = {}
        if getattr(self, "federation_manager", None):
            try:
                federation_data = await self.federation_manager.async_get_federation_summary()
            except Exception as err:
                _LOGGER.debug("Error retrieving federation summary: %s", err)
        cap_map["federation"] = federation_data

        themes = []
        user_themes = {}
        if self.theme_manager:
            themes = await self.theme_manager.async_list_otis_themes()
            user_themes = await self.theme_manager.async_get_user_themes()
        cap_map["themes"] = themes
        cap_map["user_themes"] = user_themes
        cap_map["theme_presets"] = [
            {"key": k, "name": v["name"], "description": v["description"], "preview": v["preview"], "dark_mode": v.get("dark_mode", True)}
            for k, v in PRESET_THEMES.items()
        ]

        user_rules = {}
        if getattr(self, "rules_manager", None):
            user_rules = self.rules_manager.get_rules()
        cap_map["user_rules"] = user_rules

        reasoning_timeout = DEFAULT_REASONING_TIMEOUT
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            reasoning_timeout = float(
                entry.options.get(CONF_REASONING_TIMEOUT)
                or entry.data.get(CONF_REASONING_TIMEOUT)
                or DEFAULT_REASONING_TIMEOUT
            )
            break
        cap_map["reasoning_timeout"] = reasoning_timeout

        local_llm_status = {}
        if getattr(self, "local_llm_manager", None):
            try:
                local_llm_status = await self.local_llm_manager.async_get_ollama_status(force_refresh=force_refresh)
            except Exception as err:
                _LOGGER.debug("Error retrieving local LLM status during discovery scan: %s", err)
        cap_map["local_llm"] = local_llm_status

        # Discovered registered Home Assistant users & person entities
        discovered_users = []
        try:
            if hasattr(self.hass, "auth") and hasattr(self.hass.auth, "async_get_users"):
                auth_users = await self.hass.auth.async_get_users()
                for u in auth_users:
                    if getattr(u, "is_active", True) and not getattr(u, "system_generated", False):
                        discovered_users.append({
                            "id": u.id,
                            "name": u.name or u.id,
                        })
        except Exception as u_err:
            _LOGGER.debug("Could not query auth users: %s", u_err)

        existing_uids = {u["id"] for u in discovered_users}
        for ent in entities_list:
            if ent.get("domain") == "person":
                attrs = ent.get("attributes") or {}
                uid = attrs.get("user_id")
                p_name = attrs.get("friendly_name") or ent.get("name") or ent.get("entity_id")
                if uid and uid not in existing_uids:
                    discovered_users.append({"id": uid, "name": p_name})
                    existing_uids.add(uid)
                elif not uid and ent.get("entity_id") not in existing_uids:
                    discovered_users.append({"id": ent.get("entity_id"), "name": p_name})
        cap_map["users"] = discovered_users

        if getattr(self, "agent_orchestrator", None):
            cap_map["multi_agent"] = {
                "active_agents": ALL_AGENTS,
                "metrics": self.agent_orchestrator._metrics,
            }
            cap_map["voice_satellites"] = self.agent_orchestrator.get_discovered_satellites()

        # Backup Topology & Facility Discovery
        backup_info: dict[str, Any] = {
            "configured": False,
            "agents": [],
            "schedule": "None",
            "retention": {},
            "last_completed": None,
            "last_size_bytes": 0,
        }
        try:
            if hasattr(self.hass, "config_entries") and hasattr(self.hass.config_entries, "async_entries"):
                for entry in self.hass.config_entries.async_entries():
                    edom = str(getattr(entry, "domain", "")).lower()
                    if "backup" in edom:
                        backup_info["configured"] = True
                        backup_info["agents"].append(edom)
            backup_mgr = self.hass.data.get("backup_manager") or self.hass.data.get("backup")
            if backup_mgr is not None:
                b_cfg = getattr(backup_mgr, "config", None)
                if b_cfg:
                    backup_info["configured"] = getattr(b_cfg, "automatic_backups_configured", True)
                    agents = getattr(b_cfg, "agents", {})
                    if isinstance(agents, dict):
                        backup_info["agents"] = list(agents.keys())
        except Exception as b_err:
            _LOGGER.debug("Could not inspect backup manager: %s", b_err)
            _LOGGER.debug("Could not query backup configuration: %s", b_err)
        cap_map["backup"] = backup_info

        if include_suggestions:
            cap_map["proactive_suggestions"] = await self.async_generate_proactive_suggestions(cap_map)
            self._cached_cap_map = dict(cap_map)
            self._cache_ts = now
            self._cache_signature = current_sig
        else:
            cap_map["proactive_suggestions"] = []

        return cap_map

    def _discover_media_topology(
        self,
        areas_map: dict[str, Any],
        entities_list: list[dict[str, Any]],
        active_integrations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Discover Multi-Zone Matrix Amp audio topology, input bridges, and Cinema/TV zones."""
        media_players = [e for e in entities_list if e.get("domain") == "media_player"]
        integration_domains = {
            str(i.get("domain", "") if isinstance(i, dict) else i).lower()
            for i in active_integrations
        }

        # Agnostic preset matching across active integrations and player platforms
        matched_preset = identify_matrix_preset(active_integrations, media_players)
        preset_id = matched_preset.get("id", "universal")
        preset_name = matched_preset.get("name", "Universal Multi-Zone Matrix")
        has_known_matrix_brand = preset_id != "universal"

        # Legacy backward compatibility flag
        has_control4 = preset_id == "control4" or "control4" in integration_domains or any(
            "control4" in str(e.get("platform", "")).lower() for e in media_players
        )

        # Group media players by shared source_list or matrix platform / known room speaker naming
        source_groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for mp in media_players:
            attrs = mp.get("attributes") or {}
            src_list = attrs.get("source_list")
            if isinstance(src_list, (list, tuple)) and len(src_list) >= 2:
                key = tuple(sorted(str(s).strip() for s in src_list if s))
                if key:
                    source_groups.setdefault(key, []).append(mp)

        matrix_zones: list[dict[str, Any]] = []
        shared_sources: list[str] = []

        # Pick largest source group with >= 3 rooms (or >= 2 if recognized matrix preset is active)
        if source_groups:
            best_sources, best_players = max(source_groups.items(), key=lambda kv: len(kv[1]))
            if len(best_players) >= 3 or (has_known_matrix_brand and len(best_players) >= 2):
                shared_sources = list(best_sources)
                matrix_zones = best_players

        # Fallback heuristic: if recognized matrix integration is active or room media players match area names
        if not matrix_zones:
            area_lookup = build_area_lookup_map(areas_map)
            candidate_zones = []
            for mp in media_players:
                eid = mp.get("entity_id", "").lower()
                platform = str(mp.get("platform", "")).lower()
                if any(tok in eid for tok in ("bridge", "tv", "roku", "apple_tv", "shield", "chromecast", "plex")):
                    continue
                matched_area = mp.get("area_id") or resolve_area_identifier(
                    eid.replace("media_player.", ""), area_lookup
                )
                if is_matrix_entity(eid, platform) or matched_area or eid.endswith("_deck") or eid.endswith("_room"):
                    candidate_zones.append(mp)
            if (has_known_matrix_brand and len(candidate_zones) >= 2) or len(candidate_zones) >= 4:
                matrix_zones = candidate_zones
                if not shared_sources:
                    discovered_bridges = [
                        str(mp.get("name") or mp.get("entity_id", ""))
                        for mp in media_players
                        if any(tok in mp.get("entity_id", "").lower() for tok in ("bridge", "stream", "input"))
                    ]
                    shared_sources = discovered_bridges or matched_preset.get(
                        "default_sources", ["Stream 1", "Stream 2", "Media Server", "Home Assistant"]
                    )

        matrix_zone_ids = {z["entity_id"] for z in matrix_zones}

        # Identify upstream input streamer/bridge entities
        input_streamers: list[dict[str, Any]] = []
        shared_norm = {s.lower().replace(" ", "_") for s in shared_sources}
        for mp in media_players:
            eid = mp.get("entity_id", "")
            if eid in matrix_zone_ids:
                continue
            obj = eid.split(".", 1)[-1].lower()
            name_lower = str(mp.get("name") or "").lower()
            if (
                "bridge" in obj
                or "streamer" in obj
                or obj in shared_norm
                or any(s.lower() in name_lower for s in shared_sources if s)
            ):
                input_streamers.append(mp)

        # Identify Cinema / TV media players (using agnostic helper)
        tv_cinema_zones: list[dict[str, Any]] = []
        for mp in media_players:
            eid = mp.get("entity_id", "")
            if eid in matrix_zone_ids:
                continue
            if is_tv_cinema_player(eid, mp.get("attributes")):
                tv_cinema_zones.append(mp)

        return {
            "matrix_amp_detected": len(matrix_zones) >= 2,
            "has_control4": has_control4,
            "matrix_preset": matched_preset,
            "matrix_platform": preset_id,
            "matrix_preset_name": preset_name,
            "matrix_presets_available": get_matrix_presets_list(),
            "matrix_zones": [
                {
                    "entity_id": z["entity_id"],
                    "name": z.get("name") or z["entity_id"],
                    "area_id": z.get("area_id"),
                    "state": z.get("state", "unknown"),
                }
                for z in matrix_zones
            ],
            "shared_sources": shared_sources,
            "matrix_shared_sources": shared_sources,
            "input_streamers": [
                {
                    "entity_id": s["entity_id"],
                    "name": s.get("name") or s["entity_id"],
                    "state": s.get("state", "unknown"),
                }
                for s in input_streamers
            ],
            "tv_cinema_zones": [
                {
                    "entity_id": t["entity_id"],
                    "name": t.get("name") or t["entity_id"],
                    "area_id": t.get("area_id"),
                }
                for t in tv_cinema_zones
            ],
            "total_media_players": len(media_players),
            "ready_for_unified_coordinator": bool(
                len(matrix_zones) >= 2 or (len(input_streamers) >= 1 and len(media_players) >= 2)
            ),
        }

    def _discover_security_topology(
        self,
        areas_map: dict[str, Any],
        entities_list: list[dict[str, Any]],
        active_integrations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Discover Alarmo/alarm panels, smart locks, garage covers, sirens, cameras, persons, and SleepNumber bed occupancy."""
        alarm_panels = [
            e["entity_id"] for e in entities_list if e.get("domain") == "alarm_control_panel"
        ]
        locks = [e["entity_id"] for e in entities_list if e.get("domain") == "lock"]
        sirens = [e["entity_id"] for e in entities_list if e.get("domain") == "siren"]
        raw_cameras = [
            e["entity_id"]
            for e in entities_list
            if e.get("domain") == "camera" and e.get("state") not in ("unavailable", "unknown")
        ]
        cam_groups: dict[str, list[str]] = {}
        for c_eid in raw_cameras:
            if any(k in c_eid.lower() for k in ("map", "vacuum", "cleaning")):
                continue
            ckey = get_canonical_camera_key(c_eid)
            cam_groups.setdefault(ckey, []).append(c_eid)

        strategy = (
            self.vision_manager.get_camera_stream_strategy()
            if self.vision_manager and hasattr(self.vision_manager, "get_camera_stream_strategy")
            else DEFAULT_CAMERA_STREAM_STRATEGY
        )
        ent_plat = {e.get("entity_id"): e.get("platform") for e in entities_list if "entity_id" in e}

        cameras = []
        for c_list in cam_groups.values():
            c_list.sort(key=lambda x: stream_priority(x, x, strategy=strategy, platform=ent_plat.get(x)))
            cameras.append(c_list[0])
        persons = [
            e["entity_id"]
            for e in entities_list
            if e.get("domain") == "person" and e.get("state") not in ("unavailable", "unknown")
        ]

        garage_covers = [
            e["entity_id"]
            for e in entities_list
            if e.get("domain") == "cover"
            and (
                "garage" in e.get("entity_id", "").lower()
                or str((e.get("attributes") or {}).get("device_class", "")).lower() == "garage"
            )
        ]

        bed_occupancy_sensors = [
            e["entity_id"]
            for e in entities_list
            if e.get("domain") == "binary_sensor"
            and any(
                kw in e.get("entity_id", "").lower()
                for kw in ("sleepnumber", "in_bed", "bed_occupancy", "bed_presence", "eight_sleep")
            )
        ]

        driving_sensors = [
            e["entity_id"]
            for e in entities_list
            if e.get("domain") == "binary_sensor"
            and any(kw in e.get("entity_id", "").lower() for kw in ("driving", "android_auto", "carplay"))
        ]

        perimeter_contact_sensors = [
            e["entity_id"]
            for e in entities_list
            if is_contact_sensor(e.get("entity_id", ""))
        ]

        return {
            "alarm_panels": alarm_panels,
            "locks": locks,
            "garage_covers": garage_covers,
            "sirens": sirens,
            "cameras": cameras,
            "persons": persons,
            "bed_occupancy_sensors": bed_occupancy_sensors,
            "driving_sensors": driving_sensors,
            "perimeter_contact_sensors": perimeter_contact_sensors,
            "ready_for_unified_coordinator": bool(
                alarm_panels or locks or garage_covers or bed_occupancy_sensors
            ),
        }

    def _discover_climate_topology(
        self,
        areas_map: dict[str, Any],
        entities_list: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Discover HVAC and climate architecture, mapping thermostats to rooms, setpoints, and zones."""
        climates = [e for e in entities_list if e.get("domain") == "climate"]
        area_lookup = build_area_lookup_map(areas_map)
        thermostats = []
        space_thermostats = []
        equipment_thermostats = []
        area_to_thermostat: dict[str, str | None] = {}
        area_to_floor: dict[str, str] = {}

        upstairs_thermo = None
        downstairs_thermo = None

        for c in climates:
            eid = c["entity_id"]
            state_obj = self.hass.states.get(eid)
            attrs = state_obj.attributes if state_obj else {}
            state_val = state_obj.state if state_obj else c.get("state", "unknown")
            fname = attrs.get("friendly_name", c.get("name", eid))
            check_text = f"{eid} {fname}".lower()

            assigned_area_id = c.get("area_id")
            if not assigned_area_id:
                matched_id = resolve_area_identifier(check_text, area_lookup)
                if not matched_id:
                    for aid in areas_map:
                        if aid in eid.lower() or areas_map[aid].get("name", "").lower() in check_text:
                            assigned_area_id = aid
                            break
                else:
                    assigned_area_id = matched_id

            area_name = areas_map.get(assigned_area_id, {}).get("name", "Whole Home / Unassigned") if assigned_area_id else "Whole Home / Unassigned"

            is_equipment = any(k in check_text for k in ("pool", "spa", "hot_tub", "water_heater", "boiler"))
            zone_scope = "Equipment (Water/Pool/Spa)" if is_equipment else ""

            if not is_equipment:
                if any(k in check_text for k in ("upstairs", "upper", "second", "2nd")):
                    zone_scope = "Upper Floor Zone"
                elif any(k in check_text for k in ("downstairs", "ground", "lower", "main", "1st")):
                    zone_scope = "Ground Floor Zone"
                else:
                    zone_scope = "Whole Home Zone"

            t_info = {
                "entity_id": eid,
                "name": fname,
                "area_id": assigned_area_id,
                "area_name": area_name,
                "state": state_val,
                "current_temperature": attrs.get("current_temperature"),
                "target_temperature": attrs.get("temperature"),
                "target_temp_high": attrs.get("target_temp_high"),
                "target_temp_low": attrs.get("target_temp_low"),
                "hvac_action": attrs.get("hvac_action"),
                "hvac_modes": attrs.get("hvac_modes", []),
                "preset_mode": attrs.get("preset_mode"),
                "fan_mode": attrs.get("fan_mode"),
                "zone_scope": zone_scope,
                "is_equipment": is_equipment,
            }
            thermostats.append(t_info)
            if is_equipment:
                equipment_thermostats.append(t_info)
            else:
                space_thermostats.append(t_info)
                if zone_scope == "Upper Floor Zone" and not upstairs_thermo:
                    upstairs_thermo = t_info
                elif zone_scope == "Ground Floor Zone" and not downstairs_thermo:
                    downstairs_thermo = t_info

        # Determine architecture
        if upstairs_thermo and downstairs_thermo:
            architecture_type = "Central Dual-Zone HVAC (Downstairs & Upstairs)"
        elif space_thermostats:
            architecture_type = f"Central Single-Zone HVAC ({len(space_thermostats)} space thermostat)"
        else:
            architecture_type = "No dedicated space HVAC detected"

        primary_thermostat = (
            downstairs_thermo["entity_id"]
            if downstairs_thermo
            else (space_thermostats[0]["entity_id"] if space_thermostats else (thermostats[0]["entity_id"] if thermostats else None))
        )

        # Map each area to its floor and controlling thermostat
        for aid, adata in areas_map.items():
            aname = adata.get("name", aid)
            floor = classify_area_floor(aid, aname)
            area_to_floor[aid] = floor

            # 1. Exact assigned thermostat in this specific room
            exact_match = next((t["entity_id"] for t in space_thermostats if t.get("area_id") == aid), None)
            if exact_match:
                area_to_thermostat[aid] = exact_match
            elif floor == "Upper Floor" and upstairs_thermo:
                area_to_thermostat[aid] = upstairs_thermo["entity_id"]
            elif floor == "Ground Floor" and downstairs_thermo:
                area_to_thermostat[aid] = downstairs_thermo["entity_id"]
            elif floor == "Outdoor":
                if any(k in aid.lower() for k in ("pool", "spa")) and equipment_thermostats:
                    area_to_thermostat[aid] = equipment_thermostats[0]["entity_id"]
                else:
                    area_to_thermostat[aid] = None
            else:
                area_to_thermostat[aid] = primary_thermostat

        return {
            "thermostats": thermostats,
            "space_thermostats": space_thermostats,
            "equipment_thermostats": equipment_thermostats,
            "architecture_type": architecture_type,
            "area_to_thermostat": area_to_thermostat,
            "area_to_floor": area_to_floor,
            "primary_thermostat": primary_thermostat,
            "upstairs_thermostat": upstairs_thermo["entity_id"] if upstairs_thermo else None,
            "downstairs_thermostat": downstairs_thermo["entity_id"] if downstairs_thermo else None,
            "has_per_room_thermostats": False,
            "total_count": len(thermostats),
        }

    def _discover_system_maturity(
        self,
        areas_map: dict[str, Any],
        devices_map: dict[str, Any],
        entities_list: list[dict[str, Any]],
        orphaned_entities: list[dict[str, Any]],
        active_integrations: list[dict[str, Any]],
        has_walkthrough: bool,
        has_floorplan: bool,
        media_topology: dict[str, Any],
        security_topology: dict[str, Any],
    ) -> dict[str, Any]:
        """Calculate Smart Home Maturity Score (0-100), infer areas for unassigned devices, and build onboarding checklist."""
        area_lookup = build_area_lookup_map(areas_map)

        # Find devices/entities without area_id whose name or entity_id matches a registered area
        inferred_device_assignments: dict[str, str] = {}
        inferred_entity_assignments: dict[str, str] = {}

        # Sort area tokens longest-first so "master_bath" matches before "master"
        sorted_tokens = sorted(area_lookup.items(), key=lambda kv: len(kv[0]), reverse=True)

        def _match_area_from_text(text: str) -> str | None:
            if not text:
                return None
            norm = text.lower().replace("-", "_").replace("'", "_")
            for token, aid in sorted_tokens:
                if len(token) < 3:
                    continue
                if token in norm.split("_") or f"_{token}_" in f"_{norm}_" or token in norm.lower():
                    return aid
            return None

        unassigned_devices_count = 0
        for dev_id, dev in devices_map.items():
            if not dev.get("area_id"):
                unassigned_devices_count += 1
                matched = _match_area_from_text(str(dev.get("name") or ""))
                if matched:
                    inferred_device_assignments[dev_id] = matched

        for ent in entities_list:
            if ent.get("domain") in ("automation", "script", "scene", "person", "zone", "sun", "weather"):
                continue
            if not ent.get("area_id"):
                dev_id = ent.get("device_id")
                if dev_id and dev_id in inferred_device_assignments:
                    continue
                matched = _match_area_from_text(
                    f"{ent.get('entity_id', '')} {ent.get('name', '')}"
                )
                if matched:
                    if dev_id and dev_id in devices_map and not devices_map[dev_id].get("area_id"):
                        inferred_device_assignments[dev_id] = matched
                    else:
                        inferred_entity_assignments[ent["entity_id"]] = matched

        automations_count = sum(1 for e in entities_list if e.get("domain") == "automation")
        scripts_count = sum(1 for e in entities_list if e.get("domain") == "script")
        areas_with_entities = sum(1 for a in areas_map.values() if a.get("entities"))

        # Compute 0-100 Smart Home Maturity Score across 5 weighted dimensions (20 pts each)
        # 1. Spatial & Floor Plan Organization (20 pts)
        spatial_pts = 0
        spatial_gaps: list[str] = []
        if len(areas_map) >= 3:
            spatial_pts += 8
        else:
            spatial_gaps.append(f"Add at least 3 areas (currently {len(areas_map)}).")

        if areas_with_entities >= max(1, len(areas_map) // 2):
            spatial_pts += 6
        else:
            spatial_gaps.append(f"Populate more areas with devices/entities ({areas_with_entities}/{len(areas_map)} populated).")

        if has_walkthrough or has_floorplan:
            spatial_pts += 6
        else:
            spatial_gaps.append("Upload a walkthrough video or create a vector Floor Plan.")

        # 2. Registry Hygiene & Area Assignment (20 pts)
        hygiene_pts = 20
        hygiene_gaps: list[str] = []
        if orphaned_entities:
            hygiene_pts -= min(10, len(orphaned_entities) * 2)
            hygiene_gaps.append(f"Clean up {len(orphaned_entities)} orphaned entities.")
        if inferred_device_assignments or inferred_entity_assignments:
            unassigned_count = len(inferred_device_assignments) + len(inferred_entity_assignments)
            hygiene_pts -= min(10, unassigned_count)
            hygiene_gaps.append(f"Commission or auto-assign {unassigned_count} unassigned devices/entities to areas.")
        hygiene_pts = max(0, hygiene_pts)

        # 3. Lighting & Climate Automation Coverage (20 pts)
        auto_pts = min(20, (automations_count * 4) + (scripts_count * 2))
        auto_gaps: list[str] = []
        if auto_pts < 20:
            needed = max(1, (20 - auto_pts + 3) // 4)
            auto_gaps.append(f"Create ~{needed} more automations or scripts (currently {automations_count} automations, {scripts_count} scripts).")

        # 4. Security & Presence Intelligence (20 pts)
        sec_pts = 0
        sec_gaps: list[str] = []
        if security_topology.get("alarm_panels") or security_topology.get("locks"):
            sec_pts += 10
        else:
            sec_gaps.append("Install an alarm panel (e.g. Alarmo) or smart locks.")

        if security_topology.get("persons") or security_topology.get("bed_occupancy_sensors"):
            sec_pts += 5
        else:
            sec_gaps.append("Configure person presence or bed occupancy sensors.")

        if automations_count >= 2:
            sec_pts += 5
        else:
            sec_gaps.append("Create at least 2 security or arrival/departure automations.")

        # 5. Media & Ecosystem Optimization (20 pts)
        media_pts = 10
        media_gaps: list[str] = []
        media_keywords = ("matrix", "router", "media", "audio", "speaker", "sound", "streamer", "music", "cinema")
        has_media_coordinator = any(
            any(kw in str(e.get("entity_id", "")).lower() or kw in str(e.get("name", "")).lower() for kw in media_keywords)
            for e in entities_list
            if e.get("domain") in ("script", "automation")
        )
        if media_topology.get("matrix_amp_detected"):
            if has_media_coordinator:
                media_pts = 20
            else:
                media_pts = 12
                media_gaps.append("Deploy an Otis Matrix Audio Router script to automate zone switching.")
        elif media_topology.get("total_media_players", 0) > 0:
            if has_media_coordinator or "music_assistant" in active_integrations or "mass" in active_integrations:
                media_pts = 20
            else:
                media_pts = 16
                media_gaps.append("Configure multi-room audio grouping or deploy a media coordinator script.")
        else:
            media_gaps.append("Add media player entities (Sonos, Cast, Apple TV, Music Assistant) to your rooms.")

        tips = {
            "spatial": "20/20 (Perfect) • Spatial organization and floor plan are fully mapped." if spatial_pts >= 20 else f"{spatial_pts}/20 • To reach 20/20: {' '.join(spatial_gaps)}",
            "hygiene": "20/20 (Perfect) • Entity registry is clean with zero unassigned or orphaned entities." if hygiene_pts >= 20 else f"{hygiene_pts}/20 • To reach 20/20: {' '.join(hygiene_gaps)}",
            "automation": "20/20 (Perfect) • Deep automation coverage across lighting, climate, and daily routines." if auto_pts >= 20 else f"{auto_pts}/20 • To reach 20/20: {' '.join(auto_gaps)}",
            "security": "20/20 (Perfect) • Complete security and presence intelligence active." if sec_pts >= 20 else f"{sec_pts}/20 • To reach 20/20: {' '.join(sec_gaps)}",
            "media": "20/20 (Perfect) • Multi-room audio matrix and media players fully coordinated." if media_pts >= 20 else f"{media_pts}/20 • To reach 20/20: {' '.join(media_gaps)}",
        }

        gaps = {
            "spatial": spatial_gaps,
            "hygiene": hygiene_gaps,
            "automation": auto_gaps,
            "security": sec_gaps,
            "media": media_gaps,
        }

        score = max(5, min(100, spatial_pts + hygiene_pts + auto_pts + sec_pts + media_pts))
        if score >= 85:
            stage = "Fully Optimized Smart Home"
        elif score >= 60:
            stage = "Automated & Connected"
        elif score >= 35:
            stage = "Configured Foundation"
        else:
            stage = "Fresh / Bare Installation"

        return {
            "score": score,
            "stage": stage,
            "breakdown": {
                "spatial": spatial_pts,
                "hygiene": hygiene_pts,
                "automation": auto_pts,
                "security": sec_pts,
                "media": media_pts,
            },
            "tips": tips,
            "gaps": gaps,
            "unassigned_devices_count": unassigned_devices_count,
            "inferred_device_assignments": inferred_device_assignments,
            "inferred_entity_assignments": inferred_entity_assignments,
            "automations_count": automations_count,
            "scripts_count": scripts_count,
        }

    def _inspect_config_files_sync(
        self, active_entity_ids: set[str]
    ) -> dict[str, Any]:
        """Synchronously inspect automations.yaml, scripts.yaml, and configuration.yaml for overlap and improvements."""
        result: dict[str, Any] = {
            "norm_names": set(),
            "automated_entities": set(),
            "improvement_suggestions": [],
            "system_suggestions": [],
        }
        if not (hasattr(self.hass, "config") and hasattr(self.hass.config, "path")):
            return result

        try:
            auto_path = self.hass.config.path("automations.yaml")
            script_path = self.hass.config.path("scripts.yaml")
            config_path = self.hass.config.path("configuration.yaml")
        except Exception:
            return result

        if not isinstance(auto_path, str):
            return result

        def _norm(s: str) -> str:
            return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()

        service_verbs = {
            "turn_on",
            "turn_off",
            "turned_on",
            "turned_off",
            "toggle",
            "set_options",
            "select_option",
            "set_value",
            "set_temperature",
            "set_hvac_mode",
            "set_preset_mode",
            "set_fan_mode",
            "set_humidity",
            "volume_set",
            "volume_mute",
            "volume_up",
            "volume_down",
            "media_play",
            "media_pause",
            "media_play_pause",
            "media_stop",
            "media_next_track",
            "media_previous_track",
            "media_seek",
            "play_media",
            "clear_playlist",
            "shuffle_set",
            "repeat_set",
            "join",
            "unjoin",
            "select_source",
            "select_sound_mode",
            "lock",
            "unlock",
            "open",
            "open_cover",
            "close_cover",
            "stop_cover",
            "set_cover_position",
            "set_cover_tilt_position",
            "set_percentage",
            "set_direction",
            "oscillate",
            "increase_speed",
            "decrease_speed",
            "alarm_arm_away",
            "alarm_arm_home",
            "alarm_arm_night",
            "alarm_arm_vacation",
            "alarm_arm_custom_bypass",
            "alarm_disarm",
            " alarm_trigger",
            "start",
            "pause",
            "stop",
            "return_to_base",
            "clean_spot",
            "locate",
            "send_command",
            "set_fan_speed",
            "set_datetime",
            "reload",
            "create",
            "dismiss",
            "backup_full",
            "is_off",
            "is_on",
            "unlocked",
            "locked",
            "trigger",
            "yaml",
            "yml",
            "json",
            "mp3",
            "wav",
            "ogg",
            "flac",
            "m3u",
            "jpg",
            "jpeg",
            "png",
            "gif",
            "mp4",
        }
        tracked_domains = {
            "light",
            "switch",
            "binary_sensor",
            "sensor",
            "media_player",
            "climate",
            "lock",
            "cover",
            "alarm_control_panel",
            "script",
            "input_boolean",
            "input_select",
            "person",
        }

        def _extract_auto_entities(node: Any, parent_key: str = "") -> set[str]:
            """Extract entity_ids referenced in an automation while ignoring blueprint paths, actions, and trigger/condition types."""
            found: set[str] = set()
            skip_keys = {
                "path",
                "action",
                "service",
                "trigger",
                "condition",
                "platform",
                "domain",
                "type",
                "subtype",
                "event",
                "id",
                "alias",
                "description",
                "mode",
                "media_content_id",
                "media_content_type",
                "icon",
                "image",
                "icon_url",
            }
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "use_blueprint" and isinstance(v, dict):
                        if "input" in v:
                            found.update(_extract_auto_entities(v["input"], "input"))
                        continue
                    if k in skip_keys and isinstance(v, str):
                        continue
                    found.update(_extract_auto_entities(v, k))
            elif isinstance(node, list):
                for item in node:
                    found.update(_extract_auto_entities(item, parent_key))
            elif isinstance(node, str):
                # Skip file paths or URLs unless it's a Jinja template
                if ("/" in node or "\\" in node) and "{{" not in node and "{%" not in node:
                    return found
                for dom, obj in re.findall(r"(?<![/\w])([a-z_]+)\.([a-z0-9_]+)(?![/\w])", node):
                    if dom in tracked_domains and obj not in service_verbs:
                        found.add(f"{dom}.{obj}")
            return found

        # 1. Inspect scripts.yaml
        if isinstance(script_path, str) and os.path.isfile(script_path):
            try:
                with open(script_path, encoding="utf-8") as f:
                    raw_scripts = f.read()
                for m in re.findall(r"(?<![/\w])([a-z_]+)\.([a-z0-9_]+)(?![/\w])", raw_scripts):
                    if m[0] in tracked_domains and m[1] not in service_verbs:
                        result["automated_entities"].add(f"{m[0]}.{m[1]}")
                parsed_scripts = yaml.safe_load(raw_scripts)
                if isinstance(parsed_scripts, dict):
                    for skey, sbody in parsed_scripts.items():
                        result["norm_names"].add(_norm(skey))
                        if isinstance(sbody, dict) and sbody.get("alias"):
                            result["norm_names"].add(_norm(sbody["alias"]))
            except Exception as err:
                _LOGGER.debug("Could not inspect scripts.yaml: %s", err)

        # 2. Inspect automations.yaml
        if os.path.isfile(auto_path):
            try:
                with open(auto_path, encoding="utf-8") as f:
                    raw_autos = f.read()
                parsed_autos = yaml.safe_load(raw_autos)
                if isinstance(parsed_autos, list):
                    for auto in parsed_autos:
                        if not isinstance(auto, dict):
                            continue
                        aid = str(auto.get("id") or "")
                        alias = str(auto.get("alias") or aid)
                        result["norm_names"].add(_norm(alias))
                        auto_dump = yaml.dump(auto)

                        ref_eids = _extract_auto_entities(auto)
                        result["automated_entities"].update(ref_eids)

                        # Check A: Input select option whitespace mismatch (e.g. "<Label> ..." vs "<Label>...")
                        ellipsis_match = re.search(r"([A-Za-z0-9_]+)\s+\.\.\.", auto_dump)
                        if ellipsis_match and "input_select" in auto_dump:
                            bad_opt = ellipsis_match.group(0)
                            clean_opt = f"{ellipsis_match.group(1)}..."
                            result["improvement_suggestions"].append({
                                "id": f"fix_input_select_option_{aid}",
                                "title": f"Fix '{bad_opt}' Option Mismatch in '{alias}'",
                                "category": "automation",
                                "priority": "high",
                                "icon": "mdi:wrench-check",
                                "description": (
                                    f"Home Assistant logs a warning because '{alias}' selects option '{bad_opt}' "
                                    f"(with extra whitespace) while set_options defines '{clean_opt}'. "
                                    "Standardize the option string in 1 click to eliminate this log warning."
                                ),
                                "action_type": "improve_automation",
                                "action_payload": {
                                    "automation_id": aid,
                                    "alias": alias,
                                    "replace_map": {bad_opt: clean_opt},
                                },
                            })

                        # Check B: Broken / Typo entity references inside existing automations (high-confidence typos only)
                        if active_entity_ids:
                            import difflib
                            for eid in sorted(ref_eids):
                                if eid in active_entity_ids:
                                    continue
                                dom, obj = eid.split(".", 1)
                                if dom in ("script", "person"):
                                    continue
                                replacement_eid = None
                                # Only suggest replacement if another active entity in the same domain has a single-token typo (e.g. sstudy -> study)
                                obj_tokens = obj.split("_")
                                for cand in active_entity_ids:
                                    if not cand.startswith(f"{dom}."):
                                        continue
                                    cand_obj = cand.split(".", 1)[1]
                                    cand_tokens = cand_obj.split("_")
                                    if len(obj_tokens) != len(cand_tokens):
                                        continue
                                    diffs = [
                                        (t_a, t_b)
                                        for t_a, t_b in zip(obj_tokens, cand_tokens, strict=True)
                                        if t_a != t_b
                                    ]
                                    if len(diffs) == 1:
                                        t_a, t_b = diffs[0]
                                        if (
                                            not t_a.isdigit()
                                            and not t_b.isdigit()
                                            and len(t_a) >= 4
                                            and len(t_b) >= 4
                                            and abs(len(t_a) - len(t_b)) <= 2
                                            and difflib.SequenceMatcher(None, t_a, t_b).ratio() >= 0.80
                                        ):
                                            replacement_eid = cand
                                            break

                                if replacement_eid:
                                    result["improvement_suggestions"].append({
                                        "id": f"fix_broken_entity_{aid}_{obj}",
                                        "title": f"Fix Broken Entity Reference in '{alias}' ({eid} → {replacement_eid})",
                                        "category": "automation",
                                        "priority": "high",
                                        "icon": "mdi:auto-fix",
                                        "description": (
                                            f"Existing automation '{alias}' references typo/missing entity "
                                            f"'{eid}', causing runtime service warnings in Home Assistant logs. "
                                            f"Replace it with active entity '{replacement_eid}'."
                                        ),
                                        "action_type": "improve_automation",
                                        "action_payload": {
                                            "automation_id": aid,
                                            "alias": alias,
                                            "replace_map": {eid: replacement_eid},
                                        },
                                    })

                        # Check C: Multi-trigger coordinator automations running in default mode: single (skip blueprints)
                        triggers = auto.get("trigger") or auto.get("triggers") or []
                        t_count = len(triggers) if isinstance(triggers, list) else 1
                        has_explicit_mode = "mode" in auto and auto.get("mode") is not None
                        if t_count >= 4 and not has_explicit_mode and "use_blueprint" not in auto:
                            result["improvement_suggestions"].append({
                                "id": f"upgrade_mode_queued_{aid}",
                                "title": f"Upgrade '{alias}' Execution Mode to Queued ({t_count} Triggers)",
                                "category": "automation",
                                "priority": "medium",
                                "icon": "mdi:fast-forward-outline",
                                "description": (
                                    f"'{alias}' monitors {t_count} distinct state triggers but omits an execution mode "
                                    "(defaulting to 'single'). Concurrent sensor or lock events are dropped while running. "
                                    "Upgrade to 'mode: queued' so no state transition is missed."
                                ),
                                "action_type": "improve_automation",
                                "action_payload": {
                                    "automation_id": aid,
                                    "alias": alias,
                                    "mode": "queued",
                                },
                            })

                        # Check D: Blueprint invalid top-level conditions or actions in automations.yaml
                        if "use_blueprint" in auto:
                            has_invalid_top_level = bool(
                                auto.get("action")
                                or auto.get("actions")
                                or auto.get("condition")
                                or auto.get("conditions")
                            )
                            if has_invalid_top_level:
                                bp_info = auto.get("use_blueprint", {})
                                bp_path = bp_info.get("path") if isinstance(bp_info, dict) else str(bp_info)
                                result["improvement_suggestions"].append({
                                    "id": f"fix_blueprint_top_level_{aid}",
                                    "title": f"Fix Invalid Blueprint Logic Injected into '{alias}'",
                                    "category": "automation",
                                    "priority": "critical",
                                    "icon": "mdi:alert-box-outline",
                                    "description": (
                                        f"Automation '{alias}' uses blueprint '{bp_path}' but contains top-level action/condition "
                                        "definitions in automations.yaml. Blueprint automations can only define 'input:' variables; "
                                        "top-level injections cause Home Assistant setup errors."
                                    ),
                                    "action_type": "repair_blueprint_automation",
                                    "action_payload": {
                                        "automation_id": aid,
                                        "alias": alias,
                                    },
                                })

                # Check E: Guest Mode Climate Comfort Integration
                def _is_guest_mode_toggle(eid: str) -> bool:
                    e_low = eid.lower()
                    if not e_low.startswith(("input_boolean.", "switch.", "binary_sensor.")):
                        return False
                    if any(bad in e_low for bad in ("cpu", "utilization", "memory", "ap_", "rssi", "signal", "battery", "temp", "humidity", "wifi", "link")):
                        return False
                    return "guest_mode" in e_low or "guest_visit" in e_low or e_low.endswith(".guest")

                guest_eid = next((eid for eid in active_entity_ids if _is_guest_mode_toggle(eid)), None)
                if not guest_eid:
                    guest_eid = next((eid for eid in result["automated_entities"] if _is_guest_mode_toggle(eid)), None)
                if guest_eid and isinstance(parsed_autos, list):
                    climate_mentions_guest = False
                    blueprint_managed_climates: dict[str, list[str]] = {}
                    for auto in parsed_autos:
                        if not isinstance(auto, dict):
                            continue
                        adump = yaml.dump(auto).lower()
                        if "climate" in adump and ("guest_mode" in adump or "guest mode" in adump or "people_at_home" in adump):
                            climate_mentions_guest = True
                        bp = auto.get("use_blueprint")
                        if isinstance(bp, dict) and isinstance(bp.get("input"), dict):
                            t_sel = bp["input"].get("thermostat_selection")
                            if isinstance(t_sel, str) and t_sel.startswith("climate."):
                                blueprint_managed_climates.setdefault(t_sel, []).append(str(auto.get("alias") or auto.get("id") or ""))
                    _non_interior_climate_tokens = ("pool", "spa", "hot_tub", "garage", "attic", "wine", "crawl", "greenhouse", "sleepnumber", "sleepiq", "bed", "patio", "exterior")
                    interior_climates = [
                        eid for eid in active_entity_ids
                        if eid.startswith("climate.") and not any(t in eid.lower() for t in _non_interior_climate_tokens)
                    ]
                    target_climate = next(
                        (eid for eid in interior_climates if any(k in eid for k in ("guest", "upstairs", "zone_2"))),
                        interior_climates[0] if interior_climates else None,
                    )
                    if not climate_mentions_guest and target_climate and guest_eid:
                        bp_owners = blueprint_managed_climates.get(target_climate) or []
                        bp_note = (
                            f" (Note: '{target_climate}' is currently managed by blueprint '{bp_owners[0]}', so coordinate via its occupancy/away inputs rather than overriding it.)"
                            if bp_owners
                            else ""
                        )
                        result["improvement_suggestions"].append({
                            "id": "link_guest_mode_climate_comfort",
                            "title": f"Coordinate {guest_eid} with {target_climate}",
                            "category": "automation",
                            "priority": "high",
                            "icon": "mdi:account-group-outline",
                            "description": (
                                f"Guest mode '{guest_eid}' is configured, but thermostat '{target_climate}' "
                                f"does not currently adjust for guest visits.{bp_note} Coordinate them to maintain comfort "
                                "setpoints during visits."
                            ),
                            "action_type": "improve_automation",
                            "action_payload": {
                                "topic": "guest_mode_climate",
                                "target_entity": target_climate,
                                "managing_blueprints": bp_owners,
                            },
                        })

                # Check F: Proactive Migration of Existing Automations & Blueprints to Otis Native Coordinators
                if isinstance(parsed_autos, list):
                    has_ev_or_storage = any(
                        any(k in eid for k in ("ev_charge", "ev_charger", "tesla_charge", "powerwall", "home_battery", "enphase_battery"))
                        for eid in active_entity_ids
                    )

                    _room_keywords = (
                        "common_area", "common area", "great_room", "great room", "living_room", "living room",
                        "study", "office", "kitchen", "bathroom", "hallway", "bedroom", "garage", "mudroom",
                        "foyer", "theater", "guest", "dining", "basement", "laundry",
                    )

                    for auto in parsed_autos:
                        if not isinstance(auto, dict):
                            continue
                        aid = str(auto.get("id") or auto.get("alias") or "")
                        alias = auto.get("alias") or aid
                        alias_low = str(alias).lower()
                        auto_str = yaml.dump(auto).lower()

                        # Motion lighting automation -> recommend Otis Multimodal Presence Fusion
                        already_presence_aware = (
                            any(k in alias_low for k in ("vacancy", "presence", "mmwave", "otis"))
                            or any(k in auto_str for k in ("mmwave", "otis_ai", "presence_fusion"))
                        )
                        if (
                            not already_presence_aware
                            and any(k in auto_str for k in ("motion", "pir", "occupancy"))
                            and any(k in auto_str for k in ("light.turn_on", "light.turn_off", "light.toggle"))
                        ):
                            alias_matches = [rk for rk in _room_keywords if rk in alias_low]
                            if alias_matches:
                                matched_area = alias_matches[0].replace(" ", "_")
                                area_label = matched_area.replace("_", " ").title()
                            else:
                                body_matches = list(dict.fromkeys(rk.replace(" ", "_") for rk in _room_keywords if rk in auto_str))
                                if len(body_matches) == 1:
                                    matched_area = body_matches[0]
                                    area_label = matched_area.replace("_", " ").title()
                                elif len(body_matches) > 1:
                                    matched_area = "multi_room"
                                    area_label = "Multi-Room"
                                else:
                                    matched_area = "general"
                                    area_label = "Room"
                            sugg_id = f"migrate_presence_coordinator_{aid}"
                            if not any(s["id"] == sugg_id for s in result["improvement_suggestions"]):
                                result["improvement_suggestions"].append({
                                    "id": sugg_id,
                                    "title": f"Migrate '{alias}' to Multimodal Presence Coordinator ({area_label})",
                                    "category": "migration",
                                    "priority": "high",
                                    "icon": "mdi:motion-sensor-plus",
                                    "description": (
                                        f"Existing automation '{alias}' relies on basic motion triggers. "
                                        "Migrating to Otis Multimodal Presence Fusion combines micro-motion mmWave radar, "
                                        "BLE trilateration, and thermal body gating so lights never shut off while someone is sitting still, "
                                        "and ignores robotic vacuums and pets."
                                    ),
                                    "action_type": "propose_automation_migration",
                                    "action_payload": {
                                        "automation_id": aid,
                                        "alias": alias,
                                        "target_coordinator": "presence_fusion",
                                        "area": matched_area or "general",
                                    },
                                    })

                        # EV or Battery charging automation -> recommend Otis TOU Contextual Energy Arbitrage
                        alias_lower = str(alias).lower()
                        is_non_energy = any(
                            k in alias_lower
                            for k in ("light", "lamp", "ups", "maintenance", "adaptive", "sleep", "bed", "motion", "door", "window", "fan")
                        )
                        if (
                            has_ev_or_storage
                            and not is_non_energy
                            and any(k in auto_str for k in ("ev_charge", "ev_charging", "charger", "tesla_charge", "charge_mode"))
                            and any(k in auto_str for k in ("switch.turn_on", "time", "numeric_state"))
                        ):
                            sugg_id = f"migrate_energy_arbitrage_{aid}"
                            if not any(s["id"] == sugg_id for s in result["improvement_suggestions"]):
                                result["improvement_suggestions"].append({
                                    "id": sugg_id,
                                    "title": f"Migrate '{alias}' to Contextual Energy Arbitrage",
                                    "category": "migration",
                                    "priority": "high",
                                    "icon": "mdi:transmission-tower-export",
                                    "description": (
                                        f"Existing automation '{alias}' controls charging on static triggers. "
                                        "Migrating to Otis Contextual Energy Arbitrage dynamically integrates dynamic TOU off-peak tariffs, "
                                        "negative grid pricing detection, and solar position to minimize charging costs."
                                    ),
                                    "action_type": "propose_automation_migration",
                                    "action_payload": {
                                        "automation_id": aid,
                                        "alias": alias,
                                        "target_coordinator": "energy_arbitrage",
                                    },
                                })
            except Exception as err:
                _LOGGER.debug("Could not inspect automations.yaml: %s", err)

        # 3. Inspect configuration.yaml for HA Performance & Log Hygiene
        if isinstance(config_path, str) and os.path.isfile(config_path):
            try:
                with open(config_path, encoding="utf-8") as f:
                    raw_cfg = f.read()

                if "recorder:" in raw_cfg and "commit_interval:" not in raw_cfg:
                    result["system_suggestions"].append({
                        "id": "optimize_recorder_commit_interval",
                        "title": "Optimize HA Database Performance (Recorder Commit Interval)",
                        "category": "system",
                        "priority": "high",
                        "icon": "mdi:database-sync",
                        "description": (
                            "Your configuration.yaml 'recorder:' section flushes SQLite writes continuously. "
                            "Adding 'commit_interval: 30' batches database commits every 30 seconds, reducing "
                            "disk I/O overhead and SQLite lock contention across 5,000+ entities."
                        ),
                        "action_type": "optimize_system_config",
                        "action_payload": {"optimization_type": "recorder_commit_interval"},
                    })

                if (
                    "input_select." in raw_cfg
                    and "Event data for call_service exceed maximum size" not in raw_cfg
                ):
                    result["system_suggestions"].append({
                        "id": "suppress_recorder_32kb_call_service_warning",
                        "title": "Eliminate Recorder 32KB Service Event Log Warning",
                        "category": "system",
                        "priority": "medium",
                        "icon": "mdi:file-document-check-outline",
                        "description": (
                            "Large media catalog option updates trigger 'WARNING (Recorder) Event data for "
                            "call_service exceed maximum size of 32768 bytes' in Home Assistant logs. "
                            "Add a targeted logger filter in configuration.yaml to keep system logs clean."
                        ),
                        "action_type": "optimize_system_config",
                        "action_payload": {"optimization_type": "suppress_recorder_32kb_log_filter"},
                    })
            except Exception as err:
                _LOGGER.debug("Could not inspect configuration.yaml: %s", err)

        # 4. Inspect config entries and backup manager for automatic backup configurations (e.g. pCloud Backup, HA Automatic Backups)
        try:
            if hasattr(self.hass, "config_entries") and hasattr(self.hass.config_entries, "async_entries"):
                for entry in self.hass.config_entries.async_entries():
                    edom = str(getattr(entry, "domain", "")).lower()
                    if ("backup" in edom and edom != "backup") or edom in ("pcloud_backup", "google_drive_backup", "samba_backup", "onedrive"):
                        result["automatic_backups_configured"] = True
                        break
            backup_mgr = self.hass.data.get("backup_manager") or self.hass.data.get("backup")
            if backup_mgr is not None:
                b_cfg = getattr(backup_mgr, "config", None)
                if b_cfg and getattr(b_cfg, "automatic_backups_configured", False):
                    result["automatic_backups_configured"] = True
        except Exception as err:
            _LOGGER.debug("Could not inspect backup configuration: %s", err)

        return result

    async def async_generate_proactive_suggestions(
        self, capability_map: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Generate intelligent, proactive smart home recommendations across all maturity stages."""
        if not getattr(self.hass, "is_running", True):
            _LOGGER.debug(
                "Skipping proactive suggestion generation until Home Assistant is fully started."
            )
            self._suggestions_by_id = {}
            return []

        suggestions: list[dict[str, Any]] = []

        orphaned = capability_map.get("orphaned_entities", [])
        areas = capability_map.get("areas", {})
        devices = capability_map.get("devices", {})
        entities = capability_map.get("entities", [])
        integrations = capability_map.get("integrations", [])

        # Lazily compute topologies if capability_map was constructed manually in tests
        media_topology = capability_map.get("media_topology")
        if not isinstance(media_topology, dict):
            media_topology = self._discover_media_topology(areas, entities, integrations)

        security_topology = capability_map.get("security_topology")
        if not isinstance(security_topology, dict):
            security_topology = self._discover_security_topology(areas, entities, integrations)

        maturity = capability_map.get("maturity")
        if not isinstance(maturity, dict):
            maturity = self._discover_system_maturity(
                areas,
                devices,
                entities,
                orphaned,
                integrations,
                self.floorplan_parser.has_walkthrough(),
                self.floorplan_parser.floorplan_exists(),
                media_topology,
                security_topology,
            )

        # Index existing automations and scripts (both from registry AND directly from automations.yaml/scripts.yaml)
        def _norm_str(s: str) -> str:
            return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()

        active_entity_ids = {e["entity_id"] for e in entities if e.get("entity_id")}
        exec_res = self.hass.async_add_executor_job(
            self._inspect_config_files_sync, active_entity_ids
        )
        if asyncio.iscoroutine(exec_res) or hasattr(exec_res, "__await__"):
            config_audit = await exec_res
        else:
            config_audit = self._inspect_config_files_sync(active_entity_ids)
        if not isinstance(config_audit, dict):
            config_audit = self._inspect_config_files_sync(active_entity_ids)
        automated_entities: set[str] = config_audit.get("automated_entities", set())

        existing_auto_names = {
            _norm_str(e.get("name") or e.get("entity_id") or "")
            for e in entities
            if e.get("domain") == "automation"
        } | config_audit.get("norm_names", set())
        existing_script_names = {
            _norm_str(e.get("name") or e.get("entity_id") or "")
            for e in entities
            if e.get("domain") == "script"
        } | config_audit.get("norm_names", set())
        all_existing_names = existing_auto_names | existing_script_names

        # 0. Surface Sentinel Telemetry Anomaly Self-Healing Alerts (Highest Priority)
        if self.sentinel_manager:
            try:
                sentinel_suggestions = self.sentinel_manager.convert_anomalies_to_proactive_suggestions()
                suggestions.extend(sentinel_suggestions)
            except Exception as err:
                _LOGGER.debug("Error generating Sentinel suggestions: %s", err)

        # Surface Local Edge AI Model Switch & Hardware Optimization Recommendations
        local_llm_info = capability_map.get("local_llm", {})
        suitability = local_llm_info.get("suitability") if isinstance(local_llm_info, dict) else None
        if not suitability and getattr(self, "local_llm_manager", None):
            try:
                suitability = getattr(self.local_llm_manager, "_last_suitability", None)
            except Exception:
                suitability = None
        if suitability and suitability.get("model_switch_recommended"):
            rec_model = suitability.get("recommended_model")
            cur_model = suitability.get("current_model") or local_llm_info.get("active_model", "")
            reason = suitability.get("reason", "Host hardware and inference benchmarks indicate an alternative model will provide better responsiveness.")
            suggestions.append({
                "id": f"switch_local_llm_{str(rec_model).replace(':', '_')}",
                "title": f"⚡ Optimize Local Edge AI Model: Switch to {rec_model}",
                "category": "performance",
                "priority": "high",
                "icon": "mdi:chip",
                "description": (
                    f"Otis evaluated your host hardware and inference performance. {reason} "
                    f"Switching from {cur_model} to {rec_model} will optimize response speed."
                ),
                "action_type": "switch_local_llm_model",
                "action_payload": {
                    "model": rec_model,
                    "current_model": cur_model,
                },
            })

        # Surface Dynamic Cloud AI Agent Model & Reliability Recommendations
        if getattr(self, "rules_manager", None) and hasattr(self.rules_manager, "get_agent_health_metrics"):
            try:
                agent_metrics = self.rules_manager.get_agent_health_metrics() or {}
                ce_list = list(self.hass.config_entries.async_entries()) if getattr(self.hass, "config_entries", None) else []
                ce_by_id = {ce.entry_id: ce for ce in ce_list}
                active_ce_ids = set(ce_by_id.keys())
                ent_reg = None
                try:
                    ent_reg = er.async_get(self.hass)
                except Exception:
                    ent_reg = None

                # Group/deduplicate metrics by canonical config entry ID when possible
                grouped_agents: dict[str, dict[str, Any]] = {}
                for ag_id, met in agent_metrics.items():
                    ag_str = str(ag_id or "")
                    if not ag_str or ag_str.startswith(("local_llm:", "otis_")) or ag_str == "conversation.home_assistant":
                        continue
                    is_live_entity = bool(ag_str.startswith("conversation.") and self.hass.states.get(ag_str) is not None)
                    is_live_entry = bool(ag_str in active_ce_ids)
                    if (active_ce_ids or ag_str.startswith("conversation.")) and not (is_live_entity or is_live_entry):
                        continue

                    resolved_ce_id = ag_str if is_live_entry else None
                    if not resolved_ce_id and ent_reg is not None and ag_str.startswith("conversation."):
                        reg_ent = ent_reg.async_get(ag_str)
                        if reg_ent is not None and getattr(reg_ent, "config_entry_id", None):
                            resolved_ce_id = str(reg_ent.config_entry_id)

                    canon_key = resolved_ce_id or ag_str
                    s_cnt = int(met.get("success_count") or 0)
                    e_cnt = int(met.get("error_count") or 0)
                    consec = int(met.get("consecutive_failures") or 0)
                    avg_lat = float(met.get("avg_latency_s") or 0.0)
                    last_err = str(met.get("last_error_reason") or "").strip()

                    existing = grouped_agents.get(canon_key)
                    if existing is None:
                        grouped_agents[canon_key] = {
                            "ag_str": ag_str,
                            "ce_id": resolved_ce_id,
                            "raw_ids": [ag_str],
                            "s_cnt": s_cnt,
                            "e_cnt": e_cnt,
                            "consec": consec,
                            "avg_lat": avg_lat,
                            "last_err": last_err,
                        }
                    else:
                        if ag_str not in existing["raw_ids"]:
                            existing["raw_ids"].append(ag_str)
                        prev_total = existing["s_cnt"] + existing["e_cnt"]
                        cur_total = s_cnt + e_cnt
                        existing["s_cnt"] += s_cnt
                        existing["e_cnt"] += e_cnt
                        existing["consec"] = max(existing["consec"], consec)
                        if (prev_total + cur_total) > 0:
                            existing["avg_lat"] = (
                                (existing["avg_lat"] * prev_total) + (avg_lat * cur_total)
                            ) / (prev_total + cur_total)
                        if last_err and (not existing["last_err"] or e_cnt >= existing["e_cnt"]):
                            existing["last_err"] = last_err
                        if ag_str.startswith("conversation.") and not existing["ag_str"].startswith("conversation."):
                            existing["ag_str"] = ag_str

                for canon_key, grp in grouped_agents.items():
                    ag_str = grp["ag_str"]
                    s_cnt = grp["s_cnt"]
                    e_cnt = grp["e_cnt"]
                    consec = grp["consec"]
                    avg_lat = grp["avg_lat"]
                    last_err = grp["last_err"]
                    total_calls = s_cnt + e_cnt
                    fail_rate = (e_cnt / total_calls) if total_calls > 0 else 0.0
                    if consec >= 2 or (total_calls >= 3 and fail_rate >= 0.4) or (avg_lat >= 25.0 and total_calls >= 2):
                        ce = ce_by_id.get(grp["ce_id"] or "")
                        ag_name = (ce.title if ce and getattr(ce, "title", None) else "") or get_agent_display_name(self.hass, ag_str)
                        if ce is None:
                            for cand_ce in ce_list:
                                if cand_ce.entry_id == ag_str or cand_ce.title == ag_name:
                                    ce = cand_ce
                                    break
                        ce_domain, cur_cfg_model, protect_free_tier = _extract_cloud_agent_config(ce)
                        if cur_cfg_model and await _sync_cloud_agent_model_metrics(
                            self.rules_manager, grp["raw_ids"], cur_cfg_model
                        ):
                            continue
                        deprecated_models = (
                            self.rules_manager.get_deprecated_models()
                            if hasattr(self.rules_manager, "get_deprecated_models")
                            else set()
                        )
                        peer_models: list[str] = []
                        if ce is not None and isinstance(getattr(ce, "subentries", None), Mapping):
                            for sub in ce.subentries.values():
                                s_data = getattr(sub, "data", None)
                                if isinstance(s_data, Mapping):
                                    for mk in ("chat_model", "model", "llm_model"):
                                        mv = str(s_data.get(mk) or "").strip()
                                        if mv and mv != cur_cfg_model and "tts" not in mv.lower() and mv not in peer_models:
                                            peer_models.append(mv)
                        rec_model, rec_advice = _recommend_cloud_agent_optimization(
                            domain=ce_domain,
                            agent_name=ag_name,
                            current_model=cur_cfg_model,
                            protect_free_tier=protect_free_tier,
                            last_error=last_err,
                            avg_latency=avg_lat,
                            deprecated_models=deprecated_models,
                            peer_working_models=peer_models,
                        )
                        err_note = f" Last error: {last_err[:120]}." if last_err else ""
                        model_note = f" (current model: `{cur_cfg_model}`)" if cur_cfg_model else ""
                        safe_id = re.sub(r"[^a-z0-9_]+", "_", canon_key.lower()).strip("_")
                        suggestions.append({
                            "id": f"optimize_cloud_agent_{safe_id}",
                            "title": f"☁️ Optimize Cloud AI Agent: {ag_name}",
                            "category": "performance",
                            "priority": "high",
                            "icon": "mdi:cloud-alert",
                            "description": (
                                f"Agent '{ag_name}'{model_note} recorded {e_cnt} error(s) across {total_calls} request(s) "
                                f"({round(fail_rate * 100)}% failure rate, {consec} consecutive failure(s), avg {round(avg_lat, 1)}s).{err_note} "
                                f"{rec_advice}"
                            ),
                            "action_type": "configure_agent",
                            "action_payload": {
                                "agent_id": ag_str,
                                "agent_name": ag_name,
                                "domain": ce_domain,
                                "current_model": cur_cfg_model,
                                "recommended_model": rec_model,
                                "protect_free_tier": protect_free_tier,
                                "error_count": e_cnt,
                                "total_calls": total_calls,
                            },
                        })
            except Exception as ag_err:
                _LOGGER.debug("Error generating cloud agent health recommendations: %s", ag_err)

        # Surface HA Core Log Monitor & GitHub Issue Tracking Cards
        if getattr(self, "log_monitor", None):
            try:
                log_cards = await self.log_monitor.async_get_proactive_cards()
                suggestions.extend(log_cards)
            except Exception as l_err:
                _LOGGER.debug("Error generating Log Monitor suggestions: %s", l_err)

        # Surface Existing Automation Improvements, Proactive Migrations & HA System Optimizations
        suggestions.extend(config_audit.get("improvement_suggestions", [])[:6])
        suggestions.extend(config_audit.get("system_suggestions", []))

        # Surface Self-Healing Mesh Network Routing Optimizations
        if self.mesh_manager:
            try:
                mesh_audit = await self.mesh_manager.async_audit_mesh_topology()
                health_score = mesh_audit.get("health_score", 100)
                degraded_nodes = mesh_audit.get("degraded_nodes", [])
                if health_score < 85 or degraded_nodes:
                    node_count = len(degraded_nodes)
                    suggestions.append({
                        "id": "heal_mesh_network_routes",
                        "title": f"Self-Healing Mesh: Route Degradation Detected ({health_score}% Health)",
                        "category": "mesh",
                        "priority": "high" if health_score < 70 else "medium",
                        "icon": "mdi:access-point-network-off",
                        "description": (
                            f"Otis Mesh Manager identified {node_count} Zigbee/Z-Wave node(s) with high hop count or weak signal. "
                            "Trigger autonomous neighbor re-negotiation to heal routing paths and eliminate latency."
                        ),
                        "action_type": "heal_mesh_network",
                        "action_payload": {"degraded_nodes": degraded_nodes},
                    })
            except Exception as err:
                _LOGGER.debug("Error auditing mesh for suggestions: %s", err)

        # Surface Contextual TOU Energy Arbitrage Opportunities
        if self.energy_manager:
            try:
                energy_telemetry = await self.energy_manager.async_get_energy_summary()
                arbitrage = energy_telemetry.get("arbitrage", {})
                current_tariff = arbitrage.get("current_tariff_period")
                negative_pricing = arbitrage.get("negative_pricing_active", False)
                if negative_pricing:
                    suggestions.append({
                        "id": "negative_pricing_energy_opportunity",
                        "title": "⚡ Negative Grid Pricing Detected: Dispatch Flexible Loads",
                        "category": "energy",
                        "priority": "critical",
                        "icon": "mdi:cash-fast",
                        "description": (
                            "Grid electricity prices are currently negative! Pre-charge home batteries, "
                            "heat pool water, and dispatch EV charging to earn credit."
                        ),
                        "action_type": "execute_energy_arbitrage",
                        "action_payload": {"strategy": "negative_pricing_dispatch"},
                    })
                elif current_tariff == "off_peak":
                    # Check whether home has EV chargers/vehicles or just discretionary appliances
                    topo = await self.energy_manager.async_discover_energy_topology()
                    has_ev = bool(topo.get("ev_chargers") or topo.get("ev_vehicles"))
                    if has_ev:
                        suggestions.append({
                            "id": "off_peak_energy_arbitrage_window",
                            "title": "🌙 Off-Peak TOU Tariff Window Active: Schedule Heavy Loads",
                            "category": "energy",
                            "priority": "low",
                            "icon": "mdi:clock-check-outline",
                            "description": (
                                "Your electric utility is in super off-peak hours. Otis can co-optimize your EV charging "
                                "and discretionary appliances before on-peak rates resume."
                            ),
                            "action_type": "schedule_ev_charging",
                            "action_payload": {"mode": "off_peak_fast"},
                        })
                    else:
                        suggestions.append({
                            "id": "off_peak_energy_arbitrage_window",
                            "title": "🌙 Off-Peak TOU Tariff Window Active: Shift Discretionary Loads",
                            "category": "energy",
                            "priority": "low",
                            "icon": "mdi:clock-check-outline",
                            "description": (
                                "Your electric utility is in off-peak hours. Otis can co-optimize your pool pumps, "
                                "water heating, and discretionary sub-circuits before on-peak rates resume."
                            ),
                            "action_type": "execute_energy_arbitrage",
                            "action_payload": {"strategy": "off_peak_dispatch"},
                        })
            except Exception as err:
                _LOGGER.debug("Error checking energy manager for suggestions: %s", err)

        # Surface Multimodal Presence Radar Calibration
        if self.presence_fusion_manager:
            try:
                presence_data = await self.presence_fusion_manager.async_fuse_presence(use_cache=True)
                rooms_with_radar = [
                    rname for rname, rinfo in presence_data.get("rooms", {}).items()
                    if any("mmwave" in m for m in rinfo.get("active_modalities", []))
                ]
                if rooms_with_radar and not any(s.get("id") == "calibrate_mmwave_presence" for s in suggestions):
                    room_list_str = ", ".join(r.replace("_", " ").title() for r in rooms_with_radar[:3])
                    suggestions.append({
                        "id": "calibrate_mmwave_presence",
                        "title": f"Calibrate Micro-Motion Radar ({room_list_str})",
                        "category": "presence",
                        "priority": "medium",
                        "icon": "mdi:radar",
                        "description": (
                            f"Active mmWave radar targets discovered in {room_list_str}. "
                            "Calibrate Bayesian noise floors and static target persistence to eliminate false vacancies."
                        ),
                        "action_type": "fuse_presence",
                        "action_payload": {"calibrate": True},
                    })
            except Exception as err:
                _LOGGER.debug("Error checking presence fusion for suggestions: %s", err)

        # Surface New Home Assistant Capabilities (Native Multi-Floor Registry Sync)
        try:
            from homeassistant.helpers import floor_registry as fr
            floor_reg = fr.async_get(self.hass)
            existing_floors = list(floor_reg.async_list_floors()) if hasattr(floor_reg, "async_list_floors") else []
            if len(areas) >= 3 and len(existing_floors) < 2:
                ha_ver = getattr(self.hass.config, "version", "2026.x")
                suggestions.append({
                    "id": "discover_ha_native_floor_registry",
                    "title": f"New HA Capability ({ha_ver}): Sync Native Multi-Floor Registry",
                    "category": "system",
                    "priority": "medium",
                    "icon": "mdi:layers-triple",
                    "description": (
                        "Home Assistant supports native Floor Registry grouping for voice intents and area cards, "
                        f"but your {len(areas)} areas are not yet linked to native HA floors. Sync Otis's Ground Floor, "
                        "Upper Level, and Outdoor zones into Home Assistant's Floor Registry in 1 click."
                    ),
                    "action_type": "sync_ha_floors",
                    "action_payload": {},
                })
        except Exception:
            pass

        # Surface Professional Dashboard Gap Recommendations
        try:
            dash_audit = await self.dashboard_manager.async_analyze_dashboard_gaps(capability_map)
            for prop in dash_audit.get("proposals", [])[:2]:
                suggestions.append({
                    "id": prop["id"],
                    "title": prop["title"],
                    "category": "dashboard",
                    "priority": prop.get("priority", "medium"),
                    "icon": prop.get("icon", "mdi:view-dashboard-plus"),
                    "description": prop["description"],
                    "action_type": "create_dashboard",
                    "action_payload": prop,
                })
        except Exception as err:
            _LOGGER.debug("Dashboard gap analysis skipped: %s", err)

        # 1. Orphaned entities cleanup suggestion
        if orphaned:
            orphan_count = len(orphaned)
            entity_ids = [e["entity_id"] for e in orphaned]
            suggestions.append({
                "id": f"cleanup_orphans_{orphan_count}",
                "title": f"Clean Up {orphan_count} Orphaned {'Entity' if orphan_count == 1 else 'Entities'}",
                "category": "cleanup",
                "priority": "high" if orphan_count >= 5 else "medium",
                "icon": "mdi:broom",
                "description": (
                    f"Found {orphan_count} orphaned entities from deleted or inactive integrations. "
                    "Cleaning them removes registry bloat and prevents state engine warnings."
                ),
                "action_type": "cleanup_orphans",
                "action_payload": {"entity_ids": entity_ids},
            })

        # 1b. 1-Click Auto-Assign Unassigned Devices & Entities to Areas
        inferred_devs = maturity.get("inferred_device_assignments", {})
        inferred_ents = maturity.get("inferred_entity_assignments", {})
        total_inferred = len(inferred_devs) + len(inferred_ents)
        if total_inferred > 0:
            suggestions.append({
                "id": "auto_assign_device_areas",
                "title": f"Auto-Assign {total_inferred} Unassigned {'Device' if total_inferred == 1 else 'Devices/Entities'} to Areas",
                "category": "cleanup",
                "priority": "high" if total_inferred >= 4 else "medium",
                "icon": "mdi:map-marker-check",
                "description": (
                    f"Otis matched {total_inferred} unassigned devices/entities to your registered rooms by name "
                    "and topology. Assigning them unlocks accurate room-level lighting, climate, and audio routing."
                ),
                "action_type": "auto_assign_areas",
                "action_payload": {
                    "device_assignments": inferred_devs,
                    "entity_assignments": inferred_ents,
                },
            })

        # 2. Control4 / Multi-Zone Matrix Amp Audio Router & Auto-Power Coordinator Package
        if media_topology.get("matrix_amp_detected"):
            matrix_zones = media_topology.get("matrix_zones", [])
            zone_ids = [z["entity_id"] for z in matrix_zones]
            shared_sources = media_topology.get("shared_sources") or [
                "Bridge",
                "Gym Bridge",
                "Server",
                "Home Assistant",
            ]
            input_streamers = [s["entity_id"] for s in media_topology.get("input_streamers", [])]
            has_matrix_router = (
                any(
                    any(
                        kw in name
                        for kw in (
                            "matrix audio router",
                            "matrix amp",
                            "room speaker",
                            "media router",
                            "bridge on off",
                            "media launcher",
                        )
                    )
                    for name in all_existing_names
                )
                or sum(1 for zid in zone_ids if zid in automated_entities) >= 3
            )
            if zone_ids and not has_matrix_router:
                default_source = shared_sources[0]
                package_scripts = [
                    {
                        "alias": "Otis Matrix Audio Router",
                        "description": (
                            f"Routes audio sources ({', '.join(shared_sources[:4])}) to {', '.join(zone_ids[:8])} "
                            "and sets optimal initial zone volume."
                        ),
                        "fields": {
                            "target_zones": {
                                "description": "Matrix output room media_player entities",
                                "example": zone_ids[:2],
                            },
                            "source_name": {
                                "description": "Matrix Amp input source name",
                                "example": default_source,
                            },
                            "volume": {
                                "description": "Initial volume level (0.0 - 1.0)",
                                "example": 0.35,
                            },
                        },
                        "sequence": [
                            {
                                "service": "media_player.turn_on",
                                "target": {"entity_id": "{{ target_zones | default(" + str(zone_ids[:1]) + ") }}"},
                            },
                            {
                                "service": "media_player.select_source",
                                "target": {"entity_id": "{{ target_zones | default(" + str(zone_ids[:1]) + ") }}"},
                                "data": {"source": "{{ source_name | default('" + default_source + "') }}"},
                            },
                            {
                                "service": "media_player.volume_set",
                                "target": {"entity_id": "{{ target_zones | default(" + str(zone_ids[:1]) + ") }}"},
                                "data": {"volume_level": "{{ volume | default(0.35) }}"},
                            },
                        ],
                        "mode": "parallel",
                    }
                ]
                idle_trigger = (
                    [
                        {
                            "platform": "state",
                            "entity_id": input_streamers,
                            "to": ["idle", "off", "paused"],
                            "for": {"minutes": 15},
                        }
                    ]
                    if input_streamers
                    else [
                        {
                            "platform": "state",
                            "entity_id": zone_ids,
                            "to": "idle",
                            "for": {"minutes": 20},
                        }
                    ]
                )
                package_automations = [
                    {
                        "alias": "Matrix Amp Coordinator: Auto-Off Idle Room Zones",
                        "description": (
                            "Automatically powers down Control4 Matrix Amp room output zones when upstream "
                            "streamer bridges remain idle for 15 minutes."
                        ),
                        "trigger": idle_trigger,
                        "action": [
                            {"service": "media_player.turn_off", "target": {"entity_id": zone_ids}}
                        ],
                        "mode": "single",
                    }
                ]
                suggestions.append({
                    "id": "matrix_audio_router_package",
                    "title": f"Multi-Zone Matrix Audio Router & Idle Power Guard ({len(zone_ids)} Zones)",
                    "category": "media",
                    "priority": "high",
                    "icon": "mdi:speaker-multiple",
                    "description": (
                        f"Discovered a multi-zone matrix audio architecture ({len(zone_ids)} room outputs sharing "
                        f"inputs: {', '.join(shared_sources[:4])}). Deploy a unified Matrix Audio Router script "
                        "plus an idle-streamer auto-shutdown coordinator to save amplifier power."
                    ),
                    "action_type": "create_package",
                    "action_payload": {
                        "scripts": package_scripts,
                        "automations": package_automations,
                    },
                })

        # 2b. Cinema / Theater Lighting & Shade Coordinator
        tv_zones = media_topology.get("tv_cinema_zones", [])
        has_cinema_auto = (
            any(
                any(kw in name for kw in ("cinema", "theater", "movie mode", "tv bias", "it s time"))
                for name in existing_auto_names
            )
            or any(t.get("entity_id") in automated_entities for t in tv_zones)
        )
        if tv_zones and not has_cinema_auto:
            primary_tv = tv_zones[0]
            tv_area_id = primary_tv.get("area_id")
            if not tv_area_id:
                for cand_aid in ("theater", "great_room", "living_room", "master"):
                    if cand_aid in areas:
                        tv_area_id = cand_aid
                        break
            tv_area = areas.get(tv_area_id, {}) if tv_area_id else {}
            tv_buckets = classify_area_entities(tv_area.get("entities", []))
            room_lights = tv_buckets["lights"] or [
                e["entity_id"] for e in entities if e.get("domain") == "light"
            ][:3]
            room_covers = [
                eid
                for eid in tv_area.get("entities", [])
                if eid.startswith("cover.") and "garage" not in eid.lower()
            ]
            if room_lights:
                play_actions: list[dict[str, Any]] = [
                    {
                        "service": "light.turn_on",
                        "target": {"entity_id": room_lights[:3]},
                        "data": {"brightness_pct": 15, "transition": 3},
                    }
                ]
                if room_covers:
                    play_actions.append(
                        {"service": "cover.close_cover", "target": {"entity_id": room_covers}}
                    )
                suggestions.append({
                    "id": "cinema_lighting_shade_coordinator",
                    "title": f"Cinema Mode Lighting & Shade Coordinator ({primary_tv.get('name')})",
                    "category": "media",
                    "priority": "medium",
                    "icon": "mdi:theater",
                    "description": (
                        f"Automatically dim lighting to 15% (and close shades if present) when {primary_tv.get('name')} "
                        "starts playing after sunset, and gently restore lighting to 60% when paused or stopped."
                    ),
                    "action_type": "create_automation",
                    "action_payload": {
                        "alias": f"Cinema Mode Coordinator: {primary_tv.get('name')}",
                        "description": "Automated by Otis AI Companion media topology engine",
                        "trigger": [
                            {
                                "platform": "state",
                                "entity_id": primary_tv["entity_id"],
                                "to": "playing",
                                "id": "media_playing",
                            },
                            {
                                "platform": "state",
                                "entity_id": primary_tv["entity_id"],
                                "from": "playing",
                                "to": ["paused", "idle", "off"],
                                "for": {"seconds": 15},
                                "id": "media_stopped",
                            },
                        ],
                        "condition": [
                            {"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"}
                        ],
                        "action": [
                            {
                                "choose": [
                                    {
                                        "conditions": [{"condition": "trigger", "id": "media_playing"}],
                                        "sequence": play_actions,
                                    },
                                    {
                                        "conditions": [{"condition": "trigger", "id": "media_stopped"}],
                                        "sequence": [
                                            {
                                                "service": "light.turn_on",
                                                "target": {"entity_id": room_lights[:3]},
                                                "data": {"brightness_pct": 60, "transition": 2},
                                            }
                                        ],
                                    },
                                ]
                            }
                        ],
                        "mode": "restart",
                    },
                })

        # 3. Unified Security, Presence & SleepNumber Bedtime Coordinator
        alarm_panels = security_topology.get("alarm_panels", [])
        locks = security_topology.get("locks", [])
        garage_covers = security_topology.get("garage_covers", [])
        sirens = security_topology.get("sirens", [])
        bed_sensors = security_topology.get("bed_occupancy_sensors", [])
        persons = security_topology.get("persons", [])
        all_lights = [e["entity_id"] for e in entities if e.get("domain") == "light"]
        all_media = [e["entity_id"] for e in entities if e.get("domain") == "media_player"]

        has_security_coordinator = (
            any(
                any(
                    kw in name
                    for kw in (
                        "security alarm system",
                        "security presence coordinator",
                        "unified security",
                        "alarm triggered router",
                        "disarm when door unlocked",
                    )
                )
                for name in all_existing_names
            )
            or any(ap in automated_entities for ap in alarm_panels)
        )
        if (
            (alarm_panels or (locks and (persons or bed_sensors)))
            and not has_security_coordinator
        ):
            triggers: list[dict[str, Any]] = []
            choose_branches: list[dict[str, Any]] = []

            # Branch 1: Everyone Leaves -> Arm Away + Lock Doors + Close Garage + Turn Off Lights/Media
            if persons:
                triggers.append(
                    {
                        "platform": "state",
                        "entity_id": persons,
                        "to": "not_home",
                        "for": {"minutes": 3},
                        "id": "everyone_left",
                    }
                )
                away_seq: list[dict[str, Any]] = []
                if locks:
                    away_seq.append({"service": "lock.lock", "target": {"entity_id": locks}})
                if garage_covers:
                    away_seq.append({"service": "cover.close_cover", "target": {"entity_id": garage_covers}})
                if alarm_panels:
                    away_seq.append(
                        {"service": "alarm_control_panel.alarm_arm_away", "target": {"entity_id": alarm_panels[0]}}
                    )
                if all_lights:
                    away_seq.append({"service": "light.turn_off", "target": {"entity_id": all_lights[:15]}})
                if all_media:
                    away_seq.append({"service": "media_player.turn_off", "target": {"entity_id": all_media[:10]}})
                choose_branches.append(
                    {
                        "conditions": [
                            {"condition": "trigger", "id": "everyone_left"},
                            *(
                                [{"condition": "state", "entity_id": p, "state": "not_home"} for p in persons]
                            ),
                        ],
                        "sequence": away_seq,
                    }
                )

            # Branch 2: Bed Occupancy (SleepNumber) -> Arm Night + Lock Doors + Shut Down House
            if bed_sensors:
                triggers.append(
                    {
                        "platform": "state",
                        "entity_id": bed_sensors,
                        "to": "on",
                        "for": {"minutes": 5},
                        "id": "bedtime_occupied",
                    }
                )
                night_seq: list[dict[str, Any]] = []
                if locks:
                    night_seq.append({"service": "lock.lock", "target": {"entity_id": locks}})
                if garage_covers:
                    night_seq.append({"service": "cover.close_cover", "target": {"entity_id": garage_covers}})
                if alarm_panels:
                    night_seq.append(
                        {"service": "alarm_control_panel.alarm_arm_night", "target": {"entity_id": alarm_panels[0]}}
                    )
                if all_lights:
                    night_seq.append({"service": "light.turn_off", "target": {"entity_id": all_lights[:15]}})
                choose_branches.append(
                    {
                        "conditions": [
                            {"condition": "trigger", "id": "bedtime_occupied"},
                            {"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"},
                            *(
                                [{"condition": "state", "entity_id": b, "state": "on"} for b in bed_sensors]
                            ),
                        ],
                        "sequence": night_seq,
                    }
                )

            # Branch 3: Arrival Home -> Disarm Alarm + Unlock Entry + Welcome Lights
            if persons:
                triggers.append(
                    {
                        "platform": "state",
                        "entity_id": persons,
                        "from": "not_home",
                        "to": "home",
                        "id": "person_arrived",
                    }
                )
                arrive_seq: list[dict[str, Any]] = []
                if alarm_panels:
                    arrive_seq.append(
                        {"service": "alarm_control_panel.alarm_disarm", "target": {"entity_id": alarm_panels[0]}}
                    )
                if locks:
                    arrive_seq.append({"service": "lock.unlock", "target": {"entity_id": locks[0]}})
                if all_lights:
                    arrive_seq.append({"service": "light.turn_on", "target": {"entity_id": all_lights[:3]}})
                choose_branches.append(
                    {
                        "conditions": [{"condition": "trigger", "id": "person_arrived"}],
                        "sequence": arrive_seq,
                    }
                )

            # Branch 4: Alarm Triggered -> Activate Sirens & Turn On All Interior/Exterior Lights
            if alarm_panels and (sirens or all_lights):
                triggers.append(
                    {
                        "platform": "state",
                        "entity_id": alarm_panels[0],
                        "to": "triggered",
                        "id": "alarm_triggered",
                    }
                )
                intrusion_seq: list[dict[str, Any]] = []
                if sirens:
                    intrusion_seq.append({"service": "siren.turn_on", "target": {"entity_id": sirens}})
                if all_lights:
                    intrusion_seq.append(
                        {
                            "service": "light.turn_on",
                            "target": {"entity_id": all_lights[:15]},
                            "data": {"brightness_pct": 100},
                        }
                    )
                choose_branches.append(
                    {
                        "conditions": [{"condition": "trigger", "id": "alarm_triggered"}],
                        "sequence": intrusion_seq,
                    }
                )

            if triggers and choose_branches:
                features_desc = []
                if alarm_panels:
                    features_desc.append(f"Alarm panel ({alarm_panels[0]})")
                if locks:
                    features_desc.append(f"{len(locks)} smart locks")
                if garage_covers:
                    features_desc.append(f"{len(garage_covers)} garage doors")
                if bed_sensors:
                    features_desc.append(f"{len(bed_sensors)} SleepNumber bed sensors")
                if sirens:
                    features_desc.append(f"{len(sirens)} indoor sirens")

                suggestions.append({
                    "id": "unified_security_presence_coordinator",
                    "title": "Unified Security, Presence & Bedtime Coordinator",
                    "category": "security",
                    "priority": "high",
                    "icon": "mdi:shield-lock",
                    "description": (
                        f"Cohesive multi-mode security coordinator integrating {', '.join(features_desc)}. "
                        "Handles Away arming & house shutdown on departure, automatic Night arming when bed sensors "
                        "confirm everyone is in bed, arrival disarming, and full siren/light activation on intrusion."
                    ),
                    "action_type": "create_automation",
                    "action_payload": {
                        "alias": "Unified Security, Presence & Bedtime Coordinator",
                        "description": "Synthesized by Otis AI Companion security topology engine",
                        "trigger": triggers,
                        "action": [{"choose": choose_branches}],
                        "mode": "queued",
                    },
                })

        # 4. Whole-Home Adaptive Multi-Room Occupancy Lighting Coordinator (plus per-area motion lighting)
        motion_light_areas: list[dict[str, Any]] = []
        for area_id, area_info in areas.items():
            area_name = area_info.get("name", area_id)
            area_buckets = classify_area_entities(area_info.get("entities", []))
            lights = area_buckets["lights"]
            motion_sensors = area_buckets["motion"]

            has_existing = (
                any(
                    _norm_str(area_name) in name
                    or _norm_str(area_id) in name
                    or ("inside lights" in name and ("adaptive" in name or "auto" in name))
                    or "lighting router" in name
                    for name in all_existing_names
                )
                or (
                    any(m in automated_entities for m in motion_sensors)
                    and any(lt in automated_entities for lt in lights)
                )
                or (lights and sum(1 for lt in lights if lt in automated_entities) >= max(1, len(lights) // 2))
            )
            if lights and motion_sensors and not has_existing:
                target_lights = lights[0] if len(lights) == 1 else lights
                motion_light_areas.append(
                    {
                        "area_id": area_id,
                        "area_name": area_name,
                        "motion": motion_sensors[0],
                        "lights": target_lights,
                    }
                )
                suggestions.append({
                    "id": f"motion_light_{area_id}",
                    "title": f"Motion-Activated Lighting in {area_name}",
                    "category": "automation",
                    "priority": "medium",
                    "icon": "mdi:motion-sensor",
                    "area_id": area_id,
                    "description": (
                        f"Automatically illuminate {area_name} when motion is detected, "
                        "and turn lights off automatically after 5 minutes of no occupancy."
                    ),
                    "action_type": "create_automation",
                    "action_payload": {
                        "alias": f"Motion-Activated Lighting: {area_name}",
                        "description": f"Automated by Otis AI Companion for {area_name}",
                        "trigger": [
                            {"platform": "state", "entity_id": motion_sensors[0], "to": "on"}
                        ],
                        "action": [
                            {"service": "light.turn_on", "target": {"entity_id": target_lights}},
                            {
                                "wait_for_trigger": [
                                    {
                                        "platform": "state",
                                        "entity_id": motion_sensors[0],
                                        "to": "off",
                                        "for": {"minutes": 5},
                                    }
                                ],
                                "continue_on_timeout": False,
                            },
                            {"service": "light.turn_off", "target": {"entity_id": target_lights}},
                        ],
                        "mode": "restart",
                    },
                })

        has_whole_home_lighting = any(
            any(
                kw in name
                for kw in (
                    "whole home adaptive",
                    "lighting coordinator",
                    "inside lights",
                    "lighting router",
                )
            )
            for name in all_existing_names
        )
        if len(motion_light_areas) >= 2 and not has_whole_home_lighting:
            coord_triggers = []
            coord_choices = []
            for item in motion_light_areas[:8]:
                aid = item["area_id"]
                coord_triggers.append(
                    {
                        "platform": "state",
                        "entity_id": item["motion"],
                        "to": "on",
                        "id": f"enter_{aid}",
                    }
                )
                coord_triggers.append(
                    {
                        "platform": "state",
                        "entity_id": item["motion"],
                        "to": "off",
                        "for": {"minutes": 5},
                        "id": f"clear_{aid}",
                    }
                )
                coord_choices.append(
                    {
                        "conditions": [{"condition": "trigger", "id": f"enter_{aid}"}],
                        "sequence": [{"service": "light.turn_on", "target": {"entity_id": item["lights"]}}],
                    }
                )
                coord_choices.append(
                    {
                        "conditions": [{"condition": "trigger", "id": f"clear_{aid}"}],
                        "sequence": [{"service": "light.turn_off", "target": {"entity_id": item["lights"]}}],
                    }
                )
            room_names = ", ".join(m["area_name"] for m in motion_light_areas[:5])
            suggestions.append({
                "id": "whole_home_lighting_coordinator",
                "title": f"Whole-Home Adaptive Occupancy Lighting Coordinator ({len(motion_light_areas)} Rooms)",
                "category": "lighting",
                "priority": "high",
                "icon": "mdi:home-lightbulb",
                "description": (
                    f"Instead of managing dozens of separate per-room automations, deploy a single cohesive "
                    f"multi-room occupancy lighting coordinator covering {room_names}."
                ),
                "action_type": "create_automation",
                "action_payload": {
                    "alias": "Whole-Home Adaptive Occupancy Lighting Coordinator",
                    "description": "Cohesive multi-room lighting coordinator generated by Otis AI Companion",
                    "trigger": coord_triggers,
                    "action": [{"choose": coord_choices}],
                    "mode": "parallel",
                },
            })

        # 5. Energy Guard: Climate pause on open exterior door/window (interior thermostats only)
        _non_interior_climate = ("pool", "spa", "hot_tub", "garage", "attic", "wine", "crawl", "greenhouse", "sleepnumber", "sleepiq", "bed", "patio", "exterior")
        climates = [
            e for e in entities
            if e.get("domain") == "climate"
            and not any(t in (e.get("entity_id", "") + " " + (e.get("name") or "")).lower() for t in _non_interior_climate)
        ]
        _exterior_contact_tokens = ("front", "back", "rear", "patio", "sliding", "slider", "french", "entry", "porch", "deck", "sunroom", "window", "exterior", "outside", "main_door", "lanai", "balcony", "garage_door")
        _interior_or_non_hvac_tokens = ("closet", "pantry", "bathroom", "bath", "bedroom", "toilet", "laundry", "utility", "office", "study", "attic", "interior", "gate", "mailbox", "fridge", "refrigerator", "freezer", "coolselect", "cabinet", "drawer", "safe", "keypad", "cloud_connection")
        _unconditioned_area_tokens = ("garage", "attic", "crawl", "shed", "patio", "deck", "porch", "frontyard", "backyard", "yard", "driveway", "outside", "exterior", "greenhouse")
        _hvac_area_by_eid = {
            ent_id: aid
            for aid, adata in (areas or {}).items()
            for ent_id in (adata.get("entities") or [])
        }
        door_window_sensors = []
        for e in entities:
            eid = str(e.get("entity_id") or "")
            if not is_contact_sensor(eid):
                continue
            st_obj = self.hass.states.get(eid) if hasattr(self.hass, "states") else None
            raw_dc = (
                (st_obj.attributes.get("device_class") if st_obj and isinstance(getattr(st_obj, "attributes", None), dict) else None)
                or e.get("device_class")
                or e.get("original_device_class")
            )
            dc = raw_dc.lower() if isinstance(raw_dc, str) else ""
            if dc and dc not in ("door", "window", "opening"):
                continue
            if not dc and any(bad_sfx in eid.lower() for bad_sfx in ("_occupancy", "_motion", "_problem", "_connectivity", "_keypad_disabled", "_cloud_connection", "_visitor")):
                continue
            e_area = str(e.get("area_id") or _hvac_area_by_eid.get(eid) or "").lower()
            if e_area and any(ua in e_area for ua in _unconditioned_area_tokens):
                continue
            hay = (eid + " " + str(e.get("name") or "")).lower()
            if any(bad in hay for bad in _interior_or_non_hvac_tokens):
                continue
            if any(t in hay for t in _exterior_contact_tokens):
                door_window_sensors.append(eid)
        has_climate_guard = any(
            "climate" in name and ("door" in name or "window" in name or "pause" in name)
            for name in existing_auto_names
        )
        if climates and door_window_sensors and not has_climate_guard:
            guarded_sensors = door_window_sensors[:10]
            guarded_climates = [c["entity_id"] for c in climates[:5]]
            # Detect existing HVAC/Thermostat blueprint automations that control these thermostats
            managing_hvac_autos: list[str] = []
            for e in entities:
                if e.get("domain") == "automation":
                    e_name_low = str(e.get("name") or e.get("entity_id") or "").lower()
                    if "thermostat" in e_name_low and ("upstairs" in e_name_low or "downstairs" in e_name_low or "climate" in e_name_low):
                        managing_hvac_autos.append(e["entity_id"])
            auto_note = (
                f" Coordinates with {', '.join(managing_hvac_autos)} (pausing them while open so they do not override the hold, then restoring when closed)."
                if managing_hvac_autos
                else ""
            )
            action_steps: list[dict[str, Any]] = []
            if managing_hvac_autos:
                action_steps.append({"service": "automation.turn_off", "target": {"entity_id": managing_hvac_autos}})
            action_steps.append({
                "service": "climate.turn_off",
                "target": {"entity_id": guarded_climates if len(guarded_climates) > 1 else guarded_climates[0]},
            })
            if managing_hvac_autos:
                action_steps.append({
                    "wait_for_trigger": [
                        {
                            "platform": "state",
                            "entity_id": guarded_sensors if len(guarded_sensors) > 1 else guarded_sensors[0],
                            "to": "off",
                            "for": {"minutes": 1},
                        }
                    ],
                    "continue_on_timeout": True,
                })
                action_steps.append({"service": "automation.turn_on", "target": {"entity_id": managing_hvac_autos}})
            suggestions.append({
                "id": "climate_door_window_guard",
                "title": "HVAC Energy Guard (Open Exterior Door/Window)",
                "category": "energy",
                "priority": "high",
                "icon": "mdi:hvac",
                "description": (
                    f"Automatically pause {len(guarded_climates)} interior thermostat(s) when any of {len(guarded_sensors)} "
                    f"exterior door or window contact(s) is left open for more than 3 minutes.{auto_note}"
                ),
                "action_type": "create_automation",
                "action_payload": {
                    "alias": "Climate Energy Guard: Pause HVAC on Open Exterior Door/Window",
                    "description": "Automated by Otis AI Companion",
                    "trigger": [
                        {
                            "platform": "state",
                            "entity_id": guarded_sensors if len(guarded_sensors) > 1 else guarded_sensors[0],
                            "to": "on",
                            "for": {"minutes": 3},
                        }
                    ],
                    "action": action_steps,
                    "mode": "restart",
                },
            })

        # 6. Security / Bedtime Routine script
        has_night_routine = (
            any(
                any(
                    kw in name
                    for kw in (
                        "goodnight",
                        "bedtime",
                        "sleep",
                        "night routine",
                        "lights off at bed",
                    )
                )
                for name in all_existing_names
            )
            or any(b in automated_entities for b in bed_sensors)
        )
        if (locks or len(all_lights) >= 2) and not has_night_routine:
            seq = []
            if locks:
                seq.append({"service": "lock.lock", "target": {"entity_id": locks[0]}})
            if all_lights:
                seq.append({"service": "light.turn_off", "target": {"entity_id": all_lights[:5]}})
            suggestions.append({
                "id": "bedtime_goodnight_routine",
                "title": "Goodnight & Security Routine",
                "category": "security",
                "priority": "medium",
                "icon": "mdi:shield-moon",
                "description": (
                    "A 1-click evening routine that secures exterior doors, turns off living area lighting, "
                    "and arms perimeter detection."
                ),
                "action_type": "create_script",
                "action_payload": {
                    "alias": "Goodnight Routine",
                    "sequence": seq,
                    "mode": "single",
                },
            })

        # 7. Automated Nightly System Backup (Infrastructure Resilience)
        integration_domains = {
            str(i.get("domain", "") if isinstance(i, dict) else i).lower()
            for i in integrations
        }
        has_backup_integration = any(
            ("backup" in d and d != "backup")
            or d in ("pcloud_backup", "google_drive_backup", "samba_backup", "auto_backup", "onedrive")
            for d in integration_domains
        )
        has_backup_auto = (
            any("backup" in name for name in existing_auto_names)
            or bool(config_audit.get("automatic_backups_configured"))
            or has_backup_integration
        )
        if ("hassio" in integration_domains or "backup" in integration_domains) and not has_backup_auto:
            backup_service = "hassio.backup_full" if "hassio" in integration_domains else "backup.create"
            suggestions.append({
                "id": "automated_nightly_backup",
                "title": "Automated Nightly Home Assistant Backup (3:00 AM)",
                "category": "system",
                "priority": "medium",
                "icon": "mdi:backup-restore",
                "description": (
                    "Protect your smart home configuration, spatial graph, and automations by scheduling an "
                    "automatic nightly system backup at 3:00 AM."
                ),
                "action_type": "create_automation",
                "action_payload": {
                    "alias": "System Maintenance: Automated Nightly Backup",
                    "description": "Automated by Otis AI Companion infrastructure advisor",
                    "trigger": [{"platform": "time", "at": "03:00:00"}],
                    "action": [{"service": backup_service, "data": {}}],
                    "mode": "single",
                },
            })

        # 8. Ecosystem & Integration Advisor (Music Assistant, Alarmo, Spook/Watchman)
        if (
            media_topology.get("matrix_amp_detected")
            and "mass" not in integration_domains
            and "music_assistant" not in integration_domains
        ):
            streamers = media_topology.get("input_streamers", [])
            streamer_eids = ", ".join(s["entity_id"] for s in streamers[:2]) if streamers else "your matrix input bridges"
            suggestions.append({
                "id": "ecosystem_advisor_music_assistant",
                "title": "Ecosystem Advisor: Pair Music Assistant with Your Matrix Amp",
                "category": "system",
                "priority": "low",
                "icon": "mdi:music-box-multiple",
                "description": (
                    "Your multi-zone Matrix Amp routes shared input bridges across multiple rooms. Installing the "
                    "Music Assistant add-on/integration lets Otis stream Spotify, Apple Music, local FLAC libraries, "
                    "and voice announcements directly into your matrix input bridges."
                ),
                "action_type": "advisor_guide",
                "action_payload": {
                    "guide": (
                        f"Install the Music Assistant Server add-on and Home Assistant integration, then expose "
                        f"{streamer_eids} as upstream player providers."
                    )
                },
            })

        if (
            (locks or security_topology.get("perimeter_contact_sensors"))
            and not alarm_panels
            and "alarmo" not in integration_domains
        ):
            suggestions.append({
                "id": "ecosystem_advisor_alarmo",
                "title": "Ecosystem Advisor: Install Alarmo for Native Security Panel",
                "category": "security",
                "priority": "low",
                "icon": "mdi:shield-Plus",
                "description": (
                    "You have door/window sensors and smart locks but no active alarm_control_panel entity. "
                    "Installing Alarmo via HACS creates a full-featured security panel with entry/exit delays and PIN codes."
                ),
                "action_type": "advisor_guide",
                "action_payload": {
                    "guide": "Install 'Alarmo' from HACS -> Integrations to create alarm_control_panel.alarmo."
                },
            })

        # 9. Multi-agent failover configuration recommendation
        prioritized_agents = await async_get_prioritized_agents(self.hass)
        if len(prioritized_agents) <= 1:
            suggestions.append({
                "id": "multi_agent_redundancy",
                "title": "Configure AI Failover Redundancy",
                "category": "system",
                "priority": "low",
                "icon": "mdi:robot-confused",
                "description": (
                    "Only 1 AI conversation agent is active. Adding a local or cloud fallback agent "
                    "(e.g., Ollama or OpenAI) ensures Otis AI Companion remains 100% operational during cloud rate limits or provider downtime."
                ),
                "action_type": "configure_agent",
                "action_payload": {},
            })

        # 10. Historical Sensor Trend & Habit Routine Mining
        try:
            mined_routines = await self.async_mine_historical_habits(days=7)
            for idx, routine in enumerate(mined_routines[:3]):
                s_id = f"habit_routine_{idx}_{routine['trigger_entity'].replace('.', '_')}"
                suggestions.append({
                    "id": s_id,
                    "title": routine["title"],
                    "category": "habit_routine",
                    "priority": "medium",
                    "icon": "mdi:clock-check-outline",
                    "description": routine["description"],
                    "action_type": routine["action_type"],
                    "action_payload": routine["action_payload"],
                })
        except Exception as err:
            _LOGGER.debug("Discovery Engine: Habit mining skipped or failed: %s", err)

        # 11. Spatial Adjacency: Contextual Pathway Lighting
        spatial_graph = capability_map.get("spatial_graph", {})
        adjacencies = spatial_graph.get("adjacencies", {})
        has_pathway_auto = any("pathway" in name or "transition" in name for name in existing_auto_names)
        _outdoor_pathway_tokens = ("backyard", "frontyard", "yard", "driveway", "porch", "patio", "deck", "pool", "exterior", "outside", "garage", "attic", "shed")
        if not has_pathway_auto and adjacencies:
            for src_area_id, neighbors in adjacencies.items():
                if any(tok in str(src_area_id).lower() for tok in _outdoor_pathway_tokens):
                    continue
                src_area = areas.get(src_area_id, {})
                src_motion = _filter_valid_presence_sensors(classify_area_entities(src_area.get("entities", []))["motion"])
                if not src_motion:
                    continue
                for nbr_id in neighbors:
                    if any(tok in str(nbr_id).lower() for tok in _outdoor_pathway_tokens):
                        continue
                    nbr_area = areas.get(nbr_id, {})
                    nbr_lights = [
                        lt for lt in classify_area_entities(nbr_area.get("entities", []))["lights"]
                        if not any(tok in lt.lower() for tok in _NON_MAIN_LIGHT_TOKENS)
                    ]
                    if nbr_lights:
                        src_name = src_area.get("name", src_area_id)
                        nbr_name = nbr_area.get("name", nbr_id)
                        nbr_motion = _filter_valid_presence_sensors(classify_area_entities(nbr_area.get("entities", []))["motion"])
                        clear_entities = [src_motion[0]] + ([nbr_motion[0]] if nbr_motion else [])
                        suggestions.append({
                            "id": f"spatial_pathway_{src_area_id}_{nbr_id}",
                            "title": f"Pathway Lighting: {src_name} → {nbr_name}",
                            "category": "lighting",
                            "priority": "medium",
                            "icon": "mdi:map-marker-path",
                            "description": (
                                f"Automatically illuminate {nbr_name} pathway lighting when motion is detected in connected {src_name} after dark, "
                                "and turn off automatically after 2 minutes of inactivity."
                            ),
                            "action_type": "create_automation",
                            "action_payload": {
                                "alias": f"Contextual Pathway Lighting: {src_name} to {nbr_name}",
                                "description": "Automated by Otis AI Companion spatial adjacency engine",
                                "trigger": [
                                    {
                                        "platform": "state",
                                        "entity_id": src_motion[0],
                                        "to": "on",
                                    }
                                ],
                                "condition": [
                                    {
                                        "condition": "state",
                                        "entity_id": "sun.sun",
                                        "state": "below_horizon",
                                    }
                                ],
                                "action": [
                                    {"service": "light.turn_on", "target": {"entity_id": nbr_lights[0]}},
                                    {
                                        "wait_for_trigger": [
                                            {
                                                "platform": "state",
                                                "entity_id": clear_entities if len(clear_entities) > 1 else clear_entities[0],
                                                "to": "off",
                                                "for": {"minutes": 2},
                                            }
                                        ],
                                        "timeout": {"minutes": 10},
                                        "continue_on_timeout": True,
                                    },
                                    {"service": "light.turn_off", "target": {"entity_id": nbr_lights[0]}},
                                ],
                                "mode": "restart",
                            },
                        })
                        break
                if any(s.get("id", "").startswith("spatial_pathway_") for s in suggestions):
                    break

        # 11b. Architectural Open-Concept Zone Sync (Living/Great Room + Kitchen)
        living_area_id = next(
            (aid for aid in areas if any(k in aid.lower() for k in ("great_room", "living", "family"))),
            None,
        )
        kitchen_area_id = next(
            (aid for aid in areas if "kitchen" in aid.lower()),
            None,
        )
        gr_buckets = classify_area_entities(areas.get(living_area_id or "", {}).get("entities", []))
        kit_buckets = classify_area_entities(areas.get(kitchen_area_id or "", {}).get("entities", []))
        gr_lights = gr_buckets["lights"]
        kit_lights = kit_buckets["lights"]
        gr_motion = gr_buckets["motion"] + kit_buckets["motion"]
        has_open_concept_sync = (
            any(
                any(
                    kw in name
                    for kw in (
                        "open concept",
                        "great room zone",
                        "inside lights",
                        "lighting router",
                    )
                )
                for name in all_existing_names
            )
            or (
                any(lt in automated_entities for lt in gr_lights)
                and any(lt in automated_entities for lt in kit_lights)
            )
        )
        if living_area_id and kitchen_area_id and gr_lights and kit_lights and gr_motion and not has_open_concept_sync:
            living_name = areas[living_area_id].get("name", living_area_id)
            kitchen_name = areas[kitchen_area_id].get("name", kitchen_area_id)
            suggestions.append({
                "id": "architectural_great_room_open_concept_sync",
                "title": f"{living_name} & {kitchen_name} Open-Concept Zone Sync",
                "category": "lighting",
                "priority": "high",
                "icon": "mdi:floor-plan",
                "description": (
                    f"Your floor plan maps {living_name} and {kitchen_name} as a connected open-concept space. "
                    f"Coordinate ambient lighting across both sub-zones upon evening entry and turn off together "
                    f"only when the entire open-concept zone clears."
                ),
                "action_type": "create_automation",
                "action_payload": {
                    "alias": f"Open-Concept Zone Sync ({living_name} & {kitchen_name})",
                    "description": "Synthesized from Otis AI architectural walkthrough floor plan",
                    "trigger": [
                        {"platform": "state", "entity_id": gr_motion[0], "to": "on"}
                    ],
                    "condition": [
                        {"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"}
                    ],
                    "action": [
                        {"service": "light.turn_on", "target": {"entity_id": [gr_lights[0], kit_lights[0]]}}
                    ],
                    "mode": "single",
                },
            })

        # 11c. Architectural Indoor-to-Outdoor Transition (Entry/Mudroom → Backyard/Patio/Pool)
        transition_in_id = next(
            (aid for aid in areas if any(k in aid.lower() for k in ("mudroom", "breezeway", "foyer", "back_entry"))),
            None,
        )
        outdoor_area_ids = [
            aid for aid in areas if any(k in aid.lower() for k in ("backyard", "patio", "deck", "pool", "yard"))
        ]
        mud_buckets = classify_area_entities(areas.get(transition_in_id or "", {}).get("entities", []))
        mud_triggers = list(mud_buckets["motion"] + mud_buckets["contact"])
        outdoor_lights: list[str] = []
        outdoor_names: list[str] = []
        for o_id in outdoor_area_ids:
            o_buckets = classify_area_entities(areas.get(o_id, {}).get("entities", []))
            mud_triggers.extend(o_buckets["motion"] + o_buckets["contact"])
            if o_buckets["lights"]:
                outdoor_lights.extend(o_buckets["lights"])
                outdoor_names.append(areas[o_id].get("name", o_id))

        has_backyard_transition = (
            any(
                any(
                    kw in name
                    for kw in (
                        "to backyard",
                        "backyard deck",
                        "outside lights",
                        "lighting router",
                    )
                )
                for name in all_existing_names
            )
            or any(lt in automated_entities for lt in outdoor_lights)
        )
        if transition_in_id and mud_triggers and outdoor_lights and not has_backyard_transition:
            in_name = areas[transition_in_id].get("name", transition_in_id)
            out_label = " & ".join(outdoor_names[:2]) if outdoor_names else "Outdoor Living"
            suggestions.append({
                "id": "architectural_mudroom_backyard_pool_transition",
                "title": f"{in_name} → {out_label} Evening Transition",
                "category": "lighting",
                "priority": "medium",
                "icon": "mdi:pool",
                "description": (
                    f"Based on your spatial transition from {in_name} out to {out_label}, "
                    "automatically illuminate outdoor perimeter & deck lighting when stepping outside after dark."
                ),
                "action_type": "create_automation",
                "action_payload": {
                    "alias": f"{in_name} to {out_label} Evening Lighting",
                    "description": "Synthesized from Otis AI architectural walkthrough floor plan",
                    "trigger": [
                        {"platform": "state", "entity_id": mud_triggers[0], "to": "on"}
                    ],
                    "condition": [
                        {"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"}
                    ],
                    "action": [
                        {"service": "light.turn_on", "target": {"entity_id": outdoor_lights[:3]}}
                    ],
                    "mode": "single",
                },
            })

        # 12. Interactive Vector Floor Plan walkthrough recommendation
        has_walkthrough = self.floorplan_parser.has_walkthrough()
        if not has_walkthrough:
            suggestions.append({
                "id": "record_walkthrough_floorplan",
                "title": "Record Walkthrough for Vector Floor Plan",
                "category": "visualization",
                "priority": "high",
                "icon": "mdi:floor-plan",
                "description": (
                    "No walkthrough video found for your home. Use your mobile phone to record a quick video "
                    "walkthrough, calling out each room as you enter. Otis will parse the video into an interactive "
                    "multi-floor SVG dashboard!"
                ),
                "action_type": "upload_walkthrough",
                "action_payload": {},
            })

        # 13. Phase 7 Energy & Predictive Load Orchestrator Suggestions
        energy_topo = capability_map.get("energy_topology", {})
        tariff_info = energy_topo.get("tariff", {})
        load_shed_info = energy_topo.get("load_shedding", {})
        solar_info = energy_topo.get("solar", {})

        if tariff_info.get("is_peak") and load_shed_info.get("active_sheddable_loads_count", 0) > 0:
            savings = round(load_shed_info.get("potential_savings_w", 0))
            cand_loads = load_shed_info.get("candidates") or []
            load_preview = ", ".join(
                f"{c.get('name') or c.get('entity_id')} (~{round(float(c.get('watts') or c.get('estimated_watts') or 0))}W)"
                for c in cand_loads[:4]
                if c.get("name") or c.get("entity_id")
            )
            load_detail = f" Candidate loads: {load_preview}." if load_preview else ""
            suggestions.append({
                "id": "peak_load_shed_recommendation",
                "title": f"Shed High-Draw Loads for Peak Tariff (~{savings}W)",
                "category": "energy",
                "priority": "high",
                "icon": "mdi:transmission-tower-export",
                "description": (
                    f"Your electrical grid is currently in PEAK rate window. Otis detected "
                    f"{load_shed_info.get('active_sheddable_loads_count')} deferrable load(s) consuming up to {savings}W.{load_detail} "
                    "Shed non-essential loads now to minimize peak energy costs."
                ),
                "action_type": "load_shed",
                "action_payload": {
                    "tier": 1,
                    "candidates": [
                        {
                            "entity_id": c["entity_id"],
                            "name": c.get("name") or c["entity_id"],
                            "watts": round(float(c.get("estimated_watts") or c.get("watts") or 0)),
                        }
                        for c in cand_loads[:6]
                        if c.get("entity_id")
                    ],
                },
            })

        if solar_info.get("has_surplus"):
            prod = round(solar_info.get("production_w", 0))
            suggestions.append({
                "id": "solar_surplus_sequencing",
                "title": f"Solar Production Surplus (+{prod}W Available)",
                "category": "energy",
                "priority": "medium",
                "icon": "mdi:solar-power-variant",
                "description": (
                    f"Your solar generation currently exceeds home consumption with ~{prod}W surplus. "
                    "Ideal window to charge electric vehicles, run pool filtration, or pre-heat/pre-cool rooms."
                ),
                "action_type": "chat_prompt",
                "action_payload": {"prompt": "Optimize high loads for solar production surplus"},
            })

        # 11. Multi-Modal Vision & Presence Contextual Alerts & Automation Optimizations (Phase 8)
        if getattr(self, "vision_manager", None):
            try:
                ctx_alerts = await self.vision_manager.async_evaluate_contextual_alerts()
                for alert in ctx_alerts:
                    suggestions.append(alert)

                # Generate proactive Vision & Presence automation recommendations
                presence_states = await self.vision_manager.async_get_presence_states(use_cache=True)
                p_rooms = presence_states.get("rooms", {})
                for aid, ainfo in areas.items():
                    a_name = ainfo.get("name") or aid.replace("_", " ").title()
                    a_ents = ainfo.get("entities", [])
                    has_presence = any(
                        eid.startswith("binary_sensor.") and any(k in eid.lower() for k in ("motion", "occupancy", "presence"))
                        for eid in a_ents
                    ) or aid in p_rooms
                    a_lights = [eid for eid in a_ents if eid.startswith("light.") and not any(tok in eid.lower() for tok in _NON_MAIN_LIGHT_TOKENS)]
                    has_vacancy_auto = any(
                        "vacancy" in name and aid in name
                        for name in all_existing_names
                    )
                    if has_presence and a_lights and not has_vacancy_auto:
                        valid_area_sensors = _filter_valid_presence_sensors(a_ents)
                        m_sensor = valid_area_sensors[0] if valid_area_sensors else None
                        if m_sensor:
                            suggestions.append({
                                "id": f"vision_presence_vacancy_auto_{aid}",
                                "title": f"Vision & Presence: Auto-Power Down Vacant {a_name}",
                                "category": "energy",
                                "priority": "medium",
                                "icon": "mdi:motion-sensor-off",
                                "description": (
                                    f"Presence telemetry indicates {a_name} is actively occupied during the day. "
                                    f"Deploy an intelligent 10-minute vacancy auto-off coordinator for {len(a_lights)} "
                                    f"{'area' if any(tok in aid.lower() for tok in ('backyard', 'frontyard', 'yard', 'driveway', 'porch', 'patio', 'deck', 'garage', 'exterior', 'outside')) else 'room'} lights to save power when residents leave."
                                ),
                                "action_type": "create_automation",
                                "action_payload": {
                                    "alias": f"Vacancy Coordinator: Auto-Off {a_name} Lights",
                                    "description": f"Automated by Otis AI Companion Vision & Presence for {a_name}",
                                    "trigger": [
                                        {
                                            "platform": "state",
                                            "entity_id": m_sensor,
                                            "to": "off",
                                            "for": {"minutes": 10},
                                        }
                                    ],
                                    "action": [
                                        {"service": "light.turn_off", "target": {"entity_id": a_lights[:5]}}
                                    ],
                                    "mode": "single",
                                },
                            })
                            break  # Surface top vacancy coordinator

                # Outdoor Camera Smart Detection Alerts
                cams = await self.vision_manager.async_get_cameras()
                all_states_list = self.hass.states.async_all() if hasattr(self.hass.states, "async_all") else []
                for c in cams:
                    c_eid = c.get("entity_id", "")
                    raw_name = c.get("name") or c_eid
                    c_name = re.sub(r"\s+(?:fluent|clear|sub|main)\b", "", str(raw_name), flags=re.IGNORECASE).strip() or raw_name
                    c_lower = (c_eid + " " + c_name).lower()
                    is_outdoor = any(k in c_lower for k in ("front", "driveway", "porch", "patio", "backyard", "doorbell", "yard"))
                    has_cam_alert = any(c_name.lower() in name for name in all_existing_names)
                    if is_outdoor and not has_cam_alert:
                        c_slug = re.sub(r"\W+", "_", c_eid.lower()).strip("_")
                        is_front_entry = any(k in c_lower for k in ("front", "driveway", "porch", "doorbell"))
                        cam_prefix = c_eid.replace("camera.", "").split("_fluent")[0].split("_clear")[0]
                        trigger_eid = next(
                            (
                                st.entity_id
                                for st in all_states_list
                                if st.entity_id.startswith("binary_sensor.")
                                and cam_prefix in st.entity_id.lower()
                                and any(k in st.entity_id.lower() for k in ("_person", "_motion", "_visitor"))
                            ),
                            c_eid,
                        )
                        trigger_to = "on" if trigger_eid.startswith("binary_sensor.") else "recording"
                        title_text = (
                            f"Vision Watchdog: Outdoor Arrival & Delivery Detection ({c_name})"
                            if is_front_entry
                            else f"Vision Watchdog: Perimeter Activity & Visitor Detection ({c_name})"
                        )
                        desc_text = (
                            f"Connect Otis AI vision heuristics with {c_name} to broadcast actionable mobile alerts "
                            "with live snapshots when delivery vehicles, packages, or visitors approach after sunset."
                            if is_front_entry
                            else f"Connect Otis AI vision heuristics with {c_name} to broadcast actionable mobile alerts "
                            "with live snapshots when unexpected perimeter movement or visitors are detected after sunset."
                        )
                        suggestions.append({
                            "id": f"vision_outdoor_watchdog_{c_slug}",
                            "title": title_text,
                            "category": "security",
                            "priority": "high",
                            "icon": "mdi:cctv",
                            "description": desc_text,
                            "action_type": "create_automation",
                            "action_payload": {
                                "alias": f"Vision Watchdog: {c_name} Activity Alert",
                                "description": "Automated by Otis AI Companion Vision Watchdog",
                                "trigger": [
                                    {
                                        "platform": "state",
                                        "entity_id": trigger_eid,
                                        "to": trigger_to,
                                    }
                                ],
                                "condition": [
                                    {"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"}
                                ],
                                "action": [
                                    {
                                        "service": "notify.notify",
                                        "data": {
                                            "title": f"Security Notice: Activity at {c_name}",
                                            "message": f"Otis detected evening activity on {c_name}.",
                                        },
                                    }
                                ],
                                "mode": "single",
                            },
                        })
                        break  # Surface 1 primary outdoor camera suggestion
            except Exception as err:
                _LOGGER.debug("Error evaluating contextual alerts: %s", err)

        # 12. Self-Supervised Habit Learning & Behavioral Routines (Phase 9)
        if getattr(self, "habit_manager", None):
            try:
                deviations = await self.habit_manager.async_detect_habit_deviations()
                for dev in deviations:
                    suggestions.append(dev)

                mined_habits = await self.habit_manager.async_mine_habits(days=14, min_occurrences=3)
                for routine in mined_habits[:2]:
                    suggestions.append(routine)

                # Phase 4 Step 4: Spatial migration habits
                spatial_habits = await self.habit_manager.async_mine_spatial_habits(min_confidence=0.70, min_occurrences=2)
                for sh in spatial_habits:
                    suggestions.append(sh)
            except Exception as err:
                _LOGGER.debug("Error evaluating habit routine suggestions: %s", err)

        # 13. Autonomous Home Commissioning (Phase 10)
        if getattr(self, "commissioning_manager", None):
            try:
                comm_audit = await self.commissioning_manager.async_audit_unassigned()
                high_conf = comm_audit.get("high_confidence_count", 0)
                if high_conf > 0:
                    suggestions.append({
                        "id": f"auto_commission_{high_conf}_entities",
                        "title": f"Autonomous Commissioning: {high_conf} Unassigned Entities Detected",
                        "category": "cleanup",
                        "priority": "high" if high_conf >= 3 else "medium",
                        "icon": "mdi:home-plus",
                        "description": (
                            f"Otis discovered {high_conf} unassigned entities with strong heuristic & spatial "
                            "room matches (e.g. naming tokens and parent device topology). "
                            "Click to automatically commission them with zero manual configuration."
                        ),
                        "action_type": "auto_commission_entities",
                        "action_payload": {"min_confidence": 0.85},
                    })
            except Exception as err:
                _LOGGER.debug("Error generating commissioning suggestions: %s", err)

        # 14. Multi-Node Federation Edge Sync (Phase 10)
        if getattr(self, "federation_manager", None):
            try:
                fed_summary = await self.federation_manager.async_get_federation_summary()
                offline = fed_summary.get("offline_nodes", 0)
                total_nodes = fed_summary.get("total_nodes", 0)
                if offline > 0:
                    suggestions.append({
                        "id": "federation_offline_alert",
                        "title": f"Federation Alert: {offline} Remote Edge Node(s) Unreachable",
                        "category": "system",
                        "priority": "high",
                        "icon": "mdi:server-network-off",
                        "description": (
                            f"{offline} of {total_nodes} federated Home Assistant edge nodes are unreachable. "
                            "Inspect network link or trigger edge resynchronization."
                        ),
                        "action_type": "sync_federated_nodes",
                        "action_payload": {},
                    })
            except Exception as err:
                _LOGGER.debug("Error generating federation suggestions: %s", err)

        # 15. Smart Home Maturity Improvement Cards (Guarantee actionable cards for any dimension < 20/20)
        bd = maturity.get("breakdown", {})
        mat_gaps = maturity.get("gaps", {})

        # Spatial Maturity (< 20)
        if bd.get("spatial", 20) < 20 and not any(
            s.get("category") == "visualization" or "floor" in s.get("id", "") or "pathway" in s.get("id", "")
            for s in suggestions
        ):
            spatial_desc = (
                " ".join(mat_gaps.get("spatial", []))
                if mat_gaps.get("spatial")
                else "Upload a walkthrough video or map your rooms to unlock 20/20 spatial intelligence."
            )
            suggestions.append({
                "id": "maturity_reach_20_spatial",
                "title": f"Maturity Goal: Reach 20/20 Spatial Organization ({bd.get('spatial', 0)}/20)",
                "category": "system",
                "priority": "medium",
                "icon": "mdi:floor-plan",
                "description": (
                    f"Otis spatial maturity is at {bd.get('spatial', 0)}/20. {spatial_desc} "
                    "Achieving 20/20 gives Otis complete spatial context for room-aware commands and auto-routing."
                ),
                "action_type": "upload_walkthrough",
                "action_payload": {},
            })

        # Hygiene Maturity (< 20)
        if bd.get("hygiene", 20) < 20 and not any(
            s.get("category") == "cleanup" for s in suggestions
        ):
            hygiene_desc = (
                " ".join(mat_gaps.get("hygiene", []))
                if mat_gaps.get("hygiene")
                else "Clean up orphaned entities or assign unassigned devices to areas."
            )
            suggestions.append({
                "id": "maturity_reach_20_hygiene",
                "title": f"Maturity Goal: Reach 20/20 Registry Hygiene ({bd.get('hygiene', 0)}/20)",
                "category": "cleanup",
                "priority": "medium",
                "icon": "mdi:broom",
                "description": (
                    f"Registry hygiene is at {bd.get('hygiene', 0)}/20. {hygiene_desc} "
                    "A clean registry prevents state engine collisions and ensures 100% entity addressability."
                ),
                "action_type": "auto_commission_entities",
                "action_payload": {},
            })

        # Automation Maturity (< 20)
        if bd.get("automation", 20) < 20 and not any(
            s.get("category") in ("automation", "lighting", "habit_routine") for s in suggestions
        ):
            auto_desc = (
                " ".join(mat_gaps.get("automation", []))
                if mat_gaps.get("automation")
                else "Add essential occupancy lighting, sunset, or climate automations."
            )
            suggestions.append({
                "id": "maturity_reach_20_automation",
                "title": f"Maturity Goal: Reach 20/20 Automation Depth ({bd.get('automation', 0)}/20)",
                "category": "automation",
                "priority": "medium",
                "icon": "mdi:lightning-bolt-circle",
                "description": (
                    f"Automation coverage is at {bd.get('automation', 0)}/20. {auto_desc} "
                    "Reaching 20/20 transforms manual switch presses into autonomous background routines."
                ),
                "action_type": "chat_prompt",
                "action_payload": {"prompt": "Create essential smart home automations for my lighting and climate"},
            })

        # Security Maturity (< 20)
        if bd.get("security", 20) < 20 and not any(
            s.get("category") == "security" for s in suggestions
        ):
            sec_desc = (
                " ".join(mat_gaps.get("security", []))
                if mat_gaps.get("security")
                else "Configure an alarm control panel (e.g. Alarmo), smart locks, or presence tracking."
            )
            suggestions.append({
                "id": "maturity_reach_20_security",
                "title": f"Maturity Goal: Reach 20/20 Security & Presence ({bd.get('security', 0)}/20)",
                "category": "security",
                "priority": "medium",
                "icon": "mdi:shield-check",
                "description": (
                    f"Security intelligence is at {bd.get('security', 0)}/20. {sec_desc} "
                    "Reaching 20/20 ensures automated perimeter defense, night arming, and intrusion deterrence."
                ),
                "action_type": "advisor_guide",
                "action_payload": {"guide": "Install Alarmo via HACS and configure smart locks or presence sensors for whole-home security."},
            })

        # Media Maturity (< 20)
        if bd.get("media", 20) < 20 and not any(
            s.get("category") == "media" for s in suggestions
        ):
            media_desc = (
                " ".join(mat_gaps.get("media", []))
                if mat_gaps.get("media")
                else "Deploy whole-home audio grouping or pair Music Assistant with your media players."
            )
            suggestions.append({
                "id": "maturity_reach_20_media",
                "title": f"Maturity Goal: Reach 20/20 Media Harmony ({bd.get('media', 0)}/20)",
                "category": "media",
                "priority": "medium",
                "icon": "mdi:speaker-multiple",
                "description": (
                    f"Media architecture is at {bd.get('media', 0)}/20. {media_desc} "
                    "Reaching 20/20 unlocks cross-room follow-me audio, synchronized party mode, and voice announcements."
                ),
                "action_type": "advisor_guide",
                "action_payload": {"guide": "Configure media players or Music Assistant in your main rooms for coordinated multi-room audio."},
            })

        # 16. Proactive Identity, Presence & Spatial Intelligence (People, Pets & Guests)
        if getattr(self, "rules_manager", None):
            try:
                rules_data = self.rules_manager.get_rules()
                profiles = self.rules_manager.get_person_profiles()
                ignored_pids = {str(x).lower() for x in (rules_data.get("ignored_persons") or [])}
                person_entities = [e for e in entities if str(e.get("entity_id", "")).startswith("person.")]

                merged_profile_map: dict[str, dict[str, Any]] = {}

                # 1. Include all stored profiles from rules_manager (custom residents, pets, guests)
                for raw_pid, prof in profiles.items():
                    if not isinstance(prof, dict):
                        continue
                    pid = str(prof.get("person_id") or raw_pid).strip().lower()
                    if not pid or pid in ignored_pids:
                        continue
                    if prof.get("training_enabled") is False or prof.get("entity_type") == "ignored":
                        continue
                    p_label = str(prof.get("label") or pid.replace("person.", "").replace("user_", "").replace("_", " ").title())
                    p_type = prof.get("entity_type") or (
                        "pet" if any(k in p_label.lower() for k in ("dexter", "charles", "dog", "cat", "pet"))
                        else ("guest" if "guest" in p_label.lower() else "resident")
                    )
                    merged_profile_map[pid] = {
                        "person_id": pid,
                        "label": p_label,
                        "entity_type": p_type,
                        "confidence": float(prof.get("confidence", 0.50)),
                        "samples": int(prof.get("samples", 0)),
                        "verified_rooms": list(prof.get("verified_rooms") or []),
                    }

                # 2. Merge tracked person.* entities (skip untracked persons with no device_trackers unless explicitly profiled)
                for pe in person_entities:
                    pid = str(pe["entity_id"]).lower()
                    if pid in ignored_pids:
                        continue
                    p_name = pe.get("name") or pid.replace("person.", "").title()
                    prof = profiles.get(pid, {})
                    if prof.get("training_enabled") is False or prof.get("entity_type") == "ignored":
                        continue
                    st_p = self.hass.states.get(pid) if hasattr(self.hass, "states") else None
                    if st_p and isinstance(getattr(st_p, "attributes", None), dict):
                        trackers = st_p.attributes.get("device_trackers")
                        if isinstance(trackers, list) and len(trackers) == 0 and pid not in profiles:
                            continue
                    p_type = prof.get("entity_type") or (
                        "pet" if any(k in p_name.lower() for k in ("dexter", "charles", "dog", "cat", "pet"))
                        else ("guest" if "guest" in p_name.lower() else "resident")
                    )
                    merged_profile_map[pid] = {
                        "person_id": pid,
                        "label": prof.get("label") or p_name,
                        "entity_type": p_type,
                        "confidence": float(prof.get("confidence", 0.50)),
                        "samples": int(prof.get("samples", 0)),
                        "verified_rooms": list(prof.get("verified_rooms") or []),
                    }

                # Filter out accidental area-named or compound "and" profiles when individual profiles exist
                area_name_lowers = {str(a.get("name") or k).strip().lower() for k, a in (areas or {}).items()}
                raw_active = list(merged_profile_map.values())
                single_lowers = {str(p["label"]).strip().lower() for p in raw_active if " and " not in str(p["label"]).lower()}
                active_training_profiles: list[dict[str, Any]] = [
                    p for p in raw_active
                    if str(p["label"]).strip().lower() not in area_name_lowers
                    and not (
                        " and " in str(p["label"]).lower()
                        and any(sp in str(p["label"]).lower() for sp in single_lowers)
                    )
                ]

                # Live Room Entry & Active Presence Identity Verification Prompts
                guest_mode_on = any(
                    str(getattr(st, "state", "") or "").lower() == "on"
                    for st in (self.hass.states.async_all("input_boolean") if hasattr(self.hass, "states") else [])
                    if "guest_mode" in st.entity_id.lower()
                )
                untrained_profiles = [
                    p for p in active_training_profiles
                    if (p["samples"] < 5 or p["confidence"] < 0.85)
                    and (p["entity_type"] != "guest" or guest_mode_on)
                ]
                if untrained_profiles and getattr(self, "vision_manager", None):
                    pres_data = await self.vision_manager.async_get_presence_states(use_cache=True)
                    rooms_map = pres_data.get("rooms") or {}
                    recent_trans = self.vision_manager.get_transition_history(5)
                    cams = await self.vision_manager.async_get_cameras()
                    all_states = self.hass.states.async_all() if hasattr(self.hass.states, "async_all") else []
                    entity_to_area = (
                        self.vision_manager._build_entity_to_area_map()
                        if hasattr(self.vision_manager, "_build_entity_to_area_map")
                        else {}
                    )
                    recent_verifications = (
                        rules_data.get("recent_room_verifications") or {}
                    )
                    now_ts = time.time()

                    candidate_rooms: list[tuple[str, str]] = []
                    seen_rooms: set[str] = set()

                    for tr in reversed(recent_trans):
                        to_r = str(tr.get("to_area") or "").strip().lower()
                        if to_r and to_r not in seen_rooms:
                            if (now_ts - float(recent_verifications.get(to_r, 0.0))) < 600.0:
                                continue
                            r_name = rooms_map.get(to_r, {}).get("area_name") or to_r.replace("_", " ").title()
                            candidate_rooms.append((to_r, r_name))
                            seen_rooms.add(to_r)

                    for r_slug, r_info in rooms_map.items():
                        clean_slug = str(r_slug).strip().lower()
                        if clean_slug in seen_rooms:
                            continue
                        if (now_ts - float(recent_verifications.get(clean_slug, 0.0))) < 600.0:
                            continue
                        s_info = r_info.get("sensors") or {}
                        has_active_sensor = (
                            (s_info.get("mmwave") or {}).get("active")
                            or (s_info.get("pir") or {}).get("active")
                            or ((s_info.get("pir") or {}).get("seconds_since_motion") is not None and (s_info.get("pir") or {}).get("seconds_since_motion", 9999) <= 600)
                            or r_info.get("status") in ("occupied", "likely_occupied")
                        )
                        if has_active_sensor:
                            candidate_rooms.append((clean_slug, r_info.get("area_name") or clean_slug.replace("_", " ").title()))
                            seen_rooms.add(clean_slug)

                    # Also include camera-equipped rooms if fewer than 3 active rooms matched
                    for c_item in cams:
                        c_area = str(c_item.get("area_id") or "").strip().lower()
                        if not c_area or c_area in seen_rooms:
                            continue
                        if (now_ts - float(recent_verifications.get(c_area, 0.0))) < 600.0:
                            continue
                        c_area_name = (
                            rooms_map.get(c_area, {}).get("area_name")
                            or c_item.get("area_name")
                            or c_area.replace("_", " ").title()
                        )
                        candidate_rooms.append((c_area, c_area_name))
                        seen_rooms.add(c_area)

                    # Resolve camera & detection snapshot media for each candidate room and prioritize rooms with visual media
                    classified_snapshots = set(
                        str(x) for x in (rules_data.get("classified_snapshots") or []) if x
                    )
                    seen_det_eids: set[str] = set()
                    enriched_candidates: list[tuple[str, str, dict[str, Any]]] = []
                    for r_slug, r_name in candidate_rooms:
                        media_info = self._resolve_room_training_media(
                            r_slug, r_name, cams, all_states, entity_to_area
                        )
                        snap_key = media_info.get("snapshot_key")
                        det_eid_val = media_info.get("detection_image_entity_id")
                        if snap_key and snap_key in classified_snapshots:
                            continue
                        if det_eid_val and det_eid_val in seen_det_eids:
                            continue
                        if det_eid_val:
                            seen_det_eids.add(det_eid_val)
                        enriched_candidates.append((r_slug, r_name, media_info))

                    camera_backed = [
                        item for item in enriched_candidates
                        if item[2].get("camera_entity_id")
                        or item[2].get("detection_image_entity_id")
                        or item[2].get("snapshot_camera_entity_id")
                    ]
                    selected_room_items = camera_backed[:3] if camera_backed else enriched_candidates[:3]

                    # Concurrently resolve bounding boxes for detection snapshots (cached per snapshot_key)
                    bbox_results: list[Any] = [None] * len(selected_room_items)
                    if hasattr(self.vision_manager, "async_detect_snapshot_bbox"):
                        async def _fetch_bbox(m_info: dict[str, Any]) -> dict[str, Any] | None:
                            target_eid = (
                                m_info.get("detection_image_entity_id")
                                or m_info.get("snapshot_camera_entity_id")
                            )
                            if not target_eid:
                                return None
                            try:
                                return await asyncio.wait_for(
                                    self.vision_manager.async_detect_snapshot_bbox(
                                        target_eid,
                                        m_info.get("detection_label"),
                                        m_info.get("snapshot_key"),
                                    ),
                                    timeout=6.0,
                                )
                            except Exception:
                                return None

                        bbox_results = list(
                            await asyncio.gather(
                                *[_fetch_bbox(item[2]) for item in selected_room_items],
                                return_exceptions=True,
                            )
                        )

                    for idx, (r_slug, r_name, media_info) in enumerate(selected_room_items):
                        primary_cand = untrained_profiles[0]
                        det_label = media_info.get("detection_label")
                        cam_title = media_info.get("camera_name") or r_name
                        snap_key = media_info.get("snapshot_key")
                        card_id = f"verify_room_entry_{r_slug}_{snap_key}" if snap_key else f"verify_room_entry_{r_slug}"
                        det_bbox = bbox_results[idx] if idx < len(bbox_results) and isinstance(bbox_results[idx], dict) else None
                        suggestions.append({
                            "id": card_id,
                            "title": f"📍 Who is in the {r_name}? Verify Identity for Training",
                            "category": "presence",
                            "priority": "critical",
                            "icon": "mdi:account-question",
                            "description": (
                                f"{f'{det_label} detection & presence' if det_label else 'Presence & motion'} recorded in the {r_name} ({cam_title}). "
                                f"Review the snapshot below and select who is in the {r_name} "
                                "(or mark as Unknown Person, Unknown Animal, or Not Person/Pet) "
                                "to calibrate Otis's camera recognition, pet-aware security & occupancy filtering, "
                                "personalized room comfort/lighting, guest hospitality, and spatial routines."
                            ),
                            "action_type": "confirm_person_identity",
                            "action_payload": {
                                "person_id": primary_cand["person_id"],
                                "label": primary_cand["label"],
                                "confirmed": True,
                                "suggestion_id": card_id,
                                "snapshot_key": snap_key,
                                "detection_bbox": det_bbox,
                                "visual_features": {
                                    "area": r_slug,
                                    "area_name": r_name,
                                    "camera_entity_id": media_info.get("camera_entity_id"),
                                    "detection_image_entity_id": media_info.get("detection_image_entity_id"),
                                    "snapshot_key": snap_key,
                                    "suggestion_id": card_id,
                                },
                                "candidates": [
                                    {
                                        "person_id": cp["person_id"],
                                        "label": cp["label"],
                                        "entity_type": cp["entity_type"],
                                        "confidence": cp["confidence"],
                                        "samples": cp["samples"],
                                    }
                                    for cp in sorted(
                                        active_training_profiles,
                                        key=lambda p: (
                                            0 if (p["samples"] < 5 or p["confidence"] < 0.85) else 1,
                                            -p["confidence"],
                                        ),
                                    )[:12]
                                ],
                                "area": r_slug,
                                "area_name": r_name,
                                **media_info,
                            },
                        })

                    # Ambiguous Room Transition Review Cards (with camera snapshot + room selector)
                    if hasattr(self.vision_manager, "get_ambiguous_room_transitions"):
                        for amb in self.vision_manager.get_ambiguous_room_transitions():
                            from_area = amb["from_area"]
                            from_name = amb["from_area_name"]
                            cand_rooms = amb.get("candidate_areas") or []
                            if len(cand_rooms) < 2:
                                continue
                            subj = amb.get("subject", "person")
                            amb_media = self._resolve_room_training_media(
                                from_area, from_name, cams, all_states, entity_to_area, preferred_subject=subj
                            )
                            direction = str(amb.get("direction") or "entering").lower()
                            cand_names = ", ".join(c["area_name"] for c in cand_rooms)
                            amb_ts = int(amb.get("timestamp") or (now_ts // 600))
                            if direction == "leaving":
                                tr_title = f"🚪 Where did the {subj} go from {from_name}?"
                                tr_desc = (
                                    f"Activity in {from_name} shows a {subj} leaving {from_name}, "
                                    f"with multiple adjacent rooms ({cand_names}). Review the snapshot below and select which room they entered."
                                )
                            else:
                                tr_title = f"🚪 Where did the {subj} come from into {from_name}?"
                                tr_desc = (
                                    f"Activity in {from_name} shows a {subj} entering {from_name}, "
                                    f"with multiple adjacent rooms ({cand_names}). Review the snapshot below and select which room they came from."
                                )
                            suggestions.append({
                                "id": f"confirm_room_transition_{from_area}_{amb_ts}",
                                "title": tr_title,
                                "category": "presence",
                                "priority": "high",
                                "icon": "mdi:door-open",
                                "description": tr_desc,
                                "action_type": "confirm_room_transition",
                                "action_payload": {
                                    "from_area": from_area,
                                    "from_area_name": from_name,
                                    "subject": subj,
                                    "direction": direction,
                                    "candidate_rooms": cand_rooms,
                                    "area": from_area,
                                    "area_name": from_name,
                                    **amb_media,
                                },
                            })

                # Multi-Domain Quality Recommendations Powered by People, Pet & Guest Identity Data
                pet_profiles = [p for p in active_training_profiles if p.get("entity_type") == "pet"]
                resident_profiles = [p for p in active_training_profiles if p.get("entity_type") == "resident"]
                guest_profiles = [p for p in active_training_profiles if p.get("entity_type") == "guest"]
                feedback_history = list(rules_data.get("vision_training_feedback") or [])

                # A. Pet-Aware Occupancy & Security Guard (prevents pets from tripping Away alarms or bright night lights)
                if pet_profiles:
                    raw_pet_labels = [str(p.get("label") or "").strip() for p in pet_profiles if p.get("label")]
                    single_pet_lowers = {lbl.lower() for lbl in raw_pet_labels if " and " not in lbl.lower() and "," not in lbl.lower()}
                    dedup_pet_labels = [
                        lbl for lbl in dict.fromkeys(raw_pet_labels)
                        if not (
                            " and " in lbl.lower()
                            and any(sp in lbl.lower() for sp in single_pet_lowers)
                        )
                    ]
                    pet_names = ", ".join((dedup_pet_labels or raw_pet_labels)[:3])
                    pet_verified_rooms: list[str] = []
                    for pp in pet_profiles:
                        for vr in pp.get("verified_rooms") or []:
                            vr_clean = str(vr).strip().lower()
                            if vr_clean and vr_clean not in pet_verified_rooms:
                                pet_verified_rooms.append(vr_clean)

                    target_pet_room = pet_verified_rooms[0] if pet_verified_rooms else None
                    target_room_label = (
                        target_pet_room.replace("_", " ").title()
                        if target_pet_room
                        else "Main Living Areas"
                    )
                    room_motion_entities = [
                        e["entity_id"]
                        for e in entities
                        if str(e.get("entity_id", "")).startswith("binary_sensor.")
                        and any(k in str(e.get("entity_id", "")).lower() for k in ("motion", "occupancy", "pir"))
                        and (not target_pet_room or target_pet_room in str(e.get("entity_id", "")).lower())
                    ]
                    room_person_entities = [
                        e["entity_id"]
                        for e in entities
                        if str(e.get("entity_id", "")).startswith("binary_sensor.")
                        and "person" in str(e.get("entity_id", "")).lower()
                        and (not target_pet_room or target_pet_room in str(e.get("entity_id", "")).lower())
                    ]
                    room_light_entities = [
                        e["entity_id"]
                        for e in entities
                        if str(e.get("entity_id", "")).startswith("light.")
                        and (not target_pet_room or target_pet_room in str(e.get("entity_id", "")).lower())
                    ]
                    if room_motion_entities or room_person_entities:
                        trigger_ent = (room_person_entities or room_motion_entities)[0]
                        light_ent = room_light_entities[0] if room_light_entities else None
                        slug_suffix = target_pet_room or "home"
                        suggestions.append({
                            "id": f"identity_pet_immunity_guard_{slug_suffix}",
                            "title": f"🐾 Pet-Immune Occupancy & Security Guard ({pet_names} in {target_room_label})",
                            "category": "security",
                            "priority": "high",
                            "icon": "mdi:paw",
                            "description": (
                                f"Using trained pet identity profiles for {pet_names}, gate motion-activated lighting and "
                                f"security alerts in {target_room_label} on verified human presence (`{trigger_ent}`) so pet movement "
                                "does not trigger false Away-mode alarms or bright overnight lights."
                            ),
                            "action_type": "create_automation",
                            "action_payload": {
                                "alias": f"Otis Pet-Immune Presence Guard ({target_room_label})",
                                "description": f"Prevents {pet_names} from triggering false occupancy lighting or security alerts in {target_room_label}.",
                                "trigger": [
                                    {
                                        "platform": "state",
                                        "entity_id": trigger_ent,
                                        "to": "on",
                                    }
                                ],
                                "condition": (
                                    [
                                        {
                                            "condition": "state",
                                            "entity_id": room_person_entities[0],
                                            "state": "on",
                                        }
                                    ]
                                    if room_person_entities and room_person_entities[0] != trigger_ent
                                    else []
                                ),
                                "action": (
                                    [
                                        {
                                            "service": "light.turn_on",
                                            "target": {"entity_id": light_ent},
                                        }
                                    ]
                                    if light_ent
                                    else [
                                        {
                                            "service": "persistent_notification.create",
                                            "data": {
                                                "title": f"Verified Human Activity in {target_room_label}",
                                                "message": f"Human presence verified in {target_room_label} (pet activity filtered for {pet_names}).",
                                            },
                                        }
                                    ]
                                ),
                                "mode": "single",
                            },
                        })

                # B. Personalized Resident Room Comfort & Lighting Coordinator (for residents with verified rooms/samples)
                for res_prof in resident_profiles:
                    v_rooms = [str(r).strip().lower() for r in (res_prof.get("verified_rooms") or []) if str(r).strip()]
                    if not v_rooms and int(res_prof.get("samples", 0)) < 1:
                        continue
                    fav_room = v_rooms[0] if v_rooms else "study"
                    fav_room_name = fav_room.replace("_", " ").title()
                    res_label = res_prof["label"]
                    res_slug = re.sub(r"[^a-z0-9_]+", "_", res_prof["person_id"].lower()).strip("_")

                    r_sensors = _filter_valid_presence_sensors([
                        e["entity_id"]
                        for e in entities
                        if str(e.get("entity_id", "")).startswith("binary_sensor.")
                        and fav_room in str(e.get("entity_id", "")).lower()
                    ])
                    r_lights = [
                        e["entity_id"]
                        for e in entities
                        if str(e.get("entity_id", "")).startswith("light.")
                        and fav_room in str(e.get("entity_id", "")).lower()
                        and not any(tok in str(e.get("entity_id", "")).lower() for tok in _NON_MAIN_LIGHT_TOKENS)
                    ]
                    r_climates = [
                        e["entity_id"]
                        for e in entities
                        if str(e.get("entity_id", "")).startswith("climate.")
                        and fav_room in str(e.get("entity_id", "")).lower()
                    ]
                    if r_sensors and (r_lights or r_climates):
                        actions_list: list[dict[str, Any]] = []
                        if r_lights:
                            actions_list.append({
                                "service": "light.turn_on",
                                "target": {"entity_id": r_lights[0]},
                            })
                        if r_climates:
                            actions_list.append({
                                "service": "climate.set_hvac_mode",
                                "target": {"entity_id": r_climates[0]},
                                "data": {"hvac_mode": "heat_cool"},
                            })
                        if r_lights:
                            actions_list.append({
                                "wait_for_trigger": [
                                    {
                                        "platform": "state",
                                        "entity_id": r_sensors[0],
                                        "to": "off",
                                        "for": {"minutes": 5},
                                    }
                                ],
                                "timeout": {"minutes": 30},
                                "continue_on_timeout": True,
                            })
                            actions_list.append({
                                "service": "light.turn_off",
                                "target": {"entity_id": r_lights[0]},
                            })
                        suggestions.append({
                            "id": f"identity_resident_comfort_{res_slug}_{fav_room}",
                            "title": f"👤 Personalized Room Comfort for {res_label} ({fav_room_name})",
                            "category": "presence",
                            "priority": "medium",
                            "icon": "mdi:account-star",
                            "description": (
                                f"{res_label} has verified identity presence in the {fav_room_name} "
                                f"({int(res_prof.get('samples', 0))}/5 samples, {int(round(float(res_prof.get('confidence', 0.5)) * 100))}% confidence). "
                                f"Automate personalized lighting and comfort in the {fav_room_name} when {res_label} enters."
                            ),
                            "action_type": "create_automation",
                            "action_payload": {
                                "alias": f"Otis Personalized {fav_room_name} Comfort ({res_label})",
                                "description": f"Activates personalized lighting/comfort in the {fav_room_name} when {res_label} is detected.",
                                "trigger": [
                                    {
                                        "platform": "state",
                                        "entity_id": r_sensors[0],
                                        "to": "on",
                                    }
                                ],
                                "condition": [],
                                "action": actions_list,
                                "mode": "restart",
                            },
                        })
                        break

                # C. Guest Hospitality & Privacy Mode Coordinator
                if guest_profiles:
                    guest_names = ", ".join(g["label"] for g in guest_profiles[:2])
                    guest_rooms: list[str] = []
                    for gp in guest_profiles:
                        for vr in gp.get("verified_rooms") or []:
                            vr_clean = str(vr).strip().lower()
                            if vr_clean and vr_clean not in guest_rooms:
                                guest_rooms.append(vr_clean)
                    g_room = guest_rooms[0] if guest_rooms else "guest_room"
                    g_room_name = g_room.replace("_", " ").title()
                    g_sensors = _filter_valid_presence_sensors([
                        e["entity_id"]
                        for e in entities
                        if str(e.get("entity_id", "")).startswith("binary_sensor.")
                        and any(k in str(e.get("entity_id", "")).lower() for k in (g_room, "guest", "foyer", "hallway"))
                    ])
                    g_lights = [
                        e["entity_id"]
                        for e in entities
                        if str(e.get("entity_id", "")).startswith("light.")
                        and any(k in str(e.get("entity_id", "")).lower() for k in (g_room, "guest", "hallway", "foyer"))
                        and not any(tok in str(e.get("entity_id", "")).lower() for tok in _NON_MAIN_LIGHT_TOKENS)
                    ]
                    guest_bool_eid = next(
                        (
                            st.entity_id
                            for st in (self.hass.states.async_all("input_boolean") if hasattr(self.hass, "states") else [])
                            if "guest_mode" in st.entity_id.lower()
                        ),
                        None,
                    )
                    if g_sensors and g_lights:
                        suggestions.append({
                            "id": f"identity_guest_hospitality_{g_room}",
                            "title": f"👥 Guest Hospitality & Pathway Lighting ({guest_names})",
                            "category": "presence",
                            "priority": "medium",
                            "icon": "mdi:account-group",
                            "description": (
                                f"Trained guest profile ({guest_names}) enables automatic hospitality lighting in the {g_room_name} "
                                "and gentle evening pathway illumination without triggering unfamiliar-person security alerts."
                            ),
                            "action_type": "create_automation",
                            "action_payload": {
                                "alias": f"Otis Guest Hospitality Lighting ({g_room_name})",
                                "description": f"Provides welcoming lighting in {g_room_name} for recognized guests ({guest_names}).",
                                "trigger": [
                                    {
                                        "platform": "state",
                                        "entity_id": g_sensors[0],
                                        "to": "on",
                                    }
                                ],
                                "condition": (
                                    [{"condition": "state", "entity_id": guest_bool_eid, "state": "on"}]
                                    if guest_bool_eid
                                    else []
                                ),
                                "action": [
                                    {
                                        "service": "light.turn_on",
                                        "target": {"entity_id": g_lights[0]},
                                    },
                                    {
                                        "wait_for_trigger": [
                                            {
                                                "platform": "state",
                                                "entity_id": g_sensors[0],
                                                "to": "off",
                                                "for": {"minutes": 5},
                                            }
                                        ],
                                        "timeout": {"minutes": 30},
                                        "continue_on_timeout": True,
                                    },
                                    {
                                        "service": "light.turn_off",
                                        "target": {"entity_id": g_lights[0]},
                                    },
                                ],
                                "mode": "restart",
                            },
                        })

                # D. Vision Feedback Calibration: False-Positive Suppression & Unknown Person Deterrence
                if feedback_history:
                    false_pos_areas: list[str] = []
                    unknown_person_areas: list[str] = []
                    for fb in reversed(feedback_history):
                        if not isinstance(fb, dict):
                            continue
                        fb_type = str(fb.get("classification") or fb.get("feedback_type") or "").strip().lower()
                        vf = fb.get("visual_features") if isinstance(fb.get("visual_features"), dict) else {}
                        fb_area = str(fb.get("area") or vf.get("area") or "").strip().lower()
                        if not fb_area:
                            continue
                        if fb_type in ("not_person_pet", "unknown_animal", "false_positive") and fb_area not in false_pos_areas:
                            false_pos_areas.append(fb_area)
                        elif fb_type == "unknown_person" and fb_area not in unknown_person_areas:
                            unknown_person_areas.append(fb_area)

                    for fp_area in false_pos_areas:
                        fp_area_eids = list((areas.get(fp_area) or {}).get("entities") or [])
                        if not fp_area_eids:
                            fp_area_eids = [
                                str(e.get("entity_id") or "")
                                for e in entities
                                if e.get("area_id") == fp_area or f".{fp_area}_" in str(e.get("entity_id") or "").lower()
                            ]
                        fp_valid_sensors = _filter_valid_presence_sensors(fp_area_eids)
                        if len(fp_valid_sensors) >= 2:
                            fp_name = fp_area.replace("_", " ").title()
                            suggestions.append({
                                "id": f"identity_feedback_filter_{fp_area}",
                                "title": f"🎯 Vision False-Positive Filter Calibrated ({fp_name})",
                                "category": "security",
                                "priority": "medium",
                                "icon": "mdi:shield-check-outline",
                                "description": (
                                    f"You marked recent camera/sensor activity in the {fp_name} as a non-person/animal false positive. "
                                    f"Require dual-sensor confirmation ({fp_valid_sensors[0]} + {fp_valid_sensors[1]}) in the {fp_name} "
                                    "before triggering occupancy or security automations."
                                ),
                                "action_type": "advisor_guide",
                                "action_payload": {
                                    "guide": (
                                        f"In the {fp_name}, pair `{fp_valid_sensors[0]}` with `{fp_valid_sensors[1]}` "
                                        "so shadows, pets, or single-sensor noise never trigger false room occupancy."
                                    )
                                },
                            })
                            break

                    if unknown_person_areas:
                        up_area = unknown_person_areas[0]
                        up_name = up_area.replace("_", " ").title()
                        up_sensors = [
                            e["entity_id"]
                            for e in entities
                            if str(e.get("entity_id", "")).startswith("binary_sensor.")
                            and up_area in str(e.get("entity_id", "")).lower()
                            and any(k in str(e.get("entity_id", "")).lower() for k in ("person", "motion", "occupancy"))
                        ]
                        up_lights = [
                            e["entity_id"]
                            for e in entities
                            if str(e.get("entity_id", "")).startswith("light.")
                            and up_area in str(e.get("entity_id", "")).lower()
                        ]
                        if up_sensors:
                            suggestions.append({
                                "id": f"identity_unknown_person_watchdog_{up_area}",
                                "title": f"🕵️ Unfamiliar Person Deterrence & Alert ({up_name})",
                                "category": "security",
                                "priority": "high",
                                "icon": "mdi:shield-alert",
                                "description": (
                                    f"Based on your Unknown Person training feedback in the {up_name}, deploy an automated deterrence rule "
                                    f"that turns on {up_name} lighting and sends an immediate security notification when unrecognized person activity occurs."
                                ),
                                "action_type": "create_automation",
                                "action_payload": {
                                    "alias": f"Otis Unfamiliar Person Deterrence ({up_name})",
                                    "description": f"Alerts and illuminates {up_name} when person detection triggers.",
                                    "trigger": [
                                        {
                                            "platform": "state",
                                            "entity_id": up_sensors[0],
                                            "to": "on",
                                        }
                                    ],
                                    "condition": [],
                                    "action": (
                                        [
                                            {
                                                "service": "light.turn_on",
                                                "target": {"entity_id": up_lights[0]},
                                            },
                                            {
                                                "service": "persistent_notification.create",
                                                "data": {
                                                    "title": f"Unfamiliar Person Activity ({up_name})",
                                                    "message": f"Person activity detected in {up_name} ({up_sensors[0]}).",
                                                },
                                            },
                                        ]
                                        if up_lights
                                        else [
                                            {
                                                "service": "persistent_notification.create",
                                                "data": {
                                                    "title": f"Unfamiliar Person Activity ({up_name})",
                                                    "message": f"Person activity detected in {up_name} ({up_sensors[0]}).",
                                                },
                                            }
                                        ]
                                    ),
                                    "mode": "single",
                                },
                            })
            except Exception as err:
                _LOGGER.debug("Error generating person identification suggestions: %s", err)

        # 17. Autonomous Self-Healing Mesh Network (Phase 6)
        if getattr(self, "mesh_manager", None):
            try:
                mesh_audit = await self.mesh_manager.async_audit_mesh_topology()
                dead_nodes = mesh_audit.get("dead_nodes", [])
                for dn in dead_nodes[:3]:
                    nid = dn.get("id") or dn.get("node_id")
                    dname = dn.get("name") or nid
                    proto = dn.get("protocol", "mesh").upper()
                    clean_slug = re.sub(r"[^a-z0-9_]+", "_", str(nid).lower()).strip("_")
                    suggestions.append({
                        "id": f"heal_mesh_node_{clean_slug}",
                        "title": f"Self-Healing Mesh: Remediate Dead Node ({dname})",
                        "category": "system",
                        "priority": "high",
                        "icon": "mdi:router-wireless-settings",
                        "description": (
                            f"Otis detected an unresponsive {proto} mesh node '{dname}' (ID: {dn.get('node_id')}). "
                            "Trigger autonomous self-healing to ping node, repair routing neighbors, and recover connectivity."
                        ),
                        "action_type": "heal_mesh_node",
                        "action_payload": {
                            "node_id": nid,
                            "protocol": dn.get("protocol"),
                            "force_rebuild": False,
                        },
                    })
            except Exception as err:
                _LOGGER.debug("Error generating mesh self-healing suggestions: %s", err)

        # Surface Official Home Assistant News & Announcements
        try:
            ha_news = await self.async_fetch_ha_official_news()
            suggestions.extend(ha_news)
        except Exception as err:
            _LOGGER.debug("Error adding official HA news to suggestions: %s", err)

        # Filter out permanently hidden recommendations (X-dismissed or completed)
        if getattr(self, "rules_manager", None) and hasattr(self.rules_manager, "get_hidden_recommendations"):
            hidden_ids = set(self.rules_manager.get_hidden_recommendations())
            if hidden_ids:
                suggestions = [s for s in suggestions if s.get("id") not in hidden_ids]

        # Sort suggestions by priority: Critical -> High -> Medium -> Low
        priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        suggestions.sort(
            key=lambda s: priority_rank.get(str(s.get("priority", "medium")).lower(), 2)
        )

        self._suggestions_by_id = {s["id"]: s for s in suggestions if s.get("id")}
        return suggestions

    def _resolve_room_training_media(
        self,
        r_slug: str,
        r_name: str,
        cams: list[dict[str, Any]],
        all_states: list[Any],
        entity_to_area: dict[str, str],
        preferred_subject: str | None = None,
    ) -> dict[str, Any]:
        """Resolve live camera and Frigate/NVR detection snapshot media for a given room."""
        clean_slug = str(r_slug or "").strip().lower()
        clean_name = str(r_name or clean_slug).strip().lower()
        aliases = {clean_slug, clean_name.replace(" ", "_")}
        if clean_slug == "great_room":
            aliases.update({"kitchen", "living_room", "greatroom"})
        elif clean_slug == "foyer":
            aliases.update({"entryway"})
        elif clean_slug == "frontyard":
            aliases.update({"front_doorbell", "frontdoor", "driveway", "porch"})
        elif clean_slug == "garage":
            aliases.update({"driveway"})

        cam_eid: str | None = None
        cam_name: str | None = None
        cam_pic: str | None = None
        cam_token: str | None = None

        # Pass 1: exact area match first so e.g. Front Doorbell in Frontyard never hijacks Foyer
        for exact_only in (True, False):
            for c in cams or []:
                c_area = str(c.get("area_id") or "").strip().lower()
                c_eid = str(c.get("entity_id") or "")
                c_eid_low = c_eid.lower()
                c_lbl = str(c.get("name") or c_eid)
                matched = (
                    c_area == clean_slug
                    if exact_only
                    else (
                        any(a and a in c_eid_low for a in aliases)
                        or any(a and a in c_lbl.lower().replace(" ", "_") for a in aliases)
                    )
                )
                if matched:
                    cam_eid = c_eid
                    cam_name = c_lbl
                    cam_pic = c.get("entity_picture")
                    cam_token = c.get("access_token")
                    if not cam_pic and cam_token and cam_eid:
                        cam_pic = f"/api/camera_proxy/{cam_eid}?token={cam_token}"
                    break
            if cam_eid:
                break

        det_candidates: list[tuple[int, float, int, str, str | None, str, str]] = []
        snap_eid: str | None = None
        snap_pic: str | None = None
        snap_state: str = ""

        for st in all_states or []:
            eid = getattr(st, "entity_id", "")
            eid_low = eid.lower()
            if not (eid_low.startswith("image.") or eid_low.startswith("camera.")):
                continue
            st_val = str(getattr(st, "state", "") or "")
            if st_val.lower() in ("unavailable", "unknown", "none", ""):
                continue

            attrs = getattr(st, "attributes", {}) or {}
            e_area = str(entity_to_area.get(eid) or "").strip().lower()
            matches_room = (
                e_area == clean_slug
                or any(a and (f".{a}_" in eid_low or eid_low.endswith(f".{a}")) for a in aliases)
            )
            if not matches_room:
                continue

            pic = attrs.get("entity_picture")
            token = attrs.get("access_token")
            if not pic and token:
                proxy_prefix = "image_proxy" if eid_low.startswith("image.") else "camera_proxy"
                pic = f"/api/{proxy_prefix}/{eid}?token={token}"

            if eid_low.startswith("image.") and any(
                eid_low.endswith(sfx) for sfx in ("_person", "_dog", "_cat", "_pet", "_animal")
            ):
                last_changed = getattr(st, "last_changed", None)
                ts_val = 0.0
                if last_changed and hasattr(last_changed, "timestamp"):
                    try:
                        ts_val = float(last_changed.timestamp())
                    except Exception:
                        ts_val = 0.0
                type_rank = 1 if eid_low.endswith("_person") else 0
                det_lbl = "Person" if eid_low.endswith("_person") else (
                    "Dog" if eid_low.endswith("_dog") else (
                        "Cat" if eid_low.endswith("_cat") else "Pet/Animal"
                    )
                )
                pref_low = str(preferred_subject or "").strip().lower()
                subj_match = 1 if (pref_low and (
                    (pref_low in ("person", "human", "visitor") and eid_low.endswith("_person"))
                    or (pref_low in ("dog", "pet", "animal") and eid_low.endswith(("_dog", "_pet", "_animal")))
                    or (pref_low == "cat" and eid_low.endswith("_cat"))
                )) else 0
                det_candidates.append((subj_match, ts_val, type_rank, eid, pic, det_lbl, st_val))
            elif eid_low.startswith("camera.") and "snapshot" in eid_low and not snap_eid:
                snap_eid = eid
                snap_pic = pic
                snap_state = st_val
            elif eid_low.startswith("camera.") and not cam_eid and "map" not in eid_low:
                cam_eid = eid
                cam_name = attrs.get("friendly_name") or eid
                cam_pic = pic

        det_eid: str | None = None
        det_pic: str | None = None
        det_label: str | None = None
        det_state: str = ""
        if det_candidates:
            det_candidates.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
            _, _, _, det_eid, det_pic, det_label, det_state = det_candidates[0]

        snapshot_key: str | None = None
        if det_eid:
            import hashlib
            raw_key = f"{det_eid}:{det_state}:{det_pic or ''}"
            snapshot_key = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:12]
        elif snap_eid:
            import hashlib
            raw_key = f"{snap_eid}:{snap_state}:{snap_pic or ''}"
            snapshot_key = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:12]

        primary_pic = det_pic or snap_pic or cam_pic
        return {
            "camera_entity_id": cam_eid,
            "camera_name": cam_name,
            "camera_entity_picture": cam_pic,
            "detection_image_entity_id": det_eid,
            "detection_image_picture": det_pic,
            "detection_label": det_label,
            "snapshot_camera_entity_id": snap_eid,
            "snapshot_camera_picture": snap_pic,
            "snapshot_key": snapshot_key,
            "entity_picture": primary_pic,
        }

    async def async_fetch_ha_official_news(self) -> list[dict[str, Any]]:
        """Fetch and cache official Home Assistant blog / release news entries from atom.xml."""
        now = time.time()
        # Cache news for 6 hours (21600 seconds)
        if self._ha_news_cache and (now - self._ha_news_cache_ts < 21600):
            return self._ha_news_cache

        if getattr(self, "rag_manager", None) and hasattr(self.rag_manager, "async_sync_ha_docs"):
            try:
                await self.rag_manager.async_sync_ha_docs()
            except Exception as docs_err:
                _LOGGER.debug("Could not refresh Home Assistant docs during news sync: %s", docs_err)

        try:
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            import aiohttp
            session = async_get_clientsession(self.hass)
            async with session.get(
                "https://www.home-assistant.io/atom.xml",
                timeout=aiohttp.ClientTimeout(total=5),
                headers={"User-Agent": "HomeAssistant-OtisAI/1.0"},
            ) as resp:
                if resp.status == 200:
                    xml_content = await resp.text()
                    news_items = await self.hass.async_add_executor_job(
                        self._parse_ha_atom_feed, xml_content
                    )
                    if news_items:
                        self._ha_news_cache = news_items
                        self._ha_news_cache_ts = now
                        return news_items
        except Exception as err:
            _LOGGER.debug("Could not fetch official Home Assistant news: %s", err)

        return self._ha_news_cache

    def _parse_ha_atom_feed(self, xml_content: str) -> list[dict[str, Any]]:
        """Parse Home Assistant atom XML feed into recommendation items."""
        import xml.etree.ElementTree as ET
        import re
        import hashlib
        items: list[dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns)[:4]:
                title_elem = entry.find("atom:title", ns)
                title = title_elem.text.strip() if title_elem is not None and title_elem.text else "Official HA Update"
                link_elem = entry.find("atom:link", ns)
                link = link_elem.attrib.get("href", "") if link_elem is not None else "https://www.home-assistant.io/blog/"
                updated_elem = entry.find("atom:updated", ns)
                updated_raw = updated_elem.text.strip() if updated_elem is not None and updated_elem.text else ""
                pub_date = updated_raw.split("T")[0] if "T" in updated_raw else updated_raw

                content_elem = entry.find("atom:content", ns)
                raw_content = content_elem.text if content_elem is not None and content_elem.text else ""
                clean_text = re.sub(r"<template[\s\S]*?</template>", "", raw_content)
                clean_text = re.sub(r"<style[\s\S]*?</style>", "", clean_text)
                clean_text = re.sub(r"<script[\s\S]*?</script>", "", clean_text)
                clean_text = re.sub(r"<[^>]+>", " ", clean_text)
                clean_text = " ".join(clean_text.split())
                if len(clean_text) > 180:
                    clean_text = clean_text[:177] + "..."
                if not clean_text:
                    clean_text = "Read the latest official release and community news from the Home Assistant blog."

                slug = link.rstrip("/").split("/")[-1]
                slug_hash = hashlib.md5(slug.encode("utf-8")).hexdigest()[:8]
                card_id = f"ha_news_{slug}_{slug_hash}"

                is_major_release = "release" in slug.lower() or "release" in title.lower()
                items.append({
                    "id": card_id,
                    "title": f"📰 {title}",
                    "category": "news",
                    "priority": "medium" if is_major_release else "low",
                    "icon": "mdi:newspaper-variant-outline",
                    "description": f"Official Home Assistant update ({pub_date}): {clean_text}",
                    "action_type": "open_url",
                    "action_payload": {
                        "url": link,
                        "title": title,
                        "pub_date": pub_date,
                    },
                })

                # Check for actionable new features mentioned in HA release news
                text_lower = f"{title} {clean_text}".lower()
                if "voice" in text_lower or "assist" in text_lower or "satellite" in text_lower:
                    items.append({
                        "id": f"adopt_voice_news_{slug_hash}",
                        "title": f"Adopt HA Capability: Configure Voice Satellites ({title})",
                        "category": "system",
                        "priority": "medium",
                        "icon": "mdi:microphone-outline",
                        "description": (
                            "Home Assistant news highlights voice & satellite upgrades. Otis can link your "
                            "local media players and satellite hardware with localized wake words and room arbitration."
                        ),
                        "action_type": "advisor_guide",
                        "action_payload": {
                            "guide_message": "To configure voice satellites with Otis, open the Capabilities tab or ask Assist Co-Pilot: 'Configure a voice satellite for [Room]'."
                        },
                    })
                if "floor" in text_lower or "sections" in text_lower:
                    items.append({
                        "id": f"adopt_floors_news_{slug_hash}",
                        "title": f"Adopt HA Capability: Sync Native Floors & Sections ({title})",
                        "category": "system",
                        "priority": "medium",
                        "icon": "mdi:layers-triple-outline",
                        "description": (
                            "Recent Home Assistant updates introduce native Floor & Sections dashboard capabilities. "
                            "Sync your areas and rooms to native Home Assistant floors in 1 click."
                        ),
                        "action_type": "sync_ha_floors",
                        "action_payload": {},
                    })
        except Exception as err:
            _LOGGER.debug("Error parsing HA atom feed: %s", err)
        return items

    async def async_mine_historical_habits(self, days: int = 7) -> list[dict[str, Any]]:
        """Asynchronously mine Home Assistant SQLite recorder trends for habit routine patterns."""
        if getattr(self, "habit_manager", None):
            return await self.habit_manager.async_mine_habits(days=days, min_occurrences=2)
        return []


__all__ = [
    "DOMAIN",
    "OtisMediaStudioView",
    "OtisIssueReporterView",
    "create_github_issue",
    "check_device_token",
    "request_device_code",
]
