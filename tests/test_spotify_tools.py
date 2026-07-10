"""Tests for Spotify tool handlers.

All HTTP calls to the Spotify API are mocked — no network access.
DB access uses the in-memory test DB (SITY_DB_URL env var set by conftest).
"""
from __future__ import annotations

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("SITY_DB_URL", "sqlite:////tmp/sity_pytest_test.db")

from sqlmodel import Session, select

from app.memory.db import engine
from app.memory.models import Setting


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(tool_name: str, tool_input: dict | None = None):
    ctx = MagicMock()
    ctx.tool_name = tool_name
    ctx.tool_input = tool_input or {}
    return ctx


def _mock_response(status_code: int, json_data: dict | None = None, content: bytes = b"x"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.content = content if json_data is None else b"x"
    if json_data is not None:
        resp.json.return_value = json_data
        resp.content = b"x"
    return resp


def _clear_previous_context():
    with Session(engine) as db:
        row = db.exec(select(Setting).where(Setting.key == "spotify:previous_context")).first()
        if row:
            db.delete(row)
            db.commit()


def _read_previous_context() -> dict | None:
    with Session(engine) as db:
        row = db.exec(select(Setting).where(Setting.key == "spotify:previous_context")).first()
        return json.loads(row.value_json) if row else None


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=False)
def test_auth_guard_now_playing(mock_conn):
    from app.tools.handlers.spotify_tools import handle_spotify_now_playing
    result = handle_spotify_now_playing(_make_ctx("spotify_now_playing"))
    assert result.ok is False
    assert "no está conectado" in result.message.lower()


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=False)
def test_auth_guard_resume_previous(mock_conn):
    from app.tools.handlers.spotify_tools import handle_spotify_resume_previous
    result = handle_spotify_resume_previous(_make_ctx("spotify_resume_previous"))
    assert result.ok is False


# ---------------------------------------------------------------------------
# spotify_now_playing
# ---------------------------------------------------------------------------

@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._get")
def test_now_playing_nothing(mock_get, _):
    mock_get.return_value = _mock_response(204, content=b"")
    from app.tools.handlers.spotify_tools import handle_spotify_now_playing
    result = handle_spotify_now_playing(_make_ctx("spotify_now_playing"))
    assert result.ok is True
    assert "no hay" in result.message.lower()


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._get")
def test_now_playing_track(mock_get, _):
    mock_get.return_value = _mock_response(200, {
        "is_playing": True,
        "progress_ms": 30000,
        "item": {
            "name": "Throne",
            "uri": "spotify:track:abc",
            "duration_ms": 240000,
            "artists": [{"name": "Bring Me The Horizon"}],
            "album": {"name": "That's the Spirit"},
        },
    })
    from app.tools.handlers.spotify_tools import handle_spotify_now_playing
    result = handle_spotify_now_playing(_make_ctx("spotify_now_playing"))
    assert result.ok is True
    assert "Throne" in result.message
    assert "Bring Me The Horizon" in result.message


# ---------------------------------------------------------------------------
# spotify_recently_played
# ---------------------------------------------------------------------------

@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._get")
def test_recently_played_happy(mock_get, _):
    mock_get.return_value = _mock_response(200, {
        "items": [
            {
                "track": {"name": "Drown", "artists": [{"name": "Bring Me The Horizon"}]},
                "played_at": "2026-07-10T12:00:00Z",
            }
        ]
    })
    from app.tools.handlers.spotify_tools import handle_spotify_recently_played
    result = handle_spotify_recently_played(_make_ctx("spotify_recently_played", {"limit": 5}))
    assert result.ok is True
    assert "Drown" in result.message


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._get")
def test_recently_played_error(mock_get, _):
    mock_get.return_value = _mock_response(500)
    from app.tools.handlers.spotify_tools import handle_spotify_recently_played
    result = handle_spotify_recently_played(_make_ctx("spotify_recently_played"))
    assert result.ok is False
    assert "500" in result.message


