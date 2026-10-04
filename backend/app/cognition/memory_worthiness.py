"""memory_worthiness.py — Memory Worthiness evaluation and consolidation pipeline (MINI-REMAKE v3.0).

Evaluates individual semantic propositions for persistence worthiness,
independently of turn-level salience.

Pipeline per proposition:
  SemanticProposition → evaluate_memory_worthiness() → MW_effective >= MW_GATE?
    → Semantic Resolver (NEW / MATCH / RELATED / CONTRADICT)
    → DB operation (upsert_semantic_candidate / reinforce_fact / contradict_fact)
    → MemoryResult

Never raises — failures return IGNORED results.

All hyperparameters are module-level constants, configurable for calibration.
"""
from __future__ import annotations

from sqlmodel import Session

from app.cognition.semantic_proposition import (
    MemoryOperation,
    MemoryResult,
    SemanticProposition,
)
from app.cognition.semantic_resolver import SemanticResolution, resolve_candidate
from app.cognition.semantic_service import (
    contradict_fact,
    load_active_facts,
    reinforce_fact,
    upsert_semantic_candidate,
)
from app.trace.logger import write_log

# ─── Hyperparameters (all configurable — calibrate with real data) ──────────
MW_GATE: float = 0.40
CONTEXT_PENALTY: float = 0.50
MW_WEIGHTS: dict[str, float] = {
    "expected_duration":    0.30,
    "behavioral_relevance": 0.25,
    "personal_relevance":   0.25,
    "assertion_strength":   0.20,
}

# RELATED → linked consolidate only when resolver confidence meets this floor
_RELATED_CONFIDENCE_MIN: float = 0.60
# ────────────────────────────────────────────────────────────────────────────


def evaluate_memory_worthiness(
    proposition: SemanticProposition,
) -> tuple[float, float]:
    """Compute (MW_base, MW_effective) for a proposition.

    MW_base    = weighted sum of expected_duration, behavioral_relevance,
                 personal_relevance, assertion_strength.
    MW_effective = MW_base * (1 - CONTEXT_PENALTY * context_dependency)

    Both values clamped to [0, 1]. Pure function — no I/O.
    """
    p = proposition.properties
    mw_base = (
        MW_WEIGHTS["expected_duration"]    * max(0.0, min(1.0, p.expected_duration))
        + MW_WEIGHTS["behavioral_relevance"] * max(0.0, min(1.0, p.behavioral_relevance))
        + MW_WEIGHTS["personal_relevance"]   * max(0.0, min(1.0, p.personal_relevance))
        + MW_WEIGHTS["assertion_strength"]   * max(0.0, min(1.0, p.assertion_strength))
    )
    mw_base = max(0.0, min(1.0, mw_base))
    penalty = CONTEXT_PENALTY * max(0.0, min(1.0, p.context_dependency))
    mw_effective = mw_base * (1.0 - penalty)
    return (mw_base, max(0.0, min(1.0, mw_effective)))


def process_mw_pipeline(
    session: Session,
    *,
    user_id: int,
    propositions: list[SemanticProposition],
    trace_id: str = "",
) -> list[MemoryResult]:
    """Run MW gate + resolver + DB ops for each proposition.

    Returns one MemoryResult per input proposition.
    Refreshes existing_facts after each persist so subsequent propositions
    see facts created earlier in the same turn.
    Never raises.
    """
    if not propositions:
        return []

    try:
        existing_facts = load_active_facts(session, user_id)
    except Exception:
        existing_facts = []

    results: list[MemoryResult] = []

    for prop in propositions:
        mw_base, mw_effective = evaluate_memory_worthiness(prop)
        p = prop.properties

        if mw_effective < MW_GATE:
            _write_mw_log(trace_id, prop, p, mw_base, mw_effective,
                          resolver_result="n/a", operation="ignored",
                          persisted=False, fact_id=None)
            results.append(MemoryResult(
                proposition_id=prop.id,
                operation=MemoryOperation.IGNORED,
                persisted=False,
                fact_id=None,
            ))
            continue

        try:
            resolution = resolve_candidate(
                prop.content, "semantic_fact", existing_facts, trace_id=trace_id,
            )
        except Exception as exc:
            write_log(level="WARN", module="cognition", event="mw_resolver_error",
                      trace_id=trace_id, payload={"error": str(exc)[:200]})
            results.append(MemoryResult(
                proposition_id=prop.id,
                operation=MemoryOperation.IGNORED,
                persisted=False,
                fact_id=None,
            ))
            continue

        mr = _apply_resolution(session, user_id=user_id, prop=prop,
                               resolution=resolution, trace_id=trace_id)

        _write_mw_log(trace_id, prop, p, mw_base, mw_effective,
                      resolver_result=resolution.relation,
                      operation=mr.operation.value,
                      persisted=mr.persisted,
                      fact_id=mr.fact_id)

        if mr.persisted:
            try:
                existing_facts = load_active_facts(session, user_id)
            except Exception:
                pass

        results.append(mr)

    return results


