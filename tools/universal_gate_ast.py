"""Shared AST helpers for UNIVERSAL_FIX_IMPACT_GATE_V1 (no gate/build imports)."""
from __future__ import annotations

import ast
import re
from typing import Optional

_TICKER_LIKE_RE = re.compile(r"^[A-Z]{1,5}$|^\$[A-Z]{1,5}$")
# Routing-context symbols (guest tickers, audit fixtures) may exceed 5 chars.
_ROUTING_SYMBOL_RE = re.compile(r"^\$?[A-Z][A-Z0-9]{1,11}$")
_TICKER_VAR_NAMES = frozenset({"ticker", "symbol", "sym", "tkr", "underlying", "anchor"})
_HORIZON_VAR_NAMES = frozenset({"horizon", "horizon_slug", "slug", "hz", "tf", "timeframe"})

COMMON_NON_TICKERS: frozenset[str] = frozenset(
    {
        "API", "URL", "HTTP", "HTTPS", "JSON", "YAML", "SQL", "UTC", "ET", "DB",
        "ML", "UI", "OK", "FAIL", "GET", "POST", "PUT", "DELETE", "SSE", "RTH",
        "ETF", "USD", "EPS", "PE", "IV", "ATR", "VIX", "MACD", "RSI", "EMA",
        "SMA", "OHLC", "TRUE", "FALSE", "NONE", "NULL", "NAN", "ALL", "ANY",
        "MAX", "MIN", "AVG", "SUM", "STD", "VAR", "CPU", "GPU", "RAM", "SSD",
        "SHA", "HMAC", "JWT", "TLS", "SSL", "DNS", "TCP", "UDP", "IPC", "PID",
        "ENV", "CLI", "REPL", "AST", "UTF", "ASCII", "UUID", "ISO", "GMT",
        "EST", "PST", "CST", "MST", "EDT", "PDT", "CDT", "MDT", "HIGH", "LOW",
        "CALL", "WAIT", "FLAT", "LONG", "EDGE", "MOVE", "UP", "DOWN", "CORE",
        "XGB", "DIR", "LIVE", "MARK", "ABOVE", "BELOW", "FIXED", "MIXED",
        "SCALP", "GATES", "TRADE", "WATCH", "ZONE", "WEAK", "OMIT", "NO",
        "META", "GOOG", "FADE", "N", "BELOW", "ABOVE",
        "TRANSFORMER", "LSTM", "MONTE", "REGIME", "FUSION", "XGBOOST",
    }
)

ROUTING_MAP_NAMES = frozenset(
    {"routes", "route", "handlers", "handler_map", "anchor_map", "guest_map", "ticker_map"}
)


def is_ticker_like_symbol(val: str) -> bool:
    v = (val or "").strip().upper()
    if not v or v in COMMON_NON_TICKERS:
        return False
    return bool(_TICKER_LIKE_RE.match(v))


def is_routing_context_symbol(val: str) -> bool:
    """Symbol used in ticker routing context (includes long guest/audit symbols)."""
    v = (val or "").strip().upper()
    if not v or v in COMMON_NON_TICKERS:
        return False
    if len(v) < 2:
        return False
    return bool(_ROUTING_SYMBOL_RE.match(v))


def _is_ticker_var(name: str) -> bool:
    low = name.lower()
    return any(tok in low for tok in _TICKER_VAR_NAMES) or low.endswith("_ticker")


def _is_horizon_var(name: str) -> bool:
    low = name.lower()
    return any(tok in low for tok in _HORIZON_VAR_NAMES) or low.endswith("_horizon")


