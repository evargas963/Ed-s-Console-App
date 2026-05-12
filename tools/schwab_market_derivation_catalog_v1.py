#!/usr/bin/env python3
"""
Schwab coverage proof — AST-first market-derivation catalog (v1 scaffold).

**Program bar (operator):** every site that computes, defaults, or derives a
market-data primitive or analytic must be evaluated against
`schwab_field_inventory/schwab_field_dictionary.csv`, with disposition recorded.

**What v1 does:** walks Python files, uses ``ast`` (not line-regex) to flag
high-signal *structural* patterns that often indicate derivation/defaulting:
mid-price style division, ``x or 0`` defaults, ``dict.get(..., default)`` with
market-like keys, and a small set of named calls (e.g. ``time.time`` as time
fallback — flagged as TIME_NOW_FALLBACK for review).

**What v1 does NOT yet claim:** exhaustive detection of every derivation in the
repo. Magic constants, deep model math, and novel patterns require expanding
this visitor and/or manual extension of the working register. Empty output
residual for this tool alone is **not** proof of full coverage — it is one
layer toward the register the bar requires.

Output: working CSV for human/machine follow-up (`disposition` defaults to
``UNREVIEWED``). Buckets after review: ``REPLACED``, ``GOVERNED_EXCEPTION``,
``NO_SCHWAB_EQUIVALENT`` (per operator schema).

By default, ``.claude/`` (Cursor worktrees) is skipped. Use ``--include-claude-worktrees`` to scan it.

Examples:
  python tools/schwab_market_derivation_catalog_v1.py
  python tools/schwab_market_derivation_catalog_v1.py --include-tests --max-files 50
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHWAB_CSV = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"
DEFAULT_OUT = ROOT / "governance" / "SCHWAB_COVERAGE_CATALOG_V1_WORKING.csv"

# Applied per path `parts`; `.claude` excluded by default (Cursor worktrees mirror the repo).
BASE_SKIP_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".pytest_cache",
        ".mypy_cache",
        "backups",
    }
)
DOT_CLAUDE = ".claude"

# Identifiers / literal keys that suggest market primitives (expand over time).
MARKET_IDENTS = frozenset(
    {
        "bid",
        "ask",
        "last",
        "lastPrice",
        "mark",
        "mid",
        "spread",
        "volume",
        "totalVolume",
        "openInterest",
        "oi",
        "spot",
        "open",
        "high",
        "low",
        "close",
        "delta",
        "gamma",
        "theta",
        "vega",
        "rho",
        "volatility",
        "iv",
        "daysToExpiration",
        "dte",
        "expiration",
        "quote",
        "chain",
        "candle",
        "bar",
        "vwap",
    }
)

MARKET_GET_KEYS = frozenset(
    {
        "bid",
        "ask",
        "last",
        "lastPrice",
        "mark",
        "totalVolume",
        "volume",
        "openInterest",
        "delta",
        "gamma",
        "theta",
        "vega",
        "rho",
        "volatility",
        "open",
        "high",
        "low",
        "close",
        "daysToExpiration",
    }
)

SUSPICIOUS_CALL_NAMES = frozenset({"black_scholes", "bs_price", "norm_cdf", "norm_pdf"})

# Limit `time.time()` flags to paths likely to be market/runtime (reduces test-harness noise).
_MARKET_PATH_SUBSTR = (
    "server.py",
    "market_",
    "live_market",
    "signals.py",
    "order_flow",
    "features/",
    "v2_decision",
    "math_",
    "liquidity",
    "prediction",
    "lstm",
    "ml_",
    "db.py",
    "calibration/",
    "monte_carlo",
    "micro_structure",
    "market_data_adapter",
    "market_context",
    "market_state",
)


def _market_weighted_path(rel: str) -> bool:
    rl = rel.replace("\\", "/")
    return any(s in rl for s in _MARKET_PATH_SUBSTR)


@dataclass
class Finding:
    path: str
    line: int
    col: int
    pattern_kind: str
    summary: str
    tokens: tuple[str, ...]

    def row_dict(self, csv_candidates: str) -> dict[str, str]:
        h = hashlib.sha256(
            f"{self.path}:{self.line}:{self.col}:{self.pattern_kind}".encode()
        ).hexdigest()[:16]
        return {
            "catalog_id": h,
            "path": self.path,
            "line": str(self.line),
            "col": str(self.col),
            "pattern_kind": self.pattern_kind,
            "summary": self.summary,
            "tokens": " ".join(self.tokens),
            "csv_candidate_fields": csv_candidates,
            "disposition": "UNREVIEWED",
            "canonical_field_citation": "",
            "governed_ref": "",
            "notes": "",
        }


def _tokenize_canonical_field(name: str) -> list[str]:
    parts = re.split(r"[^a-zA-Z0-9]+", name.lower())
    return [p for p in parts if len(p) > 2]


def load_schwab_index(csv_path: Path) -> dict[str, list[str]]:
    """Map lowercase token -> canonical_field rows that contain token."""
    by_tok: dict[str, list[str]] = defaultdict(list)
    with csv_path.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            cf = (row.get("canonical_field") or "").strip()
            if not cf:
                continue
            seen_tok: set[str] = set()
            for tok in _tokenize_canonical_field(cf):
                if tok not in seen_tok:
                    seen_tok.add(tok)
                    by_tok[tok].append(cf)
    return by_tok


def csv_candidates_for_tokens(index: dict[str, list[str]], tokens: Iterable[str]) -> str:
    hits: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        tl = str(t).lower()
        if len(tl) < 2:
            continue
        for cf in index.get(tl, ()):
            if cf not in seen:
                seen.add(cf)
                hits.append(cf)
                if len(hits) >= 25:
                    return ";".join(hits)
    return ";".join(hits)


def _is_zeroish(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        v = node.value
        if v == 0 or v == 0.0:
            return True
    return False


def _collect_idents(node: ast.AST, out: set[str]) -> None:
    if isinstance(node, ast.Name):
        out.add(node.id)
    elif isinstance(node, ast.Attribute):
        out.add(node.attr)
        _collect_idents(node.value, out)
    elif isinstance(node, ast.BinOp):
        _collect_idents(node.left, out)
        _collect_idents(node.right, out)
    elif isinstance(node, ast.UnaryOp):
        _collect_idents(node.operand, out)
    elif isinstance(node, ast.Call):
        _collect_idents(node.func, out)
        for a in node.args:
            _collect_idents(a, out)
        for kw in node.keywords:
            if kw.value is not None:
                _collect_idents(kw.value, out)


def _id_intersects_market(idents: set[str]) -> bool:
    return bool(idents & MARKET_IDENTS)


class DerivationVisitor(ast.NodeVisitor):
    def __init__(self, file_rel: str, findings: list[Finding]) -> None:
        self.file_rel = file_rel
        self.findings = findings

    def _add(self, node: ast.AST, kind: str, summary: str, tokens: set[str]) -> None:
        line = getattr(node, "lineno", 0) or 0
        col = getattr(node, "col_offset", 0) or 0
        self.findings.append(
            Finding(
                path=self.file_rel,
                line=line,
                col=col,
                pattern_kind=kind,
                summary=summary[:500],
                tokens=tuple(sorted(tokens))[:40],
            )
        )

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        if isinstance(node.op, ast.Div):
            idents: set[str] = set()
            _collect_idents(node, idents)
            if _id_intersects_market(idents):
                self._add(
                    node,
                    "BINOP_DIV_MARKET_IDENT",
                    "Division involving market-like identifiers (e.g. mid/spread math)",
                    idents & MARKET_IDENTS | idents,
                )
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        if isinstance(node.op, ast.Or) and node.values:
            left = node.values[0]
            for fallback in node.values[1:]:
                if _is_zeroish(fallback):
                    idents: set[str] = set()
                    _collect_idents(left, idents)
                    if _id_intersects_market(idents):
                        self._add(
                            node,
                            "DEFAULT_OR_ZERO_BOOL",
                            "`a or 0`-style default with market-like left operand",
                            idents & MARKET_IDENTS,
                        )
                    break
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        # `x if x is not None else 0` patterns: check orelse zeroish
        if _is_zeroish(node.orelse):
            idents: set[str] = set()
            _collect_idents(node.body, idents)
            _collect_idents(node.test, idents)
            if _id_intersects_market(idents):
                self._add(
                    node,
                    "DEFAULT_ZERO_IFEXP",
                    "Conditional expression with zeroish fallback; check for market defaulting",
                    idents & MARKET_IDENTS,
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        # dict.get("volume", 0)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            if node.args:
                key = node.args[0]
                sk: str | None = None
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    sk = key.value
                elif isinstance(key, ast.Str):  # py<3.8 compat unused in 3.10+
                    sk = key.s
                if sk and sk in MARKET_GET_KEYS and len(node.args) >= 2:
                    default = node.args[1]
                    if _is_zeroish(default) or isinstance(
                        default, (ast.Constant, ast.Name, ast.Attribute)
                    ):
                        self._add(
                            node,
                            "DICT_GET_MARKET_DEFAULT",
                            f".get({sk!r}, <default>) on market-like key",
                            {sk, "get"},
                        )
        # time.time() as fallback clock
        if isinstance(node.func, ast.Attribute) and node.func.attr == "time":
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "time":
                if not node.args and _market_weighted_path(self.file_rel):
                    self._add(
                        node,
                        "TIME_NOW_FALLBACK",
                        "time.time() call — review vs Schwab quote/trade timestamps",
                        {"time", "time.time"},
                    )
        if isinstance(node.func, ast.Name) and node.func.id in SUSPICIOUS_CALL_NAMES:
            self._add(
                node,
                "NAMED_DERIVATION_CALL",
                f"Call to {node.func.id} — review vs Schwab primitives",
                {node.func.id},
            )
        self.generic_visit(node)


def iter_py_files(
    root: Path,
    *,
    include_tests: bool,
    include_claude_worktrees: bool = False,
) -> Iterable[Path]:
    skip = set(BASE_SKIP_DIRS)
    if not include_claude_worktrees:
        skip.add(DOT_CLAUDE)
    for p in root.rglob("*.py"):
        parts = set(p.parts)
        if skip & parts:
            continue
        rel = p.relative_to(root).as_posix()
        if not include_tests and (
            rel.startswith("tests/")
            or rel.startswith("test_")
            or "/test_" in rel
        ):
            continue
        if rel.startswith("governance/") or rel.startswith("docs/"):
            continue
        yield p


def scan_file(path: Path, root: Path, findings: list[Finding]) -> None:
    rel = path.relative_to(root).as_posix()
    try:
        src = path.read_text(encoding="utf-8")
    except OSError:
        return
    try:
        tree = ast.parse(src, filename=rel)
    except SyntaxError:
        return
    DerivationVisitor(rel, findings).visit(tree)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="AST-first catalog of market derivation/default sites (coverage proof scaffold v1).",
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root (default: EdWebConsole root)",
    )
    ap.add_argument(
        "--schwab-csv",
        type=Path,
        default=SCHWAB_CSV,
        help="Schwab canonical_field CSV",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUT,
        help="Output working register CSV",
    )
    ap.add_argument(
        "--include-tests",
        action="store_true",
        help="Include tests/ and test_*.py (default: production paths only)",
    )
    ap.add_argument(
        "--include-claude-worktrees",
        action="store_true",
        help="Scan .claude/ (e.g. Cursor worktrees); default excludes to avoid duplicate findings.",
    )
    ap.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Stop after N files (smoke / dev)",
    )
    args = ap.parse_args()
    root = args.root.resolve()
    idx = load_schwab_index(args.schwab_csv.resolve())

    findings: list[Finding] = []
    n = 0
    for py in sorted(
        iter_py_files(
            root,
            include_tests=args.include_tests,
            include_claude_worktrees=args.include_claude_worktrees,
        )
    ):
        scan_file(py, root, findings)
        n += 1
        if args.max_files is not None and n >= args.max_files:
            break

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "catalog_id",
        "path",
        "line",
        "col",
        "pattern_kind",
        "summary",
        "tokens",
        "csv_candidate_fields",
        "disposition",
        "canonical_field_citation",
        "governed_ref",
        "notes",
    ]
    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for fn in findings:
            toks = [t.lower() for t in fn.tokens]
            cand = csv_candidates_for_tokens(idx, toks)
            w.writerow(fn.row_dict(cand))

    print(
        json.dumps(
            {
                "files_scanned": n,
                "findings": len(findings),
                "output": str(args.output.resolve()),
                "disclaimer": (
                    "v1 AST patterns are not exhaustive; disposition UNREVIEWED until human proof."
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
