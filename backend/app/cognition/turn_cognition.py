"""turn_cognition.py — Full per-turn cognition pipeline (Fases 2–7).

run_cognition_turn is the single entry point for the complete cognition pass:
  1.  Expire stale short_term goals
  2.  Load active Goals + their milestones
  3.  Run Perception (Haiku #1) — includes context_type classification (Fase 7)
  4.  Load MentalState SQLModel row
  5.  Run Appraisal (Haiku #2 — Perception + MentalState + Goals)
  6.  Apply Appraisal deltas to MentalState row and persist
  7.  Load SocialProfile row
  8.  Apply Appraisal + Perception signals to SocialProfile and persist
  9.  Apply GoalUpdateIntents, GoalStateChanges, MilestoneUpdates to DB
 10.  Compute salience (pure Python — used for both Episode and Reflection gates)
 11.  Evaluate salience and maybe persist an Episode (Haiku #3, conditional ≥ 0.25)
 12.  Run Decision (Haiku #4 + coherence check Haiku #5) → DecisionResult | None
 13.  Run Reflection after-action review (Haiku #6, conditional ≥ 0.45) → ReflectionResult | None
 14.  Return CognitionTurnResult
 15.  Record ProceduralObservation; fire background synthesis if threshold reached (non-blocking)

Never raises — Perception and Appraisal return neutral/zero fallbacks on any error.
Decision returns None on any failure (technical or coherence) → fallback to old system.
The MentalState/SocialProfile commits are the only DB writes that could fail; they are
wrapped in a try/except at the call site in turn_runner.py.

MentalState timing note: TurnContext.mental_state is a plain dict snapshot
built before this function runs and already passed to PersonaEngine. Deltas
are applied here to the SQLModel rows and persisted for the NEXT turn.
Decision uses the POST-APPRAISAL mental state (after step 6).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import Session

from app.cognition.appraisal import AppraisalResult, apply_appraisal_to_mental_state, run_appraisal
from app.cognition.decision import DecisionResult, run_decision
from app.cognition.episode_service import compute_salience, maybe_create_episode
from app.cognition.procedural_service import maybe_trigger_pattern_synthesis
from app.cognition.reflection import ReflectionResult, _REFLECTION_SALIENCE_MIN, run_reflection
from app.cognition.self_model_service import load_values_dict
from app.cognition.goal_priority import compute_effective_priority
from app.cognition.goal_service import (
    apply_goal_intents,
    apply_goal_state_changes,
    apply_milestone_updates,
    get_active_goals,
    get_milestones_for_goal,
    resolve_expired_short_term_goals,
)
from app.cognition.perception import PerceptionResult, run_perception
from app.memory.models import Goal
from app.settings.settings_service import SettingsService
from app.social.social_service import apply_appraisal_to_social_profile, get_or_create_social_profile
from app.trace.logger import write_log


@dataclass
class CognitionTurnResult:
    perception: PerceptionResult
    appraisal: AppraisalResult
    active_goals: list[Goal] = field(default_factory=list)
    decision: DecisionResult | None = None
    reflection: ReflectionResult | None = None


def run_cognition_turn(
    session: Session,
    user_id: int,
    user_message: str,
    settings_service: SettingsService,
    personality: dict,
    *,
    trace_id: str = "",
) -> CognitionTurnResult:
    """Run the full cognition pipeline for one authenticated user turn."""
    # Expire stale short_term goals before loading — keeps context clean
    resolve_expired_short_term_goals(session, user_id)

    # Load goals + their milestones before Perception so Appraisal can reference milestone IDs
    active_goals = get_active_goals(session, user_id)
    active_goals_dicts = []
    for g in active_goals:
        milestones = get_milestones_for_goal(session, g.id) if g.id is not None else []
        active_goals_dicts.append({
            "id": g.id,
            "description": g.description,
            "scope": g.scope,
            "is_wellbeing": g.is_wellbeing,
            "milestones": [
                {"id": m.id, "description": m.description, "status": m.status}
                for m in milestones
            ],
        })

    perception = run_perception(user_message, trace_id=trace_id)

    # Load the SQLModel row (not the dict) to apply deltas in-place
    ms_row = settings_service.get_or_create_mental_state(user_id)
    mental_state_dict = {
        "interest":          ms_row.interest,
        "frustration":       ms_row.frustration,
        "social_comfort":    ms_row.social_comfort,
        "valence":           ms_row.valence,
        "arousal":           ms_row.arousal,
        "current_curiosity": ms_row.current_curiosity,
        "boredom":           ms_row.boredom,
        "melancholy":        ms_row.melancholy,
        "defensiveness":     ms_row.defensiveness,
    }

    appraisal = run_appraisal(
        perception=perception.as_dict(),
        mental_state=mental_state_dict,
        personality=personality,
        active_goals=active_goals_dicts,
        trace_id=trace_id,
    )

    apply_appraisal_to_mental_state(ms_row, appraisal)
    settings_service.save_mental_state(ms_row)

    # Per-turn SocialProfile update: Appraisal + Perception signals → 11 relationship dimensions
    sp_row = get_or_create_social_profile(session, user_id)
    apply_appraisal_to_social_profile(
        profile=sp_row,
        appraisal_trust_evidence=appraisal.trust_evidence,
        appraisal_interest_delta=appraisal.interest_delta,
        appraisal_frustration_delta=appraisal.frustration_delta,
        perception_social_signal=perception.social_signal,
        perception_challenge=perception.challenge,
        personality=personality,
    )
    session.add(sp_row)
    session.commit()

    if appraisal.goal_updates:
        apply_goal_intents(session, user_id, appraisal.goal_updates)

    if appraisal.goal_state_changes:
        apply_goal_state_changes(session, user_id, appraisal.goal_state_changes)

    if appraisal.milestone_updates:
        apply_milestone_updates(session, user_id, appraisal.milestone_updates)

    # Step 10: compute salience (pure Python) — used for both Episode and Reflection gates
    _salience = compute_salience(perception, appraisal)

    # Step 11: episodic memory — conditional Haiku call only when salience ≥ 0.25
    try:
        maybe_create_episode(
            session=session,
            user_id=user_id,
            user_message=user_message,
            perception=perception,
            appraisal=appraisal,
            source_message_ids=[],
            trace_id=trace_id,
        )
    except Exception as ep_exc:
        write_log(
            level="WARN",
            module="cognition",
            event="episode_creation_failed",
            trace_id=trace_id,
            payload={"user_id": user_id, "error": str(ep_exc)[:200]},
        )

    # Step 12: Decision — selects one of 10 actions via Haiku + coherence check.
    # Returns None on any failure → turn_runner.py falls back to old system.
    decision_result: DecisionResult | None = None
    try:
        # POST-APPRAISAL mental state (after deltas applied in step 6)
        post_mental_state = {
            "frustration":    ms_row.frustration,
            "interest":       ms_row.interest,
            "defensiveness":  ms_row.defensiveness,
            "boredom":        ms_row.boredom,
            "social_comfort": ms_row.social_comfort,
            "melancholy":     ms_row.melancholy,
        }
        # Trust average across the 4 trust dimensions in SocialProfile
        _trust_avg = (
            sp_row.trust_honesty + sp_row.trust_intentions
            + sp_row.trust_competence + sp_row.trust_reliability
        ) / 4.0
        # Highest effective_priority across active goals; 0 if no goals
        _max_goal_priority = 0.0
        if active_goals:
            _rel_map = {gr.goal_id: gr.relevance for gr in appraisal.goal_relevance}
            for _g in active_goals:
                if _g.id is not None:
                    _eff = compute_effective_priority(
                        base_importance=_g.base_importance,
                        relevance_boost=_rel_map.get(_g.id, 0.0),
                        tone=perception.tone,
                        is_wellbeing=_g.is_wellbeing,
                    )
                    _max_goal_priority = max(_max_goal_priority, _eff)
        # domain_activated: any non-base tool domain triggered for this message
        from app.chat.toolset_selector import select_toolset_with_metadata
        _domain_activated = bool(
            select_toolset_with_metadata(user_message).activated_domains
        )
        try:
            _values_dict: dict[str, float] | None = load_values_dict(session)
        except Exception:
            _values_dict = None
        decision_result = run_decision(
            user_message=user_message,
            perception=perception,
            appraisal=appraisal,
            mental_state=post_mental_state,
            personality=personality,
            affinity=sp_row.affinity,
            conflict=sp_row.conflict,
            trust_avg=_trust_avg,
            max_goal_priority=_max_goal_priority,
            domain_activated=_domain_activated,
            trace_id=trace_id,
            values=_values_dict,
        )
    except Exception as dec_exc:
        write_log(
            level="WARN",
            module="cognition",
            event="decision_fallback_triggered",
            trace_id=trace_id,
            payload={
                "reason": "technical_error",
                "step": "decision_orchestration",
                "error": str(dec_exc)[:200],
            },
        )

    # Step 13: Reflection — after-action review when salience ≥ 0.45 (sección 56).
    # Runs after Decision so it can include the chosen action in its context.
    reflection_result: ReflectionResult | None = None
    if _salience.total >= _REFLECTION_SALIENCE_MIN:
        try:
            reflection_result = run_reflection(
                session,
                user_id=user_id,
                user_message=user_message,
                perception=perception,
                appraisal=appraisal,
                decision=decision_result,
                salience_total=_salience.total,
                trace_id=trace_id,
            )
        except Exception as refl_exc:
            write_log(
                level="WARN",
                module="cognition",
                event="reflection_failed",
                trace_id=trace_id,
                payload={"user_id": user_id, "error": str(refl_exc)[:200]},
            )

    # Step 15: Procedural memory — record observation; fire daemon synthesis if threshold reached.
    # Non-blocking: any failure is logged and swallowed; never affects turn result.
    try:
        maybe_trigger_pattern_synthesis(
            session,
            user_id=user_id,
            context_type=perception.context_type,
            user_message=user_message,
            trace_id=trace_id,
        )
    except Exception as proc_exc:
        write_log(
            level="WARN",
            module="cognition",
            event="procedural_observation_error",
            trace_id=trace_id,
            payload={"user_id": user_id, "error": str(proc_exc)[:200]},
        )

    return CognitionTurnResult(
        perception=perception,
        appraisal=appraisal,
        active_goals=active_goals,
        decision=decision_result,
        reflection=reflection_result,
    )
