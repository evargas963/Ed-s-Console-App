"""Shared helpers for canonical 1m repair tools (carry basis + synthetic source tags)."""

from __future__ import annotations

from horizon_outcomes import (
    SYNTHETIC_ANCHOR_COVERAGE_PAD_V1,
    SYNTHETIC_EDGE_CARRY_V1,
    SYNTHETIC_INTERIOR_GRID_REPAIR_V1,
)

GAP_FILL_CANONICAL_1M_GRID_V1 = "gap_fill_canonical_1m_grid_v1"

REPAIR_SYNTHETIC_1M_SOURCES: frozenset[str] = frozenset(
    {
        GAP_FILL_CANONICAL_1M_GRID_V1,
        SYNTHETIC_EDGE_CARRY_V1,
        SYNTHETIC_INTERIOR_GRID_REPAIR_V1,
        SYNTHETIC_ANCHOR_COVERAGE_PAD_V1,
    }
)


def carry_basis_source_sql(*, column: str = "source") -> tuple[str, tuple[str, ...]]:
    """SQL fragment + bind values: exclude known synthetic repair sources from carry basis."""
    placeholders = ",".join("?" * len(REPAIR_SYNTHETIC_1M_SOURCES))
    clause = f"({column} IS NULL OR {column} NOT IN ({placeholders}))"
    return clause, tuple(REPAIR_SYNTHETIC_1M_SOURCES)