def _string_from_node(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.strip()
    return None


def _symbols_in_container(node: ast.AST) -> set[str]:
    found: set[str] = set()
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        for elt in node.elts:
            s = _string_from_node(elt)
            if s and is_routing_context_symbol(s):
                found.add(s.upper())
    return found


def collect_routing_symbols_from_source(src: str, relpath: str = "") -> set[str]:
    """Collect ticker-like symbols used in routing contexts (registry inventory)."""
    found: set[str] = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, ast.In):
                    left = node.left
                    if isinstance(left, ast.Name) and _is_ticker_var(left.id):
                        found |= _symbols_in_container(comp)
                elif isinstance(op, (ast.Eq, ast.NotEq)):
                    s = _string_from_node(comp)
                    if s and is_routing_context_symbol(s):
                        var = node.left if isinstance(node.left, ast.Name) else None
                        if var and _is_ticker_var(var.id):
                            found.add(s.upper())
        if isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                s = sl.value.strip()
                if is_routing_context_symbol(s):
                    base = node.value
                    if isinstance(base, ast.Name) and base.id.lower() in ROUTING_MAP_NAMES:
                        found.add(s.upper())
        if isinstance(node, ast.Match):
            for case in node.cases:
                for pat in case.pattern.values if hasattr(case.pattern, "values") else []:
                    s = _string_from_node(pat)
                    if s and is_routing_context_symbol(s):
                        found.add(s.upper())
                if isinstance(case.pattern, ast.MatchAs) and case.pattern.name:
                    pass
                if isinstance(case.pattern, ast.Constant):
                    s = _string_from_node(case.pattern)
                    if s and is_routing_context_symbol(s):
                        found.add(s.upper())
                if isinstance(case.pattern, ast.MatchValue):
                    s = _string_from_node(case.pattern.value)
                    if s and is_routing_context_symbol(s):
                        found.add(s.upper())
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and "TICKER" in tgt.id.upper():
                    s = _string_from_node(node.value)
                    if s and is_routing_context_symbol(s):
                        found.add(s.upper())
    return found


def scan_ticker_routing_violations(
    src: str,
    relpath: str,
    *,
    known_symbols: frozenset[str],
    allowlist: Optional[dict[tuple[str, str, str], str]] = None,
) -> list[tuple[str, int, str]]:
    """Return (code, line, message) for unknown routing symbols in production."""
    from tools.check_universal_ticker_lock import TICKER_LITERAL_ALLOWLIST  # lazy

    allow = TICKER_LITERAL_ALLOWLIST if allowlist is None else allowlist
    rel_norm = relpath.replace("\\", "/")
    violations: list[tuple[str, int, str]] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return violations

    def _check_symbol(sym: str, lineno: int, ctx: str, fn: str = "<module>") -> None:
        su = sym.upper()
        if not is_routing_context_symbol(su):
            return
        if su in known_symbols:
            return
        key = (rel_norm, fn, su)
        if key in allow:
            return
        violations.append(
            (
                "FUTURE_ENTITY_INVENTORY_DRIFT",
                lineno,
                f"{relpath}:{lineno} routing symbol {su!r} in {ctx} not in "
                f"known_routing_symbols inventory — regen inventory",
            )
        )

    fn_name = "<module>"
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_name = node.name
        if isinstance(node, ast.Compare):
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, ast.In):
                    left = node.left
                    if isinstance(left, ast.Name) and _is_ticker_var(left.id):
                        for s in _symbols_in_container(comp):
                            _check_symbol(s, node.lineno, "membership test", fn_name)
                elif isinstance(op, (ast.Eq, ast.NotEq)):
                    s = _string_from_node(comp)
                    var = node.left if isinstance(node.left, ast.Name) else None
                    if s and var and _is_ticker_var(var.id):
                        _check_symbol(s, node.lineno, f"compare to {var.id}", fn_name)
        if isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                s = sl.value.strip()
                base = node.value
                if isinstance(base, ast.Name) and base.id.lower() in ROUTING_MAP_NAMES:
                    _check_symbol(s, node.lineno, f"map subscript {base.id}", fn_name)
        if isinstance(node, ast.Match):
            for case in node.cases:
                if isinstance(case.pattern, ast.MatchValue):
                    s = _string_from_node(case.pattern.value)
                    if s:
                        _check_symbol(s, node.lineno, "match/case", fn_name)
                for pat in getattr(case.pattern, "values", []) or []:
                    s = _string_from_node(pat)
                    if s:
                        _check_symbol(s, node.lineno, "match/case", fn_name)
                if isinstance(case.pattern, ast.Constant):
                    s = _string_from_node(case.pattern)
                    if s:
                        _check_symbol(s, node.lineno, "match/case", fn_name)
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and "TICKER" in tgt.id.upper():
                    s = _string_from_node(node.value)
                    if s:
                        _check_symbol(s, node.lineno, f"assign {tgt.id}", fn_name)
    return violations
