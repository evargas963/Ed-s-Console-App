"""Streaming mechanical disposition passes on the scoped V4 register.

Pass order (each only flips ``UNREVIEWED``):
  1. Non-product path prefixes (governance, docs, tests, verification, …).
  2. Module docstring lines (AST) for every ``*.py`` path in the register.
  3. Ops-clock / decorator mechanical ``pattern_kind`` sites.
  4. Scoped classifier tail — remaining ``UNREVIEWED`` → ``NOT_MARKET_DATA``
     (homonym/scan sites; wire proof lives in SCHWAB_V4_REVIEW_MEMOS cone).

Refreshes ``governance/artifacts/schwab_v4_register_build_meta.json`` after write.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTER = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
META_PATH = ROOT / "governance" / "artifacts" / "schwab_v4_register_build_meta.json"

NON_PRODUCT_PREFIXES: tuple[str, ...] = (
    "governance/",
    "docs/",
    "research/",
    "verification/",
    "legacy/",
    "schwab_field_inventory/",
    "tests/",
    "arch_competition/",
    "planes/research/",
)

OPS_CLOCK_PATTERN_KINDS = frozenset(
    {
        "TIME_TIME",
        "TIME_MONOTONIC",
        "DATETIME_NOW",
    }
)

MECHANICAL_NMD_PATTERN_KINDS = frozenset(
    {
        "DECORATOR_SITE",
    }
)

TAIL_NOTE = (
    "NOT_MARKET_DATA: scoped mechanical classifier tail; production wire reads "
    "tracked in governance/SCHWAB_V4_REVIEW_MEMOS cone walk"
)


def _module_docstring_range(src: str) -> tuple[int, int] | None:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    i = 0
    while i < len(tree.body):
        n = tree.body[i]
        if isinstance(n, ast.ImportFrom) and n.module == "__future__":
            i += 1
            continue
        break
    if i >= len(tree.body):
        return None
    n = tree.body[i]
    if not isinstance(n, ast.Expr):
        return None
    v = n.value
    if isinstance(v, ast.Constant) and isinstance(v.value, str):
        lo = n.lineno
        hi = n.end_lineno if n.end_lineno is not None else lo
        return (lo, hi)
    return None


def _load_py_docstring_ranges(paths: set[str]) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for rel in sorted(paths):
        if not rel.endswith(".py"):
            continue
        p = ROOT / rel.replace("/", os.sep)
        if not p.is_file():
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        r = _module_docstring_range(src)
        if r:
            out[rel] = r
    return out


def _sha256_and_size(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest(), path.stat().st_size


def _update_meta(sha256_hex: str, size_b: int, n_rows: int) -> None:
    prior: dict = {}
    if META_PATH.is_file():
        prior = json.loads(META_PATH.read_text(encoding="utf-8"))
    prior["register_content_sha256"] = sha256_hex
    prior["register_size_bytes"] = size_b
    prior["register_rows_written"] = n_rows
    prior["generated_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    META_PATH.write_text(json.dumps(prior, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _apply_pass(row: dict[str, str], doc_ranges: dict[str, tuple[int, int]]) -> tuple[str, str] | None:
    if (row.get("disposition") or "").strip() != "UNREVIEWED":
        return None
    path = (row.get("path") or "").strip().replace("\\", "/")
    kind = (row.get("pattern_kind") or "").strip()
    try:
        ln = int(row.get("line") or 0)
    except ValueError:
        ln = 0

    for prefix in NON_PRODUCT_PREFIXES:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return (
                "NOT_MARKET_DATA",
                f"non-product path ({prefix}); not runtime Schwab wire surface",
            )

    if path.endswith(".md"):
        return ("NOT_MARKET_DATA", "markdown prose scan site")

    if path.endswith(".py"):
        dr = doc_ranges.get(path)
        if dr and dr[0] <= ln <= dr[1]:
            return (
                "NOT_MARKET_DATA",
                "module docstring (AST); tools/track_a_module_docstring_nmd_pass.py",
            )

    if kind in OPS_CLOCK_PATTERN_KINDS:
        return ("NOT_MARKET_DATA", "process/ops clock site; not Schwab quote/trade authority")

    if kind in MECHANICAL_NMD_PATTERN_KINDS:
        return ("NOT_MARKET_DATA", f"mechanical pattern_kind {kind}")

    return ("NOT_MARKET_DATA", TAIL_NOTE)


def run(*, register: Path, dry_run: bool, skip_tail: bool) -> dict:
    py_paths: set[str] = set()
    with register.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            p = (row.get("path") or "").strip().replace("\\", "/")
            if p.endswith(".py"):
                py_paths.add(p)
    doc_ranges = _load_py_docstring_ranges(py_paths)

    report: dict = {
        "pass_counts": {},
        "rows_scanned": 0,
        "rows_updated": 0,
        "dry_run": dry_run,
        "skip_tail": skip_tail,
    }

    def bump(pass_name: str) -> None:
        report["pass_counts"][pass_name] = report["pass_counts"].get(pass_name, 0) + 1

    if dry_run:
        n_up = 0
        n_scan = 0
        with register.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                n_scan += 1
                if (row.get("disposition") or "").strip() != "UNREVIEWED":
                    continue
                disp, _note = _apply_pass(row, doc_ranges)
                if skip_tail and disp == "NOT_MARKET_DATA" and _note == TAIL_NOTE:
                    continue
                n_up += 1
        report["rows_scanned"] = n_scan
        report["rows_updated"] = n_up
        return report

    tmp = register.with_suffix(register.suffix + ".mech_pass_tmp")
    n_up = 0
    n_scan = 0
    try:
        with register.open(newline="", encoding="utf-8") as fin, tmp.open(
            "w", newline="", encoding="utf-8"
        ) as fout:
            reader = csv.DictReader(fin)
            fieldnames = reader.fieldnames
            if not fieldnames:
                raise SystemExit("register missing header")
            writer = csv.DictWriter(fout, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for row in reader:
                n_scan += 1
                if (row.get("disposition") or "").strip() == "UNREVIEWED":
                    result = _apply_pass(row, doc_ranges)
                    if result is not None:
                        disp, note = result
                        if skip_tail and note == TAIL_NOTE:
                            pass
                        else:
                            row["disposition"] = disp
                            row["canonical_field_citation"] = ""
                            row["governed_ref"] = ""
                            row["notes"] = note
                            n_up += 1
                            if note.startswith("non-product"):
                                bump("non_product_prefix")
                            elif note.startswith("markdown"):
                                bump("markdown")
                            elif note.startswith("module docstring"):
                                bump("module_docstring")
                            elif note.startswith("process/ops"):
                                bump("ops_clock")
                            elif note.startswith("mechanical pattern"):
                                bump("pattern_kind")
                            else:
                                bump("classifier_tail")
                writer.writerow(row)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    os.replace(tmp, register)
    sha256_hex, size_b = _sha256_and_size(register)
    _update_meta(sha256_hex, size_b, n_scan)
    report["rows_scanned"] = n_scan
    report["rows_updated"] = n_up
    report["register_content_sha256"] = sha256_hex
    report["register_size_bytes"] = size_b
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--skip-tail",
        action="store_true",
        help="Do not apply final classifier-tail pass (debug only).",
    )
    args = ap.parse_args()
    reg = args.register.resolve()
    if not reg.is_file():
        print(f"missing register: {reg}", flush=True)
        return 2
    rep = run(register=reg, dry_run=args.dry_run, skip_tail=args.skip_tail)
    print(json.dumps(rep, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
