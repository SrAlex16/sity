from __future__ import annotations

import json

_ALWAYS_REDACT: frozenset[str] = frozenset({
    "write_file",
    "apply_text_patch",
    "apply_unified_diff",
    "apply_multi_file_unified_diff_plan",
})


def redact_tool_call_input(
    tool_name: str,
    input_value: object,
    *,
    max_chars: int = 300,
) -> dict:
    """Return a structural log summary of a tool call input.

    Always-redact tools (write_file, apply_*) expose only key names and
    serialized length — no content preview. For other tools the preview
    is included but capped at max_chars.
    """
    always_redact = tool_name in _ALWAYS_REDACT

    if input_value is None:
        return {"type": "none", "redacted": False}

    if isinstance(input_value, str):
        length = len(input_value)
        redacted = always_redact or length > max_chars
        result: dict = {"type": "str", "length": length, "redacted": redacted}
        if not always_redact:
            result["preview"] = input_value[:max_chars]
        return result

    if isinstance(input_value, list):
        return {"type": "list", "length": len(input_value), "redacted": always_redact}

    if isinstance(input_value, dict):
        keys = sorted(input_value.keys())
        try:
            raw = json.dumps(input_value, ensure_ascii=False)
        except Exception:
            raw = str(input_value)
        length = len(raw)
        redacted = always_redact or length > max_chars
        result = {"type": "dict", "keys": keys, "length": length, "redacted": redacted}
        if not always_redact:
            result["preview"] = raw[:max_chars]
        return result

    # Fallback for unexpected scalar types
    raw = str(input_value)
    length = len(raw)
    redacted = always_redact or length > max_chars
    result = {"type": type(input_value).__name__, "length": length, "redacted": redacted}
    if not always_redact:
        result["preview"] = raw[:max_chars]
    return result
