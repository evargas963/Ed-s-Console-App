"""Executable Lane-A legacy differential (packaged evidence, independently runnable).

Usage (from the repository root, on clean base + Lane-A patch):
    python reports/scoreboard_forensic/legacy_differential/compare_legacy_differential.py <base_sha>

Method:
  1. Build the canonical test fixture (tests.test_calibration_daily_scoreboard._fixture_db)
     in a temp dir. SQLite FILE bytes are not deterministic across creations, so the
     fixture identity is the sha256 of the deterministic ROW-CONTENT dump (sorted SQL rows),
     not the file bytes.
  2. Extract the BASE implementation via `git show <base_sha>:calibration/daily_scoreboard.py`.
  3. Run both implementations with run_backfill=False, restrict to the explicit
     LEGACY_FIELD_ALLOWLIST, flatten to leaf fields, and compare:
       - every numeric leaf (LEGACY_NUMERIC_SUBSET_IDENTITY)
       - every leaf of any type (LEGACY_FIELD_VALUE_IDENTITY)
  4. Write legacy_differential_result.json beside this program and exit 0 only if
     both identities hold.

Schema-v4-only fields are NEVER part of a legacy claim (allowlist below).
LEGACY_COMPLETE_JSON_BYTE_IDENTITY and LEGACY_COMPLETE_OUTPUT_BYTE_IDENTITY remain
NOT_PROVEN under the declared compatibility boundary (schema v4 adds keys; the
HTML semantics are the Lane-A fix).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

LEGACY_FIELD_ALLOWLIST = [
    "et_date", "tickers_filter", "backfill_stats", "by_horizon", "by_ticker",
    "by_horizon_aggregation", "by_horizon_equal_weight", "eligible_grid",
    "coverage", "quality_circle",
]
# db_path is excluded: it embeds the ephemeral temp path (environment detail, not a metric).


def fixture_content_sha(db_path: Path) -> str:
    """Deterministic fixture identity: sorted SQL row dump with volatile
    wall-clock values masked (the schema's created_at DEFAULT datetime('now')
    is insertion time, not fixture content — it never feeds the scoreboard)."""
    import re

    conn = sqlite3.connect(db_path)
    dump = "\n".join(sorted(conn.iterdump()))
    conn.close()
    dump = re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", "<CREATED_AT>", dump)
    return hashlib.sha256(dump.encode()).hexdigest()


def flatten(d, pre=""):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flatten(v, f"{pre}.{k}"))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            out.update(flatten(v, f"{pre}[{i}]"))
    else:
        out[pre] = d
    return out


def main() -> int:
    base_sha = sys.argv[1]
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tests"))
    from test_calibration_daily_scoreboard import ET_DATE, _fixture_db

    import calibration.daily_scoreboard as new_ds

    tmp = Path(tempfile.mkdtemp(prefix="legacy_diff_"))
    db = _fixture_db(tmp)
    fx_sha = fixture_content_sha(db)

    old_src = subprocess.run(
        ["git", "show", f"{base_sha}:calibration/daily_scoreboard.py"],
        capture_output=True, text=True, cwd=root, check=True,
    ).stdout
    old_path = tmp / "old_daily_scoreboard.py"
    old_path.write_text(old_src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("old_ds_pkg", old_path)
    old_ds = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old_ds)

    old_sb = old_ds.build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    new_sb = new_ds.build_daily_scoreboard(db, ET_DATE, run_backfill=False)
    o = flatten({k: old_sb[k] for k in LEGACY_FIELD_ALLOWLIST})
    n = flatten({k: new_sb[k] for k in LEGACY_FIELD_ALLOWLIST})
    all_fields = sorted(set(o) | set(n))
    numeric_fields = sorted(
        k for k in all_fields
        if isinstance(o.get(k), (int, float)) and not isinstance(o.get(k), bool)
    )
    numeric_mismatch = [k for k in numeric_fields if o.get(k) != n.get(k)]
    field_mismatch = [k for k in all_fields if o.get(k) != n.get(k)]
    result = {
        "schema": "LANE_A_LEGACY_DIFFERENTIAL_RESULT",
        "base_sha": base_sha,
        "fixture_content_sha256": fx_sha,
        "old_source_sha256": hashlib.sha256(old_src.encode()).hexdigest(),
        "new_source_sha256": hashlib.sha256(
            (root / "calibration/daily_scoreboard.py").read_bytes()
        ).hexdigest(),
        "comparison_program_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "field_allowlist": LEGACY_FIELD_ALLOWLIST,
        "numeric_fields_compared": len(numeric_fields),
        "numeric_mismatches": numeric_mismatch,
        "all_fields_compared": len(all_fields),
        "field_value_mismatches": field_mismatch,
        "legacy_subset_json_sha256_old": hashlib.sha256(
            json.dumps({k: old_sb[k] for k in LEGACY_FIELD_ALLOWLIST}, sort_keys=True).encode()
        ).hexdigest(),
        "legacy_subset_json_sha256_new": hashlib.sha256(
            json.dumps({k: new_sb[k] for k in LEGACY_FIELD_ALLOWLIST}, sort_keys=True).encode()
        ).hexdigest(),
        "LEGACY_NUMERIC_SUBSET_IDENTITY": "PROVEN" if not numeric_mismatch else "NOT_PROVEN",
        "LEGACY_FIELD_VALUE_IDENTITY": "PROVEN" if not field_mismatch else "NOT_PROVEN",
        "LEGACY_COMPLETE_JSON_BYTE_IDENTITY": "NOT_PROVEN (schema v4 intentionally adds keys)",
        "LEGACY_COMPLETE_OUTPUT_BYTE_IDENTITY": "NOT_PROVEN (HTML semantics are the Lane-A fix)",
    }
    out = Path(__file__).resolve().parent / "legacy_differential_result.json"
    # RC-397: pin the terminator. `write_text` opens with newline=None, which translates
    # "\n" to os.linesep — so this writer emitted CRLF on Windows and LF on Linux for the
    # SAME content, and the tracked blob's style then depended on who last ran it. That is
    # the RC-382 class (a writer nobody owned), and it surfaced as an eol_style_invariant
    # violation on the required Linux runner for a file the change never touched. Writing
    # BYTES takes the platform out of the decision entirely.
    out.write_bytes(json.dumps(result, indent=1).encode("utf-8"))
    print(json.dumps({k: result[k] for k in (
        "fixture_content_sha256", "numeric_fields_compared", "all_fields_compared",
        "LEGACY_NUMERIC_SUBSET_IDENTITY", "LEGACY_FIELD_VALUE_IDENTITY")}, indent=1))
    return 0 if (not numeric_mismatch and not field_mismatch) else 1


if __name__ == "__main__":
    raise SystemExit(main())
