"""Perception — Fase 2. Single Haiku call, runs every turn.

Contracts (Section 12 of SITY_VNEXT_ARQUITECTURA_MENTE_COMPLETA.md):
  user_intent  : coarse intent category (request, question, vent, joke, ...)
  tone         : detected tone (playful, serious, frustrated, ironic, neutral, ...)
  challenge    : float [0, 1] — confrontation/challenge level directed at Sity
  social_signal: float [0, 1] — interpersonal/relational content weight
  novelty      : float [0, 1] — how novel/unexpected the topic is vs. routine

On any error, returns PerceptionResult.neutral() — never blocks the main pipeline.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from app.cortex.providers.factory import build_ai_provider
from app.cortex.schemas import AIRequest
from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"

_VALID_INTENTS = frozenset({
    "request", "question", "vent", "joke", "greeting",
    "farewell", "task", "opinion", "complaint", "other",
})
_VALID_TONES = frozenset({
    "playful", "serious", "frustrated", "ironic", "neutral",
    "warm", "hostile", "curious", "sad", "anxious", "other",
})

_PERCEPTION_SYSTEM = (
    "Analyze the user's message and return a JSON object with exactly these fields. "
    "No explanation, no markdown, no wrapping — only raw JSON.\n\n"
    '{\n'
    '  "user_intent": <one of: request|question|vent|joke|greeting|farewell|task|opinion|complaint|other>,\n'
    '  "tone": <one of: playful|serious|frustrated|ironic|neutral|warm|hostile|curious|sad|anxious|other>,\n'
    '  "challenge": <float 0.0-1.0 — how much the message confronts or challenges the assistant>,\n'
    '  "social_signal": <float 0.0-1.0 — interpersonal/relational content weight>,\n'
    '  "novelty": <float 0.0-1.0 — how unexpected or novel the topic is vs. routine exchanges>\n'
    '}\n\n'
    "Definitions:\n"
    "- challenge: 0 = fully cooperative, 1 = aggressive confrontation or strong pressure\n"
    "- social_signal: 0 = purely informational, 1 = deeply personal/relational\n"
    "- novelty: 0 = routine/repetitive, 1 = completely new or surprising topic\n\n"
    "Use neutral defaults (challenge=0.1, social_signal=0.3, novelty=0.2) for ambiguous messages. "
    "Output only valid JSON."
)


@dataclass
class PerceptionResult:
    user_intent: str
    tone: str
    challenge: float
    social_signal: float
    novelty: float

    @classmethod
    def neutral(cls) -> "PerceptionResult":
        return cls(
            user_intent="other",
            tone="neutral",
            challenge=0.1,
            social_signal=0.3,
            novelty=0.2,
        )

    def as_dict(self) -> dict:
        return {
            "user_intent": self.user_intent,
            "tone": self.tone,
            "challenge": self.challenge,
            "social_signal": self.social_signal,
            "novelty": self.novelty,
        }


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _parse_perception(text: str) -> PerceptionResult | None:
    try:
        stripped = text.strip()
        # Strip markdown code fences if present
        if stripped.startswith("```"):
            parts = stripped.split("```")
            stripped = parts[1] if len(parts) > 1 else stripped
            if stripped.startswith("json"):
                stripped = stripped[4:]
        data = json.loads(stripped)
        user_intent = str(data.get("user_intent", "other")).lower()
        tone = str(data.get("tone", "neutral")).lower()
        return PerceptionResult(
            user_intent=user_intent if user_intent in _VALID_INTENTS else "other",
            tone=tone if tone in _VALID_TONES else "neutral",
            challenge=_clamp(float(data.get("challenge", 0.1))),
            social_signal=_clamp(float(data.get("social_signal", 0.3))),
            novelty=_clamp(float(data.get("novelty", 0.2))),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def run_perception(
    user_message: str,
    *,
    trace_id: str = "",
) -> PerceptionResult:
    """Run Perception classifier on the user's message.

    Returns PerceptionResult.neutral() on any provider error — never raises.
    """
    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    try:
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="perception",
            system_prompt=_PERCEPTION_SYSTEM,
            user_message=user_message,
            max_tokens=80,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if response.ok and response.text:
            result = _parse_perception(response.text)
            if result is not None:
                return result
        write_log(
            level="WARN",
            module="cognition",
            event="perception_parse_failed",
            trace_id=trace_id,
            payload={"raw": (response.text or "")[:200]},
        )
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="perception_error",
            trace_id=trace_id,
            payload={"error": str(exc)[:200]},
        )
    return PerceptionResult.neutral()
