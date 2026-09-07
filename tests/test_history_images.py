"""Tests for multi-turn visual context (Paso 2 of file management).

Verifies that:
1. _history_to_messages() produces correct image content blocks.
2. _attach_history_images() loads images from disk for linked FileArtifact rows.
3. The image history limit (_IMAGE_HISTORY_TURNS_MAX=2) is respected.
4. planner history (attach_images=False) never carries image blocks.
"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest
from sqlmodel import Session

# 1×1 transparent PNG — same as test_file_artifact.py
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_PNG_BYTES = base64.b64decode(_PNG_B64)


@pytest.fixture()
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import app.chat.file_artifact as _fa
    target = tmp_path / "uploads" / "images"
    target.mkdir(parents=True)
    monkeypatch.setattr(_fa, "UPLOADS_IMAGES_DIR", target)
    # Also redirect PROJECT_ROOT so disk reads resolve against tmp_path
    monkeypatch.setattr(_fa, "PROJECT_ROOT", tmp_path)
    return target


# ------------------------------------------------------------------ #
# 1. _history_to_messages — unit tests (no DB, no disk)              #
# ------------------------------------------------------------------ #

def test_history_to_messages_text_only() -> None:
    from app.api.schemas import ChatHistoryItem
    from app.chat.prompt_context import _history_to_messages

    items = [
        ChatHistoryItem(role="user", text="hola"),
        ChatHistoryItem(role="sity", text="Hola"),
    ]
    result = _history_to_messages(items)
    assert result == [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "Hola"},
    ]


def test_history_to_messages_merges_consecutive_text() -> None:
    from app.api.schemas import ChatHistoryItem
    from app.chat.prompt_context import _history_to_messages

    items = [
        ChatHistoryItem(role="user", text="a"),
        ChatHistoryItem(role="user", text="b"),
    ]
    result = _history_to_messages(items)
    assert len(result) == 1
    assert result[0]["content"] == "a\nb"


def test_history_to_messages_image_turn_creates_content_blocks() -> None:
    from app.api.schemas import ChatHistoryItem
    from app.chat.prompt_context import _history_to_messages

    items = [
        ChatHistoryItem(
            role="user",
            text="qué ves?",
            images=[{"media_type": "image/png", "data": _PNG_B64}],
        ),
        ChatHistoryItem(role="sity", text="Veo un píxel."),
    ]
    result = _history_to_messages(items)
    assert len(result) == 2
    user_msg = result[0]
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], list)
    assert user_msg["content"][0]["type"] == "image"
    assert user_msg["content"][0]["source"]["type"] == "base64"
    assert user_msg["content"][0]["source"]["media_type"] == "image/png"
    assert user_msg["content"][0]["source"]["data"] == _PNG_B64
    assert user_msg["content"][1] == {"type": "text", "text": "qué ves?"}
    assert result[1] == {"role": "assistant", "content": "Veo un píxel."}


def test_history_to_messages_image_turn_not_merged_with_adjacent() -> None:
    from app.api.schemas import ChatHistoryItem
    from app.chat.prompt_context import _history_to_messages

    items = [
        ChatHistoryItem(
            role="user",
            text="imagen",
            images=[{"media_type": "image/png", "data": _PNG_B64}],
        ),
        ChatHistoryItem(role="user", text="texto"),
    ]
    result = _history_to_messages(items)
    # Two separate user entries — image turn must not merge with following text-only turn
    assert len(result) == 2
    assert isinstance(result[0]["content"], list)
    assert result[1]["content"] == "texto"


def test_history_to_messages_include_images_false_strips_images() -> None:
    from app.api.schemas import ChatHistoryItem
    from app.chat.prompt_context import _history_to_messages

    items = [
        ChatHistoryItem(
            role="user",
            text="qué ves?",
            images=[{"media_type": "image/png", "data": _PNG_B64}],
        ),
    ]
    result = _history_to_messages(items, include_images=False)
    assert isinstance(result[0]["content"], str)
    assert result[0]["content"] == "qué ves?"


def test_history_to_messages_multiple_images_in_one_turn() -> None:
    from app.api.schemas import ChatHistoryItem
    from app.chat.prompt_context import _history_to_messages

    items = [
        ChatHistoryItem(
            role="user",
            text="compara estas dos",
            images=[
                {"media_type": "image/png", "data": _PNG_B64},
                {"media_type": "image/jpeg", "data": _PNG_B64},
            ],
        ),
    ]
    result = _history_to_messages(items)
    content = result[0]["content"]
    assert isinstance(content, list)
    # Two image blocks + one text block
    assert len(content) == 3
    assert content[0]["type"] == "image"
    assert content[1]["type"] == "image"
    assert content[2]["type"] == "text"


# ------------------------------------------------------------------ #
# 2. _attach_history_images — integration (DB + disk)                #
# ------------------------------------------------------------------ #

class _FakeMsg:
    """Minimal ChatMessage stand-in with id, role, text."""
    def __init__(self, id: int, role: str, text: str) -> None:
        self.id = id
        self.role = role
        self.text = text


def test_attach_history_images_loads_linked_artifact(
    db_session: Session, upload_dir: Path
) -> None:
    from app.api.schemas import ChatHistoryItem
    from app.chat.file_artifact import save_uploaded_image, wire_uploaded_images_to_message
    from app.chat.prompt_context import _attach_history_images

    fa = save_uploaded_image(_PNG_B64, "image/png", db_session, user_id=1)
    wire_uploaded_images_to_message(db_session, [fa.id], chat_message_id=10)

    raw_rows = [_FakeMsg(id=10, role="user", text="qué ves?")]
    items = [ChatHistoryItem(role="user", text="qué ves?")]

    _attach_history_images(db_session, raw_rows, items)

    assert len(items[0].images) == 1
    assert items[0].images[0]["media_type"] == "image/png"
    assert items[0].images[0]["data"] == base64.b64encode(_PNG_BYTES).decode()


def test_attach_history_images_no_linked_artifact_leaves_item_unchanged(
    db_session: Session, upload_dir: Path
) -> None:
    from app.api.schemas import ChatHistoryItem
    from app.chat.prompt_context import _attach_history_images

    raw_rows = [_FakeMsg(id=999, role="user", text="texto")]
    items = [ChatHistoryItem(role="user", text="texto")]

    _attach_history_images(db_session, raw_rows, items)
    assert items[0].images == []


def test_attach_history_images_respects_limit(
    db_session: Session, upload_dir: Path
) -> None:
    """Only the 2 most recent image turns get images attached; older turns stay text-only."""
    from app.api.schemas import ChatHistoryItem
    from app.chat.file_artifact import save_uploaded_image, wire_uploaded_images_to_message
    from app.chat.prompt_context import _IMAGE_HISTORY_TURNS_MAX, _attach_history_images

    assert _IMAGE_HISTORY_TURNS_MAX == 2

    fa1 = save_uploaded_image(_PNG_B64, "image/png", db_session, user_id=1)
    fa2 = save_uploaded_image(_PNG_B64, "image/png", db_session, user_id=1)
    fa3 = save_uploaded_image(_PNG_B64, "image/png", db_session, user_id=1)
    wire_uploaded_images_to_message(db_session, [fa1.id], chat_message_id=1)
    wire_uploaded_images_to_message(db_session, [fa2.id], chat_message_id=2)
    wire_uploaded_images_to_message(db_session, [fa3.id], chat_message_id=3)

    raw_rows = [
        _FakeMsg(id=1, role="user", text="img1"),
        _FakeMsg(id=2, role="user", text="img2"),
        _FakeMsg(id=3, role="user", text="img3"),  # most recent
    ]
    items = [
        ChatHistoryItem(role="user", text="img1"),
        ChatHistoryItem(role="user", text="img2"),
        ChatHistoryItem(role="user", text="img3"),
    ]

    _attach_history_images(db_session, raw_rows, items)

    assert len(items[2].images) == 1, "most recent turn must have image"
    assert len(items[1].images) == 1, "second-most-recent turn must have image"
    assert len(items[0].images) == 0, "oldest turn must NOT have image (limit=2)"


def test_attach_history_images_skips_sity_rows(
    db_session: Session, upload_dir: Path
) -> None:
    """sity rows are never given images regardless of what's in the DB."""
    from app.api.schemas import ChatHistoryItem
    from app.chat.prompt_context import _attach_history_images

    raw_rows = [_FakeMsg(id=1, role="sity", text="respuesta")]
    items = [ChatHistoryItem(role="sity", text="respuesta")]

    _attach_history_images(db_session, raw_rows, items)
    assert items[0].images == []


