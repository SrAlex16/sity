"""turn_cognition.py — Full per-turn cognition pipeline (Fase 2 Paso 3, Fase 3 Paso 1, Fase 4).

run_cognition_turn is the single entry point for the complete cognition pass:
  1. Expire stale short_term goals
  2. Load active Goals + their milestones
  3. Run Perception (Haiku classifier)
  4. Load MentalState SQLModel row
  5. Run Appraisal (Haiku — Perception + MentalState + Goals)
  6. Apply Appraisal deltas to MentalState row and persist
  7. Load SocialProfile row
  8. Apply Appraisal + Perception signals to SocialProfile and persist
  9. Apply GoalUpdateIntents, GoalStateChanges, MilestoneUpdates to DB
 10. Evaluate salience and maybe persist an Episode (Haiku, conditional)
 11. Return CognitionTurnResult

Never raises — Perception and Appraisal return neutral/zero fallbacks on any error.
The MentalState/SocialProfile commits are the only DB writes that could fail; they are
wrapped in a try/except at the call site in turn_runner.py.

MentalState timing note: TurnContext.mental_state is a plain dict snapshot
built before this function runs and already passed to PersonaEngine. Deltas
are applied here to the SQLModel rows and persisted for the NEXT turn.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import Session

from app.cognition.appraisal import AppraisalResult, apply_appraisal_to_mental_state, run_appraisal
from app.cognition.episode_service import maybe_create_episode
from app.trace.logger import write_log
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


@dataclass
class CognitionTurnResult:
    perception: PerceptionResult
    appraisal: AppraisalResult
    active_goals: list[Goal] = field(default_factory=list)


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

    # Step 10: episodic memory — conditional Haiku call only when salience ≥ 0.25
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

    return CognitionTurnResult(
        perception=perception,
        appraisal=appraisal,
        active_goals=active_goals,
    )
