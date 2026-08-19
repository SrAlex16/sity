"""Shared JSON parsing utilities for initiative Haiku calls."""


def strip_json_fences(text: str) -> str:
    """Strip markdown code fences that models sometimes wrap around JSON responses."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    return text.strip()
