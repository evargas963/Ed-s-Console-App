"""Every Schwab numeric field is read through `numeric_contract.schwab_number` / `schwab_count`
(AGENTS.md rule 2).

Failures this catches: raw ``float(ct.get("strikePrice"))`` admitted NaN (2026-07-25); and
(2026-09-27) the older readers -- ``float_finite_or_none``, ``float_nonnegative_or_none``,
``float_positive_or_none`` and local delegates of them -- passed Schwab's -999 and text through
as numbers, and dropped a reported 0 price or volume (114,675 zero-volume bars fell out of VWAP).

A violation: any numeric converter other than the two Schwab readers applied to a Schwab field
read -- directly (``conv(x.get("F"))``, ``conv(x["F"])``, ``conv(f(x, "F"))``) or through a name
bound from one in the same scope. Converters: ``float``, ``int``, every other function in
``numeric_contract``, and any scanned function that returns a converter's result without calling
a Schwab reader. Parsed with ``ast``; no exceptions list.

Run standalone:   python tools/check_vendor_field_coercion.py
Exit code 0 = clean, 1 = violations found.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Numeric leaves of a Schwab option-chain contract / quote (REST).
VENDOR_FIELDS = frozenset({
    "strikePrice", "totalVolume", "openInterest", "gamma", "delta", "theta", "vega",
    "volatility", "bid", "ask", "mark", "last", "lastSize", "bidSize", "askSize",
    "multiplier", "daysToExpiration", "highPrice", "lowPrice", "openPrice",
    "closePrice", "netChange", "lastPrice", "mid",
    "underlyingPrice", "rho", "theoreticalOptionValue", "theoreticalVolatility",
    "timeValue", "intrinsicValue", "markChange", "markPercentChange", "netPercentChange",
    "breakEven", "extrinsicValue", "high52Week", "low52Week", "percentChange",
    "deliverableUnits", "avg10DaysVolume",
    # Streamer LEVELONE_* / *_BOOK numeric fields.
    "BID_PRICE", "ASK_PRICE", "LAST_PRICE", "MARK", "TOTAL_VOLUME", "LAST_SIZE", "BID_SIZE",
    "ASK_SIZE", "OPEN_INTEREST", "DELTA", "GAMMA", "VOLATILITY", "THETA", "VEGA", "NET_CHANGE",
    "NET_CHANGE_PERCENT", "HIGH_PRICE", "LOW_PRICE", "OPEN_PRICE", "CLOSE_PRICE", "MULTIPLIER",
    "STRIKE_TYPE", "BOOK_TIME", "TRADE_TIME_MILLIS", "QUOTE_TIME_MILLIS",
})

#: Numeric contract leaves that are not prices/greeks/counts (ids, clocks, codes).
EXCLUDED_NUMERIC_LEAVES = frozenset({
    "quoteTimeInLong", "tradeTimeInLong", "lastTradingDay", "expirationDate", "ssid",
    "settlementType", "deliverableNote", "penny", "optionRoot",
})

SCHWAB_READERS = frozenset({"schwab_number", "schwab_count"})

EXCLUDE_DIRS = (".claude", ".venv", "node_modules", "research", "schwab-py-main", "__pycache__",
                "tools", "tests", "calibration")


def numeric_contract_converters() -> frozenset[str]:
    tree = ast.parse((REPO / "numeric_contract.py").read_text(encoding="utf-8"))
    return frozenset({"float", "int"} | {
        n.name for n in tree.body if isinstance(n, ast.FunctionDef)} - SCHWAB_READERS)


def _name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


def _calls(node: ast.AST) -> set[str]:
    return {n for n in (_name(c.func) for c in ast.walk(node) if isinstance(c, ast.Call)) if n}


def _defs(tree: ast.AST) -> list:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def with_delegates(trees: list, conv: frozenset[str]) -> frozenset[str]:
    """`conv` plus every function in `trees` that returns a converter's result without calling
    a Schwab reader (so `_f`, imported from another module, is a converter too)."""
    conv, defs = set(conv), [d for t in trees for d in _defs(t)]
    grew = True
    while grew:
        grew = False
        for d in defs:
            if d.name in conv or _calls(d) & SCHWAB_READERS:
                continue
            if any(isinstance(r, ast.Return) and r.value is not None and _calls(r.value) & conv
                   for r in ast.walk(d)):
                conv.add(d.name)
                grew = True
    return frozenset(conv)


def scan_source(src: str, converters: frozenset[str] | None = None) -> list[tuple[int, str]]:
    """(line, message) for each Schwab field read through a converter other than a Schwab reader."""
    tree = ast.parse(src)
    conv = with_delegates([tree], converters if converters is not None else numeric_contract_converters())
    consts = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign)
              and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
              for t in n.targets if isinstance(t, ast.Name)}
    defs = _defs(tree)

    def field_read(e: ast.AST) -> str | None:
        if not isinstance(e, (ast.Call, ast.Subscript)) or _calls(e) & (conv | SCHWAB_READERS):
            return None
        for n in ast.walk(e):
            v = n.value if isinstance(n, ast.Constant) else consts.get(n.id) if isinstance(n, ast.Name) else None
            if isinstance(v, str) and v in VENDOR_FIELDS:
                return v
        return None

    out = set()
    for scope in [tree, *defs]:
        bound = {}
        for n in ast.walk(scope):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                f = field_read(n.value)
                if f:
                    bound[n.targets[0].id] = f
        for n in ast.walk(scope):
            if isinstance(n, ast.Call) and _name(n.func) in conv and n.args:
                a = n.args[0]
                f = field_read(a) or (bound.get(a.id) if isinstance(a, ast.Name) else None)
                if f:
                    out.add((n.lineno, f"Schwab field {f} read through {_name(n.func)}(); "
                                       f"use schwab_number / schwab_count"))
    return sorted(out)


def scanned_sources() -> dict[str, str]:
    out = {}
    for path in sorted(REPO.rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if rel != "numeric_contract.py" and rel.split("/")[0] not in EXCLUDE_DIRS and "/tests/" not in rel:
            out[rel] = path.read_text(encoding="utf-8")
    return out


def violations(sources: dict[str, str] | None = None) -> list[tuple[str, int, str]]:
    sources = scanned_sources() if sources is None else sources
    conv = with_delegates([ast.parse(s) for s in sources.values()], numeric_contract_converters())
    return [(rel, ln, msg) for rel, src in sources.items() for ln, msg in scan_source(src, conv)]


def main() -> int:
    found = violations()
    for rel, ln, msg in found:
        print(f"{rel}:{ln}  {msg}")
    print(f"vendor-field coercion: {len(found)} violation(s)")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
