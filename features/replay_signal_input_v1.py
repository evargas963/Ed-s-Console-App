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
from time_et import RTH_END_MINS
from volatility_regime import vol_percent_to_decimal

# VOL_INPUT_CONTRACT 1.0.0 (lane V1 - closes VOL-UNIT-001): the snapshots table
# persists iv_level / realized_vol in PERCENT (server.py snapshot stamp,
# db.py column comments) while the SignalInput contract is DECIMAL
# (signal_types.py:86-88). This builder is the replay-route conversion
# boundary and uses the SAME function as the live boundary
# (market_state vol_percent_to_decimal stamp) so both routes convert exactly
# once. Missing stays None (never 0); invalid (negative/non-finite) becomes
# None - explicitly unavailable, never directional evidence.
REPLAY_ROUTE_IDENTITY = "replay"
VOL_INPUT_CONTRACT_VERSION = "1.0.0"
_PERCENT_PERSISTED_VOL_FIELDS = ("iv_level", "realized_vol")


def _replay_vol_decimal(value):
    """Percent-persisted vol column -> canonical decimal, exactly once.

    vol_percent_to_decimal is idempotent for already-decimal values
    (<= VOL_DECIMAL_PERCENT_HEURISTIC passthrough), so a value that is somehow
    already decimal is not divided again (no double conversion). Negative or
    non-finite values violate the ratified range (0, 5.0] and are classified
    unavailable (None) rather than passed through as fake evidence."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")) or v < 0:
        return None
    return vol_percent_to_decimal(v)


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
    if kw.get("mins_to_close") is None:
        eh = kw.get("et_hour")
        em = kw.get("et_minute")
        if eh is not None and em is not None:
            try:
                kw["mins_to_close"] = max(0.0, float(RTH_END_MINS) - (int(eh) * 60 + int(em)))
            except (TypeError, ValueError):
                pass
    # VOL_INPUT_CONTRACT 1.0.0 replay unit boundary (VOL-UNIT-001): convert the
    # percent-persisted vol columns to the decimal SignalInput contract using
    # the same canonical function as the live builder.
    for _vf in _PERCENT_PERSISTED_VOL_FIELDS:
        kw[_vf] = _replay_vol_decimal(kw.get(_vf))
    return SignalInput(**kw)
