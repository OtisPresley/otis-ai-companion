"""Unit tests for HACS Default Catalog PR 13059 Compliance: Phase 4 and Phase 5."""
from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.otis_ai.const import CONF_GEMINI_API_KEY, DOMAIN
from custom_components.otis_ai.dashboard_manager import DashboardManager
from custom_components.otis_ai.floorplan_parser import FloorplanParser
from custom_components.otis_ai.theme_manager import ThemeManager


# ==============================================================================
# PHASE 4: DATA BOUNDARIES & STORAGE ISOLATION (Items 7, 8, 9, 10, 11)
# ==============================================================================

@pytest.mark.asyncio
async def test_dashboard_manager_no_raw_disk_writes():
    """Verify DashboardManager uses HA official Lovelace APIs, not raw .storage file writes."""
    hass = MagicMock()
    mock_coll = MagicMock()
    mock_coll.async_create_item = AsyncMock(return_value={"id": "otis_test"})
    mock_coll.async_get_items = MagicMock(return_value=[])

    mock_ll_storage = MagicMock()
    mock_ll_storage.async_save = AsyncMock()

    mock_ll_dash = MagicMock()
    mock_ll_dash.async_get_dashboards = AsyncMock(return_value=[])

    hass.data = {
        "lovelace": MagicMock(dashboards={"otis-pro-dashboard": MagicMock(async_save=AsyncMock())})
    }

    dm = DashboardManager(hass)

    with patch.object(dm, "_get_dashboards_collection", return_value=mock_coll), \
         patch("builtins.open") as mock_open:
        res = await dm.async_create_professional_dashboard(
            payload={
                "url_path": "otis-pro-dashboard",
                "dashboard_id": "otis_pro_dashboard",
                "title": "Otis Pro",
                "template": "media_studio",
            },
            capability_map={},
        )
        assert res["success"] is True
        # Verify open() was never called for storage files
        assert not any(".storage/lovelace" in str(c) for c in mock_open.call_args_list)


@pytest.mark.asyncio
async def test_dashboard_manager_analyze_gaps_no_raw_storage_reads():
    """Verify async_analyze_dashboard_gaps inspects runtime collections rather than raw storage."""
    hass = MagicMock()
    hass.states.async_all.return_value = []
    dash_mock = MagicMock()
    dash_mock.url_path = "energy"
    hass.data = {
        "lovelace": MagicMock(dashboards={"energy": dash_mock})
    }

    dm = DashboardManager(hass)
    with patch("os.listdir") as mock_listdir, patch("builtins.open") as mock_open:
        gaps = await dm.async_analyze_dashboard_gaps(capability_map={})
        assert isinstance(gaps, dict)
        # Verify raw storage was not read
        assert not any(".storage" in str(c) for c in mock_listdir.call_args_list)
        assert not any(".storage" in str(c) for c in mock_open.call_args_list)


@pytest.mark.asyncio
async def test_theme_manager_saves_to_storage_and_no_yaml():
    """Verify ThemeManager persists to .storage/otis_ai_themes and does not write YAML."""
    hass = MagicMock()
    tm = ThemeManager(hass)

    mock_store = MagicMock()
    mock_store.async_load = AsyncMock(return_value={})
    mock_store.async_save = AsyncMock()
    tm._store = mock_store

    with patch("builtins.open") as mock_open:
        res = await tm.async_generate_and_save_theme(
            prompt="Midnight Neon with dark mode",
            name="Midnight Neon",
            base_palette="cyberpunk",
        )
        assert res.get("success") is True
        # Store.async_save must be called
        mock_store.async_save.assert_awaited()
        # No yaml files written to filesystem
        assert not any(".yaml" in str(c) for c in mock_open.call_args_list)


@pytest.mark.asyncio
async def test_theme_manager_apply_theme_no_user_data_manipulation():
    """Verify ThemeManager calls frontend.set_theme and does not touch frontend.user_data directly."""
    hass = MagicMock()
    hass.services.has_service = MagicMock(return_value=True)
    hass.services.async_call = AsyncMock()
    tm = ThemeManager(hass)

    res = await tm.async_apply_theme("otis_midnight_neon")
    assert res is True
    # Verifies frontend.set_theme service call
    hass.services.async_call.assert_awaited_with(
        "frontend", "set_theme", {"name": "otis_midnight_neon"}, blocking=True
    )


