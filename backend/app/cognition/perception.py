"""Perception — Fase 2 + Fase 7. Single Haiku call, runs every turn.

Contracts (Section 12 of SITY_VNEXT_ARQUITECTURA_MENTE_COMPLETA.md):
  user_intent  : coarse intent category (request, question, vent, joke, ...)
  tone         : detected tone (playful, serious, frustrated, ironic, neutral, ...)
  challenge    : float [0, 1] — confrontation/challenge level directed at Sity
  social_signal: float [0, 1] — interpersonal/relational content weight
  novelty      : float [0, 1] — how novel/unexpected the topic is vs. routine
  context_type : interaction domain category for procedural pattern detection (Fase 7)

On any error, returns PerceptionResult.neutral() — never blocks the main pipeline.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from app.cognition.semantic_proposition import SemanticProperties, SemanticProposition
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
_VALID_CONTEXT_TYPES = frozenset({
    "technical_design", "debugging", "implementation", "explanation",
    "casual_chat", "creative", "planning", "feedback",
})
_VALID_TEMPORAL_SCOPES = frozenset({
    "persistent", "habitual", "transient", "situational",
})

_PERCEPTION_SYSTEM = (
    "Analyze the user's message and return a JSON object with exactly these fields. "
    "No explanation, no markdown, no wrapping — only raw JSON.\n\n"
    '{\n'
    '  "user_intent": <one of: request|question|vent|joke|greeting|farewell|task|opinion|complaint|other>,\n'
    '  "tone": <one of: playful|serious|frustrated|ironic|neutral|warm|hostile|curious|sad|anxious|other>,\n'
    '  "challenge": <float 0.0-1.0 — how much the message confronts or challenges the assistant>,\n'
    '  "social_signal": <float 0.0-1.0 — interpersonal/relational content weight>,\n'
    '  "novelty": <float 0.0-1.0 — how unexpected or novel the topic is vs. routine exchanges>,\n'
    '  "context_type": <one of: technical_design|debugging|implementation|explanation|casual_chat|creative|planning|feedback>,\n'
    '  "semantic_propositions": [\n'
    '    {\n'
    '      "id": "p1",\n'
    '      "content": "<≤200 chars — describe user in third person: \'User dislikes coffee\'>",\n'
    '      "properties": {\n'
    '        "personal_relevance": <0.0-1.0 — 0=external info, 1=directly about the user>,\n'
    '        "temporal_scope": "<persistent|habitual|transient|situational>",\n'
    '        "context_dependency": <0.0-1.0 — 0=general truth, 1=only true in this specific context>,\n'
    '        "assertion_strength": <0.0-1.0 — 0=hypothetical/uncertain, 1=clear direct statement>,\n'
    '        "expected_duration": <0.0-1.0 — 0=momentary state, 1=permanent trait>,\n'
    '        "behavioral_relevance": <0.0-1.0 — 0=no impact on responses, 1=changes how to respond>\n'
    '      }\n'
    '    }\n'
    '  ]\n'
    '}\n\n'
    "Definitions:\n"
    "- challenge: 0 = fully cooperative, 1 = aggressive confrontation or strong pressure\n"
    "- social_signal: 0 = purely informational, 1 = deeply personal/relational\n"
    "- novelty: 0 = routine/repetitive, 1 = completely new or surprising topic\n"
    "- context_type: dominant interaction domain\n"
    "  technical_design = architecture/design decisions/trade-offs\n"
    "  debugging = bugs/errors/troubleshooting\n"
    "  implementation = write/generate/build something concrete\n"
    "  explanation = conceptual questions, how/why/what does X mean\n"
    "  casual_chat = social/personal/greetings/humor\n"
    "  creative = writing/brainstorming/storytelling/ideation\n"
    "  planning = organizing/coordinating/step-by-step planning\n"
    "  feedback = review/critique/opinion on existing work\n"
    "- semantic_propositions: stable personal facts about the user ONLY.\n"
    "  Use third-person: 'User dislikes coffee', 'User has a dog named Toby'.\n"
    "  Return empty [] when the message has no personal user-specific information.\n"
    "  temporal_scope: persistent=permanent trait, habitual=recurring pattern,\n"
    "    transient=temporary state (e.g. 'tired today'), situational=only true in this context.\n"
    "  Max 5 propositions.\n\n"
    "Use neutral defaults (challenge=0.1, social_signal=0.3, novelty=0.2, context_type=casual_chat) "
    "for ambiguous messages. Output only valid JSON."
)


@dataclass
class PerceptionResult:
    user_intent: str
    tone: str
    challenge: float
    social_signal: float
    novelty: float
    context_type: str = "casual_chat"
    semantic_propositions: list[SemanticProposition] = field(default_factory=list)

    @classmethod
    def neutral(cls) -> "PerceptionResult":
        return cls(
            user_intent="other",
            tone="neutral",
            challenge=0.1,
            social_signal=0.3,
            novelty=0.2,
            context_type="casual_chat",
        )

    def as_dict(self) -> dict:
        return {
            "user_intent": self.user_intent,
            "tone": self.tone,
            "challenge": self.challenge,
            "social_signal": self.social_signal,
            "novelty": self.novelty,
            "context_type": self.context_type,
        }


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _parse_semantic_proposition(raw: Any, idx: int) -> SemanticProposition | None:
    """Parse one semantic proposition dict from Haiku output. Returns None on failure."""
    if not isinstance(raw, dict):
        return None
    content = str(raw.get("content", "")).strip()[:200]
    if not content:
        return None
    prop_id = str(raw.get("id", f"p{idx + 1}"))
    props_raw = raw.get("properties") or {}
    if not isinstance(props_raw, dict):
        props_raw = {}

    def _f(key: str, default: float = 0.0) -> float:
        try:
            return max(0.0, min(1.0, float(props_raw.get(key, default))))
        except (TypeError, ValueError):
            return default

    ts = str(props_raw.get("temporal_scope", "persistent")).lower()
    return SemanticProposition(
        id=prop_id,
        content=content,
        properties=SemanticProperties(
            personal_relevance=_f("personal_relevance"),
            temporal_scope=ts if ts in _VALID_TEMPORAL_SCOPES else "persistent",
            context_dependency=_f("context_dependency"),
            assertion_strength=_f("assertion_strength"),
            expected_duration=_f("expected_duration"),
            behavioral_relevance=_f("behavioral_relevance"),
        ),
    )


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
        context_type = str(data.get("context_type", "casual_chat")).lower()

        raw_props = data.get("semantic_propositions", [])
        semantic_propositions: list[SemanticProposition] = []
        if isinstance(raw_props, list):
            for i, p in enumerate(raw_props[:5]):
                sp = _parse_semantic_proposition(p, i)
                if sp is not None:
                    semantic_propositions.append(sp)

        return PerceptionResult(
            user_intent=user_intent if user_intent in _VALID_INTENTS else "other",
            tone=tone if tone in _VALID_TONES else "neutral",
            challenge=_clamp(float(data.get("challenge", 0.1))),
            social_signal=_clamp(float(data.get("social_signal", 0.3))),
            novelty=_clamp(float(data.get("novelty", 0.2))),
            context_type=context_type if context_type in _VALID_CONTEXT_TYPES else "casual_chat",
            semantic_propositions=semantic_propositions,
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
            max_tokens=700,
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
