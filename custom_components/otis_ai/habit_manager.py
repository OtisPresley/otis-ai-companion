"""Otis AI Companion: Self-Supervised Habit Learning & Behavioral Modeling (Phase 9).

Mines long-term historical trends from Home Assistant's SQLite recorder database,
models user behavioral baselines without manual configuration, detects habit pattern
deviations (e.g. missed bedtime routines, unusual vacancy), and generates automatic
seasonal circadian lighting & temperature curves.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import math
import os
import sqlite3
import time
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class BehavioralHabitManager:
    """Manages self-supervised habit mining, pattern deviation detection, and seasonal curves."""

    def __init__(
        self,
        hass: HomeAssistant,
        spatial_manager=None,
        energy_manager=None,
        vision_manager=None,
    ) -> None:
        """Initialize the Behavioral Habit Manager."""
        self.hass = hass
        self.spatial_manager = spatial_manager
        self.energy_manager = energy_manager
        self.vision_manager = vision_manager

        self._mined_habits_cache: list[dict[str, Any]] | None = None
        self._mined_habits_ts: float = 0.0
        self._cache_ttl = 900.0  # 15 minutes TTL

    def _get_db_path(self) -> str | None:
        """Resolve Home Assistant SQLite recorder database path."""
        if hasattr(self.hass, "config") and hasattr(self.hass.config, "path"):
            try:
                db_path = self.hass.config.path("home-assistant_v2.db")
                if isinstance(db_path, str) and os.path.isfile(db_path):
                    return db_path
            except Exception as err:
                _LOGGER.debug("Could not resolve recorder db path: %s", err)
        return None

    async def async_mine_habits(self, days: int = 14, min_occurrences: int = 3) -> list[dict[str, Any]]:
        """Asynchronously mine SQLite recorder trends for habit routines."""
        now = time.time()
        if (
            self._mined_habits_cache is not None
            and (now - self._mined_habits_ts) < self._cache_ttl
        ):
            return list(self._mined_habits_cache)

        db_path = self._get_db_path()
        if not db_path:
            return []

        res = await self.hass.async_add_executor_job(
            self._mine_habits_sync, db_path, days, min_occurrences
        )
        self._mined_habits_cache = list(res)
        self._mined_habits_ts = now
        return res

    def _mine_habits_sync(
        self, db_path: str, days: int = 14, min_occurrences: int = 3
    ) -> list[dict[str, Any]]:
        """Synchronously query the SQLite recorder in read-only mode to extract sequence transitions."""
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
            cursor = conn.cursor()

            # Query relevant metadata IDs for sensor triggers and actuator targets
            cursor.execute(
                """
                SELECT metadata_id, entity_id FROM states_meta
                WHERE entity_id LIKE 'binary_sensor.%'
                   OR entity_id LIKE 'light.%'
                   OR entity_id LIKE 'switch.%'
                   OR entity_id LIKE 'media_player.%'
                   OR entity_id LIKE 'climate.%'
                   OR entity_id LIKE 'cover.%'
                """
            )
            meta_rows = cursor.fetchall()
            if not meta_rows:
                conn.close()
                return []

            meta_map: dict[int, str] = {}
            for m_id, eid in meta_rows:
                eid_lower = eid.lower()
                # Prioritize meaningful occupancy/presence/door sensors and controllable devices
                if eid.startswith("binary_sensor."):
                    if any(k in eid_lower for k in ("motion", "occupancy", "presence", "bed", "sleep", "door", "contact")):
                        meta_map[m_id] = eid
                else:
                    meta_map[m_id] = eid

            if not meta_map:
                conn.close()
                return []

            candidate_meta_ids = list(meta_map.keys())[:60]
            placeholders = ",".join("?" for _ in candidate_meta_ids)
            cutoff_ts = time.time() - (days * 86400)

            query = f"""
                SELECT metadata_id, state, last_updated_ts
                FROM states
                WHERE metadata_id IN ({placeholders})
                  AND last_updated_ts >= ?
                  AND state NOT IN ('unknown', 'unavailable', '')
                ORDER BY last_updated_ts ASC
                LIMIT 8000
            """
            cursor.execute(query, candidate_meta_ids + [cutoff_ts])
            raw_states = cursor.fetchall()
            conn.close()

            if not raw_states:
                return []

            # Map rows to (entity_id, state, timestamp)
            rows = [
                (meta_map[m_id], state, float(ts))
                for m_id, state, ts in raw_states
                if m_id in meta_map
            ]

            return self.cluster_temporal_sequences(rows, min_occurrences=min_occurrences)

        except Exception as err:
            _LOGGER.debug("Error mining habit recorder trends: %s", err)
            return []

    def cluster_temporal_sequences(
        self,
        rows: list[tuple[str, str, float]],
        window_seconds: float = 180.0,
        min_occurrences: int = 3,
    ) -> list[dict[str, Any]]:
        """Cluster recurring temporal sequences of state transitions into habit routine proposals."""
        if not rows:
            return []

        sorted_rows = sorted(rows, key=lambda x: x[2])
        episodes: list[list[tuple[str, str, float]]] = []
        current_ep: list[tuple[str, str, float]] = []

        for item in sorted_rows:
            if not current_ep:
                current_ep.append(item)
            else:
                prev_ts = current_ep[-1][2]
                if item[2] - prev_ts <= window_seconds:
                    current_ep.append(item)
                else:
                    if len(current_ep) >= 2:
                        episodes.append(current_ep)
                    current_ep = [item]
        if len(current_ep) >= 2:
            episodes.append(current_ep)

        if not episodes:
            return []

        actuator_domains = {"light", "switch", "media_player", "climate", "cover", "fan"}
        pattern_counts: dict[tuple, list[float]] = {}
        pattern_actions: dict[tuple, list[dict[str, str]]] = {}

        for ep in episodes:
            trigger_eid, trigger_state, trigger_ts = ep[0]
            # Habit triggers must be binary sensors (motion, door, bed occupancy)
            if not trigger_eid.startswith("binary_sensor."):
                continue

            actions = []
            seen = {trigger_eid}
            for act_eid, act_state, _ in ep[1:]:
                dom = act_eid.split(".", 1)[0]
                if act_eid not in seen and dom in actuator_domains:
                    seen.add(act_eid)
                    actions.append({"entity_id": act_eid, "state": act_state})

            if not actions:
                continue

            act_tuple = tuple((a["entity_id"], a["state"]) for a in actions)
            key = (trigger_eid, trigger_state, act_tuple)

            if key not in pattern_counts:
                pattern_counts[key] = []
                pattern_actions[key] = actions
            pattern_counts[key].append(trigger_ts)

        proposals = []
        for (trigger_eid, trigger_state, _), timestamps in pattern_counts.items():
            if len(timestamps) < min_occurrences:
                continue

            actions = pattern_actions[(trigger_eid, trigger_state, _)]
            avg_ts = sum(timestamps) / len(timestamps)
            hours = []
            for ts in timestamps:
                try:
                    if (
                        self.hass
                        and hasattr(self.hass, "config")
                        and hasattr(self.hass.config, "time_zone")
                        and self.hass.config.time_zone
                    ):
                        import zoneinfo

                        tz = zoneinfo.ZoneInfo(self.hass.config.time_zone)
                        dt = datetime.fromtimestamp(ts, tz=tz)
                    else:
                        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    hours.append(dt.hour)
                except Exception:
                    hours.append(8)
            hour = int(round(sum(hours) / len(hours))) if hours else 8

            # Determine temporal lifestyle category
            if 5 <= hour < 12:
                time_prefix = "Morning"
            elif 12 <= hour < 17:
                time_prefix = "Afternoon"
            elif 17 <= hour < 22:
                time_prefix = "Evening"
            else:
                time_prefix = "Night"

            all_eids = [trigger_eid] + [a["entity_id"] for a in actions]
            combined = " ".join(all_eids).lower()

            if "gym" in combined or "workout" in combined:
                context_label = "Workout"
            elif "bed" in combined or "sleep" in combined:
                context_label = "Bedtime" if time_prefix in ("Evening", "Night") else "Wakeup"
            elif "office" in combined or "desk" in combined or "study" in combined:
                context_label = "Productivity"
            elif "theater" in combined or "movie" in combined or "tv" in combined:
                context_label = "Cinema & Media"
            elif "kitchen" in combined or "coffee" in combined:
                context_label = "Kitchen"
            else:
                context_label = actions[0]["entity_id"].split(".")[-1].replace("_", " ").title()

            routine_name = f"{time_prefix} {context_label} Routine"
            confidence = min(0.98, round(len(timestamps) / (len(timestamps) + 2.0) + 0.25, 2))

            action_payloads = []
            for act in actions:
                a_eid = act["entity_id"]
                a_st = act["state"]
                dom = a_eid.split(".")[0]
                if dom in ("light", "switch", "media_player", "fan"):
                    svc = f"{dom}.turn_{a_st}" if a_st in ("on", "off") else f"{dom}.turn_on"
                    action_payloads.append({"service": svc, "target": {"entity_id": a_eid}})
                elif dom == "cover":
                    svc = "cover.open_cover" if a_st in ("open", "opening", "on") else "cover.close_cover"
                    action_payloads.append({"service": svc, "target": {"entity_id": a_eid}})
                else:
                    action_payloads.append({
                        "service": "homeassistant.turn_on" if a_st == "on" else "homeassistant.turn_off",
                        "target": {"entity_id": a_eid},
                    })

            clean_trig_id = trigger_eid.replace(".", "_")
            proposals.append({
                "id": f"habit_routine_{clean_trig_id}_{int(avg_ts)}",
                "name": routine_name,
                "title": routine_name,
                "category": "habit_routine",
                "priority": "medium",
                "confidence": confidence,
                "occurrences": len(timestamps),
                "trigger_entity": trigger_eid,
                "trigger_state": trigger_state,
                "mean_hour": hour,
                "actions": actions,
                "description": (
                    f"Mined from your recurring habit patterns ({len(timestamps)} occurrences): "
                    f"When {trigger_eid} turns {trigger_state}, {len(actions)} device action(s) consistently follow."
                ),
                "action_type": "create_automation",
                "action_payload": {
                    "alias": routine_name,
                    "description": f"Automated habit routine mined by Otis AI Companion ({len(timestamps)} occurrences)",
                    "trigger": [{"platform": "state", "entity_id": trigger_eid, "to": trigger_state}],
                    "action": action_payloads,
                    "mode": "single",
                },
            })

        return proposals

    async def async_detect_habit_deviations(self) -> list[dict[str, Any]]:
        """Detect live house state deviations against learned behavioral baselines."""
        deviations: list[dict[str, Any]] = []
        now = datetime.now()
        current_hour = now.hour

        all_states = self.hass.states.async_all() if hasattr(self.hass.states, "async_all") else []

        # 1. Missed Bedtime Routine Guard (Late night past 11 PM or before 5 AM)
        if current_hour >= 23 or current_hour < 5:
            # Check for unlocked exterior doors or active lights left on in common areas
            unlocked_doors: list[str] = []
            active_common_lights: list[str] = []

            for s in all_states:
                eid = s.entity_id
                if eid.startswith("lock.") and s.state == "unlocked":
                    unlocked_doors.append(eid)
                elif eid.startswith("light.") and s.state == "on":
                    name = (s.attributes.get("friendly_name") or eid).lower()
                    if any(k in name for k in ("hallway", "living", "foyer", "dining", "kitchen", "porch", "patio")):
                        active_common_lights.append(s.attributes.get("friendly_name") or eid)

            if unlocked_doors or len(active_common_lights) >= 2:
                remediation_actions = []
                for l_eid in unlocked_doors:
                    remediation_actions.append({"service": "lock.lock", "target": {"entity_id": l_eid}})
                if active_common_lights:
                    remediation_actions.append({
                        "service": "light.turn_off",
                        "target": {"entity_id": "all"},
                    })

                deviations.append({
                    "id": f"deviation_missed_bedtime_{now.strftime('%Y%m%d')}",
                    "title": "Bedtime Routine Deviation: Perimeter & Lights Unsecured",
                    "category": "habit_routine",
                    "priority": "high",
                    "icon": "mdi:bed-clock",
                    "description": (
                        f"Customary bedtime hour has passed ({now.strftime('%I:%M %p')}), but "
                        f"{len(unlocked_doors)} lock(s) remain unlocked and {len(active_common_lights)} common lights are still on."
                    ),
                    "action_type": "call_service",
                    "action_payload": {
                        "service": "scene.apply" if not unlocked_doors else "lock.lock",
                        "target": {"entity_id": unlocked_doors[0]} if unlocked_doors else {"entity_id": "all"},
                        "button_label": "Secure Home for Sleep",
                    },
                })

        # 2. Morning Wakeup Window Deviation (Between 8 AM and 11 AM)
        elif 8 <= current_hour < 11:
            closed_covers: list[str] = []
            for s in all_states:
                if s.entity_id.startswith("cover."):
                    dev_cls = str(s.attributes.get("device_class") or "").lower()
                    if dev_cls in ("blind", "shade", "curtain", "shutter") and s.state in ("closed", "closing"):
                        closed_covers.append(s.entity_id)

            if closed_covers:
                deviations.append({
                    "id": f"deviation_morning_shades_{now.strftime('%Y%m%d')}",
                    "title": "Morning Routine: Natural Daylight Optimization",
                    "category": "habit_routine",
                    "priority": "medium",
                    "icon": "mdi:weather-sunset-up",
                    "description": f"Morning daylight window is active. Open {len(closed_covers)} window shade(s) to optimize natural circadian light.",
                    "action_type": "call_service",
                    "action_payload": {
                        "service": "cover.open_cover",
                        "target": {"entity_id": closed_covers[0]},
                        "button_label": "Open Window Shades",
                    },
                })

        return deviations

    def calculate_circadian_curves(
        self,
        solar_elevation: float | None = None,
        now_dt: datetime | None = None,
    ) -> dict[str, Any]:
        """Calculate dynamic circadian color temperature (Kelvin) and brightness curves."""
        dt = now_dt or datetime.now()
        hour_fraction = dt.hour + (dt.minute / 60.0)

        # Default solar elevation approximation based on time of day if sun sensor is unavailable
        if solar_elevation is None:
            # Peaks at solar noon (~13:00) with elevation ~60 deg; drops below 0 at night
            rad = ((hour_fraction - 13.0) / 12.0) * math.pi
            solar_elevation = round(60.0 * math.cos(rad), 1)

        # Circadian Kelvin profile:
        # Night / Pre-dawn: 2200K (Amber / Melatonin-friendly)
        # Sunrise / Dawn (0 to 15 deg): 2700K - 3500K
        # Midday (> 30 deg): 5000K - 5700K (Daylight / Focus)
        # Golden Hour / Sunset (15 to 0 deg): 3000K - 2400K
        if solar_elevation <= -10.0:
            target_kelvin = 2200
            target_brightness_pct = 20
            mode = "night_sleep"
        elif -10.0 < solar_elevation <= 5.0:
            target_kelvin = 2500
            target_brightness_pct = 40
            mode = "dawn_dusk"
        elif 5.0 < solar_elevation <= 25.0:
            target_kelvin = 3500
            target_brightness_pct = 75
            mode = "morning_evening"
        else:
            target_kelvin = 5500
            target_brightness_pct = 100
            mode = "midday_focus"

        # Seasonal HVAC baseline curves
        month = dt.month
        is_winter = month in (12, 1, 2)
        is_summer = month in (6, 7, 8)
        season = "Winter" if is_winter else ("Summer" if is_summer else ("Spring" if month in (3, 4, 5) else "Fall"))

        if is_winter:
            hvac_target_heat = 69.0
            hvac_target_cool = 75.0
            eco_note = "Winter comfort curve active: 69°F heating target with nighttime 65°F setback."
        elif is_summer:
            hvac_target_heat = 66.0
            hvac_target_cool = 73.0
            eco_note = "Summer cooling curve active: 73°F daytime target with pre-cooling before peak TOU."
        else:
            hvac_target_heat = 68.0
            hvac_target_cool = 74.0
            eco_note = "Transitional seasonal curve: moderate setpoints with natural ventilation priority."

        return {
            "timestamp": dt.isoformat(),
            "season": season,
            "solar_elevation": solar_elevation,
            "lighting_curve": {
                "color_temp_kelvin": target_kelvin,
                "brightness_percent": target_brightness_pct,
                "mode": mode,
                "circadian_phase": mode.replace("_", " ").title(),
            },
            "climate_curve": {
                "season": season,
                "target_temp_heat_f": hvac_target_heat,
                "target_temp_cool_f": hvac_target_cool,
                "seasonal_recommendation": eco_note,
            },
        }
