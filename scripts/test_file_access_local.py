#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_ROOT))


from app.system_agent.file_access import (  # noqa: E402
    apply_text_patch,
    apply_unified_diff,
    list_directory,
    preview_text_patch,
    preview_unified_diff,
    read_file,
    split_unified_diff_by_file,
    write_file,
)
from app.system_agent.file_audit import (  # noqa: E402
    find_latest_reversible_file_change,
)


TEST_DIR = PROJECT_ROOT / "config"
WRITE_TEST = TEST_DIR / "local-file-access-test.txt"
PATCH_TEST = TEST_DIR / "local-file-access-patch.txt"
DIFF_TEST = TEST_DIR / "local-file-access-diff.txt"
MULTI_A = TEST_DIR / "local-file-access-multi-a.txt"
MULTI_B = TEST_DIR / "local-file-access-multi-b.txt"


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def ok(message: str) -> None:
    print(f"[OK] {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)
    ok(message)


def require_result_ok(result: dict, label: str) -> None:
    if not result.get("ok"):
        print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
        fail(label)
    ok(label)


def require_result_not_ok(result: dict, label: str) -> None:
    if result.get("ok"):
        print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
        fail(label)
    ok(label)


def cleanup() -> None:
    for path in [WRITE_TEST, PATCH_TEST, DIFF_TEST, MULTI_A, MULTI_B]:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def main() -> None:
    cleanup()

    print("==> read/list allowed")

    result = list_directory(str(TEST_DIR))
    require_result_ok(result, "list_directory allowed config")

    result = read_file(str(PROJECT_ROOT / "README.md"))
    require_result_ok(result, "read_file allows README.md")

    print("==> read/list blocked outside repo")

    result = list_directory("/home/alex/Documents")
    require_result_not_ok(result, "list_directory blocks /home/alex/Documents")

    result = read_file("/etc/passwd")
    require_result_not_ok(result, "read_file blocks /etc/passwd")

    print("==> blocked sensitive paths (secrets and VCS internals)")

    blocked_read_paths = [
        ".git/config",
        ".env",
        ".env.local",
        "backend/.env",
        "backend/.env.local",
        "frontend/.env",
        "frontend/.env.local",
    ]

    for rel_path in blocked_read_paths:
        abs_path = str(PROJECT_ROOT / rel_path)
        result = read_file(abs_path)
        require_result_not_ok(result, f"read_file blocks {rel_path}")

    print("==> write_file allowed")

    result = write_file(
        str(WRITE_TEST),
        "hola local",
        pending_action_id="local_test_write",
        trace_id="local_trace",
    )
    require_result_ok(result, "write_file allowed config")
    require(WRITE_TEST.read_text(encoding="utf-8") == "hola local", "write_file content")

    print("==> write_file blocked")

    result = write_file(
        "/home/alex/Documents/local-file-access-test.txt",
        "hola",
        pending_action_id="local_test_blocked",
        trace_id="local_trace",
    )
    require_result_not_ok(result, "write_file blocks /home/alex/Documents")

    result = write_file(
        str(PROJECT_ROOT / ".env"),
        "NOPE=1",
        pending_action_id="local_test_env",
        trace_id="local_trace",
    )
    require_result_not_ok(result, "write_file blocks .env")

    print("==> text patch")

    PATCH_TEST.write_text("alfa\nbeta\ngamma\n", encoding="utf-8")

    preview = preview_text_patch(str(PATCH_TEST), "beta", "beta mod")
    require_result_ok(preview, "preview_text_patch")

    result = apply_text_patch(
        str(PATCH_TEST),
        "beta",
        "beta mod",
        pending_action_id="local_test_patch",
        trace_id="local_trace",
    )
    require_result_ok(result, "apply_text_patch")
    require("beta mod" in PATCH_TEST.read_text(encoding="utf-8"), "apply_text_patch content")

    result = preview_text_patch(str(PROJECT_ROOT / ".env"), "A", "B")
    require_result_not_ok(result, "preview_text_patch blocks .env")

    print("==> unified diff")

    DIFF_TEST.write_text("linea uno\nlinea dos\nlinea tres\n", encoding="utf-8")

    diff = (
        "--- config/local-file-access-diff.txt\n"
        "+++ config/local-file-access-diff.txt\n"
        "@@ -1,3 +1,4 @@\n"
        " linea uno\n"
        "-linea dos\n"
        "+linea dos modificada\n"
        " linea tres\n"
        "+linea cuatro\n"
    )

    preview = preview_unified_diff(diff)
    require_result_ok(preview, "preview_unified_diff")

    result = apply_unified_diff(
        diff,
        pending_action_id="local_test_unified",
        trace_id="local_trace",
    )
    require_result_ok(result, "apply_unified_diff")
    require("linea cuatro" in DIFF_TEST.read_text(encoding="utf-8"), "apply_unified_diff content")

    blocked_diff = (
        "--- .env\n"
        "+++ .env\n"
        "@@ -1 +1 @@\n"
        "-A=1\n"
        "+B=2\n"
    )
    result = preview_unified_diff(blocked_diff)
    require_result_not_ok(result, "preview_unified_diff blocks .env")

    print("==> multi-file split")

    MULTI_A.write_text("a uno\na dos\na tres\n", encoding="utf-8")
    MULTI_B.write_text("b uno\nb dos\nb tres\n", encoding="utf-8")

    multi_diff = (
        "--- config/local-file-access-multi-a.txt\n"
        "+++ config/local-file-access-multi-a.txt\n"
        "@@ -1,3 +1,3 @@\n"
        " a uno\n"
        "-a dos\n"
        "+a dos modificado\n"
        " a tres\n"
        "--- config/local-file-access-multi-b.txt\n"
        "+++ config/local-file-access-multi-b.txt\n"
        "@@ -1,3 +1,4 @@\n"
        " b uno\n"
        " b dos\n"
        "-b tres\n"
        "+b tres modificado\n"
        "+b cuatro\n"
    )

    split = split_unified_diff_by_file(multi_diff)
    require_result_ok(split, "split_unified_diff_by_file")
    require(split.get("count") == 2, "split_unified_diff_by_file count")

    blocked_multi_diff = (
        "--- config/local-file-access-multi-a.txt\n"
        "+++ config/local-file-access-multi-a.txt\n"
        "@@ -1,3 +1,3 @@\n"
        " a uno\n"
        "-a dos\n"
        "+a dos otra vez\n"
        " a tres\n"
        "--- .env\n"
        "+++ .env\n"
        "@@ -1 +1 @@\n"
        "-A=1\n"
        "+B=2\n"
    )

    split = split_unified_diff_by_file(blocked_multi_diff)
    require_result_not_ok(split, "split_unified_diff_by_file rejects blocked plan")
    require(bool(split.get("rejected_entire_plan")), "blocked multi-file rejects entire plan")

    print("==> latest reversible lookup")

    latest = find_latest_reversible_file_change()
    require(isinstance(latest, dict), "find_latest_reversible_file_change returns dict")

    cleanup()
    ok("All local file access tests passed")


if __name__ == "__main__":
    main()
