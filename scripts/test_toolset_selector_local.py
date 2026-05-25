#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> None:
    from app.chat.toolset_selector import select_toolset_for_message

    def toolset_names(message: str) -> set[str]:
        return {t["name"] for t in select_toolset_for_message(message)}

    def assert_has_tool(message: str, tool: str) -> None:
        names = toolset_names(message)
        assert tool in names, f"Expected {tool!r} in toolset for {message!r}. Got: {sorted(names)}"

    def assert_no_tool(message: str, tool: str) -> None:
        names = toolset_names(message)
        assert tool not in names, f"Expected {tool!r} NOT in toolset for {message!r}. Got: {sorted(names)}"

    # ── Explicit tool names in message (index path) ───────────────────────────
    print("==> explicit tool names")
    assert_has_tool("usa la herramienta capture_camera_snapshot es una orden", "capture_camera_snapshot")
    assert_has_tool("usa la herramienta record_audio_sample es una orden", "record_audio_sample")
    assert_has_tool("usa la herramienta list_camera_devices es una orden", "list_camera_devices")
    assert_has_tool("usa la herramienta git_read_status", "git_read_status")
    assert_has_tool("usa la herramienta read_system_status", "read_system_status")
    print("[OK] explicit tool names in toolset")

    # ── Natural language sense domain (regex roots path) ──────────────────────
    print("==> natural language sense roots")
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

    # ── Conversational messages do NOT add sense toolset ──────────────────────
    print("==> conversational messages excluded")
    assert_no_tool("qué tal estás hoy", "capture_camera_snapshot")
    assert_no_tool("cuéntame algo interesante", "record_audio_sample")
    assert_no_tool("yo he descubierto que soy inmortal", "capture_camera_snapshot")
    print("[OK] conversational messages do not include sense tools")

    # ── 'herramienta' no triggers ram/system toolset (word-boundary fix) ──────
    print("==> word-boundary regression")
    assert_no_tool("usa la herramienta list_directory", "read_system_status")
    print("[OK] 'herramienta' does not trigger system toolset via 'ram'")

    print("\ntoolset selector local test ok")


if __name__ == "__main__":
    main()
