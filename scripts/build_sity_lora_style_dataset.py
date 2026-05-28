#!/usr/bin/env python3
"""
Build a curated Sity LoRA style dataset from raw train_candidates.jsonl.

Input:
  datasets/sity_style_v0/train_candidates.jsonl

Output:
  datasets/sity_style_v0/train_style_v0.jsonl
  datasets/sity_style_v0/eval_style_v0.jsonl
  datasets/sity_style_v0/style_review.md

Rules:
  - No DB access, no external APIs, stdlib only.
  - Never overwrites train_candidates.jsonl.
  - Keeps pair_id/category/flags/messages intact.

Usage:
  python scripts/build_sity_lora_style_dataset.py
  python scripts/build_sity_lora_style_dataset.py --dry-run
  python scripts/build_sity_lora_style_dataset.py --input path/to/candidates.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "datasets" / "sity_style_v0"

DEFAULT_INPUT  = DATASET_DIR / "train_candidates.jsonl"
DEFAULT_TRAIN  = DATASET_DIR / "train_style_v0.jsonl"
DEFAULT_EVAL   = DATASET_DIR / "eval_style_v0.jsonl"
DEFAULT_REVIEW = DATASET_DIR / "style_review.md"

EVAL_TARGET  = 30
TRAIN_MIN_WARNING = 120

MAX_ASSISTANT_CHARS = 700

# Categories that go through style filtering (allow list)
STYLE_CATEGORIES = {
    "casual_conversation",
    "existential_opinion",
    "meta_sity",
    "personality_adjustment",
    "general",
    "tech_support",
}

# Categories excluded entirely
EXCLUDE_CATEGORIES = {
    "file_action",
    "git_action",
    "system_query",
    "sensor_action",
    "order_override",
}

# Patterns that disqualify any example (operational/structural signals)
_OP_PATTERNS: list[str] = [
    r"act_[a-f0-9]{8}",
    r"confirmo ejecutar",
    r"acci[oó]n pendiente",
    r"acci[oó]n ejecutada",
    r"herramienta",
    r"\btool\b",
    r"\btrace\b",
    r"trace_id",
    r"tokens consumidos",
    r"modelo usado",
    r"Claude Haiku",
    r"/home/",
    r"backend/app/",
    r"frontend/",
    r"config/",
    r"\bdata/",
    r"commit hash",
    r"rama main",
    r"origin/main",
    r"git status",
    r"[uú]ltimos commits",
    r"servicios permitidos",
    r"\bsystemd\b",
    r"CPU al\b",
    r"RAM al\b",
    r"disco ra[ií]z",
]
OP_RE = re.compile("|".join(_OP_PATTERNS), re.IGNORECASE)
CODE_BLOCK_RE = re.compile(r"```")

# Tacos/desahogo signals — used for eval priority scoring
TACO_RE = re.compile(
    r"\b(cago|encabron|joder|hostia|coño|cabrón|cabron|puta|mierda|"
    r"follen|follar|gilipollas|imbécil|imbecil|jodido|ostia|me cago)\b",
    re.IGNORECASE,
)

# Preference/opinion signals — used for eval priority scoring
OPINION_RE = re.compile(
    r"\b(favorit[oa]|prefieres|gusta[s]?|opini[oó]n|me parece|mejor[es]?|"
    r"peor[es]?|elegir[ía]|elegiría|afinidad|estética|estetic[ao])\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Pair:
    pair_id: str
    category: str
    flags: list[str]
    messages: list[dict]
    raw: dict

    @property
    def user(self) -> str:
        return next((m["content"] for m in self.messages if m["role"] == "user"), "")

    @property
    def assistant(self) -> str:
        return next((m["content"] for m in self.messages if m["role"] == "assistant"), "")

    @property
    def is_manual_seed(self) -> bool:
        return "manual_seed" in self.flags


@dataclass
class ExcludedPair:
    pair: Pair
    reason: str


@dataclass
class FilterResult:
    selected: list[Pair] = field(default_factory=list)
    excluded: list[ExcludedPair] = field(default_factory=list)
    n_excluded_category: int = 0
    n_excluded_flag: int = 0
    n_excluded_pattern: int = 0
    n_excluded_code: int = 0
    n_excluded_length: int = 0


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_candidates(path: Path) -> list[Pair]:
    pairs: list[Pair] = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"WARN: line {lineno} JSON error: {exc}", file=sys.stderr)
                continue
            pairs.append(Pair(
                pair_id=d.get("pair_id", f"line_{lineno}"),
                category=d.get("category", "unknown"),
                flags=d.get("flags", []),
                messages=d.get("messages", []),
                raw=d,
            ))
    return pairs


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def filter_pairs(all_pairs: list[Pair]) -> FilterResult:
    result = FilterResult()

    for pair in all_pairs:
        # 1. Category exclusion
        if pair.category in EXCLUDE_CATEGORIES:
            result.n_excluded_category += 1
            result.excluded.append(ExcludedPair(pair, f"excluded_category:{pair.category}"))
            continue

        # 2. Flags (keep only unflagged OR manual_seed)
        if pair.flags and not pair.is_manual_seed:
            result.n_excluded_flag += 1
            result.excluded.append(ExcludedPair(pair, f"flagged:{','.join(pair.flags)}"))
            continue

        # 3. Operational/structural patterns (in user OR assistant)
        combined = pair.user + " " + pair.assistant
        m = OP_RE.search(combined)
        if m:
            result.n_excluded_pattern += 1
            result.excluded.append(ExcludedPair(pair, f"op_pattern:{m.group(0)!r}"))
            continue

        # 4. Code blocks in assistant
        if CODE_BLOCK_RE.search(pair.assistant):
            result.n_excluded_code += 1
            result.excluded.append(ExcludedPair(pair, "code_block_in_assistant"))
            continue

        # 5. Length (skip for manual_seed)
        if not pair.is_manual_seed and len(pair.assistant) > MAX_ASSISTANT_CHARS:
            result.n_excluded_length += 1
            result.excluded.append(ExcludedPair(
                pair, f"assistant_too_long:{len(pair.assistant)}_chars"
            ))
            continue

        result.selected.append(pair)

    return result


# ---------------------------------------------------------------------------
# Eval priority scoring
# ---------------------------------------------------------------------------

# Higher score → goes to eval first
CATEGORY_EVAL_PRIORITY: dict[str, int] = {
    "existential_opinion":  100,
    "personality_adjustment": 90,
    "meta_sity":            80,
    "casual_conversation":  70,
    "general":              40,
    "tech_support":         20,
}


def eval_priority_score(pair: Pair) -> int:
    score = CATEGORY_EVAL_PRIORITY.get(pair.category, 0)
    if TACO_RE.search(pair.user):
        score += 200  # tacos/desahogo always go to eval first
    if OPINION_RE.search(pair.user):
        score += 150  # preference questions go early
    return score


# ---------------------------------------------------------------------------
# Split
# ---------------------------------------------------------------------------

def split_eval_train(
    selected: list[Pair],
    *,
    eval_target: int,
) -> tuple[list[Pair], list[Pair]]:
    """
    Pick eval_target examples for eval, prioritizing coverage of critical
    categories and tacos/desahogo. Rest goes to train.
    """
    sorted_by_priority = sorted(selected, key=eval_priority_score, reverse=True)

    eval_set: list[Pair] = []
    # Ensure category coverage: at most ceil(eval_target / num_categories) per category
    # before falling back to pure priority ordering.
    cat_counts: dict[str, int] = {}
    max_per_cat = max(2, eval_target // len(STYLE_CATEGORIES))

    # First pass: take up to max_per_cat per category (priority order)
    remaining_after_pass1: list[Pair] = []
    for pair in sorted_by_priority:
        if len(eval_set) >= eval_target:
            remaining_after_pass1.append(pair)
            continue
        n = cat_counts.get(pair.category, 0)
        if n < max_per_cat:
            eval_set.append(pair)
            cat_counts[pair.category] = n + 1
        else:
            remaining_after_pass1.append(pair)

    # Second pass: fill remaining slots from leftovers (pure priority)
    for pair in sorted(remaining_after_pass1, key=eval_priority_score, reverse=True):
        if len(eval_set) >= eval_target:
            break
        eval_set.append(pair)

    eval_ids = {p.pair_id for p in eval_set}
    train_set = [p for p in selected if p.pair_id not in eval_ids]

    return eval_set, train_set


# ---------------------------------------------------------------------------
# Review markdown
# ---------------------------------------------------------------------------

def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _preview(text: str, n: int = 80) -> str:
    t = text.replace("\n", " ").strip()
    return (t[:n] + "…") if len(t) > n else t


def build_review(
    *,
    n_input: int,
    result: FilterResult,
    eval_set: list[Pair],
    train_set: list[Pair],
    timestamp: str,
) -> str:
    selected = result.selected
    n_total_excl = (
        result.n_excluded_category
        + result.n_excluded_flag
        + result.n_excluded_pattern
        + result.n_excluded_code
        + result.n_excluded_length
    )

    lines: list[str] = [
        "# Sity LoRA style dataset — style_review",
        f"",
        f"Generado: {timestamp}",
        f"",
        "## Resumen",
        "",
        _row(["Métrica", "Valor"]),
        "|---|---|",
        _row(["Candidatos entrada (train_candidates.jsonl)", str(n_input)]),
        _row(["Excluidos total", str(n_total_excl)]),
        _row(["→ por categoría excluida", str(result.n_excluded_category)]),
        _row(["→ por flags (no manual_seed)", str(result.n_excluded_flag)]),
        _row(["→ por patrón operativo", str(result.n_excluded_pattern)]),
        _row(["→ por bloque de código en assistant", str(result.n_excluded_code)]),
        _row(["→ por longitud assistant > 700 chars", str(result.n_excluded_length)]),
        _row(["Seleccionados (limpios)", str(len(selected))]),
        _row(["→ train_style_v0.jsonl", str(len(train_set))]),
        _row(["→ eval_style_v0.jsonl", str(len(eval_set))]),
        "",
    ]

    # Warnings
    if len(selected) < TRAIN_MIN_WARNING:
        lines.append(
            f"> ⚠ WARNING: solo {len(selected)} ejemplos limpios (mínimo recomendado: {TRAIN_MIN_WARNING}). "
            "Añadir manual_seed.jsonl antes de entrenar."
        )
        lines.append("")

    if len(eval_set) < EVAL_TARGET:
        lines.append(
            f"> ⚠ WARNING: eval set tiene {len(eval_set)} ejemplos (objetivo: {EVAL_TARGET})."
        )
        lines.append("")

    # Category distribution of selected
    lines += ["## Distribución por categoría (seleccionados)", ""]
    cat_train: dict[str, int] = {}
    cat_eval: dict[str, int] = {}
    for p in train_set:
        cat_train[p.category] = cat_train.get(p.category, 0) + 1
    for p in eval_set:
        cat_eval[p.category] = cat_eval.get(p.category, 0) + 1
    all_cats = sorted(set(cat_train) | set(cat_eval))

    lines.append(_row(["Categoría", "Train", "Eval", "Total"]))
    lines.append("|---|---|---|---|")
    for cat in all_cats:
        t = cat_train.get(cat, 0)
        e = cat_eval.get(cat, 0)
        lines.append(_row([cat, str(t), str(e), str(t + e)]))
    lines.append("")

    # First 100 selected
    preview_n = min(100, len(selected))
    lines += [f"## Primeros {preview_n} seleccionados", ""]
    lines.append(_row(["Pair ID", "Cat", "Flags", "User (preview)", "Assistant (preview)"]))
    lines.append("|---|---|---|---|---|")
    for p in selected[:preview_n]:
        flags_str = ",".join(p.flags) if p.flags else "—"
        lines.append(_row([
            p.pair_id,
            p.category,
            flags_str,
            _preview(p.user),
            _preview(p.assistant),
        ]))
    lines.append("")

    # First 100 excluded
    excl_n = min(100, len(result.excluded))
    lines += [f"## Primeros {excl_n} excluidos", ""]
    lines.append(_row(["Pair ID", "Cat", "Motivo", "User (preview)", "Assistant (preview)"]))
    lines.append("|---|---|---|---|---|")
    for ep in result.excluded[:excl_n]:
        p = ep.pair
        lines.append(_row([
            p.pair_id,
            p.category,
            ep.reason,
            _preview(p.user),
            _preview(p.assistant),
        ]))
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build curated Sity LoRA style dataset from train_candidates.jsonl"
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT),
        help=f"Input JSONL (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DATASET_DIR),
        help=f"Output directory (default: {DATASET_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print stats but do not write output files",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_path = Path(args.input)
    out_dir = Path(args.out_dir)

    if not input_path.exists():
        print(f"ERROR: input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Safety guard: never overwrite the source
    out_dir.mkdir(parents=True, exist_ok=True)
    train_path  = out_dir / "train_style_v0.jsonl"
    eval_path   = out_dir / "eval_style_v0.jsonl"
    review_path = out_dir / "style_review.md"

    if train_path.resolve() == input_path.resolve():
        print("ERROR: output would overwrite input. Aborting.", file=sys.stderr)
        sys.exit(1)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n  Sity LoRA style dataset builder — {ts}")
    print(f"  Input : {input_path}")
    print(f"  OutDir: {out_dir}\n")

    # Load
    all_pairs = load_candidates(input_path)
    print(f"  Loaded   : {len(all_pairs)} pairs")

    # Filter
    result = filter_pairs(all_pairs)
    print(f"  Clean    : {len(result.selected)}")
    print(f"  Excluded : {len(result.excluded)}"
          f" (cat={result.n_excluded_category}"
          f" flag={result.n_excluded_flag}"
          f" pattern={result.n_excluded_pattern}"
          f" code={result.n_excluded_code}"
          f" len={result.n_excluded_length})")

    if len(result.selected) < TRAIN_MIN_WARNING:
        print(
            f"\n  ⚠  WARNING: only {len(result.selected)} clean examples "
            f"(recommended minimum: {TRAIN_MIN_WARNING}).\n"
            "     Add manual_seed.jsonl examples before training.\n"
        )

    # Split
    eval_target = min(EVAL_TARGET, max(0, len(result.selected) - 10))
    eval_set, train_set = split_eval_train(result.selected, eval_target=eval_target)
    print(f"  Train    : {len(train_set)}")
    print(f"  Eval     : {len(eval_set)}")

    if len(eval_set) < EVAL_TARGET:
        print(f"\n  ⚠  WARNING: eval set has {len(eval_set)} examples (target: {EVAL_TARGET}).\n")

    if args.dry_run:
        print("\n  --dry-run: no files written.\n")
        return

    # Write train
    with train_path.open("w", encoding="utf-8") as f:
        for p in train_set:
            f.write(json.dumps(p.raw, ensure_ascii=False) + "\n")
    print(f"\n  Written  : {train_path}")

    # Write eval
    with eval_path.open("w", encoding="utf-8") as f:
        for p in eval_set:
            f.write(json.dumps(p.raw, ensure_ascii=False) + "\n")
    print(f"  Written  : {eval_path}")

    # Write review
    review_md = build_review(
        n_input=len(all_pairs),
        result=result,
        eval_set=eval_set,
        train_set=train_set,
        timestamp=ts,
    )
    review_path.write_text(review_md, encoding="utf-8")
    print(f"  Written  : {review_path}\n")


if __name__ == "__main__":
    main()
