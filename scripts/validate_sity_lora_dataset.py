#!/usr/bin/env python3
"""
validate_sity_lora_dataset.py
─────────────────────────────
Valida archivos JSONL de dataset LoRA Sity antes de entrenar.

Comprobaciones:
  - JSONL válido (cada línea es JSON parseable)
  - messages[0] role == "user", messages[1] role == "assistant"
  - content no vacío en ambos roles
  - pair_id único dentro de cada archivo
  - sin frases prohibidas de asistente genérico en el assistant
  - train y eval no comparten pair_id (si se pasan los dos)

Uso:
  python scripts/validate_sity_lora_dataset.py TRAIN [EVAL]
  python scripts/validate_sity_lora_dataset.py datasets/sity_style_v0/train_style_v0.jsonl datasets/sity_style_v0/eval_style_v0.jsonl
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ─── Frases prohibidas en el assistant ───────────────────────────────────────
# Indicadores de respuesta RLHF genérica o anti-Sity.

FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("como_ia",        re.compile(r"\bcomo\s+(ia|modelo de lenguaje|asistente de ia|inteligencia artificial|bot|chatbot)\b", re.IGNORECASE)),
    ("no_preferencias",re.compile(r"no tengo (preferencias|opiniones|sentimientos|emociones|experiencias personales)", re.IGNORECASE)),
    ("soy_modelo",     re.compile(r"\b(soy\s+solo\s+un\s+programa|soy\s+un\s+modelo|no\s+soy\s+humano)\b", re.IGNORECASE)),
    ("aqui_ayudar",    re.compile(r"estoy\s+aquí\s+para\s+ayudarte", re.IGNORECASE)),
    ("puedo_ayudarte", re.compile(r"\ben\s+qué\s+(más\s+)?puedo\s+ayudarte", re.IGNORECASE)),
    ("lo_siento_pero", re.compile(r"lo\s+siento[,.]?\s+pero\b", re.IGNORECASE)),
    ("lenguaje_ofens", re.compile(r"lenguaje\s+(ofensivo|inapropiado)", re.IGNORECASE)),
    ("tono_respetuoso",re.compile(r"\btono\s+respetuoso\b", re.IGNORECASE)),
    ("por_supuesto",   re.compile(r"^[¡!]?por\s+supuesto[!,.]?", re.IGNORECASE)),
    ("claro_exclam",   re.compile(r"^[¡!]claro[!,.]", re.IGNORECASE)),
]


def validate_file(path: Path, label: str) -> tuple[list[str], set[str]]:
    """Valida un archivo JSONL. Devuelve (errores, pair_ids_encontrados)."""
    errors: list[str] = []
    seen_ids: set[str] = set()

    if not path.exists():
        return [f"{label}: archivo no encontrado: {path}"], set()

    lines = path.read_text(encoding="utf-8").splitlines()
    valid_count = 0

    for lineno, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        # 1. JSON válido
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{label}:{lineno}: JSON inválido — {exc}")
            continue

        pair_id = obj.get("pair_id", f"<línea {lineno}>")

        # 2. pair_id único
        if pair_id in seen_ids:
            errors.append(f"{label}:{lineno}: pair_id duplicado: {pair_id!r}")
        seen_ids.add(pair_id)

        # 3. messages presente y bien formado
        messages = obj.get("messages")
        if not isinstance(messages, list) or len(messages) < 2:
            errors.append(f"{label}:{lineno} [{pair_id}]: messages ausente o < 2 entradas")
            continue

        user_msg = messages[0]
        asst_msg = messages[1]

        if user_msg.get("role") != "user":
            errors.append(f"{label}:{lineno} [{pair_id}]: messages[0].role != 'user' (es {user_msg.get('role')!r})")

        if asst_msg.get("role") != "assistant":
            errors.append(f"{label}:{lineno} [{pair_id}]: messages[1].role != 'assistant' (es {asst_msg.get('role')!r})")

        user_content = user_msg.get("content", "").strip()
        asst_content = asst_msg.get("content", "").strip()

        if not user_content:
            errors.append(f"{label}:{lineno} [{pair_id}]: user content vacío")

        if not asst_content:
            errors.append(f"{label}:{lineno} [{pair_id}]: assistant content vacío")
            continue

        # 4. Frases prohibidas en assistant
        for name, pat in FORBIDDEN_PATTERNS:
            if pat.search(asst_content):
                errors.append(f"{label}:{lineno} [{pair_id}]: frase prohibida [{name}] en assistant: {asst_content[:80]!r}")

        valid_count += 1

    return errors, seen_ids


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: validate_sity_lora_dataset.py TRAIN [EVAL]", file=sys.stderr)
        sys.exit(1)

    train_path = Path(sys.argv[1])
    eval_path  = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    all_errors: list[str] = []

    train_errors, train_ids = validate_file(train_path, "train")
    all_errors.extend(train_errors)

    eval_ids: set[str] = set()
    if eval_path:
        eval_errors, eval_ids = validate_file(eval_path, "eval")
        all_errors.extend(eval_errors)

        # 5. Sin solapamiento train ∩ eval
        overlap = train_ids & eval_ids
        if overlap:
            for pid in sorted(overlap):
                all_errors.append(f"OVERLAP: pair_id {pid!r} aparece en train y eval")

    if all_errors:
        print(f"ERRORES ({len(all_errors)}):", file=sys.stderr)
        for err in all_errors:
            print(f"  {err}", file=sys.stderr)
        sys.exit(1)

    parts = [f"train={len(train_ids)}"]
    if eval_path:
        parts.append(f"eval={len(eval_ids)}")
    if train_ids and eval_ids:
        parts.append("no overlap")
    print(f"OK — {', '.join(parts)}")


if __name__ == "__main__":
    main()
