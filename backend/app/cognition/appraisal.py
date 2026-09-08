"""Appraisal — Fase 2. Second Haiku call per turn.

DESIGN DECISION — inercia/smoothing for MentalState deltas:
  Deltas are applied directly to MentalState without any additional smoothing
  or inercia multiplier. Rationale: MentalState is an accumulated, persistent
  state updated every turn — it already carries memory through its current values.
  The inercia principle discussed in the architecture document (Section 12/15)
  applies specifically to SocialProfile.trust (relationship-level consolidation),
  where it makes sense: a long-established relationship is not shaken by one bad
  turn. MentalState represents *momentary* emotional state and should respond
  proportionally to events. Small shifts → small deltas; significant events →
  larger deltas. The [0, 1] clamp is the only bound, which is intentional.

Contracts (Section 12):
  interest_delta   : float — change to MentalState.interest
  frustration_delta: float — change to MentalState.frustration
  trust_evidence   : float — positive evidence of trust; fed into SocialProfile
                     via social update, not directly into MentalState
  goal_updates     : list[GoalUpdateIntent] — goal creation intents (applied
                     to DB when integrated in Paso 3)

On any error, returns AppraisalResult.zero() — never blocks the pipeline.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest
from app.memory.models import MentalState
from app.settings.settings_service import clamp_01
from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"

_APPRAISAL_SYSTEM = (
    "You are an appraisal module for an AI assistant's internal emotional state.\n"
    "Given the perception of the user's message and the current emotional state, "
    "compute emotional delta values and suggest any goal updates.\n\n"
    "Return a JSON object with exactly these fields. No explanation, no markdown — only raw JSON.\n\n"
    "{\n"
    '  "interest_delta": <float in [-0.3, 0.3] — change in interest level>,\n'
    '  "frustration_delta": <float in [-0.3, 0.3] — change in frustration (positive = more frustrated)>,\n'
    '  "trust_evidence": <float in [0.0, 0.05] — evidence of trust from this interaction>,\n'
    '  "goal_updates": <list of goal update objects, or empty []>\n'
    "}\n\n"
    "Goal update object (only include when a clear goal emerges from the conversation):\n"
    "{\n"
    '  "action": "create",\n'
    '  "description": "<concise goal description>",\n'
    '  "scope": "short_term" | "long_term",\n'
    '  "base_importance": <float 0.0-1.0>,\n'
    '  "is_wellbeing": <true if this goal relates to user mental health/wellbeing, else false>\n'
    "}\n\n"
    "Guidelines:\n"
    "- interest_delta: positive when the topic is interesting or novel; negative for routine/boring\n"
    "- frustration_delta: positive when the user is confrontational; negative when warm/cooperative\n"
    "- trust_evidence: small positive (≤ 0.05) when the user is cooperative and respectful; 0 otherwise\n"
    "- goal_updates: suggest a goal only when a clear, actionable objective emerges. "
    "Empty list is correct for most turns.\n"
    "- is_wellbeing: mark true ONLY when the goal directly relates to the user's mental health, "
    "emotional support, or personal wellbeing.\n\n"
    "Output only valid JSON. Use 0 for all deltas if the message is neutral or routine."
)


@dataclass
class GoalUpdateIntent:
    """Intent to create a goal, produced by Appraisal. Applied to DB in Paso 3 integration."""
    action: str          # "create"
    description: str
    scope: str           # "short_term" | "long_term"
    base_importance: float
    is_wellbeing: bool = False


@dataclass
class AppraisalResult:
    interest_delta: float
    frustration_delta: float
    trust_evidence: float
    goal_updates: list[GoalUpdateIntent] = field(default_factory=list)

    @classmethod
    def zero(cls) -> "AppraisalResult":
        return cls(
            interest_delta=0.0,
            frustration_delta=0.0,
            trust_evidence=0.0,
            goal_updates=[],
        )


def _clamp_delta(v: float) -> float:
    return max(-0.3, min(0.3, float(v)))


def _parse_goal_update(raw: Any) -> GoalUpdateIntent | None:
    if not isinstance(raw, dict):
        return None
    action = str(raw.get("action", "")).lower()
    if action != "create":
        return None
    description = str(raw.get("description", "")).strip()
    if not description:
        return None
    scope = str(raw.get("scope", "short_term")).lower()
    if scope not in ("short_term", "long_term"):
        scope = "short_term"
    try:
        base_importance = clamp_01(float(raw.get("base_importance", 0.5)))
    except (TypeError, ValueError):
        base_importance = 0.5
    return GoalUpdateIntent(
        action=action,
        description=description,
        scope=scope,
        base_importance=base_importance,
        is_wellbeing=bool(raw.get("is_wellbeing", False)),
    )


def _parse_appraisal(text: str) -> AppraisalResult | None:
    try:
        stripped = text.strip()
        if stripped.startswith("```"):
            parts = stripped.split("```")
            stripped = parts[1] if len(parts) > 1 else stripped
            if stripped.startswith("json"):
                stripped = stripped[4:]
        data = json.loads(stripped)
        goal_updates = [
            gu for gu in (
                _parse_goal_update(item)
                for item in (data.get("goal_updates") or [])
            )
            if gu is not None
        ]
        return AppraisalResult(
            interest_delta=_clamp_delta(data.get("interest_delta", 0.0)),
            frustration_delta=_clamp_delta(data.get("frustration_delta", 0.0)),
            trust_evidence=max(0.0, min(0.05, float(data.get("trust_evidence", 0.0)))),
            goal_updates=goal_updates,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _build_appraisal_context(
    perception: dict[str, Any],
    mental_state: dict[str, float],
    personality: dict[str, float],
) -> str:
    return (
        f"PERCEPTION:\n{json.dumps(perception, ensure_ascii=False)}\n\n"
        f"CURRENT MENTAL STATE:\n{json.dumps(mental_state, ensure_ascii=False)}\n\n"
        "PERSONALITY (key traits, 0-1 scale):\n"
        f"  curiosity={personality.get('curiosity', 0.5):.2f}, "
        f"warmth={personality.get('warmth', 0.4):.2f}, "
        f"emotional_stability={personality.get('emotional_stability', 0.6):.2f}"
    )


def apply_appraisal_to_mental_state(
    state: MentalState,
    result: AppraisalResult,
) -> MentalState:
    """Apply Appraisal deltas to MentalState in-place. Returns the same object.

    Clamps all fields to [0, 1]. Does not commit — caller is responsible.
    trust_evidence is not stored in MentalState; it feeds SocialProfile via
    the social update pipeline. A small social_comfort nudge is applied here
    as a proxy for the relational warmth signal in the current turn.
    """
    state.interest = clamp_01(state.interest + result.interest_delta)
    state.frustration = clamp_01(state.frustration + result.frustration_delta)
    # trust_evidence → small social_comfort nudge (scale 0.5 to avoid over-reaction)
    state.social_comfort = clamp_01(state.social_comfort + result.trust_evidence * 0.5)
    return state


def run_appraisal(
    *,
    perception: dict[str, Any],
    mental_state: dict[str, float],
    personality: dict[str, float],
    trace_id: str = "",
) -> AppraisalResult:
    """Run Appraisal on the current turn context.

    Returns AppraisalResult.zero() on any provider error — never raises.
    """
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    context = _build_appraisal_context(perception, mental_state, personality)
    try:
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="appraisal",
            system_prompt=_APPRAISAL_SYSTEM,
            user_message=context,
            max_tokens=200,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if response.ok and response.text:
            result = _parse_appraisal(response.text)
            if result is not None:
                return result
        write_log(
            level="WARN",
            module="cognition",
            event="appraisal_parse_failed",
            trace_id=trace_id,
            payload={"raw": (response.text or "")[:200]},
        )
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="appraisal_error",
            trace_id=trace_id,
            payload={"error": str(exc)[:200]},
        )
    return AppraisalResult.zero()
