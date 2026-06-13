"""Telegram configuration model and pure helpers."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class TelegramConfig:
    enabled: bool
    allowed_chat_ids: list[int]
    rate_limit_per_minute: int
    log_incoming: bool
    log_outgoing: bool


def load_telegram_config(config_path: Path) -> TelegramConfig:
    with config_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    tg = raw.get("telegram", {})
    return TelegramConfig(
        enabled=bool(tg.get("enabled", False)),
        allowed_chat_ids=[int(c) for c in tg.get("allowed_chat_ids", [])],
        rate_limit_per_minute=int(tg.get("rate_limit_per_minute", 10)),
        log_incoming=bool(tg.get("log_incoming", True)),
        log_outgoing=bool(tg.get("log_outgoing", True)),
    )


def is_rate_limited(
    buckets: dict[int, deque[float]],
    chat_id: int,
    limit: int,
) -> bool:
    """Return True if chat_id has sent ≥ limit messages in the last 60 seconds.

    Appends the current timestamp when NOT limited so the counter advances.
    """
    now = time.monotonic()
    dq = buckets[chat_id]
    while dq and now - dq[0] > 60.0:
        dq.popleft()
    if len(dq) >= limit:
        return True
    dq.append(now)
    return False
