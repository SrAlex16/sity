"""semantic_proposition.py — Types for the Memory Worthiness pipeline (MINI-REMAKE v3.0).

Separates salience (event-level) from memory worthiness (proposition-level).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass
class SemanticProperties:
    personal_relevance: float      # 0.0=external info, 1.0=directly about the user
    temporal_scope: str            # "persistent"|"habitual"|"transient"|"situational"
    context_dependency: float      # 0.0=general truth, 1.0=only true in this context
    assertion_strength: float      # 0.0=hypothetical/uncertain, 1.0=clear direct statement
    expected_duration: float       # 0.0=momentary, 1.0=permanent
    behavioral_relevance: float    # 0.0=no decision impact, 1.0=changes Sity's responses


@dataclass
class SemanticProposition:
    id: str
    content: str
    properties: SemanticProperties


class MemoryOperation(Enum):
    """Semantic memory operation — final result of the MW pipeline for one proposition."""
    IGNORED     = "ignored"
    CONSOLIDATE = "consolidate"
    REINFORCE   = "reinforce"
    REVISE      = "revise"


class MemoryProcessingState(Enum):
    """Internal pipeline state — not exposed in MemoryResult."""
    CANDIDATE  = "candidate"
    RESOLVING  = "resolving"
    PERSISTING = "persisting"
    COMPLETED  = "completed"


@dataclass
class MemoryResult:
    proposition_id: str
    operation: MemoryOperation
    persisted: bool
    fact_id: str | None
    related_fact_ids: list[str] = field(default_factory=list)
