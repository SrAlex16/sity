"""semantic_service.py — Semantic fact consolidation (Remake Fase 9).

Extracts and maintains stable facts about the user from episodic memory.

Architecture (sección 25/59):
  1. Background synthesis: batch of unprocessed episodes → Haiku extracts stable facts.
  2. Reinforcement: episodes confirming a fact increase confidence (diminishing returns).
  3. Contradiction: episodes contradicting a fact decrease confidence (relative);
     facts below 0.20 are deactivated. Revision-downward from the start.
  4. Read-only integration in Reflection Step: top-5 facts by confidence injected
     as additional context in the Haiku prompt (no extra call — zero marginal cost).

Confidence formula (Punto 4C — diminishing returns):
  Reinforcement: confidence += (1 - confidence) * _SEMANTIC_REINFORCE_RATE  (0.20)
  Contradiction: confidence -= confidence * _SEMANTIC_CONTRADICT_RATE        (0.15)
  Deactivation:  confidence < 0.20 → is_active = False

Asymmetry is intentional: contradicting a stable observation carries higher epistemic
weight than confirming it.

Synthesis trigger: called from social/update.py _run_social_update (already in daemon
thread) after the snapshot/reflection/narrative block. No additional daemon thread.
Threshold: _SEMANTIC_BATCH_MIN = 3 unprocessed episodes.

Volume consolidation trigger (Punto 4D): after each new candidate insertion, if
total active SelfBelief + SemanticFact candidates >= _CONSOLIDATION_VOLUME_TRIGGER (10),
a background daemon thread runs _run_volume_consolidation.

Isolation invariant: ALL queries filter by user_id. A fact from user A NEVER
influences user B.
Never raises — logs WARN and returns on any error.
"""
from __future__ import annotations

import json
import os
import threading
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

# Diminishing-returns learning rates (Punto 4C)
_SEMANTIC_REINFORCE_RATE: float = 0.20   # confidence += (1 - confidence) * rate
_SEMANTIC_CONTRADICT_RATE: float = 0.15  # confidence -= confidence * rate

# Volume consolidation trigger (Punto 4D)
_CONSOLIDATION_VOLUME_TRIGGER: int = 10

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
    source: str = "synthesis",
) -> SemanticFact | None:
    """Increase confidence with diminishing returns: confidence += (1-confidence)*0.20.

    user_id required for isolation — fact must belong to the calling user.
    Returns updated fact or None if not found, inactive, or isolation violation.
    Appends to evidence_trail_json.
    """
    try:
        fact = session.get(SemanticFact, fact_id)
        if fact is None or fact.user_id != user_id or not fact.is_active:
            return None
        now = utc_now()
        fact.confidence = min(
            SEMANTIC_CONFIDENCE_MAX,
            fact.confidence + (1 - fact.confidence) * _SEMANTIC_REINFORCE_RATE,
        )
        fact.reinforcement_count += 1
        fact.last_confirmed_at = now
        trail: list[dict] = json.loads(fact.evidence_trail_json)
        trail.append({
            "turn_id": trace_id,
            "relation": "reinforcement",
            "strength": _SEMANTIC_REINFORCE_RATE,
            "source": source,
            "timestamp": now.isoformat(),
        })
        fact.evidence_trail_json = json.dumps(trail)
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
    source: str = "synthesis",
) -> SemanticFact | None:
    """Decrease confidence: confidence -= confidence * 0.15. Deactivates if below threshold.

    user_id required for isolation.
    Returns updated fact or None if not found, inactive, or isolation violation.
    Appends to evidence_trail_json.
    """
    try:
        fact = session.get(SemanticFact, fact_id)
        if fact is None or fact.user_id != user_id or not fact.is_active:
            return None
        now = utc_now()
        fact.confidence = max(0.0, fact.confidence - fact.confidence * _SEMANTIC_CONTRADICT_RATE)
        fact.contradiction_count += 1
        fact.last_contradicted_at = now
        trail: list[dict] = json.loads(fact.evidence_trail_json)
        trail.append({
            "turn_id": trace_id,
            "relation": "contradiction",
            "strength": _SEMANTIC_CONTRADICT_RATE,
            "source": source,
            "timestamp": now.isoformat(),
        })
        fact.evidence_trail_json = json.dumps(trail)
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
                    fact.confidence = min(
                        SEMANTIC_CONFIDENCE_MAX,
                        fact.confidence + (1 - fact.confidence) * _SEMANTIC_REINFORCE_RATE,
                    )
                    fact.reinforcement_count += 1
                    fact.last_confirmed_at = now
                    trail: list[dict] = json.loads(fact.evidence_trail_json)
                    trail.append({
                        "turn_id": trace_id,
                        "relation": "reinforcement",
                        "strength": _SEMANTIC_REINFORCE_RATE,
                        "source": "episode_synthesis",
                        "timestamp": now.isoformat(),
                    })
                    fact.evidence_trail_json = json.dumps(trail)
                    db.add(fact)

            for fact_id in result.contradicted_ids:
                fact = fact_by_id.get(fact_id)
                if fact is not None and fact.user_id == user_id and fact.is_active:
                    fact.confidence = max(0.0, fact.confidence - fact.confidence * _SEMANTIC_CONTRADICT_RATE)
                    fact.contradiction_count += 1
                    fact.last_contradicted_at = now
                    trail2: list[dict] = json.loads(fact.evidence_trail_json)
                    trail2.append({
                        "turn_id": trace_id,
                        "relation": "contradiction",
                        "strength": _SEMANTIC_CONTRADICT_RATE,
                        "source": "episode_synthesis",
                        "timestamp": now.isoformat(),
                    })
                    fact.evidence_trail_json = json.dumps(trail2)
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


