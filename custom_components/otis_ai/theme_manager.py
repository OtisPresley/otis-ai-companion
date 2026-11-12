"""Dynamic theme generator and storage manager for Otis AI Companion."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any
import yaml

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

DEFAULT_THEMES_DIR = "themes"
STORAGE_KEY = "otis_ai_themes"
STORAGE_VERSION = 1

# Built-in curated theme presets with robust surface and input contrast variables
PRESET_THEMES: dict[str, dict[str, Any]] = {
    "cyberpunk": {
        "name": "Otis Cyberpunk Neon",
        "description": "High-tech futuristic dark theme with glowing cyan, electric magenta, and neon purple accents.",
        "dark_mode": True,
        "preview": {
            "primary": "#00f0ff",
            "accent": "#f43f5e",
            "background": "#070b14",
            "card_bg": "#0f172a",
            "text": "#f8fafc",
        },
        "vars": {
            "primary-color": "#00f0ff",
            "accent-color": "#f43f5e",
            "primary-background-color": "#070b14",
            "secondary-background-color": "#0b1220",
            "ha-card-background": "rgba(15, 23, 42, 0.95)",
            "card-background-color": "#0f172a",
            "mdc-theme-surface": "#0f172a",
            "ha-card-border-color": "rgba(0, 240, 255, 0.28)",
            "ha-card-border-width": "1px",
            "ha-card-border-radius": "12px",
            "ha-card-box-shadow": "0 0 16px rgba(0, 240, 255, 0.16)",
            "primary-text-color": "#f8fafc",
            "secondary-text-color": "#94a3b8",
            "disabled-text-color": "#475569",
            "divider-color": "rgba(0, 240, 255, 0.15)",
            "app-header-background-color": "#070b14",
            "app-header-text-color": "#00f0ff",
            "state-icon-color": "#94a3b8",
            "state-icon-active-color": "#00f0ff",
            "switch-checked-button-color": "#00f0ff",
            "switch-checked-track-color": "rgba(0, 240, 255, 0.4)",
            "switch-unchecked-button-color": "#475569",
            "switch-unchecked-track-color": "#1e293b",
            "slider-color": "#00f0ff",
            "slider-bar-color": "#1e293b",
            # Input & Select Control Contrast
            "input-fill-color": "#0b1220",
            "input-ink-color": "#f8fafc",
            "input-label-ink-color": "#94a3b8",
            "input-dropdown-icon-color": "#00f0ff",
            "input-idle-line-color": "rgba(0, 240, 255, 0.2)",
            "input-hover-line-color": "#00f0ff",
            "mdc-select-fill-color": "#0b1220",
            "mdc-select-ink-color": "#f8fafc",
            "mdc-select-label-ink-color": "#94a3b8",
            "mdc-select-dropdown-icon-color": "#00f0ff",
            "mdc-text-field-fill-color": "#0b1220",
            "mdc-text-field-ink-color": "#f8fafc",
            "mdc-text-field-label-ink-color": "#94a3b8",
            "mdc-theme-text-primary-on-background": "#f8fafc",
            "mdc-theme-text-secondary-on-background": "#94a3b8",
            "sidebar-background-color": "#070b14",
            "sidebar-text-color": "#f8fafc",
            "sidebar-icon-color": "#94a3b8",
            "sidebar-selected-icon-color": "#00f0ff",
            "sidebar-selected-text-color": "#00f0ff",
        },
    },
    "midnight_slate": {
        "name": "Otis Midnight Slate",
        "description": "Sophisticated frosted dark slate palette with sky-blue highlights and subtle glass borders.",
        "dark_mode": True,
        "preview": {
            "primary": "#38bdf8",
            "accent": "#818cf8",
            "background": "#0b1120",
            "card_bg": "#1e293b",
            "text": "#ffffff",
        },
        "vars": {
            "primary-color": "#38bdf8",
            "accent-color": "#818cf8",
            "primary-background-color": "#0b1120",
            "secondary-background-color": "#0f172a",
            "ha-card-background": "rgba(30, 41, 59, 0.95)",
            "card-background-color": "#1e293b",
            "mdc-theme-surface": "#1e293b",
            "ha-card-border-color": "rgba(56, 189, 248, 0.22)",
            "ha-card-border-width": "1px",
            "ha-card-border-radius": "14px",
            "ha-card-box-shadow": "0 8px 24px rgba(0, 0, 0, 0.32)",
            "primary-text-color": "#ffffff",
            "secondary-text-color": "rgba(255, 255, 255, 0.72)",
            "disabled-text-color": "rgba(255, 255, 255, 0.4)",
            "divider-color": "rgba(255, 255, 255, 0.08)",
            "app-header-background-color": "#0b1120",
            "app-header-text-color": "#ffffff",
            "state-icon-color": "rgba(255, 255, 255, 0.65)",
            "state-icon-active-color": "#38bdf8",
            "switch-checked-button-color": "#38bdf8",
            "switch-checked-track-color": "rgba(56, 189, 248, 0.35)",
            "switch-unchecked-button-color": "#64748b",
            "switch-unchecked-track-color": "#1e293b",
            "slider-color": "#38bdf8",
            "slider-bar-color": "#1e293b",
            # Input & Select Control Contrast (Fix white-on-white dropdowns)
            "input-fill-color": "#0f172a",
            "input-ink-color": "#ffffff",
            "input-label-ink-color": "#94a3b8",
            "input-dropdown-icon-color": "#38bdf8",
            "input-idle-line-color": "rgba(255, 255, 255, 0.15)",
            "input-hover-line-color": "#38bdf8",
            "mdc-select-fill-color": "#0f172a",
            "mdc-select-ink-color": "#ffffff",
            "mdc-select-label-ink-color": "#94a3b8",
            "mdc-select-dropdown-icon-color": "#38bdf8",
            "mdc-text-field-fill-color": "#0f172a",
            "mdc-text-field-ink-color": "#ffffff",
            "mdc-text-field-label-ink-color": "#94a3b8",
            "mdc-theme-text-primary-on-background": "#ffffff",
            "mdc-theme-text-secondary-on-background": "#94a3b8",
            "sidebar-background-color": "#0b1120",
            "sidebar-text-color": "#ffffff",
            "sidebar-icon-color": "#94a3b8",
            "sidebar-selected-icon-color": "#38bdf8",
            "sidebar-selected-text-color": "#38bdf8",
        },
    },
    "oled_black": {
        "name": "Otis OLED Obsidian",
        "description": "Zero-emission pitch black background engineered for OLED displays with vivid emerald and sky indicators.",
        "dark_mode": True,
        "preview": {
            "primary": "#10b981",
            "accent": "#38bdf8",
            "background": "#000000",
            "card_bg": "#111113",
            "text": "#ffffff",
        },
        "vars": {
            "primary-color": "#10b981",
            "accent-color": "#38bdf8",
            "primary-background-color": "#000000",
            "secondary-background-color": "#080808",
            "ha-card-background": "#111113",
            "card-background-color": "#111113",
            "mdc-theme-surface": "#111113",
            "ha-card-border-color": "#27272a",
            "ha-card-border-width": "1px",
            "ha-card-border-radius": "10px",
            "ha-card-box-shadow": "none",
            "primary-text-color": "#ffffff",
            "secondary-text-color": "#a1a1aa",
            "disabled-text-color": "#52525b",
            "divider-color": "#27272a",
            "app-header-background-color": "#000000",
            "app-header-text-color": "#ffffff",
            "state-icon-color": "#71717a",
            "state-icon-active-color": "#10b981",
            "switch-checked-button-color": "#10b981",
            "switch-checked-track-color": "rgba(16, 185, 129, 0.4)",
            "switch-unchecked-button-color": "#52525b",
            "switch-unchecked-track-color": "#18181b",
            "slider-color": "#10b981",
            "slider-bar-color": "#27272a",
            "input-fill-color": "#080808",
            "input-ink-color": "#ffffff",
            "input-label-ink-color": "#a1a1aa",
            "input-dropdown-icon-color": "#10b981",
            "input-idle-line-color": "#27272a",
            "input-hover-line-color": "#10b981",
            "mdc-select-fill-color": "#080808",
            "mdc-select-ink-color": "#ffffff",
            "mdc-select-label-ink-color": "#a1a1aa",
            "mdc-select-dropdown-icon-color": "#10b981",
            "mdc-text-field-fill-color": "#080808",
            "mdc-text-field-ink-color": "#ffffff",
            "mdc-text-field-label-ink-color": "#a1a1aa",
            "mdc-theme-text-primary-on-background": "#ffffff",
            "mdc-theme-text-secondary-on-background": "#a1a1aa",
            "sidebar-background-color": "#000000",
            "sidebar-text-color": "#ffffff",
            "sidebar-icon-color": "#71717a",
            "sidebar-selected-icon-color": "#10b981",
            "sidebar-selected-text-color": "#10b981",
        },
    },
    "sunset_amber": {
        "name": "Otis Sunset Amber",
        "description": "Warm luxury evening aesthetic featuring rich charcoal, warm amber gold, and fire orange highlights.",
        "dark_mode": True,
        "preview": {
            "primary": "#f59e0b",
            "accent": "#ea580c",
            "background": "#1c1917",
            "card_bg": "#292524",
            "text": "#fafaf9",
        },
        "vars": {
            "primary-color": "#f59e0b",
            "accent-color": "#ea580c",
            "primary-background-color": "#1c1917",
            "secondary-background-color": "#141210",
            "ha-card-background": "rgba(41, 37, 36, 0.95)",
            "card-background-color": "#292524",
            "mdc-theme-surface": "#292524",
            "ha-card-border-color": "rgba(245, 158, 11, 0.25)",
            "ha-card-border-width": "1px",
            "ha-card-border-radius": "16px",
            "ha-card-box-shadow": "0 8px 24px rgba(0, 0, 0, 0.28)",
            "primary-text-color": "#fafaf9",
            "secondary-text-color": "#a8a29e",
            "disabled-text-color": "#57534e",
            "divider-color": "rgba(245, 158, 11, 0.12)",
            "app-header-background-color": "#1c1917",
            "app-header-text-color": "#f59e0b",
            "state-icon-color": "#a8a29e",
            "state-icon-active-color": "#f59e0b",
            "switch-checked-button-color": "#f59e0b",
            "switch-checked-track-color": "rgba(245, 158, 11, 0.4)",
            "switch-unchecked-button-color": "#57534e",
            "switch-unchecked-track-color": "#292524",
            "slider-color": "#f59e0b",
            "slider-bar-color": "#292524",
            "input-fill-color": "#141210",
            "input-ink-color": "#fafaf9",
            "input-label-ink-color": "#a8a29e",
            "input-dropdown-icon-color": "#f59e0b",
            "input-idle-line-color": "rgba(245, 158, 11, 0.2)",
            "input-hover-line-color": "#f59e0b",
            "mdc-select-fill-color": "#141210",
            "mdc-select-ink-color": "#fafaf9",
            "mdc-select-label-ink-color": "#a8a29e",
            "mdc-select-dropdown-icon-color": "#f59e0b",
            "mdc-text-field-fill-color": "#141210",
            "mdc-text-field-ink-color": "#fafaf9",
            "mdc-text-field-label-ink-color": "#a8a29e",
            "mdc-theme-text-primary-on-background": "#fafaf9",
            "mdc-theme-text-secondary-on-background": "#a8a29e",
            "sidebar-background-color": "#1c1917",
            "sidebar-text-color": "#fafaf9",
            "sidebar-icon-color": "#a8a29e",
            "sidebar-selected-icon-color": "#f59e0b",
            "sidebar-selected-text-color": "#f59e0b",
        },
    },
    "emerald_luxury": {
        "name": "Otis Emerald Luxury",
        "description": "Deep imperial forest green with radiant mint and gilded gold highlights.",
        "dark_mode": True,
        "preview": {
            "primary": "#34d399",
            "accent": "#fbbf24",
            "background": "#022c22",
            "card_bg": "#064e3b",
            "text": "#f0fdf4",
        },
        "vars": {
            "primary-color": "#34d399",
            "accent-color": "#fbbf24",
            "primary-background-color": "#022c22",
            "secondary-background-color": "#011e17",
            "ha-card-background": "rgba(6, 78, 59, 0.95)",
            "card-background-color": "#064e3b",
            "mdc-theme-surface": "#064e3b",
            "ha-card-border-color": "rgba(52, 211, 153, 0.25)",
            "ha-card-border-width": "1px",
            "ha-card-border-radius": "14px",
            "ha-card-box-shadow": "0 8px 24px rgba(0, 0, 0, 0.35)",
            "primary-text-color": "#f0fdf4",
            "secondary-text-color": "#a7f3d0",
            "disabled-text-color": "#047857",
            "divider-color": "rgba(52, 211, 153, 0.15)",
            "app-header-background-color": "#022c22",
            "app-header-text-color": "#34d399",
            "state-icon-color": "#a7f3d0",
            "state-icon-active-color": "#34d399",
            "switch-checked-button-color": "#34d399",
            "switch-checked-track-color": "rgba(52, 211, 153, 0.4)",
            "switch-unchecked-button-color": "#047857",
            "switch-unchecked-track-color": "#064e3b",
            "slider-color": "#34d399",
            "slider-bar-color": "#064e3b",
            "input-fill-color": "#011e17",
            "input-ink-color": "#f0fdf4",
            "input-label-ink-color": "#a7f3d0",
            "input-dropdown-icon-color": "#34d399",
            "input-idle-line-color": "rgba(52, 211, 153, 0.2)",
            "input-hover-line-color": "#34d399",
            "mdc-select-fill-color": "#011e17",
            "mdc-select-ink-color": "#f0fdf4",
            "mdc-select-label-ink-color": "#a7f3d0",
            "mdc-select-dropdown-icon-color": "#34d399",
            "mdc-text-field-fill-color": "#011e17",
            "mdc-text-field-ink-color": "#f0fdf4",
            "mdc-text-field-label-ink-color": "#a7f3d0",
            "mdc-theme-text-primary-on-background": "#f0fdf4",
            "mdc-theme-text-secondary-on-background": "#a7f3d0",
            "sidebar-background-color": "#022c22",
            "sidebar-text-color": "#f0fdf4",
            "sidebar-icon-color": "#a7f3d0",
            "sidebar-selected-icon-color": "#34d399",
            "sidebar-selected-text-color": "#34d399",
        },
    },
    "nordic_frost": {
        "name": "Otis Nordic Frost",
        "description": "Airy Scandinavian light mode with crisp porcelain surfaces, sky-blue controls, and ultra-clean contrast.",
        "dark_mode": False,
        "preview": {
            "primary": "#0284c7",
            "accent": "#0d9488",
            "background": "#f8fafc",
            "card_bg": "#ffffff",
            "text": "#0f172a",
        },
        "vars": {
            "primary-color": "#0284c7",
            "accent-color": "#0d9488",
            "primary-background-color": "#f8fafc",
            "secondary-background-color": "#f1f5f9",
            "ha-card-background": "#ffffff",
            "card-background-color": "#ffffff",
            "mdc-theme-surface": "#ffffff",
            "ha-card-border-color": "#e2e8f0",
            "ha-card-border-width": "1px",
            "ha-card-border-radius": "12px",
            "ha-card-box-shadow": "0 2px 8px rgba(0, 0, 0, 0.05)",
            "primary-text-color": "#0f172a",
            "secondary-text-color": "#64748b",
            "disabled-text-color": "#94a3b8",
            "divider-color": "#e2e8f0",
            "app-header-background-color": "#ffffff",
            "app-header-text-color": "#0f172a",
            "state-icon-color": "#64748b",
            "state-icon-active-color": "#0284c7",
            "switch-checked-button-color": "#0284c7",
            "switch-checked-track-color": "rgba(2, 132, 199, 0.35)",
            "switch-unchecked-button-color": "#cbd5e1",
            "switch-unchecked-track-color": "#e2e8f0",
            "slider-color": "#0284c7",
            "slider-bar-color": "#e2e8f0",
            "input-fill-color": "#f1f5f9",
            "input-ink-color": "#0f172a",
            "input-label-ink-color": "#64748b",
            "input-dropdown-icon-color": "#0284c7",
            "input-idle-line-color": "#cbd5e1",
            "input-hover-line-color": "#0284c7",
            "mdc-select-fill-color": "#f1f5f9",
            "mdc-select-ink-color": "#0f172a",
            "mdc-select-label-ink-color": "#64748b",
            "mdc-select-dropdown-icon-color": "#0284c7",
            "mdc-text-field-fill-color": "#f1f5f9",
            "mdc-text-field-ink-color": "#0f172a",
            "mdc-text-field-label-ink-color": "#64748b",
            "mdc-theme-text-primary-on-background": "#0f172a",
            "mdc-theme-text-secondary-on-background": "#64748b",
            "sidebar-background-color": "#ffffff",
            "sidebar-text-color": "#0f172a",
            "sidebar-icon-color": "#64748b",
            "sidebar-selected-icon-color": "#0284c7",
            "sidebar-selected-text-color": "#0284c7",
        },
    },
    "high_contrast": {
        "name": "Otis High Contrast",
        "description": "Accessibility-focused ultra high-contrast dark theme with sharp borders and vibrant primary colors.",
        "dark_mode": True,
        "preview": {
            "primary": "#ffff00",
            "accent": "#00ffff",
            "background": "#000000",
            "card_bg": "#000000",
            "text": "#ffffff",
        },
        "vars": {
            "primary-color": "#ffff00",
            "accent-color": "#00ffff",
            "primary-background-color": "#000000",
            "secondary-background-color": "#000000",
            "ha-card-background": "#000000",
            "card-background-color": "#000000",
            "mdc-theme-surface": "#000000",
            "ha-card-border-color": "#ffffff",
            "ha-card-border-width": "2px",
            "ha-card-border-radius": "4px",
            "ha-card-box-shadow": "none",
            "primary-text-color": "#ffffff",
            "secondary-text-color": "#e5e7eb",
            "disabled-text-color": "#9ca3af",
            "divider-color": "#ffffff",
            "app-header-background-color": "#000000",
            "app-header-text-color": "#ffff00",
            "state-icon-color": "#ffffff",
            "state-icon-active-color": "#ffff00",
            "switch-checked-button-color": "#ffff00",
            "switch-checked-track-color": "rgba(255, 255, 0, 0.5)",
            "switch-unchecked-button-color": "#ffffff",
            "switch-unchecked-track-color": "#374151",
            "slider-color": "#ffff00",
            "slider-bar-color": "#374151",
            "input-fill-color": "#000000",
            "input-ink-color": "#ffffff",
            "input-label-ink-color": "#ffff00",
            "input-dropdown-icon-color": "#ffff00",
            "input-idle-line-color": "#ffffff",
            "input-hover-line-color": "#ffff00",
            "mdc-select-fill-color": "#000000",
            "mdc-select-ink-color": "#ffffff",
            "mdc-select-label-ink-color": "#ffff00",
            "mdc-select-dropdown-icon-color": "#ffff00",
            "mdc-text-field-fill-color": "#000000",
            "mdc-text-field-ink-color": "#ffffff",
            "mdc-text-field-label-ink-color": "#ffff00",
            "mdc-theme-text-primary-on-background": "#ffffff",
            "mdc-theme-text-secondary-on-background": "#e5e7eb",
            "sidebar-background-color": "#000000",
            "sidebar-text-color": "#ffffff",
            "sidebar-icon-color": "#ffff00",
            "sidebar-selected-icon-color": "#00ffff",
            "sidebar-selected-text-color": "#00ffff",
        },
    },
}

NAMED_COLORS: dict[str, str] = {
    "cyan": "#06b6d4",
    "teal": "#14b8a6",
    "sky": "#0ea5e9",
    "blue": "#3b82f6",
    "indigo": "#6366f1",
    "violet": "#8b5cf6",
    "purple": "#a855f7",
    "fuchsia": "#d946ef",
    "pink": "#ec4899",
    "rose": "#f43f5e",
    "red": "#ef4444",
    "orange": "#f97316",
    "amber": "#f59e0b",
    "yellow": "#eab308",
    "lime": "#84cc16",
    "green": "#22c55e",
    "emerald": "#10b981",
    "gold": "#eab308",
    "neon cyan": "#00f0ff",
    "neon green": "#39ff14",
    "neon pink": "#ff007f",
    "coral": "#ff6f61",
}


def slugify_theme_name(name: str) -> str:
    """Convert theme title into a safe lowercase alphanumeric identifier."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name.lower()).strip("_")
    return slug or "custom"


