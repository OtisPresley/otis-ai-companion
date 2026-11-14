"""Unit tests for HACS Default Catalog PR 13059 Compliance: Phase 2 and Phase 3."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.otis_ai import (
    DOMAIN,
    MAX_UPLOAD_SIZE_BYTES,
    MAX_UPLOAD_CLIPS,
    OtisWalkthroughUploadView,
    OtisIssueReporterView,
    _register_admin_service,
    Unauthorized,
)
from custom_components.otis_ai.floorplan_parser import (
    DEFAULT_OUTPUT_SVG_PATH,
    FloorplanParser,
)
from custom_components.otis_ai.local_llm import (
    ALLOWED_TOOL_NAMES,
    ALLOWED_SERVICE_DOMAINS,
    LocalLLMManager,
)


@pytest.fixture(autouse=True)
def mock_web_response():
    with patch("aiohttp.web.Response", side_effect=lambda status=200, text="": MagicMock(status=status, text=text)):
        yield


# ==============================================================================
# PHASE 2: UPLOAD LIMITS & FILE PATH CONTAINMENT
# ==============================================================================

def test_walkthrough_upload_view_requires_auth_and_constants():
    """Verify OtisWalkthroughUploadView enforces authentication and upload ceilings."""
    hass = MagicMock()
    fp = MagicMock()
    eng = MagicMock()
    view = OtisWalkthroughUploadView(hass, fp, eng)
    assert view.requires_auth is True
    assert MAX_UPLOAD_SIZE_BYTES == 3 * 1024 * 1024 * 1024
    assert MAX_UPLOAD_CLIPS == 5


def test_walkthrough_upload_content_length_exceeded():
    """Verify that requests with Content-Length > 3GB are rejected with HTTP 413."""
    hass = MagicMock()
    fp = MagicMock()
    eng = MagicMock()
    view = OtisWalkthroughUploadView(hass, fp, eng)

    req = MagicMock()
    req.content_length = MAX_UPLOAD_SIZE_BYTES + 1
    resp = asyncio.run(view.post(req))
    assert resp.status == 413
    assert "Upload payload too large" in resp.text


def test_walkthrough_upload_clip_count_exceeded():
    """Verify that multipart uploads with > 5 video clips are rejected with HTTP 413."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw) if callable(fn) else None)
    fp = MagicMock()
    fp.cleanup_previous_uploads = MagicMock()
    eng = MagicMock()
    view = OtisWalkthroughUploadView(hass, fp, eng, media_dir="/tmp/test_otis_media")

    # Mock multipart stream returning 6 file fields
    mock_fields = []
    for i in range(6):
        field = AsyncMock()
        field.name = "file"
        field.read_chunk = AsyncMock(side_effect=[b"chunk", b""])
        mock_fields.append(field)
    mock_fields.append(None)

    mock_reader = AsyncMock()
    mock_reader.next = AsyncMock(side_effect=mock_fields)

    req = MagicMock()
    req.content_length = 1000
    req.content_type = "multipart/form-data"
    req.multipart = AsyncMock(return_value=mock_reader)

    with patch("builtins.open", MagicMock()):
        resp = asyncio.run(view.post(req))
    assert resp.status == 413
    assert "Maximum allowed file count exceeded" in resp.text


def test_walkthrough_upload_aggregate_size_stream_exceeded():
    """Verify that stream chunks exceeding 3GB aggregate are rejected with HTTP 413."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw) if callable(fn) else None)
    fp = MagicMock()
    fp.cleanup_previous_uploads = MagicMock()
    eng = MagicMock()
    view = OtisWalkthroughUploadView(hass, fp, eng, media_dir="/tmp/test_otis_media")

    field = AsyncMock()
    field.name = "file"
    # Return two massive chunks that together exceed MAX_UPLOAD_SIZE_BYTES
    massive_chunk = b"x" * 1024
    field.read_chunk = AsyncMock(side_effect=[massive_chunk, massive_chunk, b""])

    mock_reader = AsyncMock()
    mock_reader.next = AsyncMock(side_effect=[field, None])

    req = MagicMock()
    req.content_length = None
    req.content_type = "multipart/form-data"
    req.multipart = AsyncMock(return_value=mock_reader)

    with patch("custom_components.otis_ai.MAX_UPLOAD_SIZE_BYTES", 1500), \
         patch("builtins.open", MagicMock()):
        resp = asyncio.run(view.post(req))
    assert resp.status == 413
    assert "Aggregate upload stream exceeded limit" in resp.text


def test_walkthrough_upload_empty_rejection():
    """Verify that an upload with no video files is rejected with HTTP 400."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw) if callable(fn) else None)
    fp = MagicMock()
    fp.cleanup_previous_uploads = MagicMock()
    eng = MagicMock()
    view = OtisWalkthroughUploadView(hass, fp, eng, media_dir="/tmp/test_otis_media")

    # Non-file field
    field = AsyncMock()
    field.name = "spoken_order"
    field.text = AsyncMock(return_value="living_room, kitchen")

    mock_reader = AsyncMock()
    mock_reader.next = AsyncMock(side_effect=[field, None])

    req = MagicMock()
    req.content_length = 50
    req.content_type = "multipart/form-data"
    req.multipart = AsyncMock(return_value=mock_reader)

    resp = asyncio.run(view.post(req))
    assert resp.status == 400
    assert "No video walkthrough files were provided" in resp.text


