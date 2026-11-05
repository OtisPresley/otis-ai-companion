"""Otis AI Companion: Local LLM Embedding-Based RAG & Smart Home Knowledge Manager.

Indexes device manuals, troubleshooting guides, hardware setup notes, live entity telemetry,
and historical smart home events into a local vector store with hybrid dense + lexical retrieval.
Zero-cloud, privacy-first, and fully persistent across Home Assistant restarts.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "otis_ai_knowledge_store"
STORAGE_VERSION = 1
DEFAULT_EMBEDDING_DIM = 128

IGNORED_TELEMETRY_ATTRS: set[str] = {
    "access_token",
    "entity_picture",
    "entity_picture_local",
    "options",
    "attribution",
    "icon",
    "friendly_name",
    "device_class",
    "unit_of_measurement",
    "state_class",
    "supported_features",
    "supported_color_modes",
    "available_tones",
    "device_trackers",
    "restored",
}

KEY_TELEMETRY_ATTRS: set[str] = {
    "temperature",
    "current_temperature",
    "target_temperature",
    "target_temp_high",
    "target_temp_low",
    "humidity",
    "current_humidity",
    "hvac_action",
    "hvac_mode",
    "preset_mode",
    "fan_mode",
    "brightness",
    "color_temp",
    "rgb_color",
    "volume_level",
    "is_volume_muted",
    "media_title",
    "media_artist",
    "media_channel",
    "source",
    "sound_mode",
    "power",
    "current_power_w",
    "energy",
    "voltage",
    "current",
    "battery_level",
    "battery",
    "battery_state",
    "linkquality",
    "rssi",
    "ip_address",
    "ip",
    "mac",
    "ping",
    "motion",
    "occupancy",
    "presence",
    "illuminance",
    "co2",
    "pm25",
    "air_quality",
    "valve_position",
}


def compute_fallback_embedding(text: str, dim: int = DEFAULT_EMBEDDING_DIM) -> list[float]:
    """Deterministic normalized subword and token hash embedding in pure Python.

    Provides instantaneous zero-cloud fallback embeddings when local neural embedding
    models are offline, cold-starting, or unconfigured.
    """
    if not text:
        return [0.0] * dim

    vec = [0.0] * dim
    tokens = re.findall(r"\w+", text.lower())
    for tok in tokens:
        # Token unigram deterministic hash
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16) % dim
        vec[h] += 1.0
        # Character bigram subword hashes
        for i in range(len(tok) - 1):
            sub = tok[i : i + 2]
            h_sub = int(hashlib.md5(sub.encode("utf-8")).hexdigest()[:8], 16) % dim
            vec[h_sub] += 0.5

    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0.0:
        return [round(x / norm, 5) for x in vec]
    return vec


def cosine_similarity(v1: list[float] | None, v2: list[float] | None) -> float:
    """Compute cosine similarity between two numeric vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 > 0.0 and norm2 > 0.0:
        return max(0.0, min(1.0, dot / (norm1 * norm2)))
    return 0.0


def lexical_similarity(query: str, text: str) -> float:
    """Compute token overlap similarity between query and candidate text."""
    if not query or not text:
        return 0.0
    q_tokens = set(re.findall(r"\w+", query.lower()))
    if not q_tokens:
        return 0.0
    t_tokens = set(re.findall(r"\w+", text.lower()))
    if not t_tokens:
        return 0.0
    overlap = len(q_tokens.intersection(t_tokens))
    return overlap / len(q_tokens)


def chunk_text(text: str, max_chars: int = 500, overlap: int = 100) -> list[str]:
    """Split text into coherent semantic chunks based on paragraphs or sentences."""
    clean = text.strip()
    if not clean:
        return []
    if len(clean) <= max_chars:
        return [clean]

    paragraphs = clean.split("\n\n")
    chunks: list[str] = []
    current_chunk = ""

    for para in paragraphs:
        para_clean = para.strip()
        if not para_clean:
            continue
        if len(current_chunk) + len(para_clean) + 2 <= max_chars:
            current_chunk = f"{current_chunk}\n\n{para_clean}".strip()
        else:
            if current_chunk:
                chunks.append(current_chunk)
                # Keep tail for overlap if long enough
                overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else ""
                current_chunk = f"{overlap_text}\n\n{para_clean}".strip()
            else:
                # Single paragraph exceeds max_chars; split by sentences or punctuation
                sentences = re.split(r"(?<=[.!?])\s+", para_clean)
                for sent in sentences:
                    if len(current_chunk) + len(sent) + 1 <= max_chars:
                        current_chunk = f"{current_chunk} {sent}".strip()
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = sent.strip()

    if current_chunk:
        chunks.append(current_chunk)

    return chunks or [clean]


