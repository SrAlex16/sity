"""NotificationFact — the unit of work the dispatcher accepts.

Detectors (timers, job_manager, initiative_runner, etc.) produce a
NotificationFact and hand it to dispatcher.dispatch(). The dispatcher
decides whether to send it, and via which channel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NotificationFact:
    """Describes something that happened and should potentially notify the user.

    fact_id must be unique and stable for the same real-world event so the
    dispatcher can deduplicate: e.g. "timer:{task_id}" or "bg:{job_id}".
    payload is what the user sees: {"title": ..., "body": ..., "url": ..., "urgent": bool}.
    """
    session_id: str
    notification_type: str  # timer_fired | background_result | external_event | recurrent_task | proactive_initiative
    fact_id: str
    payload: dict = field(default_factory=dict)
    urgency: str = "medium"  # high | medium | low
    subtype: Optional[str] = None  # e.g. "web_search", "gmail_new_message"


@dataclass
class DispatchResult:
    discarded: bool = False
    reason: Optional[str] = None  # "duplicate" | "rate_limited:..." | "guest_no_sse"
    channel: Optional[str] = None  # "sse" | "push" | "pending" — None when discarded
    notification_id: Optional[int] = None
