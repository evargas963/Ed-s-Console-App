# chains.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from math_exposure_core import _f as _safe_float  # canonical float parser

@dataclass(frozen=True)
class QuoteBlock:
    last: float | None
    bid: float | None
    ask: float | None
    mark: float | None
    session_label: str
    raw: dict

def parse_quote_payload(ticker: str, quote_json: dict, session_label: str) -> QuoteBlock:
    """
    Parse Schwab quote response into a QuoteBlock.
    session_label must be passed in from MarketContext.session_label — it is a global
    market state derived once from SPY, not per-ticker.
    """
    node = quote_json.get(ticker.upper()) or quote_json.get(ticker) or {}
    q    = node.get("quote", {}) or {}
    last = _safe_float(q.get("lastPrice"))
    bid  = _safe_float(q.get("bidPrice"))
    ask  = _safe_float(q.get("askPrice"))
    mark = _safe_float(q.get("mark"))
    return QuoteBlock(last=last, bid=bid, ask=ask, mark=mark,
                      session_label=session_label, raw=quote_json)


def iter_contracts(chain_json: dict) -> Iterable[dict]:
    """
    Walk Schwab chain map:
      callExpDateMap: { '2026-01-10:7': { '613.0': [contract...], ... }, ... }
      putExpDateMap:  same
    """
    for side_key in ("callExpDateMap", "putExpDateMap"):
        m = chain_json.get(side_key) or {}
        for exp_map in m.values():
            if not isinstance(exp_map, dict):
                continue
            for strike_list in exp_map.values():
                if not isinstance(strike_list, list):
                    continue
                for ct in strike_list:
                    if isinstance(ct, dict):
                        yield ct

def contract_fields(ct: dict) -> dict:
    """
    Normalize only what we need. Keep raw values too.
    """
    return {
        "putCall": ct.get("putCall"),
        "strikePrice": ct.get("strikePrice"),
        "openInterest": ct.get("openInterest"),
        "delta": ct.get("delta"),
        "gamma": ct.get("gamma"),
        "theta": ct.get("theta"),
        "vega": ct.get("vega"),
        "rho": ct.get("rho"),
        "theoreticalVolatility": ct.get("theoreticalVolatility"),
        "theoreticalOptionValue": ct.get("theoreticalOptionValue"),
        "volatility": ct.get("volatility"),
        "daysToExpiration": ct.get("daysToExpiration"),
        "expirationDate": ct.get("expirationDate"),
        "expirationType": ct.get("expirationType"),
        "settlementType": ct.get("settlementType"),
        "exerciseType": ct.get("exerciseType"),
        "lastTradingDay": ct.get("lastTradingDay"),
        "multiplier": ct.get("multiplier", 100),
        "mark": ct.get("mark"),
        "bid": ct.get("bid"),
        "ask": ct.get("ask"),
        "last": ct.get("last"),
        "openPrice": ct.get("openPrice"),
        "highPrice": ct.get("highPrice"),
        "lowPrice": ct.get("lowPrice"),
        "closePrice": ct.get("closePrice"),
        "totalVolume": ct.get("totalVolume"),
        "bidSize": ct.get("bidSize"),
        "askSize": ct.get("askSize"),
        "bidAskSize": ct.get("bidAskSize"),
        "lastSize": ct.get("lastSize"),
        "quoteTimeInLong": ct.get("quoteTimeInLong"),
        "tradeTimeInLong": ct.get("tradeTimeInLong"),
        "extrinsicValue": ct.get("extrinsicValue"),
        "timeValue": ct.get("timeValue"),
        "intrinsicValue": ct.get("intrinsicValue"),
        "inTheMoney": ct.get("inTheMoney"),
        "nonStandard": ct.get("nonStandard"),
        "mini": ct.get("mini"),
        "pennyPilot": ct.get("pennyPilot"),
        "deliverableNote": ct.get("deliverableNote"),
        "symbol": ct.get("symbol"),
        "raw": ct,
    }