def format_entity_telemetry_chunk(
    entity_id: str,
    state_obj: Any,
    area_name: str | None = None,
    include_attributes: bool = True,
) -> str:
    """Format live entity telemetry state and attributes into a semantically dense RAG chunk."""
    friendly = state_obj.attributes.get("friendly_name", entity_id) if hasattr(state_obj, "attributes") else entity_id
    state_val = getattr(state_obj, "state", "unknown")
    unit = state_obj.attributes.get("unit_of_measurement", "") if hasattr(state_obj, "attributes") else ""
    device_class = state_obj.attributes.get("device_class", "") if hasattr(state_obj, "attributes") else ""
    domain = entity_id.split(".")[0] if "." in entity_id else "entity"
    area_str = area_name or "Unassigned"

    telemetry_parts: list[str] = []
    if include_attributes and hasattr(state_obj, "attributes") and state_obj.attributes:
        attrs = state_obj.attributes
        # Prioritize key telemetry attributes
        for k in KEY_TELEMETRY_ATTRS:
            if k in attrs and attrs[k] is not None:
                telemetry_parts.append(f"{k}: {attrs[k]}")

        # Also capture any other non-ignored scalar attributes
        for k, v in attrs.items():
            if k not in KEY_TELEMETRY_ATTRS and k not in IGNORED_TELEMETRY_ATTRS and not k.startswith("_"):
                if isinstance(v, (str, int, float, bool)) and len(str(v)) < 100:
                    telemetry_parts.append(f"{k}: {v}")

    attr_summary = ", ".join(telemetry_parts[:12]) if telemetry_parts else "none"

    return (
        f"Device: {friendly} ({entity_id})\n"
        f"Domain: {domain} | Area: {area_str}\n"
        f"Current Status: {state_val}{f' {unit}' if unit else ''}{f' (Class: {device_class})' if device_class else ''}\n"
        f"Telemetry: {attr_summary}\n"
        f"Summary: {friendly} located in {area_str} is currently {state_val}{f' {unit}' if unit else ''}."
    )


