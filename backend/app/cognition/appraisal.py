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
  goal_relevance   : list[GoalRelevance] — per-active-goal relevance_boost [0,1]
                     used by compute_effective_priority in goal_priority.py

On any error, returns AppraisalResult.zero() — never blocks the pipeline.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest
from app.memory.models import MentalState
from app.settings.settings_service import clamp_01
from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"

_APPRAISAL_SYSTEM_BASE = (
    "You are an appraisal module for an AI assistant's internal emotional state.\n"
    "Given the perception of the user's message, the current emotional state, and "
    "optionally a list of active goals, compute emotional delta values, goal updates, "
    "per-goal relevance scores, and goal state transitions.\n\n"
    "Return a JSON object with exactly these fields. No explanation, no markdown — only raw JSON.\n\n"
    "{\n"
    '  "interest_delta": <float in [-0.3, 0.3] — change in interest level>,\n'
    '  "frustration_delta": <float in [-0.3, 0.3] — change in frustration (positive = more frustrated)>,\n'
    '  "trust_evidence": <float in [0.0, 0.05] — evidence of trust from this interaction>,\n'
    '  "goal_updates": <list of goal update objects, or empty []>,\n'
    '  "goal_relevance": <list of goal relevance objects for each active goal, or empty []>,\n'
    '  "goal_state_changes": <list of goal state change objects, or empty []>,\n'
    '  "milestone_updates": <list of milestone update objects, or empty []>\n'
    "}\n\n"
    "Goal update object (only include when a clear goal emerges from the conversation):\n"
    "{\n"
    '  "action": "create",\n'
    '  "description": "<concise goal description>",\n'
    '  "scope": "short_term" | "long_term",\n'
    '  "base_importance": <float 0.0-1.0>,\n'
    '  "is_wellbeing": <true if this goal relates to user mental health/wellbeing, else false>,\n'
    '  "initial_milestones": ["<first sub-step>", ...]  // optional; omit or [] for simple goals\n'
    "}\n\n"
    "Goal relevance object (one per active goal listed in the context):\n"
    "{\n"
    '  "goal_id": <integer goal ID from the ACTIVE GOALS list>,\n'
    '  "relevance": <float 0.0-1.0 — how relevant the current turn is to this goal>\n'
    "}\n\n"
    "Goal state change object (only when a goal is clearly finished or abandoned):\n"
    "{\n"
    '  "goal_id": <integer goal ID from the ACTIVE GOALS list>,\n'
    '  "new_status": "resolved" | "abandoned"\n'
    "}\n\n"
    "Milestone update object — two forms:\n"
    '{"goal_id": <integer>, "action": "add_milestone", "description": "<sub-step description>"}\n'
    '{"milestone_id": <integer milestone ID from the milestones list>, "action": "complete"}\n\n'
    "Guidelines:\n"
    "- interest_delta: positive when the topic is interesting or novel; negative for routine/boring\n"
    "- frustration_delta: positive when the user is confrontational; negative when warm/cooperative\n"
    "- trust_evidence: small positive (≤ 0.05) when the user is cooperative and respectful; 0 otherwise\n"
    "- goal_updates: suggest a goal only when a clear, actionable objective emerges. "
    "Empty list is correct for most turns.\n"
    "- is_wellbeing: mark true ONLY when the goal directly relates to the user's mental health, "
    "emotional support, or personal wellbeing.\n"
    "- initial_milestones: include only when the goal naturally decomposes into concrete sub-steps "
    "already evident from the conversation. Omit or use [] for simple, single-step goals.\n"
    "- goal_relevance: for each active goal, score how much the current turn relates to it. "
    "0 = completely unrelated, 1 = directly and explicitly about this goal. "
    "If no active goals are listed, return empty [].\n"
    "- goal_state_changes: signal 'resolved' ONLY when there is clear evidence the goal was achieved "
    "(e.g. the user says they accomplished it). Signal 'abandoned' ONLY when the user explicitly gives "
    "up or states the goal is no longer relevant. Empty list is correct for the vast majority of turns.\n"
    "- milestone_updates: add milestones when the conversation reveals specific actionable sub-steps. "
    "Complete a milestone when you have clear evidence it was accomplished. "
    "Empty list is correct for most turns.\n"
    "- similar goals: before creating a new goal, check the ACTIVE GOALS list. If a new goal is "
    "semantically similar to an existing one (same domain, similar objective), prefer adding "
    "milestones to the existing goal rather than creating a duplicate. Only create a new goal "
    "when the objective is clearly distinct from all active goals.\n\n"
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
    initial_milestones: list[str] = field(default_factory=list)  # optional initial sub-steps


@dataclass
class GoalRelevance:
    """Per-turn relevance score for an active goal, produced by Appraisal.

    Used by compute_effective_priority() in goal_priority.py to compute the
    adjusted priority for the goal in this turn's context.
    """
    goal_id: int
    relevance: float     # [0, 1] — 0 = unrelated, 1 = directly about this goal


@dataclass
class GoalStateChange:
    """Intent to transition a goal's status, produced by Appraisal.

    Only "resolved" and "abandoned" are valid targets — goals cannot transition
    back to "active" via this mechanism. The DB layer enforces this by ignoring
    state changes for goals that are not currently "active".
    """
    goal_id: int
    new_status: str      # "resolved" | "abandoned"


@dataclass
class MilestoneIntent:
    """Intent to add a new milestone to a goal or complete an existing one.

    action="add_milestone": requires goal_id + description.
    action="complete":      requires milestone_id (from the milestones list in context).

    The DB layer verifies goal/milestone ownership before applying any change.
    """
    action: str                   # "add_milestone" | "complete"
    goal_id: Optional[int] = None          # for add_milestone
    description: Optional[str] = None      # for add_milestone
    milestone_id: Optional[int] = None     # for complete


@dataclass
class AppraisalResult:
    interest_delta: float
    frustration_delta: float
    trust_evidence: float
    goal_updates: list[GoalUpdateIntent] = field(default_factory=list)
    goal_relevance: list[GoalRelevance] = field(default_factory=list)
    goal_state_changes: list[GoalStateChange] = field(default_factory=list)
    milestone_updates: list[MilestoneIntent] = field(default_factory=list)

    @classmethod
    def zero(cls) -> "AppraisalResult":
        return cls(
            interest_delta=0.0,
            frustration_delta=0.0,
            trust_evidence=0.0,
            goal_updates=[],
            goal_relevance=[],
            goal_state_changes=[],
            milestone_updates=[],
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
    raw_milestones = raw.get("initial_milestones")
    initial_milestones: list[str] = []
    if isinstance(raw_milestones, list):
        for item in raw_milestones:
            if isinstance(item, str) and item.strip():
                initial_milestones.append(item.strip())
    return GoalUpdateIntent(
        action=action,
        description=description,
        scope=scope,
        base_importance=base_importance,
        is_wellbeing=bool(raw.get("is_wellbeing", False)),
        initial_milestones=initial_milestones,
    )


def _parse_goal_relevance(raw: Any) -> GoalRelevance | None:
    if not isinstance(raw, dict):
        return None
    try:
        goal_id = int(raw["goal_id"])
        relevance = max(0.0, min(1.0, float(raw.get("relevance", 0.0))))
        return GoalRelevance(goal_id=goal_id, relevance=relevance)
    except (KeyError, TypeError, ValueError):
        return None


def _parse_milestone_intent(raw: Any) -> MilestoneIntent | None:
    if not isinstance(raw, dict):
        return None
    action = str(raw.get("action", "")).strip().lower()
    if action == "add_milestone":
        goal_id_raw = raw.get("goal_id")
        if goal_id_raw is None:
            return None
        description = str(raw.get("description", "")).strip()
        if not description:
            return None
        try:
            return MilestoneIntent(action="add_milestone", goal_id=int(goal_id_raw), description=description)
        except (TypeError, ValueError):
            return None
    elif action == "complete":
        milestone_id_raw = raw.get("milestone_id")
        if milestone_id_raw is None:
            return None
        try:
            return MilestoneIntent(action="complete", milestone_id=int(milestone_id_raw))
        except (TypeError, ValueError):
            return None
    return None


def _parse_goal_state_change(raw: Any) -> GoalStateChange | None:
    if not isinstance(raw, dict):
        return None
    try:
        goal_id = int(raw["goal_id"])
        new_status = str(raw.get("new_status", "")).strip().lower()
        if new_status not in ("resolved", "abandoned"):
            return None
        return GoalStateChange(goal_id=goal_id, new_status=new_status)
    except (KeyError, TypeError, ValueError):
        return None


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
        goal_relevance = [
            gr for gr in (
                _parse_goal_relevance(item)
                for item in (data.get("goal_relevance") or [])
            )
            if gr is not None
        ]
        goal_state_changes = [
            gsc for gsc in (
                _parse_goal_state_change(item)
                for item in (data.get("goal_state_changes") or [])
            )
            if gsc is not None
        ]
        milestone_updates = [
            mi for mi in (
                _parse_milestone_intent(item)
                for item in (data.get("milestone_updates") or [])
            )
            if mi is not None
        ]
        return AppraisalResult(
            interest_delta=_clamp_delta(data.get("interest_delta", 0.0)),
            frustration_delta=_clamp_delta(data.get("frustration_delta", 0.0)),
            trust_evidence=max(0.0, min(0.05, float(data.get("trust_evidence", 0.0)))),
            goal_updates=goal_updates,
            goal_relevance=goal_relevance,
            goal_state_changes=goal_state_changes,
            milestone_updates=milestone_updates,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _build_appraisal_context(
    perception: dict[str, Any],
    mental_state: dict[str, float],
    personality: dict[str, float],
    active_goals: list[dict[str, Any]],
) -> str:
    parts = [
        f"PERCEPTION:\n{json.dumps(perception, ensure_ascii=False)}",
        f"CURRENT MENTAL STATE:\n{json.dumps(mental_state, ensure_ascii=False)}",
        (
            "PERSONALITY (key traits, 0-1 scale):\n"
            f"  curiosity={personality.get('curiosity', 0.5):.2f}, "
            f"warmth={personality.get('warmth', 0.4):.2f}, "
            f"emotional_stability={personality.get('emotional_stability', 0.6):.2f}"
        ),
    ]
    if active_goals:
        goals_repr = json.dumps(active_goals, ensure_ascii=False)
        parts.append(f"ACTIVE GOALS (score relevance for each):\n{goals_repr}")
    else:
        parts.append("ACTIVE GOALS: none — return empty goal_relevance []")
    return "\n\n".join(parts)


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
    active_goals: list[dict[str, Any]] | None = None,
    trace_id: str = "",
) -> AppraisalResult:
    """Run Appraisal on the current turn context.

    active_goals: list of active Goal dicts, each with at least {id, description, scope}.
        Used to compute per-goal relevance_boost scores (goal_relevance in the result).
        Pass None or [] when no active goals exist for this user/session.

    Returns AppraisalResult.zero() on any provider error — never raises.
    """
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    context = _build_appraisal_context(perception, mental_state, personality, active_goals or [])
    try:
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="appraisal",
            system_prompt=_APPRAISAL_SYSTEM_BASE,
            user_message=context,
            max_tokens=300,
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
