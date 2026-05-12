"""V4 gatekeeper scoreboard — P (perf-proofed replacements) + Δ unreviewed + D17 metrics."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from tools.schwab_coverage_v4_metrics import compute_full_metrics, DEFAULT_OPERATOR, DEFAULT_REGISTER

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PERF_DIR = ROOT / "governance" / "artifacts" / "perf_proof" / "replacements"
DEFAULT_OUT = ROOT / "governance" / "artifacts" / "schwab_v4_scoreboard.json"
DEFAULT_REGISTER_META = ROOT / "governance" / "artifacts" / "schwab_v4_register_build_meta.json"


def load_prior_scoreboard_from_git(
    repo_root: Path,
    scoreboard_out_path: Path,
) -> tuple[dict | None, str | None, str]:
    """Return (prior_doc, head_sha, source) where source is git_head | none.

    Reads ``git show HEAD:<path>`` so repeated local rebuilds without a commit
    still compare Δ against the last committed scoreboard (not the stale
    working-tree copy from the prior rebuild).
    """
    try:
        rel = scoreboard_out_path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return None, None, "none"

    rel_posix = rel.as_posix()
    rev_proc = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if rev_proc.returncode != 0:
        return None, None, "none"
    head_sha = rev_proc.stdout.strip() or None

    show_proc = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"HEAD:{rel_posix}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if show_proc.returncode != 0:
        return None, None, "none"
    try:
        return json.loads(show_proc.stdout), head_sha, "git_head"
    except json.JSONDecodeError:
        return None, head_sha, "none"


def _prior_counts_from_doc(prev: dict | None) -> tuple[int | None, int | None]:
    if not prev:
        return None, None
    prior_u: int | None = None
    prior_r: int | None = None
    try:
        prior_u = int(prev["d17"]["unreviewed_count"])
    except (KeyError, TypeError, ValueError):
        pass
    sb = prev.get("scoreboard")
    if isinstance(sb, dict):
        try:
            prior_r = int(sb.get("replaced_count_d17"))
        except (TypeError, ValueError):
            pass
    if prior_r is None:
        try:
            prior_r = int(prev["d17"]["replaced_count"])
        except (KeyError, TypeError, ValueError):
            pass
    return prior_u, prior_r


def _load_prior_from_working_tree(out_path: Path) -> dict | None:
    if not out_path.is_file():
        return None
    try:
        return json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


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
    repo_root: Path | None = None,
    prior_from_git: bool = True,
) -> dict:
    root = repo_root or ROOT
    prior_doc: dict | None = None
    prior_git_ref: str | None = None
    prior_source = "none"

    if prior_from_git:
        prior_doc, prior_git_ref, prior_source = load_prior_scoreboard_from_git(root, out_path)

    if prior_doc is None:
        prior_doc = _load_prior_from_working_tree(out_path)
        if prior_doc is not None:
            prior_source = "working_tree"
            prior_git_ref = None

    prior_unreviewed, prior_replaced = _prior_counts_from_doc(prior_doc)

    d17 = compute_full_metrics(register, operator_register)
    unreviewed_now = int(d17["unreviewed_count"])
    replaced_now = int(d17["replaced_count"])
    delta_u = None if prior_unreviewed is None else unreviewed_now - prior_unreviewed
    delta_r = None if prior_replaced is None else replaced_now - prior_replaced

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
            "delta_unreviewed_count": delta_u,
            "prior_replaced_count_d17": prior_replaced,
            "delta_replaced_count_d17": delta_r,
            "replaced_count_d17": replaced_now,
            "prior_git_ref": prior_git_ref,
            "prior_scoreboard_source": prior_source,
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
        "--no-prior-git",
        action="store_true",
        help="Use on-disk scoreboard for Δ prior (legacy; misreports when the file was rebuilt twice without commit).",
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
            prior_from_git=not args.no_prior_git,
        )
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps(doc["scoreboard"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
