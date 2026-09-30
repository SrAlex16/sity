"""metacognitive_evaluator.py — Punto 7. SelfBelief → decision bias (MINI-REMAKE v2.0).

compute_metacognitive_adjustments asks Haiku whether any active self-beliefs are
relevant to the current turn and, if so, proposes small action-score adjustments.
The code then bounds the proposals using:

    modifier = proposed * max_relevant_conf * MAX_METACOGNITIVE_BIAS * weight
    weight = 1.5  if max_relevant_conf ≥ _HIGH_CONFIDENCE_THRESHOLD  else  1.0

This is Pass 6 in the Decision pipeline, applied after compute_utility_scores()
and before the Decision Haiku call.

Never raises — returns {} on any error or when Haiku says not applicable.
"""
from __future__ import annotations

import json
import os

from app.cognition.perception import PerceptionResult
from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest
from app.memory.models import SelfBelief
from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_METACOGNITIVE_BIAS: float = 0.05
_HIGH_CONFIDENCE_THRESHOLD: float = 0.80
_HIGH_CONFIDENCE_WEIGHT: float = 1.50

_METACOGNITIVE_SYSTEM = (
    "You are the metacognitive module for an AI assistant named Sity. "
    "Given Sity's self-beliefs and the current conversational context, determine "
    "whether any beliefs are applicable and propose small adjustments to action "
    "selection scores. Return ONLY valid JSON — no markdown, no explanation.\n\n"
    '{"applicable": <bool>, "relevant_beliefs": [<belief_id>, ...], '
    '"adjustments": {"<action>": <float -1.0 to 1.0>}, "reason": "<brief>"}\n\n'
    "Valid actions: answer, help, ask, challenge, refuse, set_boundary, use_tool, "
    "wait, initiate, change_topic.\n"
    "Include only actions whose scores should shift. If no beliefs apply, set "
    "applicable=false and return empty adjustments. "
    "These are soft nudges — keep proposed values modest."
)


def compute_metacognitive_adjustments(
    self_beliefs: list[SelfBelief],
    context_type: str,
    perception: PerceptionResult,
    mental_state: dict,
    *,
    trace_id: str = "",
) -> dict[str, float]:
    """Return {action: delta} score adjustments derived from active self-beliefs.

    Returns {} when self_beliefs is empty, Haiku is not applicable, or any error.
    """
    if not self_beliefs:
        return {}

    belief_lines: list[str] = []
    for b in self_beliefs:
        if b.id is None:
            continue
        belief_lines.append(
            f"  [id={b.id}, conf={b.confidence:.2f}] {b.proposition[:150]}"
        )

    if not belief_lines:
        return {}

    context_text = (
        f"CONTEXT_TYPE: {context_type}\n"
        f"USER_INTENT: {perception.user_intent}\n"
        f"TONE: {perception.tone}\n"
        f"CHALLENGE: {perception.challenge:.2f}\n"
        f"FRUSTRATION: {float(mental_state.get('frustration', 0.0)):.2f}\n"
        f"INTEREST: {float(mental_state.get('interest', 0.0)):.2f}\n\n"
        "SELF-BELIEFS (active, confidence ≥ 0.60):\n" + "\n".join(belief_lines)
    )

    try:
        provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="metacognitive_eval",
            system_prompt=_METACOGNITIVE_SYSTEM,
            user_message=context_text,
            max_tokens=120,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if not response.ok or not response.text:
            return {}

        return _apply_metacognitive_bounds(
            response.text, self_beliefs, trace_id=trace_id
        )
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="metacognitive_eval_failed",
            trace_id=trace_id,
            payload={"error": str(exc)[:200]},
        )
        return {}


def _apply_metacognitive_bounds(
    raw_text: str,
    self_beliefs: list[SelfBelief],
    *,
    trace_id: str = "",
) -> dict[str, float]:
    """Parse Haiku response and apply confidence-bounded modifiers.

    Formula per action:  modifier = proposed * max_conf * MAX_METACOGNITIVE_BIAS * weight
    """
    from app.cognition.decision import _VALID_ACTIONS  # local — avoids circular at import time

    try:
        stripped = raw_text.strip()
        if stripped.startswith("```"):
            parts = stripped.split("```")
            stripped = parts[1] if len(parts) > 1 else stripped
            if stripped.startswith("json"):
                stripped = stripped[4:]
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return {}

    if not data.get("applicable", False):
        return {}

    raw_adjustments: dict = data.get("adjustments", {})
    if not raw_adjustments:
        return {}

    relevant_ids: list[int] = []
    for x in data.get("relevant_beliefs", []):
        try:
            relevant_ids.append(int(x))
        except (TypeError, ValueError):
            pass

    belief_map = {b.id: b for b in self_beliefs if b.id is not None}
    relevant_beliefs = [belief_map[bid] for bid in relevant_ids if bid in belief_map]
    if not relevant_beliefs:
        relevant_beliefs = list(self_beliefs)

    max_conf = max((b.confidence for b in relevant_beliefs), default=0.0)
    weight = _HIGH_CONFIDENCE_WEIGHT if max_conf >= _HIGH_CONFIDENCE_THRESHOLD else 1.0

    result: dict[str, float] = {}
    for action, proposed in raw_adjustments.items():
        action_clean = str(action).strip().lower()
        if action_clean not in _VALID_ACTIONS:
            continue
        try:
            proposed_f = float(proposed)
        except (TypeError, ValueError):
            continue
        proposed_f = max(-1.0, min(1.0, proposed_f))
        result[action_clean] = proposed_f * max_conf * MAX_METACOGNITIVE_BIAS * weight

    if result:
        write_log(
            level="INFO",
            module="cognition",
            event="metacognitive_adjustment_applied",
            trace_id=trace_id,
            payload={
                "adjustments": {a: round(v, 4) for a, v in result.items()},
                "max_conf": round(max_conf, 2),
                "weight": weight,
            },
        )

    return result
