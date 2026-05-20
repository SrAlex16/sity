from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

import yaml

from app.system_agent.file_audit import append_file_audit_event, create_file_backup


PROJECT_ROOT = Path("/home/alex/projects/sity")
CONFIG_PATH = PROJECT_ROOT / "config" / "system_access.yaml"

MAX_READ_BYTES = 120_000
MAX_READ_CHARS_FOR_MODEL = 12_000
MAX_WRITE_BYTES = 250_000
MAX_PATCH_PREVIEW_CHARS = 12_000
MAX_UNIFIED_DIFF_BYTES = 250_000
MAX_UNIFIED_DIFF_PREVIEW_CHARS = 20_000
MAX_DIRECTORY_ITEMS = 200


class FileAccessError(Exception):
    pass


def load_system_access_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _resolve_path(path_value: str) -> Path:
    path = Path(path_value).expanduser()

    if not path.is_absolute():
        path = PROJECT_ROOT / path

    return path.resolve()


def _configured_paths(section: str) -> list[Path]:
    config = load_system_access_config()
    file_access = config.get("file_access", {})
    values = file_access.get(section, [])

    paths: list[Path] = []

    for value in values:
        try:
            paths.append(_resolve_path(str(value)))
        except Exception:
            continue

    return paths


def _is_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _is_blocked(path: Path) -> bool:
    for blocked in _configured_paths("blocked_paths"):
        if _is_inside(path, blocked):
            return True

    return False


def _is_allowed(path: Path, section: str) -> bool:
    if _is_blocked(path):
        return False

    for allowed in _configured_paths(section):
        if _is_inside(path, allowed):
            return True

    return False


def assert_read_allowed(path: Path) -> None:
    if not _is_allowed(path, "readable_paths"):
        raise FileAccessError(f"Ruta no permitida para lectura: {path}")


def assert_write_allowed(path: Path) -> None:
    if not _is_allowed(path, "writable_paths"):
        raise FileAccessError(f"Ruta no permitida para escritura: {path}")


def read_file(path_value: str) -> dict[str, Any]:
    try:
        path = _resolve_path(path_value)
        assert_read_allowed(path)

        if not path.exists():
            return {"ok": False, "error": f"No existe el archivo: {path}"}

        if not path.is_file():
            return {"ok": False, "error": f"No es un archivo: {path}"}

        size = path.stat().st_size

        if size > MAX_READ_BYTES:
            return {
                "ok": False,
                "error": f"Archivo demasiado grande para leer completo: {size} bytes",
                "path": str(path),
                "size_bytes": size,
                "max_bytes": MAX_READ_BYTES,
            }

        content = path.read_text(encoding="utf-8", errors="replace")
        truncated = len(content) > MAX_READ_CHARS_FOR_MODEL

        return {
            "ok": True,
            "path": str(path),
            "size_bytes": size,
            "content": content[:MAX_READ_CHARS_FOR_MODEL],
            "truncated": truncated,
            "total_chars": len(content),
        }

    except FileAccessError as exc:
        return {"ok": False, "error": str(exc)}

    except Exception as exc:
        return {"ok": False, "error": f"Error leyendo archivo: {exc}"}


