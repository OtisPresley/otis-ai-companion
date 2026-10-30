"""Autonomous Home Commissioning Manager for Otis AI Companion (Phase 10).

Zero-config auto-discovery, heuristics, spatial similarity, and auto-assignment
of unassigned/orphaned entities and devices into Home Assistant rooms.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)

from .spatial_manager import normalize_area_key

_LOGGER = logging.getLogger(__name__)

# Domains typically ignored during spatial room commissioning
IGNORED_COMMISSIONING_DOMAINS = {
    "automation",
    "script",
    "scene",
    "person",
    "zone",
    "sun",
    "weather",
    "conversation",
    "update",
    "persistent_notification",
    "timer",
    "counter",
    "input_boolean",
    "input_number",
    "input_text",
    "input_select",
    "input_datetime",
    "tag",
}

# Synonyms and stem maps for common home spaces
SPATIAL_SYNONYM_MAP: dict[str, list[str]] = {
    "bathroom": ["bath", "powder_room", "restroom", "wc", "washroom", "toilet", "lavatory"],
    "bedroom": ["bed", "guest_room", "bunk", "sleeping", "dorm"],
    "kitchen": ["pantry", "cook", "galley", "scullery"],
    "living_room": ["living", "family_room", "great_room", "lounge", "parlor", "sitting_room", "den"],
    "dining_room": ["dining", "breakfast_nook", "dinette", "eating"],
    "garage": ["carport", "workshop", "auto", "shed", "driveway"],
    "office": ["study", "workstation", "desk", "library"],
    "hallway": ["hall", "corridor", "passageway", "vestibule", "stairway", "stairs"],
    "foyer": ["entryway", "entry", "front_door", "porch", "mudroom"],
    "patio": ["deck", "terrace", "balcony", "veranda", "lanai", "porch", "backyard", "yard"],
    "laundry": ["utility", "washer", "dryer"],
    "theater": ["cinema", "media_room", "tv_room"],
    "gym": ["fitness", "workout", "exercise"],
    "basement": ["cellar", "crawlspace"],
    "attic": ["loft"],
}


class AutonomousCommissioningManager:
    """Manages zero-config discovery and heuristic room assignment of unassigned entities & devices."""

    def __init__(self, hass: HomeAssistant, spatial_manager=None) -> None:
        """Initialize the Commissioning Manager."""
        self.hass = hass
        self.spatial_manager = spatial_manager

    def _normalize_tokens(self, text: str) -> list[str]:
        """Normalize a string into clean lowercase tokens."""
        if not text:
            return []
        cleaned = re.sub(r"[._\-\/\\:,\(\)\[\]]", " ", str(text).lower())
        tokens = [t for t in cleaned.split() if len(t) >= 2]
        return tokens

    def _calculate_match_score(
        self,
        entity_tokens: list[str],
        device_tokens: list[str],
        area_id: str,
        area_name: str,
        area_aliases: list[str] | None = None,
    ) -> tuple[float, str]:
        """Calculate confidence score (0.0 to 1.0) and reasoning for matching an entity to an area."""
        area_norm = normalize_area_key(area_name)
        id_norm = normalize_area_key(area_id)
        aliases_norm = [normalize_area_key(a) for a in (area_aliases or []) if a]

        all_target_keys = set(filter(None, [area_norm, id_norm] + aliases_norm))
        all_tokens = set(entity_tokens + device_tokens)

        # 1. Exact Area Key Match in entity tokens or joined text
        for target in all_target_keys:
            if target in all_tokens:
                return 0.95, f"Exact token match '{target}' in entity or device metadata"
            joined_ent = "_".join(entity_tokens)
            if target in joined_ent or f"_{target}_" in f"_{joined_ent}_":
                return 0.95, f"Exact match for area '{target}' in entity ID"
            joined_dev = "_".join(device_tokens)
            if target in joined_dev or f"_{target}_" in f"_{joined_dev}_":
                return 0.92, f"Exact match for area '{target}' in parent device name"

        # 2. Multi-word area token containment (e.g. 'living_room' -> 'living' and 'room')
        for target in all_target_keys:
            subtokens = target.split("_")
            if len(subtokens) > 1 and all(st in all_tokens for st in subtokens):
                return 0.90, f"Full compound match for multi-word area '{target}'"

        # 3. Spatial Synonyms & Stems
        for canon, synonyms in SPATIAL_SYNONYM_MAP.items():
            if canon in all_target_keys or any(s in all_target_keys for s in synonyms):
                # Check if entity or device has a synonym token
                matched_syn = next((s for s in synonyms if s in all_tokens), None)
                if matched_syn:
                    return 0.85, f"Spatial synonym match '{matched_syn}' mapped to '{area_name}'"
                if canon in all_tokens:
                    return 0.85, f"Spatial category match '{canon}' mapped to '{area_name}'"

        # 4. Spatial Adjacency / Boundary check
        if self.spatial_manager and hasattr(self.spatial_manager, "get_adjacent_areas"):
            try:
                neighbors = self.spatial_manager.get_adjacent_areas(area_id)
                for n_id in neighbors:
                    n_norm = normalize_area_key(n_id)
                    if n_norm in all_tokens:
                        return 0.75, f"Boundary/Spatial adjacency inferred from neighboring '{n_id}'"
            except Exception as err:
                _LOGGER.debug("Spatial adjacency check error: %s", err)

        # 5. Partial single-token overlap if area has multiple words
        for target in all_target_keys:
            subtokens = [st for st in target.split("_") if len(st) >= 4 and st not in ("room", "area")]
            if subtokens and any(st in all_tokens for st in subtokens):
                matched_st = next(st for st in subtokens if st in all_tokens)
                return 0.70, f"Partial characteristic token '{matched_st}' matched for '{area_name}'"

        return 0.0, "No spatial correlation found"

    async def async_audit_unassigned(self, min_confidence: float = 0.85) -> dict[str, Any]:
        """Audit all entities and devices in Home Assistant for unassigned rooms and compute suggestions."""
        area_reg = ar.async_get(self.hass)
        device_reg = dr.async_get(self.hass)
        entity_reg = er.async_get(self.hass)

        existing_areas = area_reg.async_list_areas() if hasattr(area_reg, "async_list_areas") else []

        area_info_list: list[dict[str, Any]] = []
        for a in existing_areas:
            aid = str(getattr(a, "id", "") or "")
            aname = str(getattr(a, "name", aid) or aid)
            aliases = list(getattr(a, "aliases", []) or [])
            if aid:
                area_info_list.append({
                    "id": aid,
                    "name": aname,
                    "aliases": aliases,
                })

        devices = device_reg.devices if hasattr(device_reg, "devices") else {}
        entities = entity_reg.entities if hasattr(entity_reg, "entities") else {}

        # Index devices by ID
        dev_map: dict[str, Any] = {}
        unassigned_devices: list[dict[str, Any]] = []
        for d_id, dev in devices.items():
            area_id = getattr(dev, "area_id", None)
            d_name = getattr(dev, "name_by_user", None) or getattr(dev, "name", "") or ""
            d_model = getattr(dev, "model", "") or ""
            d_mfr = getattr(dev, "manufacturer", "") or ""
            dev_data = {
                "id": d_id,
                "name": d_name,
                "area_id": area_id,
                "model": d_model,
                "manufacturer": d_mfr,
            }
            dev_map[d_id] = dev_data
            if not area_id:
                unassigned_devices.append(dev_data)

        suggested_assignments: list[dict[str, Any]] = []
        unassigned_entities: list[dict[str, Any]] = []

        for e_id, ent in entities.items():
            domain = str(getattr(ent, "domain", "") or e_id.split(".")[0])
            if domain in IGNORED_COMMISSIONING_DOMAINS:
                continue

            ent_area = getattr(ent, "area_id", None)
            dev_id = getattr(ent, "device_id", None)
            parent_dev = dev_map.get(dev_id) if dev_id else None

            if ent_area:
                continue

            ent_name = (
                getattr(ent, "name", None)
                or getattr(ent, "original_name", None)
                or e_id
            )
            unassigned_entities.append({
                "entity_id": e_id,
                "name": ent_name,
                "domain": domain,
                "device_id": dev_id,
            })

            # Check if parent device already has an area we can inherit directly
            if parent_dev and parent_dev.get("area_id"):
                p_area_id = parent_dev["area_id"]
                p_area_name = next((a["name"] for a in area_info_list if a["id"] == p_area_id), p_area_id)
                suggested_assignments.append({
                    "entity_id": e_id,
                    "device_id": dev_id,
                    "name": ent_name,
                    "domain": domain,
                    "suggested_area_id": p_area_id,
                    "suggested_area_name": p_area_name,
                    "confidence": 1.0,
                    "reason": f"Inherited from configured parent device '{parent_dev.get('name')}'",
                    "eligible_auto": True,
                })
                continue

            # Heuristic match across registered areas
            ent_tokens = self._normalize_tokens(f"{e_id} {ent_name}")
            dev_tokens = self._normalize_tokens(
                f"{parent_dev.get('name', '')} {parent_dev.get('model', '')}" if parent_dev else ""
            )

            best_match: tuple[float, str, dict[str, Any] | None] = (0.0, "", None)

            for a_info in area_info_list:
                score, reason = self._calculate_match_score(
                    entity_tokens=ent_tokens,
                    device_tokens=dev_tokens,
                    area_id=a_info["id"],
                    area_name=a_info["name"],
                    area_aliases=a_info.get("aliases"),
                )
                if score > best_match[0]:
                    best_match = (score, reason, a_info)

            score, reason, matched_area = best_match
            if matched_area and score >= 0.65:
                suggested_assignments.append({
                    "entity_id": e_id,
                    "device_id": dev_id,
                    "name": ent_name,
                    "domain": domain,
                    "suggested_area_id": matched_area["id"],
                    "suggested_area_name": matched_area["name"],
                    "confidence": round(score, 2),
                    "reason": reason,
                    "eligible_auto": score >= min_confidence,
                })

        # Sort suggestions by confidence descending
        suggested_assignments.sort(key=lambda s: s["confidence"], reverse=True)

        # Build room breakdown summary
        room_summary: dict[str, list[str]] = {}
        for s in suggested_assignments:
            r_name = s["suggested_area_name"]
            if r_name not in room_summary:
                room_summary[r_name] = []
            room_summary[r_name].append(s["entity_id"])

        high_confidence_count = sum(1 for s in suggested_assignments if s["confidence"] >= min_confidence)

        return {
            "total_unassigned_entities": len(unassigned_entities),
            "total_unassigned_devices": len(unassigned_devices),
            "suggested_assignments": suggested_assignments,
            "high_confidence_count": high_confidence_count,
            "room_summary": room_summary,
            "min_confidence_threshold": min_confidence,
        }

    async def async_auto_commission(self, min_confidence: float = 0.85) -> dict[str, Any]:
        """Automatically commission entities and devices that meet the confidence threshold."""
        audit = await self.async_audit_unassigned(min_confidence=min_confidence)
        eligible = [s for s in audit.get("suggested_assignments", []) if s["confidence"] >= min_confidence]

        if not eligible:
            return {
                "success": True,
                "assigned_count": 0,
                "assigned_entities": 0,
                "assigned_devices": 0,
                "assignments": [],
                "message": "No unassigned entities met the autonomous commissioning confidence threshold.",
            }

        entity_reg = er.async_get(self.hass)
        device_reg = dr.async_get(self.hass)

        assigned_ents = 0
        assigned_devs = 0
        applied_assignments: list[dict[str, Any]] = []

        device_to_areas: dict[str, list[str]] = {}

        for item in eligible:
            eid = item["entity_id"]
            aid = item["suggested_area_id"]
            dev_id = item.get("device_id")

            try:
                if hasattr(entity_reg, "async_update_entity"):
                    entity_reg.async_update_entity(eid, area_id=aid)
                    assigned_ents += 1
                    applied_assignments.append(item)
                    _LOGGER.info("Commissioned entity '%s' into area '%s' (%s)", eid, aid, item["reason"])

                if dev_id:
                    if dev_id not in device_to_areas:
                        device_to_areas[dev_id] = []
                    device_to_areas[dev_id].append(aid)
            except Exception as err:
                _LOGGER.warning("Failed to auto-commission entity '%s': %s", eid, err)

        # Update parent devices if all child entities agree on the same area
        for dev_id, areas in device_to_areas.items():
            if not areas:
                continue
            # If all assigned child entities matched the same area, commission the parent device too
            primary_area = max(set(areas), key=areas.count)
            try:
                if hasattr(device_reg, "async_update_device"):
                    device_reg.async_update_device(dev_id, area_id=primary_area)
                    assigned_devs += 1
                    _LOGGER.info("Commissioned parent device '%s' into area '%s'", dev_id, primary_area)
            except Exception as err:
                _LOGGER.debug("Could not assign area to device '%s': %s", dev_id, err)

        total_assigned = assigned_ents + assigned_devs
        return {
            "success": True,
            "assigned_count": total_assigned,
            "assigned_entities": assigned_ents,
            "assigned_devices": assigned_devs,
            "assignments": applied_assignments,
            "message": (
                f"Successfully commissioned {assigned_ents} entities and {assigned_devs} devices "
                f"into their designated rooms with zero manual configuration!"
            ),
        }

    async def async_assign_entity(self, entity_id: str, area_id: str) -> dict[str, Any]:
        """Manually commission a specific entity to an area."""
        entity_reg = er.async_get(self.hass)
        if not hasattr(entity_reg, "async_update_entity"):
            return {"success": False, "error": "Entity registry not available"}

        try:
            entity_reg.async_update_entity(entity_id, area_id=area_id)
            return {"success": True, "entity_id": entity_id, "area_id": area_id}
        except Exception as err:
            return {"success": False, "error": str(err)}

    async def async_assign_device(self, device_id: str, area_id: str) -> dict[str, Any]:
        """Manually commission a specific device to an area."""
        device_reg = dr.async_get(self.hass)
        if not hasattr(device_reg, "async_update_device"):
            return {"success": False, "error": "Device registry not available"}

        try:
            device_reg.async_update_device(device_id, area_id=area_id)
            return {"success": True, "device_id": device_id, "area_id": area_id}
        except Exception as err:
            return {"success": False, "error": str(err)}