# ---------------------------------------------------------------------------
# spotify_list_devices
# ---------------------------------------------------------------------------

@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._get")
def test_list_devices_happy(mock_get, _):
    mock_get.return_value = _mock_response(200, {
        "devices": [
            {"id": "dev1", "name": "RasPad", "type": "Computer", "is_active": True, "volume_percent": 60},
        ]
    })
    from app.tools.handlers.spotify_tools import handle_spotify_list_devices
    result = handle_spotify_list_devices(_make_ctx("spotify_list_devices"))
    assert result.ok is True
    assert "RasPad" in result.message
    assert "ACTIVO" in result.message


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._get")
def test_list_devices_none(mock_get, _):
    mock_get.return_value = _mock_response(200, {"devices": []})
    from app.tools.handlers.spotify_tools import handle_spotify_list_devices
    result = handle_spotify_list_devices(_make_ctx("spotify_list_devices"))
    assert result.ok is True
    assert "no hay" in result.message.lower()


# ---------------------------------------------------------------------------
# _search_uri
# ---------------------------------------------------------------------------

@patch("app.tools.handlers.spotify_tools._get")
def test_search_uri_track(mock_get):
    mock_get.return_value = _mock_response(200, {
        "tracks": {"items": [{"uri": "spotify:track:t1", "name": "Throne", "artists": [{"name": "BMTH"}]}]},
        "albums": {"items": []},
    })
    from app.tools.handlers.spotify_tools import _search_uri
    result = _search_uri("Throne BMTH")
    assert result is not None
    uri, desc = result
    assert uri == "spotify:track:t1"
    assert "Throne" in desc


@patch("app.tools.handlers.spotify_tools._get")
def test_search_uri_album_fallback(mock_get):
    mock_get.return_value = _mock_response(200, {
        "tracks": {"items": []},
        "albums": {"items": [{"uri": "spotify:album:a1", "name": "Spirit", "artists": [{"name": "BMTH"}]}]},
    })
    from app.tools.handlers.spotify_tools import _search_uri
    result = _search_uri("Spirit BMTH")
    assert result is not None
    uri, desc = result
    assert uri == "spotify:album:a1"
    assert "álbum" in desc


@patch("app.tools.handlers.spotify_tools._get")
def test_search_uri_nothing(mock_get):
    mock_get.return_value = _mock_response(200, {"tracks": {"items": []}, "albums": {"items": []}})
    from app.tools.handlers.spotify_tools import _search_uri
    assert _search_uri("xxxxunknown") is None


# ---------------------------------------------------------------------------
# spotify_play
# ---------------------------------------------------------------------------