# ---------------------------------------------------------------------------
# Reflection candidate upsert (Punto 6)
# ---------------------------------------------------------------------------

_REFLECTION_INFERRED_CONFIDENCE_MAX: float = 0.45   # cap for "inferred" candidates
_REFLECTION_CANDIDATE_PROMOTE_REINFORCEMENTS: int = 2
_REFLECTION_CANDIDATE_PROMOTE_CONFIDENCE: float = 0.55


def upsert_semantic_candidate(
    session: Session,
    *,
    user_id: int,
    proposition: str,
    inference_type: str = "inferred",
    confidence: float,
    trace_id: str = "",
    related_belief_id: int | None = None,
) -> SemanticFact:
    """Create or reinforce a SemanticFact candidate from Reflection output.

    Confidence is clamped to _REFLECTION_INFERRED_CONFIDENCE_MAX (0.45) for "inferred"
    facts. Auto-promotes (candidate=False) when reinforcement_count >= 2 or
    confidence >= 0.55. Uses diminishing-returns formula on reinforce.

    Deduplication: exact proposition match (lowercased). Never raises.
    related_belief_id: set when semantic resolution returned RELATED (Punto 4A).
    """
    if inference_type not in ("inferred", "explicit"):
        inference_type = "inferred"
    if inference_type == "inferred":
        confidence = min(_REFLECTION_INFERRED_CONFIDENCE_MAX, confidence)
    confidence = max(0.0, min(1.0, confidence))
    prop_clean = proposition.strip()[:300]

    try:
        existing = session.exec(
            select(SemanticFact)
            .where(SemanticFact.user_id == user_id)
            .where(SemanticFact.proposition == prop_clean)
            .where(SemanticFact.is_active == True)  # noqa: E712
        ).first()

        if existing is not None:
            now = utc_now()
            existing.confidence = min(
                SEMANTIC_CONFIDENCE_MAX,
                existing.confidence + (1 - existing.confidence) * _SEMANTIC_REINFORCE_RATE,
            )
            existing.reinforcement_count += 1
            existing.last_confirmed_at = now
            trail: list[dict] = json.loads(existing.evidence_trail_json)
            trail.append({
                "turn_id": trace_id,
                "relation": "reinforcement",
                "strength": _SEMANTIC_REINFORCE_RATE,
                "source": "reflection",
                "timestamp": now.isoformat(),
            })
            existing.evidence_trail_json = json.dumps(trail)
            if existing.candidate and (
                existing.reinforcement_count >= _REFLECTION_CANDIDATE_PROMOTE_REINFORCEMENTS
                or existing.confidence >= _REFLECTION_CANDIDATE_PROMOTE_CONFIDENCE
            ):
                existing.candidate = False
            session.add(existing)
            session.commit()
            return existing

        fact = SemanticFact(
            user_id=user_id,
            proposition=prop_clean,
            confidence=confidence,
            inference_type=inference_type,
            candidate=True,
            source_episode_ids_json="[]",
            related_belief_id=related_belief_id,
        )
        session.add(fact)
        session.commit()
        session.refresh(fact)
        return fact
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="semantic_candidate_upsert_failed",
            trace_id=trace_id,
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )
        return SemanticFact(user_id=user_id, proposition=prop_clean, confidence=confidence)


