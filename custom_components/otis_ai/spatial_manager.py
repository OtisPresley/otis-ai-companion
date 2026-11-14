"""Spatial adjacency graph and area connection manager for Otis AI Companion."""
from __future__ import annotations

from collections import deque
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "otis_ai_spatial_graph"
STORAGE_VERSION = 1

# Standard topological pairings used to infer initial connections between common home areas
DEFAULT_ADJACENCY_PAIRS = [
    ("foyer", "frontyard", "door"),
    ("foyer", "hallway", "open"),
    ("foyer", "great_room", "open"),
    ("hallway", "great_room", "open"),
    ("hallway", "guest_room", "door"),
    ("hallway", "downstairs_bath", "door"),
    ("hallway", "master", "door"),
    ("hallway", "laundry_room", "door"),
    ("hallway", "study", "door"),
    ("hallway", "office", "door"),
    ("hallway", "gym", "door"),
    ("master", "master_bath", "door"),
    ("kitchen", "great_room", "open"),
    ("kitchen", "dining_room", "open"),
    ("kitchen", "mudroom", "door"),
    ("dining_room", "great_room", "open"),
    ("mudroom", "garage", "door"),
    ("mudroom", "laundry_room", "door"),
    ("garage", "frontyard", "door"),
    ("great_room", "backyard", "door"),
    ("great_room", "theater", "door"),
    ("backyard", "pool", "open"),
]

AREA_SYNONYM_MAPPINGS = {
    "guest_room": ("guest_bedroom", "guest_suite", "guest_bath", "guest", "bedroom_2", "bedroom_3", "guestroom"),
    "master": ("master_bedroom", "primary_bedroom", "primary", "master_bed", "main_bedroom"),
    "great_room": ("living_room", "family_room", "living", "lounge", "main_room"),
    "hallway": ("hall", "corridor", "upstairs_hallway", "downstairs_hallway", "upstairs", "downstairs", "landing"),
    "study": ("office", "den", "library", "workroom"),
    "downstairs_bath": ("powder_room", "half_bath", "guest_bath", "bath_2"),
    "backyard": ("patio", "deck", "porch", "yard", "terrace"),
    "frontyard": ("front_porch", "porch", "driveway", "entryway"),
}


MOTION_KEYWORDS = ("motion", "occupancy", "presence")
CONTACT_KEYWORDS = ("door", "window", "contact", "opening")


def normalize_area_key(name: str) -> str:
    """Normalize area name or ID to a consistent lowercase snake_case key."""
    if not name:
        return ""
    text = str(name).lower()
    text = re.sub(r"['\"]", "", text)
    text = re.sub(r"[-\s]+", "_", text)
    return re.sub(r"[^\w_]", "", text).strip("_")


def build_area_lookup_map(areas: list[Any] | dict[str, Any]) -> dict[str, str]:
    """Build a unified lookup map from raw ID, normalized ID, and normalized name to official area_id."""
    lookup: dict[str, str] = {}
    if isinstance(areas, dict):
        iterable = [
            {"id": str(v.get("id") or k), "name": str(v.get("name") or k)}
            if isinstance(v, dict)
            else {"id": str(getattr(v, "id", "") or k), "name": str(getattr(v, "name", k) or k)}
            for k, v in areas.items()
        ]
    else:
        iterable = list(areas or [])

    for item in iterable:
        if isinstance(item, dict):
            aid = str(item.get("id") or "")
            aname = str(item.get("name") or aid)
        else:
            aid = str(getattr(item, "id", "") or "")
            aname = str(getattr(item, "name", aid) or aid)
        if not aid:
            continue
        lookup[aid] = aid
        norm_id = normalize_area_key(aid)
        norm_name = normalize_area_key(aname)
        if norm_id:
            lookup[norm_id] = aid
        if norm_name:
            lookup[norm_name] = aid
    return lookup


def resolve_area_identifier(area_str: str, area_lookup: dict[str, str]) -> str:
    """Resolve an area string (ID, name, or normalized slug) using a pre-built area lookup map."""
    if not area_str:
        return ""
    raw = str(area_str).strip()
    if raw in area_lookup:
        return area_lookup[raw]
    norm = normalize_area_key(raw)
    return area_lookup.get(norm, "")