def test_floorplan_parser_sanitize_svg_path():
    """Verify FloorplanParser strictly confines paths to managed storage, blocking www and traversal."""
    hass = MagicMock()
    fp = FloorplanParser(hass)

    # Normal default
    assert fp._sanitize_svg_path(None) == DEFAULT_OUTPUT_SVG_PATH
    assert fp._sanitize_svg_path("") == DEFAULT_OUTPUT_SVG_PATH

    # Disallow path traversal
    assert fp._sanitize_svg_path("../../../etc/passwd") == DEFAULT_OUTPUT_SVG_PATH
    assert fp._sanitize_svg_path("media/../../secret.svg") == DEFAULT_OUTPUT_SVG_PATH

    # Disallow writing to www
    assert fp._sanitize_svg_path("www/otis_floorplan.svg") == DEFAULT_OUTPUT_SVG_PATH
    assert fp._sanitize_svg_path("/config/www/otis_floorplan.svg") == DEFAULT_OUTPUT_SVG_PATH
    assert fp._sanitize_svg_path("www/sub/path.svg") == DEFAULT_OUTPUT_SVG_PATH

    # Valid internal paths remain confined
    valid_path = ".storage/otis_ai/media/custom_layout.svg"
    assert fp._sanitize_svg_path(valid_path) == valid_path


# ==============================================================================
# PHASE 3: ACCESS CONTROL & PERMISSIONS
# ==============================================================================

def test_register_admin_service_enforces_admin():
    """Verify _register_admin_service raises Unauthorized for non-admin callers."""
    hass = MagicMock()
    registered = {}

    def mock_reg(domain, service, handler, **kwargs):
        registered[(domain, service)] = handler
    hass.services.async_register = mock_reg

    test_handler = AsyncMock(return_value={"success": True})
    _register_admin_service(hass, DOMAIN, "test_admin_service", test_handler)
    assert (DOMAIN, "test_admin_service") in registered

    admin_guard = registered[(DOMAIN, "test_admin_service")]

    # 1. Non-admin user call must raise Unauthorized
    non_admin_user = MagicMock()
    non_admin_user.is_admin = False
    hass.auth.async_get_user = MagicMock(return_value=non_admin_user)

    call_non_admin = MagicMock()
    call_non_admin.context.user_id = "user_non_admin"

    with pytest.raises(Unauthorized):
        asyncio.run(admin_guard(call_non_admin))
    test_handler.assert_not_called()

    # 2. Admin user call succeeds
    admin_user = MagicMock()
    admin_user.is_admin = True
    hass.auth.async_get_user = MagicMock(return_value=admin_user)

    call_admin = MagicMock()
    call_admin.context.user_id = "user_admin"

    res = asyncio.run(admin_guard(call_admin))
    assert res == {"success": True}
    test_handler.assert_called_once_with(call_admin)


