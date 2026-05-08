"""
Reconstruct SignalInput from a snapshots table row dict for stack replay / fusion backfill.

Uses column names aligned with SnapshotRow / SignalInput where they overlap; remaining
SignalInput fields use dataclass defaults.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from signal_types import SignalInput
from timeframe_config import CANONICAL_TIMEFRAME


def _positive_float_required(row: dict[str, Any], field: str) -> float:
    raw = row.get(field)
    if raw is None or raw == "":
        raise ValueError(f"{field} is required for replay SignalInput")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric for replay SignalInput") from exc
    if value <= 0:
        raise ValueError(f"{field} must be positive for replay SignalInput")
    return value


def signal_input_from_snapshot_row_dict(row: dict[str, Any]) -> SignalInput:
    """Build SignalInput from a sqlite Row-like dict (e.g. snapshots.*)."""
    spot = _positive_float_required(row, "spot")

    kw: dict[str, Any] = {}
    for f in dataclasses.fields(SignalInput):
        if f.name in ("recent_crosses", "candles_5m", "candles_1m"):
            df = f.default_factory
            kw[f.name] = df() if df is not dataclasses.MISSING and callable(df) else []
            continue
        v = row.get(f.name)
        if v is not None:
            if f.name == "charm_magnitude" and isinstance(v, (int, float)) and not isinstance(v, bool):
                # DB may store a numeric charm score; SignalInput expects categorical str.
                kw[f.name] = None
            else:
                kw[f.name] = v
        elif f.default is not dataclasses.MISSING:
            kw[f.name] = f.default
        elif f.default_factory is not dataclasses.MISSING:
            df = f.default_factory
            kw[f.name] = df() if callable(df) else None
        else:
            kw[f.name] = None

    kw["ticker"] = str(row.get("ticker") or "").upper().strip()
    kw["timeframe"] = str(row.get("timeframe") or CANONICAL_TIMEFRAME)
    kw["spot"] = spot
    ts = row.get("ts_utc")
    if ts is not None:
        try:
            kw["refresh_ts_utc"] = float(ts)
        except (TypeError, ValueError):
            pass
    return SignalInput(**kw)
