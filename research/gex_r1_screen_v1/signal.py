"""0DTE GEX proxy from stored selected-expiry chain JSON."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.domain.time_et import ET, RTH_START_MINS, is_trading_day_et  # RC-58: the one calendar authority


@dataclass(frozen=True)
class MorningSignal:
    ticker: str
    et_date: str
    ts_utc: float
    spot: float
    gex_0dte: float
    gex_sign: int
    n_contracts: int
    n_calls: int
    n_puts: int
    net_gamma_snapshot: float | None
    sign_agrees_net_gamma: bool | None
    expiry: str | None


def _et_mins(ts_utc: float) -> int:
    dt = datetime.fromtimestamp(float(ts_utc), tz=timezone.utc).astimezone(ET)
    return int(dt.hour * 60 + dt.minute)


def _et_date(ts_utc: float) -> str:
    dt = datetime.fromtimestamp(float(ts_utc), tz=timezone.utc).astimezone(ET)
    return dt.strftime("%Y-%m-%d")


def gex_0dte_from_chain(chain: list[dict[str, Any]], spot: float) -> tuple[float, int, int]:
    """Net GEX via the LIVE computation — single source of truth (GOVERNING LAW).

    Delegates to ``compute_exposures_by_strike`` -> ``aggregate_net_gex`` (the exact
    functions the live app uses); no reimplementation of the math here. Numerically
    identical to the prior standalone formula (verified 2026-07-17: ratio 1.0000,
    sign-match, to the decimal, SPY/QQQ/IWM). Returns (net_gex, n_calls, n_puts);
    counts use the same sanitizer as the live path.
    """
    from math_exposure_core import (
        aggregate_net_gex,
        compute_exposures_by_strike,
        gamma_is_plausible,
    )

    if spot <= 0 or not math.isfinite(spot):
        return float("nan"), 0, 0
    exposures, _diag = compute_exposures_by_strike(chain, spot=spot, require_oi=False)
    gex = aggregate_net_gex(exposures, sorted(exposures.keys()))
    if gex is None or not math.isfinite(gex):
        return float("nan"), 0, 0

    n_c = n_p = 0
    for ct in chain:
        if not isinstance(ct, dict):
            continue
        g = ct.get("gamma")
        oi = ct.get("openInterest")
        if g is None or oi is None:
            continue
        try:
            gf = float(g)
            oif = float(oi)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(oif) or oif < 0:
            continue
        try:
            df = float(ct["delta"]) if ct.get("delta") is not None else None
        except (TypeError, ValueError):
            df = None
        if not gamma_is_plausible(gf, df):
            continue
        pc = str(ct.get("putCall") or "").upper()
        if pc.startswith("C"):
            n_c += 1
        elif pc.startswith("P"):
            n_p += 1
    return float(gex), n_c, n_p


def load_morning_signals(
    db_path: str,
    tickers: list[str],
    *,
    start_mins: int | None = None,
    end_mins: int = 615,
) -> list[MorningSignal]:
    """First snapshot/day with option_chain_json in the morning ET window."""
    if start_mins is None:
        start_mins = RTH_START_MINS
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out: list[MorningSignal] = []
    for ticker in tickers:
        rows = conn.execute(
            """
            SELECT ts_utc, spot, net_gamma, option_chain_json, expiry
            FROM snapshots
            WHERE ticker=?
              AND option_chain_json IS NOT NULL
              AND length(option_chain_json) > 10
              AND spot IS NOT NULL AND spot > 0
            ORDER BY ts_utc ASC
            """,
            (ticker,),
        ).fetchall()
        seen: set[str] = set()
        for r in rows:
            ts = float(r["ts_utc"])
            mins = _et_mins(ts)
            if mins < start_mins or mins > end_mins:
                continue
            day = _et_date(ts)
            if not is_trading_day_et(day):
                continue      # RC-58: minute windows admit weekend/holiday snapshots; a
                              # market-closed morning is frozen data, not a signal
            if day in seen:
                continue
            try:
                chain = json.loads(r["option_chain_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(chain, list) or not chain:
                continue
            spot = float(r["spot"])
            gex, n_c, n_p = gex_0dte_from_chain(chain, spot)
            if not math.isfinite(gex) or (n_c + n_p) < 4:
                continue
            sign = 1 if gex > 0 else (-1 if gex < 0 else 0)
            ng = r["net_gamma"]
            ng_f = float(ng) if ng is not None else None
            agree = None
            if ng_f is not None and math.isfinite(ng_f) and sign != 0:
                ng_sign = 1 if ng_f > 0 else (-1 if ng_f < 0 else 0)
                agree = ng_sign == sign
            seen.add(day)
            out.append(
                MorningSignal(
                    ticker=ticker,
                    et_date=day,
                    ts_utc=ts,
                    spot=spot,
                    gex_0dte=gex,
                    gex_sign=sign,
                    n_contracts=n_c + n_p,
                    n_calls=n_c,
                    n_puts=n_p,
                    net_gamma_snapshot=ng_f,
                    sign_agrees_net_gamma=agree,
                    expiry=str(r["expiry"]) if r["expiry"] is not None else None,
                )
            )
    conn.close()
    return out


def attach_gex_z(signals: list[MorningSignal], *, trail: int = 20) -> list[dict[str, Any]]:
    """Robust z vs trailing median/IQR per ticker (in-order)."""
    by_tk: dict[str, list[MorningSignal]] = {}
    for s in signals:
        by_tk.setdefault(s.ticker, []).append(s)
    rows: list[dict[str, Any]] = []
    for ticker, seq in by_tk.items():
        seq = sorted(seq, key=lambda x: x.et_date)
        hist: list[float] = []
        for s in seq:
            gex_z = float("nan")
            if len(hist) >= 5:
                arr = sorted(hist[-trail:])
                med = arr[len(arr) // 2]
                q1 = arr[len(arr) // 4]
                q3 = arr[(3 * len(arr)) // 4]
                iqr = max(q3 - q1, 1e-12)
                gex_z = (s.gex_0dte - med) / iqr
            hist.append(s.gex_0dte)
            rows.append(
                {
                    "ticker": s.ticker,
                    "et_date": s.et_date,
                    "ts_utc": s.ts_utc,
                    "spot": s.spot,
                    "gex_0dte": s.gex_0dte,
                    "gex_sign": s.gex_sign,
                    "gex_z": gex_z,
                    "n_contracts": s.n_contracts,
                    "net_gamma_snapshot": s.net_gamma_snapshot,
                    "sign_agrees_net_gamma": s.sign_agrees_net_gamma,
                    "expiry": s.expiry,
                }
            )
    return rows