class RAGKnowledgeManager:
    """Manages persistent smart home document indexing, embeddings, and RAG retrieval."""

    def __init__(
        self,
        hass: HomeAssistant,
        local_llm_manager: Any | None = None,
        storage_key: str = STORAGE_KEY,
    ) -> None:
        """Initialize the RAG Knowledge Manager."""
        self.hass = hass
        self.local_llm_manager = local_llm_manager
        self._store = Store(hass, STORAGE_VERSION, storage_key)
        self._chunks: dict[str, dict[str, Any]] = {}
        self._documents: dict[str, dict[str, Any]] = {}
        self._loaded: bool = False

    async def async_load(self) -> None:
        """Load knowledge base from persistent storage."""
        if self._loaded:
            return
        try:
            data = await self._store.async_load()
            if isinstance(data, dict):
                self._chunks = data.get("chunks", {})
                self._documents = data.get("documents", {})
                _LOGGER.debug(
                    "Loaded %d knowledge chunks across %d documents from storage",
                    len(self._chunks),
                    len(self._documents),
                )
        except Exception as err:
            _LOGGER.warning("Could not load knowledge store from storage: %s", err)
            self._chunks = {}
            self._documents = {}

        self._loaded = True

        # Pre-seed essential system knowledge if store is completely empty
        if not self._chunks:
            await self._async_seed_default_knowledge()

        self.async_update_rag_sensor()

    async def async_save(self) -> None:
        """Save knowledge chunks and document metadata to persistent storage."""
        try:
            await self._store.async_save({
                "chunks": self._chunks,
                "documents": self._documents,
                "updated_at": time.time(),
            })
            self.async_update_rag_sensor()
        except Exception as err:
            _LOGGER.error("Failed to save knowledge store: %s", err)

    def async_update_rag_sensor(self) -> None:
        """Publish sensor.otis_knowledge_rag with RAG index statistics."""
        if hasattr(self.hass, "states") and hasattr(self.hass.states, "async_set"):
            stats = self.get_knowledge_stats()
            self.hass.states.async_set(
                "sensor.otis_knowledge_rag",
                str(stats["total_chunks"]),
                {
                    "total_chunks": stats["total_chunks"],
                    "total_documents": stats["total_documents"],
                    "categories": stats["categories"],
                    "friendly_name": "Otis Knowledge & RAG Vector Store",
                    "icon": "mdi:brain",
                    "last_updated": time.time(),
                },
            )

    async def _generate_embedding(self, text: str) -> list[float]:
        """Generate embedding using local LLM server with pure-python fallback."""
        if self.local_llm_manager and hasattr(self.local_llm_manager, "async_get_embedding"):
            try:
                emb = await self.local_llm_manager.async_get_embedding(text)
                if emb and isinstance(emb, list) and len(emb) > 0:
                    return emb
            except Exception as err:
                _LOGGER.debug("Local LLM embedding request failed: %s; using fallback", err)

        return compute_fallback_embedding(text)

    async def async_index_document(
        self,
        title: str,
        content: str,
        category: str = "manual",
        doc_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Index a document or guide, chunking it and calculating embeddings."""
        await self.async_load()

        document_id = doc_id or f"doc_{int(time.time() * 1000)}"
        meta = metadata or {}
        chunks_text = chunk_text(content)

        created_chunks: list[str] = []
        now = time.time()

        for idx, c_text in enumerate(chunks_text):
            chunk_id = f"{document_id}_c{idx}"
            embed_text = f"{title}\n{c_text}" if title else c_text
            embedding = await self._generate_embedding(embed_text)

            chunk_record = {
                "chunk_id": chunk_id,
                "document_id": document_id,
                "title": title,
                "category": category,
                "content": c_text,
                "metadata": meta,
                "embedding": embedding,
                "created_at": now,
            }
            self._chunks[chunk_id] = chunk_record
            created_chunks.append(chunk_id)

        self._documents[document_id] = {
            "document_id": document_id,
            "title": title,
            "category": category,
            "chunk_count": len(created_chunks),
            "metadata": meta,
            "created_at": now,
        }

        await self.async_save()
        _LOGGER.info(
            "Indexed document '%s' (%s) into %d chunks",
            title,
            document_id,
            len(created_chunks),
        )

        return {
            "success": True,
            "document_id": document_id,
            "title": title,
            "category": category,
            "chunks_indexed": len(created_chunks),
        }

    async def async_index_device_manual(
        self,
        title: str,
        content: str,
        manufacturer: str | None = None,
        model: str | None = None,
        domain: str | None = None,
        doc_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Index a device technical manual with manufacturer and model taxonomy metadata."""
        clean_meta = dict(metadata or {})
        if manufacturer:
            clean_meta["manufacturer"] = manufacturer
        if model:
            clean_meta["model"] = model
        if domain:
            clean_meta["domain"] = domain

        manual_id = doc_id or f"manual:{re.sub(r'[^a-zA-Z0-9_]', '_', title.lower())}"

        return await self.async_index_document(
            title=title,
            content=content,
            category="manual",
            doc_id=manual_id,
            metadata=clean_meta,
        )

    async def async_index_entity_telemetry(
        self,
        entity_ids: list[str] | str | None = None,
        domains: list[str] | str | None = None,
        include_attributes: bool = True,
    ) -> dict[str, Any]:
        """Index current Home Assistant entity telemetry and state embeddings."""
        await self.async_load()

        if not self.hass or not hasattr(self.hass, "states"):
            return {"success": False, "error": "Home Assistant states unavailable"}

        # Normalize entity_ids filter
        target_eids: set[str] | None = None
        if entity_ids:
            if isinstance(entity_ids, str):
                target_eids = {e.strip() for e in entity_ids.split(",") if e.strip()}
            elif isinstance(entity_ids, (list, set, tuple)):
                target_eids = {str(e).strip() for e in entity_ids if e}

        # Normalize domains filter
        target_domains: set[str] | None = None
        if domains:
            if isinstance(domains, str):
                target_domains = {d.strip().lower() for d in domains.split(",") if d.strip()}
            elif isinstance(domains, (list, set, tuple)):
                target_domains = {str(d).strip().lower() for d in domains if d}

        # Build area lookup map
        area_map: dict[str, str] = {}
        try:
            from homeassistant.helpers import area_registry as ar
            from homeassistant.helpers import device_registry as dr
            from homeassistant.helpers import entity_registry as er

            ent_reg = er.async_get(self.hass)
            dev_reg = dr.async_get(self.hass)
            area_reg = ar.async_get(self.hass)

            for ent_entry in ent_reg.entities.values():
                area_id = ent_entry.area_id
                if not area_id and ent_entry.device_id:
                    dev_entry = dev_reg.async_get(ent_entry.device_id)
                    if dev_entry:
                        area_id = dev_entry.area_id
                if area_id:
                    area_obj = area_reg.async_get_area(area_id)
                    if area_obj:
                        area_map[ent_entry.entity_id] = area_obj.name
        except Exception as e_err:
            _LOGGER.debug("Could not resolve entity area names for RAG: %s", e_err)

        # Candidate states
        all_states = self.hass.states.async_all()
        indexed_entities: list[str] = []
        now = time.time()

        for st in all_states:
            eid = st.entity_id
            domain = eid.split(".")[0]

            if target_eids is not None and eid not in target_eids:
                continue

            if target_domains is not None and domain not in target_domains:
                continue

            # If no filters provided, default to common smart home domain set
            if target_eids is None and target_domains is None:
                if domain not in {
                    "climate",
                    "sensor",
                    "light",
                    "switch",
                    "lock",
                    "media_player",
                    "cover",
                    "camera",
                    "binary_sensor",
                    "fan",
                    "vacuum",
                    "alarm_control_panel",
                }:
                    continue

            area_name = area_map.get(eid)
            content = format_entity_telemetry_chunk(
                eid, st, area_name=area_name, include_attributes=include_attributes
            )
            friendly = st.attributes.get("friendly_name", eid)
            doc_id = f"telemetry:{eid}"
            chunk_id = f"{doc_id}_c0"

            emb = await self._generate_embedding(content)

            chunk_record = {
                "chunk_id": chunk_id,
                "document_id": doc_id,
                "title": f"Live Telemetry: {friendly} ({eid})",
                "category": "entity_telemetry",
                "content": content,
                "metadata": {
                    "entity_id": eid,
                    "domain": domain,
                    "area": area_name,
                    "state": st.state,
                    "unit": st.attributes.get("unit_of_measurement"),
                    "device_class": st.attributes.get("device_class"),
                    "indexed_at": now,
                },
                "embedding": emb,
                "created_at": now,
            }

            self._chunks[chunk_id] = chunk_record
            self._documents[doc_id] = {
                "document_id": doc_id,
                "title": f"Live Telemetry: {friendly} ({eid})",
                "category": "entity_telemetry",
                "chunk_count": 1,
                "metadata": chunk_record["metadata"],
                "created_at": now,
            }
            indexed_entities.append(eid)

        await self.async_save()

        _LOGGER.info(
            "Otis AI RAG: Indexed telemetry for %d entities (total chunks: %d)",
            len(indexed_entities),
            len(self._chunks),
        )

        return {
            "success": True,
            "indexed_count": len(indexed_entities),
            "total_chunks": len(self._chunks),
            "entities": indexed_entities,
        }

    async def async_index_entity_history(
        self,
        entity_id: str,
        events: list[dict[str, Any]] | None = None,
        max_events: int = 20,
    ) -> dict[str, Any]:
        """Index recent state transitions or anomaly logs for a specific entity."""
        await self.async_load()

        friendly = entity_id
        if self.hass:
            state_obj = self.hass.states.get(entity_id)
            if state_obj:
                friendly = state_obj.attributes.get("friendly_name", entity_id)

        event_lines: list[str] = []
        if events:
            for ev in events[:max_events]:
                ts = ev.get("time") or ev.get("timestamp") or ""
                state = ev.get("state") or ev.get("action") or ""
                desc = ev.get("description") or ev.get("message") or ""
                event_lines.append(f"- [{ts}] State: {state}. {desc}".strip())
        elif self.hass and state_obj:
            event_lines.append(
                f"Entity {entity_id} ({friendly}) current state is '{state_obj.state}' "
                f"with attributes: {dict(state_obj.attributes)}."
            )

        if not event_lines:
            return {"success": False, "error": f"No state or event data found for entity {entity_id}"}

        doc_title = f"Historical Events: {friendly} ({entity_id})"
        doc_content = f"Event history log for {friendly} ({entity_id}):\n" + "\n".join(event_lines)

        return await self.async_index_document(
            title=doc_title,
            content=doc_content,
            category="event_history",
            doc_id=f"history:{entity_id}",
            metadata={"entity_id": entity_id, "friendly_name": friendly, "indexed_at": time.time()},
        )

    async def async_query_knowledge(
        self,
        query: str,
        limit: int = 3,
        category: str | list[str] | None = None,
        min_score: float = 0.12,
    ) -> list[dict[str, Any]]:
        """Perform hybrid semantic vector and lexical search across indexed knowledge."""
        await self.async_load()
        if not self._chunks:
            return []

        query_emb = await self._generate_embedding(query)
        scored_results: list[tuple[float, dict[str, Any]]] = []
        now = time.time()

        # Normalize category filter
        cat_filter: set[str] | None = None
        if category:
            if isinstance(category, str):
                cat_filter = {category}
            elif isinstance(category, (list, set, tuple)):
                cat_filter = {str(c) for c in category}

        for chunk in self._chunks.values():
            c_cat = chunk.get("category")
            if cat_filter and c_cat not in cat_filter:
                continue

            c_emb = chunk.get("embedding")
            c_content = chunk.get("content", "")
            c_title = chunk.get("title", "")

            # Dense vector cosine similarity
            v_score = cosine_similarity(query_emb, c_emb)
            # Sparse lexical token overlap
            c_text_full = f"{c_title} {c_content}" if c_title else c_content
            l_score = lexical_similarity(query, c_text_full)

            # Hybrid score weighting
            combined_score = (0.7 * v_score) + (0.3 * l_score) if v_score > 0 else l_score

            # Recency boost for fresh entity telemetry (within 1 hour)
            if c_cat == "entity_telemetry":
                created_at = chunk.get("created_at", now)
                age = max(0.0, now - created_at)
                if age < 3600.0:
                    boost = 0.08 * (1.0 - (age / 3600.0))
                    combined_score += boost

            if combined_score >= min_score:
                scored_results.append((combined_score, {
                    "chunk_id": chunk.get("chunk_id"),
                    "document_id": chunk.get("document_id"),
                    "title": chunk.get("title"),
                    "category": c_cat,
                    "content": c_content,
                    "metadata": chunk.get("metadata", {}),
                    "score": round(combined_score, 3),
                    "vector_score": round(v_score, 3),
                    "lexical_score": round(l_score, 3),
                }))

        # Sort descending by combined score
        scored_results.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored_results[:limit]]

    async def async_get_rag_context(
        self,
        query: str,
        limit: int = 3,
        category: str | list[str] | None = None,
    ) -> str:
        """Search knowledge base and format a contextual RAG prompt snippet for the LLM."""
        results = await self.async_query_knowledge(query, limit=limit, category=category)
        if not results:
            return ""

        lines = ["\n### Relevant Smart Home Documentation & Knowledge Base (RAG):"]
        for r in results:
            title = r.get("title", "Document")
            cat_name = str(r.get("category", "info")).replace("_", " ").title()
            content = r.get("content", "").strip()
            score = r.get("score", 0.0)
            lines.append(f"• **[{cat_name}] {title}** (Relevance: {int(score * 100)}%):\n  {content}")

        return "\n".join(lines) + "\n"

    async def async_clear_knowledge(
        self,
        category: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        """Clear indexed chunks and documents by category or specific document ID."""
        await self.async_load()

        if document_id:
            chunks_to_del = [cid for cid, c in self._chunks.items() if c.get("document_id") == document_id]
            for cid in chunks_to_del:
                self._chunks.pop(cid, None)
            self._documents.pop(document_id, None)
            deleted_count = len(chunks_to_del)
        elif category:
            chunks_to_del = [cid for cid, c in self._chunks.items() if c.get("category") == category]
            for cid in chunks_to_del:
                self._chunks.pop(cid, None)
            docs_to_del = [did for did, d in self._documents.items() if d.get("category") == category]
            for did in docs_to_del:
                self._documents.pop(did, None)
            deleted_count = len(chunks_to_del)
        else:
            deleted_count = len(self._chunks)
            self._chunks.clear()
            self._documents.clear()

        await self.async_save()
        return {
            "success": True,
            "deleted_chunks": deleted_count,
            "remaining_chunks": len(self._chunks),
            "remaining_documents": len(self._documents),
        }

    def get_knowledge_stats(self) -> dict[str, Any]:
        """Return index statistics including counts by category and storage size."""
        by_category: dict[str, int] = {}
        for c in self._chunks.values():
            cat = c.get("category", "unknown")
            by_category[cat] = by_category.get(cat, 0) + 1

        return {
            "total_chunks": len(self._chunks),
            "total_documents": len(self._documents),
            "categories": by_category,
            "loaded": self._loaded,
        }

    async def _async_seed_default_knowledge(self) -> None:
        """Seed default smart home operating manuals and troubleshooting references."""
        default_docs = [
            {
                "title": "Otis AI Smart Home Architecture & Services",
                "category": "manual",
                "doc_id": "manual:otis_ai_core",
                "content": (
                    "Otis AI Companion provides smart home co-piloting, 2D and 3D floorplan rendering, "
                    "proactive Sentinel watchdog auditing, and automated anomaly healing. "
                    "Available services include otis_ai.run_sentinel_watchdog for auditing stuck devices, "
                    "otis_ai.turn_off_stuck_actuator, otis_ai.restart_ble_proxy for ESPHome adapters, "
                    "and otis_ai.pin_floorplan_entity for positioning badges on the floorplan. "
                    "The floorplan supports 2D blueprints and 3D isometric perspectives with suspended upper levels."
                ),
                "metadata": {"manufacturer": "Otis AI", "domain": "otis_ai"},
            },
            {
                "title": "Smart Switch & Dimmer Troubleshooting (TP-Link / Shelly / Inovelli)",
                "category": "troubleshooting",
                "doc_id": "manual:switches_troubleshooting",
                "content": (
                    "When a smart dimmer or switch (e.g. TP-Link Kasa, Shelly, Inovelli) exhibits an amber or red blinking LED, "
                    "it indicates Wi-Fi handshake failure or network isolation. "
                    "To remediate: 1) Verify 2.4GHz Wi-Fi is active. 2) Press and hold the reset button for 5 seconds to reset Wi-Fi "
                    "without wiping device config. 3) For stuck relays or actuators that have been running continuously, "
                    "use Otis AI turn_off_stuck_actuator or power-cycle the breaker."
                ),
                "metadata": {"domain": "switch"},
            },
            {
                "title": "Zigbee and Z-Wave Mesh Healing Best Practices",
                "category": "troubleshooting",
                "doc_id": "manual:mesh_healing",
                "content": (
                    "If battery sensors or smart plugs become unreachable ('node_status: dead' or 'is_failed: true'), "
                    "heal the routing topology using otis_ai.heal_mesh_node. Mains-powered routing nodes (plugs, in-wall switches) "
                    "should be positioned within 25 feet of each other. Never place metal barriers or microwave ovens between coordinators and routers."
                ),
                "metadata": {"domain": "mesh"},
            },
            {
                "title": "Lutron Caseta Wireless Dimmer & Smart Bridge Manual",
                "category": "manual",
                "doc_id": "manual:lutron_caseta",
                "content": (
                    "Lutron Caseta wireless dimmers (PD-6WCL) communicate over Clear Connect RF at 434 MHz to the Lutron Smart Bridge. "
                    "To factory reset a Caseta dimmer: Triple tap the 'On' button and hold on the third tap for 6 seconds until the indicator LED "
                    "flashes rapidly, then immediately release and triple tap again. The LED will flash slowly to confirm factory default settings. "
                    "Pico remotes can be paired directly to dimmers by holding the off button on both devices for 6 seconds."
                ),
                "metadata": {"manufacturer": "Lutron", "model": "PD-6WCL", "domain": "light"},
            },
            {
                "title": "Shelly Plus 1 / Plus 1PM Smart Relay Manual & Factory Reset",
                "category": "manual",
                "doc_id": "manual:shelly_plus",
                "content": (
                    "Shelly Plus 1 and Plus 1PM relays operate over Wi-Fi and Bluetooth. Default web interface IP in AP mode is 192.168.33.1. "
                    "To factory reset: Within 60 seconds of applying power to the breaker, toggle the physical wall switch connected to SW terminal "
                    "5 times consecutively. The internal relay will click rapidly 5 times to confirm reset. "
                    "Shelly Plus 1PM includes internal thermal protection and overpower cut-off (>3500W)."
                ),
                "metadata": {"manufacturer": "Shelly", "model": "Plus 1PM", "domain": "switch"},
            },
            {
                "title": "Control4 8-Channel Audio Matrix Amplifier Manual",
                "category": "manual",
                "doc_id": "manual:control4_amp",
                "content": (
                    "Control4 multi-zone power amplifiers provide 8 stereo zones (16 channels) of Class D amplification. "
                    "Matrix switching allows routing any of the analog RCA or digital coax inputs to any amplified speaker output zone. "
                    "Control is handled via IP socket commands on port 8750 or serial RS-232 at 115200 baud. "
                    "Status LED blinks orange during thermal throttling or clip detection. Ensure 1U rack clearance for convective airflow."
                ),
                "metadata": {"manufacturer": "Control4", "model": "C4-AMP108", "domain": "media_player"},
            },
            {
                "title": "UniFi Switch & Access Point PoE & Roaming Manual",
                "category": "manual",
                "doc_id": "manual:unifi_network",
                "content": (
                    "UniFi Access Points (U6-Pro, U7-Pro) require 802.3at PoE+ power from the upstream UniFi switch. "
                    "For seamless 802.11k/v/r fast roaming between access points, configure Minimum RSSI threshold to -75 dBm "
                    "and disable wireless meshing if all APs are hardwired to gigabit Ethernet. "
                    "If an AP shows offline or blinking white, perform a PoE power cycle on the switch port using otis_ai.power_cycle_poe_port."
                ),
                "metadata": {"manufacturer": "Ubiquiti", "model": "UniFi", "domain": "network"},
            },
            {
                "title": "Yale Assure Lock 2 Smart Deadbolt Manual",
                "category": "manual",
                "doc_id": "manual:yale_assure_lock",
                "content": (
                    "Yale Assure Lock 2 smart deadbolts feature Z-Wave Plus, Zigbee, or Matter-over-Thread modular smart modules. "
                    "To enter programming mode: Touch keypad with palm, enter Master PIN followed by Gear icon. "
                    "To enroll in Z-Wave/Zigbee: Press Gear, press 7, press Gear, press 1, press Gear. "
                    "Auto-lock timeout is customizable between 30 seconds and 3 minutes. Emergency 9V battery terminals on keypad base "
                    "allow jump-starting dead AA batteries from the exterior."
                ),
                "metadata": {"manufacturer": "Yale", "model": "YRD450", "domain": "lock"},
            },
        ]

        for doc in default_docs:
            await self.async_index_document(
                title=doc["title"],
                content=doc["content"],
                category=doc["category"],
                doc_id=doc["doc_id"],
                metadata=doc.get("metadata", {"seeded": True}),
            )
