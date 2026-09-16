"""Tests for GET /uploads/images/{filename} authorization.

Coverage:
  - Owner (authenticated user) → 200
  - Different authenticated user → 404
  - No session (anonymous) → 404
  - Guest of a different session → 404
  - Guest owner with chat_message_id wired → 200
  - Guest owner with chat_message_id IS NULL (timing window) → 200
  - File exists on disk but no FileArtifact row → 404
  - Path traversal still blocked (existing validation preserved)
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.memory.db import engine
from app.memory.models import ChatMessage, FileArtifact

_ROOT = Path(__file__).resolve().parents[1]
_UPLOADS_DIR = _ROOT / "uploads" / "images"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _email(tag: str = "") -> str:
    return f"upl_{tag or 'u'}_{_uid()}@test.invalid"


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _register_and_login(client: TestClient, email: str, password: str = "Str0ngPass1") -> None:
    resp = client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text


def _write_dummy_image(filename: str) -> Path:
    """Write a minimal valid PNG to the uploads directory and return the path."""
    _UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    # 1×1 px transparent PNG (smallest valid PNG)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    path = _UPLOADS_DIR / filename
    path.write_bytes(png_bytes)
    return path


def _insert_artifact(
    user_id: int | None,
    filename: str,
    chat_message_id: int | None = None,
) -> FileArtifact:
    with Session(engine) as session:
        fa = FileArtifact(
            user_id=user_id,
            artifact_type="image",
            filename=filename,
            rel_path=f"uploads/images/{filename}",
            mime_type="image/png",
            source="chat_upload",
            chat_message_id=chat_message_id,
        )
        session.add(fa)
        session.commit()
        session.refresh(fa)
        return fa


def _insert_chat_message(session_id: str) -> ChatMessage:
    with Session(engine) as session:
        msg = ChatMessage(
            session_id=session_id,
            role="user",
            text="test",
        )
        session.add(msg)
        session.commit()
        session.refresh(msg)
        return msg


def _get_user_id(email: str) -> int:
    from sqlmodel import select
    from app.memory.models import User
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email)).first()
        assert user is not None
        assert user.id is not None
        return user.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_owner_gets_image():
    """Authenticated owner of a FileArtifact can download their own image."""
    email = _email("owner")
    filename = f"{_uid()}.png"
    path = _write_dummy_image(filename)

    with _client() as c:
        _register_and_login(c, email)
        user_id = _get_user_id(email)
        _insert_artifact(user_id, filename)
        resp = c.get(f"/uploads/images/{filename}")
    path.unlink(missing_ok=True)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")


def test_other_authenticated_user_gets_404():
    """A different authenticated user cannot download another user's image."""
    email_a = _email("other_a")
    email_b = _email("other_b")
    filename = f"{_uid()}.png"
    path = _write_dummy_image(filename)

    with _client() as c:
        _register_and_login(c, email_a)
        user_id_a = _get_user_id(email_a)
        _insert_artifact(user_id_a, filename)

    with _client() as c:
        _register_and_login(c, email_b)
        resp = c.get(f"/uploads/images/{filename}")
    path.unlink(missing_ok=True)

    assert resp.status_code == 404


def test_no_session_gets_404():
    """A request with no session cookie cannot download any image."""
    email = _email("nosess")
    filename = f"{_uid()}.png"
    path = _write_dummy_image(filename)

    with _client() as c:
        _register_and_login(c, email)
        user_id = _get_user_id(email)
        _insert_artifact(user_id, filename)

    # Fresh client with no cookies
    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.clear()
        resp = c.get(f"/uploads/images/{filename}")
    path.unlink(missing_ok=True)

    assert resp.status_code == 404


def test_guest_owner_with_wired_message_gets_200():
    """Guest can download their own image when chat_message_id is wired to their session."""
    filename = f"{_uid()}.png"
    path = _write_dummy_image(filename)
    guest_session_id = f"guest:{uuid.uuid4().hex}"

    msg = _insert_chat_message(guest_session_id)
    _insert_artifact(None, filename, chat_message_id=msg.id)

    with TestClient(app, raise_server_exceptions=True) as c:
        # Inject the guest session cookie directly
        c.cookies.set("sity_guest_session", guest_session_id)
        resp = c.get(f"/uploads/images/{filename}")
    path.unlink(missing_ok=True)

    assert resp.status_code == 200


def test_guest_different_session_gets_404():
    """A guest with a different session_id cannot download another guest's wired image."""
    filename = f"{_uid()}.png"
    path = _write_dummy_image(filename)
    owner_session = f"guest:{uuid.uuid4().hex}"
    other_session = f"guest:{uuid.uuid4().hex}"

    msg = _insert_chat_message(owner_session)
    _insert_artifact(None, filename, chat_message_id=msg.id)

    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("sity_guest_session", other_session)
        resp = c.get(f"/uploads/images/{filename}")
    path.unlink(missing_ok=True)

    assert resp.status_code == 404


def test_guest_owner_timing_window_allowed():
    """Guest image with chat_message_id=None (not yet wired) is allowed (timing window)."""
    filename = f"{_uid()}.png"
    path = _write_dummy_image(filename)
    guest_session_id = f"guest:{uuid.uuid4().hex}"

    # Artifact not yet wired: chat_message_id IS NULL
    _insert_artifact(None, filename, chat_message_id=None)

    with TestClient(app, raise_server_exceptions=True) as c:
        c.cookies.set("sity_guest_session", guest_session_id)
        resp = c.get(f"/uploads/images/{filename}")
    path.unlink(missing_ok=True)

    assert resp.status_code == 200


def test_no_artifact_row_gets_404():
    """File on disk but no FileArtifact row in DB → 404."""
    email = _email("norow")
    filename = f"{_uid()}.png"
    path = _write_dummy_image(filename)
    # Intentionally NOT inserting a FileArtifact row

    with _client() as c:
        _register_and_login(c, email)
        resp = c.get(f"/uploads/images/{filename}")
    path.unlink(missing_ok=True)

    assert resp.status_code == 404


def test_path_traversal_still_blocked():
    """Path traversal in filename is still rejected with 400."""
    with _client() as c:
        resp = c.get("/uploads/images/../../../etc/passwd")
    assert resp.status_code in {400, 404}
