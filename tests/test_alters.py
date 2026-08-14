"""Tests for AlterService (Paso 1 — modelo + servicio, sin endpoints HTTP).

Coverage:
  - list_alters returns exactly 5 slots, all empty by default
  - save_alter stores parameters from a session; list_alters shows filled slot
  - Two users have isolated slot spaces (user_id 1 vs user_id 2)
  - load_alter on empty slot raises ValueError (clear error, no crash)
  - load_alter applies all 14 values to the session
  - clear_alter empties the slot (row deleted, list_alters shows empty again)
  - rename_alter changes name only (parameters unchanged)
  - copy_alter overwrites destination completely (no leftover from old dest)
  - copy_alter copies the name as well as parameters
  - save_alter overwrites an existing slot (idempotent re-save)
  - slot out of range raises ValueError
  - set_all_personality applies 14 values to target session without affecting others
  - set_all_personality rejects unknown keys and missing keys
"""
from __future__ import annotations

import pytest
from sqlmodel import SQLModel, Session, create_engine

from app.settings.settings_service import CANONICAL_PERSONALITY, PERSONALITY_KEYS, SettingsService
from app.settings.alter_service import AlterService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_session() -> Session:
    """In-memory SQLite session with all tables created."""
    import app.memory.models as _models  # noqa: F401 — registers all tables
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _full_personality(base: float = 0.5) -> dict[str, float]:
    """Return a complete 14-key personality dict with a uniform base value."""
    return {k: round(base, 4) for k in PERSONALITY_KEYS}


# ---------------------------------------------------------------------------
# list_alters
# ---------------------------------------------------------------------------

def test_list_alters_all_empty_by_default() -> None:
    with _make_session() as session:
        svc = AlterService(session)
        slots = svc.list_alters(user_id=1)
    assert len(slots) == 5
    for i, slot in enumerate(slots, start=1):
        assert slot["slot"] == i
        assert slot["is_empty"] is True
        assert slot["name"] is None
        assert slot["parameters"] is None


# ---------------------------------------------------------------------------
# save_alter
# ---------------------------------------------------------------------------

def test_save_alter_stores_session_personality() -> None:
    with _make_session() as session:
        settings = SettingsService(session)
        settings.set_all_personality("user:1", _full_personality(0.42))

        svc = AlterService(session)
        result = svc.save_alter(user_id=1, slot=2, name="Modo frío", current_session_id="user:1")

    assert result["slot"] == 2
    assert result["name"] == "Modo frío"
    assert result["is_empty"] is False
    assert len(result["parameters"]) == 14
    assert result["parameters"]["sarcasm_level"] == pytest.approx(0.42)


def test_list_alters_shows_filled_slot_after_save() -> None:
    with _make_session() as session:
        settings = SettingsService(session)
        settings.set_all_personality("user:1", _full_personality(0.7))

        svc = AlterService(session)
        svc.save_alter(user_id=1, slot=3, name="Alter 3", current_session_id="user:1")
        slots = svc.list_alters(user_id=1)

    assert slots[2]["slot"] == 3
    assert slots[2]["is_empty"] is False
    assert slots[2]["name"] == "Alter 3"
    # Other slots still empty
    for i in [0, 1, 3, 4]:
        assert slots[i]["is_empty"] is True


