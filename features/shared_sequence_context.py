"""
Per-tick shared DB sequence preparation for LSTM + Transformer (one fetch, one LSTM merge).

Horizon-specific model masks and Transformer merged windows are still built per horizon;
this module only deduplicates identical work across the governed-horizon loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping







@dataclass(frozen=True)
class SharedSequenceContext:
    """Immutable handles to shared sequence data.

    COH-I-F closure: ``@dataclass(frozen=True)`` prevents attribute reassignment, but
    the typed ``dict`` fields used to be mutable in place. ``meta`` is now a
    ``MappingProxyType`` view (raises ``TypeError`` on write). The snapshot tuples
    are tuples-of-dicts: per-row dict contents are NOT individually frozen because
    snapshot dicts flow through other consumer code (mass-freezing here would have
    too wide a blast radius); the tuple wrapper itself prevents row insertion /
    removal and is the structural guarantee callers can rely on.
    """

    as_of_ts: float
    chron_snapshots: tuple[dict[str, Any], ...]
    lstm_merged_window: tuple[dict[str, Any], ...]
    lstm_merged_days: tuple[dict[str, Any], ...]
    n_fetch: int
    meta: Mapping[str, Any]








def transformer_window_chronological(
    ctx: SharedSequenceContext,
    seq_len: int,
) -> list[dict[str, Any]]:
    """Last ``seq_len`` chronological snapshots (newest at end) — for Transformer merge."""
    ch = ctx.chron_snapshots
    if len(ch) < seq_len:
        from features.lstm_sequence_input import TransformerSequenceInputError

        raise TransformerSequenceInputError(
            f"Transformer needs at least {seq_len} snapshots, got {len(ch)}"
        )
    return list(ch[-seq_len:])





