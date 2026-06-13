"""Edit distance between voice transcript and final sent text."""
from __future__ import annotations

from difflib import SequenceMatcher


def compute_edit_distance_pct(original: str, final: str) -> float:
    """Return the fraction of characters changed (0.0 = identical, 1.0 = completely different).

    Uses SequenceMatcher ratio so insertions, deletions and substitutions
    all count proportionally to the total length.
    """
    o = original.strip()
    f = final.strip()
    if o == f:
        return 0.0
    if not o or not f:
        return 1.0
    ratio = SequenceMatcher(None, o, f).ratio()
    return round(1.0 - ratio, 4)
