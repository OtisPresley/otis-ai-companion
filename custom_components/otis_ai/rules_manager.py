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
    "predictive_preconditioning_enabled": False,
    "preferred_speaker": "",
    "custom_instructions": "",
    "dashboard_layout": "modern_sections",
    "navigation_style": "sleek_buttons",
    "calendar_view": "listDay",
    "primary_content_focus": "balanced",
    "presence_room_cards": True,
    "dismissed_recommendation_ids": [],
    "hidden_recommendation_ids": [],
    "show_ignored_recommendations": False,
    "floorplan_view_mode": "2d",
    "floorplan_3d": False,
    "floorplan_azimuth": 0,
    "floorplan_pitch": 30,
    "floorplan_wall_height": 36,
    "floorplan_walls_enabled": True,
    "floorplan_zone": "all",
    "floorplan_scale": 1.0,
    "voice_announcements_enabled": True,
    "voice_filter_passersby": True,
    "person_profiles": {},
    "ignored_persons": [],
    "wizard_state": {},
    "reasoning_timeout": 60,
    "learned_instructions": [],
    "agent_health_metrics": {},
    "vision_training_feedback": [],
    "recent_room_verifications": {},
    "classified_snapshots": [],
    "excluded_load_shed_entities": [],
    "media_input_mappings": {},
    "media_default_zone": "",
    "media_unjoin_input": "None",
    "migrated_coordinators": {},
}


SENSITIVE_RULE_PATTERNS = (
    "lock_code",
    "guest_code",
    "pin",
    "password",
    "secret",
    "token",
    "credential",
    "api_key",
    "auth_token",
)


