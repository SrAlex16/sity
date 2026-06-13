"""Tests for compute_edit_distance_pct — pure function, no mocks needed."""
from __future__ import annotations

import pytest

from app.audio.edit_distance import compute_edit_distance_pct


def test_identical_strings_return_zero() -> None:
    assert compute_edit_distance_pct("hola mundo", "hola mundo") == 0.0


def test_identical_after_strip() -> None:
    assert compute_edit_distance_pct("  hola  ", "hola") == 0.0


def test_completely_different_strings() -> None:
    pct = compute_edit_distance_pct("aaa", "zzz")
    assert pct == 1.0


def test_original_empty_returns_one() -> None:
    assert compute_edit_distance_pct("", "algo") == 1.0


def test_final_empty_returns_one() -> None:
    assert compute_edit_distance_pct("algo", "") == 1.0


def test_both_empty_returns_zero() -> None:
    assert compute_edit_distance_pct("", "") == 0.0


def test_both_empty_after_strip_returns_zero() -> None:
    assert compute_edit_distance_pct("   ", "   ") == 0.0


def test_partial_edit_between_zero_and_one() -> None:
    pct = compute_edit_distance_pct("el gato come pescado", "el gato come carne")
    assert 0.0 < pct < 1.0


def test_single_char_added() -> None:
    pct = compute_edit_distance_pct("hola", "holas")
    assert 0.0 < pct < 0.5


def test_result_is_rounded_to_four_decimals() -> None:
    pct = compute_edit_distance_pct("abc", "abx")
    assert pct == round(pct, 4)


def test_returns_float() -> None:
    result = compute_edit_distance_pct("a", "b")
    assert isinstance(result, float)


def test_order_matters() -> None:
    # edit distance between A→B and B→A is the same (SequenceMatcher is symmetric)
    pct_ab = compute_edit_distance_pct("abc", "xyz")
    pct_ba = compute_edit_distance_pct("xyz", "abc")
    assert pct_ab == pct_ba


def test_high_similarity_gives_low_pct() -> None:
    # One word change in a long sentence → low edit distance
    pct = compute_edit_distance_pct(
        "necesito que me muestres el fichero de configuración",
        "necesito que me muestres el fichero de configuracion",
    )
    assert pct < 0.15


def test_full_rewrite_gives_high_pct() -> None:
    pct = compute_edit_distance_pct("pon música", "apaga la calefacción")
    assert pct > 0.5