_SEMANTIC_PASSIVE_DECAY: float = 0.02       # confidence penalty per cycle for unstable facts
_SEMANTIC_PASSIVE_DECAY_MIN_CONFIDENCE: float = 0.65
_SEMANTIC_PASSIVE_DECAY_MIN_REINFORCEMENTS: int = 3


def apply_semantic_fact_decay(*, user_id: int, trace_id: str = "") -> None:
    """Apply passive confidence decay to under-reinforced, low-confidence facts.

    Targets: active facts where confidence < 0.65 AND reinforcement_count < 3
    AND stability != "stable". Deactivates any fact whose confidence drops below
    SEMANTIC_DEACTIVATION_THRESHOLD after decay.

    Called from maybe_trigger_semantic_consolidation() every synthesis cycle.
    Never raises.
    """
    try:
        with Session(engine) as db:
            stmt = select(SemanticFact).where(
                SemanticFact.user_id == user_id,
                SemanticFact.is_active == True,  # noqa: E712
                SemanticFact.confidence < _SEMANTIC_PASSIVE_DECAY_MIN_CONFIDENCE,
                SemanticFact.reinforcement_count < _SEMANTIC_PASSIVE_DECAY_MIN_REINFORCEMENTS,
                SemanticFact.stability != "stable",
            )
            facts = db.exec(stmt).all()
            if not facts:
                return
            decayed = 0
            deactivated = 0
            for fact in facts:
                fact.confidence = max(0.0, fact.confidence - _SEMANTIC_PASSIVE_DECAY)
                if fact.confidence < SEMANTIC_DEACTIVATION_THRESHOLD:
                    fact.is_active = False
                    deactivated += 1
                else:
                    decayed += 1
                db.add(fact)
            db.commit()
            if decayed or deactivated:
                write_log(
                    level="INFO",
                    module="cognition",
                    event="semantic_passive_decay_applied",
                    trace_id=trace_id,
                    payload={"user_id": user_id, "decayed": decayed, "deactivated": deactivated},
                )
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="semantic_passive_decay_failed",
            trace_id=trace_id,
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )


def maybe_trigger_semantic_consolidation(*, user_id: int, trace_id: str = "") -> None:
    """Check unprocessed episode count; run synthesis inline if threshold reached.

    Called from social/update.py _run_social_update (already in a daemon thread).
    Opens its own Session for the count check, then delegates to _run_fact_synthesis.
    Also applies passive fact decay each cycle.
    Never raises.
    """
    try:
        apply_semantic_fact_decay(user_id=user_id, trace_id=trace_id)

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


# ---------------------------------------------------------------------------
# Volume consolidation (Punto 4D)
# ---------------------------------------------------------------------------

_VOLUME_CONSOLIDATION_SYSTEM = (
    "You are Sity's memory consolidation module.\n"
    "Given a cluster of similar propositions, classify each pair's relation.\n\n"
    "Return ONLY valid JSON — no markdown:\n"
    '{"pairs": [{"a_id": <int>, "b_id": <int>, "relation": "MERGE|DISTINCT|CONTRADICT", '
    '"reason": "<brief>"}]}\n\n'
    "MERGE: same concept — should be combined into one entry\n"
    "CONTRADICT: directly opposing claims about the same subject\n"
    "DISTINCT: related but genuinely different — keep separate"
)


