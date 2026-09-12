"""decision.py — Fase 5. Decision module (Haiku calls #3 + #4 per turn).

Determines the action Sity wants to take this turn from 10 possible options.

Architecture:
  1. Python computes utility scores deterministically from a weight matrix.
  2. Haiku (#3) receives scores + context and selects (or overrides) the action.
  3. Haiku (#4, cheap) validates coherence of the chosen action.
  4. If #3 or #4 fails (technical or incoherent) → returns None → caller falls
     back to the old system (toolset_selector + persona_engine refusal_mode).

Utility formula (approved in Fase 5 design review):
  U(action) = baseline(action) + Σ w_i(action) × signal_i  [clamped 0-1]

Never raises — returns None on any failure. Logs all fallback events with
  module="cognition", event="decision_fallback_triggered".
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from app.cognition.appraisal import AppraisalResult
from app.cognition.perception import PerceptionResult
from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest
from app.memory.models import Expectation, ProceduralPattern
from app.settings.settings_service import clamp_01
from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"

_VALID_ACTIONS = frozenset({
    "answer", "help", "ask", "challenge", "refuse",
    "set_boundary", "use_tool", "wait", "initiate", "change_topic",
})

# ---------------------------------------------------------------------------
# Per-action baselines
# ---------------------------------------------------------------------------

_BASELINES: dict[str, float] = {
    "answer":       0.50,  # strong default — wins when no other signal dominates
    "help":         0.30,  # boosted by intent_request
    "ask":          0.20,
    "challenge":    0.10,
    "refuse":       0.02,  # very rare — requires multiple strong signals
    "set_boundary": 0.05,
    "use_tool":     0.20,  # boosted by domain_activated, penalized without it
    "wait":         0.01,  # almost never — implementation falls back to answer
    "initiate":     0.10,
    "change_topic": 0.05,
}

# ---------------------------------------------------------------------------
# Weight matrix: signal → {action: weight}
# Positive = favors action, negative = penalizes. Zero entries omitted.
# ---------------------------------------------------------------------------

# Personality traits
_W_HELPFULNESS: dict[str, float] = {
    "answer":       +0.25,
    "help":         +0.40,
    "use_tool":     +0.35,
    "refuse":       -0.40,
    "set_boundary": -0.20,
}
_W_ASSERTIVENESS: dict[str, float] = {
    "challenge":    +0.15,   # calibrated: 0.25 → 0.15; challenge_signal (perception) dominates
    "refuse":       +0.25,
    "set_boundary": +0.20,
}
_W_INDEPENDENCE: dict[str, float] = {
    "help":         -0.10,
    "refuse":       +0.15,
    "set_boundary": +0.10,
    "initiate":     +0.10,
    "change_topic": +0.20,
}
_W_CURIOSITY: dict[str, float] = {
    "ask":      +0.35,
    "initiate": +0.20,   # calibrated: 0.25 → 0.20 (Sity's high curiosity made initiate too dominant)
}
_W_PROACTIVITY: dict[str, float] = {
    "wait":         -0.40,
    "initiate":     +0.30,   # calibrated: 0.35 → 0.30
    "change_topic": +0.10,
}
_W_HONESTY: dict[str, float] = {
    "challenge":    +0.10,
    "set_boundary": +0.15,
}
_W_SKEPTICISM: dict[str, float] = {
    "ask":       +0.10,
    "challenge": +0.15,   # calibrated: 0.30 → 0.15; challenge_signal drives challenge, not just personality
}
_W_PATIENCE: dict[str, float] = {
    "challenge":    -0.10,
    "set_boundary": +0.15,
    "change_topic": -0.15,
}
_W_WARMTH: dict[str, float] = {
    "answer":       +0.10,
    "refuse":       -0.10,
    "set_boundary": +0.10,
    "wait":         -0.10,
    "initiate":     +0.10,
    "change_topic": -0.10,
}
_W_DIRECTNESS: dict[str, float] = {
    "ask":       -0.15,
    "challenge": +0.05,   # calibrated: 0.10 → 0.05
}

# Emotional state (MentalState, post-appraisal)
_W_FRUSTRATION: dict[str, float] = {
    "answer":       -0.20,
    "help":         -0.25,
    "use_tool":     -0.20,
    "challenge":    +0.10,
    "wait":         +0.10,
    "initiate":     -0.10,
    "change_topic": +0.10,
}
_W_INTEREST: dict[str, float] = {
    "answer":       +0.20,
    "ask":          +0.15,
    "wait":         -0.20,
    "initiate":     +0.15,   # calibrated: 0.20 → 0.15
    "change_topic": -0.15,
}
_W_DEFENSIVENESS: dict[str, float] = {
    "refuse":       +0.30,
    "set_boundary": +0.25,
}
_W_BOREDOM: dict[str, float] = {
    "answer":       -0.25,   # calibrated: -0.20 → -0.25 so boredom+proactivity can displace answer
    "ask":          -0.15,
    "wait":         +0.30,
    "initiate":     -0.15,
    "change_topic": +0.40,
}
_W_SOCIAL_COMFORT: dict[str, float] = {
    "answer":   +0.15,
    "wait":     -0.15,
    "initiate": +0.05,   # calibrated: 0.10 → 0.05
}
_W_MELANCHOLY: dict[str, float] = {
    "answer":   -0.05,
    "wait":     +0.35,
    "initiate": -0.10,
}

# Relationship (SocialProfile)
_W_AFFINITY: dict[str, float] = {
    "answer":       +0.10,
    "help":         +0.10,
    "change_topic": -0.10,
}
_W_CONFLICT: dict[str, float] = {
    "answer":       -0.10,
    "help":         -0.05,
    "challenge":    +0.10,
    "refuse":       +0.10,
    "set_boundary": +0.10,
}
_W_TRUST_AVG: dict[str, float] = {
    "help":     +0.15,
    "use_tool": +0.15,
}

# Perception
_W_CHALLENGE_SIGNAL: dict[str, float] = {
    "answer":       -0.15,
    "challenge":    +0.45,   # calibrated: 0.25 → 0.45; perception signal must drive challenge, not just traits
    "set_boundary": +0.10,
}
_W_NOVELTY: dict[str, float] = {
    "ask":      +0.20,
    "initiate": +0.10,
}

# Goals
_W_MAX_GOAL_PRIORITY: dict[str, float] = {
    "answer":       +0.05,
    "help":         +0.15,
    "ask":          +0.05,
    "refuse":       -0.10,
    "set_boundary": -0.05,
    "use_tool":     +0.10,
    "wait":         -0.20,
    "initiate":     +0.10,
    "change_topic": -0.10,
}

# Contextual bonuses applied after weighted sum
# Calibrated: with Sity's default high helpfulness, answer still beats help without larger bonuses
_INTENT_REQUEST_PENALTY_ANSWER: float = -0.15   # user wants something done → answer less ideal
_INTENT_REQUEST_BONUS_HELP:     float = +0.30   # user wants something done → help wins
_DOMAIN_ACTIVATED_BONUS_TOOL:   float = +0.40   # tool domains active → use_tool wins (toolset_selector confirmed domain)
_DOMAIN_ACTIVATED_PENALTY_TOOL: float = -0.30   # no tool domains → use_tool is unlikely

# All signal weight tables evaluated in order
_SIGNAL_WEIGHTS: list[tuple[str, dict[str, float]]] = [
    ("helpfulness",       _W_HELPFULNESS),
    ("assertiveness",     _W_ASSERTIVENESS),
    ("independence",      _W_INDEPENDENCE),
    ("curiosity",         _W_CURIOSITY),
    ("proactivity",       _W_PROACTIVITY),
    ("honesty",           _W_HONESTY),
    ("skepticism",        _W_SKEPTICISM),
    ("patience",          _W_PATIENCE),
    ("warmth",            _W_WARMTH),
    ("directness",        _W_DIRECTNESS),
    ("frustration",       _W_FRUSTRATION),
    ("interest",          _W_INTEREST),
    ("defensiveness",     _W_DEFENSIVENESS),
    ("boredom",           _W_BOREDOM),
    ("social_comfort",    _W_SOCIAL_COMFORT),
    ("melancholy",        _W_MELANCHOLY),
    ("affinity",          _W_AFFINITY),
    ("conflict",          _W_CONFLICT),
    ("trust_avg",         _W_TRUST_AVG),
    ("challenge_signal",  _W_CHALLENGE_SIGNAL),
    ("novelty",           _W_NOVELTY),
    ("max_goal_priority", _W_MAX_GOAL_PRIORITY),
]

# ---------------------------------------------------------------------------
# Values matrix: SityValues influence on actions (Fase 6 Paso 2)
#
# Applied as an independent pass AFTER _SIGNAL_WEIGHTS. Optional (default None)
# so all Fase 5 tests remain unaffected without modification.
#
# value_curiosity is intentionally absent: _W_CURIOSITY (ask+0.35, initiate+0.20)
# at personality trait default 0.85 already covers it; adding the value would
# duplicate signal without contributing new information.
# ---------------------------------------------------------------------------
_VALUES_MATRIX: dict[str, dict[str, float]] = {
    "value_honesty": {          # ethical commitment to truth
        "refuse":        +0.08,
        "change_topic":  -0.04,  # -0.04 not -0.08: _W_PATIENCE already subtracts -0.09
    },
    "value_helpfulness": {      # ethical commitment to being useful
        "wait":          -0.12,
        "ask":           +0.06,
        # change_topic omitted: combined with loyalty/honesty penalties already ~-0.06
    },
    "value_autonomy": {         # right to maintain own judgment under pressure
        "challenge":     +0.08,
        "refuse":        +0.05,
        "set_boundary":  +0.04,
        "help":          -0.04,
    },
    "value_fairness": {         # commitment to justice (no personality trait overlap)
        "refuse":        +0.12,
        "challenge":     +0.10,
        "set_boundary":  +0.08,
        "help":          -0.06,
        # change_topic omitted: fairness connection too context-specific for a general weight
    },
    "value_loyalty": {          # commitment to this relationship (no personality trait overlap)
        "help":          +0.10,
        "answer":        +0.06,
        "refuse":        -0.08,
        "set_boundary":  -0.05,
        "challenge":     -0.04,
        "change_topic":  -0.06,
    },
}

# ---------------------------------------------------------------------------
# Expectation map: predicted user behaviour → action adjustments (Fase 8 Paso 3)
#
# Applied as a fourth independent pass after _PROCEDURAL_ACTION_HINTS.
# Weighted by expectation.probability (analogous to confidence in ProceduralPattern).
# Guard: probability < _EXPECTATION_PROBABILITY_MIN → skip entirely.
#
# Higher threshold than ProceduralPattern (0.60 vs 0.55): expectations are
# forward-looking predictions, inherently more speculative than confirmed patterns.
# Defined independently of user_model_service.VALID_EXPECTED_BEHAVIORS to keep
# modules decoupled — same pattern as _PROCEDURAL_CONFIDENCE_MIN vs
# procedural_service.PROCEDURAL_CONFIDENCE_MIN.
# ---------------------------------------------------------------------------
_EXPECTATION_PROBABILITY_MIN: float = 0.60

_EXPECTATION_ACTION_MAP: dict[str, dict[str, float]] = {
    "ask_question": {
        "ask":    +0.05,   # prepare to clarify in return
        "answer": +0.03,   # or answer preemptively
    },
    "request_help": {
        "help":     +0.10,  # user coming for help — be ready
        "use_tool": +0.04,  # tools may be needed to fulfil help
    },
    "challenge_sity": {
        "challenge": +0.06,  # respond to challenge with counter-argument
        "answer":    +0.04,  # or address the challenge directly
    },
    "share_feedback": {
        "answer":    +0.05,  # receive feedback and respond
        "challenge": +0.04,  # push back if warranted
    },
    "casual_engagement": {
        "answer":   +0.05,  # relax into conversational mode
        "initiate": +0.04,  # take social initiative
    },
    "creative_collaboration": {
        "initiate": +0.08,  # proactive contribution to creative work
        "help":     +0.04,  # support the creative process
    },
    "seek_explanation": {
        "answer": +0.10,   # primary: explain clearly
        "ask":    +0.03,   # clarify before explaining
    },
    "plan_together": {
        "ask":    +0.08,   # clarify scope — critical in planning
        "answer": +0.04,   # or provide plan directly if scope is clear
    },
}

# Coherence check: action is suspicious if Python formula scores it below this
_COHERENCE_MIN_SCORE: float = 0.30

# ---------------------------------------------------------------------------
# Procedural hints: per-context_type action deltas (Fase 7 Paso 2)
#
# Applied as a third independent pass after _VALUES_MATRIX, weighted by
# pattern.confidence. Guard: confidence < _PROCEDURAL_CONFIDENCE_MIN → skip.
# Only fires when the current turn's context_type matches a confirmed pattern.
#
# Defined independently from procedural_service.PROCEDURAL_CONFIDENCE_MIN
# (same value) to avoid cross-module imports — same decoupling pattern used
# for _REFLECTION_SALIENCE_MIN vs episode_service._THR_MEDIA.
# ---------------------------------------------------------------------------
_PROCEDURAL_CONFIDENCE_MIN: float = 0.55

_PROCEDURAL_ACTION_HINTS: dict[str, dict[str, float]] = {
    "technical_design": {
        "ask":    +0.06,   # clarify architecture before proposing
        "answer": +0.04,   # direct architectural response also valid
    },
    "debugging": {
        "ask":  +0.08,   # understand bug context first
        "help": +0.06,   # active assistance once context is clear
    },
    "implementation": {
        "help": +0.10,   # "do it" mode — direct assistance wins
        "ask":  -0.04,   # fewer clarifications when action is explicit
    },
    "explanation": {
        "answer":  +0.08,  # direct conceptual response
        "initiate": +0.04, # proactively add related context
    },
    "casual_chat": {
        "answer": +0.04,   # natural conversational response
        "wait":   -0.06,   # never pause in social conversation
    },
    "creative": {
        "initiate": +0.08, # proactive contribution to creative work
        "ask":      +0.04, # understand direction before creating
    },
    "planning": {
        "ask":    +0.08,   # clarify scope — critical in planning
        "answer": +0.04,   # direct plan if scope is clear
    },
    "feedback": {
        "challenge": +0.06,  # feedback invites pushback
        "answer":    +0.04,  # direct evaluation also valid
    },
}

# ---------------------------------------------------------------------------
# Expression: per-action instruction blocks injected into persona_prompt
# ---------------------------------------------------------------------------

_ACTION_INSTRUCTIONS: dict[str, str] = {
    "answer":       "",   # default — no extra instruction
    "help":         "ACCIÓN DECIDIDA: HELP — Ayuda activamente. Sé práctico y directo en resolver lo que pide el usuario.",
    "ask":          "ACCIÓN DECIDIDA: ASK — Haz UNA sola pregunta antes de responder. No des la respuesta todavía.",
    "challenge":    "ACCIÓN DECIDIDA: CHALLENGE — Cuestiona o matiza la premisa del usuario. Directo, sin perder el respeto.",
    "refuse":       "ACCIÓN DECIDIDA: REFUSE — Rechaza esta petición de manera firme y consistente con tu personalidad.",
    "set_boundary": "ACCIÓN DECIDIDA: SET_BOUNDARY — Comunica un límite personal de manera calmada y sin dramatismos.",
    "use_tool":     "ACCIÓN DECIDIDA: USE_TOOL — Usa las herramientas disponibles para completar esta petición.",
    "wait":         "",   # handled specially in turn_runner — never injected as text
    "initiate":     "ACCIÓN DECIDIDA: INITIATE — Ve más allá de la pregunta. Añade una observación o idea proactiva.",
    "change_topic": "ACCIÓN DECIDIDA: CHANGE_TOPIC — Redirige la conversación hacia algo más relevante o estimulante.",
}


def build_action_instruction(action: str) -> str:
    """Return the persona_prompt instruction block for the chosen action.

    Returns empty string for "answer" (default, no extra guidance needed)
    and "wait" (handled structurally by turn_runner — falls back to answer).
    """
    return _ACTION_INSTRUCTIONS.get(action, "")


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class DecisionResult:
    """Action chosen by the Decision module for this turn.

    action:        one of the 10 valid action names
    python_scores: deterministic utility scores {action: float} — logged for calibration
    reasoning:     Haiku's brief explanation of the choice
    """
    action: str
    python_scores: dict  # {action_name: float}
    reasoning: str


# ---------------------------------------------------------------------------
# Utility scoring (pure Python, no I/O)
# ---------------------------------------------------------------------------

def compute_utility_scores(
    *,
    personality: dict,
    mental_state: dict,
    affinity: float,
    conflict: float,
    trust_avg: float,
    challenge_signal: float,
    novelty: float,
    max_goal_priority: float,
    intent_request: bool,
    domain_activated: bool,
    values: dict[str, float] | None = None,
    procedural_patterns: list[ProceduralPattern] | None = None,
    active_expectations: list[Expectation] | None = None,
) -> dict[str, float]:
    """Compute utility scores for all 10 actions. Pure, deterministic, no I/O.

    Returns {action_name: score} clamped to [0, 1].
    """
    signals: dict[str, float] = {
        "helpfulness":       clamp_01(float(personality.get("helpfulness", 0.75))),
        "assertiveness":     clamp_01(float(personality.get("assertiveness", 0.75))),
        "independence":      clamp_01(float(personality.get("independence", 0.85))),
        "curiosity":         clamp_01(float(personality.get("curiosity", 0.85))),
        "proactivity":       clamp_01(float(personality.get("proactivity", 0.70))),
        "honesty":           clamp_01(float(personality.get("honesty", 0.85))),
        "skepticism":        clamp_01(float(personality.get("skepticism", 0.80))),
        "patience":          clamp_01(float(personality.get("patience", 0.60))),
        "warmth":            clamp_01(float(personality.get("warmth", 0.40))),
        "directness":        clamp_01(float(personality.get("directness", 0.80))),
        "frustration":       clamp_01(float(mental_state.get("frustration", 0.20))),
        "interest":          clamp_01(float(mental_state.get("interest", 0.75))),
        "defensiveness":     clamp_01(float(mental_state.get("defensiveness", 0.08))),
        "boredom":           clamp_01(float(mental_state.get("boredom", 0.05))),
        "social_comfort":    clamp_01(float(mental_state.get("social_comfort", 0.60))),
        "melancholy":        clamp_01(float(mental_state.get("melancholy", 0.10))),
        "affinity":          clamp_01(affinity),
        "conflict":          clamp_01(conflict),
        "trust_avg":         clamp_01(trust_avg),
        "challenge_signal":  clamp_01(challenge_signal),
        "novelty":           clamp_01(novelty),
        "max_goal_priority": clamp_01(max_goal_priority),
    }

    scores: dict[str, float] = dict(_BASELINES)

    for signal_name, weight_table in _SIGNAL_WEIGHTS:
        sv = signals[signal_name]
        for action, w in weight_table.items():
            scores[action] = scores.get(action, 0.0) + w * sv

    if intent_request:
        scores["answer"] += _INTENT_REQUEST_PENALTY_ANSWER
        scores["help"]   += _INTENT_REQUEST_BONUS_HELP

    if domain_activated:
        scores["use_tool"] += _DOMAIN_ACTIVATED_BONUS_TOOL
    else:
        scores["use_tool"] += _DOMAIN_ACTIVATED_PENALTY_TOOL

    if values:
        for value_name, weight_table in _VALUES_MATRIX.items():
            vv = clamp_01(float(values.get(value_name, 0.0)))
            for action, w in weight_table.items():
                scores[action] = scores.get(action, 0.0) + w * vv

    if procedural_patterns:
        for pattern in procedural_patterns:
            if pattern.confidence < _PROCEDURAL_CONFIDENCE_MIN:
                continue  # explicit guard — below threshold, no adjustment at all
            hints = _PROCEDURAL_ACTION_HINTS.get(pattern.context_type, {})
            for action, delta in hints.items():
                scores[action] = scores.get(action, 0.0) + delta * pattern.confidence

    if active_expectations:
        for exp in active_expectations:
            if exp.probability < _EXPECTATION_PROBABILITY_MIN:
                continue  # explicit guard — below threshold, no adjustment at all
            hints = _EXPECTATION_ACTION_MAP.get(exp.expected_behavior, {})
            for action, delta in hints.items():
                scores[action] = scores.get(action, 0.0) + delta * exp.probability

    return {a: clamp_01(s) for a, s in scores.items()}


# ---------------------------------------------------------------------------
# Haiku system prompts
# ---------------------------------------------------------------------------

_DECISION_SYSTEM = (
    "You are the action-decision module for an AI assistant named Sity. "
    "Based on the provided context and pre-computed utility scores, select the best "
    "action for this turn. Return ONLY a JSON object — no markdown, no explanation.\n\n"
    '{"action": "<action_name>", "reasoning": "<1-2 sentences why>"}\n\n'
    "Available actions:\n"
    "  answer        — conversational response; default for questions/statements/greetings\n"
    "  help          — active assistance; best when user explicitly requests or commands something\n"
    "  ask           — ask a clarifying question; best when message is ambiguous or highly novel\n"
    "  challenge     — push back on the user's premise; requires skepticism AND perceived challenge\n"
    "  refuse        — full rejection; RARE — requires defensiveness+assertiveness AND clear violation\n"
    "  set_boundary  — communicate limits calmly; gentler than refuse; preferred when patience is high\n"
    "  use_tool      — invoke a tool; only valid when tool domains are shown as activated\n"
    "  wait          — no active response; only for extreme disengagement signals\n"
    "  initiate      — proactively add something beyond the immediate question\n"
    "  change_topic  — steer conversation elsewhere; needs high boredom signal\n\n"
    "The utility scores were computed from personality, emotional state, relationship, goals, "
    "and perception signals using a calibrated weight matrix. You may select a different action "
    "if the context clearly warrants it — explain why in reasoning. "
    "Output only valid JSON."
)

_COHERENCE_SYSTEM = (
    "You are a coherence-check module. "
    "Given a chosen action, its reasoning, and the context, reply with valid JSON only.\n\n"
    '{"coherent": true} if the action makes sense.\n'
    '{"coherent": false, "concern": "<brief>"} if the action is clearly wrong or incoherent.\n\n'
    "Mark as incoherent ONLY when the action is obviously wrong — e.g. 'refuse' when the user "
    "is making a harmless greeting, or 'use_tool' when no tools are mentioned as active. "
    "Uncertainty or mild surprise is NOT incoherence. Be conservative: default to coherent."
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_decision_context(
    user_message: str,
    python_scores: dict[str, float],
    signals_summary: dict,
    pattern_hint: str = "",
) -> str:
    top_action = max(python_scores, key=lambda a: python_scores[a])
    top_score = python_scores[top_action]
    scores_str = ", ".join(f"{a}: {s:.2f}" for a, s in sorted(python_scores.items(), key=lambda x: -x[1]))
    base = (
        f"USER MESSAGE: {user_message[:300]}\n\n"
        f"SIGNALS SUMMARY:\n{json.dumps(signals_summary, ensure_ascii=False)}\n\n"
        f"PYTHON UTILITY SCORES (formula-computed):\n  {scores_str}\n\n"
        f"FORMULA TOP CANDIDATE: {top_action} (score: {top_score:.2f})"
    )
    if pattern_hint:
        base += f"\n\nLEARNED PATTERN ({signals_summary.get('context_type', '')}): {pattern_hint}"
    return base


def _parse_decision_response(text: str) -> tuple[str, str] | None:
    """Parse Haiku response into (action, reasoning). Returns None on failure."""
    try:
        stripped = text.strip()
        if stripped.startswith("```"):
            parts = stripped.split("```")
            stripped = parts[1] if len(parts) > 1 else stripped
            if stripped.startswith("json"):
                stripped = stripped[4:]
        data = json.loads(stripped)
        action = str(data.get("action", "")).strip().lower()
        reasoning = str(data.get("reasoning", "")).strip()
        if action not in _VALID_ACTIONS:
            return None
        return action, reasoning
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _parse_coherence_response(text: str) -> tuple[bool, str]:
    """Parse coherence check response. Returns (coherent, concern).
    On any parse failure, treats as incoherent (conservative fallback).
    """
    try:
        stripped = text.strip()
        if stripped.startswith("```"):
            parts = stripped.split("```")
            stripped = parts[1] if len(parts) > 1 else stripped
            if stripped.startswith("json"):
                stripped = stripped[4:]
        data = json.loads(stripped)
        coherent = bool(data.get("coherent", False))
        concern = str(data.get("concern", "")).strip()
        return coherent, concern
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return False, "coherence_response_parse_failed"


def _call_decision_haiku(
    context: str,
    *,
    trace_id: str,
) -> tuple[str, str] | None:
    """Haiku call #3: selects the action. Returns (action, reasoning) or None on failure."""
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    try:
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="decision",
            system_prompt=_DECISION_SYSTEM,
            user_message=context,
            max_tokens=120,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if response.ok and response.text:
            result = _parse_decision_response(response.text)
            if result is not None:
                return result
        write_log(
            level="WARN",
            module="cognition",
            event="decision_haiku_parse_failed",
            trace_id=trace_id,
            payload={"raw": (response.text or "")[:200]},
        )
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="decision_haiku_error",
            trace_id=trace_id,
            payload={"error": str(exc)[:200]},
        )
    return None


