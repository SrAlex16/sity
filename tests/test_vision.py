"""Tests for image (vision) support — validation and content block construction."""
from __future__ import annotations

import base64

import pytest

from app.api.schemas import ChatImageInput
from app.cortex.schemas import AIRequest
from app.cortex.claude_provider import _user_content_block

# Minimal valid 1×1 white JPEG in base64
_TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
    "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
    "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjL/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAA"
    "AAAAAAAAAAAAAP/EABQBAQAAAAAAAAAAAAAAAAAAAAD/xAAUEQEAAAAAAAAAAAAAAAAAAAAA"
    "/9oADAMBAAIRAxEAPwCwABmX/9k="
)


# ── _validate_images (imported via routes_chat to avoid circular imports) ──────

def _validate(images: list[ChatImageInput]) -> str | None:
    from app.api.routes_chat import _validate_images
    return _validate_images(images)


def test_validate_images_accepts_valid_jpeg() -> None:
    img = ChatImageInput(media_type="image/jpeg", data=_TINY_JPEG_B64)
    assert _validate([img]) is None


def test_validate_images_rejects_invalid_media_type() -> None:
    img = ChatImageInput(media_type="image/tiff", data=_TINY_JPEG_B64)
    err = _validate([img])
    assert err is not None
    assert "no soportado" in err


def test_validate_images_rejects_invalid_base64() -> None:
    img = ChatImageInput(media_type="image/jpeg", data="!!!not_base64!!!")
    err = _validate([img])
    assert err is not None
    assert "inválidos" in err


def test_validate_images_rejects_oversized_image() -> None:
    # Generate ~6 MB of valid base64 (raw bytes, not a real JPEG)
    big_data = base64.b64encode(b"A" * (6 * 1024 * 1024)).decode()
    img = ChatImageInput(media_type="image/jpeg", data=big_data)
    err = _validate([img])
    assert err is not None
    assert "5MB" in err


def test_validate_images_empty_list_is_ok() -> None:
    assert _validate([]) is None


# ── _user_content_block ────────────────────────────────────────────────────────

def _make_request(images: list[dict[str, str]] | None = None) -> AIRequest:
    return AIRequest(
        trace_id="t1",
        task_type="chat_message",
        system_prompt="test",
        user_message="¿qué ves?",
        images=images or [],
    )


def test_user_content_block_without_images_returns_string() -> None:
    req = _make_request()
    result = _user_content_block(req)
    assert isinstance(result, str)
    assert result == "¿qué ves?"


def test_user_content_block_with_images_returns_list() -> None:
    req = _make_request(images=[{"media_type": "image/jpeg", "data": _TINY_JPEG_B64}])
    result = _user_content_block(req)
    assert isinstance(result, list)
    assert len(result) == 2


def test_user_content_block_image_block_structure() -> None:
    req = _make_request(images=[{"media_type": "image/jpeg", "data": _TINY_JPEG_B64}])
    result = _user_content_block(req)
    assert isinstance(result, list)
    img_block = result[0]
    assert img_block["type"] == "image"
    assert img_block["source"]["type"] == "base64"
    assert img_block["source"]["media_type"] == "image/jpeg"
    assert img_block["source"]["data"] == _TINY_JPEG_B64


def test_user_content_block_text_is_last() -> None:
    req = _make_request(images=[{"media_type": "image/jpeg", "data": _TINY_JPEG_B64}])
    result = _user_content_block(req)
    assert isinstance(result, list)
    text_block = result[-1]
    assert text_block["type"] == "text"
    assert text_block["text"] == "¿qué ves?"


# ── build_planner_ai_request images propagation ────────────────────────────────

def test_planner_request_includes_images() -> None:
    from app.chat.ai_request_builder import build_planner_ai_request
    img = {"media_type": "image/jpeg", "data": _TINY_JPEG_B64}
    req = build_planner_ai_request(
        trace_id="t-planner",
        user_message="¿qué hay en esta imagen?",
        tools=[],
        images=[img],
    )
    assert len(req.images) == 1
    assert req.images[0]["media_type"] == "image/jpeg"
    assert req.images[0]["data"] == _TINY_JPEG_B64


def test_planner_request_without_images_defaults_empty() -> None:
    from app.chat.ai_request_builder import build_planner_ai_request
    req = build_planner_ai_request(
        trace_id="t-planner-no-img",
        user_message="busca algo",
        tools=[],
    )
    assert req.images == []
