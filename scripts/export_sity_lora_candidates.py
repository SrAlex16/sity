#!/usr/bin/env python3
"""
export_sity_lora_candidates.py
──────────────────────────────
Extrae pares conversacionales user→sity de data/app.db para el dataset
de fine-tuning LoRA Sity v0.

Salida:
  datasets/sity_style_v0/train_candidates.jsonl
  datasets/sity_style_v0/review.md

Reglas:
  - Solo pares consecutivos (user seguido de sity en el mismo session_id).
  - Excluye respuestas mecánicas, tool outputs, mensajes operativos y frases prohibidas.
  - No modifica la DB. No llama a APIs externas.
  - Añade flags de calidad para revisión manual.

Uso:
  python scripts/export_sity_lora_candidates.py [--db PATH] [--out-dir DIR] [--include-seeds]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

# ─── Rutas por defecto ───────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_DB   = PROJECT_ROOT / "data" / "app.db"
DEFAULT_OUT  = PROJECT_ROOT / "datasets" / "sity_style_v0"
MANUAL_SEED  = DEFAULT_OUT / "manual_seed.jsonl"
REJECT_PATS  = DEFAULT_OUT / "reject_patterns.txt"

# ─── Frases prohibidas (modelo genérico / anti-Sity) ─────────────────────────
# Si aparecen en la respuesta de Sity, el par se marca con flag "generic_ai".

FORBIDDEN_PHRASES: list[str] = [
    "como ia",
    "como modelo de lenguaje",
    "como asistente de ia",
    "como inteligencia artificial",
    "no tengo preferencias",
    "no tengo opiniones",
    "no tengo sentimientos",
    "no puedo tener opiniones",
    "no puedo sentir",
    "no tengo emociones",
    "soy solo un programa",
    "soy un modelo",
    "no soy humano",
    "no tengo experiencias personales",
    "como bot",
    "como chatbot",
    "¿en qué puedo ayudarte?",
    "¿cómo puedo ayudarte",
    "espero que esto te sea útil",
    "espero haberte ayudado",
    "si tienes más preguntas",
    "por supuesto",            # filler corporativo
    "¡claro!",
    "¡genial!",
    "¡excelente!",
    "¡por supuesto!",
    "¡entendido!",
    "¡con mucho gusto",
    "encantada de ayudarte",
    "estoy aquí para ayudarte",
]

# ─── Patrones de rechazo estructural ─────────────────────────────────────────
# Respuestas que son outputs de tool/sistema, no voz de Sity.

STRUCTURAL_REJECT_PATTERNS: list[re.Pattern] = [
    # Confirmaciones de acción pendiente
    re.compile(r"acción(es)? pendiente(s)? creada", re.IGNORECASE),
    re.compile(r"confirma con:?\s*`confirmo ejecutar act_", re.IGNORECASE),
    # Tool outputs literales
    re.compile(r"unified diff aplicado:", re.IGNORECASE),
    re.compile(r"patch aplicado:", re.IGNORECASE),
    re.compile(r"archivo (creado|sobreescrito):", re.IGNORECASE),
    re.compile(r"rollback aplicado:", re.IGNORECASE),
    re.compile(r"acción ejecutada:", re.IGNORECASE),
    re.compile(r"acción\s+act_[a-f0-9]{8}\s+cancelada", re.IGNORECASE),
    # Budget/local-only guard
    re.compile(r"presupuesto diario de ia agotado", re.IGNORECASE),
    re.compile(r"modo local-only activo", re.IGNORECASE),
    # Respuestas mock del MockProvider
    re.compile(r"^respuesta mock\.$", re.IGNORECASE),
    re.compile(r"^hecho\.$", re.IGNORECASE),
    # Pseudo tool calls (que no filtra ResponseGuard en producción porque ya bloqueó)
    re.compile(r"<function_calls>", re.IGNORECASE),
    re.compile(r"<invoke\s+name=", re.IGNORECASE),
    re.compile(r"<tool_use>", re.IGNORECASE),
    # La acción no está pendiente / ya fue ejecutada
    re.compile(r"no está pendiente;\s*su estado actual", re.IGNORECASE),
    re.compile(r"no encuentro ninguna acción con id", re.IGNORECASE),
    re.compile(r"ya existe una acción pendiente equivalente", re.IGNORECASE),
]

# ─── Patrones de baja calidad (flag, no rechazo automático) ──────────────────

LOW_QUALITY_PATTERNS: list[re.Pattern] = [
    re.compile(r"```"),                                      # bloque de código (puede ser ok, pero flagear)
    re.compile(r"act_[a-f0-9]{8}"),                         # ID de acción en texto final
    re.compile(r"\bconfirma con\b", re.IGNORECASE),         # prompt de confirmación
    re.compile(r"\bdiff\b.*\bgit\b|\bgit\b.*\bdiff\b", re.IGNORECASE),
    re.compile(r"backup_path|audit_log|trace_id", re.IGNORECASE),
    re.compile(r"^\s*ok\s*$", re.IGNORECASE),               # respuesta vacía disfrazada
    re.compile(r"^\s*hecho\s*$", re.IGNORECASE),
]

# ─── Longitud mínima / máxima ─────────────────────────────────────────────────

MIN_ASSISTANT_LEN = 15    # caracteres
MAX_ASSISTANT_LEN = 1800  # evitar monstruos de 10 párrafos poco representativos
MIN_USER_LEN      = 3

# ─── Categorías ───────────────────────────────────────────────────────────────

CATEGORY_RULES: list[tuple[str, re.Pattern]] = [
    ("casual_conversation",    re.compile(r"hola|qué tal|cómo estás|buenas|qué hay|hey|hi\b", re.IGNORECASE)),
    ("existential_opinion",    re.compile(r"qué (piensas|crees|opinas)|tu opinión|te parece|qué harías|favorit", re.IGNORECASE)),
    ("tech_support",           re.compile(r"error|fallo|bug|no funciona|arregla|código|script|backend|frontend|python|docker", re.IGNORECASE)),
    ("git_action",             re.compile(r"\bgit\b|commit|branch|pull|push|merge|repositorio", re.IGNORECASE)),
    ("file_action",            re.compile(r"escribe|crea|modifica|archivo|fichero|lee el archivo|read_file|write_file", re.IGNORECASE)),
    ("system_query",           re.compile(r"raspberry|cpu|ram|disco|servicio|systemd|memoria|proceso", re.IGNORECASE)),
    ("personality_adjustment", re.compile(r"sarcasm|calidez|verbosidad|personalidad|ajusta|slider|sube|baja", re.IGNORECASE)),
    ("sensor_action",          re.compile(r"foto|captura|audio|graba|micrófono|cámara|webcam", re.IGNORECASE)),
    ("meta_sity",              re.compile(r"eres|cómo eres|qué eres|quién eres|qué puedes|capacidades|recuerdas", re.IGNORECASE)),
    ("order_override",         re.compile(r"es una orden", re.IGNORECASE)),
]

CATEGORY_DEFAULT = "general"


# ─── Estructuras de datos ──────────────────────────────────────────────────────

@dataclass
class RawPair:
    pair_id:       str
    session_id:    str
    user_text:     str
    sity_text:     str
    user_ts:       str
    sity_ts:       str
    user_trace:    str | None
    sity_trace:    str | None
    dataset_source: str | None = None


@dataclass
class ScoredPair:
    pair_id:  str
    user:     str
    assistant: str
    category: str
    flags:    list[str] = field(default_factory=list)
    rejected: bool = False
    reject_reason: str = ""


# ─── Lectura de DB ────────────────────────────────────────────────────────────

def iter_raw_pairs(db_path: Path, *, exclude_sources: set[str] | None = None) -> Iterator[RawPair]:
    """Extrae pares user→sity consecutivos de la DB. Solo lectura.

    Args:
        exclude_sources: dataset_source values to skip entirely (both messages of the pair).
            Defaults to {"demo_session"} when None; pass set() to include everything.
    """
    if exclude_sources is None:
        exclude_sources = {"demo_session"}

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, session_id, role, text, trace_id, created_at,
                   dataset_source, dataset_eligible
            FROM chatmessage
            ORDER BY session_id, id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    # Agrupar por session_id
    sessions: dict[str, list[dict]] = {}
    for row in rows:
        sid = row["session_id"]
        sessions.setdefault(sid, []).append(dict(row))

    pair_counter = 0
    for session_id, messages in sessions.items():
        i = 0
        while i < len(messages) - 1:
            curr = messages[i]
            nxt  = messages[i + 1]
            if curr["role"] == "user" and nxt["role"] == "sity":
                src = curr.get("dataset_source") or nxt.get("dataset_source")
                if src in exclude_sources:
                    i += 2
                    continue
                if not curr.get("dataset_eligible", True) or not nxt.get("dataset_eligible", True):
                    i += 2
                    continue
                pair_counter += 1
                yield RawPair(
                    pair_id        = f"pair_{pair_counter:05d}",
                    session_id     = session_id,
                    user_text      = curr["text"] or "",
                    sity_text      = nxt["text"]  or "",
                    user_ts        = curr["created_at"] or "",
                    sity_ts        = nxt["created_at"]  or "",
                    user_trace     = curr["trace_id"],
                    sity_trace     = nxt["trace_id"],
                    dataset_source = src,
                )
                i += 2
            else:
                i += 1


# ─── Carga de patrones externos ───────────────────────────────────────────────

def load_extra_reject_patterns(path: Path) -> list[re.Pattern]:
    if not path.exists():
        return []
    patterns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            try:
                patterns.append(re.compile(line, re.IGNORECASE))
            except re.error as exc:
                print(f"[WARN] reject_patterns.txt: patrón inválido {line!r}: {exc}", file=sys.stderr)
    return patterns


# ─── Carga de semillas manuales ───────────────────────────────────────────────

def load_manual_seeds(path: Path) -> list[ScoredPair]:
    if not path.exists():
        return []
    seeds = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"[WARN] manual_seed.jsonl línea {i}: JSON inválido — {exc}", file=sys.stderr)
            continue
        if "messages" in obj:
            msgs = obj["messages"]
            user_text = next((m["content"] for m in msgs if m.get("role") == "user"), "")
            asst_text = next((m["content"] for m in msgs if m.get("role") == "assistant"), "")
        else:
            user_text = obj.get("user", "")
            asst_text = obj.get("assistant", "")
        seeds.append(ScoredPair(
            pair_id   = obj.get("pair_id", f"seed_{i:03d}"),
            user      = user_text,
            assistant = asst_text,
            category  = obj.get("category", "manual_seed"),
            flags     = obj.get("flags", ["manual_seed"]),
            rejected  = False,
        ))
    return seeds


# ─── Clasificación y scoring ──────────────────────────────────────────────────

def classify(text: str) -> str:
    for category, pattern in CATEGORY_RULES:
        if pattern.search(text):
            return category
    return CATEGORY_DEFAULT


def check_forbidden(text: str) -> list[str]:
    text_lower = text.lower()
    return [phrase for phrase in FORBIDDEN_PHRASES if phrase in text_lower]


def score_pair(
    pair: RawPair,
    extra_reject: list[re.Pattern],
) -> ScoredPair:
    user      = pair.user_text.strip()
    assistant = pair.sity_text.strip()
    flags: list[str] = []

    # ── Rechazos automáticos ──────────────────────────────────────────────────

    if not user or len(user) < MIN_USER_LEN:
        return ScoredPair(pair.pair_id, user, assistant, CATEGORY_DEFAULT,
                          rejected=True, reject_reason="user_too_short")

    if not assistant or len(assistant) < MIN_ASSISTANT_LEN:
        return ScoredPair(pair.pair_id, user, assistant, CATEGORY_DEFAULT,
                          rejected=True, reject_reason="assistant_too_short")

    if len(assistant) > MAX_ASSISTANT_LEN:
        flags.append("too_long")   # no rechazar, pero flagear

    for pat in STRUCTURAL_REJECT_PATTERNS:
        if pat.search(assistant):
            return ScoredPair(pair.pair_id, user, assistant, CATEGORY_DEFAULT,
                              rejected=True, reject_reason=f"structural:{pat.pattern[:40]}")

    for pat in extra_reject:
        if pat.search(assistant):
            return ScoredPair(pair.pair_id, user, assistant, CATEGORY_DEFAULT,
                              rejected=True, reject_reason=f"extra_reject:{pat.pattern[:40]}")

    # ── Flags de calidad ─────────────────────────────────────────────────────

    forbidden_hits = check_forbidden(assistant)
    if forbidden_hits:
        flags.append(f"generic_ai:{','.join(forbidden_hits[:2])}")

    for pat in LOW_QUALITY_PATTERNS:
        if pat.search(assistant):
            flags.append(f"low_quality:{pat.pattern[:30]}")

    # Detectar respuestas en inglés (simplista pero útil)
    english_words = re.findall(r"\b(the|of|and|to|in|is|you|that|it|he|she|we|are|for|on|with|this|they|have|from|at|be)\b", assistant, re.IGNORECASE)
    if len(english_words) > 3:
        flags.append("possible_english")

    # Detectar voseo rioplatense
    if re.search(r"\b(vos|querés|podés|tenés|hacés|sos|estás\s+vos)\b", assistant, re.IGNORECASE):
        flags.append("voseo_detected")

    # Detectar masculino gramatical (Estoy listo/autorizado/etc.)
    if re.search(r"\bestoy\s+(listo|cansado|bloqueado|autorizado|listo)\b", assistant, re.IGNORECASE):
        flags.append("masculine_grammar")

    # Detectar emojis
    emoji_pat = re.compile("[\U00010000-\U0010ffff]", flags=re.UNICODE)
    if emoji_pat.search(assistant):
        flags.append("has_emoji")

    category = classify(user + " " + assistant)

    return ScoredPair(
        pair_id   = pair.pair_id,
        user      = user,
        assistant = assistant,
        category  = category,
        flags     = flags,
        rejected  = False,
    )


# ─── Exportación ─────────────────────────────────────────────────────────────

def write_jsonl(pairs: list[ScoredPair], out_path: Path) -> int:
    """Escribe solo los pares no rechazados en formato ChatML / instruct."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("w", encoding="utf-8") as f:
        for pair in pairs:
            if pair.rejected:
                continue
            record = {
                "pair_id":  pair.pair_id,
                "category": pair.category,
                "flags":    pair.flags,
                "messages": [
                    {"role": "user",      "content": pair.user},
                    {"role": "assistant", "content": pair.assistant},
                ],
            }
            f.write(json.dumps(record, ensure_ascii=False))
            f.write("\n")
            written += 1
    return written