@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._put")
@patch("app.tools.handlers.spotify_tools._save_previous_context")
@patch("app.tools.handlers.spotify_tools._search_uri", return_value=("spotify:track:t1", "Throne — BMTH"))
def test_play_with_query_track(mock_search, mock_save, mock_put, _):
    mock_put.return_value = _mock_response(204)
    from app.tools.handlers.spotify_tools import handle_spotify_play
    result = handle_spotify_play(_make_ctx("spotify_play", {"query": "Throne"}))
    assert result.ok is True
    assert "Throne" in result.message
    mock_save.assert_called_once()
    # track uri → uris list
    call_kwargs = mock_put.call_args
    assert "uris" in call_kwargs.kwargs["body"]


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._put")
@patch("app.tools.handlers.spotify_tools._save_previous_context")
@patch("app.tools.handlers.spotify_tools._search_uri", return_value=("spotify:album:a1", "álbum Spirit — BMTH"))
def test_play_with_query_album(mock_search, mock_save, mock_put, _):
    mock_put.return_value = _mock_response(204)
    from app.tools.handlers.spotify_tools import handle_spotify_play
    result = handle_spotify_play(_make_ctx("spotify_play", {"query": "Spirit"}))
    assert result.ok is True
    mock_save.assert_called_once()
    call_kwargs = mock_put.call_args
    assert "context_uri" in call_kwargs.kwargs["body"]


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._put")
@patch("app.tools.handlers.spotify_tools._save_previous_context")
def test_play_resume_no_save(mock_save, mock_put, _):
    """Resuming without a query must NOT save previous context."""
    mock_put.return_value = _mock_response(204)
    from app.tools.handlers.spotify_tools import handle_spotify_play
    result = handle_spotify_play(_make_ctx("spotify_play", {}))
    assert result.ok is True
    mock_save.assert_not_called()


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._search_uri", return_value=None)
def test_play_not_found(mock_search, _):
    from app.tools.handlers.spotify_tools import handle_spotify_play
    result = handle_spotify_play(_make_ctx("spotify_play", {"query": "xxxxunknown"}))
    assert result.ok is False
    assert "No encontré" in result.message


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._put")
@patch("app.tools.handlers.spotify_tools._save_previous_context")
@patch("app.tools.handlers.spotify_tools._search_uri", return_value=("spotify:track:t1", "Throne — BMTH"))
def test_play_device_id_optional(mock_search, mock_save, mock_put, _):
    mock_put.return_value = _mock_response(204)
    from app.tools.handlers.spotify_tools import handle_spotify_play
    result = handle_spotify_play(_make_ctx("spotify_play", {"query": "Throne", "device_id": "dev1"}))
    assert result.ok is True
    call_kwargs = mock_put.call_args
    assert call_kwargs.kwargs["params"] == {"device_id": "dev1"}


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._put")
@patch("app.tools.handlers.spotify_tools._save_previous_context")
@patch("app.tools.handlers.spotify_tools._search_uri", return_value=("spotify:playlist:abc123", "Otako culiao"))
def test_play_404_includes_uri(mock_search, mock_save, mock_put, _):
    """404 when a URI was resolved must include the URI so the model can retry."""
    mock_put.return_value = _mock_response(404)
    from app.tools.handlers.spotify_tools import handle_spotify_play
    result = handle_spotify_play(_make_ctx("spotify_play", {"query": "Otako culiao"}))
    assert result.ok is False
    assert "spotify:playlist:abc123" in result.message
    assert "dispositivo" in result.message.lower()


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._put")
@patch("app.tools.handlers.spotify_tools._save_previous_context")
def test_play_404_resume_no_uri(mock_save, mock_put, _):
    """404 on plain resume (no query) must NOT reference any URI."""
    mock_put.return_value = _mock_response(404)
    from app.tools.handlers.spotify_tools import handle_spotify_play
    result = handle_spotify_play(_make_ctx("spotify_play", {}))
    assert result.ok is False
    assert "spotify:" not in result.message
    assert "dispositivo" in result.message.lower()


# ---------------------------------------------------------------------------
# spotify_pause
# ---------------------------------------------------------------------------

@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._put")
def test_pause_happy(mock_put, _):
    mock_put.return_value = _mock_response(204)
    from app.tools.handlers.spotify_tools import handle_spotify_pause
    result = handle_spotify_pause(_make_ctx("spotify_pause"))
    assert result.ok is True
    assert "pausada" in result.message.lower()


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._put")
def test_pause_404(mock_put, _):
    mock_put.return_value = _mock_response(404)
    from app.tools.handlers.spotify_tools import handle_spotify_pause
    result = handle_spotify_pause(_make_ctx("spotify_pause"))
    assert result.ok is False
    assert "dispositivo" in result.message.lower()


# ---------------------------------------------------------------------------
# spotify_skip
# ---------------------------------------------------------------------------