def _parse_consolidation_response(text: str) -> list[dict]:
    """Parse Haiku JSON into a list of pair dicts. Returns [] on any failure."""
    try:
        stripped = text.strip()
        if stripped.startswith("```"):
            parts = stripped.split("```")
            stripped = parts[1] if len(parts) > 1 else stripped
            if stripped.startswith("json"):
                stripped = stripped[4:]
        data = json.loads(stripped)
        if not isinstance(data, dict):
            return []
        pairs = data.get("pairs", [])
        if not isinstance(pairs, list):
            return []
        result: list[dict] = []
        for p in pairs:
            if not isinstance(p, dict):
                continue
            try:
                a_id = int(p["a_id"])
                b_id = int(p["b_id"])
                rel = str(p.get("relation", "DISTINCT")).upper()
                if rel not in ("MERGE", "DISTINCT", "CONTRADICT"):
                    rel = "DISTINCT"
                reason = str(p.get("reason", ""))[:200]
                result.append({"a_id": a_id, "b_id": b_id, "relation": rel, "reason": reason})
            except (KeyError, ValueError, TypeError):
                continue
        return result
    except (json.JSONDecodeError, TypeError):
        return []


def _cluster_by_first_words(items: list) -> list[list]:
    """Group items by first 3 words of proposition (lowercased). Returns clusters of size >= 2."""
    clusters: dict[str, list] = {}
    for item in items:
        key = " ".join(item.proposition.strip().lower().split()[:3])
        clusters.setdefault(key, []).append(item)
    return [c for c in clusters.values() if len(c) >= 2]


def _call_cluster_haiku(items: list, *, trace_id: str) -> list[dict]:
    """Call Haiku to classify pairs within a cluster. Returns [] on failure."""
    items_text = "\n".join(
        f"- id={item.id}: {item.proposition[:150]}" for item in items
    )
    user_msg = f"Cluster of propositions to classify:\n{items_text}"
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    try:
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="semantic_consolidation",
            system_prompt=_VOLUME_CONSOLIDATION_SYSTEM,
            user_message=user_msg,
            max_tokens=300,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if response.ok and response.text:
            return _parse_consolidation_response(response.text)
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="volume_consolidation_haiku_error",
            trace_id=trace_id,
            payload={"error": str(exc)[:200]},
        )
    return []


def _count_active_candidates(user_id: int) -> int:
    """Count combined active SelfBelief + SemanticFact candidates for the given user."""
    try:
        with Session(engine) as db:
            sf_count = db.execute(
                sa_text(
                    "SELECT COUNT(*) FROM semanticfact"
                    " WHERE user_id = :uid AND candidate = 1 AND is_active = 1"
                ),
                {"uid": user_id},
            ).scalar() or 0
            sb_count = db.execute(
                sa_text("SELECT COUNT(*) FROM selfbelief WHERE is_active = 1")
            ).scalar() or 0
        return int(sf_count) + int(sb_count)
    except Exception:
        return 0


