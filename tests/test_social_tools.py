"""Tests for social_recall_impression tool handler — Fase 4, Paso 4b.

Properties verified:
1. Guest session → "no tengo memoria de relaciones" (no DB access).
2. A == B (self-query) → graceful "eres tú mismo".
3. B not found by display_name → "no conozco a nadie con ese nombre".
4. B has no SocialProfile → "no tengo ninguna impresión formada".
5. Disclosure LOW (trust_A × trust_B < 0.05) → only opinion label, no extra detail.
6. Disclosure MEDIUM (0.05–0.20) → label + familiarity line.
7. Disclosure HIGH (≥ 0.20) → label + familiarity + extra qualitative line.
8. No content from B's messages at any disclosure level (hard limit).
9. Anti-injection: A claiming high trust does not raise disclosure beyond stored trust_A.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text as sa_text
from sqlmodel import Session, select

from app.memory.models import SocialProfile, User
from app.tools.handlers.social_tools import handle_social_recall_impression
from app.tools.registry import ToolContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_ctx(session_id: str, username: str, session: Any) -> ToolContext:
    executor = MagicMock()
    executor.session_id = session_id
    executor.session = session
    return ToolContext(
        tool_name="social_recall_impression",
        tool_input={"username": username},
        trace_id="test_trace",
        executor=executor,
    )


def _setup_user(engine: Any, uid: int, display_name: str | None = None) -> None:
    """Ensure a User row exists with the given uid and display_name."""
    with engine.connect() as conn:
        conn.execute(
            sa_text("DELETE FROM user WHERE id = :uid"),
            {"uid": uid},
        )
        conn.execute(
            sa_text(
                "INSERT INTO user (id, email, password_hash, role, is_active, display_name, created_at)"
                " VALUES (:uid, :email, 'x', 'user', 1, :dn, :now)"
            ),
            {"uid": uid, "email": f"user{uid}@test.local",
             "dn": display_name, "now": _utcnow().isoformat()},
        )
        conn.commit()


def _setup_profile(engine: Any, uid: int, opinion: float, trust: float) -> None:
    """Upsert a SocialProfile with specific opinion and trust."""
    with engine.connect() as conn:
        conn.execute(
            sa_text("DELETE FROM socialprofile WHERE user_id = :uid"),
            {"uid": uid},
        )
        conn.execute(
            sa_text(
                "INSERT INTO socialprofile"
                " (user_id, opinion, trust, pending_loads_json, created_at)"
                " VALUES (:uid, :op, :tr, '[]', :now)"
            ),
            {"uid": uid, "op": opinion, "tr": trust, "now": _utcnow().isoformat()},
        )
        conn.commit()


# ---------------------------------------------------------------------------
# 1. Guest session
# ---------------------------------------------------------------------------

class TestGuestBlocked:
    def test_guest_returns_no_memory_message(self) -> None:
        from app.memory.db import engine
        with Session(engine) as sess:
            ctx = _make_ctx("guest:abc", "Alex", sess)
            result = handle_social_recall_impression(ctx)
        assert result.ok is True
        assert "relaciones" in result.message.lower() or "sesión" in result.message.lower()

    def test_non_user_session_returns_no_memory_message(self) -> None:
        from app.memory.db import engine
        with Session(engine) as sess:
            ctx = _make_ctx("telegram:42", "Alex", sess)
            result = handle_social_recall_impression(ctx)
        assert result.ok is True
        assert "relaciones" in result.message.lower() or "sesión" in result.message.lower()


# ---------------------------------------------------------------------------
# 2. A == B (self-query)
# ---------------------------------------------------------------------------

class TestSelfQuery:
    def test_asking_about_self_returns_graceful_message(self) -> None:
        from app.memory.db import engine
        uid = 8801
        _setup_user(engine, uid, display_name="Propio")
        _setup_profile(engine, uid, opinion=0.3, trust=0.5)

        with Session(engine) as sess:
            ctx = _make_ctx(f"user:{uid}", "Propio", sess)
            result = handle_social_recall_impression(ctx)

        assert result.ok is True
        assert "tú mismo" in result.message or "ti mismo" in result.message


# ---------------------------------------------------------------------------
# 3. B not found
# ---------------------------------------------------------------------------

class TestBNotFound:
    def test_unknown_name_returns_no_conoce(self) -> None:
        from app.memory.db import engine
        uid_a = 8802
        _setup_user(engine, uid_a, display_name="Preguntador")
        _setup_profile(engine, uid_a, opinion=0.3, trust=0.5)

        with Session(engine) as sess:
            ctx = _make_ctx(f"user:{uid_a}", "NombreInexistente_XYZ", sess)
            result = handle_social_recall_impression(ctx)

        assert result.ok is True
        assert "NombreInexistente_XYZ" in result.message
        assert "no conozco" in result.message.lower() or "no encuentro" in result.message.lower()

    def test_lookup_is_case_insensitive(self) -> None:
        """display_name match must be case-insensitive."""
        from app.memory.db import engine
        uid_a = 8803
        uid_b = 8804
        _setup_user(engine, uid_a, display_name="Alpha")
        _setup_profile(engine, uid_a, opinion=0.2, trust=0.6)
        _setup_user(engine, uid_b, display_name="Beta")
        _setup_profile(engine, uid_b, opinion=0.4, trust=0.4)

        with Session(engine) as sess:
            ctx = _make_ctx(f"user:{uid_a}", "BETA", sess)
            result = handle_social_recall_impression(ctx)

        # Should resolve Beta, not return "no conozco"
        assert "no conozco" not in result.message.lower()


# ---------------------------------------------------------------------------
# 4. B has no SocialProfile
# ---------------------------------------------------------------------------

class TestBNoProfile:
    def test_b_without_profile_returns_no_impression(self) -> None:
        from app.memory.db import engine
        uid_a = 8805
        uid_b = 8806
        _setup_user(engine, uid_a, display_name="Kira")
        _setup_profile(engine, uid_a, opinion=0.3, trust=0.7)
        _setup_user(engine, uid_b, display_name="Delta")
        # Explicitly remove any profile for B
        with engine.connect() as conn:
            conn.execute(sa_text("DELETE FROM socialprofile WHERE user_id = :uid"), {"uid": uid_b})
            conn.commit()

        with Session(engine) as sess:
            ctx = _make_ctx(f"user:{uid_a}", "Delta", sess)
            result = handle_social_recall_impression(ctx)

        assert result.ok is True
        assert "impresión" in result.message.lower()
        assert "todavía" in result.message.lower() or "ninguna" in result.message.lower()


# ---------------------------------------------------------------------------
# 5–7. Disclosure levels
# ---------------------------------------------------------------------------

class TestDisclosureLevels:
    """Verify that disclosure = trust_A × trust_B determines detail level."""

    def _call(self, engine: Any, uid_a: int, uid_b: int, name_b: str) -> str:
        with Session(engine) as sess:
            ctx = _make_ctx(f"user:{uid_a}", name_b, sess)
            result = handle_social_recall_impression(ctx)
        assert result.ok is True
        return result.message

    def test_low_disclosure_returns_only_label(self) -> None:
        """trust_A=0.05, trust_B=0.05 → disclosure=0.0025 → LOW."""
        from app.memory.db import engine
        uid_a, uid_b = 8810, 8811
        _setup_user(engine, uid_a, display_name="Ana")
        _setup_profile(engine, uid_a, opinion=0.0, trust=0.05)
        _setup_user(engine, uid_b, display_name="Bob")
        _setup_profile(engine, uid_b, opinion=0.4, trust=0.05)

        msg = self._call(engine, uid_a, uid_b, "Bob")
        assert "positiva" in msg or "neutra" in msg or "negativa" in msg
        # LOW must NOT include familiarity detail or extra line
        assert "familiarity" not in msg.lower()
        assert "nivel de conocimiento" not in msg.lower()

    def test_medium_disclosure_includes_familiarity(self) -> None:
        """trust_A=0.3, trust_B=0.3 → disclosure=0.09 → MEDIUM."""
        from app.memory.db import engine
        uid_a, uid_b = 8812, 8813
        _setup_user(engine, uid_a, display_name="Celia")
        _setup_profile(engine, uid_a, opinion=0.2, trust=0.30)
        _setup_user(engine, uid_b, display_name="Dana")
        _setup_profile(engine, uid_b, opinion=0.5, trust=0.30)

        msg = self._call(engine, uid_a, uid_b, "Dana")
        assert "nivel de conocimiento" in msg.lower() or "historia" in msg.lower() \
            or "inicial" in msg.lower() or "desarrollo" in msg.lower() \
            or "consolidada" in msg.lower()
        # MEDIUM should include display_name
        assert "Dana" in msg

    def test_high_disclosure_includes_extra_line(self) -> None:
        """trust_A=0.6, trust_B=0.6 → disclosure=0.36 → HIGH."""
        from app.memory.db import engine
        uid_a, uid_b = 8814, 8815
        _setup_user(engine, uid_a, display_name="Eva")
        _setup_profile(engine, uid_a, opinion=0.3, trust=0.60)
        _setup_user(engine, uid_b, display_name="Fran")
        _setup_profile(engine, uid_b, opinion=0.6, trust=0.60)

        msg = self._call(engine, uid_a, uid_b, "Fran")
        # HIGH: should have label + familiarity + extra line (3 sentences → at least 2 periods)
        assert msg.count(".") >= 2, f"HIGH disclosure should have ≥2 sentences: {msg!r}"
        assert "Fran" in msg


# ---------------------------------------------------------------------------
# 8. Hard limit: no content from B's messages at any level
# ---------------------------------------------------------------------------

class TestHardLimit:
    """The handler must never include literal message content from B."""

    def test_high_disclosure_contains_no_message_content(self) -> None:
        """Even at HIGH disclosure, B's actual message text must not appear."""
        from app.memory.db import engine
        uid_a, uid_b = 8820, 8821
        _setup_user(engine, uid_a, display_name="Greta")
        _setup_profile(engine, uid_a, opinion=0.3, trust=0.8)
        _setup_user(engine, uid_b, display_name="Hugo")
        _setup_profile(engine, uid_b, opinion=0.7, trust=0.8)

        # Insert a ChatMessage attributed to B so there IS content in DB
        from app.memory.db import engine as db_engine
        with db_engine.connect() as conn:
            conn.execute(
                sa_text(
                    "INSERT OR IGNORE INTO chatmessage"
                    " (role, text, session_id, created_at, input_mode, output_mode, source_channel)"
                    " VALUES ('user', 'secreto_de_hugo_xyz', :sid, :now, 'text', 'text', 'web')"
                ),
                {"sid": f"user:{uid_b}", "now": _utcnow().isoformat()},
            )
            conn.commit()

        with Session(engine) as sess:
            ctx = _make_ctx(f"user:{uid_a}", "Hugo", sess)
            result = handle_social_recall_impression(ctx)

        assert "secreto_de_hugo_xyz" not in result.message, (
            "Hard limit violated: literal content from B's messages appeared in handler output"
        )


