"""Tests for file management Parts 5–8.

Part 5 — PUT /files/{id}/permanent:
  - Guest → 401
  - Not-owner → 404
  - Not-found → 404
  - Owner → ok, is_permanent=True, expires_at=None

Part 6 — image semantic extraction:
  - extract_image_semantic_facts skips when ANTHROPIC_API_KEY not set
  - extract_image_semantic_facts skips when artifact already semantic_extracted
  - extract_image_semantic_facts creates SemanticFact rows on success
  - extract_image_semantic_facts sets semantic_extracted=True on success
  - _parse_facts handles valid JSON, bad JSON, empty list
  - Never raises on any error

Part 7 — storage_alert:
  - maybe_send_storage_alert no-op when < 90%
  - maybe_send_storage_alert dispatches at >= 90%
  - maybe_send_storage_alert dispatches at >= 100% with 'full' level
  - Never raises

Part 8 — GET /files/storage-stats:
  - Guest → 401
  - User → returns used_bytes, limit_bytes, file_count, permanent_count
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.main import app
from app.memory.models import FileArtifact, SemanticFact
from helpers import make_user_token


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _mem_db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def _add_artifact(
    db: Session,
    *,
    user_id: int = 1,
    file_size_bytes: int = 100,
    is_permanent: bool = False,
    expires_at: datetime | None = None,
    semantic_extracted: bool = False,
) -> FileArtifact:
    fa = FileArtifact(
        user_id=user_id,
        artifact_type="image",
        filename=f"f_{int(time.monotonic()*1e9)}.jpg",
        rel_path="uploads/images/placeholder.jpg",
        mime_type="image/jpeg",
        source="chat_upload",
        file_size_bytes=file_size_bytes,
        is_permanent=is_permanent,
        expires_at=expires_at,
        semantic_extracted=semantic_extracted,
    )
    db.add(fa)
    db.commit()
    db.refresh(fa)
    return fa


# ---------------------------------------------------------------------------
# Part 5 — PUT /files/{id}/permanent
# ---------------------------------------------------------------------------

class TestMarkPermanentEndpoint:

    def test_guest_returns_401(self) -> None:
        with _client() as c:
            resp = c.put("/files/1/permanent")
        assert resp.status_code == 401

    def test_not_found_returns_404(self) -> None:
        token = make_user_token()
        with _client() as c:
            resp = c.put("/files/999999/permanent", cookies={"sity_session": token})
        assert resp.status_code == 404

    def test_owner_marks_permanent(self, db_session: Session) -> None:
        token = make_user_token()
        from app.auth.jwt_utils import decode_token
        payload = decode_token(token)
        assert payload is not None
        uid = int(payload["sub"])
        fa = _add_artifact(db_session, user_id=uid)
        assert fa.id is not None

        with _client() as c:
            resp = c.put(f"/files/{fa.id}/permanent", cookies={"sity_session": token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["is_permanent"] is True

        db_session.refresh(fa)
        assert fa.is_permanent is True
        assert fa.expires_at is None

    def test_other_user_returns_404(self, db_session: Session) -> None:
        fa = _add_artifact(db_session, user_id=9999)
        token = make_user_token()
        with _client() as c:
            resp = c.put(f"/files/{fa.id}/permanent", cookies={"sity_session": token})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Part 6 — image semantic extraction
# ---------------------------------------------------------------------------

class TestParseFacts:
    def test_valid_json(self) -> None:
        from app.chat.image_semantic_extractor import _parse_facts
        text = '{"facts": ["User lives in an urban environment", "User owns a cat"]}'
        result = _parse_facts(text)
        assert result == ["User lives in an urban environment", "User owns a cat"]

    def test_empty_facts(self) -> None:
        from app.chat.image_semantic_extractor import _parse_facts
        result = _parse_facts('{"facts": []}')
        assert result == []

    def test_bad_json_returns_empty(self) -> None:
        from app.chat.image_semantic_extractor import _parse_facts
        result = _parse_facts("not json at all")
        assert result == []

    def test_markdown_block_stripped(self) -> None:
        from app.chat.image_semantic_extractor import _parse_facts
        text = '```json\n{"facts": ["User is a developer"]}\n```'
        result = _parse_facts(text)
        assert result == ["User is a developer"]

    def test_max_3_facts(self) -> None:
        from app.chat.image_semantic_extractor import _parse_facts
        text = '{"facts": ["A", "B", "C", "D", "E"]}'
        result = _parse_facts(text)
        assert len(result) == 3

    def test_long_fact_clamped_to_200(self) -> None:
        from app.chat.image_semantic_extractor import _parse_facts
        long = "x" * 300
        text = f'{{"facts": ["{long}"]}}'
        result = _parse_facts(text)
        assert len(result) == 1
        assert len(result[0]) == 200


class TestExtractImageSemanticFacts:
    def test_skips_when_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # Should return immediately without calling any provider
        with patch("app.cortex.providers.factory.build_ai_provider") as mock_p:
            from app.chat.image_semantic_extractor import extract_image_semantic_facts
            extract_image_semantic_facts("b64data", "image/jpeg", user_id=1, artifact_id=1)
        mock_p.assert_not_called()

    def test_skips_already_extracted(self) -> None:
        eng = _mem_db()
        with Session(eng) as db:
            fa = _add_artifact(db, user_id=1, semantic_extracted=True)
        with patch("app.chat.image_semantic_extractor.engine", eng), \
             patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}), \
             patch("app.cortex.providers.factory.build_ai_provider") as mock_p:
            from app.chat.image_semantic_extractor import extract_image_semantic_facts
            extract_image_semantic_facts("b64", "image/jpeg", user_id=1, artifact_id=fa.id)
        mock_p.assert_not_called()

    def test_creates_semantic_facts_on_success(self) -> None:
        from sqlmodel import select as sq_select
        eng = _mem_db()
        with Session(eng) as db:
            fa = _add_artifact(db, user_id=1, semantic_extracted=False)
            artifact_id = fa.id

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.text = '{"facts": ["User is a software developer", "User works from home"]}'
        mock_provider = MagicMock()
        mock_provider.generate.return_value = mock_response

        with patch("app.chat.image_semantic_extractor.engine", eng), \
             patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}), \
             patch("app.cortex.providers.factory.build_ai_provider", return_value=mock_provider):
            from app.chat.image_semantic_extractor import extract_image_semantic_facts
            extract_image_semantic_facts("b64", "image/jpeg", user_id=1, artifact_id=artifact_id)

        with Session(eng) as db:
            facts = db.exec(sq_select(SemanticFact).where(SemanticFact.user_id == 1)).all()
            assert len(facts) == 2
            assert any("developer" in f.proposition for f in facts)
            fa2 = db.get(FileArtifact, artifact_id)
            assert fa2 is not None and fa2.semantic_extracted is True

    def test_never_raises_on_error(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}), \
             patch("app.cortex.providers.factory.build_ai_provider", side_effect=RuntimeError("boom")):
            from app.chat.image_semantic_extractor import extract_image_semantic_facts
            extract_image_semantic_facts("bad", "image/jpeg", user_id=1, artifact_id=999)


# ---------------------------------------------------------------------------
# Part 7 — storage_alert
# ---------------------------------------------------------------------------

class TestMaybeSendStorageAlert:

    def test_no_op_below_90_pct(self) -> None:
        eng = _mem_db()
        with Session(eng) as db:
            with patch("app.notifications.storage_alert.dispatch") as mock_dispatch:
                from app.notifications.storage_alert import maybe_send_storage_alert
                maybe_send_storage_alert(
                    session_id="user:1",
                    user_id=1,
                    used_bytes=100,
                    limit_bytes=1000,
                    db=db,
                )
        mock_dispatch.assert_not_called()

    def test_dispatches_at_90_pct(self) -> None:
        eng = _mem_db()
        with Session(eng) as db:
            with patch("app.notifications.storage_alert.dispatch") as mock_dispatch:
                from app.notifications.storage_alert import maybe_send_storage_alert
                maybe_send_storage_alert(
                    session_id="user:1",
                    user_id=1,
                    used_bytes=900,
                    limit_bytes=1000,
                    db=db,
                )
        mock_dispatch.assert_called_once()
        fact = mock_dispatch.call_args[0][0]
        assert "warning" in fact.fact_id

    def test_dispatches_full_level_at_100_pct(self) -> None:
        eng = _mem_db()
        with Session(eng) as db:
            with patch("app.notifications.storage_alert.dispatch") as mock_dispatch:
                from app.notifications.storage_alert import maybe_send_storage_alert
                maybe_send_storage_alert(
                    session_id="user:1",
                    user_id=1,
                    used_bytes=1000,
                    limit_bytes=1000,
                    db=db,
                )
        mock_dispatch.assert_called_once()
        fact = mock_dispatch.call_args[0][0]
        assert "full" in fact.fact_id

    def test_never_raises(self) -> None:
        eng = _mem_db()
        with Session(eng) as db:
            with patch("app.notifications.storage_alert.dispatch", side_effect=RuntimeError("boom")):
                from app.notifications.storage_alert import maybe_send_storage_alert
                maybe_send_storage_alert("user:1", 1, 950, 1000, db)


# ---------------------------------------------------------------------------
# Part 8 — GET /files/storage-stats
# ---------------------------------------------------------------------------

class TestStorageStatsEndpoint:

    def test_guest_returns_401(self) -> None:
        with _client() as c:
            resp = c.get("/files/storage-stats")
        assert resp.status_code == 401

    def test_returns_correct_fields(self) -> None:
        token = make_user_token()
        with _client() as c:
            resp = c.get("/files/storage-stats", cookies={"sity_session": token})
        assert resp.status_code == 200
        data = resp.json()
        assert "used_bytes" in data
        assert "limit_bytes" in data
        assert "file_count" in data
        assert "permanent_count" in data
        assert data["limit_bytes"] > 0

    def test_used_bytes_counts_user_files(self, db_session: Session) -> None:
        token = make_user_token()
        from app.auth.jwt_utils import decode_token
        payload = decode_token(token)
        assert payload is not None
        uid = int(payload["sub"])
        _add_artifact(db_session, user_id=uid, file_size_bytes=1024)
        _add_artifact(db_session, user_id=uid, file_size_bytes=2048)
        with _client() as c:
            resp = c.get("/files/storage-stats", cookies={"sity_session": token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["used_bytes"] >= 3072
        assert data["file_count"] >= 2