def test_save_alter_overwrites_existing_slot() -> None:
    with _make_session() as session:
        settings = SettingsService(session)
        settings.set_all_personality("user:1", _full_personality(0.1))
        svc = AlterService(session)
        svc.save_alter(user_id=1, slot=1, name="Primero", current_session_id="user:1")

        # Change session personality and save again to the same slot
        settings.set_all_personality("user:1", _full_personality(0.9))
        svc.save_alter(user_id=1, slot=1, name="Actualizado", current_session_id="user:1")

        slots = svc.list_alters(user_id=1)

    filled = [s for s in slots if not s["is_empty"]]
    assert len(filled) == 1  # still only 1 row, not 2
    assert filled[0]["name"] == "Actualizado"
    assert filled[0]["parameters"]["warmth_level"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# User isolation
# ---------------------------------------------------------------------------

def test_two_users_have_isolated_slots() -> None:
    with _make_session() as session:
        settings = SettingsService(session)
        settings.set_all_personality("user:1", _full_personality(0.2))
        settings.set_all_personality("user:2", _full_personality(0.8))

        svc = AlterService(session)
        svc.save_alter(user_id=1, slot=1, name="U1-Slot1", current_session_id="user:1")
        svc.save_alter(user_id=2, slot=1, name="U2-Slot1", current_session_id="user:2")

        u1_slots = svc.list_alters(user_id=1)
        u2_slots = svc.list_alters(user_id=2)

    assert u1_slots[0]["name"] == "U1-Slot1"
    assert u1_slots[0]["parameters"]["sarcasm_level"] == pytest.approx(0.2)
    assert u2_slots[0]["name"] == "U2-Slot1"
    assert u2_slots[0]["parameters"]["sarcasm_level"] == pytest.approx(0.8)

    # User 2 has not touched slots 2-5
    for i in range(1, 5):
        assert u2_slots[i]["is_empty"] is True


# ---------------------------------------------------------------------------
# load_alter
# ---------------------------------------------------------------------------

def test_load_alter_empty_slot_raises() -> None:
    with _make_session() as session:
        svc = AlterService(session)
        with pytest.raises(ValueError, match="empty"):
            svc.load_alter(user_id=1, slot=4, session_id="user:1")


def test_load_alter_applies_all_14_values_to_session() -> None:
    target_values = _full_personality(0.33)
    with _make_session() as session:
        settings = SettingsService(session)
        settings.set_all_personality("user:1", target_values)

        svc = AlterService(session)
        svc.save_alter(user_id=1, slot=5, name="Carga", current_session_id="user:1")

        # Change session to something different
        settings.set_all_personality("user:1", _full_personality(0.99))

        result = svc.load_alter(user_id=1, slot=5, session_id="user:1")

    assert len(result) == 14
    for key in PERSONALITY_KEYS:
        assert result[key] == pytest.approx(0.33, abs=1e-4), f"Mismatch on {key}"


def test_load_alter_does_not_affect_other_sessions() -> None:
    target_values = _full_personality(0.25)
    with _make_session() as session:
        settings = SettingsService(session)
        settings.set_all_personality("user:1", target_values)
        settings.set_all_personality("user:2", _full_personality(0.75))

        svc = AlterService(session)
        svc.save_alter(user_id=1, slot=1, name="Alter", current_session_id="user:1")
        svc.load_alter(user_id=1, slot=1, session_id="user:1")

        # user:2 session untouched
        u2_personality = settings.get_personality(session_id="user:2")

    for key in PERSONALITY_KEYS:
        assert u2_personality[key] == pytest.approx(0.75, abs=1e-4), f"user:2 affected at {key}"


# ---------------------------------------------------------------------------
# rename_alter
# ---------------------------------------------------------------------------

def test_rename_alter_changes_name_only() -> None:
    with _make_session() as session:
        settings = SettingsService(session)
        settings.set_all_personality("user:1", _full_personality(0.55))
        svc = AlterService(session)
        svc.save_alter(user_id=1, slot=2, name="Original", current_session_id="user:1")
        svc.rename_alter(user_id=1, slot=2, new_name="Renombrado")
        slots = svc.list_alters(user_id=1)

    slot2 = slots[1]
    assert slot2["name"] == "Renombrado"
    assert slot2["parameters"]["patience_level"] == pytest.approx(0.55)


def test_rename_alter_empty_slot_raises() -> None:
    with _make_session() as session:
        svc = AlterService(session)
        with pytest.raises(ValueError, match="empty"):
            svc.rename_alter(user_id=1, slot=3, new_name="X")


# ---------------------------------------------------------------------------
# clear_alter
# ---------------------------------------------------------------------------

def test_clear_alter_empties_slot() -> None:
    with _make_session() as session:
        settings = SettingsService(session)
        settings.set_all_personality("user:1", _full_personality(0.5))
        svc = AlterService(session)
        svc.save_alter(user_id=1, slot=1, name="Borrar", current_session_id="user:1")
        svc.clear_alter(user_id=1, slot=1)
        slots = svc.list_alters(user_id=1)

    assert slots[0]["is_empty"] is True


def test_clear_alter_already_empty_is_noop() -> None:
    with _make_session() as session:
        svc = AlterService(session)
        svc.clear_alter(user_id=1, slot=2)  # no exception
        assert svc.list_alters(user_id=1)[1]["is_empty"] is True


# ---------------------------------------------------------------------------
# copy_alter
# ---------------------------------------------------------------------------

def test_copy_alter_overwrites_destination_completely() -> None:
    with _make_session() as session:
        settings = SettingsService(session)
        # Slot 1: warmth 0.9
        settings.set_all_personality("user:1", _full_personality(0.9))
        svc = AlterService(session)
        svc.save_alter(user_id=1, slot=1, name="Cálido", current_session_id="user:1")
        # Slot 2: warmth 0.1
        settings.set_all_personality("user:1", _full_personality(0.1))
        svc.save_alter(user_id=1, slot=2, name="Frío", current_session_id="user:1")

        svc.copy_alter(user_id=1, from_slot=1, to_slot=2)
        slots = svc.list_alters(user_id=1)

    slot2 = slots[1]
    assert slot2["name"] == "Cálido"
    assert slot2["parameters"]["warmth_level"] == pytest.approx(0.9)
    # No leftover from the old slot 2 content
    assert slot2["parameters"]["sarcasm_level"] == pytest.approx(0.9)


def test_copy_alter_also_copies_name() -> None:
    with _make_session() as session:
        settings = SettingsService(session)
        settings.set_all_personality("user:1", _full_personality(0.6))
        svc = AlterService(session)
        svc.save_alter(user_id=1, slot=1, name="Nombre original", current_session_id="user:1")
        result = svc.copy_alter(user_id=1, from_slot=1, to_slot=3)

    assert result["name"] == "Nombre original"


def test_copy_alter_source_empty_raises() -> None:
    with _make_session() as session:
        svc = AlterService(session)
        with pytest.raises(ValueError, match="empty"):
            svc.copy_alter(user_id=1, from_slot=4, to_slot=5)


# ---------------------------------------------------------------------------
# slot validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("slot", [0, 6, -1, 99])
def test_invalid_slot_raises(slot: int) -> None:
    with _make_session() as session:
        svc = AlterService(session)
        with pytest.raises(ValueError, match="Slot"):
            svc._validate_slot(slot)


# ---------------------------------------------------------------------------
# set_all_personality (SettingsService)
# ---------------------------------------------------------------------------

def test_set_all_personality_applies_all_14_values() -> None:
    values = {k: 0.5 for k in PERSONALITY_KEYS}
    values["sarcasm_level"] = 0.77
    values["warmth_level"] = 0.11

    with _make_session() as session:
        svc = SettingsService(session)
        result = svc.set_all_personality("user:42", values)

    assert len(result) == 14
    assert result["sarcasm_level"] == pytest.approx(0.77)
    assert result["warmth_level"] == pytest.approx(0.11)


def test_set_all_personality_rejects_unknown_key() -> None:
    values = {k: 0.5 for k in PERSONALITY_KEYS}
    values["nonexistent_param"] = 0.5

    with _make_session() as session:
        svc = SettingsService(session)
        with pytest.raises(ValueError, match="Unknown"):
            svc.set_all_personality("user:1", values)


def test_set_all_personality_rejects_missing_keys() -> None:
    values = {"sarcasm_level": 0.5}  # only 1 of 14 keys

    with _make_session() as session:
        svc = SettingsService(session)
        with pytest.raises(ValueError, match="Missing"):
            svc.set_all_personality("user:1", values)


def test_set_all_personality_does_not_affect_other_sessions() -> None:
    with _make_session() as session:
        svc = SettingsService(session)
        # session A starts with canonical defaults (no row = inherits global)
        before_a = svc.get_personality(session_id="user:A")

        # session B writes different values
        svc.set_all_personality("user:B", _full_personality(0.88))

        after_a = svc.get_personality(session_id="user:A")

    for key in PERSONALITY_KEYS:
        assert before_a[key] == pytest.approx(after_a[key], abs=1e-4), f"session A affected at {key}"