def write_file(
    path_value: str,
    content: str,
    *,
    create_parent_dirs: bool = False,
    pending_action_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    try:
        path = _resolve_path(path_value)
        assert_write_allowed(path)

        if path.exists() and not path.is_file():
            return {"ok": False, "error": f"La ruta existe pero no es un archivo: {path}"}

        content_bytes = content.encode("utf-8")
        if len(content_bytes) > MAX_WRITE_BYTES:
            return {
                "ok": False,
                "error": f"Contenido demasiado grande: {len(content_bytes)} bytes (máx {MAX_WRITE_BYTES}).",
            }

        if create_parent_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)

        if not path.parent.exists():
            return {
                "ok": False,
                "error": f"El directorio padre no existe: {path.parent}. Usa create_parent_dirs=true para crearlo.",
            }

        previous_exists = path.exists()
        previous_size = path.stat().st_size if previous_exists else None

        backup = create_file_backup(
            path,
            action="write_file",
            pending_action_id=pending_action_id,
            trace_id=trace_id,
        )

        path.write_text(content, encoding="utf-8")

        append_file_audit_event({
            "action": "write_file",
            "path": str(path),
            "pending_action_id": pending_action_id,
            "trace_id": trace_id,
            "created": not previous_exists,
            "previous_size_bytes": previous_size,
            "bytes_written": len(content_bytes),
            "backup": backup,
            "status": "ok",
        })

        return {
            "ok": True,
            "path": str(path),
            "created": not previous_exists,
            "previous_size_bytes": previous_size,
            "bytes_written": len(content_bytes),
            "backup": backup,
        }

    except FileAccessError as exc:
        return {"ok": False, "error": str(exc)}

    except Exception as exc:
        return {"ok": False, "error": f"Error escribiendo archivo: {exc}"}


def list_directory(path_value: str) -> dict[str, Any]:
    try:
        path = _resolve_path(path_value)
        assert_read_allowed(path)

        if not path.exists():
            return {"ok": False, "error": f"No existe el directorio: {path}"}

        if not path.is_dir():
            return {"ok": False, "error": f"No es un directorio: {path}"}

        items = []

        for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if _is_blocked(child.resolve()):
                continue

            stat = child.stat()

            items.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "type": "directory" if child.is_dir() else "file",
                    "size_bytes": stat.st_size if child.is_file() else None,
                }
            )

            if len(items) >= MAX_DIRECTORY_ITEMS:
                break

        return {
            "ok": True,
            "path": str(path),
            "items": items,
            "truncated": len(items) >= MAX_DIRECTORY_ITEMS,
            "max_items": MAX_DIRECTORY_ITEMS,
        }

    except FileAccessError as exc:
        return {"ok": False, "error": str(exc)}

    except Exception as exc:
        return {"ok": False, "error": f"Error listando directorio: {exc}"}


def preview_text_patch(
    path_value: str,
    old_text: str,
    new_text: str,
) -> dict[str, Any]:
    try:
        path = _resolve_path(path_value)
        assert_write_allowed(path)

        if not path.exists():
            return {"ok": False, "error": f"No existe el archivo: {path}"}

        if not path.is_file():
            return {"ok": False, "error": f"No es un archivo: {path}"}

        original_content = path.read_text(encoding="utf-8", errors="replace")

        if old_text not in original_content:
            return {
                "ok": False,
                "error": "No se encontró el texto exacto que se quería reemplazar.",
                "path": str(path),
            }

        updated_content = original_content.replace(old_text, new_text, 1)

        diff = "".join(
            difflib.unified_diff(
                original_content.splitlines(keepends=True),
                updated_content.splitlines(keepends=True),
                fromfile=str(path),
                tofile=str(path),
            )
        )

        truncated = len(diff) > MAX_PATCH_PREVIEW_CHARS
        if truncated:
            diff = diff[:MAX_PATCH_PREVIEW_CHARS] + "\n... diff truncado ...\n"

        return {
            "ok": True,
            "path": str(path),
            "diff": diff,
            "diff_truncated": truncated,
            "replacements": 1,
        }

    except FileAccessError as exc:
        return {"ok": False, "error": str(exc)}

    except Exception as exc:
        return {"ok": False, "error": f"Error generando preview de patch: {exc}"}


