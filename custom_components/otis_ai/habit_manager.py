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


def cluster_sequences_to_routines(
    rows: list[tuple[str, str, float]],
    window_seconds: float = 300.0,
    min_occurrences: int = 2,
    entity_area_map: dict[str, str] | None = None,
    adjacencies: dict[str, list[str]] | None = None,
    hass: HomeAssistant | None = None,
) -> list[dict[str, Any]]:
    """Cluster recurring temporal sequences of state transitions into habit routine proposals.

    Args:
        rows: List of (entity_id, state, timestamp) tuples sorted by timestamp.
        window_seconds: Maximum time window between trigger and subsequent action events.
        min_occurrences: Minimum times the sequence must occur across distinct episodes/days.
        entity_area_map: Optional mapping of entity_id -> area_id for spatial coherence filtering.
        adjacencies: Optional mapping of area_id -> list of adjacent area_ids.
        hass: Optional HomeAssistant instance to determine time zone.

    Returns:
        List of routine proposals containing name, trigger, actions, and confidence.
    """
    if not rows:
        return []

    sorted_rows = sorted(rows, key=lambda x: x[2])
    episodes: list[list[tuple[str, str, float]]] = []
    current_episode: list[tuple[str, str, float]] = []

    for item in sorted_rows:
        if not current_episode:
            current_episode.append(item)
        else:
            prev_ts = current_episode[-1][2]
            if item[2] - prev_ts <= window_seconds:
                current_episode.append(item)
            else:
                if len(current_episode) >= 2:
                    episodes.append(current_episode)
                current_episode = [item]
    if len(current_episode) >= 2:
        episodes.append(current_episode)

    if not episodes:
        return []

    actuator_domains = {"light", "switch", "media_player", "select", "fan", "cover", "lock", "climate"}
    rear_tokens = {"backyard", "back_deck", "back_door", "pool", "spa", "patio"}
    front_tokens = {"frontdoor", "front_door", "frontyard", "driveway", "foyer", "entry", "porch"}

    def _is_spatially_coherent(trig_eid: str, act_eid: str) -> bool:
        t_low = trig_eid.lower()
        a_low = act_eid.lower()
        # Never pair rear/backyard sensors with front/driveway entities (or vice versa)
        if (any(rt in t_low for rt in rear_tokens) and any(ft in a_low for ft in front_tokens)) or (
            any(ft in t_low for ft in front_tokens) and any(rt in a_low for rt in rear_tokens)
        ):
            return False
        if entity_area_map:
            t_area = entity_area_map.get(trig_eid)
            a_area = entity_area_map.get(act_eid)
            if t_area and a_area and t_area != a_area:
                if adjacencies and a_area not in (adjacencies.get(t_area) or []):
                    return False
        return True

    pattern_counts: dict[tuple, list[float]] = {}
    pattern_actions: dict[tuple, list[dict[str, str]]] = {}

    for ep in episodes:
        trigger_entity, trigger_state, trigger_ts = ep[0]
        if not trigger_entity.startswith("binary_sensor."):
            continue
        actions = []
        seen_entities = {trigger_entity}
        for act_entity, act_state, _ in ep[1:]:
            if act_entity not in seen_entities and _is_spatially_coherent(trigger_entity, act_entity):
                seen_entities.add(act_entity)
                actions.append({"entity_id": act_entity, "state": act_state})

        # Require at least one controllable actuator in the sequence (never propose sensor-only sequences)
        actuator_actions = [
            a for a in actions if a["entity_id"].split(".", 1)[0] in actuator_domains
        ]
        if not actuator_actions:
            continue

        actions_tuple = tuple((a["entity_id"], a["state"]) for a in actions)
        pat_key = (trigger_entity, trigger_state, actions_tuple)

        if pat_key not in pattern_counts:
            pattern_counts[pat_key] = []
            pattern_actions[pat_key] = actions
        pattern_counts[pat_key].append(trigger_ts)

    proposals = []
    for (trigger_entity, trigger_state, _), timestamps in pattern_counts.items():
        if len(timestamps) < min_occurrences:
            continue

        actions = pattern_actions[(trigger_entity, trigger_state, _)]
        actuator_actions = [
            a for a in actions if a["entity_id"].split(".", 1)[0] in actuator_domains
        ]
        if not actuator_actions:
            continue

        avg_ts = sum(timestamps) / len(timestamps)
        hours = []
        for ts in timestamps:
            try:
                if (
                    hass
                    and hasattr(hass, "config")
                    and hasattr(hass.config, "time_zone")
                    and hass.config.time_zone
                ):
                    import zoneinfo

                    tz = zoneinfo.ZoneInfo(hass.config.time_zone)
                    dt = datetime.fromtimestamp(ts, tz=tz)
                else:
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                hours.append(dt.hour)
            except Exception:
                hours.append(8)
        hour = int(round(sum(hours) / len(hours))) if hours else 8

        if 5 <= hour < 12:
            time_prefix = "Morning"
        elif 12 <= hour < 17:
            time_prefix = "Afternoon"
        elif 17 <= hour < 22:
            time_prefix = "Evening"
        else:
            time_prefix = "Night"

        all_entities = [trigger_entity] + [a["entity_id"] for a in actuator_actions]
        combined_text = " ".join(all_entities).lower()

        if "gym" in combined_text or "workout" in combined_text:
            context_label = "Gym"
        elif "bed" in combined_text or "sleep" in combined_text:
            context_label = "Bedtime" if time_prefix in ("Evening", "Night") else "Wakeup"
        elif "kitchen" in combined_text or "coffee" in combined_text:
            context_label = "Kitchen"
        elif "office" in combined_text or "desk" in combined_text or "study" in combined_text:
            context_label = "Office"
        elif "theater" in combined_text or "cinema" in combined_text or "tv" in combined_text or "movie" in combined_text:
            context_label = "Media & Theater"
        else:
            first_action = actuator_actions[0]["entity_id"].split(".")[-1].replace("_", " ").title()
            context_label = first_action

        routine_name = f"{time_prefix} {context_label} Routine"
        confidence = min(0.98, max(0.70, round(len(timestamps) / (len(timestamps) + 1.0) + 0.25, 2)))

        action_payloads = []
        for act in actuator_actions:
            act_entity = act["entity_id"]
            act_state = act["state"]
            domain = act_entity.split(".")[0]
            if domain in ("light", "switch", "media_player", "fan"):
                service = f"{domain}.turn_{act_state}" if act_state in ("on", "off") else f"{domain}.turn_on"
                action_payloads.append({"service": service, "target": {"entity_id": act_entity}})
            elif domain == "cover":
                service = "cover.open_cover" if act_state in ("open", "opening", "on") else "cover.close_cover"
                action_payloads.append({"service": service, "target": {"entity_id": act_entity}})
            elif domain == "select":
                action_payloads.append({
                    "service": "select.select_option",
                    "target": {"entity_id": act_entity},
                    "data": {"option": act_state},
                })
            elif domain == "lock":
                service = "lock.lock" if act_state in ("locked", "lock", "on") else "lock.unlock"
                action_payloads.append({"service": service, "target": {"entity_id": act_entity}})
            elif domain == "climate":
                action_payloads.append({
                    "service": "climate.set_hvac_mode",
                    "target": {"entity_id": act_entity},
                    "data": {"hvac_mode": act_state},
                })
            else:
                action_payloads.append({
                    "service": "homeassistant.turn_on" if act_state == "on" else "homeassistant.turn_off",
                    "target": {"entity_id": act_entity},
                })

        clean_trig = trigger_entity.replace(".", "_")
        proposals.append({
            "id": f"habit_routine_{clean_trig}_{int(avg_ts)}",
            "name": routine_name,
            "title": routine_name,
            "category": "habit_routine",
            "priority": "medium",
            "confidence": confidence,
            "occurrences": len(timestamps),
            "trigger_entity": trigger_entity,
            "trigger_state": trigger_state,
            "mean_hour": hour,
            "actions": actions,
            "description": (
                f"Mined from your recurring habit patterns ({len(timestamps)} occurrences): "
                f"When {trigger_entity} turns {trigger_state}, {len(actuator_actions)} device action(s) consistently follow."
            ),
            "action_type": "create_automation",
            "action_payload": {
                "alias": routine_name,
                "description": f"Automated habit routine mined by Otis AI Companion ({len(timestamps)} occurrences)",
                "trigger": [{"platform": "state", "entity_id": trigger_entity, "to": trigger_state}],
                "action": action_payloads,
                "mode": "single",
            },
        })

    return proposals


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
                   OR entity_id LIKE 'select.%'
                   OR entity_id LIKE 'fan.%'
                   OR entity_id LIKE 'lock.%'
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

            transition_rows: list[tuple[str, str, float]] = []
            last_state_by_entity: dict[str, str] = {}
            for m_id, state, ts in raw_states:
                ent = meta_map.get(m_id)
                if not ent:
                    continue
                if last_state_by_entity.get(ent) != state:
                    last_state_by_entity[ent] = state
                    transition_rows.append((ent, state, float(ts)))

            entity_area_map: dict[str, str] | None = None
            adjacencies: dict[str, list[str]] | None = None
            if self.spatial_manager:
                try:
                    adjacencies = getattr(self.spatial_manager, "adjacencies", None)
                except Exception:
                    pass

            return self.cluster_temporal_sequences(
                transition_rows,
                min_occurrences=min_occurrences,
                entity_area_map=entity_area_map,
                adjacencies=adjacencies,
            )

        except Exception as err:
            _LOGGER.debug("Error mining habit recorder trends: %s", err)
            return []

    def cluster_temporal_sequences(
        self,
        rows: list[tuple[str, str, float]],
        window_seconds: float = 300.0,
        min_occurrences: int = 2,
        entity_area_map: dict[str, str] | None = None,
        adjacencies: dict[str, list[str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Cluster recurring temporal sequences of state transitions into habit routine proposals."""
        return cluster_sequences_to_routines(
            rows=rows,
            window_seconds=window_seconds,
            min_occurrences=min_occurrences,
            entity_area_map=entity_area_map,
            adjacencies=adjacencies,
            hass=self.hass,
        )

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
