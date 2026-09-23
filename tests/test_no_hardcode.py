"""Guardrails estáticos contra hardcodes problemáticos en código de producción.

Tres categorías:
  a) Nombres propios en prompts y persona_engine.py
  b) Rutas de filesystem absolutas /home/<user>/ en backend/app/
  c) Emails de admin en código de producción fuera de los archivos permitidos

Mecanismo de escape: # HARDCODED_OK: <razón>
  Añadir este comentario en la línea del match O en la línea anterior lo marca
  como aprobado. Usar solo cuando el hardcode esté justificado (p.ej., ejemplo
  en docstring de un prompt de Haiku, dominio de ejemplo en config de SMTP).

Regresión de referencia — commit 009c845:
  Eliminó "Alex" de persona_engine.py:454 y prompts/local_persona_system.md.
  Si se reintroduce en cualquiera de los dos sitios, estas pruebas fallan en
  CI antes de que el nombre llegue al prompt del modelo.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_APP = _ROOT / "backend" / "app"
_PROMPTS = _APP / "prompts"
_PERSONA_ENGINE = _APP / "core" / "persona_engine.py"


def _has_escape(lines: list[str], lineno: int) -> bool:
    """True if `lines[lineno]` or its predecessor carries # HARDCODED_OK:."""
    if "# HARDCODED_OK:" in lines[lineno]:
        return True
    if lineno > 0 and "# HARDCODED_OK:" in lines[lineno - 1]:
        return True
    return False


# ---------------------------------------------------------------------------
# a) Nombres propios en prompts y persona_engine.py
# ---------------------------------------------------------------------------

_NAMES_RE = re.compile(r"\b(Alex|Alejandro|alejandro)\b")


def test_no_hardcoded_names_in_prompt_files() -> None:
    """Ningún .md en prompts/ contiene nombres propios hardcodeados.

    Regresión: 009c845 eliminó "Alex" de local_persona_system.md línea 4.
    Si alguien reintroduce un nombre, este test falla en CI.
    """
    for path in _PROMPTS.rglob("*.md"):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            m = _NAMES_RE.search(line)
            if m and not _has_escape(lines, i):
                raise AssertionError(
                    f"{path.name}:{i + 1}: nombre hardcodeado '{m.group()}' — "
                    "usa variable de plantilla o añade # HARDCODED_OK: <razón>"
                )


def test_no_hardcoded_names_in_persona_engine() -> None:
    """persona_engine.py no contiene nombres propios en strings literales.

    Regresión: 009c845 eliminó "Alex" de persona_engine.py:454 (bloque else
    del interlocutor_block). La persona no debe saber el nombre del usuario
    salvo que el usuario se lo diga en la conversación.
    """
    lines = _PERSONA_ENGINE.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        m = _NAMES_RE.search(line)
        if m and not _has_escape(lines, i):
            raise AssertionError(
                f"persona_engine.py:{i + 1}: nombre hardcodeado '{m.group()}' — "
                "usa variable de plantilla o añade # HARDCODED_OK: <razón>"
            )


# ---------------------------------------------------------------------------
# b) Rutas absolutas /home/<user>/ en código de producción
# ---------------------------------------------------------------------------

_HOME_PATH_RE = re.compile(r"/home/[A-Za-z_][A-Za-z0-9_-]*/")


def _py_sources() -> list[tuple[Path, list[str]]]:
    return [
        (p, p.read_text(encoding="utf-8").splitlines())
        for p in _APP.rglob("*.py")
        if "__pycache__" not in str(p)
    ]


def test_no_absolute_user_paths_in_production_code() -> None:
    """Ningún .py de producción contiene /home/<user>/ como ruta ejecutable.

    Las rutas absolutas deben venir de variables de entorno o runtime_config,
    no hardcodeadas. Las líneas de comentario (#) están exentas.
    Excepciones: usa # HARDCODED_OK: en la misma línea o la anterior.
    """
    for path, lines in _py_sources():
        for i, line in enumerate(lines):
            if line.lstrip().startswith("#"):
                continue
            m = _HOME_PATH_RE.search(line)
            if m and not _has_escape(lines, i):
                raise AssertionError(
                    f"{path.relative_to(_ROOT)}:{i + 1}: ruta absoluta "
                    f"'{m.group()}' — usa env var / runtime_config, "
                    "o añade # HARDCODED_OK: <razón>"
                )


# ---------------------------------------------------------------------------
# c) Emails de admin en código de producción
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Archivos donde emails de ejemplo o configuración son esperados
_EMAIL_ALLOWLIST = {
    "admin_seeder.py",  # lee el email de env var SITY_ADMIN_EMAIL, no hardcodeado
    "email_stub.py",    # docstring con ejemplo de dominio SMTP (no-reply@sity.aletm.com)
}


def test_no_hardcoded_admin_email_in_production_code() -> None:
    """Ningún .py de producción (fuera de allowlist) contiene emails literales.

    Los emails de admin/usuario deben venir de SITY_ADMIN_EMAIL u otras
    variables de entorno, nunca como literales en el código.
    Las líneas de comentario (#) están exentas.
    """
    for path, lines in _py_sources():
        if path.name in _EMAIL_ALLOWLIST:
            continue
        for i, line in enumerate(lines):
            if line.lstrip().startswith("#"):
                continue
            m = _EMAIL_RE.search(line)
            if m and not _has_escape(lines, i):
                raise AssertionError(
                    f"{path.relative_to(_ROOT)}:{i + 1}: email literal "
                    f"'{m.group()}' — usa variable de entorno, "
                    "o añade # HARDCODED_OK: <razón>"
                )