@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._post")
@patch("app.tools.handlers.spotify_tools._save_previous_context")
def test_skip_next_saves_context(mock_save, mock_post, _):
    mock_post.return_value = _mock_response(204)
    from app.tools.handlers.spotify_tools import handle_spotify_skip
    result = handle_spotify_skip(_make_ctx("spotify_skip", {"direction": "next"}))
    assert result.ok is True
    assert "siguiente" in result.message.lower()
    mock_save.assert_called_once()


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._post")
@patch("app.tools.handlers.spotify_tools._save_previous_context")
def test_skip_previous_saves_context(mock_save, mock_post, _):
    mock_post.return_value = _mock_response(204)
    from app.tools.handlers.spotify_tools import handle_spotify_skip
    result = handle_spotify_skip(_make_ctx("spotify_skip", {"direction": "previous"}))
    assert result.ok is True
    assert "anterior" in result.message.lower()
    mock_save.assert_called_once()


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._post")
@patch("app.tools.handlers.spotify_tools._save_previous_context")
def test_skip_invalid_direction_defaults_next(mock_save, mock_post, _):
    mock_post.return_value = _mock_response(204)
    from app.tools.handlers.spotify_tools import handle_spotify_skip
    result = handle_spotify_skip(_make_ctx("spotify_skip", {"direction": "sideways"}))
    assert result.ok is True
    assert "siguiente" in result.message.lower()


# ---------------------------------------------------------------------------
# spotify_set_volume
# ---------------------------------------------------------------------------

@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._put")
def test_set_volume_happy(mock_put, _):
    mock_put.return_value = _mock_response(204)
    from app.tools.handlers.spotify_tools import handle_spotify_set_volume
    result = handle_spotify_set_volume(_make_ctx("spotify_set_volume", {"volume_percent": 75}))
    assert result.ok is True
    assert "75" in result.message


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._put")
def test_set_volume_clamped(mock_put, _):
    mock_put.return_value = _mock_response(204)
    from app.tools.handlers.spotify_tools import handle_spotify_set_volume
    result = handle_spotify_set_volume(_make_ctx("spotify_set_volume", {"volume_percent": 999}))
    assert result.ok is True
    assert "100" in result.message


# ---------------------------------------------------------------------------
# spotify_resume_previous
# ---------------------------------------------------------------------------

@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._put")
@patch("app.tools.handlers.spotify_tools._load_previous_context",
       return_value={"uri": "spotify:playlist:p1", "description": "Deep Focus — Spotify", "saved_at": 0.0})
def test_resume_previous_playlist(mock_load, mock_put, _):
    mock_put.return_value = _mock_response(204)
    from app.tools.handlers.spotify_tools import handle_spotify_resume_previous
    result = handle_spotify_resume_previous(_make_ctx("spotify_resume_previous"))
    assert result.ok is True
    assert "Deep Focus" in result.message
    call_kwargs = mock_put.call_args
    assert call_kwargs.kwargs["body"] == {"context_uri": "spotify:playlist:p1"}


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._put")
@patch("app.tools.handlers.spotify_tools._load_previous_context",
       return_value={"uri": "spotify:track:t1", "description": "Throne — BMTH", "saved_at": 0.0})
def test_resume_previous_track(mock_load, mock_put, _):
    mock_put.return_value = _mock_response(204)
    from app.tools.handlers.spotify_tools import handle_spotify_resume_previous
    result = handle_spotify_resume_previous(_make_ctx("spotify_resume_previous"))
    assert result.ok is True
    call_kwargs = mock_put.call_args
    assert call_kwargs.kwargs["body"] == {"uris": ["spotify:track:t1"]}


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._load_previous_context", return_value=None)
def test_resume_previous_no_context(mock_load, _):
    from app.tools.handlers.spotify_tools import handle_spotify_resume_previous
    result = handle_spotify_resume_previous(_make_ctx("spotify_resume_previous"))
    assert result.ok is True
    assert "no tengo registro" in result.message.lower()


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._put")
@patch("app.tools.handlers.spotify_tools._load_previous_context",
       return_value={"uri": "spotify:playlist:p1", "description": "Focus", "saved_at": 0.0})
def test_resume_previous_404(mock_load, mock_put, _):
    mock_put.return_value = _mock_response(404)
    from app.tools.handlers.spotify_tools import handle_spotify_resume_previous
    result = handle_spotify_resume_previous(_make_ctx("spotify_resume_previous"))
    assert result.ok is False
    assert "dispositivo" in result.message.lower()


# ---------------------------------------------------------------------------
# Context save/load integration (real DB)
# ---------------------------------------------------------------------------

