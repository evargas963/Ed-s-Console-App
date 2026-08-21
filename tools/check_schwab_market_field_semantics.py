"""Mechanical lock: truthful semantics for two Schwab market-data fields (RC-440).

A trading system where "data IS the product" cannot let a field's NAME assert a
meaning the vendor has not proven, nor let a timestamp field silently become a
different clock. This lock mechanizes two closures from the Schwab semantic
normalization audit (reports/schwab_field_semantic_normalization_ledger_20260820.md):

M4 — NUM_BIDS / NUM_ASKS are NOT an order count.
  The Schwab Streamer Guide documents level field 2 as "Market Maker Count" (RC-443);
  empirically NUM_* == the count of nested per-participant rows at a book price level
  (31,614/31,614 on the RTH capture), where the participants are market-maker MPIDs
  AND exchange MICs. So it is a participant/market-maker count, NEVER an order count:
  labeling NUM_* an "order count" / "number of orders" wires a false book-depth
  authority, and asserting the documented "market-maker count" meaning must cite the
  vendor source rather than guess. This lock BLOCKS any production line that puts
  NUM_BIDS/NUM_ASKS next to an order-count / MM-count meaning unless a reasoned marker
  cites authoritative evidence (the Streamer Guide is that evidence for the count claim).

M5 — exchange_quote_ts is an EXCHANGE quote clock, not a server clock.
  `exchange_quote_ts` is produced as the Schwab QUOTE_TIME_MILLIS (with a TRADE_TIME_MILLIS
  proxy fallback) in epoch seconds; the genuine server wall clock is the separate
  `server_received_ts` (time.time()). The rename from the legacy `fast_server_ts` made
  the NAME truthful; this lock KEEPS it truthful by pinning its VALUE: it BLOCKS any
  production site that assigns a wall clock (time.time / datetime.now / monotonic /
  server_received_ts) to exchange_quote_ts, so the field can only ever carry the
  exchange quote timestamp and the name can never drift into a server clock by accident.

A site is CLEAN only through an explicit, reasoned marker:

    # num-semantics-ok: <authoritative vendor evidence for the claimed meaning>
    # exchange-quote-ts-ok: <why this assignment is provably the exchange quote clock>

Run standalone:   python tools/check_schwab_market_field_semantics.py [--verbose]
Exit code 0 = clean, 1 = a semantic overclaim found.

Schwab CSV authority: this governs HOW two Schwab leaves are LABELED/assigned; it reads
no market field itself. SCHWAB_CSV_CHECKED / NO_SCHWAB_EQUIVALENT (tooling gate).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Directories whose source is out of the live money-path (offline/vendored/generated).
EXCLUDE_DIRS = (
    ".claude", ".venv", "node_modules", "governance/archive", "research",
    "schwab-py-main", "__pycache__", "scratchpad",
)

NUM_SEMANTICS_MARKER = "num-semantics-ok"
EXCHANGE_QUOTE_TS_MARKER = "exchange-quote-ts-ok"

# M4: a NUM_BIDS/NUM_ASKS token co-located with an order-count / MM-count meaning.
_NUM_FIELD = re.compile(r"\bNUM_(?:BIDS|ASKS)\b", re.IGNORECASE)
_ORDER_COUNT_MEANING = re.compile(
    r"order[\s_-]*count"
    r"|number\s+of\s+orders"
    r"|count\s+of\s+orders"
    r"|orders\s+at\s+(?:this|the|a)\s+(?:level|price)"
    r"|\bn_orders\b"
    r"|market[\s_-]*maker\s+count"
    r"|\bmm[\s_-]*count\b",
    re.IGNORECASE,
)

# M5: exchange_quote_ts assigned from a wall clock (in code, either dict-key or bare-assign form).
_EXCHANGE_QUOTE_TS_WALLCLOCK = re.compile(
    r"""["']?exchange_quote_ts["']?\s*[:=]\s*"""
    r"""(?:time\.time\(\)|time\.monotonic\(\)|"""
    r"""datetime\.(?:now|utcnow)\b|server_received_ts\b|_now_wall\b|wall_clock\b)"""
)


def _is_excluded(path: Path) -> bool:
    rel = path.relative_to(REPO).as_posix()
    if rel.startswith("tools/") or rel.startswith("tests/") or "/tests/" in rel:
        return True
    for d in EXCLUDE_DIRS:
        if rel == d or rel.startswith(d + "/"):
            return True
    if path.name.startswith("test_") or path.name.endswith("_test.py"):
        return True
    return False


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return (lineno, kind, code) for each semantic overclaim in the file."""
    findings: list[tuple[int, str, str]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for i, line in enumerate(text.splitlines(), start=1):
        # M4: NUM_* labeled as an order/MM count.
        if _NUM_FIELD.search(line) and _ORDER_COUNT_MEANING.search(line):
            if NUM_SEMANTICS_MARKER not in line:
                findings.append((i, "num_order_count", line.strip()))
        # M5: exchange_quote_ts assigned a wall clock.
        if _EXCHANGE_QUOTE_TS_WALLCLOCK.search(line):
            if EXCHANGE_QUOTE_TS_MARKER not in line:
                findings.append((i, "exchange_quote_ts_wallclock", line.strip()))
    return findings


def _tracked_source_files() -> list[Path]:
    """Repo-wide product scope = the git INDEX, not the filesystem (RC-286/RC-307): a scanner
    that builds its own rglob list re-decides what "the repo" is and drifts onto untracked
    scratch. git ls-files is the one scope that cannot drift; it also skips gitignored trees
    (.venv, node_modules, __pycache__, scratchpad) for free."""
    r = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py", "*.html", "*.js"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError("git ls-files failed; the semantics gate must run inside the repo")
    return sorted(REPO / p for p in r.stdout.split("\0") if p)


def violations() -> list[tuple[str, int, str]]:
    """(rel_path, line, message) for each overclaim — for the gate wrapper."""
    out: list[tuple[str, int, str]] = []
    for path in _tracked_source_files():
        if _is_excluded(path) or not path.exists():
            continue
        rel = path.relative_to(REPO).as_posix()
        for (ln, kind, code) in scan_file(path):
            if kind == "num_order_count":
                msg = (
                    "NUM_BIDS/NUM_ASKS labeled as an order/market-maker count — vendor "
                    "semantics NOT_PROVEN (empirically it is the count of nested per-exchange "
                    "rows). Use a neutral name (venue/quote-source count) or add "
                    f"'# {NUM_SEMANTICS_MARKER}: <authoritative vendor evidence>': {code}")
            else:
                msg = (
                    "exchange_quote_ts assigned a wall clock — it must carry the Schwab exchange "
                    "quote timestamp (QUOTE_TIME_MILLIS/sec, TRADE_TIME_MILLIS proxy); the "
                    "server wall clock is the separate server_received_ts. Fix the assignment "
                    f"or add '# {EXCHANGE_QUOTE_TS_MARKER}: <why this is the exchange quote clock>': {code}")
            out.append((rel, ln, msg))
    return out


def main(argv: list[str]) -> int:
    total = violations()
    if not total:
        print("schwab market-field semantics: CLEAN — NUM_* carries no order-count overclaim "
              "and exchange_quote_ts is never assigned a server wall clock.")
        return 0
    print(f"schwab market-field semantics: {len(total)} overclaim(s):")
    for (rel, ln, msg) in total:
        print(f"  {rel}:{ln}  {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
