"""goal_service.py — DB operations for Goal and GoalMilestone entities (Fase 2).

Public API:
  get_active_goals          — load active Goal rows for a user
  get_milestones_for_goal   — load GoalMilestone rows for a goal, ordered by order_index
  create_goal_from_intent   — persist a GoalUpdateIntent as a Goal row (+ initial milestones)
  apply_goal_intents        — apply a list of GoalUpdateIntents to DB
  apply_goal_state_changes  — apply Appraisal-suggested status transitions (active→resolved/abandoned)
  apply_milestone_updates   — apply Appraisal-suggested milestone additions and completions
  build_active_goals_block  — format high-priority goals for Expression context injection

The priority threshold (≥ 0.5) and max-3 cap keep the injected block short enough
to not dominate the system prompt.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlmodel import Session, select

from app.cognition.appraisal import AppraisalResult, GoalStateChange, GoalUpdateIntent, MilestoneIntent
from app.cognition.goal_priority import compute_effective_priority
from app.memory.models import Goal, GoalMilestone, utc_now

_MIN_PRIORITY_THRESHOLD = 0.5
_MAX_GOALS_IN_BLOCK = 3


def get_active_goals(
    session: Session,
    user_id: int,
    *,
    scope_filter: Optional[str] = None,
) -> list[Goal]:
    """Return active Goal rows for user_id. Optionally filter by scope."""
    query = select(Goal).where(
        Goal.user_id == user_id,
        Goal.status == "active",
    )
    if scope_filter:
        query = query.where(Goal.scope == scope_filter)
    return list(session.exec(query).all())


def get_milestones_for_goal(session: Session, goal_id: int) -> list[GoalMilestone]:
    """Return GoalMilestone rows for a goal, ordered by order_index ascending."""
    return list(session.exec(
        select(GoalMilestone)
        .where(GoalMilestone.goal_id == goal_id)
        .order_by(GoalMilestone.order_index)  # type: ignore[arg-type]
    ).all())


def create_goal_from_intent(
    session: Session,
    user_id: int,
    intent: GoalUpdateIntent,
) -> Goal:
    """Persist a GoalUpdateIntent as a new Goal row (with any initial milestones) and return it."""
    goal = Goal(
        user_id=user_id,
        scope=intent.scope,
        description=intent.description,
        origin="autonomous",
        base_importance=intent.base_importance,
        status="active",
        is_wellbeing=intent.is_wellbeing,
        created_at=utc_now(),
    )
    session.add(goal)
    session.commit()
    session.refresh(goal)
    for i, desc in enumerate(intent.initial_milestones):
        session.add(GoalMilestone(
            goal_id=goal.id,
            description=desc,
            status="pending",
            order_index=i,
        ))
    if intent.initial_milestones:
        session.commit()
    return goal


def apply_goal_intents(
    session: Session,
    user_id: int,
    intents: list[GoalUpdateIntent],
) -> None:
    """Create Goal rows for each intent in the list."""
    for intent in intents:
        create_goal_from_intent(session, user_id, intent)


def resolve_expired_short_term_goals(
    session: Session,
    user_id: int,
    *,
    max_age_hours: int = 24,
) -> int:
    """Mark active short_term goals older than max_age_hours as 'expired'.

    Called at the start of each cognition turn (before loading active goals) so
    stale session goals are closed before the current turn's context is built.
    Uses 'expired' — not 'abandoned' — to distinguish automatic expiry from
    explicit user abandonment. Returns the number of goals expired.
    """
    cutoff = utc_now() - timedelta(hours=max_age_hours)
    stale = session.exec(
        select(Goal).where(
            Goal.user_id == user_id,
            Goal.status == "active",
            Goal.scope == "short_term",
            Goal.created_at < cutoff,
        )
    ).all()
    if not stale:
        return 0
    for goal in stale:
        goal.status = "expired"
        session.add(goal)
    session.commit()
    return len(stale)


def resolve_short_term_goals_on_logout(
    session: Session,
    user_id: int,
) -> int:
    """Mark all active short_term goals as 'abandoned' on explicit user logout.

    Primary closure mechanism: fires immediately when the user logs out so goals
    are closed without waiting for the 24-hour TTL. Status 'abandoned' (not
    'expired') because a voluntary session end is semantically closer to
    abandonment than time-based expiry — we don't know whether the goals were
    achieved, so we do not mark them 'resolved'. Returns the count closed.
    """
    active = session.exec(
        select(Goal).where(
            Goal.user_id == user_id,
            Goal.status == "active",
            Goal.scope == "short_term",
        )
    ).all()
    if not active:
        return 0
    for goal in active:
        goal.status = "abandoned"
        session.add(goal)
    session.commit()
    return len(active)


def apply_milestone_updates(
    session: Session,
    user_id: int,
    updates: list[MilestoneIntent],
) -> None:
    """Apply Appraisal-suggested milestone additions and completions.

    add_milestone: creates a new GoalMilestone appended after existing ones
        (order_index = current count). The goal must belong to user_id.
    complete:      marks an existing GoalMilestone as completed with a timestamp.
        The parent goal must belong to user_id (user isolation).
    Invalid or unowned targets are silently skipped.
    """
    changed = False
    for update in updates:
        if update.action == "add_milestone" and update.goal_id is not None and update.description:
            goal = session.exec(
                select(Goal).where(Goal.id == update.goal_id, Goal.user_id == user_id)
            ).first()
            if goal is None:
                continue
            existing = get_milestones_for_goal(session, update.goal_id)
            session.add(GoalMilestone(
                goal_id=update.goal_id,
                description=update.description,
                status="pending",
                order_index=len(existing),
            ))
            changed = True
        elif update.action == "complete" and update.milestone_id is not None:
            milestone = session.exec(
                select(GoalMilestone).where(GoalMilestone.id == update.milestone_id)
            ).first()
            if milestone is None:
                continue
            goal = session.exec(
                select(Goal).where(Goal.id == milestone.goal_id, Goal.user_id == user_id)
            ).first()
            if goal is None:
                continue
            milestone.status = "completed"
            milestone.completed_at = utc_now()
            session.add(milestone)
            changed = True
    if changed:
        session.commit()


def apply_goal_state_changes(
    session: Session,
    user_id: int,
    changes: list[GoalStateChange],
) -> None:
    """Apply Appraisal-suggested status transitions to active Goal rows.

    Only goals currently in "active" status are affected — this guards against
    double-resolving a goal that was already closed in the same turn or previously.
    Goals belonging to a different user_id are silently ignored (user isolation).
    resolved_at is set only for "resolved" transitions; abandoned goals leave it None.
    """
    changed = False
    for change in changes:
        goal = session.exec(
            select(Goal).where(Goal.id == change.goal_id, Goal.user_id == user_id)
        ).first()
        if goal is None or goal.status != "active":
            continue
        goal.status = change.new_status
        if change.new_status == "resolved":
            goal.resolved_at = utc_now()
        session.add(goal)
        changed = True
    if changed:
        session.commit()


def build_active_goals_block(
    active_goals: list[Goal],
    appraisal: AppraisalResult,
    tone: str,
) -> str:
    """Build a goals context block for injection into the Expression system prompt.

    Scores each active goal using compute_effective_priority, keeps only those
    at or above _MIN_PRIORITY_THRESHOLD, caps at _MAX_GOALS_IN_BLOCK, and formats
    them as a short, readable block. Returns empty string if nothing qualifies.
    """
    if not active_goals:
        return ""

    relevance_map: dict[int, float] = {
        gr.goal_id: gr.relevance for gr in appraisal.goal_relevance
    }

    scored: list[tuple[float, Goal]] = []
    for goal in active_goals:
        if goal.id is None:
            continue
        relevance_boost = relevance_map.get(goal.id, 0.0)
        priority = compute_effective_priority(
            base_importance=goal.base_importance,
            relevance_boost=relevance_boost,
            tone=tone,
            is_wellbeing=goal.is_wellbeing,
        )
        if priority >= _MIN_PRIORITY_THRESHOLD:
            scored.append((priority, goal))

    if not scored:
        return ""

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:_MAX_GOALS_IN_BLOCK]

    lines = ["METAS ACTIVAS DEL USUARIO (considera estas en tu respuesta):"]
    for priority, goal in top:
        scope_label = "corto plazo" if goal.scope == "short_term" else "largo plazo"
        wellbeing_note = " [bienestar]" if goal.is_wellbeing else ""
        lines.append(
            f"- [{scope_label}{wellbeing_note}] {goal.description} (prioridad: {priority:.2f})"
        )
    return "\n".join(lines)