@patch("app.tools.handlers.spotify_tools._get")
def test_capture_saves_context_uri_when_context_present(mock_get):
    """When a playlist context is active, save context_uri not track uri."""
    mock_get.return_value = _mock_response(200, {
        "item": {
            "uri": "spotify:track:t1",
            "name": "Throne",
            "artists": [{"name": "BMTH"}],
        },
        "context": {"uri": "spotify:playlist:p1", "type": "playlist"},
    })
    _clear_previous_context()
    from app.tools.handlers.spotify_tools import _save_previous_context
    _save_previous_context()
    saved = _read_previous_context()
    assert saved is not None
    assert saved["uri"] == "spotify:playlist:p1"
    assert "Throne" in saved["description"]


@patch("app.tools.handlers.spotify_tools._get")
def test_capture_saves_track_uri_when_no_context(mock_get):
    """When playing a standalone track (no context), save track uri."""
    mock_get.return_value = _mock_response(200, {
        "item": {
            "uri": "spotify:track:t2",
            "name": "Drown",
            "artists": [{"name": "BMTH"}],
        },
        "context": None,
    })
    _clear_previous_context()
    from app.tools.handlers.spotify_tools import _save_previous_context
    _save_previous_context()
    saved = _read_previous_context()
    assert saved is not None
    assert saved["uri"] == "spotify:track:t2"


@patch("app.tools.handlers.spotify_tools._get")
def test_capture_does_not_save_when_204(mock_get):
    """If nothing is playing (204), _save_previous_context must not write anything."""
    mock_get.return_value = _mock_response(204, content=b"")
    _clear_previous_context()
    from app.tools.handlers.spotify_tools import _save_previous_context
    _save_previous_context()
    assert _read_previous_context() is None


@patch("app.tools.handlers.spotify_tools._get")
def test_save_overwrites_existing(mock_get):
    """Saving a second time replaces the first entry, not appends."""
    mock_get.return_value = _mock_response(200, {
        "item": {"uri": "spotify:track:t1", "name": "A", "artists": [{"name": "X"}]},
        "context": None,
    })
    _clear_previous_context()
    from app.tools.handlers.spotify_tools import _save_previous_context
    _save_previous_context()

    mock_get.return_value = _mock_response(200, {
        "item": {"uri": "spotify:track:t2", "name": "B", "artists": [{"name": "Y"}]},
        "context": None,
    })
    _save_previous_context()

    saved = _read_previous_context()
    assert saved["uri"] == "spotify:track:t2"

    with Session(engine) as db:
        rows = db.exec(select(Setting).where(Setting.key == "spotify:previous_context")).all()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# spotify_list_playlists
# ---------------------------------------------------------------------------

@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._get")
def test_list_playlists_happy(mock_get, _):
    mock_get.return_value = _mock_response(200, {
        "items": [
            {"id": "pl1", "uri": "spotify:playlist:pl1", "name": "Openings Anime",
             "tracks": {"total": 42}, "description": "Los mejores openings"},
            {"id": "pl2", "uri": "spotify:playlist:pl2", "name": "Workout",
             "tracks": {"total": 30}, "description": ""},
        ]
    })
    from app.tools.handlers.spotify_tools import handle_spotify_list_playlists
    result = handle_spotify_list_playlists(_make_ctx("spotify_list_playlists"))
    assert result.ok is True
    assert "Openings Anime" in result.message
    assert "pl1" in result.message
    assert "42" in result.message
    assert "Los mejores openings" in result.message
    assert "Workout" in result.message


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._get")
def test_list_playlists_empty(mock_get, _):
    mock_get.return_value = _mock_response(200, {"items": []})
    from app.tools.handlers.spotify_tools import handle_spotify_list_playlists
    result = handle_spotify_list_playlists(_make_ctx("spotify_list_playlists"))
    assert result.ok is True
    assert "no hay" in result.message.lower()


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._get")
def test_list_playlists_error(mock_get, _):
    mock_get.return_value = _mock_response(401)
    from app.tools.handlers.spotify_tools import handle_spotify_list_playlists
    result = handle_spotify_list_playlists(_make_ctx("spotify_list_playlists"))
    assert result.ok is False
    assert "401" in result.message


