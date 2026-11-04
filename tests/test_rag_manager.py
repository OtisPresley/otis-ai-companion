"""Unit tests for Otis AI Companion RAG Knowledge Manager & Semantic Retrieval."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.otis_ai.rag_manager import (
    DEFAULT_EMBEDDING_DIM,
    RAGKnowledgeManager,
    chunk_text,
    compute_fallback_embedding,
    cosine_similarity,
    lexical_similarity,
)


def test_fallback_embedding():
    """Test deterministic pure-python fallback embedding generation."""
    v1 = compute_fallback_embedding("Smart dimmer factory reset procedure")
    assert len(v1) == DEFAULT_EMBEDDING_DIM
    # Check unit vector normalization
    norm = sum(x * x for x in v1)
    assert 0.99 <= norm <= 1.01

    # Determinism
    v2 = compute_fallback_embedding("Smart dimmer factory reset procedure")
    assert v1 == v2

    # Empty text returns zero vector
    v_empty = compute_fallback_embedding("")
    assert all(x == 0.0 for x in v_empty)


def test_cosine_similarity():
    """Test cosine similarity function."""
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]

    assert cosine_similarity(v1, v2) == 1.0
    assert cosine_similarity(v1, v3) == 0.0
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0


def test_lexical_similarity():
    """Test token overlap lexical similarity."""
    assert lexical_similarity("dimmer switch reset", "How do I reset my smart dimmer switch?") == 1.0
    assert abs(lexical_similarity("dimmer switch reset", "smart dimmer") - (1.0 / 3.0)) < 1e-4
    assert lexical_similarity("unrelated terms", "totally different text") == 0.0
    assert lexical_similarity("", "text") == 0.0


def test_chunk_text():
    """Test document chunking logic."""
    short = "This is a short manual for a smart bulb."
    assert chunk_text(short, max_chars=100) == [short]

    long_doc = (
        "Paragraph 1 explains the installation process.\n\n"
        "Paragraph 2 details the Wi-Fi pairing mode with the blinking amber light.\n\n"
        "Paragraph 3 describes the factory reset holding the reset button for 10 seconds."
    )
    chunks = chunk_text(long_doc, max_chars=90, overlap=20)
    assert len(chunks) >= 3
    assert any("installation process" in c for c in chunks)
    assert any("factory reset" in c for c in chunks)


def test_rag_manager_indexing_and_query():
    """Test indexing documents, generating embeddings, and querying the store."""
    hass = MagicMock()
    mock_store = MagicMock()
    mock_store.async_load = AsyncMock(return_value=None)
    mock_store.async_save = AsyncMock(return_value=None)

    with patch("custom_components.otis_ai.rag_manager.Store", return_value=mock_store):
        mgr = RAGKnowledgeManager(hass)

        # Index custom device manual
        res = asyncio.run(
            mgr.async_index_document(
                title="Lutron Caseta Dimmer Guide",
                content=(
                    "Lutron Caseta wireless dimmers connect to the Smart Bridge. "
                    "To factory reset a Caseta dimmer: Triple tap the on button, hold on the third tap for 6 seconds "
                    "until the indicator LED flashes rapidly, then release and immediately triple tap again."
                ),
                category="manual",
                doc_id="manual:lutron_caseta",
            )
        )
        assert res["success"] is True
        assert res["chunks_indexed"] >= 1
        assert mgr.get_knowledge_stats()["total_chunks"] >= 1

        # Query knowledge base for reset instructions
        hits = asyncio.run(mgr.async_query_knowledge("How do I factory reset my Lutron dimmer?"))
        assert len(hits) >= 1
        top = hits[0]
        assert "Lutron" in top["title"]
        assert "triple tap" in top["content"].lower()
        assert top["score"] > 0.3

        # Formatted RAG context string
        context = asyncio.run(mgr.async_get_rag_context("Lutron dimmer factory reset"))
        assert "Lutron Caseta Dimmer Guide" in context
        assert "triple tap" in context.lower()


def test_rag_manager_index_entity_history():
    """Test indexing entity state history and anomalies."""
    hass = MagicMock()
    mock_state = MagicMock()
    mock_state.state = "unavailable"
    mock_state.attributes = {"friendly_name": "Front Porch Camera", "reason": "connection timeout"}
    hass.states.get.return_value = mock_state

    mock_store = MagicMock()
    mock_store.async_load = AsyncMock(return_value=None)
    mock_store.async_save = AsyncMock(return_value=None)

    with patch("custom_components.otis_ai.rag_manager.Store", return_value=mock_store):
        mgr = RAGKnowledgeManager(hass)

        custom_events = [
            {"time": "14:00", "state": "on", "description": "Motion detected on porch"},
            {"time": "14:05", "state": "unavailable", "description": "Wi-Fi link dropped; Sentinel flagged proxy lag"},
        ]
        res = asyncio.run(
            mgr.async_index_entity_history(
                entity_id="camera.front_porch",
                events=custom_events,
            )
        )
        assert res["success"] is True

        # Query history
        hits = asyncio.run(mgr.async_query_knowledge("Why did the porch camera drop?", category="event_history"))
        assert len(hits) >= 1
        assert "Front Porch" in hits[0]["title"]
        assert "Wi-Fi link dropped" in hits[0]["content"]


def test_rag_manager_clear_knowledge():
    """Test clearing knowledge by category, document_id, or full wipe."""
    hass = MagicMock()
    mock_store = MagicMock()
    mock_store.async_load = AsyncMock(return_value=None)
    mock_store.async_save = AsyncMock(return_value=None)

    with patch("custom_components.otis_ai.rag_manager.Store", return_value=mock_store):
        mgr = RAGKnowledgeManager(hass)

        asyncio.run(mgr.async_index_document("Doc 1", "Content 1", category="manual", doc_id="doc_1"))
        asyncio.run(mgr.async_index_document("Doc 2", "Content 2", category="troubleshooting", doc_id="doc_2"))
        initial_doc_count = mgr.get_knowledge_stats()["total_documents"]
        assert initial_doc_count >= 2

        # Clear doc_1 by id
        c1 = asyncio.run(mgr.async_clear_knowledge(document_id="doc_1"))
        assert c1["remaining_documents"] == initial_doc_count - 1

        # Clear remaining by full wipe
        c2 = asyncio.run(mgr.async_clear_knowledge())
        assert c2["remaining_chunks"] == 0
        assert c2["remaining_documents"] == 0


def test_rag_manager_neural_embeddings_integration():
    """Test integration when LocalLLMManager provides neural embeddings."""
    hass = MagicMock()
    mock_store = MagicMock()
    mock_store.async_load = AsyncMock(return_value=None)
    mock_store.async_save = AsyncMock(return_value=None)

    mock_llm = MagicMock()
    # Mock a 4-dimensional neural embedding vector from Ollama
    mock_llm.async_get_embedding = AsyncMock(return_value=[0.1, 0.5, 0.8, 0.2])

    with patch("custom_components.otis_ai.rag_manager.Store", return_value=mock_store):
        mgr = RAGKnowledgeManager(hass, local_llm_manager=mock_llm)

        res = asyncio.run(
            mgr.async_index_document(
                title="Neural Doc",
                content="Sample neural text content.",
                doc_id="neural_doc",
            )
        )
        assert res["success"] is True
        mock_llm.async_get_embedding.assert_called()
        assert mgr._chunks["neural_doc_c0"]["embedding"] == [0.1, 0.5, 0.8, 0.2]
