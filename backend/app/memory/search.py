"""Full-text search over the conversation timeline using SQLite FTS5."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import text as sa_text

from app.chat.prompt_context import is_operational_guard_message
from app.memory.db import engine

log = logging.getLogger(__name__)

_FTS_READY: bool = False


@dataclass
class MessageContext:
    role: str
    text: str
    created_at: Optional[datetime]


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

            # Populate FTS if empty but chatmessage has rows (first-run or missing rebuild)
            fts_count = conn.execute(
                sa_text("SELECT COUNT(*) FROM chatmessage_fts")
            ).scalar() or 0
            msg_count = conn.execute(
                sa_text("SELECT COUNT(*) FROM chatmessage")
            ).scalar() or 0
            if fts_count == 0 and msg_count > 0:
                conn.execute(
                    sa_text("INSERT INTO chatmessage_fts(chatmessage_fts) VALUES ('rebuild')")
                )
                conn.commit()
                log.info("FTS5 chatmessage_fts rebuilt with %d messages", msg_count)

        _FTS_READY = True
        return True
    except Exception as exc:
        log.warning("FTS5 not available, will fall back to LIKE: %s", exc)
        return False


def _search_fts(conn, query: str, limit: int) -> list:
    fts_query = '"' + query.replace('"', " ") + '"'
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


def _search_like(conn, query: str, limit: int) -> list:
    return conn.execute(
        sa_text(
            "SELECT id, role, text, created_at FROM chatmessage "
            "WHERE text LIKE :q ORDER BY id DESC LIMIT :n"
        ),
        {"q": f"%{query}%", "n": limit},
    ).fetchall()


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


def search_conversation_history(query: str, limit: int = 5) -> list[SearchResult]:
    """Search conversation history using FTS5 (falls back to LIKE).

    Returns up to `limit` results, each with prev/next message context.
    Operational guard messages are filtered from results.
    """
    query = (query or "").strip()
    if not query:
        return []

    use_fts = _setup_fts()
    # Oversample to compensate for filtered operational messages
    fetch_n = min(limit * 3, 60)

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
            rows = _search_like(conn, query, fetch_n)

        for row in rows:
            msg_id, role, text, created_at = row[0], row[1], row[2], row[3]
            if msg_id in seen_ids or _is_operational(role, text):
                continue
            seen_ids.add(msg_id)

            prev_row, next_row = _adjacent(conn, msg_id)

            results.append(SearchResult(
                match=MessageContext(role=role, text=text, created_at=_parse_dt(created_at)),
                prev=MessageContext(
                    role=prev_row[0], text=prev_row[1], created_at=_parse_dt(prev_row[2])
                ) if prev_row else None,
                next=MessageContext(
                    role=next_row[0], text=next_row[1], created_at=_parse_dt(next_row[2])
                ) if next_row else None,
            ))
            if len(results) >= limit:
                break

    return results