def is_motion_sensor(entity_id: str) -> bool:
    """Return True if entity_id is a motion, occupancy, or presence binary sensor."""
    if not entity_id or not entity_id.startswith("binary_sensor."):
        return False
    lower_id = entity_id.lower()
    return any(kw in lower_id for kw in MOTION_KEYWORDS)


def is_contact_sensor(entity_id: str) -> bool:
    """Return True if entity_id is a door, window, or contact binary sensor."""
    if not entity_id or not entity_id.startswith("binary_sensor."):
        return False
    lower_id = entity_id.lower()
    return any(kw in lower_id for kw in CONTACT_KEYWORDS)


def classify_area_entities(entity_ids: list[str]) -> dict[str, list[str]]:
    """Classify a list of entity_ids into actionable domain/sensor buckets."""
    buckets: dict[str, list[str]] = {
        "lights": [],
        "motion": [],
        "contact": [],
        "climates": [],
        "media": [],
        "cameras": [],
        "locks": [],
        "covers": [],
        "switches": [],
        "vacuums": [],
        "fans": [],
    }
    for eid in entity_ids or []:
        if not isinstance(eid, str):
            continue
        if eid.startswith("light."):
            buckets["lights"].append(eid)
        elif is_motion_sensor(eid):
            buckets["motion"].append(eid)
        elif is_contact_sensor(eid):
            buckets["contact"].append(eid)
        elif eid.startswith("climate."):
            buckets["climates"].append(eid)
        elif eid.startswith("media_player."):
            buckets["media"].append(eid)
        elif eid.startswith("camera."):
            buckets["cameras"].append(eid)
        elif eid.startswith("lock."):
            buckets["locks"].append(eid)
        elif eid.startswith("cover."):
            buckets["covers"].append(eid)
        elif eid.startswith("switch."):
            buckets["switches"].append(eid)
        elif eid.startswith("vacuum."):
            buckets["vacuums"].append(eid)
        elif eid.startswith("fan."):
            buckets["fans"].append(eid)
    return buckets


