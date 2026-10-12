"""Real option chains the capture daemon captured on 2026-10-07 (production complete_chain_captures,
read-only), each with Schwab's underlying price in the capture and the instant it was captured --
the valuation instant a test prices it at (`now`), inside the sessions Schwab's /markets answers
(tests/conftest.py).

SPY_0DTE: SPY's same-day expiry (2026-10-07) at 12:32:07 ET, the 20 strikes nearest the price.
CRWD:     CRWD's 2026-10-16 expiry, every strike (strike_range=ALL), at 10:38:40 ET.
TSLA:     TSLA's 2026-10-09 expiry, every strike (strike_range=ALL), at 12:32:15 ET.
MRVL:     MRVL's full chain, all 20 expiries, every strike, at 10:31:20 ET (spot: the front
          expiry's answer).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from time_et import ET

_FX = Path(__file__).resolve().parent / "fixtures"


@dataclass(frozen=True)
class RealChain:
    ticker: str
    chain: list
    spot: float
    now: datetime


def _load(name: str) -> RealChain:
    d = json.loads((_FX / name).read_text(encoding="utf-8"))
    return RealChain(d["ticker"], d["chain"], float(d["spot"]), datetime.fromtimestamp(d["ts_utc"], ET))


SPY_0DTE = _load("real_spy_0dte_chain_2026_10_07.json")
CRWD = _load("real_crwd_complete_chain_2026_10_07.json")
TSLA = _load("real_tsla_complete_chain_2026_10_07.json")
MRVL = _load("real_mrvl_full_chain_2026_10_07.json")