def apply_text_patch(
    path_value: str,
    old_text: str,
    new_text: str,
    *,
    pending_action_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    try:
        path = _resolve_path(path_value)
        assert_write_allowed(path)

        if not path.exists():
            return {"ok": False, "error": f"No existe el archivo: {path}"}

        if not path.is_file():
            return {"ok": False, "error": f"No es un archivo: {path}"}

        original_content = path.read_text(encoding="utf-8", errors="replace")

        if old_text not in original_content:
            return {
                "ok": False,
                "error": "No se encontró el texto exacto que se quería reemplazar.",
                "path": str(path),
            }

        updated_content = original_content.replace(old_text, new_text, 1)
        updated_bytes = updated_content.encode("utf-8")

        if len(updated_bytes) > MAX_WRITE_BYTES:
            return {
                "ok": False,
                "error": f"El archivo resultante sería demasiado grande: {len(updated_bytes)} bytes",
                "max_bytes": MAX_WRITE_BYTES,
            }

        backup = create_file_backup(
            path,
            action="apply_text_patch",
            pending_action_id=pending_action_id,
            trace_id=trace_id,
        )

        path.write_text(updated_content, encoding="utf-8")

        append_file_audit_event({
            "action": "apply_text_patch",
            "path": str(path),
            "pending_action_id": pending_action_id,
            "trace_id": trace_id,
            "bytes_written": len(updated_bytes),
            "replacements": 1,
            "backup": backup,
            "status": "ok",
        })

        return {
            "ok": True,
            "path": str(path),
            "bytes_written": len(updated_bytes),
            "replacements": 1,
            "backup": backup,
        }

    except FileAccessError as exc:
        return {"ok": False, "error": str(exc)}

    except Exception as exc:
        return {"ok": False, "error": f"Error aplicando patch: {exc}"}


def _strip_diff_path(value: str) -> str:
    value = value.strip()
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    return value


def _extract_single_file_from_unified_diff(diff_text: str) -> str | None:
    old_path: str | None = None
    new_path: str | None = None

    for line in diff_text.splitlines():
        if line.startswith("--- "):
            raw = line[4:].strip().split("\t", 1)[0]
            if raw != "/dev/null":
                old_path = _strip_diff_path(raw)
        elif line.startswith("+++ "):
            raw = line[4:].strip().split("\t", 1)[0]
            if raw != "/dev/null":
                new_path = _strip_diff_path(raw)

    path = new_path or old_path

    if not path:
        return None

    if old_path and new_path and old_path != new_path:
        raise FileAccessError("Los patches con rename/move todavía no están soportados.")

    return path


def _parse_unified_diff_hunks(diff_text: str) -> list[dict[str, Any]]:
    hunks: list[dict[str, Any]] = []
    current_hunk: dict[str, Any] | None = None

    hunk_header_re = re.compile(
        r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
        r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
    )

    for line in diff_text.splitlines(keepends=True):
        if line.startswith("--- ") or line.startswith("+++ "):
            continue

        match = hunk_header_re.match(line)
        if match:
            current_hunk = {
                "old_start": int(match.group("old_start")),
                "old_count": int(match.group("old_count") or "1"),
                "new_start": int(match.group("new_start")),
                "new_count": int(match.group("new_count") or "1"),
                "lines": [],
            }
            hunks.append(current_hunk)
            continue

        if current_hunk is None:
            continue

        if line.startswith((" ", "-", "+", "\\")):
            current_hunk["lines"].append(line)

    return hunks


def _apply_unified_diff_to_content(original_content: str, diff_text: str) -> str:
    original_lines = original_content.splitlines(keepends=True)
    hunks = _parse_unified_diff_hunks(diff_text)

    if not hunks:
        raise FileAccessError("El diff no contiene hunks aplicables.")

    result_lines: list[str] = []
    source_index = 0

    for hunk in hunks:
        hunk_source_index = int(hunk["old_start"]) - 1

        if hunk_source_index < source_index:
            raise FileAccessError("El diff tiene hunks solapados o desordenados.")

        result_lines.extend(original_lines[source_index:hunk_source_index])
        source_index = hunk_source_index

        for diff_line in hunk["lines"]:
            if diff_line.startswith("\\"):
                continue

            marker = diff_line[:1]
            text = diff_line[1:]

            if marker == " ":
                if source_index >= len(original_lines):
                    raise FileAccessError("El contexto del diff excede el archivo original.")
                if original_lines[source_index] != text:
                    raise FileAccessError("El contexto del diff no coincide con el archivo original.")
                result_lines.append(original_lines[source_index])
                source_index += 1

            elif marker == "-":
                if source_index >= len(original_lines):
                    raise FileAccessError("El diff intenta eliminar más líneas de las existentes.")
                if original_lines[source_index] != text:
                    raise FileAccessError("La línea a eliminar no coincide con el archivo original.")
                source_index += 1

            elif marker == "+":
                result_lines.append(text)

            else:
                raise FileAccessError(f"Línea de diff no soportada: {diff_line!r}")

    result_lines.extend(original_lines[source_index:])
    return "".join(result_lines)


def preview_unified_diff(diff_text: str) -> dict[str, Any]:
    try:
        diff_bytes = diff_text.encode("utf-8")

        if len(diff_bytes) > MAX_UNIFIED_DIFF_BYTES:
            return {
                "ok": False,
                "error": f"Diff demasiado grande: {len(diff_bytes)} bytes",
                "max_bytes": MAX_UNIFIED_DIFF_BYTES,
            }

        path_value = _extract_single_file_from_unified_diff(diff_text)

        if not path_value:
            return {"ok": False, "error": "No se pudo extraer la ruta del archivo desde el diff."}

        path = _resolve_path(path_value)
        assert_write_allowed(path)

        if not path.exists():
            return {"ok": False, "error": f"No existe el archivo: {path}"}

        if not path.is_file():
            return {"ok": False, "error": f"No es un archivo: {path}"}

        original_content = path.read_text(encoding="utf-8", errors="replace")
        updated_content = _apply_unified_diff_to_content(original_content, diff_text)

        if original_content == updated_content:
            return {"ok": False, "error": "El diff no produce cambios.", "path": str(path)}

        normalized_diff = "".join(
            difflib.unified_diff(
                original_content.splitlines(keepends=True),
                updated_content.splitlines(keepends=True),
                fromfile=str(path),
                tofile=str(path),
            )
        )

        truncated = len(normalized_diff) > MAX_UNIFIED_DIFF_PREVIEW_CHARS
        if truncated:
            normalized_diff = normalized_diff[:MAX_UNIFIED_DIFF_PREVIEW_CHARS] + "\n... diff truncado ...\n"

        return {
            "ok": True,
            "path": str(path),
            "diff": normalized_diff,
            "diff_truncated": truncated,
            "bytes_after": len(updated_content.encode("utf-8")),
        }

    except FileAccessError as exc:
        return {"ok": False, "error": str(exc)}

    except Exception as exc:
        return {"ok": False, "error": f"Error generando preview de unified diff: {exc}"}


def apply_unified_diff(
    diff_text: str,
    *,
    pending_action_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    try:
        diff_bytes = diff_text.encode("utf-8")

        if len(diff_bytes) > MAX_UNIFIED_DIFF_BYTES:
            return {
                "ok": False,
                "error": f"Diff demasiado grande: {len(diff_bytes)} bytes",
                "max_bytes": MAX_UNIFIED_DIFF_BYTES,
            }

        path_value = _extract_single_file_from_unified_diff(diff_text)

        if not path_value:
            return {"ok": False, "error": "No se pudo extraer la ruta del archivo desde el diff."}

        path = _resolve_path(path_value)
        assert_write_allowed(path)

        if not path.exists():
            return {"ok": False, "error": f"No existe el archivo: {path}"}

        if not path.is_file():
            return {"ok": False, "error": f"No es un archivo: {path}"}

        original_content = path.read_text(encoding="utf-8", errors="replace")
        updated_content = _apply_unified_diff_to_content(original_content, diff_text)

        if original_content == updated_content:
            return {"ok": False, "error": "El diff no produce cambios.", "path": str(path)}

        updated_bytes = updated_content.encode("utf-8")

        if len(updated_bytes) > MAX_WRITE_BYTES:
            return {
                "ok": False,
                "error": f"El archivo resultante sería demasiado grande: {len(updated_bytes)} bytes",
                "max_bytes": MAX_WRITE_BYTES,
            }

        backup = create_file_backup(
            path,
            action="apply_unified_diff",
            pending_action_id=pending_action_id,
            trace_id=trace_id,
        )

        previous_size = path.stat().st_size
        path.write_text(updated_content, encoding="utf-8")

        append_file_audit_event({
            "action": "apply_unified_diff",
            "path": str(path),
            "pending_action_id": pending_action_id,
            "trace_id": trace_id,
            "previous_size_bytes": previous_size,
            "bytes_written": len(updated_bytes),
            "backup": backup,
            "status": "ok",
        })

        return {
            "ok": True,
            "path": str(path),
            "previous_size_bytes": previous_size,
            "bytes_written": len(updated_bytes),
            "backup": backup,
        }

    except FileAccessError as exc:
        return {"ok": False, "error": str(exc)}

    except Exception as exc:
        return {"ok": False, "error": f"Error aplicando unified diff: {exc}"}


def split_unified_diff_by_file(diff_text: str) -> dict[str, Any]:
    try:
        diff_bytes = diff_text.encode("utf-8")

        if len(diff_bytes) > MAX_UNIFIED_DIFF_BYTES:
            return {
                "ok": False,
                "error": f"Diff demasiado grande: {len(diff_bytes)} bytes",
                "max_bytes": MAX_UNIFIED_DIFF_BYTES,
            }

        file_diffs: list[str] = []
        current_lines: list[str] = []
        seen_file_header = False

        for line in diff_text.splitlines(keepends=True):
            if line.startswith("--- ") and seen_file_header and current_lines:
                file_diffs.append("".join(current_lines))
                current_lines = [line]
                continue

            if line.startswith("--- "):
                seen_file_header = True

            if seen_file_header:
                current_lines.append(line)

        if current_lines:
            file_diffs.append("".join(current_lines))

        if not file_diffs:
            return {
                "ok": False,
                "error": "No se encontraron diffs de archivo en el unified diff.",
            }

        items: list[dict[str, Any]] = []

        for file_diff in file_diffs:
            path_value = _extract_single_file_from_unified_diff(file_diff)

            if not path_value:
                return {
                    "ok": False,
                    "error": "No se pudo extraer una ruta de uno de los diffs.",
                }

            preview = preview_unified_diff(file_diff)

            if not preview.get("ok"):
                return {
                    "ok": False,
                    "error": (
                        "Plan multiarchivo rechazado completo. "
                        f"El archivo {path_value!r} no pasó validación: "
                        f"{preview.get('error', 'Diff inválido')}. "
                        "No se ha creado ninguna acción pendiente. "
                        "No se debe aplicar parcialmente este patch. "
                        "Si el usuario quiere aplicar solo los archivos permitidos, debe enviar un patch nuevo "
                        "que excluya explícitamente los archivos bloqueados."
                    ),
                    "path": path_value,
                    "rejected_entire_plan": True,
                    "allow_partial_apply": False,
                }

            items.append({
                "path": preview.get("path"),
                "diff": file_diff,
                "preview_diff": preview.get("diff", ""),
                "bytes_after": preview.get("bytes_after"),
                "diff_truncated": preview.get("diff_truncated", False),
            })

        return {
            "ok": True,
            "count": len(items),
            "items": items,
        }

    except FileAccessError as exc:
        return {"ok": False, "error": str(exc)}

    except Exception as exc:
        return {"ok": False, "error": f"Error separando unified diff multiarchivo: {exc}"}
