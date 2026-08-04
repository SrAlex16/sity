"""Tests for UserIntegration model and the fail-fast encryption key check.

Coverage:
  - UserIntegration table created by init_db / create_all
  - UniqueConstraint (user_id, provider) prevents duplicate active integrations
  - _verify_encryption_key: empty table → ok; correct key → ok; wrong key → RuntimeError
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.encryption import encrypt_str
from app.memory.db import _verify_encryption_key
from app.memory.models import UserIntegration


# ---------------------------------------------------------------------------
# Shared in-memory engine for model/constraint tests
# (isolated from the shared pytest test DB to avoid cross-test pollution)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mem_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _row(user_id: int = 1, provider: str = "spotify") -> UserIntegration:
    return UserIntegration(
        user_id=user_id,
        provider=provider,
        encrypted_credentials="placeholder",
        scopes="user-read-currently-playing",
        connected_at=_utc_now(),
    )


# ---------------------------------------------------------------------------
# Table creation and basic CRUD
# ---------------------------------------------------------------------------

class TestUserIntegrationModel:
    def test_table_exists(self, mem_engine) -> None:
        with Session(mem_engine) as session:
            result = session.exec(select(UserIntegration)).all()
        assert isinstance(result, list)

    def test_insert_and_retrieve(self, mem_engine) -> None:
        with Session(mem_engine) as session:
            row = _row(user_id=10, provider="google")
            session.add(row)
            session.commit()
            session.refresh(row)
            assert row.id is not None
            assert row.is_active is True
            assert row.last_refreshed_at is None

    def test_is_active_defaults_true(self, mem_engine) -> None:
        with Session(mem_engine) as session:
            row = _row(user_id=11, provider="google")
            session.add(row)
            session.commit()
            session.refresh(row)
        assert row.is_active is True

    def test_soft_delete_sets_is_active_false(self, mem_engine) -> None:
        with Session(mem_engine) as session:
            row = _row(user_id=12, provider="spotify")
            session.add(row)
            session.commit()
            session.refresh(row)
            row.is_active = False
            session.add(row)
            session.commit()
            session.refresh(row)
        assert row.is_active is False


# ---------------------------------------------------------------------------
# UniqueConstraint (user_id, provider)
# ---------------------------------------------------------------------------

class TestUniqueConstraint:
    def test_duplicate_user_provider_raises(self, mem_engine) -> None:
        with Session(mem_engine) as session:
            session.add(_row(user_id=20, provider="google"))
            session.commit()

        with pytest.raises(IntegrityError):
            with Session(mem_engine) as session:
                session.add(_row(user_id=20, provider="google"))
                session.commit()

    def test_same_user_different_provider_allowed(self, mem_engine) -> None:
        with Session(mem_engine) as session:
            session.add(_row(user_id=21, provider="google"))
            session.add(_row(user_id=21, provider="spotify"))
            session.commit()
        # No exception raised

    def test_same_provider_different_user_allowed(self, mem_engine) -> None:
        with Session(mem_engine) as session:
            session.add(_row(user_id=22, provider="google"))
            session.add(_row(user_id=23, provider="google"))
            session.commit()
        # No exception raised


# ---------------------------------------------------------------------------
# _verify_encryption_key fail-fast check
# ---------------------------------------------------------------------------

@pytest.fixture()
def verify_engine(monkeypatch: pytest.MonkeyPatch):
    """Fresh in-memory engine for each encryption-key test to avoid state leaks."""
    good_key = Fernet.generate_key().decode()
    monkeypatch.setenv("SITY_ENCRYPTION_KEY", good_key)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine, good_key


class TestVerifyEncryptionKey:
    def test_empty_table_passes(self, verify_engine) -> None:
        engine, _ = verify_engine
        with Session(engine) as session:
            _verify_encryption_key(session)  # must not raise

    def test_correct_key_passes(self, verify_engine, monkeypatch: pytest.MonkeyPatch) -> None:
        engine, good_key = verify_engine
        monkeypatch.setenv("SITY_ENCRYPTION_KEY", good_key)
        ciphertext = encrypt_str('{"access_token": "tok_abc"}')
        with Session(engine) as session:
            row = UserIntegration(
                user_id=1, provider="spotify",
                encrypted_credentials=ciphertext,
                scopes="user-read-currently-playing",
                connected_at=_utc_now(),
            )
            session.add(row)
            session.commit()
        with Session(engine) as session:
            _verify_encryption_key(session)  # must not raise

    def test_wrong_key_raises_runtime_error(
        self, verify_engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine, good_key = verify_engine
        monkeypatch.setenv("SITY_ENCRYPTION_KEY", good_key)
        ciphertext = encrypt_str('{"access_token": "tok_abc"}')
        with Session(engine) as session:
            row = UserIntegration(
                user_id=1, provider="google",
                encrypted_credentials=ciphertext,
                scopes="https://www.googleapis.com/auth/gmail.readonly",
                connected_at=_utc_now(),
            )
            session.add(row)
            session.commit()

        # Rotate to a different key — should block startup
        wrong_key = Fernet.generate_key().decode()
        monkeypatch.setenv("SITY_ENCRYPTION_KEY", wrong_key)

        with Session(engine) as session:
            with pytest.raises(RuntimeError, match="SITY_ENCRYPTION_KEY"):
                _verify_encryption_key(session)

    def test_wrong_key_error_message_is_actionable(
        self, verify_engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine, good_key = verify_engine
        monkeypatch.setenv("SITY_ENCRYPTION_KEY", good_key)
        ciphertext = encrypt_str("secret")
        with Session(engine) as session:
            row = UserIntegration(
                user_id=2, provider="spotify",
                encrypted_credentials=ciphertext,
                scopes="user-read-currently-playing",
                connected_at=_utc_now(),
            )
            session.add(row)
            session.commit()

        monkeypatch.setenv("SITY_ENCRYPTION_KEY", Fernet.generate_key().decode())

        with Session(engine) as session:
            with pytest.raises(RuntimeError, match="revisa el .env"):
                _verify_encryption_key(session)
