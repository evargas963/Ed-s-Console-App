"""One conservative streaming pass: Track A *.py module docstring lines → NOT_MARKET_DATA.

Only flips rows when **all** hold:
- ``path`` is one of the seven Track A roots (basename match).
- Current ``disposition`` is ``UNREVIEWED``.
- File parses with ``ast``; line lies in the module docstring's inclusive
  ``lineno``..``end_lineno`` (skipping leading ``from __future__`` imports).

Does **not** touch ``REPLACED`` or any other disposition. Intended for rows we
can be structurally certain are prose, not executable market access.

After rewriting the register, recomputes SHA-256/size and refreshes
``governance/artifacts/schwab_v4_register_build_meta.json`` (same pattern as
``stream_revert_v4_register_and_sync_perf.py``).
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

TRACK_A_BASENAMES = frozenset(
    {
        "server.py",
        "market_state.py",
        "market_data_adapter.py",
        "signals.py",
        "order_flow_engine.py",
        "live_market_plane.py",
        "prediction_engine.py",
    }
)

NOTE = "NOT_MARKET_DATA: module docstring (AST); tools/track_a_module_docstring_nmd_pass.py"


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


def _load_docstring_ranges() -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for name in sorted(TRACK_A_BASENAMES):
        p = ROOT / name
        if not p.is_file():
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        r = _module_docstring_range(src)
        if r:
            out[name] = r
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


def run(*, register: Path, dry_run: bool) -> dict:
    ranges = _load_docstring_ranges()
    report: dict = {
        "track_a_files_with_docstring": {k: {"lo": v[0], "hi": v[1]} for k, v in ranges.items()},
        "rows_updated": 0,
        "rows_scanned": 0,
        "dry_run": dry_run,
    }
    if dry_run:
        # count only
        n_up = 0
        n_scan = 0
        with register.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                n_scan += 1
                path = (row.get("path") or "").strip()
                if Path(path).name not in TRACK_A_BASENAMES:
                    continue
                if (row.get("disposition") or "").strip() != "UNREVIEWED":
                    continue
                try:
                    ln = int(row.get("line") or 0)
                except ValueError:
                    continue
                base = Path(path).name
                dr = ranges.get(base)
                if dr and dr[0] <= ln <= dr[1]:
                    n_up += 1
        report["rows_scanned"] = n_scan
        report["rows_updated"] = n_up
        return report

    tmp = register.with_suffix(register.suffix + ".nmd_pass_tmp")
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
                path = (row.get("path") or "").strip()
                base = Path(path).name
                if (
                    base in TRACK_A_BASENAMES
                    and (row.get("disposition") or "").strip() == "UNREVIEWED"
                ):
                    dr = ranges.get(base)
                    if dr:
                        try:
                            ln = int(row.get("line") or 0)
                        except ValueError:
                            ln = 0
                        if dr[0] <= ln <= dr[1]:
                            row["disposition"] = "NOT_MARKET_DATA"
                            row["canonical_field_citation"] = ""
                            row["governed_ref"] = ""
                            row["notes"] = NOTE
                            n_up += 1
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
    args = ap.parse_args()
    reg = args.register.resolve()
    if not reg.is_file():
        print(f"missing register: {reg}", flush=True)
        return 2
    rep = run(register=reg, dry_run=args.dry_run)
    print(json.dumps(rep, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
