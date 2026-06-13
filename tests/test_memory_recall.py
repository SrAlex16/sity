"""Tests for MemoryRecallRunner.

All tests mock search_conversation_history and read_conversation_window so they
run without a real DB. Phase 2 (window expansion) now always runs when anchors
have message_id, so every test that patches search to return fragments with
message_id must also mock read_conversation_window.
No domain-specific fixtures or intent-based assertions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.memory.recall import (
    MemoryRecallRunner,
    MemoryRecallResult,
    _CONFIDENCE_FOUND,
    _MAX_ATTEMPTS,
    _MAX_WINDOWS,
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


def _make_ctx(text: str, msg_id: int = 1, role: str = "sity") -> MessageContext:
    return MessageContext(role=role, text=text, created_at=_NOW, message_id=msg_id)


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
    with patch("app.memory.recall.search_conversation_history") as mock_s:
        mock_s.return_value = [_make_search_result(
            "sistema almacena identificador único principal confirmado definitivo"
        )]
        with patch("app.memory.recall.read_conversation_window", return_value=[]):
            result = runner.recall(query="contenido relevante", trace_id="t2")
    assert result.status in ("found", "partial")
    assert len(result.fragments) >= 1


def test_found_status_when_sufficient_novel_tokens() -> None:
    runner = _runner()
    hits = [_make_search_result(
        "sistema almacena identificador único principal confirmado definitivo"
    )]
    with patch("app.memory.recall.search_conversation_history", return_value=hits):
        with patch("app.memory.recall.read_conversation_window", return_value=[]):
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
    assert isinstance(result.windows_read, int)
    assert isinstance(result.anchor_message_ids, list)


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


def test_phase1_exhausts_all_queries_regardless_of_evidence() -> None:
    """Phase 1 must run all query variants — no early exit on ev_status."""
    runner = _runner()
    calls: list[str] = []

    def mock_search(query, limit):
        calls.append(query)
        # Return highly informative result — would have triggered early exit before
        return [_make_search_result(
            "sistema almacena identificador único principal confirmado definitivo", i
        ) for i in range(3)]

    with patch("app.memory.recall.search_conversation_history", side_effect=mock_search):
        with patch("app.memory.recall.read_conversation_window", return_value=[]):
            runner.recall(query="busca referencia clave", trace_id="t8")

    # With 3+ distinct tokens, _generate_queries produces >= 2 variants
    assert len(calls) >= 2, f"Expected ≥2 search calls (no early exit), got {len(calls)}"


def test_continues_after_noise_fragments() -> None:
    """Runner must make more than 1 search call when first results are all noise."""
    runner = _runner()
    calls: list[str] = []

    def mock_search(query, limit):
        calls.append(query)
        return [_make_search_result("busqué referencia clave resultado", i) for i in range(2)]

    with patch("app.memory.recall.search_conversation_history", side_effect=mock_search):
        with patch("app.memory.recall.read_conversation_window", return_value=[]):
            runner.recall(query="referencia clave resultado busqué", trace_id="t8b")

    assert len(calls) > 1


def test_deduplicates_across_attempts() -> None:
    """Same text appearing in multiple search attempts must not create duplicate fragments."""
    runner = _runner()
    same = _make_search_result("texto duplicado exacto en todos los intentos", msg_id=42)

    with patch("app.memory.recall.search_conversation_history", return_value=[same]):
        with patch("app.memory.recall.read_conversation_window", return_value=[]):
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
        with patch("app.memory.recall.read_conversation_window", return_value=[]):
            result = runner.recall(query="texto prueba", trace_id="t11")
    assert result.fragments[0].message_id == 999


def test_fragment_has_timestamp() -> None:
    runner = _runner()
    hit = _make_search_result("texto con fecha", msg_id=1)
    hit.match.created_at = _NOW
    with patch("app.memory.recall.search_conversation_history", return_value=[hit]):
        with patch("app.memory.recall.read_conversation_window", return_value=[]):
            result = runner.recall(query="texto fecha", trace_id="t12")
    assert result.fragments[0].timestamp == _NOW


# ---------------------------------------------------------------------------
# 5. Evidence evaluation — novel token logic
# ---------------------------------------------------------------------------

def test_noise_fragments_give_not_found() -> None:
    """Fragments that only echo the query tokens must not produce 'found' status."""
    runner = _runner()
    noise_hits = [
        _make_search_result("busqué referencia clave", msg_id=1),
        _make_search_result("encontré referencia clave", msg_id=2),
        _make_search_result("busqué referencia disponible clave", msg_id=3),
    ]
    with patch("app.memory.recall.search_conversation_history", return_value=noise_hits):
        with patch("app.memory.recall.read_conversation_window", return_value=[]):
            result = runner.recall(query="referencia clave", trace_id="t13")
    assert result.status != "found"


def test_informative_fragment_produces_found() -> None:
    """A fragment with mostly novel tokens must yield 'found'."""
    runner = _runner()
    informative = _make_search_result(
        "sistema almacena identificador único principal confirmado definitivo", msg_id=10
    )
    with patch("app.memory.recall.search_conversation_history", return_value=[informative]):
        with patch("app.memory.recall.read_conversation_window", return_value=[]):
            result = runner.recall(query="busca dato", trace_id="t14")
    assert result.status == "found"


def test_fragment_count_alone_not_sufficient() -> None:
    """Many fragments with no novel tokens must not produce 'found'."""
    runner = _runner()
    hits = [_make_search_result(f"referencia clave instancia", msg_id=i) for i in range(5)]
    with patch("app.memory.recall.search_conversation_history", return_value=hits):
        with patch("app.memory.recall.read_conversation_window", return_value=[]):
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


# ---------------------------------------------------------------------------
# 6. Window expansion — Phase 2 always runs when anchors have message_id
# ---------------------------------------------------------------------------

def test_window_expands_when_search_insufficient() -> None:
    """When search gives insufficient evidence, window expansion should upgrade status."""
    runner = _runner()
    anchor = _make_search_result("busqué referencia clave resultado", msg_id=100)
    informative = _make_ctx(
        "sistema almacena identificador único principal confirmado definitivo",
        msg_id=115,
    )

    with patch("app.memory.recall.search_conversation_history", return_value=[anchor]):
        with patch("app.memory.recall.read_conversation_window", return_value=[informative]):
            result = runner.recall(query="referencia clave resultado", trace_id="tw1")

    assert result.status == "found"
    assert result.windows_read >= 1
    assert 100 in result.anchor_message_ids


def test_window_called_even_when_search_sufficient() -> None:
    """Window must be opened even when Phase 1 already gives sufficient evidence."""
    runner = _runner()
    informative = _make_search_result(
        "sistema almacena identificador único principal confirmado definitivo", msg_id=10
    )
    window_mock = MagicMock(return_value=[])

    with patch("app.memory.recall.search_conversation_history", return_value=[informative]):
        with patch("app.memory.recall.read_conversation_window", window_mock):
            result = runner.recall(query="busca dato", trace_id="tw2")

    assert result.status == "found"
    window_mock.assert_called()
    assert result.windows_read >= 1


def test_window_always_runs_when_evidence_sufficient() -> None:
    """Even with sufficient Phase 1 evidence, Phase 2 opens exactly one window."""
    runner = _runner()
    informative = _make_search_result(
        "sistema almacena identificador único principal confirmado definitivo", msg_id=10
    )
    window_mock = MagicMock(return_value=[])

    with patch("app.memory.recall.search_conversation_history", return_value=[informative]):
        with patch("app.memory.recall.read_conversation_window", window_mock):
            result = runner.recall(query="busca dato", trace_id="tw_always")

    assert result.status == "found"
    window_mock.assert_called_once()
    assert result.windows_read == 1


def test_windows_read_count_tracked() -> None:
    """windows_read reflects how many window reads were performed."""
    runner = _runner()
    anchor = _make_search_result("busqué referencia clave", msg_id=50)
    with patch("app.memory.recall.search_conversation_history", return_value=[anchor]):
        with patch("app.memory.recall.read_conversation_window", return_value=[]):
            result = runner.recall(query="referencia clave", trace_id="tw3")

    assert result.windows_read >= 1


def test_anchor_message_ids_populated_on_window_read() -> None:
    """anchor_message_ids lists the message_ids used as window centers."""
    runner = _runner()
    anchor = _make_search_result("busqué referencia clave", msg_id=77)
    with patch("app.memory.recall.search_conversation_history", return_value=[anchor]):
        with patch("app.memory.recall.read_conversation_window", return_value=[]):
            result = runner.recall(query="referencia clave", trace_id="tw4")

    assert 77 in result.anchor_message_ids


def test_window_deduplicates_with_search_results() -> None:
    """Fragments already seen via search must not appear again from window."""
    runner = _runner()
    anchor = _make_search_result("busqué referencia clave resultado", msg_id=100)
    same_ctx = _make_ctx("busqué referencia clave resultado", msg_id=100)

    with patch("app.memory.recall.search_conversation_history", return_value=[anchor]):
        with patch("app.memory.recall.read_conversation_window", return_value=[same_ctx]):
            result = runner.recall(query="referencia clave resultado", trace_id="tw5")

    texts = [f.text for f in result.fragments]
    assert len(texts) == len(set(texts))


def test_window_adds_new_fragments_from_context() -> None:
    """Fragments introduced by window expansion must appear in result.fragments."""
    runner = _runner()
    anchor = _make_search_result("busqué referencia clave resultado", msg_id=100)
    new_ctx = _make_ctx("contenido totalmente distinto presente aquí ahora", msg_id=115)

    with patch("app.memory.recall.search_conversation_history", return_value=[anchor]):
        with patch("app.memory.recall.read_conversation_window", return_value=[new_ctx]):
            result = runner.recall(query="referencia clave resultado", trace_id="tw6")

    texts = [f.text for f in result.fragments]
    assert any("contenido totalmente distinto" in t for t in texts)


def test_windows_capped_at_max() -> None:
    """Window expansion must not exceed _MAX_WINDOWS reads per recall.

    Anchors are spaced 100 IDs apart — beyond overlap threshold (_WINDOW_BEFORE +
    _WINDOW_AFTER = 5 + 50 = 55) — so _MAX_WINDOWS is the binding constraint.
    """
    runner = _runner()
    window_calls: list[int] = []

    def mock_window(center_id, before, after):
        window_calls.append(center_id)
        return []

    # 5 anchors far enough apart that overlap dedup doesn't fire; cap does
    anchors = [_make_search_result(f"referencia clave texto {i}", msg_id=i * 100) for i in range(1, 6)]

    with patch("app.memory.recall.search_conversation_history", return_value=anchors):
        with patch("app.memory.recall.read_conversation_window", side_effect=mock_window):
            runner.recall(query="referencia clave", trace_id="tw7")

    assert len(window_calls) <= _MAX_WINDOWS


def test_window_not_attempted_when_no_anchor_ids() -> None:
    """If search returns fragments without message_ids, window must not be called."""
    runner = _runner()
    ctx = MessageContext(role="user", text="referencia clave texto largo", created_at=_NOW, message_id=None)
    hit = SearchResult(match=ctx, prev=None, next=None)
    window_mock = MagicMock(return_value=[])

    with patch("app.memory.recall.search_conversation_history", return_value=[hit]):
        with patch("app.memory.recall.read_conversation_window", window_mock):
            runner.recall(query="referencia clave", trace_id="tw8")

    window_mock.assert_not_called()


def test_overlap_dedup_skips_nearby_anchors() -> None:
    """Anchors within _WINDOW_BEFORE + _WINDOW_AFTER of an already-opened anchor are skipped."""
    from app.memory.recall import _WINDOW_BEFORE, _WINDOW_AFTER
    runner = _runner()
    window_calls: list[int] = []

    def mock_window(center_id, before, after):
        window_calls.append(center_id)
        return []

    # Two anchors close together (10 IDs apart, threshold = 5+50 = 55) → only first opened
    close_anchors = [
        _make_search_result("referencia clave texto alfa", msg_id=100),
        _make_search_result("referencia clave texto beta", msg_id=110),
    ]

    with patch("app.memory.recall.search_conversation_history", return_value=close_anchors):
        with patch("app.memory.recall.read_conversation_window", side_effect=mock_window):
            runner.recall(query="referencia clave", trace_id="tw_overlap")

    assert len(window_calls) == 1, f"Overlapping anchor should be skipped, got calls: {window_calls}"
    assert window_calls[0] == 100


def test_phase1_runs_all_attempts_then_opens_windows() -> None:
    """Phase 1 exhausts all query variants; Phase 2 opens windows on non-redundant anchors."""
    runner = _runner()
    search_calls: list[str] = []
    window_calls: list[int] = []

    def mock_search(query, limit):
        search_calls.append(query)
        if len(search_calls) == 1:
            # First call: high-novel anchor (would have triggered "sufficient" early exit before)
            return [_make_search_result(
                "sistema almacena identificador único principal confirmado definitivo", msg_id=100
            )]
        # Later calls: distinct far anchor
        return [_make_search_result("fragmento distinto separado remoto otro", msg_id=500)]

    def mock_window(center_id, before, after):
        window_calls.append(center_id)
        return []

    with patch("app.memory.recall.search_conversation_history", side_effect=mock_search):
        with patch("app.memory.recall.read_conversation_window", side_effect=mock_window):
            result = runner.recall(query="busca marcador clave resultado", trace_id="t_all")

    # Phase 1 must have made more than 1 search call (no early exit)
    assert len(search_calls) >= 2, f"Expected ≥2 search calls, got {len(search_calls)}"
    # Phase 2 must have opened at least one window
    assert len(window_calls) >= 1, f"Expected ≥1 window call, got {len(window_calls)}"
    # Anchors at 100 and 500 are 400 apart (> 55 threshold) → both should be opened if _MAX_WINDOWS >= 2
    if _MAX_WINDOWS >= 2:
        assert 100 in window_calls and 500 in window_calls
