"""Tests for app.training.dataset_stats.

Pure unit tests: all operate on in-memory fake message objects,
no DB access required for the core computation.
One integration smoke test verifies the /debug/dataset-stats endpoint.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.training.dataset_stats import (
    BASE_VECTOR,
    TARGETS,
    _CANON_THRESHOLD,
    _compute_tags,
    _is_operational,
    _l2_distance,
    _primary_bucket,
    build_consecutive_pairs,
    compute_dataset_stats,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)


def _msg(
    role: str,
    text: str = "texto",
    tone_meta: str | None = None,
    dataset_source: str | None = "normal_use",
    dataset_eligible: bool = True,
    dataset_tags_json: str | None = None,
    created_at: datetime = _NOW,
) -> SimpleNamespace:
    return SimpleNamespace(
        role=role,
        text=text,
        tone_meta=tone_meta,
        dataset_source=dataset_source,
        dataset_eligible=dataset_eligible,
        dataset_tags_json=dataset_tags_json,
        created_at=created_at,
    )


def _base_tone(**overrides: float) -> str:
    """Return tone_meta JSON at BASE_VECTOR values with optional overrides."""
    tone = dict(BASE_VECTOR)
    tone.update(overrides)
    tone["refusal_mode"] = "normal"
    tone["persona_profile"] = "base"
    return json.dumps(tone)


def _pair(
    user_text: str = "hola",
    sity_text: str = "Hola.",
    tone_meta: str | None = None,
    dataset_source: str | None = "normal_use",
    dataset_eligible: bool = True,
    dataset_tags_json: str | None = None,
) -> list[SimpleNamespace]:
    if tone_meta is None:
        tone_meta = _base_tone()
    return [
        _msg("user", user_text, dataset_source=dataset_source, dataset_eligible=dataset_eligible),
        _msg("sity", sity_text, tone_meta=tone_meta, dataset_source=dataset_source,
             dataset_eligible=dataset_eligible, dataset_tags_json=dataset_tags_json),
    ]


# ---------------------------------------------------------------------------
# _is_operational
# ---------------------------------------------------------------------------

def test_operational_budget_exhausted() -> None:
    assert _is_operational("Presupuesto diario de IA agotado.")


def test_operational_local_only() -> None:
    assert _is_operational("Modo local-only activo.")


def test_operational_provider_not_configured() -> None:
    assert _is_operational("Local AI provider not configured.")


def test_normal_text_not_operational() -> None:
    assert not _is_operational("Hola, ¿qué tal?")


# ---------------------------------------------------------------------------
# build_consecutive_pairs
# ---------------------------------------------------------------------------

def test_consecutive_pair_basic() -> None:
    msgs = [_msg("user", "hola"), _msg("sity", "Hola.")]
    pairs = build_consecutive_pairs(msgs)
    assert len(pairs) == 1
    assert pairs[0][0].role == "user"
    assert pairs[0][1].role == "sity"


def test_two_pairs_counted() -> None:
    msgs = (
        _pair("hola", "Hola.") +
        _pair("cómo estás?", "Bien.")
    )
    assert len(build_consecutive_pairs(msgs)) == 2


def test_double_user_not_a_pair() -> None:
    msgs = [_msg("user"), _msg("user"), _msg("sity")]
    pairs = build_consecutive_pairs(msgs)
    assert len(pairs) == 1


def test_double_sity_not_a_pair() -> None:
    msgs = [_msg("user"), _msg("sity"), _msg("sity")]
    pairs = build_consecutive_pairs(msgs)
    assert len(pairs) == 1


def test_empty_messages_no_pairs() -> None:
    assert build_consecutive_pairs([]) == []


# ---------------------------------------------------------------------------
# _compute_tags
# ---------------------------------------------------------------------------

def test_sarcasm_high_tag() -> None:
    tone = dict(BASE_VECTOR, sarcasm=0.65)
    tags = _compute_tags(tone, "normal_use", None)
    assert "sarcasm_high" in tags


def test_rudeness_high_tag() -> None:
    tone = dict(BASE_VECTOR, mala_leche=0.55)
    tags = _compute_tags(tone, "normal_use", None)
    assert "rudeness_high" in tags


def test_warmth_high_tag() -> None:
    tone = dict(BASE_VECTOR, warmth=0.70)
    tags = _compute_tags(tone, "normal_use", None)
    assert "warmth_high" in tags


def test_brief_tag() -> None:
    tone = dict(BASE_VECTOR, verbosity=0.15)
    tags = _compute_tags(tone, "normal_use", None)
    assert "brief" in tags


def test_melancholy_high_tag() -> None:
    tone = dict(BASE_VECTOR, melancholy=0.55)
    tags = _compute_tags(tone, "normal_use", None)
    assert "melancholy_high" in tags


def test_tsundere_high_tag() -> None:
    tone = dict(BASE_VECTOR, tsundere=0.60)
    tags = _compute_tags(tone, "normal_use", None)
    assert "tsundere_high" in tags


def test_contrarian_high_tag() -> None:
    tone = dict(BASE_VECTOR, contrarian=0.55)
    tags = _compute_tags(tone, "normal_use", None)
    assert "contrarian_high" in tags


def test_multi_persona_from_dataset_source() -> None:
    tags = _compute_tags(BASE_VECTOR, "synthetic_claude_user", None)
    assert "multi_persona" in tags


def test_multi_persona_from_dataset_tags_json() -> None:
    dtags = json.dumps(["casual_taco", "multi_persona"])
    tags = _compute_tags(BASE_VECTOR, "normal_use", dtags)
    assert "multi_persona" in tags


def test_base_vector_no_variation_tags() -> None:
    tags = _compute_tags(BASE_VECTOR, "normal_use", None)
    variation_tags = {"sarcasm_high", "rudeness_high", "warmth_high",
                      "brief", "melancholy_high", "tsundere_high",
                      "contrarian_high", "multi_persona"}
    assert not variation_tags.intersection(tags)


# ---------------------------------------------------------------------------
# _l2_distance & _primary_bucket
# ---------------------------------------------------------------------------

def test_l2_distance_base_vector_is_zero() -> None:
    assert _l2_distance(BASE_VECTOR) == pytest.approx(0.0)


def test_l2_distance_increases_with_deviation() -> None:
    tone = dict(BASE_VECTOR, sarcasm=0.80)  # +0.55 from base 0.25
    assert _l2_distance(tone) > 0.40


def test_primary_bucket_canon_base() -> None:
    bucket = _primary_bucket([], BASE_VECTOR)
    assert bucket == "canon_base"


def test_primary_bucket_multi_persona_wins() -> None:
    bucket = _primary_bucket(["multi_persona", "sarcasm_high"], BASE_VECTOR)
    assert bucket == "multi_persona"


def test_primary_bucket_sarcasm_high() -> None:
    tone = dict(BASE_VECTOR, sarcasm=0.70)
    tags = _compute_tags(tone, "normal_use", None)
    bucket = _primary_bucket(tags, tone)
    assert bucket == "variation_sarcasm_high"


def test_primary_bucket_rudeness_high() -> None:
    tone = dict(BASE_VECTOR, mala_leche=0.60)
    tags = _compute_tags(tone, "normal_use", None)
    bucket = _primary_bucket(tags, tone)
    assert bucket == "variation_rudeness_high"


def test_primary_bucket_warm() -> None:
    tone = dict(BASE_VECTOR, warmth=0.75)
    tags = _compute_tags(tone, "normal_use", None)
    bucket = _primary_bucket(tags, tone)
    assert bucket == "variation_warm"


def test_primary_bucket_brief() -> None:
    tone = dict(BASE_VECTOR, verbosity=0.10)
    tags = _compute_tags(tone, "normal_use", None)
    bucket = _primary_bucket(tags, tone)
    assert bucket == "variation_brief"


# ---------------------------------------------------------------------------
# compute_dataset_stats — counters
# ---------------------------------------------------------------------------

def test_total_pairs_counted() -> None:
    msgs = _pair() + _pair()
    stats = compute_dataset_stats(msgs)
    assert stats["total_pairs"] == 2


def test_usable_pairs_all_valid() -> None:
    msgs = _pair() + _pair()
    stats = compute_dataset_stats(msgs)
    assert stats["usable_pairs"] == 2


def test_missing_tone_meta_counted() -> None:
    msgs = [_msg("user"), _msg("sity", tone_meta=None)]
    stats = compute_dataset_stats(msgs)
    assert stats["missing_tone_meta"] == 1
    assert stats["usable_pairs"] == 0


def test_ineligible_pairs_excluded() -> None:
    msgs = [
        _msg("user", dataset_eligible=False),
        _msg("sity", tone_meta=_base_tone(), dataset_eligible=False),
    ]
    stats = compute_dataset_stats(msgs)
    assert stats["ineligible_pairs"] == 1
    assert stats["usable_pairs"] == 0


def test_operational_guard_counted() -> None:
    msgs = [
        _msg("user"),
        _msg("sity", text="Presupuesto diario de IA agotado.", tone_meta=_base_tone()),
    ]
    stats = compute_dataset_stats(msgs)
    assert stats["operational_pairs"] == 1
    assert stats["usable_pairs"] == 0


def test_by_source_normal_use() -> None:
    msgs = _pair(dataset_source="normal_use")
    stats = compute_dataset_stats(msgs)
    assert stats["by_source"].get("normal_use", 0) == 1


def test_by_source_synthetic() -> None:
    tone = json.dumps(dict(BASE_VECTOR, refusal_mode="normal", persona_profile="base"))
    msgs = [
        _msg("user", dataset_source="synthetic_claude_user"),
        _msg("sity", tone_meta=tone, dataset_source="synthetic_claude_user"),
    ]
    stats = compute_dataset_stats(msgs)
    assert stats["by_source"].get("synthetic_claude_user", 0) == 1
    assert "multi_persona" in stats["by_primary_bucket"]


def test_by_primary_bucket_canon_base() -> None:
    msgs = _pair()  # base-vector tone
    stats = compute_dataset_stats(msgs)
    assert stats["by_primary_bucket"].get("canon_base", 0) == 1


def test_by_primary_bucket_sarcasm_high() -> None:
    tone = _base_tone(sarcasm=0.70)
    msgs = [_msg("user"), _msg("sity", tone_meta=tone)]
    stats = compute_dataset_stats(msgs)
    assert stats["by_primary_bucket"].get("variation_sarcasm_high", 0) == 1


def test_by_primary_bucket_rudeness_high() -> None:
    tone = _base_tone(mala_leche=0.60)
    msgs = [_msg("user"), _msg("sity", tone_meta=tone)]
    stats = compute_dataset_stats(msgs)
    assert stats["by_primary_bucket"].get("variation_rudeness_high", 0) == 1


def test_by_primary_bucket_warm() -> None:
    tone = _base_tone(warmth=0.75)
    msgs = [_msg("user"), _msg("sity", tone_meta=tone)]
    stats = compute_dataset_stats(msgs)
    assert stats["by_primary_bucket"].get("variation_warm", 0) == 1


def test_by_primary_bucket_brief() -> None:
    tone = _base_tone(verbosity=0.10)
    msgs = [_msg("user"), _msg("sity", tone_meta=tone)]
    stats = compute_dataset_stats(msgs)
    assert stats["by_primary_bucket"].get("variation_brief", 0) == 1


def test_by_tag_multi_label() -> None:
    tone = _base_tone(sarcasm=0.70, warmth=0.70)
    msgs = [_msg("user"), _msg("sity", tone_meta=tone)]
    stats = compute_dataset_stats(msgs)
    assert stats["by_tag"].get("sarcasm_high", 0) >= 1
    assert stats["by_tag"].get("warmth_high", 0) >= 1


# ---------------------------------------------------------------------------
# Targets / progress
# ---------------------------------------------------------------------------

def test_targets_all_present() -> None:
    stats = compute_dataset_stats([])
    for bucket in TARGETS:
        assert bucket in stats["targets"]


def test_progress_zero_when_no_pairs() -> None:
    stats = compute_dataset_stats([])
    assert stats["targets"]["canon_base"]["progress"] == 0.0


def test_progress_increases_with_pairs() -> None:
    msgs = _pair() * 10
    stats = compute_dataset_stats(msgs)
    assert stats["targets"]["canon_base"]["progress"] > 0


def test_progress_capped_at_one() -> None:
    # Feed more pairs than the target for a small bucket
    msgs = _pair() * 100
    # multi_persona target is 50; but these are canon_base, so check canon_base isn't > 1
    stats = compute_dataset_stats(msgs)
    for bucket_data in stats["targets"].values():
        assert bucket_data["progress"] <= 1.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_messages() -> None:
    stats = compute_dataset_stats([])
    assert stats["total_pairs"] == 0
    assert stats["usable_pairs"] == 0


def test_sity_tone_meta_preserved_in_pair() -> None:
    snap = _base_tone(sarcasm=0.40)
    msgs = [_msg("user"), _msg("sity", tone_meta=snap)]
    stats = compute_dataset_stats(msgs)
    assert stats["usable_pairs"] == 1


def test_recent_pairs_truncated_to_120() -> None:
    long_text = "a" * 200
    msgs = _pair(user_text=long_text, sity_text=long_text)
    stats = compute_dataset_stats(msgs)
    assert len(stats["recent_pairs"]) == 1
    assert len(stats["recent_pairs"][0]["user_text"]) <= 121  # 120 + "…"
    assert len(stats["recent_pairs"][0]["sity_text"]) <= 121


def test_recent_pairs_at_most_five() -> None:
    msgs: list = []
    for i in range(10):
        msgs += _pair(f"pregunta {i}", f"respuesta {i}")
    stats = compute_dataset_stats(msgs)
    assert len(stats["recent_pairs"]) <= 5


# ---------------------------------------------------------------------------
# Endpoint smoke test
# ---------------------------------------------------------------------------

def test_endpoint_dataset_stats_ok() -> None:
    from app.main import app
    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.get("/debug/dataset-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "total_pairs" in body
    assert "usable_pairs" in body
    assert "targets" in body