def scrub_sensitive_rules(data: Any) -> Any:
    """Recursively scrub lock codes, PINs, passwords, and tokens before event bus publication."""
    if isinstance(data, dict):
        scrubbed = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(p in k_lower for p in SENSITIVE_RULE_PATTERNS):
                scrubbed[k] = "[REDACTED]"
            elif isinstance(v, (dict, list)):
                scrubbed[k] = scrub_sensitive_rules(v)
            elif isinstance(v, str) and any(p in k_lower for p in ("code", "pin")):
                scrubbed[k] = "[REDACTED]"
            else:
                scrubbed[k] = v
        return scrubbed
    elif isinstance(data, list):
        return [scrub_sensitive_rules(item) for item in data]
    return data


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
            if not self._rules.get("onboarding_completed") and (
                (self._rules.get("custom_instructions") and str(self._rules.get("custom_instructions")).strip())
                or (isinstance(self._rules.get("wizard_state"), dict) and len(self._rules.get("wizard_state")) > 0)
                or (isinstance(self._rules.get("person_profiles"), dict) and len(self._rules.get("person_profiles")) > 0)
            ):
                self._rules["onboarding_completed"] = True
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
        if "predictive_preconditioning_enabled" in merged:
            merged["predictive_preconditioning_enabled"] = bool(merged["predictive_preconditioning_enabled"])
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
        if "dashboard_layout" in merged:
            layout_val = str(merged["dashboard_layout"]).lower()
            if layout_val in ("modern_sections", "compact", "classic", "classic_grid"):
                merged["dashboard_layout"] = layout_val
        if "navigation_style" in merged:
            nav_val = str(merged["navigation_style"]).lower()
            if nav_val in ("sleek_buttons", "standard_grid", "compact_pills", "tiles"):
                merged["navigation_style"] = nav_val
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
        if "floorplan_zone" in merged:
            zone_val = str(merged["floorplan_zone"]).strip().lower()
            merged["floorplan_zone"] = zone_val if zone_val in ("all", "main", "upper", "outdoor") else "all"
        if "floorplan_scale" in merged:
            try:
                merged["floorplan_scale"] = max(0.6, min(1.8, float(merged["floorplan_scale"])))
            except (ValueError, TypeError):
                merged["floorplan_scale"] = 1.0
        if "dismissed_recommendation_ids" in merged:
            if isinstance(merged["dismissed_recommendation_ids"], (list, set, tuple)):
                merged["dismissed_recommendation_ids"] = list(dict.fromkeys(str(x) for x in merged["dismissed_recommendation_ids"] if x))
            else:
                merged["dismissed_recommendation_ids"] = []
        if "classified_snapshots" in merged:
            if isinstance(merged["classified_snapshots"], (list, set, tuple)):
                merged["classified_snapshots"] = list(dict.fromkeys(str(x) for x in merged["classified_snapshots"] if x))[-200:]
            else:
                merged["classified_snapshots"] = []
        if "excluded_load_shed_entities" in merged:
            if isinstance(merged["excluded_load_shed_entities"], (list, set, tuple)):
                merged["excluded_load_shed_entities"] = list(dict.fromkeys(str(x).strip().lower() for x in merged["excluded_load_shed_entities"] if x))
            else:
                merged["excluded_load_shed_entities"] = []

        if "wizard_state" in new_rules and isinstance(new_rules["wizard_state"], dict):
            merged["wizard_state"] = dict(new_rules["wizard_state"])
        if "person_profiles" in new_rules and isinstance(new_rules["person_profiles"], dict):
            merged["person_profiles"] = dict(new_rules["person_profiles"])
        if "ignored_persons" in new_rules and isinstance(new_rules["ignored_persons"], (list, set, tuple)):
            merged["ignored_persons"] = list(dict.fromkeys(str(x).strip().lower() for x in new_rules["ignored_persons"] if x))
        elif "ignored_persons" not in merged:
            merged["ignored_persons"] = list(self._rules.get("ignored_persons") or [])
        if "learned_instructions" in new_rules and isinstance(new_rules["learned_instructions"], (list, set, tuple)):
            merged["learned_instructions"] = list(dict.fromkeys(str(x).strip() for x in new_rules["learned_instructions"] if x))[-30:]
        if "agent_health_metrics" in new_rules and isinstance(new_rules["agent_health_metrics"], dict):
            merged["agent_health_metrics"] = dict(new_rules["agent_health_metrics"])
        if "media_input_mappings" in new_rules and isinstance(new_rules["media_input_mappings"], dict):
            merged["media_input_mappings"] = {
                str(k).strip(): str(v).strip()
                for k, v in new_rules["media_input_mappings"].items()
                if str(k).strip() and str(v).strip()
            }
        if "media_default_zone" in new_rules:
            merged["media_default_zone"] = str(new_rules["media_default_zone"] or "").strip()
        if "media_unjoin_input" in new_rules:
            merged["media_unjoin_input"] = str(new_rules["media_unjoin_input"] or "None").strip()

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
        """Return list of dismissed (ignored) recommendation IDs."""
        return list(self._rules.get("dismissed_recommendation_ids") or [])

    async def async_hide_recommendation(self, rec_id: str) -> list[str]:
        """Permanently hide a recommendation ID (via X dismiss or completion) without adding to Ignored."""
        if not self._loaded:
            await self.async_load()
        current = list(self._rules.get("hidden_recommendation_ids") or [])
        rec_id_str = str(rec_id).strip()
        if rec_id_str and rec_id_str not in current:
            current.append(rec_id_str)
            self._rules["hidden_recommendation_ids"] = current
            await self._store.async_save(self._rules)
            _LOGGER.info("Otis AI: Permanently hid recommendation '%s'", rec_id_str)
        return list(self._rules.get("hidden_recommendation_ids") or [])

    def get_hidden_recommendations(self) -> list[str]:
        """Return list of permanently hidden recommendation IDs."""
        return list(self._rules.get("hidden_recommendation_ids") or [])

    def get_rules(self) -> dict[str, Any]:
        """Return the current behavioral rules."""
        return dict(self._rules)

    def _sync_audio_follow_switch(self) -> None:
        """Publish switch.otis_audio_follow state in Home Assistant."""
        if hasattr(self.hass, "states") and hasattr(self.hass.states, "async_set"):
            enabled = bool(self._rules.get("audio_follow_enabled", True))
            state_val = "on" if enabled else "off"
            attrs = {
                "friendly_name": "Otis Audio Follow-Me",
                "icon": "mdi:cast-connected",
                "assumed_state": False,
                "description": "Enables or disables autonomous room-to-room audio migration.",
            }
            try:
                from .sensor import async_update_entity_state
                async_update_entity_state(self.hass, "switch.otis_audio_follow", state_val, attrs)
            except Exception as err:
                _LOGGER.debug("Entity state update notice: %s", err)

    def _sync_voice_announcements_switch(self) -> None:
        """Publish switch.otis_voice_announcements state in Home Assistant."""
        if hasattr(self.hass, "states") and hasattr(self.hass.states, "async_set"):
            enabled = bool(self._rules.get("voice_announcements_enabled", True))
            state_val = "on" if enabled else "off"
            attrs = {
                "friendly_name": "Otis Proactive Voice Announcements",
                "icon": "mdi:volume-high" if enabled else "mdi:volume-off",
                "assumed_state": False,
                "description": "Enables or disables proactive spoken voice announcements for security and camera events.",
            }
            try:
                from .sensor import async_update_entity_state
                async_update_entity_state(self.hass, "switch.otis_voice_announcements", state_val, attrs)
            except Exception as err:
                _LOGGER.debug("Entity state update notice: %s", err)

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
        ignored = list(self._rules.get("ignored_persons") or [])
        if clean_pid in ignored:
            ignored.remove(clean_pid)
            self._rules["ignored_persons"] = ignored

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
        """Remove a person/pet profile from recognition training and add to ignored_persons."""
        if not self._loaded:
            await self.async_load()

        profiles = dict(self._rules.get("person_profiles") or {})
        clean_pid = str(person_id).strip().lower()
        ignored = list(self._rules.get("ignored_persons") or [])

        if clean_pid not in ignored:
            ignored.append(clean_pid)
            self._rules["ignored_persons"] = ignored

        if clean_pid in profiles:
            del profiles[clean_pid]
            self._rules["person_profiles"] = profiles

        await self._store.async_save(self._rules)
        _LOGGER.info("Otis AI: Removed and ignored person profile %s", clean_pid)
        return {"success": True, "person_id": clean_pid}

    def _record_classified_snapshot(self, visual_features: dict[str, Any] | None) -> None:
        """Mark a snapshot key as classified and remove its suggestion ID from dismissed/ignored."""
        if not isinstance(visual_features, dict) or visual_features.get("reset"):
            return
        snap_key = str(visual_features.get("snapshot_key") or "").strip()
        if snap_key:
            classified = list(self._rules.get("classified_snapshots") or [])
            if snap_key in classified:
                classified.remove(snap_key)
            classified.append(snap_key)
            self._rules["classified_snapshots"] = classified[-200:]
        sugg_id = str(visual_features.get("suggestion_id") or "").strip()
        if sugg_id:
            dismissed = list(self._rules.get("dismissed_recommendation_ids") or [])
            if sugg_id in dismissed:
                dismissed.remove(sugg_id)
                self._rules["dismissed_recommendation_ids"] = dismissed

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

        import time
        clean_pid = str(person_id).strip().lower()

        if clean_pid in ("unknown_person", "unknown_animal", "not_person_pet", "false_positive"):
            feedback_log = list(self._rules.get("vision_training_feedback") or [])
            entry = {
                "classification": clean_pid,
                "label": label or clean_pid.replace("_", " ").title(),
                "track_id": track_id,
                "visual_features": visual_features or {},
                "timestamp": time.time(),
            }
            feedback_log.append(entry)
            self._rules["vision_training_feedback"] = feedback_log[-50:]

            if visual_features and isinstance(visual_features, dict) and visual_features.get("area"):
                room_verifications = dict(self._rules.get("recent_room_verifications") or {})
                room_verifications[str(visual_features["area"]).strip().lower()] = time.time()
                self._rules["recent_room_verifications"] = room_verifications
            self._record_classified_snapshot(visual_features)

            await self._store.async_save(self._rules)
            if hasattr(self.hass, "bus") and hasattr(self.hass.bus, "async_fire"):
                try:
                    self.hass.bus.async_fire("otis_ai_rules_updated", {"rules": scrub_sensitive_rules(dict(self._rules))})
                except Exception:
                    pass
            _LOGGER.info(
                "Otis AI: Recorded vision training classification '%s' (features: %s)",
                clean_pid,
                visual_features,
            )
            return {
                "success": True,
                "person_id": clean_pid,
                "classification": clean_pid,
                "feedback": entry,
            }

        profiles = dict(self._rules.get("person_profiles") or {})
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
                area_val = visual_features.get("area")
                if area_val:
                    v_rooms = list(profile.get("verified_rooms") or [])
                    clean_area = str(area_val).strip().lower()
                    if clean_area and clean_area not in v_rooms:
                        v_rooms.append(clean_area)
                    profile["verified_rooms"] = v_rooms[-20:]
                    room_verifications = dict(self._rules.get("recent_room_verifications") or {})
                    room_verifications[clean_area] = time.time()
                    self._rules["recent_room_verifications"] = room_verifications
                feats.update(visual_features)
                profile["features"] = feats
            self._record_classified_snapshot(visual_features)
        else:
            if visual_features and isinstance(visual_features, dict) and visual_features.get("reset"):
                profile["samples"] = 0
                profile["confidence"] = 0.50
                profile["tracks"] = []
                profile["verified_rooms"] = []
            else:
                cur_conf = float(profile.get("confidence", 0.50))
                profile["confidence"] = round(max(0.10, cur_conf - 0.15), 2)
                self._record_classified_snapshot(visual_features)

        profiles[clean_pid] = profile
        self._rules["person_profiles"] = profiles
        await self._store.async_save(self._rules)
        if hasattr(self.hass, "bus") and hasattr(self.hass.bus, "async_fire"):
            try:
                self.hass.bus.async_fire("otis_ai_rules_updated", {"rules": scrub_sensitive_rules(dict(self._rules))})
            except Exception:
                pass
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

    def get_agent_health_metrics(self) -> dict[str, dict[str, Any]]:
        """Return persisted conversation agent availability, latency, and quality metrics."""
        return dict(self._rules.get("agent_health_metrics") or {})

    def get_deprecated_models(self) -> set[str]:
        """Return model identifiers that returned 404/unavailable/deprecated errors on this instance."""
        return {str(m).strip() for m in (self._rules.get("deprecated_models") or []) if str(m).strip()}

    async def async_record_agent_metric(
        self,
        agent_id: str,
        *,
        success: bool,
        latency_s: float = 0.0,
        quality_penalty: int = 0,
        error_reason: str | None = None,
        configured_model: str | None = None,
    ) -> dict[str, Any]:
        """Record live performance, availability, and quality telemetry for a conversation agent."""
        if not self._loaded:
            await self.async_load()

        import time
        metrics_map = dict(self._rules.get("agent_health_metrics") or {})
        clean_id = str(agent_id).strip()
        m = dict(metrics_map.get(clean_id) or {
            "success_count": 0,
            "error_count": 0,
            "consecutive_failures": 0,
            "avg_latency_s": 2.0,
            "quality_penalties": 0,
            "last_error_ts": 0.0,
            "last_error_reason": "",
            "last_success_ts": 0.0,
            "configured_model": "",
        })

        if configured_model:
            prev_model = str(m.get("configured_model") or "").strip()
            if prev_model and prev_model != configured_model:
                # Model changed since last metric; clear stale error/cooldown history
                m["success_count"] = 0
                m["error_count"] = 0
                m["consecutive_failures"] = 0
                m["quality_penalties"] = 0
                m["last_error_ts"] = 0.0
                m["last_error_reason"] = ""
            m["configured_model"] = str(configured_model).strip()

        now_ts = time.time()
        if success:
            m["success_count"] = int(m.get("success_count", 0)) + 1
            m["consecutive_failures"] = 0
            m["last_success_ts"] = now_ts
            prev_lat = float(m.get("avg_latency_s", max(0.5, latency_s)))
            if latency_s > 0:
                m["avg_latency_s"] = round((prev_lat * 0.7) + (latency_s * 0.3), 2)
        else:
            m["error_count"] = int(m.get("error_count", 0)) + 1
            m["consecutive_failures"] = int(m.get("consecutive_failures", 0)) + 1
            m["last_error_ts"] = now_ts
            if error_reason:
                m["last_error_reason"] = str(error_reason)[:160]
                err_low = str(error_reason).lower()
                if configured_model and any(
                    tok in err_low
                    for tok in ("404", "not_found", "not found", "no longer available", "deprecated", "does not exist")
                ):
                    dep_list = list(self._rules.get("deprecated_models") or [])
                    clean_mod = str(configured_model).strip()
                    if clean_mod and clean_mod not in dep_list:
                        dep_list.append(clean_mod)
                        self._rules["deprecated_models"] = dep_list[-50:]

        if quality_penalty > 0:
            m["quality_penalties"] = int(m.get("quality_penalties", 0)) + int(quality_penalty)

        metrics_map[clean_id] = m
        self._rules["agent_health_metrics"] = metrics_map
        await self._store.async_save(self._rules)
        return m

    async def async_reset_agent_metrics_for_model_change(
        self,
        agent_ids: list[str],
        current_model: str,
    ) -> bool:
        """Reset stale failure metrics when an agent's configured model has changed."""
        if not self._loaded:
            await self.async_load()

        clean_model = str(current_model or "").strip()
        if not clean_model:
            return False

        metrics_map = dict(self._rules.get("agent_health_metrics") or {})
        changed = False
        for aid in agent_ids:
            clean_id = str(aid or "").strip()
            if not clean_id or clean_id not in metrics_map:
                continue
            m = dict(metrics_map[clean_id])
            prev_model = str(m.get("configured_model") or "").strip()
            if prev_model != clean_model:
                m["success_count"] = 0
                m["error_count"] = 0
                m["consecutive_failures"] = 0
                m["quality_penalties"] = 0
                m["last_error_ts"] = 0.0
                m["last_error_reason"] = ""
                m["configured_model"] = clean_model
                metrics_map[clean_id] = m
                changed = True

        if changed:
            self._rules["agent_health_metrics"] = metrics_map
            await self._store.async_save(self._rules)
        return changed

    async def async_learn_from_interaction(
        self,
        user_text: str,
        assistant_text: str = "",
        correction_notes: list[str] | None = None,
    ) -> list[str]:
        """Autonomously detect user corrections, household trends, and anti-hallucination guardrails and persist them."""
        if not self._loaded:
            await self.async_load()

        import re
        learned = list(self._rules.get("learned_instructions") or [])
        custom_inst = str(self._rules.get("custom_instructions") or "").strip()
        changed = False

        u_clean = str(user_text or "").strip()
        if u_clean and len(u_clean) <= 320:
            # Detect explicit user teaching / preference / correction patterns
            teaching_patterns = [
                r"(?:please\s+)?remember\s+that\s+(.+)",
                r"(?:always|never|do\s+not|don't)\s+(?:use|turn\s+on|turn\s+off|touch|include|suggest|route|announce)\s+(.+)",
                r"(?:actually|correction)[,:]\s+(.+)",
                r"from\s+now\s+on[,:]?\s+(.+)",
                r"make\s+sure\s+you\s+(?:always|never)\s+(.+)",
            ]
            for pat in teaching_patterns:
                m = re.search(pat, u_clean, re.IGNORECASE)
                if m:
                    rule_sentence = u_clean[0].upper() + u_clean[1:]
                    if not rule_sentence.endswith("."):
                        rule_sentence += "."
                    if rule_sentence not in learned:
                        learned.append(rule_sentence)
                        changed = True
                    if rule_sentence.lower() not in custom_inst.lower():
                        bullet = f"- [Auto-Learned] {rule_sentence}"
                        custom_inst = f"{custom_inst}\n{bullet}".strip() if custom_inst else bullet
                        self._rules["custom_instructions"] = custom_inst
                        changed = True
                    break

        if correction_notes:
            for note in correction_notes:
                clean_note = str(note or "").strip()
                if clean_note and clean_note not in learned:
                    learned.append(clean_note)
                    changed = True

        if changed:
            self._rules["learned_instructions"] = learned[-30:]
            await self._store.async_save(self._rules)
            _LOGGER.info("Otis AI: Autonomously updated learned instructions (%d active rules)", len(self._rules["learned_instructions"]))

        return list(self._rules.get("learned_instructions") or [])

    def get_system_prompt_snippet(self) -> str:
        """Generate a compact, token-efficient behavioral instructions snippet for LLM prompts."""
        p_key = self._rules.get("persona", "concierge")
        persona_desc = PERSONA_PROFILES.get(p_key, PERSONA_PROFILES["concierge"])
        tone = self._rules.get("tone", "friendly")
        length = self._rules.get("response_length", "balanced")
        autonomy = self._rules.get("autonomy_level", "balanced")
        custom_inst = (self._rules.get("custom_instructions") or "").strip()
        learned_inst = list(self._rules.get("learned_instructions") or [])

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

        mappings = self._rules.get("media_input_mappings")
        if isinstance(mappings, dict) and mappings:
            map_str = ", ".join(f"{inp} -> {plr}" for inp, plr in mappings.items() if inp and plr)
            if map_str:
                lines.append(f"- Matrix Audio Input-to-Streamer Mappings: {map_str}.")

        if custom_inst:
            lines.append(f"- Custom Household Rules & Notes:\n{custom_inst}")

        if learned_inst:
            learned_bullets = "\n".join(f"  * {item}" for item in learned_inst[-12:])
            lines.append(f"- Autonomous Learned Guardrails & User Corrections:\n{learned_bullets}")

        return "\n".join(lines)