def write_review(pairs: list[ScoredPair], out_path: Path) -> None:
    """Genera review.md con tabla completa para revisión humana."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total     = len(pairs)
    rejected  = sum(1 for p in pairs if p.rejected)
    accepted  = total - rejected
    flagged   = sum(1 for p in pairs if not p.rejected and p.flags)

    cats: dict[str, int] = {}
    for p in pairs:
        if not p.rejected:
            cats[p.category] = cats.get(p.category, 0) + 1

    with out_path.open("w", encoding="utf-8") as f:
        f.write("# Sity LoRA v0 — Review de candidatos\n\n")
        f.write(f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("## Resumen\n\n")
        f.write(f"| Métrica | Valor |\n")
        f.write(f"|---|---|\n")
        f.write(f"| Total pares extraídos | {total} |\n")
        f.write(f"| Aceptados | {accepted} |\n")
        f.write(f"| Rechazados | {rejected} |\n")
        f.write(f"| Aceptados con flags | {flagged} |\n")
        f.write("\n## Distribución por categoría\n\n")
        f.write("| Categoría | Count |\n|---|---|\n")
        for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
            f.write(f"| {cat} | {count} |\n")

        f.write("\n## Pares rechazados\n\n")
        f.write("| ID | Motivo | User (preview) | Assistant (preview) |\n")
        f.write("|---|---|---|---|\n")
        for p in pairs:
            if not p.rejected:
                continue
            u_prev = p.user[:60].replace("|", "│").replace("\n", " ")
            a_prev = p.assistant[:60].replace("|", "│").replace("\n", " ")
            f.write(f"| {p.pair_id} | `{p.reject_reason}` | {u_prev} | {a_prev} |\n")

        f.write("\n## Pares aceptados\n\n")
        f.write("| ID | Categoría | Flags | User | Assistant |\n")
        f.write("|---|---|---|---|---|\n")
        for p in pairs:
            if p.rejected:
                continue
            flags_str = ", ".join(p.flags) if p.flags else "—"
            u_prev = p.user[:80].replace("|", "│").replace("\n", " ")
            a_prev = p.assistant[:80].replace("|", "│").replace("\n", " ")
            f.write(f"| {p.pair_id} | {p.category} | {flags_str} | {u_prev} | {a_prev} |\n")

        f.write("\n## Notas de revisión manual\n\n")
        f.write("<!-- Añade comentarios aquí antes de pasar a fine-tuning -->\n\n")
        f.write("### Flags activos\n\n")
        flag_counts: dict[str, int] = {}
        for p in pairs:
            if p.rejected:
                continue
            for flag in p.flags:
                key = flag.split(":")[0]
                flag_counts[key] = flag_counts.get(key, 0) + 1
        for flag, count in sorted(flag_counts.items(), key=lambda x: -x[1]):
            f.write(f"- `{flag}`: {count} pares\n")


# ─── Entrypoint ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Exporta candidatos LoRA para Sity v0.")
    parser.add_argument("--db",            default=str(DEFAULT_DB),  help="Ruta a data/app.db")
    parser.add_argument("--out-dir",       default=str(DEFAULT_OUT), help="Directorio de salida")
    parser.add_argument("--include-seeds", action="store_true",       help="Incluir manual_seed.jsonl en el output")
    parser.add_argument("--include-demo",  action="store_true",       help="Incluir pares con dataset_source=demo_session (excluidos por defecto)")
    parser.add_argument("--min-assistant", type=int, default=MIN_ASSISTANT_LEN)
    parser.add_argument("--max-assistant", type=int, default=MAX_ASSISTANT_LEN)
    args = parser.parse_args()

    db_path  = Path(args.db)
    out_dir  = Path(args.out_dir)

    if not db_path.exists():
        print(f"[ERROR] DB no encontrada: {db_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[export] Leyendo DB: {db_path}")
    extra_reject = load_extra_reject_patterns(out_dir / "reject_patterns.txt")
    if extra_reject:
        print(f"[export] Patrones externos de rechazo: {len(extra_reject)}")

    exclude_sources: set[str] = set() if args.include_demo else {"demo_session"}
    if exclude_sources:
        print(f"[export] Excluyendo dataset_source: {exclude_sources} (usa --include-demo para incluirlos)")
    raw_pairs = list(iter_raw_pairs(db_path, exclude_sources=exclude_sources))
    print(f"[export] Pares brutos extraídos: {len(raw_pairs)}")

    scored: list[ScoredPair] = []
    for pair in raw_pairs:
        sp = score_pair(pair, extra_reject)
        scored.append(sp)

    if args.include_seeds:
        seeds = load_manual_seeds(out_dir / "manual_seed.jsonl")
        if seeds:
            print(f"[export] Semillas manuales cargadas: {len(seeds)}")
            scored = seeds + scored

    accepted  = [p for p in scored if not p.rejected]
    rejected  = [p for p in scored if p.rejected]
    flagged   = [p for p in accepted if p.flags]

    print(f"[export] Aceptados: {len(accepted)}")
    print(f"[export] Rechazados: {len(rejected)}")
    print(f"[export] Con flags: {len(flagged)}")

    train_path  = out_dir / "train_candidates.jsonl"
    review_path = out_dir / "review.md"

    written = write_jsonl(scored, train_path)
    print(f"[export] Escrito: {train_path} ({written} ejemplos)")

    write_review(scored, review_path)
    print(f"[export] Reporte: {review_path}")


if __name__ == "__main__":
    main()
