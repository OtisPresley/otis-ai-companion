"""Otis AI Companion: Local LLM Embedding-Based RAG & Smart Home Knowledge Manager.

Indexes device manuals, troubleshooting guides, hardware setup notes, and historical
smart home events into a local vector store with hybrid dense + lexical retrieval.
Zero-cloud, privacy-first, and fully persistent across Home Assistant restarts.
"""
from __future__ import annotations

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
        # Token unigram hash
        h = hash(tok) % dim
        vec[h] += 1.0
        # Character bigram subword hashes
        for i in range(len(tok) - 1):
            sub = tok[i : i + 2]
            h_sub = hash(sub) % dim
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

    async def async_save(self) -> None:
        """Save knowledge chunks and document metadata to persistent storage."""
        try:
            await self._store.async_save({
                "chunks": self._chunks,
                "documents": self._documents,
                "updated_at": time.time(),
            })
        except Exception as err:
            _LOGGER.error("Failed to save knowledge store: %s", err)

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
            embedding = await self._generate_embedding(c_text)

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
        category: str | None = None,
        min_score: float = 0.12,
    ) -> list[dict[str, Any]]:
        """Perform hybrid semantic vector and lexical search across indexed knowledge."""
        await self.async_load()
        if not self._chunks:
            return []

        query_emb = await self._generate_embedding(query)
        scored_results: list[tuple[float, dict[str, Any]]] = []

        for chunk in self._chunks.values():
            if category and chunk.get("category") != category:
                continue

            c_emb = chunk.get("embedding")
            c_content = chunk.get("content", "")

            # Dense vector cosine similarity
            v_score = cosine_similarity(query_emb, c_emb)
            # Sparse lexical token overlap
            l_score = lexical_similarity(query, c_content)

            # Hybrid score weighting
            combined_score = (0.7 * v_score) + (0.3 * l_score) if v_score > 0 else l_score

            if combined_score >= min_score:
                scored_results.append((combined_score, {
                    "chunk_id": chunk.get("chunk_id"),
                    "document_id": chunk.get("document_id"),
                    "title": chunk.get("title"),
                    "category": chunk.get("category"),
                    "content": c_content,
                    "metadata": chunk.get("metadata", {}),
                    "score": round(combined_score, 3),
                    "vector_score": round(v_score, 3),
                    "lexical_score": round(l_score, 3),
                }))

        # Sort descending by combined score
        scored_results.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored_results[:limit]]

    async def async_get_rag_context(self, query: str, limit: int = 3) -> str:
        """Search knowledge base and format a contextual RAG prompt snippet for the LLM."""
        results = await self.async_query_knowledge(query, limit=limit)
        if not results:
            return ""

        lines = ["\n### Relevant Smart Home Documentation & Knowledge Base (RAG):"]
        for r in results:
            title = r.get("title", "Document")
            category = r.get("category", "info").replace("_", " ").title()
            content = r.get("content", "").strip()
            score = r.get("score", 0.0)
            lines.append(f"• **[{category}] {title}** (Relevance: {int(score * 100)}%):\n  {content}")

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
            },
        ]

        for doc in default_docs:
            await self.async_index_document(
                title=doc["title"],
                content=doc["content"],
                category=doc["category"],
                doc_id=doc["doc_id"],
                metadata={"seeded": True},
            )
