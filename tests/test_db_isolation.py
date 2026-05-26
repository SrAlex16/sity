"""Regression tests for pytest DB isolation.

These tests verify two invariants:

1. The engine used during pytest is NOT the production data/app.db.
   If this fails, every test run that touches SettingsService would
   corrupt personality settings in the dev environment.

2. No personality test hardcodes 0.5 as a write value.
   0.5 caused the verbosity_level regression bug (tests → prod DB pollution).
   Personality defaults are 0.45 (verbosity) or specific values per param;
   use 0.73 or another unique non-default value in tests that need a write.
"""
from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# 1. Engine URL isolation
# ---------------------------------------------------------------------------

def test_test_engine_is_not_production_db() -> None:
    """The pytest engine must never point at data/app.db."""
    from app.memory.db import engine

    url = str(engine.url)
    assert "data/app.db" not in url, (
        f"Tests are connected to the production database: {url!r}. "
        "SITY_DB_URL must be set in conftest.py before app.memory.db is imported."
    )


def test_test_engine_url_contains_test_marker() -> None:
    """Test DB URL should include a recognisable test marker."""
    from app.memory.db import engine

    url = str(engine.url)
    markers = ("pytest", "test", "/tmp/", "\\tmp\\")
    assert any(m in url for m in markers), (
        f"Test DB URL doesn't contain any of {markers}: {url!r}. "
        "Is SITY_DB_URL pointing at a dedicated test database?"
    )


# ---------------------------------------------------------------------------
# 2. Source-level guard: no personality test writes 0.5
# ---------------------------------------------------------------------------

def test_no_personality_test_hardcodes_0_5_as_write_value() -> None:
    """Verify that no test file writes 0.5 to a personality parameter.

    Personality defaults are NOT 0.5 (verbosity default is 0.45).  Using 0.5
    in a test that writes to SettingsService produced a silent regression where
    verbosity_level appeared reset every time the test suite ran.

    Legitimate exception: a test that explicitly validates that 0.5 is accepted
    as an arbitrary in-range value should document it with a comment and
    will need to be allow-listed here.
    """
    tests_dir = Path(__file__).resolve().parent
    suspect_patterns = (
        '"value": 0.5,',
        '"value": 0.5}',
        '"value": 0.50',
        "'value': 0.5",
    )
    offenders: list[str] = []

    for test_file in sorted(tests_dir.glob("test_*.py")):
        if test_file.name == Path(__file__).name:
            continue  # skip this guard file itself

        content = test_file.read_text(encoding="utf-8")

        # Only check files that interact with personality writes.
        if (
            "update_personality_settings" not in content
            and "adjust_personality" not in content
        ):
            continue

        for pattern in suspect_patterns:
            if pattern in content:
                offenders.append(f"{test_file.name}: found {pattern!r}")

    assert not offenders, (
        "The following test(s) hardcode 0.5 as a personality write value — "
        "use 0.73 (or another non-default, non-ambiguous value) instead:\n"
        + "\n".join(f"  • {o}" for o in offenders)
    )
