"""Iterative memory recall over the conversation history.

MemoryRecallRunner performs multiple search attempts with query variants
derived algorithmically from the original query. No domain-specific logic,
no trigger word lists. The decision to invoke this runner is made externally
(by the action planner); this module only handles execution and aggregation.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.memory.search import (
    MessageContext,
    SearchResult,
    read_conversation_window,
    search_conversation_history,
)
from app.trace.logger import write_log

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 4
_MAX_WINDOWS = 3        # max window reads per recall session
_MAX_TOTAL_FRAGMENTS = 80
_TOKEN_MIN_LEN = 4
_WINDOW_BEFORE = 5
_WINDOW_AFTER = 50      # matches _WINDOW_AFTER_MAX in search.py

# Evidence quality thresholds (novel token ratio per fragment)
_NOVEL_THRESHOLD_SUFFICIENT = 0.60   # max per-fragment novel ratio → "sufficient" → "found"
_NOVEL_THRESHOLD_PARTIAL = 0.20      # avg novel ratio across fragments → "partial"

# Backward-compat alias used in tests
_CONFIDENCE_FOUND = _NOVEL_THRESHOLD_SUFFICIENT


@dataclass
class MemoryFragment:
    message_id: Optional[int]
    timestamp: Optional[datetime]
    role: str
    text: str
    prev: Optional[MessageContext] = None
    next: Optional[MessageContext] = None


@dataclass
class MemoryRecallResult:
    status: str              # "found" | "partial" | "not_found"
    queries_tried: list[str]
    fragments: list[MemoryFragment]
    evidence_summary: str
    result_confidence: float  # 0.0–1.0
    truncated: bool
    windows_read: int = 0
    anchor_message_ids: list[int] = field(default_factory=list)


def _extract_tokens(text: str) -> set[str]:
    clean = re.sub(r'[^\w\s]', ' ', text, flags=re.UNICODE)
    return {w.lower() for w in clean.split() if len(w) >= _TOKEN_MIN_LEN}


class MemoryRecallRunner:
    """Execute iterative searches and aggregate results into a MemoryRecallResult."""

    def recall(self, *, query: str, trace_id: str) -> MemoryRecallResult:
        log.info(
            "memory_recall_started trace_id=%s query=%r",
            trace_id, query[:80],
        )
        write_log(
            level="INFO",
            module="memory",
            event="memory_recall_started",
            payload={"trace_id": trace_id, "query": query[:80]},
        )

        queries = self._generate_queries(query)
        all_fragments: list[MemoryFragment] = []
        seen_keys: set[str] = set()
        queries_tried: list[str] = []
        ev_status = "not_found"
        ev_confidence = 0.0
        windows_read = 0
        anchor_message_ids: list[int] = []

        # Phase 1: exhaust all query variants — no early exit on ev_status
        for attempt, q in enumerate(queries[:_MAX_ATTEMPTS], 1):
            if q in queries_tried:
                continue
            queries_tried.append(q)

            results = search_conversation_history(q, limit=5)
            new_count = 0

            for r in results:
                key = r.match.text[:120]
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                all_fragments.append(MemoryFragment(
                    message_id=r.match.message_id,
                    timestamp=r.match.created_at,
                    role=r.match.role,
                    text=r.match.text,
                    prev=r.prev,
                    next=r.next,
                ))
                new_count += 1

            ev_status, ev_confidence, ev_reason = self._evaluate_evidence(all_fragments, query)

            log.info(
                "memory_recall_query trace_id=%s attempt=%d query=%r raw=%d accepted=%d "
                "ev_status=%s confidence=%.2f reason=%s",
                trace_id, attempt, q, len(results), new_count,
                ev_status, ev_confidence, ev_reason,
            )

        # Phase 2: always open windows around anchors (structural, regardless of ev_status)
        phase1_fragments = list(all_fragments)  # snapshot: only Phase 1 anchors as candidates
        opened_anchor_ids: list[int] = []

        for frag in phase1_fragments:
            if frag.message_id is None or len(opened_anchor_ids) >= _MAX_WINDOWS:
                continue
            anchor_id = frag.message_id
            # Skip if within window span of an already-opened anchor (structural dedup by id)
            if any(abs(anchor_id - a) <= (_WINDOW_BEFORE + _WINDOW_AFTER) for a in opened_anchor_ids):
                continue
            opened_anchor_ids.append(anchor_id)
            anchor_message_ids.append(anchor_id)

            window = read_conversation_window(
                anchor_id, before=_WINDOW_BEFORE, after=_WINDOW_AFTER
            )
            new_from_window = 0
            for ctx in window:
                key = ctx.text[:120]
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                all_fragments.append(MemoryFragment(
                    message_id=ctx.message_id,
                    timestamp=ctx.created_at,
                    role=ctx.role,
                    text=ctx.text,
                    prev=None,
                    next=None,
                ))
                new_from_window += 1

            windows_read += 1
            log.info(
                "memory_recall_window_read trace_id=%s anchor_id=%d "
                "window_msgs=%d new_fragments=%d",
                trace_id, anchor_id, len(window), new_from_window,
            )

        # Single evidence re-evaluation after all window expansion
        if opened_anchor_ids:
            ev_status, ev_confidence, ev_reason = self._evaluate_evidence(all_fragments, query)
            log.info(
                "memory_recall_after_windows trace_id=%s ev_status=%s confidence=%.2f",
                trace_id, ev_status, ev_confidence,
            )

        truncated = len(all_fragments) > _MAX_TOTAL_FRAGMENTS
        fragments = all_fragments[:_MAX_TOTAL_FRAGMENTS]

        if ev_status == "sufficient":
            status = "found"
        elif ev_status == "partial":
            status = "partial"
        else:
            status = "not_found"

        summary = self._build_summary(fragments, status, windows_read)

        log.info(
            "memory_recall_finished trace_id=%s status=%s confidence=%.2f "
            "fragments=%d windows=%d",
            trace_id, status, ev_confidence, len(fragments), windows_read,
        )
        write_log(
            level="INFO",
            module="memory",
            event="memory_recall_finished",
            payload={
                "trace_id": trace_id,
                "status": status,
                "confidence": round(ev_confidence, 2),
                "fragments": len(fragments),
                "windows": windows_read,
                "queries_tried": len(queries_tried),
            },
        )

        return MemoryRecallResult(
            status=status,
            queries_tried=queries_tried,
            fragments=fragments,
            evidence_summary=summary,
            result_confidence=ev_confidence,
            truncated=truncated,
            windows_read=windows_read,
            anchor_message_ids=anchor_message_ids,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_queries(self, query: str) -> list[str]:
        """Return up to _MAX_ATTEMPTS structurally distinct query variants.

        Uses only generic tokenization — no domain-specific logic.
        """
        clean = re.sub(r'[()\"?*^+~:-]', ' ', query)
        tokens = [w for w in clean.split() if len(w) >= 4]

        if not tokens:
            return [query.strip()] if query.strip() else []

        seen: set[str] = set()
        queries: list[str] = []

        def _add(q: str) -> None:
            q = q.strip()
            if q and q not in seen:
                seen.add(q)
                queries.append(q)

        # 1. All tokens as OR (broadest recall)
        _add(" OR ".join(tokens))

        # 2. Longest tokens only (most distinctive terms)
        if len(tokens) > 2:
            top = sorted(tokens, key=len, reverse=True)[:3]
            _add(" OR ".join(top))

        # 3. First half of tokens (front-biased subset)
        if len(tokens) > 3:
            _add(" OR ".join(tokens[: len(tokens) // 2 + 1]))

        # 4. Single longest token (maximum specificity)
        longest = max(tokens, key=len)
        _add(longest)

        return queries

    def _evaluate_evidence(
        self,
        fragments: list[MemoryFragment],
        query: str,
    ) -> tuple[str, float, str]:
        """Classify evidence quality based on novel token ratio.

        Returns (status, confidence, reason) where status is one of:
        "sufficient" | "partial" | "noise" | "not_found".

        A fragment is informative when it contains tokens that are NOT in the
        query — i.e., it carries new information rather than just echoing the
        search terms back.
        """
        if not fragments:
            return "not_found", 0.0, "no_fragments"

        query_tokens = _extract_tokens(query)

        novel_ratios: list[float] = []
        for f in fragments:
            frag_tokens = _extract_tokens(f.text)
            if not frag_tokens:
                novel_ratios.append(0.0)
                continue
            novel = frag_tokens - query_tokens
            novel_ratios.append(len(novel) / len(frag_tokens))

        max_novel = max(novel_ratios)
        avg_novel = sum(novel_ratios) / len(novel_ratios)

        if max_novel >= _NOVEL_THRESHOLD_SUFFICIENT:
            return "sufficient", max_novel, f"max_novel={max_novel:.2f}"
        if avg_novel >= _NOVEL_THRESHOLD_PARTIAL:
            return "partial", avg_novel, f"avg_novel={avg_novel:.2f}"
        if fragments:
            return "noise", avg_novel, f"avg_novel={avg_novel:.2f}_below_partial"
        return "not_found", 0.0, "no_fragments"

    def _build_summary(
        self,
        fragments: list[MemoryFragment],
        status: str,
        windows_read: int = 0,
    ) -> str:
        if status == "not_found":
            return "No hay evidencia suficiente para responder con seguridad."
        extra = f" (ventanas: {windows_read})" if windows_read else ""
        return f"Se encontraron {len(fragments)} fragmento(s) relevante(s) en el historial{extra}."
