from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path("/home/alex/projects/sity")
CONFIG_PATH = PROJECT_ROOT / "config" / "system_access.yaml"

MAX_READ_BYTES = 120_000
MAX_READ_CHARS_FOR_MODEL = 12_000
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