def _run_volume_consolidation(*, user_id: int, trace_id: str = "") -> None:
    """Cluster active candidates and merge/contradict pairs identified by Haiku.

    Called in a daemon thread from maybe_trigger_volume_consolidation.
    Never raises.
    """
    from app.memory.models import SelfBelief
    from app.cognition.self_model_service import (
        get_or_create_self_model,
        _BELIEF_REINFORCE_RATE,  # type: ignore[attr-defined]
    )

    try:
        with Session(engine) as db:
            # SemanticFact candidates for this user
            sf_candidates = list(db.exec(
                select(SemanticFact)
                .where(SemanticFact.user_id == user_id)
                .where(SemanticFact.candidate == True)  # noqa: E712
                .where(SemanticFact.is_active == True)  # noqa: E712
            ).all())

            # SelfBelief candidates (global — one SelfModel)
            sm = get_or_create_self_model(db)
            sb_candidates: list[SelfBelief] = []
            if sm.id is not None:
                sb_candidates = list(db.exec(
                    select(SelfBelief)
                    .where(SelfBelief.self_model_id == sm.id)
                    .where(SelfBelief.is_active == True)  # noqa: E712
                ).all())

            now = utc_now()
            sf_clusters = _cluster_by_first_words(sf_candidates)
            sb_clusters = _cluster_by_first_words(sb_candidates)
            merged_sf = contradicted_sf = merged_sb = 0

            for cluster in sf_clusters:
                for pair in _call_cluster_haiku(cluster, trace_id=trace_id):
                    a = next((x for x in cluster if x.id == pair["a_id"]), None)
                    b = next((x for x in cluster if x.id == pair["b_id"]), None)
                    if a is None or b is None:
                        continue
                    if pair["relation"] == "MERGE":
                        keep, dup = (a, b) if (a.id or 0) <= (b.id or 0) else (b, a)
                        keep_trail: list[dict] = json.loads(keep.evidence_trail_json)
                        keep_trail.extend(json.loads(dup.evidence_trail_json))
                        keep.evidence_trail_json = json.dumps(keep_trail)
                        keep.confidence = min(
                            SEMANTIC_CONFIDENCE_MAX,
                            keep.confidence + (1 - keep.confidence) * _SEMANTIC_REINFORCE_RATE,
                        )
                        keep.reinforcement_count += 1
                        keep.last_confirmed_at = now
                        dup.is_active = False
                        db.add(keep)
                        db.add(dup)
                        merged_sf += 1
                    elif pair["relation"] == "CONTRADICT":
                        for item in (a, b):
                            item.confidence = max(
                                0.0, item.confidence - item.confidence * _SEMANTIC_CONTRADICT_RATE
                            )
                            item.contradiction_count += 1
                            item.last_contradicted_at = now
                            ct: list[dict] = json.loads(item.evidence_trail_json)
                            ct.append({
                                "turn_id": trace_id,
                                "relation": "contradiction",
                                "strength": _SEMANTIC_CONTRADICT_RATE,
                                "source": "volume_consolidation",
                                "timestamp": now.isoformat(),
                            })
                            item.evidence_trail_json = json.dumps(ct)
                            if item.confidence < SEMANTIC_DEACTIVATION_THRESHOLD:
                                item.is_active = False
                            db.add(item)
                        contradicted_sf += 1

            for cluster in sb_clusters:
                for pair in _call_cluster_haiku(cluster, trace_id=trace_id):
                    a_id, b_id = pair["a_id"], pair["b_id"]
                    if pair["relation"] != "MERGE":
                        continue
                    keep_id, dup_id = (min(a_id, b_id), max(a_id, b_id))
                    keep_sb = db.get(SelfBelief, keep_id)
                    dup_sb = db.get(SelfBelief, dup_id)
                    if keep_sb is None or dup_sb is None:
                        continue
                    kt: list[dict] = json.loads(keep_sb.evidence_trail_json)
                    kt.extend(json.loads(dup_sb.evidence_trail_json))
                    keep_sb.evidence_trail_json = json.dumps(kt)
                    keep_sb.confidence = min(
                        1.0,
                        keep_sb.confidence + (1 - keep_sb.confidence) * _BELIEF_REINFORCE_RATE,
                    )
                    keep_sb.updated_at = now
                    dup_sb.is_active = False
                    dup_sb.updated_at = now
                    db.add(keep_sb)
                    db.add(dup_sb)
                    merged_sb += 1

            db.commit()

        write_log(
            level="INFO",
            module="cognition",
            event="volume_consolidation_completed",
            trace_id=trace_id,
            payload={
                "user_id": user_id,
                "sf_clusters": len(sf_clusters),
                "sf_merged": merged_sf,
                "sf_contradicted": contradicted_sf,
                "sb_clusters": len(sb_clusters),
                "sb_merged": merged_sb,
            },
        )
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="volume_consolidation_failed",
            trace_id=trace_id,
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )


def maybe_trigger_volume_consolidation(*, user_id: int, trace_id: str = "") -> None:
    """Fire _run_volume_consolidation in a daemon thread when candidate count >= 10.

    Called after each new SemanticFact candidate is inserted from Reflection.
    Never raises.
    """
    try:
        count = _count_active_candidates(user_id)
        if count < _CONSOLIDATION_VOLUME_TRIGGER:
            return
        threading.Thread(
            target=_run_volume_consolidation,
            kwargs={"user_id": user_id, "trace_id": trace_id},
            daemon=True,
        ).start()
    except Exception:
        pass