@pytest.mark.asyncio
async def test_theme_manager_load_and_register_runtime():
    """Verify saved themes are registered in hass.data['frontend_themes'] on boot."""
    hass = MagicMock()
    hass.data = {}
    tm = ThemeManager(hass)

    mock_store = MagicMock()
    mock_store.async_load = AsyncMock(return_value={
        "otis_cyberpunk": {
            "name": "otis_cyberpunk",
            "vars": {"primary-color": "#ff007f"},
            "dark_mode": True,
        }
    })
    tm._store = mock_store

    await tm.async_load_and_register_themes()
    assert "frontend_themes" in hass.data
    assert "otis_cyberpunk" in hass.data["frontend_themes"]
    assert hass.data["frontend_themes"]["otis_cyberpunk"]["primary-color"] == "#ff007f"


def test_gemini_api_key_isolation():
    """Verify FloorplanParser strictly reads Otis AI's own API key and does not borrow from other integrations."""
    hass = MagicMock()
    fp = FloorplanParser(hass)

    # Simulate Otis entry without key
    otis_entry = MagicMock()
    otis_entry.domain = DOMAIN
    otis_entry.data = {}
    otis_entry.options = {}

    hass.data = {DOMAIN: {}}
    hass.config_entries.async_entries.return_value = [otis_entry]

    # Must NOT borrow and returns None for api_key
    key, model = fp._get_gemini_credentials()
    assert key is None
    assert model == "models/gemini-2.5-flash"

    # When Otis config entry has its own key
    otis_entry.options = {CONF_GEMINI_API_KEY: "OTIS_OWN_API_KEY"}
    key, model = fp._get_gemini_credentials()
    assert key == "OTIS_OWN_API_KEY"


# ==============================================================================
# PHASE 5: SVG SANITIZATION (Item 14)
# ==============================================================================

def test_floorplan_render_iso_room_sanitization():
    """Verify SVG renderer escapes room names, zones, and IDs against XSS attacks."""
    hass = MagicMock()
    fp = FloorplanParser(hass)

    malicious_room = {
        "id": 'room" onclick="alert(1)',
        "name": '<script>alert("XSS")</script>',
        "zone": 'Living "><img src=x onerror=alert(1)>',
        "iso_points_str": "0,0 100,0 100,100 0,100",
        "south_facet": "0,100 100,100",
        "east_facet": "100,0 100,100",
        "subzones": [
            {"id": "sub_1", "name": 'Zone <b>Bold</b> & "Quotes"'}
        ]
    }

    svg = fp._render_iso_room(malicious_room, accent_color="#00f0ff", outdoor_accent="#10b981")

    # Ensure dangerous tags and unescaped quotes cannot break out of attributes or DOM
    assert '<script>' not in svg
    assert '&lt;script&gt;' in svg
    assert '<img' not in svg
    assert '&lt;img' in svg
    assert '"><img' not in svg
    assert '" onclick' not in svg
    assert '&quot;' in svg or '&#34;' in svg


@pytest.mark.asyncio
async def test_floorplan_update_layout_sanitization():
    """Verify async_update_floorplan_layout sanitizes entities, badges, and coordinate points."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        svg_file = os.path.join(tmp_dir, "test_fp.svg")
        raw_svg = (
            '<svg><g class="room-group" data-area-id="living">'
            '<rect x="100.0" y="100.0" width="200.0" height="200.0" class="room-box" />'
            '<text class="room-header">Living Room</text>'
            '</g></svg>'
        )
        with open(svg_file, "w", encoding="utf-8") as f:
            f.write(raw_svg)

        hass = MagicMock()
        hass.config.path = lambda *args: os.path.join(tmp_dir, *args)
        hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a, **k: fn(*a, **k))

        fp = FloorplanParser(hass)
        res = await fp.async_update_floorplan_layout(
            rooms=[
                {
                    "id": "living",
                    "x": 120.0,
                    "y": 120.0,
                    "width": 220.0,
                    "height": 220.0,
                    "name": 'Living <script>alert("XSS")</script>',
                }
            ],
            badges=[
                {
                    "entity_id": 'light.test"><script>alert(2)</script>',
                    "x": 150.0,
                    "y": 150.0,
                }
            ],
            svg_relative_path="test_fp.svg",
        )

        assert res.get("success") is True
        with open(svg_file, "r", encoding="utf-8") as f:
            content = f.read()

        assert '<script>' not in content
        assert '&lt;script&gt;' in content
