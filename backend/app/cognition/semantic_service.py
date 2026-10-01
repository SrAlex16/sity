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
background daemon threads run _run_sf_volume_consolidation and _run_sb_volume_consolidation independently.

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

        now = utc_now()
        initial_trail: list[dict] = [{
            "turn_id": trace_id,
            "relation": "initial",
            "strength": confidence,
            "source": "reflection_initial",
            "description": "initial candidate",
            "timestamp": now.isoformat(),
        }]
        fact = SemanticFact(
            user_id=user_id,
            proposition=prop_clean,
            confidence=confidence,
            inference_type=inference_type,
            candidate=True,
            source_episode_ids_json="[]",
            related_fact_id=related_fact_id,
            evidence_trail_json=json.dumps(initial_trail),
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
    '  {"ids": [<int>, ...], "relation": "contradict"},\n'
    '  {"ids": [<int>, ...], "relation": "related"}\n'
    '],\n'
    '"ungrouped": [<int>, ...]}\n\n'
    "Rules:\n"
    '"match": same concept — merge into canonical_id (keep all other ids as duplicates)\n'
    '"contradict": opposite claims about the same concept — record contradiction, do NOT merge\n'
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
            if rel not in ("match", "related", "contradict"):
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
    Preserves target_id (used for CONTRADICT idempotency checks).
    """
    _type_to_relation: dict[str, str] = {
        "reflection": "support", "reinforcement": "support",
        "contradiction": "contradict", "contradict": "contradict",
        "self_model_reflection": "support", "support": "support",
        "initial": "initial",
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
    result: dict = {
        "turn_id": entry.get("turn_id", ""),
        "relation": _type_to_relation.get(entry.get("relation", "support"), "support"),
        "strength": float(entry.get("strength", 0.0)),
        "source": entry.get("source", ""),
        "description": entry.get("description", ""),
        "timestamp": entry.get("timestamp", now_iso),
    }
    if "target_id" in entry:
        result["target_id"] = entry["target_id"]
    return result


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


def recalculate_confidence_from_trail(
    trail: list[dict],
    initial: float = 0.0,
    learning_rate: float = _SEMANTIC_REINFORCE_RATE,
    contradiction_rate: float = _SEMANTIC_CONTRADICT_RATE,
    *,
    cap: float = SEMANTIC_CONFIDENCE_MAX,
) -> float:
    """Derive confidence by replaying evidence trail entries in chronological order.

    Order matters: support→contradict→support differs from support→support→contradict.
    initial: baseline confidence before any trail entry (use 0.0 to replay all evidence
    including the initial creation entry).

    Relation semantics:
      "initial"   — first entry sets the prior (confidence = strength); subsequent
                    "initial" entries act as weighted support.
      "support"   — confidence += (1 − confidence) * learning_rate * strength
      "contradict"— confidence −= confidence * contradiction_rate * strength

    Returns value clamped to [0.0, cap].
    """
    evidence = sorted(trail, key=lambda e: e.get("timestamp", ""))
    seen_first_initial = False
    confidence = initial
    for ev in evidence:
        rel = ev.get("relation", "")
        strength = float(ev.get("strength", 0.5))
        if rel == "initial":
            if not seen_first_initial:
                confidence = min(cap, max(0.0, strength))
                seen_first_initial = True
            else:
                rate = learning_rate * strength
                confidence = min(cap, confidence + (1 - confidence) * rate)
        elif rel == "support":
            rate = learning_rate * strength
            confidence = min(cap, confidence + (1 - confidence) * rate)
        elif rel == "contradict":
            rate = contradiction_rate * strength
            confidence = max(0.0, confidence - confidence * rate)
    return confidence


def _count_active_semantic_facts(user_id: int) -> int:
    """Count active SemanticFact candidates for user_id."""
    try:
        with Session(engine) as db:
            count = db.execute(
                sa_text(
                    "SELECT COUNT(*) FROM semanticfact"
                    " WHERE user_id = :uid AND candidate = 1 AND is_active = 1"
                ),
                {"uid": user_id},
            ).scalar() or 0
        return int(count)
    except Exception:
        return 0


def _count_active_self_beliefs() -> int:
    """Count active SelfBelief rows (global self-model, no user_id filter)."""
    try:
        with Session(engine) as db:
            count = db.execute(
                sa_text(
                    "SELECT COUNT(*) FROM selfbelief"
                    " WHERE self_model_id = (SELECT id FROM selfmodel LIMIT 1)"
                    " AND is_active = 1"
                ),
            ).scalar() or 0
        return int(count)
    except Exception:
        return 0


def _run_sf_volume_consolidation(*, user_id: int, trace_id: str = "") -> None:
    """Consolidate SemanticFact candidates for user_id via Haiku semantic grouping.

    MATCH: merge duplicates into canonical — migrate trail, recalculate from trail.
    CONTRADICT: cross-add contradict entries to both facts, recalculate confidence.
    RELATED: no structural change.
    Called in a daemon thread. Never raises.
    """
    try:
        with Session(engine) as db:
            sf_candidates = list(db.exec(
                select(SemanticFact)
                .where(SemanticFact.user_id == user_id)
                .where(SemanticFact.candidate == True)  # noqa: E712
                .where(SemanticFact.is_active == True)  # noqa: E712
            ).all())

            if len(sf_candidates) < 2:
                return

            grouping = _call_semantic_grouping_haiku(sf_candidates, trace_id=trace_id)
            if not grouping:
                return

            sf_by_id = {f.id: f for f in sf_candidates if f.id is not None}
            now = utc_now()
            now_iso = now.isoformat()
            merged = 0
            contradicted = 0

            for group in grouping.get("groups", []):
                relation = str(group.get("relation", "")).lower()
                ids: list[int] = group.get("ids", [])

                if relation == "match" and len(ids) >= 2:
                    canonical_id = group.get("canonical_id", ids[0])
                    canonical = sf_by_id.get(canonical_id)
                    if canonical is None:
                        continue
                    for dup_id in ids:
                        if dup_id == canonical_id:
                            continue
                        dup = sf_by_id.get(dup_id)
                        if dup is None or not dup.is_active:
                            continue
                        merged_trail: list[dict] = json.loads(canonical.evidence_trail_json)
                        for e in json.loads(dup.evidence_trail_json):
                            merged_trail.append(_normalize_trail_entry(e, now_iso))
                        merged_trail.sort(key=lambda e: e.get("timestamp", ""))
                        canonical.evidence_trail_json = json.dumps(merged_trail)
                        canonical.reinforcement_count = sum(
                            1 for e in merged_trail if e.get("relation") == "support"
                        )
                        canonical.contradiction_count = sum(
                            1 for e in merged_trail if e.get("relation") == "contradict"
                        )
                        canonical.confidence = recalculate_confidence_from_trail(
                            merged_trail, initial=0.0,
                        )
                        canonical.last_confirmed_at = now
                        dup.is_active = False
                        db.add(canonical)
                        db.add(dup)
                        merged += 1

                elif relation == "contradict" and len(ids) >= 2:
                    for aid in ids:
                        fact_a = sf_by_id.get(aid)
                        if fact_a is None or not fact_a.is_active:
                            continue
                        trail_a: list[dict] = json.loads(fact_a.evidence_trail_json)
                        for bid in ids:
                            if bid == aid:
                                continue
                            if sf_by_id.get(bid) is None:
                                continue
                            already_known = any(
                                e.get("relation") == "contradict"
                                and e.get("target_id") == bid
                                and e.get("source") == "semantic_consolidation"
                                for e in trail_a
                            )
                            if already_known:
                                continue
                            trail_a.append({
                                "turn_id": trace_id,
                                "relation": "contradict",
                                "strength": _SEMANTIC_CONTRADICT_RATE,
                                "target_id": bid,
                                "source": "semantic_consolidation",
                                "description": f"contradicts id={bid}",
                                "timestamp": now_iso,
                            })
                            fact_a.contradiction_count += 1
                            contradicted += 1
                        fact_a.evidence_trail_json = json.dumps(trail_a)
                        fact_a.confidence = recalculate_confidence_from_trail(
                            trail_a, initial=0.0,
                        )
                        if fact_a.confidence < SEMANTIC_DEACTIVATION_THRESHOLD:
                            fact_a.is_active = False
                        db.add(fact_a)

            db.commit()

        write_log(
            level="INFO",
            module="cognition",
            event="sf_volume_consolidation_completed",
            trace_id=trace_id,
            payload={"user_id": user_id, "merged": merged, "contradicted": contradicted},
        )
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="sf_volume_consolidation_failed",
            trace_id=trace_id,
            payload={"user_id": user_id, "error": str(exc)[:200]},
        )


def _run_sb_volume_consolidation(*, trace_id: str = "") -> None:
    """Consolidate SelfBelief candidates (global) via Haiku semantic grouping.

    MATCH: merge duplicates into canonical — migrate trail, recalculate from trail.
    CONTRADICT: cross-add contradict entries to both beliefs, recalculate confidence.
    RELATED: no structural change.
    Called in a daemon thread. Never raises.
    """
    from app.memory.models import SelfBelief
    from app.cognition.self_model_service import get_or_create_self_model

    try:
        with Session(engine) as db:
            sm = get_or_create_self_model(db)
            if sm.id is None:
                return
            sb_candidates: list[SelfBelief] = list(db.exec(
                select(SelfBelief)
                .where(SelfBelief.self_model_id == sm.id)
                .where(SelfBelief.is_active == True)  # noqa: E712
            ).all())

            if len(sb_candidates) < 2:
                return

            grouping = _call_semantic_grouping_haiku(sb_candidates, trace_id=trace_id)
            if not grouping:
                return

            sb_by_id = {b.id: b for b in sb_candidates if b.id is not None}
            now = utc_now()
            now_iso = now.isoformat()
            merged = 0
            contradicted = 0

            for group in grouping.get("groups", []):
                relation = str(group.get("relation", "")).lower()
                ids: list[int] = group.get("ids", [])

                if relation == "match" and len(ids) >= 2:
                    canonical_id = group.get("canonical_id", ids[0])
                    canonical = sb_by_id.get(canonical_id)
                    if canonical is None:
                        continue
                    for dup_id in ids:
                        if dup_id == canonical_id:
                            continue
                        dup = sb_by_id.get(dup_id)
                        if dup is None or not dup.is_active:
                            continue
                        merged_trail: list[dict] = json.loads(canonical.evidence_trail_json)
                        for e in json.loads(dup.evidence_trail_json):
                            merged_trail.append(_normalize_trail_entry(e, now_iso))
                        merged_trail.sort(key=lambda e: e.get("timestamp", ""))
                        canonical.evidence_trail_json = json.dumps(merged_trail)
                        canonical.confidence = recalculate_confidence_from_trail(
                            merged_trail, initial=0.0, cap=1.0,
                        )
                        canonical.updated_at = now
                        dup.is_active = False
                        dup.updated_at = now
                        db.add(canonical)
                        db.add(dup)
                        merged += 1

                elif relation == "contradict" and len(ids) >= 2:
                    for aid in ids:
                        belief_a = sb_by_id.get(aid)
                        if belief_a is None or not belief_a.is_active:
                            continue
                        trail_a: list[dict] = json.loads(belief_a.evidence_trail_json)
                        for bid in ids:
                            if bid == aid:
                                continue
                            if sb_by_id.get(bid) is None:
                                continue
                            already_known = any(
                                e.get("relation") == "contradict"
                                and e.get("target_id") == bid
                                and e.get("source") == "semantic_consolidation"
                                for e in trail_a
                            )
                            if already_known:
                                continue
                            trail_a.append({
                                "turn_id": trace_id,
                                "relation": "contradict",
                                "strength": _SEMANTIC_CONTRADICT_RATE,
                                "target_id": bid,
                                "source": "semantic_consolidation",
                                "description": f"contradicts id={bid}",
                                "timestamp": now_iso,
                            })
                            contradicted += 1
                        belief_a.evidence_trail_json = json.dumps(trail_a)
                        belief_a.confidence = recalculate_confidence_from_trail(
                            trail_a, initial=0.0, cap=1.0,
                        )
                        belief_a.updated_at = now
                        db.add(belief_a)

            db.commit()

        write_log(
            level="INFO",
            module="cognition",
            event="sb_volume_consolidation_completed",
            trace_id=trace_id,
            payload={"merged": merged, "contradicted": contradicted},
        )
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="sb_volume_consolidation_failed",
            trace_id=trace_id,
            payload={"error": str(exc)[:200]},
        )


def maybe_trigger_volume_consolidation(*, user_id: int, trace_id: str = "") -> None:
    """Fire SF and SB consolidation independently when their counts reach threshold.

    SF consolidation fires when active SF candidates for user_id >= 10.
    SB consolidation fires when active SB beliefs >= 10 (global, independent of SF).
    Each runs in its own daemon thread. Never raises.
    """
    try:
        sf_count = _count_active_semantic_facts(user_id)
        if sf_count >= _CONSOLIDATION_VOLUME_TRIGGER:
            threading.Thread(
                target=_run_sf_volume_consolidation,
                kwargs={"user_id": user_id, "trace_id": trace_id},
                daemon=True,
            ).start()
    except Exception:
        pass
    try:
        sb_count = _count_active_self_beliefs()
        if sb_count >= _CONSOLIDATION_VOLUME_TRIGGER:
            threading.Thread(
                target=_run_sb_volume_consolidation,
                kwargs={"trace_id": trace_id},
                daemon=True,
            ).start()
    except Exception:
        pass
