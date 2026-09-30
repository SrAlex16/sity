"""semantic_resolver.py — Semantic candidate resolution (MINI-REMAKE v2.0 Punto 4A).

Determines the semantic relation between a new candidate proposition and a list of
existing beliefs/facts: new, match, related, or contradict.

Fast paths (no Haiku call):
  - Empty existing list → NEW
  - Exact proposition match (lowercased, stripped) → MATCH with confidence=1.0

Conservative fallback on any Haiku failure → NEW (better to fragment than merge
incorrectly).

Isolation invariant: this module does NOT write to the DB — callers handle persistence.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Literal, Protocol, Sequence, runtime_checkable

from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest
from app.trace.logger import write_log


@runtime_checkable
class _Candidate(Protocol):
    id: int | None
    proposition: str
    confidence: float

_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_MAX_EXISTING = 20

_RESOLVER_SYSTEM = (
    "You are the semantic deduplication module for an AI's memory system.\n"
    "Given a NEW proposition and a list of EXISTING propositions (with IDs), classify the relation.\n\n"
    "Return ONLY valid JSON — no markdown, no explanation:\n"
    '{"relation": "<new|match|related|contradict>", "target_id": <null|int>, '
    '"confidence": <float 0.0-1.0>, "reason": "<brief>"}\n\n'
    "Relation definitions:\n"
    "- MATCH: same concept expressed differently — can be merged into one entry\n"
    "- RELATED: distinct concepts that are related but should remain separate entries\n"
    "- CONTRADICT: new proposition directly opposes an existing one\n"
    "- NEW: genuinely new concept not covered by any existing entry\n\n"
    "Rules:\n"
    "- target_id must be the ID of the matching/related/contradicting existing entry, or null for NEW\n"
    "- confidence: how certain you are (0.0–1.0)\n"
    "- reason: one concise sentence"
)


@dataclass
class SemanticResolution:
    relation: Literal["new", "match", "related", "contradict"]
    target_id: int | None
    confidence: float
    reason: str


def _parse_resolver_response(text: str) -> SemanticResolution | None:
    """Parse Haiku JSON into SemanticResolution. Returns None on any failure."""
    try:
        stripped = text.strip()
        if stripped.startswith("```"):
            parts = stripped.split("```")
            stripped = parts[1] if len(parts) > 1 else stripped
            if stripped.startswith("json"):
                stripped = stripped[4:]
        data = json.loads(stripped)
        if not isinstance(data, dict):
            return None
        relation = str(data.get("relation", "new")).lower()
        if relation not in ("new", "match", "related", "contradict"):
            relation = "new"
        target_id = data.get("target_id")
        if target_id is not None:
            try:
                target_id = int(target_id)
            except (ValueError, TypeError):
                target_id = None
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.7))))
        reason = str(data.get("reason", ""))[:200]
        return SemanticResolution(
            relation=relation,  # type: ignore[arg-type]
            target_id=target_id,
            confidence=confidence,
            reason=reason,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def resolve_candidate(
    proposition: str,
    candidate_type: Literal["self_belief", "semantic_fact"],
    existing: Sequence[_Candidate],
    *,
    trace_id: str = "",
) -> SemanticResolution:
    """Determine the semantic relation between a new proposition and existing entries.

    Fast paths (no Haiku):
    - Empty existing → NEW
    - Exact proposition match (lowercased, stripped) → MATCH, confidence=1.0

    Haiku path: top-20 by confidence, conservative fallback NEW on any failure.
    """
    prop_clean = proposition.strip().lower()

    # Fast path 1: empty existing
    if not existing:
        return SemanticResolution(relation="new", target_id=None, confidence=1.0,
                                  reason="no existing entries")

    # Fast path 2: exact match
    for item in existing:
        if item.proposition.strip().lower() == prop_clean:
            return SemanticResolution(
                relation="match",
                target_id=item.id,
                confidence=1.0,
                reason="exact proposition match",
            )

    # Haiku path: top-20 by confidence desc
    sorted_existing = sorted(existing, key=lambda x: x.confidence, reverse=True)[:_MAX_EXISTING]
    existing_text = "\n".join(
        f"- (id={item.id}, conf={item.confidence:.2f}) {item.proposition[:150]}"
        for item in sorted_existing
    )
    user_msg = (
        f"NEW proposition:\n{proposition[:300]}\n\n"
        f"EXISTING {candidate_type} entries:\n{existing_text}"
    )

    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    try:
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="semantic_resolution",
            system_prompt=_RESOLVER_SYSTEM,
            user_message=user_msg,
            max_tokens=80,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if response.ok and response.text:
            result = _parse_resolver_response(response.text)
            if result is not None:
                # Validate target_id is in the candidates we sent
                if result.relation != "new" and result.target_id is not None:
                    valid_ids = {item.id for item in sorted_existing}
                    if result.target_id not in valid_ids:
                        # Invalid reference — demote to new (conservative)
                        result.target_id = None
                        result.relation = "new"
                return result
        write_log(
            level="WARN",
            module="cognition",
            event="semantic_resolver_parse_failed",
            trace_id=trace_id,
            payload={"candidate_type": candidate_type, "raw": (response.text or "")[:200]},
        )
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="semantic_resolver_haiku_error",
            trace_id=trace_id,
            payload={"candidate_type": candidate_type, "error": str(exc)[:200]},
        )

    # Conservative fallback: NEW
    return SemanticResolution(relation="new", target_id=None, confidence=0.5,
                               reason="haiku_fallback")
