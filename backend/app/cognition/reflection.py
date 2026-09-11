"""reflection.py — Structured after-action reflection for salient turns (Fase 6 Paso 3).

Conditional Haiku call (#5 per turn) only when salience_total >= _REFLECTION_SALIENCE_MIN (0.45).

Architecture (sección 56):
  1. Build context from turn data (perception, appraisal, decision, salience).
  2. Haiku answers 9 introspective questions and returns structured JSON.
  3. Save ReflectionLog to DB (full traceability for sección 57).
  4. Extract belief_updates → add_belief_candidate() with source="metacognition", confidence=0.40.
  5. Return ReflectionResult or None on any failure.

sección 57 invariant: outputs are NEVER auto-applied as facts. Belief candidates
require explicit promotion by the caller — confidence 0.40 is the metacognition floor.

Never raises — returns None on any error.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from sqlmodel import Session

from app.cognition.appraisal import AppraisalResult
from app.cognition.decision import DecisionResult
from app.cognition.perception import PerceptionResult
from app.cognition.self_model_service import add_belief_candidate, get_or_create_self_model
from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest
from app.memory.models import ReflectionLog
from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Equals _THR_MEDIA from episode_service — the same "significant turn" threshold.
# Defined here without import to keep modules decoupled.
_REFLECTION_SALIENCE_MIN: float = 0.45


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class ReflectionResult:
    """Parsed output of one Reflection Step.

    All list fields are observations (strings), never commands.
    sección 57: belief_updates are candidates — they require explicit promotion.
    """
    success_estimate: float
    memory_candidates: list[str] = field(default_factory=list)
    belief_updates: list[str] = field(default_factory=list)
    relationship_evidence: list[str] = field(default_factory=list)
    goal_updates: list[str] = field(default_factory=list)
    self_model_updates: list[str] = field(default_factory=list)
    log_id: int | None = None  # set after DB save


# ---------------------------------------------------------------------------
# Haiku system prompt
# ---------------------------------------------------------------------------

_REFLECTION_SYSTEM = (
    "You are Sity's internal reflection module. Analyze the conversational turn "
    "provided and answer 9 introspective questions.\n\n"
    "Return ONLY a JSON object — no markdown, no explanation:\n"
    '{"success_estimate": <float 0-1, how well this turn went>,\n'
    ' "memory_candidates": [<moments worth remembering, may be empty>],\n'
    ' "belief_updates": [<short sentences about what Sity learned about herself>],\n'
    ' "relationship_evidence": [<observations about this relationship>],\n'
    ' "goal_updates": [<goal-related observations>],\n'
    ' "self_model_updates": [<observations about capabilities, limits, or roles>]}\n\n'
    "Internal questions to answer:\n"
    "1. What happened this turn?\n"
    "2. What did Sity try to do?\n"
    "3. Did it work? → success_estimate\n"
    "4. What did Sity learn about herself? → belief_updates\n"
    "5. Did the relationship with this person change? → relationship_evidence\n"
    "6. Did any belief shift? → belief_updates\n"
    "7. Is anything worth remembering? → memory_candidates\n"
    "8. Did a new goal surface? → goal_updates\n"
    "9. Was anything inconsistent with Sity's self-model? → self_model_updates\n\n"
    "Keep each entry under 120 characters. All list fields may be empty [].\n"
    "Output only valid JSON."
)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_reflection_response(text: str) -> ReflectionResult | None:
    """Parse Haiku JSON into ReflectionResult. Returns None on any failure."""
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

        return ReflectionResult(
            success_estimate=success_estimate,
            memory_candidates=_clean_list("memory_candidates"),
            belief_updates=_clean_list("belief_updates"),
            relationship_evidence=_clean_list("relationship_evidence"),
            goal_updates=_clean_list("goal_updates"),
            self_model_updates=_clean_list("self_model_updates"),
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
) -> str:
    return (
        f"USER MESSAGE: {user_message[:200]}\n\n"
        f"PERCEPTION: intent={perception.user_intent}, tone={perception.tone}, "
        f"challenge={perception.challenge:.2f}, novelty={perception.novelty:.2f}\n"
        f"APPRAISAL: interest_delta={appraisal.interest_delta:+.2f}, "
        f"frustration_delta={appraisal.frustration_delta:+.2f}\n"
        f"ACTION TAKEN: {action}\n"
        f"SALIENCE: {salience_total:.2f}"
    )


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
            max_tokens=300,
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
        user_message, perception, appraisal, action, salience_total
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
            "log_id": log_row.id,
        },
    )
    return result
