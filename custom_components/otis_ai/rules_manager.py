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
    "audio_follow_enabled": True,
    "preferred_speaker": "",
    "custom_instructions": "",
    "dashboard_layout": "modern_sections",
    "navigation_style": "sleek_buttons",
    "calendar_view": "listDay",
    "primary_content_focus": "balanced",
    "presence_room_cards": True,
    "dismissed_recommendation_ids": [],
    "show_ignored_recommendations": False,
    "floorplan_view_mode": "2d",
    "floorplan_3d": False,
    "floorplan_azimuth": 0,
    "floorplan_pitch": 30,
    "floorplan_wall_height": 36,
    "floorplan_walls_enabled": True,
    "voice_announcements_enabled": True,
    "voice_filter_passersby": True,
    "person_profiles": {},
    "wizard_state": {},
    "reasoning_timeout": 60,
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
            # Auto-recover wizard_state if missing from legacy custom_instructions
            if not self._rules.get("wizard_state") and self._rules.get("custom_instructions"):
                try:
                    import re
                    ci = str(self._rules.get("custom_instructions") or "")
                    w: dict[str, Any] = {}
                    m_res = re.search(r"Primary Residents:\s*([^\.\n]+)", ci)
                    if m_res:
                        w["residents"] = m_res.group(1).strip()
                    m_work = re.search(r"Work-from-Home Routine:\s*([^\n]+)", ci)
                    if m_work:
                        w["workHours"] = m_work.group(1).strip().rstrip(".")
                    m_sleep = re.search(r"Sleep & Bed Navigation:\s*([^\n]+)", ci)
                    if m_sleep:
                        w["sleepHabits"] = m_sleep.group(1).strip().rstrip(".")
                    m_code = re.search(r"(?:code|temporary code)\s*['\"]?([0-9A-Za-z]+)['\"]?", ci)
                    if m_code:
                        w["guestLockCode"] = m_code.group(1).strip()
                    if w:
                        w.setdefault("guestDelayedOff", "00:00:00")
                        w.setdefault("guestClimateComfort", True)
                        w.setdefault("holidaySwitches", True)
                        w.setdefault("requireDeadboltConfirm", self._rules.get("require_lock_confirmation", True))
                        w.setdefault("requireAlarmConfirm", self._rules.get("require_security_confirmation", True))
                        w.setdefault("garageAlertMinutes", 15)
                        w.setdefault("perimeterCameraAlerts", True)
                        w.setdefault("matrixRouting", True)
                        w.setdefault("voiceDucking", True)
                        w.setdefault("quietHoursStart", self._rules.get("quiet_hours_start", "22:00"))
                        w.setdefault("quietHoursEnd", self._rules.get("quiet_hours_end", "07:00"))
                        w.setdefault("quietVolume", self._rules.get("quiet_hours_volume", 25))
                        self._rules["wizard_state"] = w
                except Exception as rec_err:
                    _LOGGER.debug("Could not recover wizard_state: %s", rec_err)
            self._sync_audio_follow_switch()
            self._sync_voice_announcements_switch()

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
        if "audio_follow_enabled" in merged:
            merged["audio_follow_enabled"] = bool(merged["audio_follow_enabled"])
        if "voice_announcements_enabled" in merged:
            merged["voice_announcements_enabled"] = bool(merged["voice_announcements_enabled"])
        if "voice_filter_passersby" in merged:
            merged["voice_filter_passersby"] = bool(merged["voice_filter_passersby"])
        if "presence_room_cards" in merged:
            merged["presence_room_cards"] = bool(merged["presence_room_cards"])
        if "reasoning_timeout" in merged:
            try:
                merged["reasoning_timeout"] = max(10, min(300, int(merged["reasoning_timeout"])))
            except (ValueError, TypeError):
                merged["reasoning_timeout"] = 60
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
        if "dashboard_layout" in merged and str(merged["dashboard_layout"]).lower() in ("modern_sections", "classic_grid"):
            merged["dashboard_layout"] = str(merged["dashboard_layout"]).lower()
        if "navigation_style" in merged and str(merged["navigation_style"]).lower() in ("sleek_buttons", "standard_grid", "tiles"):
            merged["navigation_style"] = str(merged["navigation_style"]).lower()
        if "calendar_view" in merged and str(merged["calendar_view"]).lower() in ("listday", "month", "listweek"):
            merged["calendar_view"] = "listDay" if str(merged["calendar_view"]).lower() == "listday" else str(merged["calendar_view"]).lower()
        if "primary_content_focus" in merged and str(merged["primary_content_focus"]).lower() in ("balanced", "studios_first", "glance_first"):
            merged["primary_content_focus"] = str(merged["primary_content_focus"]).lower()
        if "show_ignored_recommendations" in merged:
            merged["show_ignored_recommendations"] = bool(merged["show_ignored_recommendations"])
        if "floorplan_3d" in merged:
            merged["floorplan_3d"] = bool(merged["floorplan_3d"])
        if "floorplan_view_mode" in merged:
            merged["floorplan_view_mode"] = "3d" if str(merged["floorplan_view_mode"]).lower() == "3d" else "2d"
        if "floorplan_walls_enabled" in merged:
            merged["floorplan_walls_enabled"] = bool(merged["floorplan_walls_enabled"])
        if "floorplan_wall_height" in merged:
            try:
                merged["floorplan_wall_height"] = max(10, min(100, int(merged["floorplan_wall_height"])))
            except (ValueError, TypeError):
                merged["floorplan_wall_height"] = 36
        if "floorplan_azimuth" in merged:
            try:
                merged["floorplan_azimuth"] = float(merged["floorplan_azimuth"]) % 360
            except (ValueError, TypeError):
                merged["floorplan_azimuth"] = 0
        if "floorplan_pitch" in merged:
            try:
                merged["floorplan_pitch"] = max(30, min(75, float(merged["floorplan_pitch"])))
            except (ValueError, TypeError):
                merged["floorplan_pitch"] = 30
        if "dismissed_recommendation_ids" in merged:
            if isinstance(merged["dismissed_recommendation_ids"], (list, set, tuple)):
                merged["dismissed_recommendation_ids"] = list(dict.fromkeys(str(x) for x in merged["dismissed_recommendation_ids"] if x))
            else:
                merged["dismissed_recommendation_ids"] = []

        if "wizard_state" in new_rules and isinstance(new_rules["wizard_state"], dict):
            merged["wizard_state"] = dict(new_rules["wizard_state"])
        if "person_profiles" in new_rules and isinstance(new_rules["person_profiles"], dict):
            merged["person_profiles"] = dict(new_rules["person_profiles"])

        self._rules = merged
        await self._store.async_save(self._rules)
        self._sync_audio_follow_switch()
        self._sync_voice_announcements_switch()
        _LOGGER.info(
            "Otis AI: Saved user behavioral rules (persona: %s, onboarding_completed: %s)",
            self._rules.get("persona"),
            self._rules.get("onboarding_completed"),
        )
        return dict(self._rules)

    async def async_dismiss_recommendation(self, rec_id: str) -> list[str]:
        """Add a recommendation ID to the persistent dismissed list."""
        if not self._loaded:
            await self.async_load()
        current = list(self._rules.get("dismissed_recommendation_ids") or [])
        rec_id_str = str(rec_id).strip()
        if rec_id_str and rec_id_str not in current:
            current.append(rec_id_str)
            self._rules["dismissed_recommendation_ids"] = current
            await self._store.async_save(self._rules)
            _LOGGER.info("Otis AI: Dismissed recommendation '%s'", rec_id_str)
        return list(self._rules.get("dismissed_recommendation_ids") or [])

    async def async_restore_recommendation(self, rec_id: str) -> list[str]:
        """Restore a single previously dismissed recommendation ID."""
        if not self._loaded:
            await self.async_load()
        current = list(self._rules.get("dismissed_recommendation_ids") or [])
        rec_id_str = str(rec_id).strip()
        if rec_id_str in current:
            current = [x for x in current if x != rec_id_str]
            self._rules["dismissed_recommendation_ids"] = current
            await self._store.async_save(self._rules)
            _LOGGER.info("Otis AI: Restored recommendation '%s'", rec_id_str)
        return list(self._rules.get("dismissed_recommendation_ids") or [])

    async def async_reset_dismissed_recommendations(self) -> None:
        """Clear all dismissed recommendations, restoring them to the feed."""
        if not self._loaded:
            await self.async_load()
        self._rules["dismissed_recommendation_ids"] = []
        await self._store.async_save(self._rules)
        _LOGGER.info("Otis AI: Reset all dismissed recommendations")

    def get_dismissed_recommendations(self) -> list[str]:
        """Return list of dismissed recommendation IDs."""
        return list(self._rules.get("dismissed_recommendation_ids") or [])

    def get_rules(self) -> dict[str, Any]:
        """Return the current behavioral rules."""
        return dict(self._rules)

    def _sync_audio_follow_switch(self) -> None:
        """Publish switch.otis_audio_follow state in Home Assistant."""
        if hasattr(self.hass, "states") and hasattr(self.hass.states, "async_set"):
            enabled = bool(self._rules.get("audio_follow_enabled", True))
            self.hass.states.async_set(
                "switch.otis_audio_follow",
                "on" if enabled else "off",
                {
                    "friendly_name": "Otis Audio Follow-Me",
                    "icon": "mdi:cast-connected",
                    "assumed_state": False,
                    "description": "Enables or disables autonomous room-to-room audio migration.",
                },
            )

    def _sync_voice_announcements_switch(self) -> None:
        """Publish switch.otis_voice_announcements state in Home Assistant."""
        if hasattr(self.hass, "states") and hasattr(self.hass.states, "async_set"):
            enabled = bool(self._rules.get("voice_announcements_enabled", True))
            self.hass.states.async_set(
                "switch.otis_voice_announcements",
                "on" if enabled else "off",
                {
                    "friendly_name": "Otis Proactive Voice Announcements",
                    "icon": "mdi:volume-high" if enabled else "mdi:volume-off",
                    "assumed_state": False,
                    "description": "Enables or disables proactive spoken voice announcements for security and camera events.",
                },
            )

    async def async_update_person_profile(
        self,
        person_id: str,
        label: str | None = None,
        entity_type: str = "resident",  # resident, pet, guest, ignored
        training_enabled: bool = True,
    ) -> dict[str, Any]:
        """Update or create a managed person/pet profile."""
        if not self._loaded:
            await self.async_load()

        profiles = dict(self._rules.get("person_profiles") or {})
        clean_pid = str(person_id).strip().lower()
        profile = profiles.get(clean_pid, {
            "person_id": clean_pid,
            "label": label or clean_pid.replace("person.", "").title(),
            "confidence": 0.50,
            "samples": 0,
            "tracks": [],
            "features": {},
        })
        if label:
            profile["label"] = str(label).strip()
        profile["entity_type"] = entity_type
        profile["training_enabled"] = bool(training_enabled)

        profiles[clean_pid] = profile
        self._rules["person_profiles"] = profiles
        await self._store.async_save(self._rules)
        _LOGGER.info(
            "Otis AI: Updated person/pet profile %s (type: %s, training: %s)",
            clean_pid,
            entity_type,
            training_enabled,
        )
        return {"success": True, "person_id": clean_pid, "profile": profile}

    async def async_remove_person_profile(self, person_id: str) -> dict[str, Any]:
        """Remove a person/pet profile from recognition training."""
        if not self._loaded:
            await self.async_load()

        profiles = dict(self._rules.get("person_profiles") or {})
        clean_pid = str(person_id).strip().lower()
        if clean_pid in profiles:
            del profiles[clean_pid]
            self._rules["person_profiles"] = profiles
            await self._store.async_save(self._rules)
            _LOGGER.info("Otis AI: Removed person profile %s", clean_pid)
            return {"success": True, "person_id": clean_pid}
        return {"success": False, "error": f"Profile {clean_pid} not found"}

    async def async_confirm_person_identity(
        self,
        person_id: str,
        track_id: str | None = None,
        label: str | None = None,
        confirmed: bool = True,
        visual_features: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record verified person training feedback to link camera tracks with Home Assistant users."""
        if not self._loaded:
            await self.async_load()

        profiles = dict(self._rules.get("person_profiles") or {})
        clean_pid = str(person_id).strip().lower()
        profile = profiles.get(clean_pid, {
            "person_id": clean_pid,
            "label": label or clean_pid.replace("person.", "").title(),
            "confidence": 0.50,
            "samples": 0,
            "tracks": [],
            "features": {},
        })

        if confirmed:
            profile["samples"] = int(profile.get("samples", 0)) + 1
            cur_conf = float(profile.get("confidence", 0.50))
            profile["confidence"] = round(min(0.99, cur_conf + 0.10), 2)
            if label:
                profile["label"] = str(label).strip()
            if track_id:
                tr_list = list(profile.get("tracks") or [])
                if track_id not in tr_list:
                    tr_list.append(track_id)
                profile["tracks"] = tr_list[-20:]
            if visual_features and isinstance(visual_features, dict):
                feats = dict(profile.get("features") or {})
                feats.update(visual_features)
                profile["features"] = feats
        else:
            cur_conf = float(profile.get("confidence", 0.50))
            profile["confidence"] = round(max(0.10, cur_conf - 0.15), 2)

        profiles[clean_pid] = profile
        self._rules["person_profiles"] = profiles
        await self._store.async_save(self._rules)
        _LOGGER.info(
            "Otis AI: Updated person profile for %s (confirmed: %s, confidence: %.2f)",
            clean_pid,
            confirmed,
            profile["confidence"],
        )
        return {
            "success": True,
            "person_id": clean_pid,
            "profile": profile,
        }

    def get_person_profiles(self) -> dict[str, Any]:
        """Return all persisted person profiles and verification confidence levels."""
        return dict(self._rules.get("person_profiles") or {})

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

        d_layout = self._rules.get("dashboard_layout", "modern_sections").replace("_", " ").title()
        n_style = self._rules.get("navigation_style", "sleek_buttons").replace("_", " ").title()
        lines.append(f"- Dashboard & Layout Preference: {d_layout} with {n_style}.")

        if custom_inst:
            lines.append(f"- Custom Household Rules & Notes:\n{custom_inst}")

        return "\n".join(lines)