class SpatialGraphManager:
    """Manages spatial area adjacency, connection topology, and pathfinding."""

    def __init__(self, hass: HomeAssistant, storage_key: str = STORAGE_KEY) -> None:
        """Initialize the spatial graph manager."""
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, storage_key)
        self._connections: list[dict[str, str]] = []
        self._loaded: bool = False

    async def async_load(self) -> dict[str, Any]:
        """Load the spatial graph from Home Assistant storage or infer initial defaults."""
        stored_data = await self._store.async_load()
        if stored_data and isinstance(stored_data, dict) and "connections" in stored_data:
            self._connections = stored_data["connections"]
            _LOGGER.debug("Loaded %d spatial connections from storage", len(self._connections))
        else:
            _LOGGER.info("No spatial graph found in storage. Inferring initial area adjacency defaults...")
            self._connections = self._infer_default_connections()
            await self.async_save()

        self._loaded = True
        return await self.async_get_graph()

    async def async_save(self) -> None:
        """Persist spatial graph connections to storage."""
        data = {
            "version": STORAGE_VERSION,
            "connections": self._connections,
        }
        await self._store.async_save(data)
        _LOGGER.debug("Saved %d spatial connections to storage", len(self._connections))

    def _resolve_key_with_synonyms(self, key_norm: str, norm_to_area_id: dict[str, str]) -> str:
        """Resolve an area key checking direct matches, affixes, and synonym mappings."""
        resolved = resolve_area_identifier(key_norm, norm_to_area_id)
        if resolved:
            return resolved
        for k, v in norm_to_area_id.items():
            if k.endswith(f"_{key_norm}") or k.startswith(f"{key_norm}_"):
                return v

        synonyms = AREA_SYNONYM_MAPPINGS.get(key_norm, ())
        for syn in synonyms:
            syn_id = resolve_area_identifier(syn, norm_to_area_id)
            if syn_id:
                return syn_id
            for k, v in norm_to_area_id.items():
                if syn in k:
                    return v
        return ""

    def _infer_default_connections(self) -> list[dict[str, str]]:
        """Infer default area connections matching registered areas in Home Assistant."""
        area_reg = ar.async_get(self.hass)
        existing_areas = area_reg.async_list_areas() if hasattr(area_reg, "async_list_areas") else []
        norm_to_area_id = build_area_lookup_map(existing_areas)

        connections: list[dict[str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()

        for a1_norm, a2_norm, conn_type in DEFAULT_ADJACENCY_PAIRS:
            id1 = self._resolve_key_with_synonyms(a1_norm, norm_to_area_id)
            id2 = self._resolve_key_with_synonyms(a2_norm, norm_to_area_id)

            if id1 and id2:
                pair = tuple(sorted([id1, id2]))
                if pair not in seen_pairs and id1 != id2:
                    seen_pairs.add(pair)
                    connections.append({
                        "area_1": pair[0],
                        "area_2": pair[1],
                        "type": conn_type,
                    })

        # Identify central hub rooms for fallback linking of stranded areas
        hub_hallway = self._resolve_key_with_synonyms("hallway", norm_to_area_id)
        hub_living = self._resolve_key_with_synonyms("great_room", norm_to_area_id)
        hub_foyer = self._resolve_key_with_synonyms("foyer", norm_to_area_id)
        default_hub = hub_hallway or hub_living or hub_foyer or (existing_areas[0].id if existing_areas else None)

        # Connect any registered area that has 0 connections
        connected_ids = {c["area_1"] for c in connections} | {c["area_2"] for c in connections}
        for a in existing_areas:
            aid = getattr(a, "id", "")
            if not aid or aid in connected_ids:
                continue
            aname = str(getattr(a, "name", "") or aid).lower()
            target_hub = default_hub
            conn_type = "door"
            if any(k in aname for k in ("bed", "bath", "guest", "room", "closet")):
                target_hub = hub_hallway or default_hub
                conn_type = "door"
            elif any(k in aname for k in ("dining", "kitchen", "family", "media", "theater", "lounge")):
                target_hub = hub_living or default_hub
                conn_type = "open"
            elif any(k in aname for k in ("entry", "porch", "patio", "yard", "garage")):
                target_hub = hub_foyer or hub_living or default_hub
                conn_type = "door"

            if target_hub and target_hub != aid:
                pair = tuple(sorted([aid, target_hub]))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    connections.append({
                        "area_1": pair[0],
                        "area_2": pair[1],
                        "type": conn_type,
                    })
                    connected_ids.add(aid)

        _LOGGER.info(
            "Inferred %d default spatial connections across %d registered areas",
            len(connections),
            len(existing_areas),
        )
        return connections

    async def async_get_graph(self) -> dict[str, Any]:
        """Compile complete spatial adjacency graph with node metadata and neighbor lists."""
        if not self._loaded:
            await self.async_load()

        area_reg = ar.async_get(self.hass)
        existing_areas = area_reg.async_list_areas() if hasattr(area_reg, "async_list_areas") else []
        area_meta: dict[str, dict[str, Any]] = {}
        id_to_name: dict[str, str] = {}

        for a in existing_areas:
            aid = getattr(a, "id", "")
            aname = getattr(a, "name", aid)
            id_to_name[aid] = aname
            area_meta[aid] = {
                "id": aid,
                "name": aname,
                "neighbors": [],
            }

        # Build adjacency mappings
        adjacencies: dict[str, list[str]] = {aid: [] for aid in area_meta}

        for conn in self._connections:
            a1 = conn.get("area_1")
            a2 = conn.get("area_2")
            if not a1 or not a2:
                continue

            # Ensure both areas are indexed
            if a1 not in adjacencies:
                adjacencies[a1] = []
            if a2 not in adjacencies:
                adjacencies[a2] = []

            if a2 not in adjacencies[a1]:
                adjacencies[a1].append(a2)
            if a1 not in adjacencies[a2]:
                adjacencies[a2].append(a1)

            if a1 in area_meta and a2 not in area_meta[a1]["neighbors"]:
                area_meta[a1]["neighbors"].append(a2)
            if a2 in area_meta and a1 not in area_meta[a2]["neighbors"]:
                area_meta[a2]["neighbors"].append(a1)

        # Build human-readable neighbor summary
        named_adjacencies: dict[str, list[str]] = {}
        named_adjacencies_detailed: dict[str, list[dict[str, str]]] = {}
        for aid, neighbors in adjacencies.items():
            area_name = id_to_name.get(aid, aid)
            named_neighbors = [id_to_name.get(n, n) for n in neighbors]
            named_adjacencies[area_name] = named_neighbors

            detailed = []
            for n in neighbors:
                n_name = id_to_name.get(n, n)
                conn_type = "open"
                for c in self._connections:
                    if (c.get("area_1") == aid and c.get("area_2") == n) or (c.get("area_1") == n and c.get("area_2") == aid):
                        conn_type = c.get("type", "open")
                        break
                detailed.append({"neighbor": n_name, "neighbor_id": n, "type": conn_type})
            named_adjacencies_detailed[area_name] = detailed

        return {
            "connections": list(self._connections),
            "adjacencies": adjacencies,
            "named_adjacencies": named_adjacencies,
            "named_adjacencies_detailed": named_adjacencies_detailed,
            "area_count": len(area_meta),
            "connection_count": len(self._connections),
        }

    async def async_update_connection(
        self,
        area_1: str,
        area_2: str,
        connected: bool = True,
        connection_type: str = "open",
    ) -> dict[str, Any]:
        """Add, modify, or remove an adjacency connection between two areas."""
        if not self._loaded:
            await self.async_load()

        id1 = self._resolve_area_id(area_1)
        id2 = self._resolve_area_id(area_2)

        if not id1 or not id2:
            raise ValueError(f"Could not resolve area IDs for '{area_1}' and '{area_2}'")
        if id1 == id2:
            raise ValueError("Cannot connect an area to itself")

        pair = tuple(sorted([id1, id2]))
        # Remove existing connection between pair
        self._connections = [
            c for c in self._connections
            if tuple(sorted([c.get("area_1"), c.get("area_2")])) != pair
        ]

        if connected:
            self._connections.append({
                "area_1": pair[0],
                "area_2": pair[1],
                "type": connection_type,
            })
            _LOGGER.info("Connected area '%s' to '%s' (%s)", pair[0], pair[1], connection_type)
        else:
            _LOGGER.info("Disconnected area '%s' from '%s'", pair[0], pair[1])

        await self.async_save()
        return await self.async_get_graph()

    def get_adjacent_areas(self, area: str) -> list[str]:
        """Return list of adjacent area IDs for a given area."""
        target_id = self._resolve_area_id(area)
        if not target_id:
            return []

        neighbors: list[str] = []
        for conn in self._connections:
            a1 = conn.get("area_1")
            a2 = conn.get("area_2")
            if a1 == target_id and a2 and a2 not in neighbors:
                neighbors.append(a2)
            elif a2 == target_id and a1 and a1 not in neighbors:
                neighbors.append(a1)
        return neighbors

    def find_path(self, start_area: str, end_area: str) -> list[str]:
        """Find the shortest physical path of areas connecting start and end using Breadth-First Search."""
        start_id = self._resolve_area_id(start_area)
        end_id = self._resolve_area_id(end_area)

        if not start_id or not end_id:
            return []
        if start_id == end_id:
            return [start_id]

        queue: deque[list[str]] = deque([[start_id]])
        visited: set[str] = {start_id}

        while queue:
            path = queue.popleft()
            current = path[-1]

            for neighbor in self.get_adjacent_areas(current):
                if neighbor == end_id:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])

        return []

    def _resolve_area_id(self, area_str: str) -> str:
        """Resolve an area string (ID, name, or normalized slug) to an official area_id."""
        if not area_str:
            return ""

        area_reg = ar.async_get(self.hass)
        existing_areas = area_reg.async_list_areas() if hasattr(area_reg, "async_list_areas") else []
        lookup = build_area_lookup_map(existing_areas)
        return resolve_area_identifier(area_str, lookup) or area_str

    async def async_reevaluate_from_floorplan(
        self,
        room_bounds: dict[str, dict[str, Any]],
        stair_rooms: set[str] | None = None,
    ) -> dict[str, Any]:
        """Re-evaluate spatial adjacency connections from live floorplan room geometry."""
        if not self._loaded:
            await self.async_load()
        if not isinstance(room_bounds, dict) or not room_bounds:
            return await self.async_get_graph()

        area_reg = ar.async_get(self.hass)
        existing_areas = area_reg.async_list_areas() if hasattr(area_reg, "async_list_areas") else []
        lookup = build_area_lookup_map(existing_areas)

        resolved_rooms: list[dict[str, Any]] = []
        for raw_id, rb in room_bounds.items():
            if not isinstance(rb, dict):
                continue
            aid = resolve_area_identifier(str(raw_id), lookup) or str(raw_id)
            zone = str(rb.get("zone") or "main").lower()
            floor_group = "upper" if zone == "upper" else "ground"
            resolved_rooms.append({
                "id": aid,
                "raw_id": str(raw_id).lower(),
                "zone": zone,
                "floor": floor_group,
                "x": float(rb.get("x", 0.0)),
                "y": float(rb.get("y", 0.0)),
                "w": float(rb.get("width", 0.0)),
                "h": float(rb.get("height", 0.0)),
            })

        new_conns: list[dict[str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()

        def _add_conn(a1: str, a2: str, ctype: str) -> None:
            if not a1 or not a2 or a1 == a2:
                return
            pair = tuple(sorted([a1, a2]))
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                new_conns.append({"area_1": pair[0], "area_2": pair[1], "type": ctype})

        def _infer_type(r1: dict[str, Any], r2: dict[str, Any]) -> str:
            names = {r1["raw_id"], r2["raw_id"]}
            if any("great" in n or "living" in n or "kitchen" in n or "dining" in n or "hall" in n for n in names):
                if r1["zone"] != "outdoor" and r2["zone"] != "outdoor":
                    if any("bed" in n or "bath" in n or "office" in n or "study" in n or "guest" in n or "theater" in n or "gym" in n or "garage" in n or "laundry" in n for n in names):
                        return "door"
                    return "open"
            return "door"

        # 1. Shared-wall / touching-boundary adjacency on each floor
        tol = 16.0
        min_overlap = 24.0
        for i in range(len(resolved_rooms)):
            r1 = resolved_rooms[i]
            for j in range(i + 1, len(resolved_rooms)):
                r2 = resolved_rooms[j]
                if r1["floor"] != r2["floor"]:
                    continue
                x1, y1, w1, h1 = r1["x"], r1["y"], r1["w"], r1["h"]
                x2, y2, w2, h2 = r2["x"], r2["y"], r2["w"], r2["h"]
                overlap_x = min(x1 + w1, x2 + w2) - max(x1, x2)
                overlap_y = min(y1 + h1, y2 + h2) - max(y1, y2)

                touches_vert_wall = overlap_y >= min_overlap and (
                    abs((x1 + w1) - x2) <= tol or abs((x2 + w2) - x1) <= tol
                )
                touches_horiz_wall = overlap_x >= min_overlap and (
                    abs((y1 + h1) - y2) <= tol or abs((y2 + h2) - y1) <= tol
                )
                if touches_vert_wall or touches_horiz_wall:
                    _add_conn(r1["id"], r2["id"], _infer_type(r1, r2))

        # 2. Cross-floor stair connections (ground <-> upper)
        ground_stairs = [
            r for r in resolved_rooms
            if r["floor"] == "ground"
            and (
                (stair_rooms and r["raw_id"] in stair_rooms)
                or any(k in r["raw_id"] for k in ("foyer", "mudroom", "entry"))
            )
        ]
        upper_stairs = [
            r for r in resolved_rooms
            if r["floor"] == "upper"
            and (
                (stair_rooms and r["raw_id"] in stair_rooms)
                or any(k in r["raw_id"] for k in ("hallway", "landing", "gym"))
            )
        ]
        upper_hub = next((r for r in upper_stairs if "hall" in r["raw_id"] or "landing" in r["raw_id"]), None) or (upper_stairs[0] if upper_stairs else None)
        if upper_hub:
            for gs in ground_stairs:
                _add_conn(gs["id"], upper_hub["id"], "stairs")

        # 3. Preserve any existing non-derived manual connections for areas not present in floorplan
        fp_ids = {r["id"] for r in resolved_rooms}
        for old_c in self._connections:
            a1, a2 = old_c.get("area_1"), old_c.get("area_2")
            if a1 and a2 and (a1 not in fp_ids or a2 not in fp_ids):
                _add_conn(a1, a2, old_c.get("type", "door"))

        self._connections = new_conns
        await self.async_save()
        _LOGGER.info("Re-evaluated spatial adjacency graph from floor plan (%d connections)", len(self._connections))
        return await self.async_get_graph()