# ---------------------------------------------------------------------------
# spotify_playlist_tracks
# ---------------------------------------------------------------------------

@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._get")
def test_playlist_tracks_happy(mock_get, _):
    mock_get.return_value = _mock_response(200, {
        "total": 42,
        "items": [
            {"track": {"name": "Silhouette", "uri": "spotify:track:s1", "artists": [{"name": "KANA-BOON"}]}},
            {"track": {"name": "Blue Bird", "uri": "spotify:track:s2", "artists": [{"name": "Ikimono-gakari"}]}},
        ]
    })
    from app.tools.handlers.spotify_tools import handle_spotify_playlist_tracks
    result = handle_spotify_playlist_tracks(_make_ctx("spotify_playlist_tracks", {"playlist_id": "pl1"}))
    assert result.ok is True
    assert "Silhouette" in result.message
    assert "KANA-BOON" in result.message
    assert "Blue Bird" in result.message
    assert "2 de 42" in result.message


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._get")
def test_playlist_tracks_empty(mock_get, _):
    mock_get.return_value = _mock_response(200, {"total": 0, "items": []})
    from app.tools.handlers.spotify_tools import handle_spotify_playlist_tracks
    result = handle_spotify_playlist_tracks(_make_ctx("spotify_playlist_tracks", {"playlist_id": "pl1"}))
    assert result.ok is True
    assert "vacía" in result.message.lower()


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
def test_playlist_tracks_missing_id(_):
    from app.tools.handlers.spotify_tools import handle_spotify_playlist_tracks
    result = handle_spotify_playlist_tracks(_make_ctx("spotify_playlist_tracks", {}))
    assert result.ok is False
    assert "playlist_id" in result.message


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._get")
def test_playlist_tracks_error(mock_get, _):
    mock_get.return_value = _mock_response(404)
    from app.tools.handlers.spotify_tools import handle_spotify_playlist_tracks
    result = handle_spotify_playlist_tracks(_make_ctx("spotify_playlist_tracks", {"playlist_id": "bad_id"}))
    assert result.ok is False
    assert "404" in result.message


# ---------------------------------------------------------------------------
# spotify_play — URI short-circuit
# ---------------------------------------------------------------------------

@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._put")
@patch("app.tools.handlers.spotify_tools._save_previous_context")
@patch("app.tools.handlers.spotify_tools._search_uri")
def test_play_with_spotify_uri_skips_search(mock_search, mock_save, mock_put, _):
    """Passing a spotify: URI directly must NOT call _search_uri."""
    mock_put.return_value = _mock_response(204)
    from app.tools.handlers.spotify_tools import handle_spotify_play
    result = handle_spotify_play(_make_ctx("spotify_play", {"query": "spotify:playlist:pl1"}))
    assert result.ok is True
    mock_search.assert_not_called()
    call_kwargs = mock_put.call_args
    assert call_kwargs.kwargs["body"] == {"context_uri": "spotify:playlist:pl1"}


@patch("app.tools.handlers.spotify_tools.is_spotify_connected", return_value=True)
@patch("app.tools.handlers.spotify_tools._put")
@patch("app.tools.handlers.spotify_tools._save_previous_context")
@patch("app.tools.handlers.spotify_tools._search_uri")
def test_play_with_track_uri_skips_search(mock_search, mock_save, mock_put, _):
    mock_put.return_value = _mock_response(204)
    from app.tools.handlers.spotify_tools import handle_spotify_play
    result = handle_spotify_play(_make_ctx("spotify_play", {"query": "spotify:track:t1"}))
    assert result.ok is True
    mock_search.assert_not_called()
    call_kwargs = mock_put.call_args
    assert call_kwargs.kwargs["body"] == {"uris": ["spotify:track:t1"]}
