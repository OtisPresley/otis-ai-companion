"""Otis AI Companion: Automated Guest Mode Lifecycle, Lock Code, Climate & Auto-Expiry Manager."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Callable

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, entity_registry as er

try:
    from homeassistant.helpers.event import async_call_later
except ImportError:  # pragma: no cover - lightweight unit test stub
    def async_call_later(hass: Any, delay: float, action: Callable[[Any], Any]) -> Callable[[], None]:
        loop = asyncio.get_running_loop()
        handle = loop.call_later(delay, lambda: asyncio.ensure_future(action(None)))
        return handle.cancel

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DEFAULT_GUEST_LOCK_SLOT = 9
DEFAULT_GUEST_CODE_NAME = "Otis Guest"


def is_guest_mode_active(hass: HomeAssistant) -> bool:
    """Return True if Otis Guest Mode switch or a guest_mode input_boolean is on."""
    if not hasattr(hass, "states"):
        return False
    otis_sw = hass.states.get("switch.otis_guest_mode")
    if otis_sw and str(getattr(otis_sw, "state", "") or "").lower() == "on":
        return True
    for st in hass.states.async_all("input_boolean"):
        eid_low = str(getattr(st, "entity_id", "") or "").lower()
        if ("guest_mode" in eid_low or "guest_visit" in eid_low) and str(
            getattr(st, "state", "") or ""
        ).lower() == "on":
            return True
    return False


class GuestModeManager:
    """Coordinates automated Guest Mode ON/OFF execution and auto-expiry."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        rules_manager: Any,
    ) -> None:
        """Initialize the Guest Mode Manager."""
        self.hass = hass
        self.entry_id = entry_id
        self.rules_manager = rules_manager
        self._auto_off_unsub: Callable[[], None] | None = None

    def cancel_auto_off_timer(self) -> None:
        """Cancel any pending guest mode auto-off timer."""
        if self._auto_off_unsub is not None:
            try:
                self._auto_off_unsub()
            except Exception:
                pass
            self._auto_off_unsub = None

    async def async_restore_timer_on_boot(self) -> None:
        """Re-arm auto-off timer if Guest Mode is active across a restart."""
        if not self.rules_manager:
            return
        rules = await self.rules_manager.async_load()
        if not rules.get("guest_mode_enabled"):
            return
        auto_off_at_str = str(rules.get("guest_mode_auto_off_at") or "").strip()
        if not auto_off_at_str:
            return
        try:
            target_dt = datetime.fromisoformat(auto_off_at_str)
            if target_dt.tzinfo is None:
                target_dt = target_dt.replace(tzinfo=timezone.utc)
            remaining = (target_dt - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                await self.async_deactivate_guest_mode()
            else:
                self._schedule_auto_off_seconds(remaining, target_dt)
        except Exception as err:
            _LOGGER.debug("Could not restore Guest Mode auto-off timer: %s", err)

    def _schedule_auto_off_seconds(self, delay_seconds: float, target_dt: datetime) -> None:
        """Schedule the auto-off callback after delay_seconds."""
        self.cancel_auto_off_timer()

        async def _auto_off_cb(_now: Any) -> None:
            self._auto_off_unsub = None
            _LOGGER.info("Otis Guest Mode auto-off timer expired; deactivating Guest Mode.")
            await self.async_deactivate_guest_mode()

        self._auto_off_unsub = async_call_later(self.hass, max(1.0, delay_seconds), _auto_off_cb)
        self._update_switch_attributes({"auto_off_at": target_dt.isoformat()})

    def _update_switch_attributes(self, attrs: dict[str, Any]) -> None:
        """Update extra state attributes on switch.otis_guest_mode if registered."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry_id, {})
        entities = entry_data.get("entities", {})
        sw = entities.get("switch.otis_guest_mode")
        if sw and hasattr(sw, "async_set_state"):
            sw.async_set_state(sw.is_on, attrs)

    async def async_deactivate_guest_mode(self) -> None:
        """Turn off switch.otis_guest_mode and run OFF transition."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry_id, {})
        entities = entry_data.get("entities", {})
        sw = entities.get("switch.otis_guest_mode")
        if sw and hasattr(sw, "async_turn_off"):
            await sw.async_turn_off()
        else:
            if self.rules_manager and hasattr(self.rules_manager, "async_save"):
                await self.rules_manager.async_save({"guest_mode_enabled": False})
            await self.async_handle_transition(False)

    def _discover_guest_climates(self) -> list[str]:
        """Dynamically discover climate entities in guest-named areas or with guest names."""
        if not hasattr(self.hass, "states"):
            return []
        guest_area_ids: set[str] = set()
        ent_area_map: dict[str, str] = {}
        try:
            area_reg = ar.async_get(self.hass)
            for area in area_reg.async_list_areas():
                if "guest" in str(getattr(area, "name", "") or "").lower():
                    guest_area_ids.add(area.id)
            ent_reg = er.async_get(self.hass)
            for entry in ent_reg.entities.values():
                if entry.area_id:
                    ent_area_map[entry.entity_id] = entry.area_id
        except Exception:
            pass

        matched: list[str] = []
        for st in self.hass.states.async_all("climate"):
            eid = str(getattr(st, "entity_id", "") or "")
            fname = str((getattr(st, "attributes", {}) or {}).get("friendly_name", "") or "")
            if (
                ent_area_map.get(eid) in guest_area_ids
                or "guest" in eid.lower()
                or "guest" in fname.lower()
            ):
                matched.append(eid)
        return matched

    def _get_lock_platform(self, lock_eid: str) -> str | None:
        """Return the integration platform for a lock entity from entity_registry."""
        try:
            ent_reg = er.async_get(self.hass)
            entry = ent_reg.async_get(lock_eid)
            plat = getattr(entry, "platform", None) if entry else None
            if isinstance(plat, str) and plat.strip():
                return plat.strip().lower()
        except Exception:
            pass
        return None

    async def _async_dispatch_lock_code(
        self, lock_eid: str, services: dict[str, Any], action: str, guest_code: str = ""
    ) -> bool:
        """Dynamically discover and invoke the right lock usercode service for lock_eid's platform."""
        platform = self._get_lock_platform(lock_eid)
        plat_services = services.get(platform, {}) if platform else {}

        try:
            if action == "add":
                if "add_code" in plat_services:
                    await self.hass.services.async_call(
                        platform,
                        "add_code",
                        {"name": DEFAULT_GUEST_CODE_NAME, "code": guest_code, "notify_on_use": True},
                        target={"entity_id": lock_eid},
                        blocking=False,
                    )
                    return True
                if "set_lock_usercode" in plat_services:
                    await self.hass.services.async_call(
                        platform,
                        "set_lock_usercode",
                        {"entity_id": lock_eid, "code_slot": DEFAULT_GUEST_LOCK_SLOT, "usercode": guest_code},
                        blocking=False,
                    )
                    return True
                if "set_usercode" in plat_services:
                    await self.hass.services.async_call(
                        platform,
                        "set_usercode",
                        {"entity_id": lock_eid, "code_slot": DEFAULT_GUEST_LOCK_SLOT, "usercode": guest_code},
                        blocking=False,
                    )
                    return True
                for pin_srv in ("create_pin", "set_pin", "add_pin"):
                    if pin_srv in plat_services:
                        await self.hass.services.async_call(
                            platform,
                            pin_srv,
                            {"name": DEFAULT_GUEST_CODE_NAME, "pin": guest_code},
                            target={"entity_id": lock_eid},
                            blocking=False,
                        )
                        return True
                if "set_usercode" in services.get("lock", {}):
                    await self.hass.services.async_call(
                        "lock",
                        "set_usercode",
                        {"entity_id": lock_eid, "code_slot": DEFAULT_GUEST_LOCK_SLOT, "usercode": guest_code},
                        blocking=False,
                    )
                    return True
                if platform is None:
                    if "add_code" in services.get("schlage", {}):
                        await self.hass.services.async_call(
                            "schlage",
                            "add_code",
                            {"name": DEFAULT_GUEST_CODE_NAME, "code": guest_code, "notify_on_use": True},
                            target={"entity_id": lock_eid},
                            blocking=False,
                        )
                        return True
                    if "set_lock_usercode" in services.get("zwave_js", {}):
                        await self.hass.services.async_call(
                            "zwave_js",
                            "set_lock_usercode",
                            {"entity_id": lock_eid, "code_slot": DEFAULT_GUEST_LOCK_SLOT, "usercode": guest_code},
                            blocking=False,
                        )
                        return True
            else:
                if "delete_code" in plat_services:
                    await self.hass.services.async_call(
                        platform,
                        "delete_code",
                        {"name": DEFAULT_GUEST_CODE_NAME},
                        target={"entity_id": lock_eid},
                        blocking=False,
                    )
                    return True
                if "clear_lock_usercode" in plat_services:
                    await self.hass.services.async_call(
                        platform,
                        "clear_lock_usercode",
                        {"entity_id": lock_eid, "code_slot": DEFAULT_GUEST_LOCK_SLOT},
                        blocking=False,
                    )
                    return True
                if "clear_usercode" in plat_services:
                    await self.hass.services.async_call(
                        platform,
                        "clear_usercode",
                        {"entity_id": lock_eid, "code_slot": DEFAULT_GUEST_LOCK_SLOT},
                        blocking=False,
                    )
                    return True
                for pin_srv in ("delete_pin", "clear_pin", "remove_pin"):
                    if pin_srv in plat_services:
                        await self.hass.services.async_call(
                            platform,
                            pin_srv,
                            {"name": DEFAULT_GUEST_CODE_NAME},
                            target={"entity_id": lock_eid},
                            blocking=False,
                        )
                        return True
                if "clear_usercode" in services.get("lock", {}):
                    await self.hass.services.async_call(
                        "lock",
                        "clear_usercode",
                        {"entity_id": lock_eid, "code_slot": DEFAULT_GUEST_LOCK_SLOT},
                        blocking=False,
                    )
                    return True
                if platform is None:
                    if "delete_code" in services.get("schlage", {}):
                        await self.hass.services.async_call(
                            "schlage",
                            "delete_code",
                            {"name": DEFAULT_GUEST_CODE_NAME},
                            target={"entity_id": lock_eid},
                            blocking=False,
                        )
                        return True
                    if "clear_lock_usercode" in services.get("zwave_js", {}):
                        await self.hass.services.async_call(
                            "zwave_js",
                            "clear_lock_usercode",
                            {"entity_id": lock_eid, "code_slot": DEFAULT_GUEST_LOCK_SLOT},
                            blocking=False,
                        )
                        return True
        except Exception as err:
            _LOGGER.debug("Failed %s guest code on %s (%s): %s", action, lock_eid, platform, err)
        return False

    async def _async_program_lock_codes(self, guest_code: str) -> list[str]:
        """Dynamically discover lock usercode services by platform and program temporary guest code."""
        if not guest_code or not hasattr(self.hass, "services") or not hasattr(self.hass, "states"):
            return []
        services = self.hass.services.async_services()
        locks = [
            st.entity_id
            for st in self.hass.states.async_all("lock")
            if st.state not in ("unavailable", "unknown")
        ]
        if not locks:
            return []

        programmed: list[str] = []
        for lock_eid in locks:
            if await self._async_dispatch_lock_code(lock_eid, services, "add", guest_code):
                programmed.append(lock_eid)
        return programmed

    async def _async_clear_lock_codes(self, lock_eids: list[str]) -> list[str]:
        """Dynamically clear temporary guest code from programmed locks by platform."""
        if not lock_eids or not hasattr(self.hass, "services"):
            return []
        services = self.hass.services.async_services()
        cleared: list[str] = []
        for lock_eid in lock_eids:
            if await self._async_dispatch_lock_code(lock_eid, services, "delete"):
                cleared.append(lock_eid)
        return cleared

    async def _async_apply_guest_climate(self, existing_snapshot: dict[str, Any]) -> dict[str, Any]:
        """Snapshot guest-area thermostats and apply comfortable climate settings."""
        if not hasattr(self.hass, "services") or not hasattr(self.hass, "states"):
            return existing_snapshot
        guest_climates = self._discover_guest_climates()
        if not guest_climates:
            return existing_snapshot

        snapshot = dict(existing_snapshot or {})
        is_celsius = False
        try:
            temp_unit = str(getattr(self.hass.config.units, "temperature_unit", "°F") or "°F")
            is_celsius = "C" in temp_unit.upper()
        except Exception:
            pass
        comfort_temp = 21.0 if is_celsius else 70.0

        for eid in guest_climates:
            st = self.hass.states.get(eid)
            if not st:
                continue
            attrs = dict(getattr(st, "attributes", {}) or {})
            if eid not in snapshot:
                snapshot[eid] = {
                    "hvac_mode": st.state,
                    "temperature": attrs.get("temperature"),
                    "target_temp_high": attrs.get("target_temp_high"),
                    "target_temp_low": attrs.get("target_temp_low"),
                    "preset_mode": attrs.get("preset_mode"),
                }
            hvac_modes = [str(m).lower() for m in (attrs.get("hvac_modes") or [])]
            try:
                if str(st.state).lower() == "off" and hvac_modes:
                    target_mode = (
                        "heat_cool"
                        if "heat_cool" in hvac_modes
                        else ("auto" if "auto" in hvac_modes else next((m for m in hvac_modes if m != "off"), None))
                    )
                    if target_mode:
                        await self.hass.services.async_call(
                            "climate",
                            "set_hvac_mode",
                            {"entity_id": eid, "hvac_mode": target_mode},
                            blocking=False,
                        )
                preset = str(attrs.get("preset_mode") or "").lower()
                preset_modes = [str(p).lower() for p in (attrs.get("preset_modes") or [])]
                if preset == "eco" and "none" in preset_modes:
                    await self.hass.services.async_call(
                        "climate",
                        "set_preset_mode",
                        {"entity_id": eid, "preset_mode": "none"},
                        blocking=False,
                    )
                elif attrs.get("temperature") is not None:
                    await self.hass.services.async_call(
                        "climate",
                        "set_temperature",
                        {"entity_id": eid, "temperature": comfort_temp},
                        blocking=False,
                    )
            except Exception as err:
                _LOGGER.debug("Could not set guest climate comfort on %s: %s", eid, err)

        return snapshot

    async def _async_restore_guest_climate(self, snapshot: dict[str, Any]) -> None:
        """Restore snapshotted guest-area thermostats when Guest Mode ends."""
        if not snapshot or not hasattr(self.hass, "services"):
            return
        for eid, snap in snapshot.items():
            if not isinstance(snap, dict):
                continue
            try:
                hvac_mode = snap.get("hvac_mode")
                if hvac_mode and hvac_mode not in ("unknown", "unavailable"):
                    await self.hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": eid, "hvac_mode": hvac_mode},
                        blocking=False,
                    )
                if snap.get("preset_mode"):
                    await self.hass.services.async_call(
                        "climate",
                        "set_preset_mode",
                        {"entity_id": eid, "preset_mode": snap["preset_mode"]},
                        blocking=False,
                    )
                if snap.get("temperature") is not None:
                    await self.hass.services.async_call(
                        "climate",
                        "set_temperature",
                        {"entity_id": eid, "temperature": snap["temperature"]},
                        blocking=False,
                    )
                elif snap.get("target_temp_high") is not None and snap.get("target_temp_low") is not None:
                    await self.hass.services.async_call(
                        "climate",
                        "set_temperature",
                        {
                            "entity_id": eid,
                            "target_temp_high": snap["target_temp_high"],
                            "target_temp_low": snap["target_temp_low"],
                        },
                        blocking=False,
                    )
            except Exception as err:
                _LOGGER.debug("Could not restore guest climate %s: %s", eid, err)

    async def async_handle_transition(self, enabled: bool) -> dict[str, Any]:
        """Execute automated Guest Mode ON or OFF actions."""
        rules = await self.rules_manager.async_load() if self.rules_manager else {}
        wizard = rules.get("wizard_state") or {}
        summary: dict[str, Any] = {"enabled": enabled, "locks": [], "climates": [], "auto_off_hours": 0}

        if enabled:
            guest_code = str(wizard.get("guestLockCode") or "").strip()
            programmed_locks = await self._async_program_lock_codes(guest_code)
            summary["locks"] = programmed_locks

            snapshot = dict(rules.get("guest_mode_climate_snapshot") or {})
            if wizard.get("guestClimateComfort", True):
                snapshot = await self._async_apply_guest_climate(snapshot)
                summary["climates"] = list(snapshot.keys())

            auto_off_hours = int(
                rules.get("guest_mode_auto_off_hours")
                or wizard.get("guestAutoOffHours")
                or 0
            )
            summary["auto_off_hours"] = auto_off_hours
            updates: dict[str, Any] = {
                "guest_mode_enabled": True,
                "guest_mode_programmed_locks": programmed_locks,
                "guest_mode_climate_snapshot": snapshot,
            }
            if auto_off_hours > 0:
                target_dt = datetime.now(timezone.utc) + timedelta(hours=auto_off_hours)
                updates["guest_mode_auto_off_at"] = target_dt.isoformat()
                self._schedule_auto_off_seconds(auto_off_hours * 3600.0, target_dt)
            else:
                self.cancel_auto_off_timer()
                updates["guest_mode_auto_off_at"] = ""
                self._update_switch_attributes({"auto_off_at": None})

            if self.rules_manager and hasattr(self.rules_manager, "async_save"):
                await self.rules_manager.async_save(updates)
            _LOGGER.info(
                "Otis Guest Mode activated (locks=%d, climates=%d, auto_off_hours=%d)",
                len(programmed_locks),
                len(summary["climates"]),
                auto_off_hours,
            )
        else:
            self.cancel_auto_off_timer()
            programmed_locks = list(rules.get("guest_mode_programmed_locks") or [])
            cleared_locks = await self._async_clear_lock_codes(programmed_locks)
            summary["locks"] = cleared_locks

            snapshot = dict(rules.get("guest_mode_climate_snapshot") or {})
            await self._async_restore_guest_climate(snapshot)
            summary["climates"] = list(snapshot.keys())

            self._update_switch_attributes({"auto_off_at": None})
            if self.rules_manager and hasattr(self.rules_manager, "async_save"):
                await self.rules_manager.async_save(
                    {
                        "guest_mode_enabled": False,
                        "guest_mode_programmed_locks": [],
                        "guest_mode_climate_snapshot": {},
                        "guest_mode_auto_off_at": "",
                    }
                )
            _LOGGER.info(
                "Otis Guest Mode deactivated (cleared_locks=%d, restored_climates=%d)",
                len(cleared_locks),
                len(summary["climates"]),
            )
        return summary