def test_apply_suggestion_rejects_arbitrary_untracked_action():
    """Verify apply_suggestion rejects arbitrary caller actions when suggestion is not tracked."""
    from custom_components.otis_ai import async_setup_entry

    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock()
    hass.config.path = MagicMock(return_value="/tmp/test_storage")
    registered_services = {}
    def mock_reg(d, s, h, **kw):
        registered_services[(d, s)] = h
    hass.services.async_register = mock_reg

    entry = MagicMock()
    entry.entry_id = "test_entry_audit"
    entry.data = {}
    entry.options = {}

    asyncio.run(async_setup_entry(hass, entry))
    apply_handler = registered_services[(DOMAIN, "apply_suggestion")]

    # Mock engine capability map with NO suggestions
    engine = MagicMock()
    engine.get_cached_suggestion = MagicMock(return_value=None)
    engine.async_build_capability_map = AsyncMock(return_value={"proactive_suggestions": []})
    hass.data[DOMAIN][entry.entry_id]["engine"] = engine

    # Untracked arbitrary action attempt
    call = MagicMock()
    call.data = {
        "suggestion_id": "untracked_hacker_action",
        "action_type": "call_service",
        "action_payload": {"service": "homeassistant.restart"},
    }

    res = asyncio.run(apply_handler(call))
    assert res["success"] is False
    assert "not found or already resolved" in res["error"]


