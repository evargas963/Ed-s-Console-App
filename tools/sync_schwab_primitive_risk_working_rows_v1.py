#!/usr/bin/env python3
"""
WORKING.csv sync for CSV_PRIMITIVE_RISK_REVIEW residual keys where production already
fail-closed but crosswalk line numbers / code snippets drifted behind refactors.

Usage (from repo root):
    python tools/sync_schwab_primitive_risk_working_rows_v1.py
Then: python tools/classify_schwab_csv_crosswalk.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.classify_schwab_csv_crosswalk import _normalize_black_scholes_tag

WORKING = ROOT / "schwab_field_inventory" / "SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_WORKING.csv"
RESIDUAL = ROOT / "schwab_field_inventory" / "SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_RESIDUAL.csv"

PRIMITIVE_DEFAULT_TAGS = frozenset({"DEFAULT_ZERO_OR", "GET_DEFAULT_ZERO", "DEFAULT_100_OR"})

# (file, legacy_line) -> current 1-based line after refactors (verified against tree).
LINE_OVERRIDES: dict[tuple[str, int], int] = {
    ("db.py", 2827): 2836,
    ("db.py", 2842): 2851,
    ("liquidity_value_engine.py", 61): 95,
    ("liquidity_value_engine.py", 101): 131,
    ("liquidity_value_engine.py", 286): 309,
    ("liquidity_value_engine.py", 312): 335,
    ("liquidity_value_engine.py", 362): 385,
    ("market_context.py", 638): 656,
    ("market_context.py", 682): 700,
    ("market_context.py", 887): 904,
    ("market_data_adapter.py", 109): 143,
    ("math_exposure_core.py", 128): 128,
    ("math_exposure_core.py", 139): 139,
    ("math_exposure_core.py", 140): 140,
    ("math_exposure_core.py", 141): 141,
    ("math_exposure_core.py", 380): 383,
    ("math_exposure_core.py", 381): 384,
    ("math_levels.py", 555): 564,
    ("math_levels.py", 589): 602,
    ("math_levels.py", 590): 603,
    ("math_probabilities.py", 200): 201,
    ("order_flow_engine.py", 473): 489,
    ("order_flow_engine.py", 474): 490,
    ("order_flow_engine.py", 478): 501,
    ("order_flow_engine.py", 479): 502,
    ("order_flow_engine.py", 482): 508,
    ("order_flow_engine.py", 483): 509,
    ("server.py", 1063): 1083,
    ("server.py", 1098): 1119,
    ("server.py", 2648): 2663,
    ("server.py", 2855): 2948,
    ("server.py", 3457): 3587,
    ("server.py", 3459): 3592,
    ("server.py", 6273): 6406,
    ("server.py", 6284): 6417,
    ("features/signal_layer_v1.py", 146): 153,
    ("features/signal_layer_v1.py", 182): 189,
    ("features/signal_layer_v1.py", 352): 359,
    ("tools/ingest_1m_to_staging.py", 89): 91,
    ("v2_decision/a2_option_expression.py", 70): 70,
    ("v2_decision/a2_option_expression.py", 140): 145,
}


def _strip_primitive_default_tags(raw: str) -> str:
    parts = [t for t in (raw or "").split("|") if t and t not in PRIMITIVE_DEFAULT_TAGS]
    return "|".join(sorted(parts))


def _line_at(path: Path, lineno: int) -> str | None:
    if not path.is_file() or lineno < 1:
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    if lineno > len(lines):
        return None
    return lines[lineno - 1]


def main() -> int:
    primitive_keys: set[tuple[str, int]] = set()
    with RESIDUAL.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("classification") != "CSV_PRIMITIVE_RISK_REVIEW":
                continue
            fp = row["file"]
            if fp.startswith(".claude/"):
                continue
            primitive_keys.add((fp, int(row["line"])))

    with WORKING.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    n = 0
    for row in rows:
        fp = row["file"]
        if fp.startswith(".claude/"):
            continue
        try:
            ln = int(row["line"])
        except ValueError:
            continue
        key = (fp, ln)
        if key not in primitive_keys:
            continue

        new_ln = LINE_OVERRIDES.get(key, ln)
        src_path = ROOT / fp
        cur = _line_at(src_path, new_ln)
        if cur is None:
            print(f"warn missing line {fp}:{new_ln}", file=sys.stderr)
            continue
        row["line"] = str(new_ln)
        row["code"] = cur
        row["tags"] = _strip_primitive_default_tags(row.get("tags") or "")
        _normalize_black_scholes_tag(row)
        n += 1

    with WORKING.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"synced_working_rows={n} primitive_residual_keys={len(primitive_keys)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
