#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> None:
    from app.chat.toolset_selector import (
        message_mentions_action_id,
        select_toolset_for_message,
    )

    def toolset_names(message: str) -> set[str]:
        return {t["name"] for t in select_toolset_for_message(message)}

    def assert_has_tool(message: str, tool: str) -> None:
        names = toolset_names(message)
        assert tool in names, (
            f"Expected {tool!r} in toolset for {message!r}.\nGot: {sorted(names)}"
        )

    def assert_no_tool(message: str, tool: str) -> None:
        names = toolset_names(message)
        assert tool not in names, (
            f"Expected {tool!r} NOT in toolset for {message!r}.\nGot: {sorted(names)}"
        )

    # ── Structural: explicit tool names (index path) ──────────────────────────
    print("==> structural: explicit tool names")
    assert_has_tool("usa la herramienta capture_camera_snapshot es una orden", "capture_camera_snapshot")
    assert_has_tool("usa la herramienta record_audio_sample es una orden", "record_audio_sample")
    assert_has_tool("usa la herramienta list_camera_devices es una orden", "list_camera_devices")
    assert_has_tool("usa la herramienta git_read_status", "git_read_status")
    assert_has_tool("usa la herramienta read_system_status", "read_system_status")
    assert_has_tool("usa la herramienta cancel_pending_action para cancelar act_deadbeef", "cancel_pending_action")
    print("[OK] explicit tool names reach correct toolset")

    # ── Structural: action ID detection ──────────────────────────────────────
    print("==> structural: action ID detection")
    assert message_mentions_action_id("cancela act_deadbeef por favor")
    assert message_mentions_action_id("usa cancel_pending_action para cancelar act_1a2b3c4d")
    assert not message_mentions_action_id("no hay ningún ID aquí")
    assert not message_mentions_action_id("act_tooshort")       # 7 hex chars — invalid
    assert not message_mentions_action_id("act_toolongabcdef")  # 9+ chars — invalid
    print("[OK] message_mentions_action_id works correctly")

    # ── Structural: file path ────────────────────────────────────────────────
    print("==> structural: file path")
    assert_has_tool("edita backend/app/core/tool_executor.py", "read_file")
    assert_has_tool("lee config/settings.json", "read_file")
    print("[OK] file path detection reaches FILE_AGENT_TOOLSET")

    # ── Legacy NL fallback: sense domain ─────────────────────────────────────
    print("==> legacy NL fallback: sense domain")
    natural_sense_cases = [
        ("saca una captura", "capture_camera_snapshot"),
        ("saca una foto", "capture_camera_snapshot"),
        ("abre la cámara", "capture_camera_snapshot"),
        ("quiero ver la webcam", "capture_camera_snapshot"),
        ("graba audio", "record_audio_sample"),
        ("quiero grabar una muestra", "record_audio_sample"),
        ("prueba el micrófono", "record_audio_sample"),
        ("limpia capturas antiguas", "clean_old_captures"),
        ("cuánto espacio ocupan las capturas", "get_capture_storage_summary"),
    ]
    for message, expected_tool in natural_sense_cases:
        assert_has_tool(message, expected_tool)
        print(f"[OK] {message!r} → {expected_tool}")

    # ── Conversational: no extra toolsets beyond BASE ─────────────────────────
    print("==> conversational messages stay in BASE_TOOLSET")
    assert_no_tool("qué tal estás hoy", "capture_camera_snapshot")
    assert_no_tool("cuéntame algo interesante", "record_audio_sample")
    assert_no_tool("yo he descubierto que soy inmortal", "capture_camera_snapshot")
    print("[OK] conversational messages do not include sense tools")

    # ── Word-boundary regression: 'herramienta' must not trigger system tools ─
    print("==> word-boundary regression")
    assert_no_tool("usa la herramienta list_directory", "read_system_status")
    print("[OK] 'herramienta' does not trigger system toolset via 'ram'")

    print("\ntoolset selector local test ok")


if __name__ == "__main__":
    main()