def test_attach_history_images_tolerates_missing_file(
    db_session: Session, upload_dir: Path
) -> None:
    """If the image file is missing on disk, that image is silently skipped."""
    from app.api.schemas import ChatHistoryItem
    from app.chat.file_artifact import save_uploaded_image, wire_uploaded_images_to_message
    from app.chat.prompt_context import _attach_history_images
    from app.memory.models import FileArtifact

    fa = save_uploaded_image(_PNG_B64, "image/png", db_session, user_id=1)
    wire_uploaded_images_to_message(db_session, [fa.id], chat_message_id=10)

    # Delete the file so the disk read fails
    (upload_dir / fa.filename).unlink()

    raw_rows = [_FakeMsg(id=10, role="user", text="texto")]
    items = [ChatHistoryItem(role="user", text="texto")]

    _attach_history_images(db_session, raw_rows, items)
    # images list empty — no crash
    assert items[0].images == []


# ------------------------------------------------------------------ #
# 3. _load_history with attach_images=False never returns images     #
# ------------------------------------------------------------------ #

def test_load_history_attach_images_false_returns_no_images(
    db_session: Session, upload_dir: Path
) -> None:
    from app.chat.file_artifact import save_uploaded_image, wire_uploaded_images_to_message
    from app.chat.prompt_context import PromptContextBuilder

    fa = save_uploaded_image(_PNG_B64, "image/png", db_session, user_id=1)
    wire_uploaded_images_to_message(db_session, [fa.id], chat_message_id=42)

    class _Msg:
        def __init__(self, id, role, text):
            self.id = id
            self.role = role
            self.text = text
            from datetime import datetime, timezone
            self.created_at = datetime.now(timezone.utc)

    msgs = [_Msg(42, "user", "qué ves?")]

    def _get(_session, limit: int):
        return msgs[-limit:] if limit < len(msgs) else msgs[:]

    builder = PromptContextBuilder(get_recent_messages=_get)
    # _load_history with attach_images=False (default for planner)
    history = builder._load_history(session=db_session, limit=10, attach_images=False)

    for item in history:
        assert item.images == [], f"Expected no images when attach_images=False, got {item.images!r}"
