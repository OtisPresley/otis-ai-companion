"""Otis AI Companion: User Behavioral Rules, Persona Customization & Household Instructions Manager."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "otis_ai_rules"
STORAGE_VERSION = 1

PERSONA_PROFILES: dict[str, str] = {
    "concierge": "A warm, proactive, helpful smart home concierge who offers insightful automation tips and thoughtful recommendations.",
    "butler": "An impeccably polite, discreet, formal digital butler dedicated to perfection, privacy, and flawless home management.",
    "minimalist": "An ultra-concise, technical minimalist. Direct, telegraphic responses with zero filler words or unnecessary pleasantries.",
    "custom": "A fully tailored assistant driven entirely by the user's custom household rules and personality guidelines.",
}

DEFAULT_RULES: dict[str, Any] = {
    "onboarding_completed": False,
    "persona": "concierge",
    "persona_name": "Otis",
    "tone": "friendly",
    "response_length": "balanced",
    "autonomy_level": "balanced",
    "require_lock_confirmation": True,
    "require_security_confirmation": True,
    "quiet_hours_enabled": True,
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "07:00",
    "quiet_hours_volume": 25,
    "preferred_speaker": "",
    "custom_instructions": "",
}


class BehavioralRulesManager:
    """Manages persistent user behavioral rules, persona customization, and prompt injection."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the Behavioral Rules Manager."""
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._rules: dict[str, Any] = dict(DEFAULT_RULES)
        self._loaded: bool = False

    async def async_load(self) -> dict[str, Any]:
        """Load persisted user rules from HA storage."""
        if self._loaded:
            return dict(self._rules)

        try:
            stored = await self._store.async_load()
            if stored and isinstance(stored, dict):
                self._rules = {**DEFAULT_RULES, **stored}
                _LOGGER.debug(
                    "Otis AI: Loaded behavioral rules (persona: %s, tone: %s, onboarding: %s)",
                    self._rules.get("persona"),
                    self._rules.get("tone"),
                    self._rules.get("onboarding_completed"),
                )
            else:
                self._rules = dict(DEFAULT_RULES)
        except Exception as err:
            _LOGGER.debug("Could not load behavioral rules: %s", err)
            self._rules = dict(DEFAULT_RULES)
        finally:
            self._loaded = True

        return dict(self._rules)

    async def async_save(self, new_rules: dict[str, Any]) -> dict[str, Any]:
        """Validate, merge, and persist updated user behavioral rules."""
        if not self._loaded:
            await self.async_load()

        merged = dict(self._rules)
        for key, value in new_rules.items():
            if key in DEFAULT_RULES:
                merged[key] = value

        # Ensure valid types
        if "onboarding_completed" in merged:
            merged["onboarding_completed"] = bool(merged["onboarding_completed"])
        if "require_lock_confirmation" in merged:
            merged["require_lock_confirmation"] = bool(merged["require_lock_confirmation"])
        if "require_security_confirmation" in merged:
            merged["require_security_confirmation"] = bool(merged["require_security_confirmation"])
        if "quiet_hours_enabled" in merged:
            merged["quiet_hours_enabled"] = bool(merged["quiet_hours_enabled"])
        if "quiet_hours_volume" in merged:
            try:
                merged["quiet_hours_volume"] = max(0, min(100, int(merged["quiet_hours_volume"])))
            except (ValueError, TypeError):
                merged["quiet_hours_volume"] = 25

        self._rules = merged
        await self._store.async_save(self._rules)
        _LOGGER.info(
            "Otis AI: Saved user behavioral rules (persona: %s, onboarding_completed: %s)",
            self._rules.get("persona"),
            self._rules.get("onboarding_completed"),
        )
        return dict(self._rules)

    def get_rules(self) -> dict[str, Any]:
        """Return the current behavioral rules."""
        return dict(self._rules)

    def is_onboarding_completed(self) -> bool:
        """Return whether user has completed initial onboarding."""
        return bool(self._rules.get("onboarding_completed", False))

    def get_system_prompt_snippet(self) -> str:
        """Generate a compact, token-efficient behavioral instructions snippet for LLM prompts."""
        p_key = self._rules.get("persona", "concierge")
        persona_desc = PERSONA_PROFILES.get(p_key, PERSONA_PROFILES["concierge"])
        tone = self._rules.get("tone", "friendly")
        length = self._rules.get("response_length", "balanced")
        autonomy = self._rules.get("autonomy_level", "balanced")
        custom_inst = (self._rules.get("custom_instructions") or "").strip()

        lines = [
            "### User Persona & Behavioral Instructions:",
            f"- Persona: {p_key.title()} ({persona_desc})",
            f"- Tone & Style: {tone.title()} tone, {length} responses.",
        ]
        if autonomy == "strict":
            lines.append("- Autonomy Policy: STRICT. Always ask for explicit user confirmation before executing any state changes or automations.")
        elif autonomy == "high":
            lines.append("- Autonomy Policy: HIGH. Act immediately and proactively on user intent without redundant confirmation.")
        else:
            safeguards = []
            if self._rules.get("require_lock_confirmation", True):
                safeguards.append("door deadbolts")
            if self._rules.get("require_security_confirmation", True):
                safeguards.append("security alarm arm/disarm")
            sg_str = f" Require confirmation before changing {' or '.join(safeguards)}." if safeguards else ""
            lines.append(f"- Autonomy Policy: BALANCED.{sg_str}")

        if self._rules.get("quiet_hours_enabled"):
            q_start = self._rules.get("quiet_hours_start", "22:00")
            q_end = self._rules.get("quiet_hours_end", "07:00")
            q_vol = self._rules.get("quiet_hours_volume", 25)
            lines.append(f"- Quiet Hours: {q_start} to {q_end} (Cap spoken notification volume at {q_vol}%).")

        if custom_inst:
            lines.append(f"- Custom Household Rules & Notes:\n{custom_inst}")

        return "\n".join(lines)

