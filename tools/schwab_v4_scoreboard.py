"""V4 gatekeeper scoreboard — P (perf-proofed replacements) + Δ unreviewed + D17 metrics."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from tools.schwab_coverage_v4_metrics import compute_full_metrics, DEFAULT_OPERATOR, DEFAULT_REGISTER

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PERF_DIR = ROOT / "governance" / "artifacts" / "perf_proof" / "replacements"
DEFAULT_OUT = ROOT / "governance" / "artifacts" / "schwab_v4_scoreboard.json"
DEFAULT_REGISTER_META = ROOT / "governance" / "artifacts" / "schwab_v4_register_build_meta.json"


def _count_perf_proofs(repl_dir: Path) -> tuple[int, list[str]]:
    """Return (P, errors)."""
    sys.path.insert(0, str(ROOT))
    from tests.perf_proof.validate import load_and_validate

    p = 0
    errors: list[str] = []
    if not repl_dir.is_dir():
        return 0, [f"missing perf proof dir: {repl_dir}"]
    for f in sorted(repl_dir.glob("pp_*.json")):
        _doc, errs = load_and_validate(f)
        if errs:
            errors.append(f"{f.name}: {errs}")
        else:
            p += 1
    return p, errors


def build_scoreboard(
    *,
    register: Path,
    operator_register: Path,
    perf_dir: Path,
    out_path: Path,
    register_meta: Path | None = None,
    use_register_meta: bool = True,
    update_perf_index: bool = True,
    gatekeeper_overlay: dict | None = None,
) -> dict:
    prior_unreviewed: int | None = None
    if out_path.is_file():
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            prior_unreviewed = int(prev["d17"]["unreviewed_count"])
        except (KeyError, OSError, json.JSONDecodeError, TypeError, ValueError):
            prior_unreviewed = None

    d17 = compute_full_metrics(register, operator_register)
    unreviewed_now = int(d17["unreviewed_count"])
    delta = None if prior_unreviewed is None else unreviewed_now - prior_unreviewed

    P, p_errs = _count_perf_proofs(perf_dir)
    if p_errs:
        raise ValueError("perf_proof validation failed:\n" + "\n".join(p_errs))

    meta: dict | None = None
    if use_register_meta:
        mp = register_meta or DEFAULT_REGISTER_META
        if mp.is_file():
            meta = json.loads(mp.read_text(encoding="utf-8"))

    doc = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scoreboard": {
            "P": P,
            "unreviewed_count": unreviewed_now,
            "prior_unreviewed_count": prior_unreviewed,
            "delta_unreviewed_count": delta,
            "replaced_count_d17": int(d17["replaced_count"]),
        },
        "d17": d17,
        "perf_proof_dir": str(perf_dir.resolve()),
    }
    if meta is not None:
        doc["register_build"] = meta
    if gatekeeper_overlay:
        gk = dict(gatekeeper_overlay)
        if gk.get("status") == "upper_bound_only":
            gk["fields_identified_total_register_rows"] = unreviewed_now
        doc["gatekeeper"] = gk
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if update_perf_index:
        idx = {
            "schema_version": "1.0",
            "P_count": P,
            "perf_proof_files": sorted(p.name for p in perf_dir.glob("pp_*.json")),
            "updated_at_utc": doc["generated_at_utc"],
        }
        (perf_dir.parent / "index.json").write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    ap.add_argument("--operator-register", type=Path, default=DEFAULT_OPERATOR)
    ap.add_argument("--perf-dir", type=Path, default=DEFAULT_PERF_DIR)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--register-meta",
        type=Path,
        default=DEFAULT_REGISTER_META,
        help="JSON merged into scoreboard as register_build (partial-scan provenance).",
    )
    ap.add_argument(
        "--no-register-meta",
        action="store_true",
        help="Do not merge schwab_v4_register_build_meta.json (use for ad-hoc register paths).",
    )
    ap.add_argument(
        "--no-update-perf-index",
        action="store_true",
        help="Do not rewrite governance/artifacts/perf_proof/index.json.",
    )
    ap.add_argument(
        "--mock-upper-bound",
        action="store_true",
        help="Tag artifact as informational upper bound (mock embeddings OK; not V4 baseline).",
    )
    args = ap.parse_args(argv)
    overlay: dict | None = None
    if args.mock_upper_bound:
        overlay = {
            "status": "upper_bound_only",
            "mock_embeddings": True,
            "scanner_scope_independent_of_inventory": True,
            "committed_v4_register_note": "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv at commit a150291 remains authoritative until Gates I–IV close.",
            "scanner_files_attempted_reference": 9022,
            "inventory_pending_reference": 3966,
            "scope_mismatch_files_approx": 5056,
            "mock_build_on_disk_gb_approx": 10.06,
            "reconciliation_doc": "governance/SCHWAB_V4_SCANNER_VS_INVENTORY_SCOPE.md",
        }
    try:
        doc = build_scoreboard(
            register=args.register,
            operator_register=args.operator_register,
            perf_dir=args.perf_dir,
            out_path=args.out,
            register_meta=args.register_meta,
            use_register_meta=not args.no_register_meta,
            update_perf_index=not args.no_update_perf_index,
            gatekeeper_overlay=overlay,
        )
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps(doc["scoreboard"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
