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
            "relation": "support",
            "strength": _SEMANTIC_REINFORCE_RATE,
            "source": source,
            "description": "",
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
            "relation": "contradict",
            "strength": _SEMANTIC_CONTRADICT_RATE,
            "source": source,
            "description": "",
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
                        "relation": "support",
                        "strength": _SEMANTIC_REINFORCE_RATE,
                        "source": "episode_synthesis",
                        "description": "",
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
                        "relation": "contradict",
                        "strength": _SEMANTIC_CONTRADICT_RATE,
                        "source": "episode_synthesis",
                        "description": "",
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
    related_fact_id: int | None = None,
) -> SemanticFact:
    """Create or reinforce a SemanticFact candidate from Reflection output.

    Confidence is clamped to _REFLECTION_INFERRED_CONFIDENCE_MAX (0.45) for "inferred"
    facts. Auto-promotes (candidate=False) when reinforcement_count >= 2 or
    confidence >= 0.55. Uses diminishing-returns formula on reinforce.

    Deduplication: exact proposition match (lowercased). Never raises.
    related_fact_id: set when semantic resolution returned RELATED (Punto 4A).
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
                "relation": "support",
                "strength": _SEMANTIC_REINFORCE_RATE,
                "source": "reflection",
                "description": "",
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
            related_fact_id=related_fact_id,
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

_MAX_CONSOLIDATION_ITEMS: int = 30   # combined SF + SB sent to Haiku

_SEMANTIC_GROUPING_SYSTEM = (
    "You are Sity's memory consolidation module.\n"
    "Given a list of propositions (each with an id), group them semantically.\n\n"
    "Return ONLY valid JSON — no markdown:\n"
    '{"groups": [\n'
    '  {"ids": [<int>, ...], "relation": "match", "canonical_id": <int>},\n'
    '  {"ids": [<int>, ...], "relation": "related"}\n'
    '],\n'
    '"ungrouped": [<int>, ...]}\n\n'
    "Rules:\n"
    '"match": same concept — merge into canonical_id (keep all other ids as duplicates)\n'
    '"related": semantically linked but distinct — record relation only, do NOT merge\n'
    '"ungrouped": ids that do not belong to any group\n'
    "Every proposition id must appear exactly once across groups + ungrouped.\n"
    "Output only valid JSON."
)


def _parse_grouping_response(text: str) -> dict | None:
    """Parse Haiku grouping JSON. Returns dict with 'groups' and 'ungrouped', or None."""
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
        groups_raw = data.get("groups", [])
        ungrouped_raw = data.get("ungrouped", [])
        if not isinstance(groups_raw, list) or not isinstance(ungrouped_raw, list):
            return None
        groups: list[dict] = []
        for g in groups_raw:
            if not isinstance(g, dict):
                continue
            ids_raw = g.get("ids", [])
            if not isinstance(ids_raw, list) or len(ids_raw) < 2:
                continue
            try:
                ids = [int(x) for x in ids_raw]
            except (ValueError, TypeError):
                continue
            rel = str(g.get("relation", "related")).lower()
            if rel not in ("match", "related"):
                rel = "related"
            entry: dict = {"ids": ids, "relation": rel}
            if rel == "match":
                try:
                    entry["canonical_id"] = int(g["canonical_id"])
                except (KeyError, ValueError, TypeError):
                    entry["canonical_id"] = ids[0]
            groups.append(entry)
        try:
            ungrouped = [int(x) for x in ungrouped_raw]
        except (ValueError, TypeError):
            ungrouped = []
        return {"groups": groups, "ungrouped": ungrouped}
    except (json.JSONDecodeError, TypeError):
        return None


def _call_semantic_grouping_haiku(items: list, *, trace_id: str) -> dict:
    """Send all candidates (max _MAX_CONSOLIDATION_ITEMS) to Haiku for semantic grouping.

    Returns parsed grouping dict or {} on failure.
    """
    items_text = "\n".join(
        f"- id={item.id}: {item.proposition[:150]}" for item in items[:_MAX_CONSOLIDATION_ITEMS]
    )
    user_msg = f"Propositions to group ({len(items)}):\n{items_text}"
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    try:
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="semantic_consolidation",
            system_prompt=_SEMANTIC_GROUPING_SYSTEM,
            user_message=user_msg,
            max_tokens=400,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if response.ok and response.text:
            result = _parse_grouping_response(response.text)
            if result is not None:
                return result
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="volume_consolidation_haiku_error",
            trace_id=trace_id,
            payload={"error": str(exc)[:200]},
        )
    return {}


def _normalize_trail_entry(entry: dict, now_iso: str) -> dict:
    """Convert any evidence trail entry to the unified schema.

    Handles old SelfBelief schema {trace_id, type, description} and any
    partially formed entries from earlier code versions.
    """
    _type_to_relation: dict[str, str] = {
        "reflection": "support", "reinforcement": "support",
        "contradiction": "contradict", "contradict": "contradict",
        "self_model_reflection": "support", "support": "support",
    }
    if "trace_id" in entry and "turn_id" not in entry:
        return {
            "turn_id": entry.get("trace_id", ""),
            "relation": _type_to_relation.get(entry.get("type", ""), "support"),
            "strength": 0.20,
            "source": "reflection",
            "description": entry.get("description", ""),
            "timestamp": now_iso,
        }
    return {
        "turn_id": entry.get("turn_id", ""),
        "relation": _type_to_relation.get(entry.get("relation", "support"), "support"),
        "strength": float(entry.get("strength", 0.0)),
        "source": entry.get("source", ""),
        "description": entry.get("description", ""),
        "timestamp": entry.get("timestamp", now_iso),
    }


def _recalculate_confidence_from_scratch(
    initial: float, reinforcement_count: int, contradiction_count: int,
    *, cap: float = SEMANTIC_CONFIDENCE_MAX,
) -> float:
    """Replay diminishing-returns formula from initial value given total evidence counts."""
    conf = initial
    for _ in range(max(0, reinforcement_count)):
        conf = min(cap, conf + (1 - conf) * _SEMANTIC_REINFORCE_RATE)
    for _ in range(max(0, contradiction_count)):
        conf = max(0.0, conf - conf * _SEMANTIC_CONTRADICT_RATE)
    return conf


def _count_active_candidates(user_id: int) -> int:
    """Count combined active SemanticFact + SelfBelief candidates for the given user."""
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
                sa_text(
                    "SELECT COUNT(*) FROM selfbelief"
                    " WHERE self_model_id = (SELECT id FROM selfmodel LIMIT 1)"
                    " AND is_active = 1"
                ),
            ).scalar() or 0
        return int(sf_count) + int(sb_count)
    except Exception:
        return 0


def _run_volume_consolidation(*, user_id: int, trace_id: str = "") -> None:
    """Semantic grouping of active candidates via a single Haiku call.

    Groups are returned as {"match": merge into canonical, "related": link only}.
    MERGE: migrates evidence trail, accumulates counts, recalculates confidence from scratch.
    RELATED: no structural change — recorded for traceability only.
    Called in a daemon thread from maybe_trigger_volume_consolidation. Never raises.
    """
    from app.memory.models import SelfBelief
    from app.cognition.self_model_service import get_or_create_self_model

    try:
        with Session(engine) as db:
            sf_candidates = list(db.exec(
                select(SemanticFact)
                .where(SemanticFact.user_id == user_id)
                .where(SemanticFact.candidate == True)  # noqa: E712
                .where(SemanticFact.is_active == True)  # noqa: E712
            ).all())

            sm = get_or_create_self_model(db)
            sb_candidates: list[SelfBelief] = []
            if sm.id is not None:
                sb_candidates = list(db.exec(
                    select(SelfBelief)
                    .where(SelfBelief.self_model_id == sm.id)
                    .where(SelfBelief.is_active == True)  # noqa: E712
                ).all())

            all_items = (sf_candidates + sb_candidates)[:_MAX_CONSOLIDATION_ITEMS]
            if len(all_items) < 2:
                return

            grouping = _call_semantic_grouping_haiku(all_items, trace_id=trace_id)
            if not grouping:
                return

            sf_by_id = {f.id: f for f in sf_candidates if f.id is not None}
            sb_by_id = {b.id: b for b in sb_candidates if b.id is not None}
            now = utc_now()
            now_iso = now.isoformat()
            merged_sf = merged_sb = contradicted_sb = 0

            for group in grouping.get("groups", []):
                relation = str(group.get("relation", "")).lower()
                ids: list[int] = group.get("ids", [])
                if relation != "match" or len(ids) < 2:
                    continue
                canonical_id = group.get("canonical_id", ids[0])
                dup_ids = [i for i in ids if i != canonical_id]

                # ── SemanticFact merge ──────────────────────────────────────
                canonical_sf = sf_by_id.get(canonical_id)
                if canonical_sf is not None:
                    for dup_id in dup_ids:
                        dup = sf_by_id.get(dup_id)
                        if dup is None or not dup.is_active:
                            continue
                        keep_trail = json.loads(canonical_sf.evidence_trail_json)
                        for e in json.loads(dup.evidence_trail_json):
                            keep_trail.append(_normalize_trail_entry(e, now_iso))
                        canonical_sf.evidence_trail_json = json.dumps(keep_trail)
                        canonical_sf.reinforcement_count += dup.reinforcement_count
                        canonical_sf.contradiction_count += dup.contradiction_count
                        canonical_sf.confidence = _recalculate_confidence_from_scratch(
                            initial=0.30 if canonical_sf.inference_type == "inferred" else 0.45,
                            reinforcement_count=canonical_sf.reinforcement_count,
                            contradiction_count=canonical_sf.contradiction_count,
                        )
                        canonical_sf.last_confirmed_at = now
                        dup.is_active = False
                        db.add(canonical_sf)
                        db.add(dup)
                        merged_sf += 1
                    continue

                # ── SelfBelief merge ────────────────────────────────────────
                canonical_sb = sb_by_id.get(canonical_id)
                if canonical_sb is not None:
                    for dup_id in dup_ids:
                        dup_sb = sb_by_id.get(dup_id)
                        if dup_sb is None or not dup_sb.is_active:
                            continue
                        kt = json.loads(canonical_sb.evidence_trail_json)
                        for e in json.loads(dup_sb.evidence_trail_json):
                            kt.append(_normalize_trail_entry(e, now_iso))
                        canonical_sb.evidence_trail_json = json.dumps(kt)
                        total_rc = sum(
                            1 for e in json.loads(canonical_sb.evidence_trail_json)
                            if e.get("relation") == "support"
                        )
                        total_cc = sum(
                            1 for e in json.loads(canonical_sb.evidence_trail_json)
                            if e.get("relation") == "contradict"
                        )
                        canonical_sb.confidence = _recalculate_confidence_from_scratch(
                            initial=0.30,
                            reinforcement_count=total_rc,
                            contradiction_count=total_cc,
                            cap=1.0,
                        )
                        canonical_sb.updated_at = now
                        dup_sb.is_active = False
                        dup_sb.updated_at = now
                        db.add(canonical_sb)
                        db.add(dup_sb)
                        merged_sb += 1

            # ── SelfBelief CONTRADICT (previously ignored) ──────────────────
            # For now, CONTRADICT groups from Haiku are handled if they appear in
            # the "related" group — actual contradiction tracking happens via
            # the resolve_candidate path in add_self_model_observation.
            # A dedicated SB contradict pass is not part of the grouping schema above
            # (groups only have "match" | "related"), so this is a no-op here.
            # The fix to avoid SelfBelief accumulation is handled upstream.

            db.commit()

        write_log(
            level="INFO",
            module="cognition",
            event="volume_consolidation_completed",
            trace_id=trace_id,
            payload={
                "user_id": user_id,
                "merged_sf": merged_sf,
                "merged_sb": merged_sb,
                "contradicted_sb": contradicted_sb,
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