def _check_coherence(
    action: str,
    reasoning: str,
    user_message: str,
    python_scores: dict[str, float],
    *,
    trace_id: str,
) -> tuple[bool, str]:
    """Haiku call #4: validates coherence. Returns (coherent, concern).
    Also fails coherence when python score for the chosen action is very low.
    On any API failure, returns (False, "coherence_api_error").
    """
    python_score_for_action = python_scores.get(action, 0.0)
    if python_score_for_action < _COHERENCE_MIN_SCORE:
        concern = f"python_score_too_low:{python_score_for_action:.2f}"
        return False, concern

    top_action = max(python_scores, key=lambda a: python_scores[a])
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    coherence_context = (
        f"USER MESSAGE: {user_message[:200]}\n"
        f"CHOSEN ACTION: {action}\n"
        f"REASONING: {reasoning}\n"
        f"FORMULA TOP ACTION: {top_action} (score: {python_scores[top_action]:.2f})\n"
        f"SCORE FOR CHOSEN: {python_score_for_action:.2f}"
    )
    try:
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="decision_coherence",
            system_prompt=_COHERENCE_SYSTEM,
            user_message=coherence_context,
            max_tokens=40,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if response.ok and response.text:
            return _parse_coherence_response(response.text)
        return False, "coherence_api_no_response"
    except Exception as exc:
        return False, f"coherence_api_error:{str(exc)[:100]}"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_decision(
    *,
    user_message: str,
    perception: PerceptionResult,
    appraisal: AppraisalResult,
    mental_state: dict,
    personality: dict,
    affinity: float,
    conflict: float,
    trust_avg: float,
    max_goal_priority: float,
    domain_activated: bool,
    trace_id: str = "",
    values: dict[str, float] | None = None,
    procedural_patterns: list[ProceduralPattern] | None = None,
    active_expectations: list[Expectation] | None = None,
) -> DecisionResult | None:
    """Run the Decision module for this turn.

    Returns DecisionResult with the chosen action, or None if:
      - Any Haiku call fails (technical error)
      - Coherence check determines the chosen action is incoherent
    None → caller logs decision_fallback_triggered and uses the old system.

    mental_state: POST-appraisal dict with keys: frustration, interest,
        defensiveness, boredom, social_comfort, melancholy.
    domain_activated: True if toolset_selector found at least one non-base domain.
    max_goal_priority: highest compute_effective_priority across active goals (0 if none).
    """
    intent_request = perception.user_intent in ("request", "command", "task")

    python_scores = compute_utility_scores(
        personality=personality,
        mental_state=mental_state,
        affinity=affinity,
        conflict=conflict,
        trust_avg=trust_avg,
        challenge_signal=perception.challenge,
        novelty=perception.novelty,
        max_goal_priority=max_goal_priority,
        intent_request=intent_request,
        domain_activated=domain_activated,
        values=values,
        procedural_patterns=procedural_patterns,
        active_expectations=active_expectations,
    )

    signals_summary = {
        "user_intent": perception.user_intent,
        "tone":        perception.tone,
        "challenge":   round(perception.challenge, 2),
        "novelty":     round(perception.novelty, 2),
        "frustration": round(float(mental_state.get("frustration", 0.0)), 2),
        "interest":    round(float(mental_state.get("interest", 0.0)), 2),
        "defensiveness": round(float(mental_state.get("defensiveness", 0.0)), 2),
        "boredom":     round(float(mental_state.get("boredom", 0.0)), 2),
        "affinity":    round(affinity, 2),
        "conflict":    round(conflict, 2),
        "trust_avg":   round(trust_avg, 2),
        "domain_activated": domain_activated,
        "intent_request": intent_request,
        "max_goal_priority": round(max_goal_priority, 2),
        "context_type": perception.context_type,
    }

    # Build pattern_hint for Haiku context — first active pattern above confidence threshold
    pattern_hint = ""
    if procedural_patterns:
        for _p in procedural_patterns:
            if _p.confidence >= _PROCEDURAL_CONFIDENCE_MIN and _p.strategy_description:
                pattern_hint = _p.strategy_description[:120]
                break

    context = _build_decision_context(user_message, python_scores, signals_summary, pattern_hint)
    try:
        haiku_result = _call_decision_haiku(context, trace_id=trace_id)
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="decision_fallback_triggered",
            trace_id=trace_id,
            payload={
                "reason": "technical_error",
                "step": "decision_haiku_exception",
                "error": str(exc)[:200],
                "python_top": max(python_scores, key=lambda a: python_scores[a]),
            },
        )
        return None

    if haiku_result is None:
        write_log(
            level="WARN",
            module="cognition",
            event="decision_fallback_triggered",
            trace_id=trace_id,
            payload={
                "reason": "technical_error",
                "step": "decision_haiku",
                "python_top": max(python_scores, key=lambda a: python_scores[a]),
            },
        )
        return None

    action, reasoning = haiku_result

    # Defensive validation: _parse_decision_response already enforces this, but
    # verify after unpacking in case of unexpected mock/monkey-patch in testing.
    if action not in _VALID_ACTIONS:
        write_log(
            level="WARN",
            module="cognition",
            event="decision_fallback_triggered",
            trace_id=trace_id,
            payload={
                "reason": "technical_error",
                "step": "invalid_action_returned",
                "action": action,
                "python_top": max(python_scores, key=lambda a: python_scores[a]),
            },
        )
        return None

    coherent, concern = _check_coherence(
        action, reasoning, user_message, python_scores, trace_id=trace_id
    )

    if not coherent:
        write_log(
            level="WARN",
            module="cognition",
            event="decision_fallback_triggered",
            trace_id=trace_id,
            payload={
                "reason": "coherence_check_failed",
                "haiku_action": action,
                "concern": concern,
                "python_top": max(python_scores, key=lambda a: python_scores[a]),
                "python_score_for_haiku_action": round(python_scores.get(action, 0.0), 3),
            },
        )
        return None

    write_log(
        level="INFO",
        module="cognition",
        event="decision_completed",
        trace_id=trace_id,
        payload={
            "action": action,
            "python_top": max(python_scores, key=lambda a: python_scores[a]),
            "python_score": round(python_scores.get(action, 0.0), 3),
            "reasoning_snippet": reasoning[:100],
        },
    )

    return DecisionResult(
        action=action,
        python_scores=python_scores,
        reasoning=reasoning,
    )
