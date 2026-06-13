"""
Pure computation module for dataset statistics over the single Sity timeline.

No DB access, no side effects.  Receives a flat ordered list of ChatMessage-like
objects and returns a stats dict suitable for JSON serialisation.

tone_meta field names (from persona_engine.py tone_snapshot):
  sarcasm, mala_leche, warmth, honesty, initiative, dry_humor,
  frialdad_afectiva, contrarian, patience, verbosity, helpfulness, melancholy
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Numeric base vector, keyed by tone_snapshot field names.
BASE_VECTOR: dict[str, float] = {
    "sarcasm":     0.25,
    "mala_leche":  0.15,
    "warmth":      0.35,
    "honesty":     0.90,
    "initiative":  0.05,
    "dry_humor":   0.30,
    "frialdad_afectiva": 0.20,
    "contrarian":  0.10,
    "patience":    0.65,
    "verbosity":   0.35,
    "helpfulness": 0.60,
    "melancholy":  0.15,
}

#: How many usable pairs each bucket needs for LoRA v1.
TARGETS: dict[str, int] = {
    "canon_base":             650,
    "variation_sarcasm_high":  60,
    "variation_rudeness_high": 60,
    "variation_warm":          60,
    "variation_brief":         60,
    "variation_melancholy":    40,
    "variation_frialdad_afectiva": 40,
    "multi_persona":           50,
}

#: L2-distance to BASE_VECTOR below which a pair is classified as canon_base.
_CANON_THRESHOLD = 0.20

#: Variation tag → primary bucket, in priority order (first match wins).
_TAG_TO_BUCKET: list[tuple[str, str]] = [
    ("sarcasm_high",    "variation_sarcasm_high"),
    ("rudeness_high",   "variation_rudeness_high"),
    ("warmth_high",     "variation_warm"),
    ("brief",           "variation_brief"),
    ("melancholy_high", "variation_melancholy"),
    ("frialdad_afectiva_high", "variation_frialdad_afectiva"),
]

#: Sity texts that are operational guards, not training data.
_OPERATIONAL_PREFIXES: tuple[str, ...] = (
    "presupuesto diario de ia agotado",
    "modo local-only activo.",
    "local ai provider not configured",
    'no hay ninguna acción pendiente activa. el "sí',
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_operational(text: str) -> bool:
    norm = (text or "").strip().lower()
    return any(norm.startswith(p) for p in _OPERATIONAL_PREFIXES)


def _parse_tone(tone_meta: str | None) -> dict[str, float] | None:
    if not tone_meta:
        return None
    try:
        data = json.loads(tone_meta)
        if not isinstance(data, dict):
            return None
        return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}
    except (json.JSONDecodeError, ValueError):
        return None


def _l2_distance(tone: dict[str, float]) -> float:
    total = sum(
        (tone.get(k, base) - base) ** 2
        for k, base in BASE_VECTOR.items()
    )
    return math.sqrt(total)


def _compute_tags(
    tone: dict[str, float],
    dataset_source: str | None,
    dataset_tags_json: str | None,
) -> list[str]:
    tags: list[str] = []

    if tone.get("sarcasm", 0.0) >= 0.60:
        tags.append("sarcasm_high")
    if tone.get("mala_leche", 0.0) >= 0.50:
        tags.append("rudeness_high")
    if tone.get("warmth", 0.0) >= 0.60:
        tags.append("warmth_high")
    if tone.get("verbosity", 1.0) <= 0.20:
        tags.append("brief")
    if tone.get("melancholy", 0.0) >= 0.50:
        tags.append("melancholy_high")
    if tone.get("frialdad_afectiva", 0.0) >= 0.50:
        tags.append("frialdad_afectiva_high")
    if tone.get("contrarian", 0.0) >= 0.50:
        tags.append("contrarian_high")

    # multi_persona: from dataset_source or dataset_tags_json
    is_multi = dataset_source == "synthetic_claude_user"
    if not is_multi and dataset_tags_json:
        try:
            parsed = json.loads(dataset_tags_json)
            if isinstance(parsed, list) and "multi_persona" in parsed:
                is_multi = True
        except (json.JSONDecodeError, ValueError):
            pass
    if is_multi:
        tags.append("multi_persona")

    return tags


def _primary_bucket(tags: list[str], tone: dict[str, float]) -> str:
    if "multi_persona" in tags:
        return "multi_persona"
    if _l2_distance(tone) < _CANON_THRESHOLD:
        return "canon_base"
    for tag, bucket in _TAG_TO_BUCKET:
        if tag in tags:
            return bucket
    return "unknown"


def _trunc(text: str, n: int = 120) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:n] + "…" if len(text) > n else text


def _dt_str(created_at: Any) -> str:
    if created_at is None:
        return ""
    if isinstance(created_at, datetime):
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return created_at.isoformat()
    return str(created_at)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_consecutive_pairs(messages: list[Any]) -> list[tuple[Any, Any]]:
    """Return (user_msg, sity_msg) pairs that are strictly consecutive."""
    pairs: list[tuple[Any, Any]] = []
    i = 0
    while i < len(messages) - 1:
        cur = messages[i]
        nxt = messages[i + 1]
        if getattr(cur, "role", None) == "user" and getattr(nxt, "role", None) == "sity":
            pairs.append((cur, nxt))
            i += 2
        else:
            i += 1
    return pairs


def compute_dataset_stats(
    messages: list[Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compute dataset statistics over an ordered list of ChatMessage-like objects.

    Args:
        messages: Ordered (by id/created_at) list of objects with attributes:
            role, text, tone_meta, dataset_source, dataset_eligible,
            dataset_tags_json, created_at.
        now: Timestamp for computed_at; defaults to UTC now.

    Returns:
        A JSON-serialisable dict with all stats.
    """
    computed_at = (now or datetime.now(timezone.utc)).isoformat()

    pairs = build_consecutive_pairs(messages)

    total_pairs = len(pairs)
    usable_pairs = 0
    missing_tone_meta = 0
    ineligible_pairs = 0
    operational_pairs = 0

    by_source: dict[str, int] = {}
    by_primary_bucket: dict[str, int] = {}
    by_tag: dict[str, int] = {}

    recent_usable: list[dict[str, Any]] = []

    for user_msg, sity_msg in pairs:
        user_text = getattr(user_msg, "text", "") or ""
        sity_text = getattr(sity_msg, "text", "") or ""

        if not user_text.strip() or not sity_text.strip():
            continue  # degenerate pair, skip entirely

        # Ineligible check (either message)
        user_eligible = getattr(user_msg, "dataset_eligible", True)
        sity_eligible = getattr(sity_msg, "dataset_eligible", True)
        if user_eligible is False or sity_eligible is False:
            ineligible_pairs += 1
            continue

        # Operational guard
        if _is_operational(sity_text):
            operational_pairs += 1
            continue

        # tone_meta required
        tone_raw = getattr(sity_msg, "tone_meta", None)
        tone = _parse_tone(tone_raw)
        if tone is None:
            missing_tone_meta += 1
            continue

        # Usable pair
        usable_pairs += 1

        source = getattr(user_msg, "dataset_source", None) or "normal_use"
        by_source[source] = by_source.get(source, 0) + 1

        dtags_json = getattr(sity_msg, "dataset_tags_json", None)
        tags = _compute_tags(tone, source, dtags_json)
        bucket = _primary_bucket(tags, tone)

        by_primary_bucket[bucket] = by_primary_bucket.get(bucket, 0) + 1
        for tag in tags:
            by_tag[tag] = by_tag.get(tag, 0) + 1

        recent_usable.append({
            "user_text":      _trunc(user_text),
            "sity_text":      _trunc(sity_text),
            "primary_bucket": bucket,
            "tags":           tags,
            "dataset_source": source,
            "created_at":     _dt_str(getattr(user_msg, "created_at", None)),
        })

    # Progress towards targets
    targets_progress: dict[str, dict[str, Any]] = {}
    for bucket, target in TARGETS.items():
        count = by_primary_bucket.get(bucket, 0)
        targets_progress[bucket] = {
            "count":    count,
            "target":   target,
            "progress": round(min(count / target, 1.0), 4) if target > 0 else 1.0,
        }

    return {
        "computed_at":       computed_at,
        "total_pairs":       total_pairs,
        "usable_pairs":      usable_pairs,
        "missing_tone_meta": missing_tone_meta,
        "ineligible_pairs":  ineligible_pairs,
        "operational_pairs": operational_pairs,
        "by_source":         by_source,
        "by_primary_bucket": by_primary_bucket,
        "by_tag":            by_tag,
        "targets":           targets_progress,
        "recent_pairs":      recent_usable[-5:],
    }
