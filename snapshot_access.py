"""
Central enforcement for reads against the ``snapshots`` table.

Rules:
- Any query that returns *rows* or *aggregates* for analytical / production use MUST
  include an explicit ``timeframe`` filter (bound parameter), except:
  - Primary-key lookups: ``WHERE snapshot_id = ?`` (single row; timeframe implicit in row).
  - Documented audit helpers that intentionally aggregate *per* timeframe (GROUP BY).
- The dedicated training table ``snapshots_1m_normalized`` (see ``timeframe_config.SNAPSHOT_TABLE_1M``)
  is 1m-only by schema contract; timeframe column may be present but the table name is the guard.

Use :func:`require_snapshot_timeframe` at the start of any API that accepts ``timeframe: str``
so callers cannot pass None/empty silently.
"""

from __future__ import annotations

from timeframe_config import CANONICAL_TIMEFRAME, SNAPSHOT_TABLE_1M

SNAPSHOTS_TABLE: str = "snapshots"
"""Logical name for the raw multi-timeframe snapshot store."""

NORMALIZED_1M_TABLE: str = SNAPSHOT_TABLE_1M
"""1m-only normalized training table; not mixed with multi-tf ``snapshots`` reads."""


class SnapshotTimeframeRequiredError(ValueError):
    """Raised when a snapshot read path received a missing or blank timeframe."""


def require_snapshot_timeframe(timeframe: str | None, *, caller: str = "") -> str:
    """
    Require a non-empty timeframe string for ``snapshots`` reads that parameterize SQL.

    Raises:
        SnapshotTimeframeRequiredError: if None, empty, or whitespace-only.
    """
    if timeframe is None:
        raise SnapshotTimeframeRequiredError(
            f"snapshots query requires explicit timeframe (caller={caller or 'unknown'})"
        )
    s = str(timeframe).strip()
    if not s:
        raise SnapshotTimeframeRequiredError(
            f"snapshots query requires non-empty timeframe (caller={caller or 'unknown'})"
        )
    return s


def is_canonical_timeframe(timeframe: str) -> bool:
    return timeframe.strip() == CANONICAL_TIMEFRAME
