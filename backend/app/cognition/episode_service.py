"""episode_service.py — Episodic memory creation (Remake Fase 4).

Computes salience for each conversational turn and — when the turn clears the
threshold — calls a conditional Haiku pass to generate a compact episode summary,
then persists the Episode row.

Salience formula (7 components, weights sum to 1.0):
  salience = 0.20*novelty + 0.15*emotional_intensity + 0.25*goal_relevance
           + 0.15*relationship_impact + 0.10*surprise + 0.05*repetition
           + 0.10*explicit_importance

  novelty             → perception.novelty
  emotional_intensity → (|interest_delta| + |frustration_delta|) / 0.6, clamped [0,1]
  goal_relevance      → max relevance across active goals (from appraisal.goal_relevance)
  relationship_impact → clamp(social_signal*0.5 + challenge*0.4 + trust_evidence*4.0)
  surprise            → appraisal.surprise
  repetition          → 0.0 (bootstrap; placeholder for future recurrence detection)
  explicit_importance → appraisal.explicit_importance

Special rule: if explicit_importance > 0.7 → salience = max(salience, 0.45)

Levels:
  baja   < 0.25  → no Episode created (zero cost)
  media  0.25–0.45 → Episode, strength=0.50
  alta   0.45–0.70 → Episode, strength=1.00
  muy_alta ≥ 0.70 → Episode, strength=1.00 (autobiographical candidate)

Haiku call (max_tokens=150) is made ONLY when salience ≥ 0.25.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import Session

from app.cognition.appraisal import AppraisalResult
from app.cognition.perception import PerceptionResult
from app.memory.models import Episode, utc_now
from app.trace.logger import write_log

_HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Salience weights (sum = 1.0)
_W_NOVELTY              = 0.20
_W_EMOTIONAL_INTENSITY  = 0.15
_W_GOAL_RELEVANCE       = 0.25
_W_RELATIONSHIP_IMPACT  = 0.15
_W_SURPRISE             = 0.10
_W_REPETITION           = 0.05
_W_EXPLICIT_IMPORTANCE  = 0.10

# Thresholds
_THR_NONE   = 0.25   # below this → no episode
_THR_MEDIA  = 0.45   # below this → media (strength 0.50)
_THR_ALTA   = 0.70   # below this → alta (strength 1.00); ≥ this → muy_alta

# Strength values
_STRENGTH_MEDIA = 0.50
_STRENGTH_ALTA  = 1.00

# Special rule: explicit_importance above this floor forces salience ≥ _EXPLICIT_FLOOR_VALUE
_EXPLICIT_FLOOR_TRIGGER = 0.70
_EXPLICIT_FLOOR_VALUE   = 0.45


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


@dataclass
class SalienceResult:
    novelty: float
    emotional_intensity: float
    goal_relevance: float
    relationship_impact: float
    surprise: float
    explicit_importance: float
    total: float

    @property
    def level(self) -> str:
        if self.total < _THR_NONE:
            return "baja"
        if self.total < _THR_MEDIA:
            return "media"
        if self.total < _THR_ALTA:
            return "alta"
        return "muy_alta"

    @property
    def strength(self) -> float:
        if self.level == "baja":
            return 0.0
        if self.level == "media":
            return _STRENGTH_MEDIA
        return _STRENGTH_ALTA


@dataclass
class EpisodeSummaryResult:
    summary: str
    topics: list[str] = field(default_factory=list)
    emotional_valence: float = 0.0
    emotional_arousal: float = 0.0


_SUMMARY_SYSTEM = (
    "Eres un módulo de memoria episódica. Lee el mensaje del usuario y genera un registro "
    "compacto del momento conversacional.\n\n"
    "Devuelve SOLO JSON válido con estos campos:\n"
    "{\n"
    '  "summary": "<1-2 frases que capturen la esencia del momento>",\n'
    '  "topics": ["<tema1>", "<tema2>"],\n'
    '  "emotional_valence": <float -1.0 a 1.0 — negativo=tono negativo, positivo=positivo>,\n'
    '  "emotional_arousal": <float 0.0 a 1.0 — 0=calma, 1=alta activación>\n'
    "}\n\n"
    "REGLAS:\n"
    "- summary: conciso, en español, sin mencionar valores numéricos.\n"
    "- topics: 1-3 temas principales como palabras clave en español.\n"
    "- emotional_valence: -1=muy negativo, 0=neutro, 1=muy positivo.\n"
    "- emotional_arousal: 0=rutinario/calmo, 1=intenso/urgente.\n"
    "- No incluyas nada fuera del JSON."
)


def _generate_episode_summary(
    user_message: str,
    trace_id: str,
) -> Optional[EpisodeSummaryResult]:
    """Call Haiku to generate a compact episode summary. Returns None on any error."""
    from app.cortex.providers.factory import build_ai_provider
    from app.cortex.schemas import AIRequest

    provider_name = os.getenv("SITY_AI_PROVIDER", "anthropic")
    try:
        provider = build_ai_provider(provider_name, model=_HAIKU_MODEL)
        request = AIRequest(
            trace_id=trace_id,
            task_type="episode_summary",
            system_prompt=_SUMMARY_SYSTEM,
            user_message=f"Mensaje del usuario:\n{user_message[:1000]}",
            max_tokens=150,
            tools_enabled=False,
        )
        response = provider.generate(request)
        if not response.ok or not response.text:
            return None
        text = response.text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        summary = str(data.get("summary", "")).strip()
        if not summary:
            return None
        topics_raw = data.get("topics", [])
        topics = [str(t).strip() for t in topics_raw if isinstance(t, str) and str(t).strip()]
        raw_valence = max(-1.0, min(1.0, float(data.get("emotional_valence", 0.0))))
        arousal = _clamp01(float(data.get("emotional_arousal", 0.0)))
        return EpisodeSummaryResult(
            summary=summary,
            topics=topics,
            emotional_valence=raw_valence,
            emotional_arousal=arousal,
        )
    except Exception as exc:
        write_log(
            level="WARN",
            module="cognition",
            event="episode_summary_failed",
            trace_id=trace_id,
            payload={"error": str(exc)[:200]},
        )
        return None


def compute_salience(
    perception: PerceptionResult,
    appraisal: AppraisalResult,
) -> SalienceResult:
    """Pure deterministic salience computation. No I/O."""
    novelty = _clamp01(perception.novelty)

    raw_ei = (abs(appraisal.interest_delta) + abs(appraisal.frustration_delta)) / 0.6
    emotional_intensity = _clamp01(raw_ei)

    goal_relevance = max(
        (gr.relevance for gr in appraisal.goal_relevance),
        default=0.0,
    )
    goal_relevance = _clamp01(goal_relevance)

    relationship_impact = _clamp01(
        perception.social_signal * 0.5
        + perception.challenge * 0.4
        + appraisal.trust_evidence * 4.0
    )

    surprise = _clamp01(appraisal.surprise)
    explicit_importance = _clamp01(appraisal.explicit_importance)

    total = (
        _W_NOVELTY             * novelty
        + _W_EMOTIONAL_INTENSITY * emotional_intensity
        + _W_GOAL_RELEVANCE      * goal_relevance
        + _W_RELATIONSHIP_IMPACT * relationship_impact
        + _W_SURPRISE            * surprise
        # repetition = 0.0 always (bootstrap)
        + _W_EXPLICIT_IMPORTANCE * explicit_importance
    )
    total = _clamp01(total)

    if explicit_importance > _EXPLICIT_FLOOR_TRIGGER:
        total = max(total, _EXPLICIT_FLOOR_VALUE)

    return SalienceResult(
        novelty=novelty,
        emotional_intensity=emotional_intensity,
        goal_relevance=goal_relevance,
        relationship_impact=relationship_impact,
        surprise=surprise,
        explicit_importance=explicit_importance,
        total=total,
    )


def maybe_create_episode(
    session: Session,
    user_id: int,
    user_message: str,
    perception: PerceptionResult,
    appraisal: AppraisalResult,
    source_message_ids: list[int],
    *,
    trace_id: str = "",
) -> Optional[Episode]:
    """Evaluate salience and, when sufficient, create an Episode row.

    Returns the persisted Episode on success, None when salience is baja
    or the summary Haiku call fails.
    """
    sal = compute_salience(perception, appraisal)

    if sal.level == "baja":
        return None

    summary_result = _generate_episode_summary(user_message, trace_id)
    if summary_result is None:
        return None

    episode = Episode(
        user_id=user_id,
        occurred_at=utc_now(),
        summary=summary_result.summary,
        topics_json=json.dumps(summary_result.topics, ensure_ascii=False),
        source_message_ids_json=json.dumps(source_message_ids),
        salience_novelty=sal.novelty,
        salience_emotional_intensity=sal.emotional_intensity,
        salience_goal_relevance=sal.goal_relevance,
        salience_relationship_impact=sal.relationship_impact,
        salience_surprise=sal.surprise,
        salience_total=sal.total,
        emotional_valence=summary_result.emotional_valence,
        emotional_arousal=summary_result.emotional_arousal,
        relationship_effect_json="{}",
        strength=sal.strength,
        recall_count=0,
        created_at=utc_now(),
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)

    write_log(
        level="INFO",
        module="cognition",
        event="episode_created",
        trace_id=trace_id,
        payload={
            "user_id": user_id,
            "episode_id": episode.id,
            "salience_level": sal.level,
            "salience_total": round(sal.total, 3),
            "strength": sal.strength,
        },
    )
    return episode
