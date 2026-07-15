"""Stream-revert specific V4 register rows, merge register_slices, export baselines, sync perf_proof.

The register CSV may be tens of gigabytes: streaming passes write a temp file,
then atomically replace the original.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.schwab_oxx_validator import perf_proof_basename
DEFAULT_REGISTER = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
DEFAULT_SLICE_DIR = ROOT / "governance" / "register_slices"
PERF_DIR = ROOT / "governance" / "artifacts" / "perf_proof" / "replacements"
META_PATH = ROOT / "governance" / "artifacts" / "schwab_v4_register_build_meta.json"


def is_canonical_v4_register(register: Path) -> bool:
    try:
        return register.resolve() == DEFAULT_REGISTER.resolve()
    except OSError:
        return False


def count_register_rows(register: Path) -> int:
    n = 0
    with register.open(newline="", encoding="utf-8") as f:
        for _ in csv.DictReader(f):
            n += 1
    return n
MERGE_FIELDS = ("disposition", "canonical_field_citation", "governed_ref", "notes", "v2_trace")
_DISPOSITION_RANK = {
    "REPLACED": 5,
    "GOVERNED_EXCEPTION (O-53)": 4,
    "GOVERNED_EXCEPTION (O-50)": 4,
    "GOVERNED_EXCEPTION (O-49)": 4,
    "GOVERNED_EXCEPTION (O-47)": 4,
    "KEEP_DERIVED": 3,
    "PASS_THROUGH": 3,
    "NO_SCHWAB_EQUIVALENT": 3,
    "NOT_MARKET_DATA": 2,
    "UNREVIEWED": 0,
}


def _disp_rank(disp: str) -> int:
    d = (disp or "").strip()
    if d in _DISPOSITION_RANK:
        return _DISPOSITION_RANK[d]
    if d.startswith("GOVERNED_EXCEPTION"):
        return 4
    return 1


def path_line_key(row: dict[str, str]) -> tuple[str, int]:
    return (
        (row.get("path") or "").strip().replace("\\", "/"),
        int(row.get("line") or 0),
    )

COMPOSITE = "pp_v4b_schwab_gate_eleven_test_bundle.json"


def site_key(row: dict[str, str]) -> tuple[str, int, int, str, str]:
    return (
        (row.get("path") or "").strip().replace("\\", "/"),
        int(row.get("line") or 0),
        int(row.get("col") or 0),
        (row.get("pattern_kind") or "").strip(),
        (row.get("language") or "").strip(),
    )


def _parse_baseline_stem(stem: str) -> tuple[str, int, int] | None:
    if stem.startswith("static_index_html_"):
        m = re.match(r"static_index_html_(\d+)_(\d+)$", stem)
        if m:
            return ("static/index.html", int(m.group(1)), int(m.group(2)))
        return None
    m = re.match(r"^server_py_(\d+)_(\d+)$", stem)
    if m:
        return ("server.py", int(m.group(1)), int(m.group(2)))
    m = re.match(r"^(.+)_py_(\d+)_(\d+)$", stem)
    if not m:
        return None
    prefix = m.group(1)
    lo, hi = int(m.group(2)), int(m.group(3))
    if prefix.startswith("features_"):
        rel = "features/" + prefix[len("features_") :] + ".py"
    else:
        rel = prefix + ".py"
    return (rel.replace("//", "/"), lo, hi)


def export_register_baseline(
    register: Path,
    *,
    path: str,
    line_lo: int,
    line_hi: int,
    out: Path,
) -> int:
    from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS

    rows: list[dict[str, str]] = []
    with register.open(newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            if (raw.get("path") or "").strip().replace("\\", "/") != path:
                continue
            line = int(raw.get("line") or 0)
            if line_lo <= line <= line_hi:
                rows.append(dict(raw))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def _path_from_root_line(prefix: str, text: str) -> str | None:
    m = re.search(rf"^{prefix} = (.+)$", text, re.M)
    if not m:
        return None
    parts = re.findall(r'"([^"]+)"', m.group(1))
    return "/".join(parts) if parts else None


def _parse_builder_spec(builder: Path) -> dict[str, str | int] | None:
    text = builder.read_text(encoding="utf-8", errors="replace")
    spec: dict[str, str | int] = {"builder": builder.name}
    m_path = re.search(r'^PATH = "([^"]+)"', text, re.M)
    m_lo = re.search(r"^LO, HI = (\d+), (\d+)", text, re.M)
    baseline_rel = _path_from_root_line("BASELINE", text)
    slice_rel = _path_from_root_line("SLICE", text)
    if m_path:
        spec["path"] = m_path.group(1)
    if m_lo:
        spec["line_lo"] = int(m_lo.group(1))
        spec["line_hi"] = int(m_lo.group(2))
    if baseline_rel:
        spec["baseline_rel"] = baseline_rel
    elif slice_rel:
        stem = Path(slice_rel).stem
        spec["baseline_rel"] = str(Path(slice_rel).parent / f"{stem}_scanner_baseline.csv")
    if "path" not in spec and spec.get("baseline_rel"):
        stem = Path(str(spec["baseline_rel"])).name.replace("_scanner_baseline.csv", "").replace(
            "_baseline.csv", ""
        )
        parsed = _parse_baseline_stem(stem)
        if parsed:
            spec["path"], spec["line_lo"], spec["line_hi"] = parsed[0], parsed[1], parsed[2]
    if "path" not in spec or "line_lo" not in spec or "baseline_rel" not in spec:
        return None
    return spec


def refresh_slice_baselines(register: Path, *, dry_run: bool) -> list[dict]:
    reports: list[dict] = []
    for builder in sorted((ROOT / "tools").glob("_build_*_register_slice.py")):
        spec = _parse_builder_spec(builder)
        if spec is None:
            reports.append({"builder": builder.name, "skipped": "no PATH/LO/HI/BASELINE"})
            continue
        out = ROOT / str(spec["baseline_rel"])
        if dry_run:
            reports.append(
                {
                    "builder": builder.name,
                    "would_export": str(out),
                    "path": spec["path"],
                    "line_lo": spec["line_lo"],
                    "line_hi": spec["line_hi"],
                }
            )
            continue
        n = export_register_baseline(
            register,
            path=str(spec["path"]),
            line_lo=int(spec["line_lo"]),
            line_hi=int(spec["line_hi"]),
            out=out,
        )
        reports.append({"builder": builder.name, "baseline": str(out), "rows": n})
    return reports


def run_slice_builders(*, dry_run: bool) -> list[dict]:
    reports: list[dict] = []
    for builder in sorted((ROOT / "tools").glob("_build_*_register_slice.py")):
        if dry_run:
            reports.append({"builder": builder.name, "would_run": True})
            continue
        proc = subprocess.run(
            [sys.executable, str(builder)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        reports.append(
            {
                "builder": builder.name,
                "returncode": proc.returncode,
                "stdout_tail": (proc.stdout or "")[-500:],
                "stderr_tail": (proc.stderr or "")[-500:],
            }
        )
    return reports


def load_slice_disposition_maps(slice_dir: Path) -> tuple[
    dict[tuple[str, int, int, str, str], list[dict[str, str]]],
    dict[str, list[dict[str, str]]],
    dict[tuple[str, int], dict[str, str]],
]:
    """by_site / by_id hold EVERY claimant row for an identity (identities can
    legitimately collide across slice generations after sites shift and rows are
    rekeyed); the content-bound resolver picks the claimant whose reviewed
    surface_form matches the current code, so a stale claimant can never shadow
    a rekeyed one by file-load order."""
    by_site: dict[tuple[str, int, int, str, str], list[dict[str, str]]] = {}
    by_id: dict[str, list[dict[str, str]]] = {}
    by_path_line: dict[tuple[str, int], dict[str, str]] = {}
    if not slice_dir.is_dir():
        return by_site, by_id, by_path_line
    for path in sorted(slice_dir.glob("*.csv")):
        name = path.name
        if "baseline" in name:
            continue
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                disp = (row.get("disposition") or "").strip()
                if not disp or disp == "UNREVIEWED":
                    continue
                by_site.setdefault(site_key(row), []).append(row)
                rid = (row.get("register_id") or "").strip()
                if rid:
                    by_id.setdefault(rid, []).append(row)
                # register_id rows merge exactly via by_id / by_site; path+line would
                # collateral-disposition co-located wire/BINOP rows on mixed lines.
                if rid:
                    continue
                pl = path_line_key(row)
                prev = by_path_line.get(pl)
                if prev is None or _disp_rank(disp) >= _disp_rank(prev.get("disposition") or ""):
                    by_path_line[pl] = row
    return by_site, by_id, by_path_line


def _apply_slice_to_row(row: dict[str, str], slice_row: dict[str, str]) -> None:
    for field in MERGE_FIELDS:
        if field in slice_row and (slice_row.get(field) or "").strip():
            row[field] = slice_row[field]


def line_scope_production_merge_blocked(
    slice_row: dict[str, str],
    *,
    slice_basename: str = "",
) -> tuple[bool, str | None]:
    """True when automated LINE_SCOPE must not run in production merge (Policy A + scratch-only)."""
    from tools.d17_rekey_register_slices import line_scope_automation_eligible
    from tools.schwab_universal_coverage_scanner_v3.register import classify_disposition_scope

    scope = classify_disposition_scope(slice_row, slice_basename=slice_basename)
    ok, reason = line_scope_automation_eligible(slice_row, scope, production=True)
    if not ok:
        return True, reason
    return False, None


def resolve_slice_row_prototype(
    row: dict[str, str],
    by_id: dict[str, list[dict[str, str]]],
    by_site: dict[tuple[str, int, int, str, str], list[dict[str, str]]],
    by_stable_key: dict[str, dict[str, str]],
) -> tuple[dict[str, str] | None, str]:
    """Prototype resolver: register_id -> site_key -> stable_semantic_key (never
    path+line-only); content-bound like production so a stale claimant is never
    reported as the match for code it did not review."""
    rid = (row.get("register_id") or "").strip()
    if rid and rid in by_id:
        src = _surface_bound(row, by_id[rid])
        if src is not None:
            return src, "register_id"
    sk = site_key(row)
    if sk in by_site:
        src = _surface_bound(row, by_site[sk])
        if src is not None:
            return src, "site_key"
    ssk = (row.get("_stable_semantic_key") or "").strip()
    if ssk and ssk in by_stable_key:
        return by_stable_key[ssk], "stable_semantic_key"
    return None, "none"


def _surface_bound(row: dict[str, str], srcs: list[dict[str, str]]) -> dict[str, str] | None:
    """CONTENT BINDING (2026-07-15 root cause): register_id and site_key both hash
    coordinates (path|line|col|kind|language), never content — after source files
    shift, DIFFERENT code can occupy reviewed coordinates and silently inherit the
    reviewed disposition (observed at scale: 4,903 register rows carried slice
    dispositions whose reviewed surface_form no longer matched the code, including
    a bidPrice read classified NOT_MARKET_DATA). A slice disposition therefore
    applies ONLY when the reviewed surface_form byte-equals the current row's
    surface_form; content-matching claimants with CONFLICTING dispositions fail
    closed to UNREVIEWED."""
    sf = (row.get("surface_form") or "").strip()
    matching = [s for s in srcs if (s.get("surface_form") or "").strip() == sf]
    if not matching:
        return None
    disps = {(s.get("disposition") or "").strip() for s in matching}
    if len(disps) != 1:
        return None
    return matching[0]


def _resolve_slice_row(
    row: dict[str, str],
    by_id: dict[str, list[dict[str, str]]],
    by_site: dict[tuple[str, int, int, str, str], list[dict[str, str]]],
    by_path_line: dict[tuple[str, int], dict[str, str]],
) -> dict[str, str] | None:
    rid = (row.get("register_id") or "").strip()
    if rid and rid in by_id:
        src = _surface_bound(row, by_id[rid])
        if src is not None:
            return src
    sk = site_key(row)
    if sk in by_site:
        src = _surface_bound(row, by_site[sk])
        if src is not None:
            return src
    src = by_path_line.get(path_line_key(row))
    if src is not None:
        return _surface_bound(row, [src])
    return None


def merge_register_slices(
    register: Path,
    slice_dir: Path,
    *,
    dry_run: bool,
) -> dict:
    by_site, by_id, by_path_line = load_slice_disposition_maps(slice_dir)
    report = {
        "slice_files": len(list(slice_dir.glob("*.csv"))),
        "slice_dispositions": len(by_site),
        "slice_path_line_dispositions": len(by_path_line),
        "rows_scanned": 0,
        "rows_updated": 0,
        "dry_run": dry_run,
    }
    if dry_run:
        n_up = 0
        n_scan = 0
        with register.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                n_scan += 1
                if _resolve_slice_row(row, by_id, by_site, by_path_line) is not None:
                    n_up += 1
        report["rows_scanned"] = n_scan
        report["rows_updated"] = n_up
        return report

    tmp = register.with_suffix(register.suffix + ".slice_merge_tmp")
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
                src = _resolve_slice_row(row, by_id, by_site, by_path_line)
                if src is not None:
                    _apply_slice_to_row(row, src)
                    n_up += 1
                writer.writerow(row)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    os.replace(tmp, register)
    sha256_hex, size_b = _sha256_and_size(register)
    update_register_meta_if_canonical(register, sha256_hex, size_b, n_scan)
    report["rows_scanned"] = n_scan
    report["rows_updated"] = n_up
    report["register_content_sha256"] = sha256_hex
    report["register_size_bytes"] = size_b
    return report


def _collect_replaced_by_proof(register_path: Path) -> tuple[int, dict[str, list[str]]]:
    """Stream register once; group REPLACED register_ids by perf_proof basename."""
    replaced_by_proof: dict[str, list[str]] = defaultdict(list)
    n_rows = 0
    with register_path.open(newline="", encoding="utf-8") as fin:
        reader = csv.DictReader(fin)
        if not reader.fieldnames:
            raise SystemExit("register CSV missing header")
        for row in reader:
            n_rows += 1
            disp = (row.get("disposition") or "").strip()
            if disp != "REPLACED":
                continue
            proof = perf_proof_basename(row.get("governed_ref") or "")
            if proof:
                replaced_by_proof[proof].append((row.get("register_id") or "").strip())
    for k in list(replaced_by_proof.keys()):
        replaced_by_proof[k] = sorted({x for x in replaced_by_proof[k] if x})
    return n_rows, dict(replaced_by_proof)


def _write_perf_json(by_proof: dict[str, list[str]]) -> None:
    touched: set[str] = set()
    for proof_name, ids in sorted(by_proof.items()):
        path = PERF_DIR / proof_name
        if not path.is_file():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        rl = doc.setdefault("register_link", {})
        rl["status"] = "bound"
        rl["replaced_register_ids"] = sorted(set(ids))
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        touched.add(proof_name)

    for path in sorted(PERF_DIR.glob("pp_*.json")):
        if path.name == COMPOSITE or path.name in touched:
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        rl = doc.get("register_link") or {}
        if not rl.get("replaced_register_ids"):
            continue
        rl["replaced_register_ids"] = []
        rl["status"] = "unbound"
        doc["register_link"] = rl
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    gate = PERF_DIR / COMPOSITE
    if gate.is_file():
        union = sorted({rid for ids in by_proof.values() for rid in ids})
        doc = json.loads(gate.read_text(encoding="utf-8"))
        rl = doc.setdefault("register_link", {})
        rl["status"] = "composite_bundle"
        rl["wrapped_proof_ids"] = sorted(by_proof.keys())
        rl["replaced_register_ids"] = union
        gate.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _stream_patch_and_collect(
    register_path: Path,
    tmp_path: Path,
    revert_ids: set[str],
) -> tuple[int, int, dict[str, list[str]]]:
    """Return (n_rows, n_reverted, replaced_ids_by_proof_json_name)."""
    replaced_by_proof: dict[str, list[str]] = defaultdict(list)
    n_rows = 0
    n_reverted = 0
    with register_path.open(newline="", encoding="utf-8") as fin, tmp_path.open(
        "w", newline="", encoding="utf-8"
    ) as fout:
        reader = csv.DictReader(fin)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise SystemExit("register CSV missing header")
        writer = csv.DictWriter(fout, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in reader:
            n_rows += 1
            rid = (row.get("register_id") or "").strip()
            if rid in revert_ids:
                row["disposition"] = "UNREVIEWED"
                row["canonical_field_citation"] = ""
                row["governed_ref"] = ""
                n_reverted += 1
            disp = (row.get("disposition") or "").strip()
            if disp == "REPLACED":
                proof = perf_proof_basename(row.get("governed_ref") or "")
                if proof:
                    replaced_by_proof[proof].append(rid)
            writer.writerow(row)
    for k in list(replaced_by_proof.keys()):
        replaced_by_proof[k] = sorted(set(replaced_by_proof[k]))
    return n_rows, n_reverted, dict(replaced_by_proof)


def _sha256_and_size(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest(), path.stat().st_size


def _update_register_meta(sha256_hex: str, size_b: int, n_rows: int) -> None:
    prior: dict = {}
    if META_PATH.is_file():
        prior = json.loads(META_PATH.read_text(encoding="utf-8"))
    prior["register_content_sha256"] = sha256_hex
    prior["register_size_bytes"] = size_b
    prior["register_rows_written"] = n_rows
    prior["generated_at_utc"] = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    META_PATH.write_text(json.dumps(prior, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_register_meta_if_canonical(
    register: Path,
    sha256_hex: str,
    size_b: int,
    n_rows: int,
) -> bool:
    """Write global build meta only when ``register`` is the canonical V4 CSV."""
    if not is_canonical_v4_register(register):
        return False
    _update_register_meta(sha256_hex, size_b, n_rows)
    return True


def refresh_meta_pin_if_stale(register: Path, meta_path: Path | None = None) -> bool:
    """Re-hash canonical register and refresh meta pin when SHA or row count drift."""
    if not register.is_file() or not is_canonical_v4_register(register):
        return False
    sha256_hex, size_b = _sha256_and_size(register)
    n_rows = count_register_rows(register)
    mp = meta_path or META_PATH
    prior: dict = {}
    if mp.is_file():
        try:
            prior = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prior = {}
    if (
        prior.get("register_content_sha256") == sha256_hex
        and int(prior.get("register_rows_written") or -1) == n_rows
        and int(prior.get("register_size_bytes") or -1) == size_b
    ):
        return False
    _update_register_meta(sha256_hex, size_b, n_rows)
    return True


def repin_register_build_meta(register: Path | None = None) -> dict:
    """Force meta pin from canonical register CSV (hash, size, row count)."""
    reg = (register or DEFAULT_REGISTER).resolve()
    if not reg.is_file():
        raise FileNotFoundError(reg)
    if not is_canonical_v4_register(reg):
        raise ValueError(f"refusing to repin meta from non-canonical register: {reg}")
    sha256_hex, size_b = _sha256_and_size(reg)
    n_rows = count_register_rows(reg)
    _update_register_meta(sha256_hex, size_b, n_rows)
    return json.loads(META_PATH.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--merge-slices",
        type=Path,
        nargs="?",
        const=DEFAULT_SLICE_DIR,
        metavar="DIR",
        help="Merge disposition columns from register_slices/*.csv into the register.",
    )
    mode.add_argument(
        "--export-baseline",
        action="store_true",
        help="Export scanner rows for --path/--line-lo/--line-hi to --baseline-out.",
    )
    mode.add_argument(
        "--refresh-slice-baselines",
        action="store_true",
        help="Re-export scanner baselines for all _build_*_register_slice.py specs.",
    )
    mode.add_argument(
        "--run-slice-builders",
        action="store_true",
        help="Run every tools/_build_*_register_slice.py (after baselines refreshed).",
    )
    mode.add_argument(
        "--sync-only",
        action="store_true",
        help="Resync perf_proof register_link arrays from register CSV only (no row reverts).",
    )
    mode.add_argument(
        "--repin-meta",
        action="store_true",
        help="Re-hash canonical register CSV and refresh schwab_v4_register_build_meta.json pin.",
    )
    ap.add_argument("--path", type=str, default="", help="POSIX path filter for --export-baseline.")
    ap.add_argument("--line-lo", type=int, default=0)
    ap.add_argument("--line-hi", type=int, default=0)
    ap.add_argument("--baseline-out", type=Path, default=None)
    ap.add_argument(
        "--revert-ids",
        default="60ca8db4744d7ac5da79,af3f1806c0f22f08f3f5",
        help="Comma-separated register_id values to revert to UNREVIEWED.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions only; do not write register or JSON.",
    )
    args = ap.parse_args()
    reg = args.register.resolve()
    if not reg.is_file():
        print(f"missing register: {reg}", flush=True)
        return 2

    if args.export_baseline:
        if not args.path or not args.baseline_out:
            print("--export-baseline requires --path and --baseline-out", file=sys.stderr)
            return 2
        if args.dry_run:
            print(f"would export {args.path} L{args.line_lo}-L{args.line_hi} -> {args.baseline_out}")
            return 0
        n = export_register_baseline(
            reg,
            path=args.path.replace("\\", "/"),
            line_lo=args.line_lo,
            line_hi=args.line_hi,
            out=args.baseline_out.resolve(),
        )
        print(json.dumps({"rows_exported": n, "out": str(args.baseline_out)}, indent=2))
        return 0

    if args.repin_meta:
        if args.dry_run:
            print(f"would repin meta from {reg}", flush=True)
            return 0
        doc = repin_register_build_meta(reg)
        print(
            json.dumps(
                {
                    "repin_meta": True,
                    "register_content_sha256": doc.get("register_content_sha256"),
                    "register_rows_written": doc.get("register_rows_written"),
                    "register_size_bytes": doc.get("register_size_bytes"),
                },
                indent=2,
            ),
            flush=True,
        )
        return 0

    if args.refresh_slice_baselines:
        rep = refresh_slice_baselines(reg, dry_run=args.dry_run)
        print(json.dumps(rep, indent=2))
        return 0

    if args.run_slice_builders:
        rep = run_slice_builders(dry_run=args.dry_run)
        failed = [r for r in rep if r.get("returncode", 0) != 0]
        print(json.dumps(rep, indent=2))
        return 1 if failed and not args.dry_run else 0

    if args.merge_slices is not None:
        rep = merge_register_slices(reg, args.merge_slices.resolve(), dry_run=args.dry_run)
        print(json.dumps(rep, indent=2))
        return 0

    revert_ids = {x.strip() for x in args.revert_ids.split(",") if x.strip()}

    if args.sync_only:
        if args.dry_run:
            print(f"would sync perf_proof links from {reg}", flush=True)
            return 0
        n_rows, by_proof = _collect_replaced_by_proof(reg)
        _write_perf_json(by_proof)
        sha256_hex, size_b = _sha256_and_size(reg)
        update_register_meta_if_canonical(reg, sha256_hex, size_b, n_rows)
        union = sorted({rid for ids in by_proof.values() for rid in ids})
        print(
            json.dumps(
                {
                    "sync_only": True,
                    "n_rows": n_rows,
                    "replaced_by_proof": by_proof,
                    "replaced_union_count": len(union),
                    "register_content_sha256": sha256_hex,
                    "register_size_bytes": size_b,
                },
                indent=2,
            ),
            flush=True,
        )
        return 0

    tmp = reg.with_suffix(reg.suffix + ".stream_patch_tmp")
    if args.dry_run:
        print(f"would patch {reg} revert_ids={sorted(revert_ids)} tmp={tmp}", flush=True)
        return 0

    n_rows, n_rev, by_proof = _stream_patch_and_collect(reg, tmp, revert_ids)
    if n_rev != len(revert_ids):
        tmp.unlink(missing_ok=True)
        print(
            f"expected {len(revert_ids)} reverts, found {n_rev}; abort without replacing register",
            flush=True,
        )
        return 3

    os.replace(tmp, reg)
    sha256_hex, size_b = _sha256_and_size(reg)
    _write_perf_json(by_proof)
    update_register_meta_if_canonical(reg, sha256_hex, size_b, n_rows)

    print(
        json.dumps(
            {
                "n_rows": n_rows,
                "n_reverted": n_rev,
                "register_content_sha256": sha256_hex,
                "register_size_bytes": size_b,
                "replaced_by_proof": by_proof,
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