class ThemeManager:
    """Manages dynamic generation, disk persistence, and live activation of Home Assistant themes."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the theme manager."""
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._themes_cache: dict[str, Any] | None = None

    async def async_load_and_register_themes(self) -> dict[str, Any]:
        """Load stored themes from .storage/otis_ai_themes and register them in Home Assistant frontend themes at runtime."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            stored = {}
        self._themes_cache = stored

        frontend_themes = self.hass.data.setdefault("frontend_themes", {})
        if isinstance(frontend_themes, dict):
            for t_key, t_entry in stored.items():
                if isinstance(t_entry, dict) and "ha_theme_dict" in t_entry:
                    frontend_themes[t_key] = t_entry["ha_theme_dict"].get(t_key, t_entry["ha_theme_dict"])
                elif isinstance(t_entry, dict) and "vars" in t_entry:
                    mode_key = "dark" if t_entry.get("dark_mode", True) else "light"
                    frontend_themes[t_key] = {
                        **t_entry["vars"],
                        "modes": {
                            mode_key: t_entry["vars"],
                        },
                    }

        return stored

    def _get_themes_directory(self) -> str:
        """Return the absolute path to /config/themes/."""
        if hasattr(self.hass, "config") and hasattr(self.hass.config, "path"):
            return self.hass.config.path(DEFAULT_THEMES_DIR)
        return os.path.abspath(DEFAULT_THEMES_DIR)

    async def _run_executor(self, target: Any, *args: Any) -> Any:
        """Execute a sync callable in executor, safely handling coroutines or mock returns."""
        if not hasattr(self.hass, "async_add_executor_job"):
            return target(*args)
        res = self.hass.async_add_executor_job(target, *args)
        if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
            return await res
        return res

    def synthesize_theme_from_prompt(
        self,
        prompt: str,
        name: str | None = None,
        base_palette: str | None = None,
        dark_mode: bool | None = None,
        border_radius: str | None = None,
        glow_effect: bool | None = None,
        custom_vars: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Synthesize theme CSS variables and metadata from natural language instructions or presets."""
        p_lower = (prompt or "").lower()

        # 1. Determine baseline palette
        selected_key = "midnight_slate"
        if base_palette and base_palette.lower() in PRESET_THEMES:
            selected_key = base_palette.lower()
        else:
            for k in PRESET_THEMES:
                if k in p_lower or k.replace("_", " ") in p_lower:
                    selected_key = k
                    break

        base_config = PRESET_THEMES[selected_key]
        theme_vars: dict[str, Any] = dict(base_config["vars"])
        preview: dict[str, str] = dict(base_config["preview"])

        # 2. Mode (Dark vs Light)
        if dark_mode is not None:
            is_dark = dark_mode
        elif any(w in p_lower for w in ("light mode", "bright", "white theme", "scandinavian", "daylight")):
            is_dark = False
        else:
            is_dark = base_config.get("dark_mode", True)

        if not is_dark and is_dark != base_config.get("dark_mode", True):
            # Switch default variables to light baseline
            light_base = PRESET_THEMES["nordic_frost"]
            theme_vars = dict(light_base["vars"])
            preview = dict(light_base["preview"])

        # 3. Custom Color Extraction (Hex colors or named colors in prompt)
        hex_matches = re.findall(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", prompt)
        if hex_matches:
            theme_vars["primary-color"] = hex_matches[0]
            preview["primary"] = hex_matches[0]
            if len(hex_matches) > 1:
                theme_vars["accent-color"] = hex_matches[1]
                preview["accent"] = hex_matches[1]
        else:
            for cname, chex in NAMED_COLORS.items():
                if re.search(r"\b" + re.escape(cname) + r"\b", p_lower):
                    theme_vars["primary-color"] = chex
                    preview["primary"] = chex
                    theme_vars["state-icon-active-color"] = chex
                    theme_vars["switch-checked-button-color"] = chex
                    theme_vars["slider-color"] = chex
                    break

        # 4. Border Radius Extraction
        radius_match = re.search(r"\b(\d+)\s*px\b", p_lower)
        if border_radius:
            theme_vars["ha-card-border-radius"] = border_radius
        elif radius_match:
            theme_vars["ha-card-border-radius"] = f"{radius_match.group(1)}px"
        elif any(w in p_lower for w in ("sharp", "square", "brutalist")):
            theme_vars["ha-card-border-radius"] = "0px"
        elif any(w in p_lower for w in ("extra round", "pill", "smooth rounded")):
            theme_vars["ha-card-border-radius"] = "22px"
        elif "round" in p_lower:
            theme_vars["ha-card-border-radius"] = "16px"

        # 5. Glow / Neon Shadow Effect
        has_glow = (
            glow_effect
            if glow_effect is not None
            else any(w in p_lower for w in ("glow", "neon", "illuminat", "cyber"))
        )
        if has_glow:
            p_col = theme_vars["primary-color"]
            theme_vars["ha-card-box-shadow"] = f"0 0 16px color-mix(in srgb, {p_col} 35%, transparent)"
            theme_vars["ha-card-border-color"] = f"color-mix(in srgb, {p_col} 50%, transparent)"

        # 6. Synchronize input, surface, and interactive elements with theme palette
        p_col = theme_vars["primary-color"]
        sec_bg = theme_vars.get("secondary-background-color", "#0f172a") if is_dark else "#f1f5f9"
        txt_col = theme_vars.get("primary-text-color", "#ffffff") if is_dark else "#0f172a"
        sec_txt = theme_vars.get("secondary-text-color", "#94a3b8") if is_dark else "#64748b"
        card_bg = theme_vars.get("card-background-color", preview.get("card_bg", "#1e293b"))

        theme_vars["input-dropdown-icon-color"] = p_col
        theme_vars["input-hover-line-color"] = p_col
        theme_vars["mdc-select-dropdown-icon-color"] = p_col
        theme_vars["sidebar-selected-icon-color"] = p_col
        theme_vars["sidebar-selected-text-color"] = p_col

        theme_vars["card-background-color"] = card_bg
        theme_vars["mdc-theme-surface"] = card_bg
        theme_vars["input-fill-color"] = sec_bg
        theme_vars["input-ink-color"] = txt_col
        theme_vars["input-label-ink-color"] = sec_txt
        theme_vars["mdc-select-fill-color"] = sec_bg
        theme_vars["mdc-select-ink-color"] = txt_col
        theme_vars["mdc-select-label-ink-color"] = sec_txt
        theme_vars["mdc-text-field-fill-color"] = sec_bg
        theme_vars["mdc-text-field-ink-color"] = txt_col
        theme_vars["mdc-text-field-label-ink-color"] = sec_txt
        theme_vars["mdc-theme-text-primary-on-background"] = txt_col
        theme_vars["mdc-theme-text-secondary-on-background"] = sec_txt

        # 7. Apply any direct caller custom variable overrides
        if custom_vars:
            theme_vars.update(custom_vars)

        # 8. Generate clean title and slug
        if name:
            title = name
        else:
            # Generate short title from prompt or preset
            title_words = [w.capitalize() for w in re.findall(r"[a-zA-Z0-9]+", prompt)[:3]]
            title = " ".join(title_words) if title_words else base_config["name"]
            if not title.startswith("Otis"):
                title = f"Otis {title}"

        slug = slugify_theme_name(title)
        if slug.startswith("otis_"):
            slug = slug[5:]

        return {
            "title": title,
            "slug": slug,
            "theme_key": f"otis_{slug}",
            "dark_mode": is_dark,
            "preview": preview,
            "vars": theme_vars,
        }

    async def async_generate_and_save_theme(
        self,
        prompt: str,
        name: str | None = None,
        base_palette: str | None = None,
        dark_mode: bool | None = None,
        border_radius: str | None = None,
        glow_effect: bool | None = None,
        custom_vars: dict[str, Any] | None = None,
        apply_immediately: bool = False,
    ) -> dict[str, Any]:
        """Synthesize theme definition, persist to .storage/otis_ai_themes, and register in frontend at runtime."""
        theme_data = self.synthesize_theme_from_prompt(
            prompt=prompt,
            name=name,
            base_palette=base_palette,
            dark_mode=dark_mode,
            border_radius=border_radius,
            glow_effect=glow_effect,
            custom_vars=custom_vars,
        )

        theme_key = theme_data["theme_key"]
        slug = theme_data["slug"]

        mode_key = "dark" if theme_data.get("dark_mode", True) else "light"
        ha_theme_dict = {
            theme_key: {
                **theme_data["vars"],
                "modes": {
                    mode_key: theme_data["vars"],
                },
            }
        }

        from .const import SafeNoAliasDumper
        yaml_content = (
            f"# =========================================================================\n"
            f"# {theme_data['title']} (Generated by Otis AI Companion)\n"
            f"# Prompt: {prompt}\n"
            f"# =========================================================================\n\n"
            + (
                yaml.dump(ha_theme_dict, Dumper=SafeNoAliasDumper, sort_keys=False, default_flow_style=False)
                if SafeNoAliasDumper is not None
                else yaml.dump(ha_theme_dict, sort_keys=False, default_flow_style=False)
            )
        )

        # Store in .storage/otis_ai_themes via Store
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            stored = {}
        stored[theme_key] = {
            **theme_data,
            "ha_theme_dict": ha_theme_dict,
            "yaml": yaml_content,
        }
        await self._store.async_save(stored)
        self._themes_cache = stored
        _LOGGER.info("Persisted custom Otis theme %s to .storage/%s", theme_key, STORAGE_KEY)

        # Register live in Home Assistant frontend themes
        frontend_themes = self.hass.data.setdefault("frontend_themes", {})
        if isinstance(frontend_themes, dict):
            frontend_themes[theme_key] = ha_theme_dict[theme_key]

        # Trigger frontend theme update event
        try:
            from homeassistant.components.frontend.helpers import async_update_theme_and_fire_event
            async_update_theme_and_fire_event(self.hass)
        except Exception:
            self.hass.bus.async_fire("themes_updated")

        applied = False
        if apply_immediately:
            applied = await self.async_apply_theme(theme_key)

        storage_path = (
            self.hass.config.path(".storage", STORAGE_KEY)
            if hasattr(self.hass, "config") and hasattr(self.hass.config, "path")
            else f".storage/{STORAGE_KEY}"
        )

        return {
            "success": True,
            "theme_key": theme_key,
            "title": theme_data["title"],
            "slug": slug,
            "file_path": storage_path,
            "storage_key": STORAGE_KEY,
            "preview": theme_data["preview"],
            "dark_mode": theme_data["dark_mode"],
            "applied": applied,
            "yaml": yaml_content,
        }

    async def async_reload_themes(self) -> bool:
        """Update live frontend theme registry with all saved Otis themes."""
        try:
            await self.async_load_and_register_themes()
            try:
                from homeassistant.components.frontend.helpers import async_update_theme_and_fire_event
                async_update_theme_and_fire_event(self.hass)
            except Exception:
                self.hass.bus.async_fire("themes_updated")
            return True
        except Exception as err:
            _LOGGER.warning("Could not reload frontend themes: %s", err)
        return False

    async def async_apply_theme(
        self,
        theme_key: str,
        mode: str | None = None,
        user_id: str | None = None,
        all_users: bool = False,
    ) -> bool:
        """Call frontend.set_theme service to apply theme immediately."""
        try:
            service_data: dict[str, Any] = {"name": theme_key}
            if mode:
                service_data["mode"] = mode
            if self.hass.services.has_service("frontend", "set_theme"):
                await self.hass.services.async_call("frontend", "set_theme", service_data, blocking=True)
                _LOGGER.info("Applied backend theme %s (mode=%s)", theme_key, mode)
            return True
        except Exception as err:
            _LOGGER.warning("Could not apply theme %s: %s", theme_key, err)
        return False

    async def async_list_otis_themes(self) -> list[dict[str, Any]]:
        """List Otis themes from .storage/otis_ai_themes with color previews."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            stored = {}
        self._themes_cache = stored

        results: list[dict[str, Any]] = []
        for key, vals in stored.items():
            if isinstance(vals, dict):
                preview = vals.get("preview", {})
                slug = vals.get("slug") or (key[5:] if key.startswith("otis_") else key)
                title = vals.get("title") or f"Otis {' '.join([w.capitalize() for w in slug.split('_')])}"
                results.append({
                    "theme_key": key,
                    "title": title,
                    "slug": slug,
                    "storage_key": STORAGE_KEY,
                    "preview": preview,
                    "border_radius": vals.get("vars", {}).get("ha-card-border-radius", "12px"),
                })
        return results

    async def async_delete_theme(self, theme_key: str) -> bool:
        """Delete an Otis theme from .storage/otis_ai_themes and deregister from frontend."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            stored = {}
        if theme_key in stored:
            del stored[theme_key]
            await self._store.async_save(stored)
            self._themes_cache = stored
            if "frontend_themes" in self.hass.data and isinstance(self.hass.data["frontend_themes"], dict):
                self.hass.data["frontend_themes"].pop(theme_key, None)
            try:
                from homeassistant.components.frontend.helpers import async_update_theme_and_fire_event
                async_update_theme_and_fire_event(self.hass)
            except Exception:
                self.hass.bus.async_fire("themes_updated")
            return True
        return False