def build_memory_expression_block(memory_results: list[MemoryResult]) -> str:
    """Build the Expression grounding block for the persona prompt.

    Called by turn_runner when there are memory results for this turn.
    Pure function — no I/O.
    """
    if not memory_results:
        return ""

    any_persisted = any(r.persisted for r in memory_results)

    if not any_persisted:
        return (
            "[MEMORIA: No se ha guardado ningún dato nuevo sobre el usuario en este turno. "
            "No prometas recordar, anotar ni guardar nada.]"
        )

    lines = ["[MEMORIA ESTE TURNO]"]
    has_consolidate = False
    has_reinforce = False
    has_revise = False

    for r in memory_results:
        if not r.persisted:
            continue
        if r.operation == MemoryOperation.CONSOLIDATE:
            has_consolidate = True
        elif r.operation == MemoryOperation.REINFORCE:
            has_reinforce = True
        elif r.operation == MemoryOperation.REVISE:
            has_revise = True

    if has_consolidate:
        lines.append("- Se ha registrado información nueva sobre el usuario.")
        lines.append("  → Puedes indicar que tendrás esto en cuenta.")
    if has_reinforce:
        lines.append("- Se ha reforzado información ya conocida.")
        lines.append("  → Compórtate como si ya lo supieras, sin necesidad de explicitarlo.")
    if has_revise:
        lines.append("- Se ha actualizado una creencia previa.")
        lines.append("  → Responde según la información actualizada.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _apply_resolution(
    session: Session,
    *,
    user_id: int,
    prop: SemanticProposition,
    resolution: SemanticResolution,
    trace_id: str,
) -> MemoryResult:
    """Map resolver result to DB operation. Returns MemoryResult. Never raises."""
    rel = resolution.relation

    try:
        if rel == "match" and resolution.target_id is not None:
            fact = reinforce_fact(
                session, resolution.target_id,
                user_id=user_id, trace_id=trace_id, source="memory_worthiness",
            )
            if fact is not None:
                return MemoryResult(
                    proposition_id=prop.id,
                    operation=MemoryOperation.REINFORCE,
                    persisted=True,
                    fact_id=str(fact.id),
                )

        elif rel == "contradict" and resolution.target_id is not None:
            fact = contradict_fact(
                session, resolution.target_id,
                user_id=user_id, trace_id=trace_id, source="memory_worthiness",
            )
            if fact is not None:
                return MemoryResult(
                    proposition_id=prop.id,
                    operation=MemoryOperation.REVISE,
                    persisted=True,
                    fact_id=str(fact.id),
                )

        elif rel == "related":
            related_id = (
                resolution.target_id
                if resolution.confidence >= _RELATED_CONFIDENCE_MIN and resolution.target_id is not None
                else None
            )
            conf = min(0.55, prop.properties.assertion_strength * 0.30 + 0.30)
            fact = upsert_semantic_candidate(
                session,
                user_id=user_id,
                proposition=prop.content,
                inference_type="explicit",
                confidence=conf,
                trace_id=trace_id,
                related_fact_id=related_id,
            )
            related_ids = [str(related_id)] if related_id is not None else []
            return MemoryResult(
                proposition_id=prop.id,
                operation=MemoryOperation.CONSOLIDATE,
                persisted=True,
                fact_id=str(fact.id),
                related_fact_ids=related_ids,
            )

        # NEW (and fallback for failed MATCH/CONTRADICT)
        conf = min(0.55, prop.properties.assertion_strength * 0.30 + 0.30)
        fact = upsert_semantic_candidate(
            session,
            user_id=user_id,
            proposition=prop.content,
            inference_type="explicit",
            confidence=conf,
            trace_id=trace_id,
        )
        return MemoryResult(
            proposition_id=prop.id,
            operation=MemoryOperation.CONSOLIDATE,
            persisted=True,
            fact_id=str(fact.id),
        )

    except Exception as exc:
        write_log(level="WARN", module="cognition", event="mw_persistence_error",
                  trace_id=trace_id, payload={"error": str(exc)[:200]})
        return MemoryResult(
            proposition_id=prop.id,
            operation=MemoryOperation.IGNORED,
            persisted=False,
            fact_id=None,
        )


def _write_mw_log(
    trace_id: str,
    prop: SemanticProposition,
    p,
    mw_base: float,
    mw_effective: float,
    *,
    resolver_result: str,
    operation: str,
    persisted: bool,
    fact_id: str | None,
) -> None:
    write_log(
        level="INFO",
        module="cognition",
        event="memory_worthiness_evaluated",
        trace_id=trace_id,
        payload={
            "proposition":          prop.content,
            "expected_duration":    round(p.expected_duration, 3),
            "behavioral_relevance": round(p.behavioral_relevance, 3),
            "personal_relevance":   round(p.personal_relevance, 3),
            "assertion_strength":   round(p.assertion_strength, 3),
            "context_dependency":   round(p.context_dependency, 3),
            "mw_base":              round(mw_base, 3),
            "mw_effective":         round(mw_effective, 3),
            "resolver_result":      resolver_result,
            "memory_operation":     operation,
            "persisted":            persisted,
            "fact_id":              fact_id,
        },
    )
