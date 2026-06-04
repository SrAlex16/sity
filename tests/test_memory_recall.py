"""Tests for MemoryRecallRunner.

All tests mock search_conversation_history so they run without a real DB.
No domain-specific fixtures or intent-based assertions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.memory.recall import (
    MemoryRecallRunner,
    MemoryRecallResult,
    _CONFIDENCE_FOUND,
    _MAX_ATTEMPTS,
    _NOVEL_THRESHOLD_SUFFICIENT,
    _NOVEL_THRESHOLD_PARTIAL,
)
from app.memory.search import MessageContext, SearchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_search_result(text: str, msg_id: int = 1) -> SearchResult:
    ctx = MessageContext(role="user", text=text, created_at=_NOW, message_id=msg_id)
    return SearchResult(match=ctx, prev=None, next=None)


def _runner() -> MemoryRecallRunner:
    return MemoryRecallRunner()


# ---------------------------------------------------------------------------
# 1. Query generation — generic, no domain hardcodes
# ---------------------------------------------------------------------------

def test_generates_at_least_one_query_for_any_input() -> None:
    runner = _runner()
    assert len(runner._generate_queries("cualquier texto")) >= 1


def test_generates_multiple_queries_for_multi_word_input() -> None:
    runner = _runner()
    queries = runner._generate_queries("palabra1 palabra2 palabra3 palabra4")
    assert len(queries) >= 2


def test_no_duplicate_queries_generated() -> None:
    runner = _runner()
    queries = runner._generate_queries("algo bastante largo con varias palabras distintas")
    assert len(queries) == len(set(queries))


def test_short_input_produces_query_without_crash() -> None:
    runner = _runner()
    queries = runner._generate_queries("x")
    assert isinstance(queries, list)


def test_empty_input_produces_no_crash() -> None:
    runner = _runner()
    queries = runner._generate_queries("")
    assert isinstance(queries, list)


def test_generates_no_domain_specific_hardcodes() -> None:
    """The runner code must not reference domain-specific terms."""
    import inspect
    import app.memory.recall as m
    src = inspect.getsource(m)
    forbidden = ["anime", "juego", "personaje", "adivinar", "recuerdas", "te acuerdas"]
    for word in forbidden:
        assert word not in src, f"Domain hardcode found in recall.py: {word!r}"


# ---------------------------------------------------------------------------
# 2. recall() — status and confidence
# ---------------------------------------------------------------------------

def test_not_found_when_search_returns_empty() -> None:
    runner = _runner()
    with patch("app.memory.recall.search_conversation_history", return_value=[]):
        result = runner.recall(query="xyzzy_nomatch", trace_id="t1")
    assert result.status == "not_found"
    assert result.result_confidence == 0.0
    assert result.fragments == []


def test_found_or_partial_when_search_returns_informative_results() -> None:
    runner = _runner()
    # Fragment contains many tokens not in query → high novel ratio → found or partial
    with patch("app.memory.recall.search_conversation_history") as mock_s:
        mock_s.return_value = [_make_search_result(
            "sistema almacena identificador único principal confirmado definitivo"
        )]
        result = runner.recall(query="contenido relevante", trace_id="t2")
    assert result.status in ("found", "partial")
    assert len(result.fragments) >= 1


def test_found_status_when_sufficient_novel_tokens() -> None:
    runner = _runner()
    # Fragment tokens all novel relative to query → max_novel = 1.0 ≥ threshold
    hits = [_make_search_result(
        "sistema almacena identificador único principal confirmado definitivo"
    )]
    with patch("app.memory.recall.search_conversation_history", return_value=hits):
        result = runner.recall(query="contenido busca", trace_id="t3")
    assert result.status == "found"
    assert result.result_confidence >= _NOVEL_THRESHOLD_SUFFICIENT


def test_result_has_all_required_fields() -> None:
    runner = _runner()
    with patch("app.memory.recall.search_conversation_history", return_value=[]):
        result = runner.recall(query="algo", trace_id="t4")
    assert isinstance(result, MemoryRecallResult)
    assert isinstance(result.status, str)
    assert isinstance(result.queries_tried, list)
    assert isinstance(result.fragments, list)
    assert isinstance(result.evidence_summary, str)
    assert isinstance(result.result_confidence, float)
    assert isinstance(result.truncated, bool)


def test_evidence_summary_non_empty() -> None:
    runner = _runner()
    with patch("app.memory.recall.search_conversation_history", return_value=[]):
        result = runner.recall(query="algo", trace_id="t5")
    assert len(result.evidence_summary) > 0


# ---------------------------------------------------------------------------
# 3. recall() — iteration and deduplication
# ---------------------------------------------------------------------------

def test_queries_tried_non_empty() -> None:
    runner = _runner()
    with patch("app.memory.recall.search_conversation_history", return_value=[]):
        result = runner.recall(query="algo largo con varias palabras", trace_id="t6")
    assert len(result.queries_tried) >= 1


def test_no_duplicate_queries_tried() -> None:
    runner = _runner()
    with patch("app.memory.recall.search_conversation_history", return_value=[]):
        result = runner.recall(query="uno dos tres cuatro cinco seis", trace_id="t7")
    assert len(result.queries_tried) == len(set(result.queries_tried))


def test_stops_early_when_sufficient_evidence() -> None:
    """Runner makes only 1 call when first result provides sufficient novel tokens."""
    runner = _runner()
    calls: list[str] = []

    def mock_search(query, limit):
        calls.append(query)
        # All tokens novel relative to the query → max_novel = 1.0
        return [_make_search_result(
            "sistema almacena identificador único principal confirmado definitivo", i
        ) for i in range(3)]

    with patch("app.memory.recall.search_conversation_history", side_effect=mock_search):
        runner.recall(query="busca referencia clave", trace_id="t8")

    assert len(calls) == 1


def test_continues_after_noise_fragments() -> None:
    """Runner must make more than 1 call when first results are all noise (echo of query)."""
    runner = _runner()
    calls: list[str] = []

    def mock_search(query, limit):
        calls.append(query)
        # Text echoes the query → low novel ratio
        return [_make_search_result("busqué referencia clave resultado", i) for i in range(2)]

    with patch("app.memory.recall.search_conversation_history", side_effect=mock_search):
        runner.recall(query="referencia clave resultado busqué", trace_id="t8b")

    assert len(calls) > 1


def test_deduplicates_across_attempts() -> None:
    """Same text appearing in multiple search attempts must not create duplicate fragments."""
    runner = _runner()
    same = _make_search_result("texto duplicado exacto en todos los intentos", msg_id=42)

    with patch("app.memory.recall.search_conversation_history", return_value=[same]):
        result = runner.recall(query="uno dos tres cuatro cinco", trace_id="t9")

    texts = [f.text for f in result.fragments]
    assert len(texts) == len(set(texts))


def test_attempts_capped_at_max() -> None:
    calls: list[str] = []

    def mock_search(query, limit):
        calls.append(query)
        return []

    runner = _runner()
    with patch("app.memory.recall.search_conversation_history", side_effect=mock_search):
        runner.recall(query="uno dos tres cuatro cinco seis", trace_id="t10")

    assert len(calls) <= _MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# 4. Fragments — structure and content
# ---------------------------------------------------------------------------

def test_fragment_has_message_id() -> None:
    runner = _runner()
    hit = _make_search_result("texto de prueba", msg_id=999)
    with patch("app.memory.recall.search_conversation_history", return_value=[hit]):
        result = runner.recall(query="texto prueba", trace_id="t11")
    assert result.fragments[0].message_id == 999


def test_fragment_has_timestamp() -> None:
    runner = _runner()
    hit = _make_search_result("texto con fecha", msg_id=1)
    hit.match.created_at = _NOW
    with patch("app.memory.recall.search_conversation_history", return_value=[hit]):
        result = runner.recall(query="texto fecha", trace_id="t12")
    assert result.fragments[0].timestamp == _NOW


# ---------------------------------------------------------------------------
# 5. Evidence evaluation — novel token logic
# ---------------------------------------------------------------------------

def test_noise_fragments_give_not_found() -> None:
    """Fragments that only echo the query tokens must not produce 'found' status."""
    runner = _runner()
    # query tokens: referencia, clave (len >= 4)
    # fragment tokens: busqué(6), referencia(10), clave(5) → novel={busqué} = 1/3 = 0.33
    noise_hits = [
        _make_search_result("busqué referencia clave", msg_id=1),
        _make_search_result("encontré referencia clave", msg_id=2),
        _make_search_result("busqué referencia disponible clave", msg_id=3),
    ]
    with patch("app.memory.recall.search_conversation_history", return_value=noise_hits):
        result = runner.recall(query="referencia clave", trace_id="t13")
    assert result.status != "found"


def test_informative_fragment_produces_found() -> None:
    """A fragment with mostly novel tokens must yield 'found'."""
    runner = _runner()
    # All tokens are novel relative to query "busca dato"
    informative = _make_search_result(
        "sistema almacena identificador único principal confirmado definitivo", msg_id=10
    )
    with patch("app.memory.recall.search_conversation_history", return_value=[informative]):
        result = runner.recall(query="busca dato", trace_id="t14")
    assert result.status == "found"


def test_fragment_count_alone_not_sufficient() -> None:
    """Many fragments with no novel tokens must not produce 'found'."""
    runner = _runner()
    # 5 fragments, all echoing query tokens
    hits = [_make_search_result(f"referencia clave instancia", msg_id=i) for i in range(5)]
    with patch("app.memory.recall.search_conversation_history", return_value=hits):
        result = runner.recall(query="referencia clave instancia", trace_id="t15")
    assert result.status != "found"


def test_evaluate_evidence_returns_sufficient_on_high_novel() -> None:
    runner = _runner()
    fragments_data = [
        type("F", (), {"text": "sistema almacena identificador único principal confirmado"})()
    ]
    status, conf, reason = runner._evaluate_evidence(fragments_data, "busca")
    assert status == "sufficient"
    assert conf >= _NOVEL_THRESHOLD_SUFFICIENT


def test_evaluate_evidence_not_found_on_empty() -> None:
    runner = _runner()
    status, conf, reason = runner._evaluate_evidence([], "cualquier query")
    assert status == "not_found"
    assert conf == 0.0
