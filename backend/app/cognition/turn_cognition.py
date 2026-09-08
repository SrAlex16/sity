"""turn_cognition.py — Full per-turn cognition pipeline (Fase 2, Paso 3).

run_cognition_turn is the single entry point for the complete cognition pass:
  1. Load active Goals from DB (before Perception, so Appraisal can score them)
  2. Run Perception (Haiku classifier)
  3. Load MentalState SQLModel row — needed for delta application (not the dict
     already in TurnContext, which is a pre-turn snapshot for PersonaEngine)
  4. Run Appraisal (Haiku — receives Perception + MentalState + Goals)
  5. Apply Appraisal deltas to MentalState row and persist
  6. Apply GoalUpdateIntents to DB (create new Goal rows)
  7. Return CognitionTurnResult

Never raises — Perception and Appraisal return neutral/zero fallbacks on any error.
The MentalState commit is the only DB write that could fail; it is wrapped in the
SettingsService.save_mental_state contract (which does not swallow errors, so the
caller's outer try/except in turn_runner.py guards this path).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import Session

from app.cognition.appraisal import AppraisalResult, apply_appraisal_to_mental_state, run_appraisal
from app.cognition.goal_service import apply_goal_intents, apply_goal_state_changes, get_active_goals
from app.cognition.perception import PerceptionResult, run_perception
from app.memory.models import Goal
from app.settings.settings_service import SettingsService


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
    """Run the full cognition pipeline for one authenticated user turn.

    MentalState timing note: TurnContext.mental_state is a plain dict snapshot
    built before this function runs and already passed to PersonaEngine. Appraisal
    deltas are applied here to the SQLModel row and persisted — the updated values
    take effect starting from the NEXT turn. This is intentional.
    """
    # Load goals before Perception so Appraisal can score per-goal relevance
    active_goals = get_active_goals(session, user_id)
    active_goals_dicts = [
        {
            "id": g.id,
            "description": g.description,
            "scope": g.scope,
            "is_wellbeing": g.is_wellbeing,
        }
        for g in active_goals
    ]

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

    if appraisal.goal_updates:
        apply_goal_intents(session, user_id, appraisal.goal_updates)

    if appraisal.goal_state_changes:
        apply_goal_state_changes(session, user_id, appraisal.goal_state_changes)

    return CognitionTurnResult(
        perception=perception,
        appraisal=appraisal,
        active_goals=active_goals,
    )
