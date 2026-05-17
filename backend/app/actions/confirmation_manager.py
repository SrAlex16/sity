import json
import secrets
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Any

from sqlmodel import Session, select

from app.memory.models import PendingAction, utc_now
from app.trace.logger import write_log


def ensure_aware_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass
class CreatedPendingAction:
    id: str
    confirmation_phrase: str
    summary: str
    risk_level: str


class ConfirmationManager:
    def __init__(self, session: Session):
        self.session = session

    def create_pending_action(
        self,
        *,
        action_type: str,
        risk_level: str,
        summary: str,
        payload: dict[str, Any],
        trace_id: str,
        ttl_minutes: int = 15,
    ) -> CreatedPendingAction:
        action_id = f"act_{secrets.token_hex(4)}"
        confirmation_phrase = f"confirmo ejecutar {action_id}"

        action = PendingAction(
            id=action_id,
            action_type=action_type,
            risk_level=risk_level,
            status="pending",
            summary=summary,
            payload_json=json.dumps(payload, ensure_ascii=False),
            confirmation_phrase=confirmation_phrase,
            created_at=utc_now(),
            expires_at=utc_now() + timedelta(minutes=ttl_minutes),
            trace_id=trace_id,
        )

        self.session.add(action)
        self.session.commit()

        write_log(
            level="AUDIT",
            module="actions",
            event="pending_action_created",
            trace_id=trace_id,
            payload={
                "action_id": action_id,
                "action_type": action_type,
                "risk_level": risk_level,
                "summary": summary,
                "payload": payload,
                "expires_at": action.expires_at.isoformat(),
            },
            audit=True,
        )

        return CreatedPendingAction(
            id=action_id,
            confirmation_phrase=confirmation_phrase,
            summary=summary,
            risk_level=risk_level,
        )

    def find_pending_action_by_confirmation(self, message: str) -> PendingAction | None:
        normalized = message.strip().lower()

        statement = select(PendingAction).where(PendingAction.status == "pending")
        actions = list(self.session.exec(statement))

        now = ensure_aware_utc(utc_now())

        for action in actions:
            expires_at = ensure_aware_utc(action.expires_at)

            if expires_at < now:
                action.status = "expired"
                self.session.add(action)
                continue

            if normalized == action.confirmation_phrase.lower():
                self.session.commit()
                return action

        self.session.commit()
        return None

    def mark_executed(self, action: PendingAction, trace_id: str) -> None:
        action.status = "executed"
        action.executed_at = utc_now()
        self.session.add(action)
        self.session.commit()

        write_log(
            level="AUDIT",
            module="actions",
            event="pending_action_executed",
            trace_id=trace_id,
            payload={
                "action_id": action.id,
                "action_type": action.action_type,
                "risk_level": action.risk_level,
            },
            audit=True,
        )

    def mark_failed(self, action: PendingAction, trace_id: str, error: str) -> None:
        action.status = "failed"
        self.session.add(action)
        self.session.commit()

        write_log(
            level="ERROR",
            module="actions",
            event="pending_action_failed",
            trace_id=trace_id,
            payload={
                "action_id": action.id,
                "action_type": action.action_type,
                "risk_level": action.risk_level,
                "error": error,
            },
            audit=True,
        )
