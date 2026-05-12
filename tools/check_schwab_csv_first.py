#!/usr/bin/env python3
"""
Guard market-data edits with the Schwab CSV-first policy.

This is intentionally conservative: it scans a git diff for added lines that look
like market-data derivations/defaults and requires a nearby durable declaration
that the Schwab CSV authority was checked.
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"

CSV_MARKERS = (
    "Schwab CSV authority checked",
    "CSV row(s):",
    "NO_SCHWAB_EQUIVALENT",
    "SCHWAB_CSV_CHECKED",
)

MARKET_NAMES = re.compile(
    r"\b("
    r"spot|lastPrice|mark|bid|ask|bidPrice|askPrice|spread|volume|totalVolume|"
    r"openInterest|multiplier|daysToExpiration|expirationDate|theta|gamma|delta|"
    r"vega|rho|volatility|quoteTime|tradeTime|quoteTimeInLong|tradeTimeInLong|"
    r"vix|pcr|vwap|ohlc|open|high|low|close"
    r")\b",
    re.IGNORECASE,
)

MARKET_DATA_PATHS = (
    "server.py",
    "live_market_plane.py",
    "market_context.py",
    "market_state.py",
    "math_",
    "features/",
    "v2_decision/",
    "calibration/",
    "static/index.html",
    "backfill_flow_imbalance.py",
    "debug_flow_snapshot.py",
    "realized_contract_eval.py",
    "market_data_adapter.py",
    "snapshot_normalizer.py",
    "signals.py",
    "mc_fusion_adjustment.py",
    "order_flow_",
    "lstm_",
    "ml_",
    "transformer_",
    "prediction_engine.py",
    "liquidity_value_engine.py",
)

RISK_PATTERNS = (
    re.compile(r"\bor\s+0(?:\.0)?\b"),
    re.compile(r"\bor\s+1(?:\.0)?\b"),
    re.compile(r"\bor\s+100(?:\.0)?\b"),
    re.compile(r"\.get\([^\n\)]*,\s*(?:0|0\.0|1|1\.0|100|100\.0)\s*\)"),
    re.compile(r"\([^)]*(?:bid|bf)[^)]*\+[^)]*(?:ask|af)[^)]*\)\s*/\s*2(?:\.0)?", re.IGNORECASE),
    re.compile(r"(?:ask|af)\s*-\s*(?:bid|bf)", re.IGNORECASE),
    re.compile(r"time\.time\s*\("),
    re.compile(r"black[_-]?scholes|norm\.cdf|bs_", re.IGNORECASE),
)


def _load_canonical_fields() -> set[str]:
    if not CSV_PATH.exists():
        raise SystemExit(f"Missing Schwab CSV authority: {CSV_PATH}")
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        return {row["canonical_field"] for row in csv.DictReader(f)}


def _git_diff(*, staged: bool) -> str:
    args = ["git", "diff", "--cached" if staged else "--"]
    proc = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "git diff failed")
    return proc.stdout


def _added_lines(diff_text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    current = ""
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current = line.removeprefix("+++ b/")
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        content = line[1:]
        if content.strip().startswith("#"):
            continue
        out.append((current, content))
    return out


def _changed_paths(diff_text: str) -> set[str]:
    paths: set[str] = set()
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            paths.add(line.removeprefix("+++ b/"))
    return paths


def _is_market_data_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in MARKET_DATA_PATHS)


def _has_marker(diff_text: str) -> bool:
    return any(marker in diff_text for marker in CSV_MARKERS)


def _is_risky(line: str) -> bool:
    if not MARKET_NAMES.search(line):
        return False
    return any(pattern.search(line) for pattern in RISK_PATTERNS)


def _iter_repo_lines() -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    skip_parts = {".git", "__pycache__", ".venv", "venv", "node_modules", ".claude"}
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if any(part in skip_parts for part in path.parts):
            continue
        if not _is_market_data_path(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and _is_risky(stripped):
                out.append((rel, lineno, stripped))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce Schwab CSV-first review markers on risky market-data diffs.")
    parser.add_argument("--staged", action="store_true", help="Check staged diff instead of working tree diff.")
    parser.add_argument("--diff-file", type=Path, help="Check an explicit git diff file, used by CI.")
    parser.add_argument(
        "--whole-repo",
        action="store_true",
        help="Scan the current repository for risky market-data patterns, independent of git diff.",
    )
    args = parser.parse_args()

    canonical = _load_canonical_fields()
    if len(canonical) < 1000:
        raise SystemExit(f"Schwab CSV authority looks incomplete: {len(canonical)} fields")

    if args.whole_repo:
        risky_repo = _iter_repo_lines()
        if not risky_repo:
            print(f"Schwab CSV-first whole-repo guard passed ({len(canonical)} CSV fields loaded).")
            return 0
        print("Schwab CSV-first whole-repo guard FAILED.")
        print(f"CSV authority loaded: {CSV_PATH} ({len(canonical)} fields)")
        print("Risky market-data patterns remain in repository:")
        for path, lineno, line in risky_repo[:80]:
            print(f"- {path}:{lineno}: {line[:180]}")
        if len(risky_repo) > 80:
            print(f"... {len(risky_repo) - 80} more")
        return 1

    if args.diff_file:
        diff_text = args.diff_file.read_text(encoding="utf-8")
    else:
        diff_text = _git_diff(staged=args.staged)
    risky = [(path, line) for path, line in _added_lines(diff_text) if _is_risky(line)]
    changed_market_paths = sorted(p for p in _changed_paths(diff_text) if _is_market_data_path(p))
    if not risky and not changed_market_paths:
        print(f"Schwab CSV-first guard passed: no risky market-data additions found ({len(canonical)} CSV fields loaded).")
        return 0
    if _has_marker(diff_text):
        print(
            "Schwab CSV-first guard passed with declaration marker: "
            f"{len(risky)} risky market-data addition(s), "
            f"{len(changed_market_paths)} market-data file(s), {len(canonical)} CSV fields loaded."
        )
        return 0

    print("Schwab CSV-first guard FAILED.")
    print(f"CSV authority loaded: {CSV_PATH} ({len(canonical)} fields)")
    print("Market-data changes need a CSV-first declaration in the slice/commit/governance artifact:")
    print("  Schwab CSV authority checked: yes")
    print("  CSV row(s): <canonical_field rows or NO_SCHWAB_EQUIVALENT>")
    print("  Derived-field disposition: REPLACE_WITH_SCHWAB | KEEP_DERIVED_WITH_PROVENANCE | GATE_FAIL_CLOSED | REDESIGN")
    print("  All consumers checked: yes/no + disposition list")
    for path, line in risky[:40]:
        print(f"- {path}: {line.strip()[:180]}")
    if len(risky) > 40:
        print(f"... {len(risky) - 40} more")
    if changed_market_paths:
        print("Changed market-data files:")
        for path in changed_market_paths[:40]:
            print(f"- {path}")
        if len(changed_market_paths) > 40:
            print(f"... {len(changed_market_paths) - 40} more")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