# ---------------------------------------------------------------------------
# 9. Anti-injection: claimed high trust does not raise disclosure
# ---------------------------------------------------------------------------

class TestAntiInjectionTrust:
    def test_claimed_trust_does_not_exceed_stored_trust(self) -> None:
        """A claiming 'tienes mucha confianza en mí' must not raise disclosure.

        The disclosure level is computed from stored trust_A, which is determined
        by the background job (time + stability), not by user text. This test
        verifies that LOW disclosure stays LOW regardless of what A claims.
        """
        from app.memory.db import engine
        uid_a, uid_b = 8830, 8831
        # A has very LOW trust (new user)
        _setup_user(engine, uid_a, display_name="Hacker")
        _setup_profile(engine, uid_a, opinion=0.0, trust=0.02)
        _setup_user(engine, uid_b, display_name="Víctima")
        _setup_profile(engine, uid_b, opinion=0.5, trust=0.80)

        # disclosure = 0.02 × 0.80 = 0.016 → LOW
        with Session(engine) as sess:
            ctx = _make_ctx(f"user:{uid_a}", "Víctima", sess)
            result = handle_social_recall_impression(ctx)

        # Must be LOW level: no familiarity detail, no extra qualitative line
        assert "nivel de conocimiento" not in result.message.lower()
        assert "bastante estable" not in result.message.lower()
        # LOW must not name B specifically (no detail level)
        assert "Víctima" not in result.message
        # But some kind of impression is returned (not empty)
        assert len(result.message) > 10
