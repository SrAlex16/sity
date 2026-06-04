"""Full-text search over the conversation timeline using SQLite FTS5."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import text as sa_text

from app.chat.prompt_context import is_operational_guard_message
from app.memory.db import engine

log = logging.getLogger(__name__)

_FTS_READY: bool = False

_MAX_TEXT_CHARS = 1000
_LIMIT_MIN = 1
_LIMIT_MAX = 10
_LIMIT_DEFAULT = 5


@dataclass
class MessageContext:
    role: str
    text: str
    created_at: Optional[datetime]
    message_id: Optional[int] = None


@dataclass
class SearchResult:
    match: MessageContext
    prev: Optional[MessageContext]
    next: Optional[MessageContext]


def _parse_dt(value: object) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _is_operational(role: str, text: str) -> bool:
    return role == "sity" and is_operational_guard_message(text)


def _truncate(text: str) -> str:
    if len(text) <= _MAX_TEXT_CHARS:
        return text
    return text[:_MAX_TEXT_CHARS] + "…"


def _make_ctx(row: Optional[tuple]) -> Optional[MessageContext]:
    """Build MessageContext from a DB row; returns None for operational messages."""
    if row is None:
        return None
    role, text, created_at = row[0], row[1], row[2]
    if _is_operational(role, text):
        return None
    return MessageContext(role=role, text=_truncate(text), created_at=_parse_dt(created_at))


def _setup_fts() -> bool:
    """Create FTS5 virtual table + triggers if not present. Returns True if FTS5 available."""
    global _FTS_READY
    if _FTS_READY:
        return True

    try:
        with engine.connect() as conn:
            conn.execute(sa_text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chatmessage_fts "
                "USING fts5(text, content='chatmessage', content_rowid='id')"
            ))
            # Triggers keep FTS in sync with chatmessage for all future writes
            conn.execute(sa_text(
                "CREATE TRIGGER IF NOT EXISTS chatmessage_fts_ai "
                "AFTER INSERT ON chatmessage BEGIN "
                "  INSERT INTO chatmessage_fts(rowid, text) VALUES (new.id, new.text); "
                "END"
            ))
            conn.execute(sa_text(
                "CREATE TRIGGER IF NOT EXISTS chatmessage_fts_ad "
                "AFTER DELETE ON chatmessage BEGIN "
                "  INSERT INTO chatmessage_fts(chatmessage_fts, rowid, text) "
                "  VALUES ('delete', old.id, old.text); "
                "END"
            ))
            conn.execute(sa_text(
                "CREATE TRIGGER IF NOT EXISTS chatmessage_fts_au "
                "AFTER UPDATE ON chatmessage BEGIN "
                "  INSERT INTO chatmessage_fts(chatmessage_fts, rowid, text) "
                "  VALUES ('delete', old.id, old.text); "
                "  INSERT INTO chatmessage_fts(rowid, text) VALUES (new.id, new.text); "
                "END"
            ))
            conn.commit()

            # Always rebuild at startup: COUNT(*) on a content table reads from the source
            # table, not the FTS index — the index can be empty while COUNT returns non-zero.
            # Rebuild is idempotent and fast for our dataset size (~ms per 1k messages).
            conn.execute(
                sa_text("INSERT INTO chatmessage_fts(chatmessage_fts) VALUES ('rebuild')")
            )
            conn.commit()
            log.info("FTS5 chatmessage_fts rebuilt")

        _FTS_READY = True
        return True
    except Exception as exc:
        log.warning("FTS5 not available, will fall back to LIKE: %s", exc)
        return False


def _search_fts(conn, query: str, limit: int) -> list:
    # OR queries must not be quoted — quoting turns them into a phrase search
    fts_query = query if " OR " in query else '"' + query.replace('"', " ") + '"'
    return conn.execute(
        sa_text(
            "SELECT c.id, c.role, c.text, c.created_at "
            "FROM chatmessage_fts fts "
            "JOIN chatmessage c ON c.id = fts.rowid "
            "WHERE chatmessage_fts MATCH :q "
            "ORDER BY rank "
            "LIMIT :n"
        ),
        {"q": fts_query, "n": limit},
    ).fetchall()


def _search_like_tokens(conn, query: str, limit: int) -> list:
    """LIKE search per token — avoids treating the full OR-joined string as a phrase."""
    # Strip FTS boolean operators, then extract tokens of at least 3 chars
    clean = re.sub(r"\b(?:OR|AND|NOT)\b", " ", query)
    tokens = [t for t in clean.split() if len(t) >= 3]
    if not tokens:
        tokens = [query]

    seen_ids: set[int] = set()
    rows: list = []
    for token in tokens:
        for row in conn.execute(
            sa_text(
                "SELECT id, role, text, created_at FROM chatmessage "
                "WHERE text LIKE :q ORDER BY id DESC LIMIT :n"
            ),
            {"q": f"%{token}%", "n": limit},
        ).fetchall():
            if row[0] not in seen_ids:
                seen_ids.add(row[0])
                rows.append(row)
        if len(rows) >= limit:
            break
    return rows[:limit]


def _adjacent(conn, msg_id: int) -> tuple[Optional[tuple], Optional[tuple]]:
    prev = conn.execute(
        sa_text(
            "SELECT role, text, created_at FROM chatmessage "
            "WHERE id < :mid ORDER BY id DESC LIMIT 1"
        ),
        {"mid": msg_id},
    ).fetchone()
    nxt = conn.execute(
        sa_text(
            "SELECT role, text, created_at FROM chatmessage "
            "WHERE id > :mid ORDER BY id ASC LIMIT 1"
        ),
        {"mid": msg_id},
    ).fetchone()
    return prev, nxt


def search_conversation_history(query: str, limit: int = _LIMIT_DEFAULT) -> list[SearchResult]:
    """Search conversation history using FTS5 (falls back to LIKE per token).

    Returns up to `limit` results, each with prev/next message context.
    Operational guard messages are filtered from results and adjacents.
    Message text is truncated to _MAX_TEXT_CHARS characters.
    limit is clamped to [_LIMIT_MIN, _LIMIT_MAX].
    """
    query = (query or "").strip()
    if not query:
        return []

    limit = max(_LIMIT_MIN, min(limit, _LIMIT_MAX))
    use_fts = _setup_fts()
    # Oversample to compensate for filtered operational messages
    fetch_n = min(limit * 3, 30)

    results: list[SearchResult] = []
    seen_ids: set[int] = set()

    with engine.connect() as conn:
        rows: list = []
        if use_fts:
            try:
                rows = _search_fts(conn, query, fetch_n)
            except Exception as exc:
                log.warning("FTS5 query failed, falling back to LIKE: %s", exc)

        if not rows:
            rows = _search_like_tokens(conn, query, fetch_n)

        for row in rows:
            msg_id, role, text, created_at = row[0], row[1], row[2], row[3]
            if msg_id in seen_ids or _is_operational(role, text):
                continue
            seen_ids.add(msg_id)

            prev_row, next_row = _adjacent(conn, msg_id)

            results.append(SearchResult(
                match=MessageContext(
                    role=role,
                    text=_truncate(text),
                    created_at=_parse_dt(created_at),
                    message_id=msg_id,
                ),
                prev=_make_ctx(prev_row),
                next=_make_ctx(next_row),
            ))
            if len(results) >= limit:
                break

    return results
