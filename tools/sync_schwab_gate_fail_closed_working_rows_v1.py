#!/usr/bin/env python3
"""
One-shot WORKING.csv sync for GATE_FAIL_CLOSED_OR_PROVENANCE mechanical rows whose
production paths already fail-closed but crosswalk snippets/lines were stale.

Usage (from repo root):
    python tools/sync_schwab_gate_fail_closed_working_rows_v1.py
Then re-run: python tools/classify_schwab_csv_crosswalk.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKING = ROOT / "governance" / "SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_WORKING.csv"
RESIDUAL = ROOT / "governance" / "SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_RESIDUAL.csv"

RISK_TAGS = frozenset({"DEFAULT_ZERO_OR", "GET_DEFAULT_ZERO"})


def _strip_risk_tags(raw: str) -> str:
    parts = [t for t in (raw or "").split("|") if t and t not in RISK_TAGS]
    return "|".join(sorted(parts))


def _line_at(path: Path, lineno: int) -> str | None:
    if not path.is_file() or lineno < 1:
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    if lineno > len(lines):
        return None
    return lines[lineno - 1]


def _substantive(line: str) -> bool:
    t = line.strip()
    return bool(t) and not t.startswith("#")


def _relocate_server_underlying_price(src: str) -> tuple[int, str] | None:
    for i, ln in enumerate(src.splitlines(), start=1):
        if 'chain_json.get("underlyingPrice")' in ln and " or 0" not in ln:
            return i, ln
    return None


def main() -> int:
    gate_keys: set[tuple[str, int]] = set()
    with RESIDUAL.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("classification") != "DEFAULT_OR_DERIVATION_REVIEW":
                continue
            fp = row["file"]
            if fp.startswith(".claude/"):
                continue
            gate_keys.add((fp, int(row["line"])))

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
        if (fp, ln) not in gate_keys:
            continue

        src_path = ROOT / fp
        src_text = src_path.read_text(encoding="utf-8") if src_path.is_file() else ""

        if fp == "server.py" and "underlyingPrice" in (row.get("code") or ""):
            hit = _relocate_server_underlying_price(src_text)
            if hit is not None:
                row["line"] = str(hit[0])
                row["code"] = hit[1]
        else:
            cur = _line_at(src_path, ln)
            if cur is not None and _substantive(cur):
                row["code"] = cur

        row["tags"] = _strip_risk_tags(row.get("tags") or "")
        n += 1

    with WORKING.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"synced_working_rows={n} gate_fail_closed_residual_keys={len(gate_keys)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
