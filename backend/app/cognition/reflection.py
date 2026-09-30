"""reflection.py — Structured after-action reflection for salient turns (Fase 6 Paso 3).

Conditional Haiku call (#5 per turn) only when salience_total >= _REFLECTION_SALIENCE_MIN (0.45).

Architecture (sección 56):
  1. Build context from turn data (perception, appraisal, decision, salience).
  2. Haiku answers 11 introspective questions and returns structured JSON.
  3. Save ReflectionLog to DB (full traceability for sección 57).
  4. Extract belief_updates → add_belief_candidate() with source="metacognition", confidence=0.40.
  5. Extract user_belief_updates → add_belief_attribution() with confidence=0.35 (Fase 8).
  6. Extract future_commitments → upsert_expectation() (Punto 5).
  7. Return ReflectionResult or None on any failure.

sección 57 invariant: outputs are NEVER auto-applied as facts. Belief candidates
require explicit promotion by the caller — confidence 0.40 is the metacognition floor.

Never raises — returns None on any error.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import timedelta

from sqlmodel import Session

from app.cognition.appraisal import AppraisalResult
from app.cognition.decision import DecisionResult
from app.cognition.perception import PerceptionResult
from app.cognition.self_model_service import (
    add_belief_candidate,
    add_self_model_observation,
    get_or_create_self_model,
)
from app.cognition.semantic_service import upsert_semantic_candidate
from app.cognition.user_model_service import (
    VALID_EXPECTED_BEHAVIORS,
    add_belief_attribution,
    upsert_expectation,
)
from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest
from app.memory.models import GoalCandidate, Goal, RelationshipEvidence, ReflectionLog, utc_now
from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Equals _THR_MEDIA from episode_service — the same "significant turn" threshold.
# Defined here without import to keep modules decoupled.
_REFLECTION_SALIENCE_MIN: float = 0.45

# Approximate timedeltas for due_at_hint → datetime conversion
_DUE_AT_HINT_MAP: dict[str, timedelta] = {
    "hoy":            timedelta(hours=6),
    "today":          timedelta(hours=6),
    "mañana":         timedelta(hours=24),
    "tomorrow":       timedelta(hours=24),
    "esta semana":    timedelta(days=7),
    "this week":      timedelta(days=7),
    "próxima semana": timedelta(days=14),
    "next week":      timedelta(days=14),
    "pronto":         timedelta(days=3),
    "soon":           timedelta(days=3),
    "este mes":       timedelta(days=30),
    "this month":     timedelta(days=30),
}

# context_type → expected_behavior mapping for event expectations
# Uses the closest behavioral match from VALID_EXPECTED_BEHAVIORS
_COMMITMENT_BEHAVIOR = "plan_together"  # best fit for explicit future commitments


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class ReflectionResult:
    """Parsed output of one Reflection Step.

    String list fields (memory_candidates, relationship_evidence, goal_updates) are
    kept for backwards compatibility with ReflectionLog. The structured counterparts
    (_typed, _structured) carry the downstream-actionable data (Punto 6).
    sección 57: belief_updates are candidates — they require explicit promotion.
    """
    success_estimate: float
    memory_candidates: list[str] = field(default_factory=list)
    belief_updates: list[str] = field(default_factory=list)
    relationship_evidence: list[str] = field(default_factory=list)
    goal_updates: list[str] = field(default_factory=list)
    self_model_updates: list[str] = field(default_factory=list)
    user_belief_updates: list[str] = field(default_factory=list)
    future_commitments: list[dict] = field(default_factory=list)
    # Punto 6 structured fields
    memory_candidates_typed: list[dict] = field(default_factory=list)
    relationship_evidence_structured: list[dict] = field(default_factory=list)
    goal_updates_structured: list[dict] = field(default_factory=list)
    log_id: int | None = None  # set after DB save


# ---------------------------------------------------------------------------
# Haiku system prompt
# ---------------------------------------------------------------------------

_REFLECTION_SYSTEM = (
    "You are Sity's internal reflection module. Analyze the conversational turn "
    "provided and answer 11 introspective questions.\n\n"
    "Return ONLY a JSON object — no markdown, no explanation:\n"
    '{"success_estimate": <float 0-1, how well this turn went>,\n'
    ' "memory_candidates_typed": [<objects — moments worth remembering>],\n'
    ' "belief_updates": [<short sentences about what Sity learned about herself>],\n'
    ' "relationship_evidence_structured": [<objects — observations about this relationship>],\n'
    ' "goal_updates_structured": [<objects — goal-related observations>],\n'
    ' "self_model_updates": [<observations about capabilities, limits, or roles>],\n'
    ' "user_belief_updates": [<what Sity now believes the user believes — Theory of Mind>],\n'
    ' "future_commitments": [<objects — ONLY if user EXPLICITLY stated they will do something>]}\n\n'
    "memory_candidates_typed object format:\n"
    '{"proposition": "<what to remember, max 200 chars>",\n'
    ' "inference_type": "explicit" | "inferred"}\n'
    "  explicit = directly stated; inferred = Sity's interpretation\n\n"
    "relationship_evidence_structured object format:\n"
    '{"dimension": "affinity"|"trust_honesty"|"trust_intentions"|"comfort"|"respect"|"conflict"|"attachment"|"uncertainty",\n'
    ' "direction": "positive" | "negative",\n'
    ' "strength": <float 0-1>,\n'
    ' "reason": "<why, max 120 chars>"}\n\n'
    "goal_updates_structured object format:\n"
    '{"operation": "create" | "update" | "abandon",\n'
    ' "goal_description": "<description, max 200 chars>",\n'
    ' "confidence": <float 0-1>,\n'
    ' "evidence_type": "explicit" | "inferred"}\n\n'
    "future_commitments object format (all fields required):\n"
    '{"proposition": "<what the user committed to, max 200 chars>",\n'
    ' "due_at_hint": "<temporal hint: mañana|hoy|esta semana|pronto|etc., or empty string>",\n'
    ' "importance": <float 0-1, estimated urgency/importance>,\n'
    ' "observability": "direct" | "indirect"}\n\n'
    "IMPORTANT for future_commitments: only EXPLICIT commitments. "
    "IMPORTANT for goal_updates_structured: only if a genuine goal emerged or changed. "
    "All list fields may be empty []. Keep string entries under 120 chars.\n"
    "Internal questions:\n"
    "1. What happened? 2. What did Sity try? 3. Did it work? → success_estimate\n"
    "4. What did Sity learn about herself? → belief_updates\n"
    "5. Did the relationship change? → relationship_evidence_structured\n"
    "6. Belief shift? → belief_updates  7. Worth remembering? → memory_candidates_typed\n"
    "8. New goal surfaced? → goal_updates_structured\n"
    "9. Self-model inconsistency? → self_model_updates\n"
    "10. What does Sity think the user believes? → user_belief_updates\n"
    "11. Explicit future commitment? → future_commitments\n"
    "Output only valid JSON."
)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_reflection_response(text: str) -> ReflectionResult | None:
    """Parse Haiku JSON into ReflectionResult. Returns None on any failure.

    Accepts both old format (memory_candidates: [str], relationship_evidence: [str],
    goal_updates: [str]) and new structured format (Punto 6). New format takes
    precedence when present; falls back to old format for backwards compatibility.
    """
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
        success_estimate = max(0.0, min(1.0, float(data.get("success_estimate", 0.5))))

        def _clean_list(key: str) -> list[str]:
            raw = data.get(key, [])
            if not isinstance(raw, list):
                return []
            return [str(item).strip()[:200] for item in raw if item and str(item).strip()]

        # ── memory_candidates_typed (new) / memory_candidates (legacy) ───────
        raw_mct = data.get("memory_candidates_typed", [])
        memory_candidates_typed: list[dict] = []
        if isinstance(raw_mct, list) and raw_mct:
            for item in raw_mct:
                if not isinstance(item, dict):
                    continue
                prop = str(item.get("proposition", "")).strip()[:200]
                if not prop:
                    continue
                itype = str(item.get("inference_type", "inferred")).strip()
                if itype not in ("explicit", "inferred"):
                    itype = "inferred"
                memory_candidates_typed.append({"proposition": prop, "inference_type": itype})
        memory_candidates = (
            [c["proposition"] for c in memory_candidates_typed]
            if memory_candidates_typed
            else _clean_list("memory_candidates")
        )
        if not memory_candidates_typed and memory_candidates:
            memory_candidates_typed = [
                {"proposition": p, "inference_type": "inferred"} for p in memory_candidates
            ]

        # ── relationship_evidence_structured (new) / relationship_evidence (legacy) ─
        raw_re = data.get("relationship_evidence_structured", [])
        relationship_evidence_structured: list[dict] = []
        _valid_dims = {
            "trust_honesty", "trust_intentions", "trust_competence", "trust_reliability",
            "affinity", "comfort", "respect", "attachment", "conflict", "uncertainty", "familiarity",
        }
        if isinstance(raw_re, list) and raw_re:
            for item in raw_re:
                if not isinstance(item, dict):
                    continue
                dim = str(item.get("dimension", "")).strip()
                if not dim or dim not in _valid_dims:
                    continue
                direction = str(item.get("direction", "positive")).strip()
                if direction not in ("positive", "negative"):
                    direction = "positive"
                try:
                    strength = max(0.0, min(1.0, float(item.get("strength", 0.5))))
                except (TypeError, ValueError):
                    strength = 0.5
                reason = str(item.get("reason", "")).strip()[:200]
                relationship_evidence_structured.append({
                    "dimension": dim, "direction": direction,
                    "strength": strength, "reason": reason,
                })
        relationship_evidence = (
            [f"{e['dimension']}:{e['direction']}:{e['reason']}" for e in relationship_evidence_structured]
            if relationship_evidence_structured
            else _clean_list("relationship_evidence")
        )

        # ── goal_updates_structured (new) / goal_updates (legacy) ────────────
        raw_gu = data.get("goal_updates_structured", [])
        goal_updates_structured: list[dict] = []
        if isinstance(raw_gu, list) and raw_gu:
            for item in raw_gu:
                if not isinstance(item, dict):
                    continue
                desc = str(item.get("goal_description", "")).strip()[:200]
                if not desc:
                    continue
                op = str(item.get("operation", "create")).strip()
                if op not in ("create", "update", "abandon"):
                    op = "create"
                try:
                    conf = max(0.0, min(1.0, float(item.get("confidence", 0.40))))
                except (TypeError, ValueError):
                    conf = 0.40
                etype = str(item.get("evidence_type", "inferred")).strip()
                if etype not in ("explicit", "inferred"):
                    etype = "inferred"
                goal_updates_structured.append({
                    "operation": op, "goal_description": desc,
                    "confidence": conf, "evidence_type": etype,
                })
        goal_updates = (
            [g["goal_description"] for g in goal_updates_structured]
            if goal_updates_structured
            else _clean_list("goal_updates")
        )

        # ── future_commitments ───────────────────────────────────────────────
        raw_fc = data.get("future_commitments", [])
        future_commitments: list[dict] = []
        if isinstance(raw_fc, list):
            for item in raw_fc:
                if not isinstance(item, dict):
                    continue
                prop = str(item.get("proposition", "")).strip()[:200]
                if not prop:
                    continue
                hint = str(item.get("due_at_hint", "")).strip()[:50]
                try:
                    imp = max(0.0, min(1.0, float(item.get("importance", 0.5))))
                except (TypeError, ValueError):
                    imp = 0.5
                obs = str(item.get("observability", "direct")).strip()
                if obs not in ("direct", "indirect", "unobservable"):
                    obs = "direct"
                future_commitments.append({
                    "proposition": prop, "due_at_hint": hint,
                    "importance": imp, "observability": obs,
                })

        return ReflectionResult(
            success_estimate=success_estimate,
            memory_candidates=memory_candidates,
            belief_updates=_clean_list("belief_updates"),
            relationship_evidence=relationship_evidence,
            goal_updates=goal_updates,
            self_model_updates=_clean_list("self_model_updates"),
            user_belief_updates=_clean_list("user_belief_updates"),
            future_commitments=future_commitments,
            memory_candidates_typed=memory_candidates_typed,
            relationship_evidence_structured=relationship_evidence_structured,
            goal_updates_structured=goal_updates_structured,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Haiku call
# ---------------------------------------------------------------------------

def _build_reflection_context(
    user_message: str,
    perception: PerceptionResult,
    appraisal: AppraisalResult,
    action: str,
    salience_total: float,
    semantic_facts: list | None = None,
) -> str:
    ctx = (
        f"USER MESSAGE: {user_message[:200]}\n\n"
        f"PERCEPTION: intent={perception.user_intent}, tone={perception.tone}, "
        f"challenge={perception.challenge:.2f}, novelty={perception.novelty:.2f}\n"
        f"APPRAISAL: interest_delta={appraisal.interest_delta:+.2f}, "
        f"frustration_delta={appraisal.frustration_delta:+.2f}\n"
        f"ACTION TAKEN: {action}\n"
        f"SALIENCE: {salience_total:.2f}"
    )
    if semantic_facts:
        top = sorted(semantic_facts, key=lambda f: f.confidence, reverse=True)[:5]
        facts_lines = "\n".join(f"- {f.proposition}" for f in top)
        ctx += f"\n\nKNOWN USER FACTS (high-confidence):\n{facts_lines}"
    return ctx


def _call_reflection_haiku(context: str, *, trace_id: str) -> ReflectionResult | None:
    """Haiku call #5: structured reflection. Returns ReflectionResult or None on failure."""
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    try:
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="reflection",
            system_prompt=_REFLECTION_SYSTEM,
            user_message=context,
            max_tokens=600,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if response.ok and response.text:
            result = _parse_reflection_response(response.text)
            if result is not None:
                return result
        write_log(
            level="WARN",
            module="cognition",
            event="reflection_haiku_parse_failed",
            trace_id=trace_id,
            payload={"raw": (response.text or "")[:200]},
        )
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="reflection_haiku_error",
            trace_id=trace_id,
            payload={"error": str(exc)[:200]},
        )
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_reflection(
    session: Session,
    *,
    user_id: int,
    user_message: str,
    perception: PerceptionResult,
    appraisal: AppraisalResult,
    decision: DecisionResult | None,
    salience_total: float,
    trace_id: str = "",
    semantic_facts: list | None = None,
) -> ReflectionResult | None:
    """Run the Reflection Step for one salient turn.

    Returns ReflectionResult with log_id set, or None if:
      - Haiku call fails (technical error or parse failure)
    None → caller logs and skips belief extraction.

    Belief candidates created here have confidence=0.40, source="metacognition".
    They are NEVER auto-applied as facts (sección 57).
    """
    action = decision.action if decision is not None else "unknown"
    context = _build_reflection_context(
        user_message, perception, appraisal, action, salience_total,
        semantic_facts=semantic_facts,
    )

    result = _call_reflection_haiku(context, trace_id=trace_id)
    if result is None:
        write_log(
            level="WARN",
            module="cognition",
            event="reflection_haiku_failed",
            trace_id=trace_id,
            payload={"user_id": user_id, "salience_total": round(salience_total, 3)},
        )
        return None

    # Persist the full reflection output for traceability (sección 57)
    log_row = ReflectionLog(
        user_id=user_id,
        trace_id=trace_id,
        salience_total=salience_total,
        success_estimate=result.success_estimate,
        memory_candidates_json=json.dumps(result.memory_candidates, ensure_ascii=False),
        belief_updates_json=json.dumps(result.belief_updates, ensure_ascii=False),
        relationship_evidence_json=json.dumps(result.relationship_evidence, ensure_ascii=False),
        goal_updates_json=json.dumps(result.goal_updates, ensure_ascii=False),
        self_model_updates_json=json.dumps(result.self_model_updates, ensure_ascii=False),
        user_belief_updates_json=json.dumps(result.user_belief_updates, ensure_ascii=False),
    )
    session.add(log_row)
    session.commit()
    session.refresh(log_row)
    result.log_id = log_row.id

    # Extract belief candidates (sección 57: never auto-facts, always candidates)
    if result.belief_updates:
        sm = get_or_create_self_model(session)
        if sm.id is not None:
            for proposition in result.belief_updates:
                if proposition.strip():
                    add_belief_candidate(
                        session,
                        self_model_id=sm.id,
                        proposition=proposition.strip(),
                        confidence=0.40,
                        source="metacognition",
                        trace_id=trace_id,
                        evidence_type="reflection",
                        evidence_description=f"salience={salience_total:.2f}",
                    )

    # Extract user belief attribution candidates (Fase 8 — Theory of Mind)
    # confidence=0.35: more conservative than self-belief (0.40) — sección 57 stricter for ToM
    if result.user_belief_updates:
        for proposition in result.user_belief_updates:
            if proposition.strip():
                add_belief_attribution(
                    session,
                    user_id=user_id,
                    proposition=proposition.strip(),
                    confidence=0.35,
                    source="reflection",
                    context_type=perception.context_type,
                    trace_id=trace_id,
                )

    # Punto 6 — Part 1: memory_candidates_typed → SemanticFact candidates
    _mem_created = 0
    for mc in result.memory_candidates_typed:
        prop = mc.get("proposition", "").strip()
        itype = mc.get("inference_type", "inferred")
        if not prop:
            continue
        conf = 0.35 if itype == "inferred" else 0.45
        try:
            upsert_semantic_candidate(
                session,
                user_id=user_id,
                proposition=prop,
                inference_type=itype,
                confidence=conf,
                trace_id=trace_id,
            )
            _mem_created += 1
        except Exception:
            pass

    # Punto 6 — Part 2: relationship_evidence_structured → RelationshipEvidence rows
    _re_created = 0
    for ev in result.relationship_evidence_structured:
        try:
            re_row = RelationshipEvidence(
                user_id=user_id,
                dimension=ev["dimension"],
                direction=ev["direction"],
                strength=ev["strength"],
                reason=ev.get("reason", ""),
                turn_id=trace_id,
                source="reflection",
            )
            session.add(re_row)
            _re_created += 1
        except Exception:
            pass
    if _re_created:
        session.commit()

    # Punto 6 — Part 3: goal_updates_structured → GoalCandidate or direct Goal
    _gc_created = 0
    for gu in result.goal_updates_structured:
        desc = gu.get("goal_description", "").strip()
        if not desc:
            continue
        conf = gu.get("confidence", 0.40)
        etype = gu.get("evidence_type", "inferred")
        op = gu.get("operation", "create")
        try:
            if etype == "explicit" and conf >= 0.70 and op == "create":
                # Direct Goal creation
                goal = Goal(
                    user_id=user_id,
                    scope="short_term",
                    description=desc,
                    origin="autonomous",
                    base_importance=min(1.0, conf),
                    status="active",
                )
                session.add(goal)
                session.commit()
            else:
                # GoalCandidate — inferred or low-confidence
                if etype == "inferred":
                    conf = max(0.35, min(0.45, conf))
                gc = GoalCandidate(
                    user_id=user_id,
                    operation=op,
                    goal_description=desc,
                    confidence=conf,
                    source_turn_id=trace_id,
                    evidence_type=etype,
                )
                session.add(gc)
            _gc_created += 1
        except Exception:
            pass
    if _gc_created:
        session.commit()

    # Punto 6 — Part 4: self_model_updates → SelfBelief (lower confidence)
    _sm_created = 0
    for obs in result.self_model_updates:
        if obs.strip():
            try:
                add_self_model_observation(session, obs.strip(), trace_id=trace_id)
                _sm_created += 1
            except Exception:
                pass

    # Extract future commitments → create Expectations (Punto 5)
    _commitments_created = 0
    if result.future_commitments:
        _now = utc_now()
        for fc in result.future_commitments:
            hint = fc.get("due_at_hint", "").lower().strip()
            delta = _DUE_AT_HINT_MAP.get(hint)
            due_at = (_now + delta) if delta is not None else None
            exp = upsert_expectation(
                session,
                user_id=user_id,
                context_type=perception.context_type,
                expected_behavior=_COMMITMENT_BEHAVIOR,
                probability=min(1.0, fc.get("importance", 0.5) * 0.8 + 0.3),
                trace_id=trace_id,
                expectation_type="event",
                source="reflection",
                due_at=due_at,
                importance=fc.get("importance", 0.5),
                observability=fc.get("observability", "direct"),
                proposition=fc.get("proposition", ""),
            )
            if exp is not None:
                _commitments_created += 1

    write_log(
        level="INFO",
        module="cognition",
        event="reflection_completed",
        trace_id=trace_id,
        payload={
            "user_id": user_id,
            "salience_total": round(salience_total, 3),
            "success_estimate": round(result.success_estimate, 3),
            "belief_updates_count": len(result.belief_updates),
            "user_belief_updates_count": len(result.user_belief_updates),
            "future_commitments_created": _commitments_created,
            "memory_candidates_created": _mem_created,
            "relationship_evidence_created": _re_created,
            "goal_candidates_created": _gc_created,
            "self_model_observations_created": _sm_created,
            "log_id": log_row.id,
        },
    )
    return result
