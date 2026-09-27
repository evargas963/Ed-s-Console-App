"""UNIVERSAL ticker-scope lock helpers (RC-160).

Operator mandate 2026-07-30: work is UNIVERSAL across the enrolled universe — SPY-only /
sentinel-only framing without explicit OUT-OF-SCOPE + operator waiver is a breach.

Consumed by tools/check_institutional_correctness.py (check_universal_ticker_scope). BEDROCK
2026-09-06: the prose half (SPY-only PHRASES in prompt text, and the PreToolUse Edit gate that
read them) is removed — free-text matching is not enforcement (AGENTS.md). What stays is the
structural half: SPY-only ticker DEFAULTS in experiment tools (AST). The law is unchanged.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _ticker_list_from_ast(node: ast.AST) -> list[str] | None:
    """Return ticker symbols if `node` is a literal list/tuple/str of tickers; else None."""
    s = _const_str(node)
    if s is not None:
        parts = [p.strip().upper() for p in s.replace(";", ",").split(",") if p.strip()]
        return parts or None
    if isinstance(node, (ast.List, ast.Tuple)):
        out: list[str] = []
        for elt in node.elts:
            v = _const_str(elt)
            if v is None:
                return None
            out.append(v.strip().upper())
        return out
    return None


def _is_spy_only_tickers(tickers: list[str]) -> bool:
    return len(tickers) == 1 and tickers[0] == "SPY"


def _has_scope_escape(src: str, lineno: int) -> bool:
    """True when the line or the contiguous comment block above it carries an escape marker."""
    lines = src.splitlines()
    i = max(0, lineno - 1)
    window = lines[max(0, i - 6): i + 1]
    blob = "\n".join(window)
    return bool(
        re.search(r"universal-scope-ok|spy-sample-ok|OUT-OF-SCOPE|operator\s+waiver", blob, re.I)
    )


def spy_only_ticker_default_violations(path: Path, src: str) -> list[tuple[int, str]]:
    """AST: argparse --tickers default or module TICKERS/DEFAULT_TICKERS that is SPY alone."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        # add_argument("--tickers", default="SPY") / default=["SPY"]
        if isinstance(node, ast.Call):
            args_are_tickers = any(
                isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value in (
                    "--tickers", "tickers",
                )
                for a in node.args
            )
            if not args_are_tickers:
                continue
            for kw in node.keywords:
                if kw.arg != "default":
                    continue
                tickers = _ticker_list_from_ast(kw.value)
                if tickers is None or not _is_spy_only_tickers(tickers):
                    continue
                if _has_scope_escape(src, node.lineno):
                    continue
                hits.append((
                    node.lineno,
                    f"--tickers default is SPY-only ({tickers!r}); use enrolled universe "
                    f"or mark # universal-scope-ok: OUT-OF-SCOPE: <reason> (RC-160)",
                ))
        # Module-level TICKERS = ["SPY"] / DEFAULT_TICKERS = ("SPY",)
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if not isinstance(t, ast.Name):
                    continue
                if t.id not in ("TICKERS", "DEFAULT_TICKERS", "TICKER_UNIVERSE"):
                    continue
                tickers = _ticker_list_from_ast(node.value)
                if tickers is None or not _is_spy_only_tickers(tickers):
                    continue
                if _has_scope_escape(src, node.lineno):
                    continue
                hits.append((
                    node.lineno,
                    f"{t.id} is SPY-only ({tickers!r}); use enrolled universe or mark "
                    f"# universal-scope-ok: OUT-OF-SCOPE: <reason> (RC-160)",
                ))
    return hits


def experiment_tool_paths(repo: Path) -> list[Path]:
    """Experiment / liquidity study tools whose ticker defaults are policed."""
    tools = repo / "tools"
    if not tools.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(tools.glob("liquidity_*.py")):
        out.append(p)
    for p in sorted(tools.glob("*_experiment*.py")):
        if p not in out:
            out.append(p)
    for p in sorted(tools.glob("lp01_*.py")):
        if p not in out:
            out.append(p)
    return out