def test_execute_tool_plan_allowlist_and_context_propagation():
    """Verify async_execute_tool_plan enforces ALLOWED_TOOL_NAMES, ALLOWED_SERVICE_DOMAINS, and passes context."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    mgr = LocalLLMManager(hass)

    test_context = MagicMock()
    assert len(ALLOWED_TOOL_NAMES) > 0
    assert len(ALLOWED_SERVICE_DOMAINS) > 0

    tool_calls = [
        # 1. Allowed tool
        {"name": "turn_off_stuck_actuator", "parameters": {"entity_id": "switch.sump_pump"}},
        # 2. Allowed domain direct call
        {"name": "light.turn_off", "parameters": {"entity_id": "light.porch"}},
        # 3. Disallowed tool / disallowed domain
        {"name": "shell_command.execute_arbitrary", "parameters": {"cmd": "rm -rf /"}},
        # 4. Disallowed call_ha_service domain
        {
            "name": "call_ha_service",
            "parameters": {"domain": "homeassistant", "service": "restart", "service_data": {}},
        },
    ]

    results = asyncio.run(mgr.async_execute_tool_plan(tool_calls, context=test_context))
    assert len(results) == 4

    # Tool 1: Succeeded
    assert results[0]["tool"] == "turn_off_stuck_actuator"
    assert results[0]["success"] is True

    # Tool 2: Succeeded
    assert results[1]["tool"] == "light.turn_off"
    assert results[1]["success"] is True

    # Tool 3: Rejected by domain allowlist
    assert results[2]["tool"] == "shell_command.execute_arbitrary"
    assert results[2]["success"] is False
    assert "not in the authorized service domains allowlist" in results[2]["error"]

    # Tool 4: Rejected by domain allowlist
    assert results[3]["tool"] == "call_ha_service"
    assert results[3]["success"] is False
    assert "not in the authorized service domains allowlist" in results[3]["error"]

    # Verify context was passed to valid calls
    for call_args in hass.services.async_call.call_args_list:
        assert call_args.kwargs.get("context") == test_context


def test_async_manage_ollama_addon_returns_deep_link():
    """Verify async_manage_ollama_addon returns Add-on Store deep links without Supervisor API hijacking."""
    hass = MagicMock()
    mgr = LocalLLMManager(hass)
    mgr.async_get_ollama_status = AsyncMock(return_value={"models": ["qwen2.5:3b"]})

    for action in ("install", "start", "stop", "restart", "uninstall"):
        res = asyncio.run(mgr.async_manage_ollama_addon(action=action))
        assert res["success"] is True
        assert res["action"] == action
        assert res["addon_url"] == "/hassio/addon/local_otis_ollama"
        assert res["deep_link"] == "/hassio/addon/local_otis_ollama"
        assert "/hassio/addon/local_otis_ollama" in res["message"]


def test_issue_reporter_view_enforces_admin():
    """Verify OtisIssueReporterView returns HTTP 403 for non-admin requests on audit and submit."""
    hass = MagicMock()
    log_monitor = MagicMock()
    log_monitor.async_audit_logs = AsyncMock(return_value={"bugs": []})
    view = OtisIssueReporterView(hass, log_monitor)

    # 1. Non-admin GET diagnostics
    req_non_admin_get = MagicMock()
    req_non_admin_get.query = {"action": "diagnostics"}
    non_admin_user = MagicMock()
    non_admin_user.is_admin = False
    req_non_admin_get.get = MagicMock(return_value=non_admin_user)
    req_non_admin_get.__getitem__ = MagicMock(return_value=non_admin_user)

    resp_get = asyncio.run(view.get(req_non_admin_get))
    assert resp_get.status == 403

    # 2. Non-admin POST submit_issue
    req_non_admin_post = MagicMock()
    req_non_admin_post.get = MagicMock(return_value=non_admin_user)
    req_non_admin_post.__getitem__ = MagicMock(return_value=non_admin_user)
    req_non_admin_post.json = AsyncMock(return_value={"action": "submit_issue", "title": "Test Bug"})

    resp_post = asyncio.run(view.post(req_non_admin_post))
    assert resp_post.status == 403

    # 3. Admin GET diagnostics succeeds
    admin_user = MagicMock()
    admin_user.is_admin = True
    req_admin_get = MagicMock()
    req_admin_get.query = {"action": "diagnostics"}
    req_admin_get.get = MagicMock(return_value=admin_user)
    req_admin_get.__getitem__ = MagicMock(return_value=admin_user)

    resp_admin_get = asyncio.run(view.get(req_admin_get))
    assert resp_admin_get.status == 200


def test_log_monitor_copilot_summary():
    """Verify LogMonitor.async_summarize_logs_for_copilot formats bugs, warnings, and clean state."""
    from custom_components.otis_ai.log_monitor import LogMonitor

    hass = MagicMock()
    hass.config.version = "2026.11"
    hass.config.as_dict = MagicMock(return_value={"architecture": "x86_64"})
    lm = LogMonitor(hass)
    lm.async_load = AsyncMock()
    lm.async_resolve_target_repo = AsyncMock(return_value="OtisPresley/otis-ai-companion")

    # 1. Clean log buffer
    lm.get_system_log_records = MagicMock(return_value=[])
    clean_summary = asyncio.run(lm.async_summarize_logs_for_copilot())
    assert "no active integration bugs, errors, or warnings" in clean_summary.lower()

    # 2. Bug + warning records
    lm.get_system_log_records = MagicMock(return_value=[
        {
            "name": "custom_components.my_sensor.sensor",
            "level": "ERROR",
            "message": ["Failed updating sensor"],
            "exception": "KeyError: 'temp'",
            "count": 3,
            "timestamp": 1700000000.0,
            "source": ["custom_components/my_sensor/sensor.py", 42],
        },
        {
            "name": "homeassistant.components.automation",
            "level": "WARNING",
            "message": ["Template rendered invalid value"],
            "exception": "",
            "count": 2,
            "timestamp": 1700000001.0,
            "source": [],
        },
    ])
    summary = asyncio.run(lm.async_summarize_logs_for_copilot())
    assert "my_sensor" in summary
    assert "KeyError" in summary or "Failed updating sensor" in summary
    assert "homeassistant.components.automation" in summary
    assert "Template rendered invalid value" in summary


def test_room_subview_includes_all_control_domains():
    """Verify _build_room_subview includes appliances, valves, remotes, presets, and avoids false keyword drops."""
    from custom_components.otis_ai.dashboard_manager import DashboardManager

    hass = MagicMock()
    dm = DashboardManager(hass)
    room_entities = [
        {"entity_id": "light.map_room", "domain": "light", "name": "Map Room", "state": "off"},
        {"entity_id": "switch.record_player", "domain": "switch", "name": "Record Player", "state": "off", "platform": "tplink"},
        {"entity_id": "vacuum.roborock", "domain": "vacuum", "name": "Roborock", "state": "docked"},
        {"entity_id": "valve.main_water", "domain": "valve", "name": "Main Water Valve", "state": "open"},
        {"entity_id": "water_heater.garage_tank", "domain": "water_heater", "name": "Water Heater", "state": "eco"},
        {"entity_id": "remote.theater_apple_tv", "domain": "remote", "name": "Apple TV Remote", "state": "on"},
        {"entity_id": "scene.movie_lights", "domain": "scene", "name": "Movie Lights", "state": "scening"},
        {"entity_id": "input_boolean.room_guest_mode", "domain": "input_boolean", "name": "Room Override", "state": "off"},
    ]
    view = dm._build_room_subview("study", {"name": "Study"}, room_entities, layout_style="classic_grid")
    assert view is not None
    serialized = str(view)
    for expected in (
        "light.map_room",
        "switch.record_player",
        "vacuum.roborock",
        "valve.main_water",
        "water_heater.garage_tank",
        "remote.theater_apple_tv",
        "scene.movie_lights",
        "input_boolean.room_guest_mode",
    ):
        assert expected in serialized, f"Missing {expected} in room subview"
