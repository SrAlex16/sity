"""semantic_service.py — Semantic fact consolidation (Remake Fase 9).

Extracts and maintains stable facts about the user from episodic memory.

Architecture (sección 25/59):
  1. Background synthesis: batch of unprocessed episodes → Haiku extracts stable facts.
  2. Reinforcement: episodes confirming an existing fact increase its confidence (+0.05).
  3. Contradiction: episodes contradicting a fact decrease its confidence (−0.10);
     facts below 0.20 are deactivated. Revision-downward from the start.
  4. Read-only integration in Reflection Step: top-5 facts by confidence injected
     as additional context in the Haiku prompt (no extra call — zero marginal cost).

Confidence formula:
  Initial:       0.40
  Reinforcement: min(0.85, confidence + 0.05)
  Contradiction: max(0.00, confidence − 0.10)
  Deactivation:  confidence < 0.20 → is_active = False

Asymmetry is intentional: contradicting a stable observation carries higher epistemic
weight than confirming it (same principle as Appraisal surprise vs. reinforcement).

Synthesis trigger: called from social/update.py _run_social_update (already in daemon
thread) after the snapshot/reflection/narrative block. No additional daemon thread.
Threshold: _SEMANTIC_BATCH_MIN = 3 unprocessed episodes.

Isolation invariant: ALL queries filter by user_id. A fact from user A NEVER
influences user B.
Never raises — logs WARN and returns on any error.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from sqlalchemy import text as sa_text
from sqlmodel import Session, select

from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest
from app.memory.db import engine
from app.memory.models import Episode, SemanticFact, utc_now
from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Minimum unprocessed episodes before synthesis fires
_SEMANTIC_BATCH_MIN: int = 3

# Confidence parameters
_SEMANTIC_INITIAL_CONFIDENCE: float = 0.40
SEMANTIC_CONFIDENCE_MAX: float = 0.85
SEMANTIC_DEACTIVATION_THRESHOLD: float = 0.20
_SEMANTIC_REINFORCE_DELTA: float = 0.05
_SEMANTIC_CONTRADICT_DELTA: float = 0.10

_SYNTHESIS_SYSTEM = (
    "You are Sity's semantic consolidation module. Extract stable facts about the user "
    "from these conversation episodes.\n\n"
    "Given the episodes and existing facts (with IDs), return ONLY this JSON:\n"
    '{"new_facts": ["proposition ≤300 chars", ...],\n'
    ' "reinforced_ids": [fact_id, ...],\n'
    ' "contradicted_ids": [fact_id, ...]}\n\n'
    "Rules:\n"
    "- Only include STABLE patterns observed across multiple moments, not one-off events\n"
    "- Propositions must describe the user (e.g. 'User primarily works with Python')\n"
    "- max 5 new_facts per call — genuinely NEW, not already covered by existing facts\n"
    "- If no new facts, reinforcements, or contradictions → return empty lists\n"
    "Output only valid JSON."
)


# ---------------------------------------------------------------------------
# Internal result type
# ---------------------------------------------------------------------------

@dataclass
class _SynthesisResult:
    new_facts: list[str] = field(default_factory=list)
    reinforced_ids: list[int] = field(default_factory=list)
    contradicted_ids: list[int] = field(default_factory=list)


def _parse_synthesis_response(text: str) -> _SynthesisResult | None:
    """Parse Haiku JSON into _SynthesisResult. Returns None on any failure."""
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

        def _clean_list(key: str) -> list[str]:
            raw = data.get(key, [])
            if not isinstance(raw, list):
                return []
            return [str(item).strip()[:300] for item in raw if item and str(item).strip()]

        def _int_list(key: str) -> list[int]:
            raw = data.get(key, [])
            if not isinstance(raw, list):
                return []
            result: list[int] = []
            for item in raw:
                try:
                    result.append(int(item))
                except (ValueError, TypeError):
                    pass
            return result

        return _SynthesisResult(
            new_facts=_clean_list("new_facts"),
            reinforced_ids=_int_list("reinforced_ids"),
            contradicted_ids=_int_list("contradicted_ids"),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _call_synthesis_haiku(
    episodes: list[dict],
    existing_facts: list[SemanticFact],
    *,
    trace_id: str,
) -> _SynthesisResult | None:
    """Call Haiku to synthesise SemanticFacts from a batch of episodes."""
    episodes_text = "\n".join(
        f"- (id={ep['id']}) {ep['summary'][:200]}" for ep in episodes
    )
    if existing_facts:
        facts_text = "\n".join(
            f"- (id={f.id}, conf={f.confidence:.2f}) {f.proposition[:150]}"
            for f in existing_facts
        )
    else:
        facts_text = "(none yet)"

    user_msg = (
        f"Episodes ({len(episodes)} unprocessed):\n{episodes_text}\n\n"
        f"Existing semantic facts:\n{facts_text}"
    )

    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    try:
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="semantic_consolidation",
            system_prompt=_SYNTHESIS_SYSTEM,
            user_message=user_msg,
            max_tokens=400,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if response.ok and response.text:
            result = _parse_synthesis_response(response.text)
            if result is not None:
                return result
        write_log(
            level="WARN",
            module="cognition",
            event="semantic_synthesis_haiku_parse_failed",
            trace_id=trace_id,
            payload={"raw": (response.text or "")[:200]},
        )
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="semantic_synthesis_haiku_error",
            trace_id=trace_id,
            payload={"error": str(exc)[:200]},
        )
    return None


# ---------------------------------------------------------------------------
# Public service functions (pure CRUD — no Haiku calls)
# ---------------------------------------------------------------------------

def load_active_facts(
    session: Session,
    user_id: int,
    *,
    min_confidence: float = 0.0,
    limit: int = 50,
) -> list[SemanticFact]:
    """Load active SemanticFacts for user, sorted by confidence desc.

    Isolation invariant: always filtered by user_id.
    Returns empty list on any error.
    """
    try:
        return list(session.exec(
            select(SemanticFact)
            .where(SemanticFact.user_id == user_id)
            .where(SemanticFact.is_active == True)  # noqa: E712
            .where(SemanticFact.confidence >= min_confidence)
            .order_by(SemanticFact.confidence.desc())  # type: ignore[attr-defined]
            .limit(limit)
        ).all())
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="semantic_facts_load_failed",
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )
        return []


def reinforce_fact(
    session: Session,
    fact_id: int,
    *,
    user_id: int,
    trace_id: str = "",
) -> SemanticFact | None:
    """Increase confidence by _SEMANTIC_REINFORCE_DELTA, capped at SEMANTIC_CONFIDENCE_MAX.

    user_id required for isolation — fact must belong to the calling user.
    Returns updated fact or None if not found, inactive, or isolation violation.
    """
    try:
        fact = session.get(SemanticFact, fact_id)
        if fact is None or fact.user_id != user_id or not fact.is_active:
            return None
        fact.confidence = min(SEMANTIC_CONFIDENCE_MAX, fact.confidence + _SEMANTIC_REINFORCE_DELTA)
        fact.reinforcement_count += 1
        fact.last_confirmed_at = utc_now()
        session.add(fact)
        session.commit()
        return fact
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="semantic_reinforce_failed",
            trace_id=trace_id,
            payload={"fact_id": fact_id, "error": str(exc)[:200]},
        )
        return None


def contradict_fact(
    session: Session,
    fact_id: int,
    *,
    user_id: int,
    trace_id: str = "",
) -> SemanticFact | None:
    """Decrease confidence by _SEMANTIC_CONTRADICT_DELTA. Deactivates if below threshold.

    user_id required for isolation.
    Returns updated fact or None if not found, inactive, or isolation violation.
    """
    try:
        fact = session.get(SemanticFact, fact_id)
        if fact is None or fact.user_id != user_id or not fact.is_active:
            return None
        fact.confidence = max(0.0, fact.confidence - _SEMANTIC_CONTRADICT_DELTA)
        fact.contradiction_count += 1
        fact.last_contradicted_at = utc_now()
        if fact.confidence < SEMANTIC_DEACTIVATION_THRESHOLD:
            fact.is_active = False
        session.add(fact)
        session.commit()
        return fact
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="semantic_contradict_failed",
            trace_id=trace_id,
            payload={"fact_id": fact_id, "error": str(exc)[:200]},
        )
        return None


# ---------------------------------------------------------------------------
# Background synthesis (called inline from social/update.py daemon thread)
# ---------------------------------------------------------------------------

def _run_fact_synthesis(*, user_id: int, trace_id: str = "") -> None:
    """Synthesise SemanticFacts from unprocessed episodes. Opens its own Session.

    Called from maybe_trigger_semantic_consolidation (already in daemon thread).
    Never raises — logs WARN on any error.
    Isolation invariant: all queries filter by user_id.
    """
    try:
        with Session(engine) as db:
            rows = db.execute(
                sa_text(
                    "SELECT id, summary FROM episode"
                    " WHERE user_id = :uid AND semantically_processed = 0"
                    " ORDER BY occurred_at ASC LIMIT 20"
                ),
                {"uid": user_id},
            ).fetchall()

            if len(rows) < _SEMANTIC_BATCH_MIN:
                return

            episode_ids = [r[0] for r in rows]
            episodes_for_llm = [{"id": r[0], "summary": r[1]} for r in rows]

            existing_facts = list(db.exec(
                select(SemanticFact)
                .where(SemanticFact.user_id == user_id)
                .where(SemanticFact.is_active == True)  # noqa: E712
            ).all())

            result = _call_synthesis_haiku(
                episodes_for_llm,
                existing_facts,
                trace_id=trace_id,
            )
            if result is None:
                return

            now = utc_now()

            for prop in result.new_facts[:5]:
                if prop.strip():
                    db.add(SemanticFact(
                        user_id=user_id,
                        proposition=prop.strip()[:300],
                        confidence=_SEMANTIC_INITIAL_CONFIDENCE,
                        source_episode_ids_json=json.dumps(episode_ids),
                    ))

            fact_by_id = {f.id: f for f in existing_facts if f.id is not None}

            for fact_id in result.reinforced_ids:
                fact = fact_by_id.get(fact_id)
                if fact is not None and fact.user_id == user_id and fact.is_active:
                    fact.confidence = min(SEMANTIC_CONFIDENCE_MAX, fact.confidence + _SEMANTIC_REINFORCE_DELTA)
                    fact.reinforcement_count += 1
                    fact.last_confirmed_at = now
                    db.add(fact)

            for fact_id in result.contradicted_ids:
                fact = fact_by_id.get(fact_id)
                if fact is not None and fact.user_id == user_id and fact.is_active:
                    fact.confidence = max(0.0, fact.confidence - _SEMANTIC_CONTRADICT_DELTA)
                    fact.contradiction_count += 1
                    fact.last_contradicted_at = now
                    if fact.confidence < SEMANTIC_DEACTIVATION_THRESHOLD:
                        fact.is_active = False
                    db.add(fact)

            for eid in episode_ids:
                ep = db.get(Episode, eid)
                if ep is not None:
                    ep.semantically_processed = True
                    db.add(ep)

            db.commit()

            write_log(
                level="INFO",
                module="cognition",
                event="semantic_consolidation_completed",
                trace_id=trace_id,
                payload={
                    "user_id": user_id,
                    "episode_batch_size": len(episode_ids),
                    "new_facts": len(result.new_facts),
                    "reinforced": len(result.reinforced_ids),
                    "contradicted": len(result.contradicted_ids),
                },
            )
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="semantic_synthesis_failed",
            trace_id=trace_id,
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )


def maybe_trigger_semantic_consolidation(*, user_id: int, trace_id: str = "") -> None:
    """Check unprocessed episode count; run synthesis inline if threshold reached.

    Called from social/update.py _run_social_update (already in a daemon thread).
    Opens its own Session for the count check, then delegates to _run_fact_synthesis.
    Never raises.
    """
    try:
        with Session(engine) as db:
            count = db.execute(
                sa_text(
                    "SELECT COUNT(*) FROM episode"
                    " WHERE user_id = :uid AND semantically_processed = 0"
                ),
                {"uid": user_id},
            ).scalar() or 0

        if int(count) < _SEMANTIC_BATCH_MIN:
            return

        _run_fact_synthesis(user_id=user_id, trace_id=trace_id)
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="semantic_consolidation_trigger_failed",
            trace_id=trace_id,
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )
