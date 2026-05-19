import json
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Any

from sqlmodel import Session, select

from app.memory.models import ChatMessage, PendingAction, utc_now
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

    def _get_active_pending_actions(self) -> list[PendingAction]:
        statement = select(PendingAction).where(PendingAction.status == "pending")
        actions = list(self.session.exec(statement))

        now = ensure_aware_utc(utc_now())
        active_actions: list[PendingAction] = []

        for action in actions:
            expires_at = ensure_aware_utc(action.expires_at)

            if expires_at < now:
                action.status = "expired"
                self.session.add(action)
                continue

            active_actions.append(action)

        self.session.commit()
        return active_actions

    def extract_action_id_from_message(self, message: str) -> str | None:
        match = re.search(r"\bact_[a-fA-F0-9]{8}\b", message.strip())
        if not match:
            return None
        return match.group(0).lower()

    def find_action_by_id(self, action_id: str) -> PendingAction | None:
        statement = select(PendingAction).where(PendingAction.id == action_id)
        return self.session.exec(statement).first()

    def find_equivalent_pending_action(
        self,
        *,
        action_type: str,
        payload: dict,
    ) -> PendingAction | None:
        active_actions = self._get_active_pending_actions()

        for action in active_actions:
            if action.action_type != action_type:
                continue

            try:
                existing_payload = json.loads(action.payload_json)
            except json.JSONDecodeError:
                continue

            if existing_payload == payload:
                return action

        return None

    def find_pending_action_by_confirmation(self, message: str) -> PendingAction | None:
        normalized = message.strip().lower()
        for action in self._get_active_pending_actions():
            if normalized == action.confirmation_phrase.lower():
                return action
        return None

    def find_pending_action_by_context(self, message: str) -> PendingAction | None:
        normalized = message.strip().lower()
        active_actions = self._get_active_pending_actions()

        if not active_actions:
            return None

        has_confirmation_intent = (
            self._is_clear_confirmation(normalized)
            or self._has_confirmation_intent(normalized)
        )

        if not has_confirmation_intent:
            return None

        if len(active_actions) == 1 and self._is_clear_confirmation(normalized):
            action = active_actions[0]
            if self._last_sity_message_references_action(action.id):
                return action

        return None

    def _last_sity_message_references_action(self, action_id: str) -> bool:
        statement = (
            select(ChatMessage)
            .where(ChatMessage.session_id == "default")
            .where(ChatMessage.role == "sity")
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
        last_message = self.session.exec(statement).first()
        if not last_message:
            return False
        return action_id in (last_message.text or "")

    def has_multiple_active_pending_actions(self) -> bool:
        return len(self._get_active_pending_actions()) > 1

    def is_generic_confirmation_message(self, message: str) -> bool:
        return self._is_clear_confirmation(message.strip().lower())

    def _is_clear_confirmation(self, normalized: str) -> bool:
        confirmation_terms = [
            "si",
            "sí",
            "ok",
            "vale",
            "dale",
            "adelante",
            "ejecuta",
            "hazlo",
            "confirmo",
            "confirmado",
            "sí, hazlo",
            "si, hazlo",
            "sí, ejecuta",
            "si, ejecuta",
            "vale, hazlo",
            "ok, hazlo",
        ]
        return normalized in confirmation_terms

    def _has_confirmation_intent(self, normalized: str) -> bool:
        confirmation_patterns = [
            r"(^|\W)sí(\W|$)",
            r"(^|\W)si(\W|$)",
            r"(^|\W)ok(\W|$)",
            r"(^|\W)vale(\W|$)",
            r"(^|\W)dale(\W|$)",
            r"(^|\W)adelante(\W|$)",
            r"(^|\W)confirmo(\W|$)",
            r"(^|\W)confirmado(\W|$)",
            r"(^|\W)ejecuta(\W|$)",
            r"(^|\W)hazlo(\W|$)",
        ]

        return any(re.search(pattern, normalized) for pattern in confirmation_patterns)

    def _message_matches_action(self, normalized: str, action: PendingAction) -> bool:
        if not self._has_confirmation_intent(normalized):
            return False

        return self._is_clear_confirmation(normalized)

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
