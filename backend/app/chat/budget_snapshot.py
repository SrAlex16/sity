"""
budget_snapshot.py — lightweight value object for post-call budget accounting.

Computed once after persisting token usage; passed to response_factory helpers
so the ratio/warnings logic is not duplicated between the local-tool path and
the AI-final path in routes_chat.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BudgetSnapshot:
    """Budget state at a single point in time, after a token-consuming operation."""

    daily_used: int
    daily_budget: int
    daily_ratio: float
    warnings: list[str] = field(default_factory=list)


def build_budget_snapshot(
    *,
    daily_used: int,
    daily_budget: int,
    warning_threshold: float,
    critical_threshold: float,
) -> BudgetSnapshot:
    """Return a BudgetSnapshot with ratio and user-visible warnings computed."""
    daily_ratio = daily_used / daily_budget if daily_budget > 0 else 0.0

    warnings: list[str] = []
    if daily_ratio >= critical_threshold:
        warnings.append(
            f"Uso crítico: has consumido aproximadamente el {round(daily_ratio * 100)}%"
            " del presupuesto diario configurado."
        )
    elif daily_ratio >= warning_threshold:
        warnings.append(
            f"Aviso: has consumido aproximadamente el {round(daily_ratio * 100)}%"
            " del presupuesto diario configurado."
        )

    return BudgetSnapshot(
        daily_used=daily_used,
        daily_budget=daily_budget,
        daily_ratio=daily_ratio,
        warnings=warnings,
    )
