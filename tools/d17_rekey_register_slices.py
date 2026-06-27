"""D17 — disposition-preserving re-key of register_slices to current register identities.

Maps reviewed slice rows onto current pinned register UNREVIEWED rows using strict
identity matching only. Never uses path+line-only fallback. Defaults to scratch output.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.schwab_oxx_validator import perf_proof_basename
from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS
from tools.stream_revert_v4_register_and_sync_perf import merge_register_slices

DEFAULT_REGISTER = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
DEFAULT_SLICE_DIR = ROOT / "governance" / "register_slices"
DEFAULT_SCRATCH = ROOT / "reports" / "d17_rekey_prototype"
DEFAULT_OUT_SLICES = DEFAULT_SCRATCH / "register_slices_rekeyed"
DEFAULT_SUMMARY_JSON = DEFAULT_SCRATCH / "d17_rekey_summary.json"
DEFAULT_SUMMARY_MD = DEFAULT_SCRATCH / "d17_rekey_summary.md"

MONEY_PATH = {
    "signals.py",
    "call_engine.py",
    "prediction_engine.py",
    "realized_contract_eval.py",
    "bayesian_fusion.py",
    "mc_fusion_adjustment.py",
    "market_state.py",
    "live_decision_bundle.py",
    "features/signal_layer_v1.py",
    "features/inference_snapshot.py",
    "features/fusion_policy_contract.py",
}

DISPOSITION_FIELDS = (
    "disposition",
    "canonical_field_citation",
    "governed_ref",
    "notes",
    "v2_trace",
)
IDENTITY_FROM_REGISTER = (
    "register_id",
    "language",
    "col",
    "surface_form",
    "tokens",
    "csv_candidates",
    "csv_lexical_topk_note",
)
TEXT_IDENTITY_FIELDS = ("surface_form", "tokens")
OXX_IN_DISP = re.compile(r"GOVERNED_EXCEPTION\s*\(\s*(O-\d+)\s*\)", re.IGNORECASE)
OXX_IN_REF = re.compile(r"\b(O-\d+)\b", re.IGNORECASE)


def norm_path(path: str) -> str:
    return (path or "").strip().replace("\\", "/")


def path_line_key(row: dict[str, str]) -> tuple[str, int]:
    return (norm_path(row.get("path")), int(row.get("line") or 0))


def strict_identity_key(row: dict[str, str]) -> tuple[str, int, str, str, str]:
    return (
        norm_path(row.get("path")),
        int(row.get("line") or 0),
        (row.get("pattern_kind") or "").strip(),
        (row.get("surface_form") or "").strip(),
        (row.get("tokens") or "").strip(),
    )


def disposition_bundle(row: dict[str, str]) -> tuple[str, ...]:
    return tuple((row.get(f) or "").strip() for f in DISPOSITION_FIELDS)


def text_identity_admissible(
    slice_row: dict[str, str], reg_row: dict[str, str]
) -> tuple[bool, str]:
    """Require path/line/pattern_kind already matched; validate text identity fields."""
    for fld in TEXT_IDENTITY_FIELDS:
        s_val = (slice_row.get(fld) or "").strip()
        r_val = (reg_row.get(fld) or "").strip()
        if s_val and r_val and s_val != r_val:
            return False, f"{fld}_mismatch"
        if s_val and not r_val:
            return False, f"{fld}_missing_in_register"
        if r_val and not s_val:
            return False, f"{fld}_missing_in_slice"
    slice_text = any((slice_row.get(f) or "").strip() for f in TEXT_IDENTITY_FIELDS)
    reg_text = any((reg_row.get(f) or "").strip() for f in TEXT_IDENTITY_FIELDS)
    if not slice_text:
        return False, "no_text_identity_in_slice"
    if not reg_text:
        return False, "no_text_identity_in_register"
    return True, "ok"


def disposition_proof_admissible(row: dict[str, str]) -> tuple[bool, str]:
    disp = (row.get("disposition") or "").strip()
    if not disp or disp == "UNREVIEWED":
        return False, "unreviewed_slice"
    if disp.startswith("GOVERNED_EXCEPTION"):
        m = OXX_IN_DISP.match(disp)
        ref = (row.get("governed_ref") or "").strip()
        oxx = m.group(1).upper() if m else None
        ref_oxx = OXX_IN_REF.search(ref)
        if not oxx and not ref_oxx:
            return False, "governed_exception_missing_oxx"
        if oxx and ref and not ref.upper().startswith(oxx):
            return False, "governed_ref_oxx_mismatch"
        if not ref and not oxx:
            return False, "governed_exception_missing_ref"
    if disp == "REPLACED":
        if not perf_proof_basename(row.get("governed_ref") or ""):
            return False, "replaced_missing_pp_proof"
    if disp == "PASS_THROUGH":
        cite = (row.get("canonical_field_citation") or "").strip()
        ref = (row.get("governed_ref") or "").strip()
        if not cite and not ref:
            return False, "pass_through_missing_proof_fields"
    return True, "ok"


@dataclass
class RekeyStats:
    slice_rows_scanned: int = 0
    register_unreviewed_scanned: int = 0
    exact_match_candidates: int = 0
    rejected_path_line_only: int = 0
    rejected_no_text_identity: int = 0
    rejected_not_unreviewed_target: int = 0
    rejected_disposition_proof: int = 0
    ambiguous_candidates: int = 0
    conflict_candidates: int = 0
    money_path_candidates: int = 0
    rekeyed_rows: int = 0
    untouched_slice_rows: int = 0
    by_disposition: Counter = field(default_factory=Counter)
    by_path: Counter = field(default_factory=Counter)
    rewritten_files: list[str] = field(default_factory=list)
    untouched_files: list[str] = field(default_factory=list)
    target_register_ids: list[str] = field(default_factory=list)
    rejection_reasons: Counter = field(default_factory=Counter)


def _has_text_identity(row: dict[str, str]) -> bool:
    return any((row.get(f) or "").strip() for f in TEXT_IDENTITY_FIELDS)


def load_unreviewed_register(register: Path) -> tuple[list[dict[str, str]], dict[tuple, list[dict[str, str]]]]:
    rows: list[dict[str, str]] = []
    by_strict: dict[tuple, list[dict[str, str]]] = defaultdict(list)
    with register.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("disposition") or "").strip() != "UNREVIEWED":
                continue
            rows.append(row)
            if _has_text_identity(row):
                by_strict[strict_identity_key(row)].append(row)
    return rows, by_strict


def load_slice_files(slice_dir: Path) -> list[tuple[Path, list[dict[str, str]]]]:
    out: list[tuple[Path, list[dict[str, str]]]] = []
    for path in sorted(slice_dir.glob("*.csv")):
        if "baseline" in path.name:
            continue
        with path.open(newline="", encoding="utf-8") as f:
            out.append((path, list(csv.DictReader(f))))
    return out


def build_path_line_unreviewed_index(
    unreviewed: list[dict[str, str]],
) -> dict[tuple[str, int], list[dict[str, str]]]:
    idx: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    for row in unreviewed:
        idx[path_line_key(row)].append(row)
    return idx


def rekey_row(
    slice_row: dict[str, str],
    target: dict[str, str],
) -> dict[str, str]:
    out = dict(slice_row)
    for fld in IDENTITY_FROM_REGISTER:
        if fld in target:
            out[fld] = target[fld]
    return out


def evaluate_slice_row(
    slice_row: dict[str, str],
    *,
    unreviewed_by_strict: dict[tuple, list[dict[str, str]]],
    path_line_unreviewed: dict[tuple[str, int], list[dict[str, str]]],
    target_claims: dict[str, tuple[str, ...]],
) -> tuple[str, dict[str, str] | None, str]:
    disp = (slice_row.get("disposition") or "").strip()
    if not disp or disp == "UNREVIEWED":
        return "untouched", None, "unreviewed_slice"

    if not _has_text_identity(slice_row):
        pl = path_line_key(slice_row)
        if path_line_unreviewed.get(pl):
            return "rejected_path_line_only", None, "no_text_identity_in_slice"
        return "rejected_no_text", None, "no_text_identity_in_slice"

    ok, reason = disposition_proof_admissible(slice_row)
    if not ok:
        return "rejected", None, reason

    key = strict_identity_key(slice_row)
    pl = path_line_key(slice_row)
    candidates = unreviewed_by_strict.get(key, [])
    if not candidates:
        if path_line_unreviewed.get(pl):
            return "rejected_path_line_only", None, "path_line_only_no_strict_match"
        return "rejected", None, "no_register_candidate"
    if len(candidates) > 1:
        return "ambiguous", None, "multiple_register_candidates"

    target = candidates[0]
    ok, reason = text_identity_admissible(slice_row, target)
    if not ok:
        if reason.startswith("no_text_identity"):
            return "rejected_no_text", None, reason
        if path_line_unreviewed.get(pl):
            return "rejected_path_line_only", None, reason
        return "rejected", None, reason

    rid = (target.get("register_id") or "").strip()
    if not rid:
        return "rejected", None, "missing_target_register_id"

    bundle = disposition_bundle(slice_row)
    prior = target_claims.get(rid)
    if prior is not None and prior != bundle:
        return "conflict", None, "conflicting_dispositions_for_target"

    target_claims[rid] = bundle
    return "rekey", rekey_row(slice_row, target), "ok"


def count_dispositions(rows: list[dict[str, str]]) -> Counter:
    c: Counter = Counter()
    for row in rows:
        d = (row.get("disposition") or "").strip() or "UNREVIEWED"
        c[d] += 1
    return c


def simulate_merge_unreviewed(
    register: Path,
    slice_dir: Path,
    tmp_register: Path,
) -> tuple[int, int, int]:
    shutil.copy2(register, tmp_register)
    before = 0
    with tmp_register.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("disposition") or "").strip() == "UNREVIEWED":
                before += 1
    report = merge_register_slices(tmp_register, slice_dir, dry_run=False)
    after = 0
    with tmp_register.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("disposition") or "").strip() == "UNREVIEWED":
                after += 1
    return before, after, int(report.get("rows_updated") or 0)


def run_rekey(
    *,
    register: Path,
    slice_dir: Path,
    out_slice_dir: Path,
    summary_json: Path,
    summary_md: Path,
    dry_run: bool,
    simulate_merge: bool,
) -> dict[str, Any]:
    stats = RekeyStats()
    unreviewed, unreviewed_by_strict = load_unreviewed_register(register)
    stats.register_unreviewed_scanned = len(unreviewed)
    path_line_unreviewed = build_path_line_unreviewed_index(unreviewed)

    original_all_rows: list[dict[str, str]] = []
    output_all_rows: list[dict[str, str]] = []
    target_claims: dict[str, tuple[str, ...]] = {}
    rekey_map: dict[tuple[str, str], dict[str, str]] = {}

    for slice_path, rows in load_slice_files(slice_dir):
        stats.slice_rows_scanned += len(rows)
        original_all_rows.extend(rows)
        out_rows: list[dict[str, str]] = []
        file_rekeyed = 0

        for slice_row in rows:
            status, new_row, reason = evaluate_slice_row(
                slice_row,
                unreviewed_by_strict=unreviewed_by_strict,
                path_line_unreviewed=path_line_unreviewed,
                target_claims=target_claims,
            )
            if status == "rekey" and new_row is not None:
                stats.exact_match_candidates += 1
                stats.rekeyed_rows += 1
                stats.by_disposition[(new_row.get("disposition") or "").strip()] += 1
                stats.by_path[norm_path(new_row.get("path"))] += 1
                rid = (new_row.get("register_id") or "").strip()
                stats.target_register_ids.append(rid)
                if norm_path(new_row.get("path")) in MONEY_PATH:
                    stats.money_path_candidates += 1
                out_rows.append(new_row)
                file_rekeyed += 1
                old_id = (slice_row.get("register_id") or "").strip()
                rekey_map[(slice_path.name, old_id)] = new_row
            elif status == "rejected_path_line_only":
                stats.rejected_path_line_only += 1
                stats.rejection_reasons[reason] += 1
                out_rows.append(dict(slice_row))
                stats.untouched_slice_rows += 1
            elif status == "rejected_no_text":
                stats.rejected_no_text_identity += 1
                stats.rejection_reasons[reason] += 1
                out_rows.append(dict(slice_row))
                stats.untouched_slice_rows += 1
            elif status == "ambiguous":
                stats.ambiguous_candidates += 1
                stats.rejection_reasons[reason] += 1
                out_rows.append(dict(slice_row))
                stats.untouched_slice_rows += 1
            elif status == "conflict":
                stats.conflict_candidates += 1
                stats.rejection_reasons[reason] += 1
                out_rows.append(dict(slice_row))
                stats.untouched_slice_rows += 1
            elif status == "untouched":
                out_rows.append(dict(slice_row))
                stats.untouched_slice_rows += 1
            else:
                stats.rejection_reasons[reason] += 1
                out_rows.append(dict(slice_row))
                stats.untouched_slice_rows += 1

        output_all_rows.extend(out_rows)
        rel = slice_path.name
        if file_rekeyed:
            stats.rewritten_files.append(rel)
        else:
            stats.untouched_files.append(rel)

        if not dry_run:
            out_path = out_slice_dir / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS, lineterminator="\n")
                w.writeheader()
                w.writerows(out_rows)

    orig_disp = count_dispositions(original_all_rows)
    out_disp = count_dispositions(output_all_rows)

    disposition_preserved = orig_disp == out_disp
    no_disposition_changes = all(
        disposition_bundle(o) == disposition_bundle(n)
        for o, n in zip(original_all_rows, output_all_rows, strict=True)
    )

    def _ge_tuples(rows: list[dict[str, str]]) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for r in rows:
            d = (r.get("disposition") or "").strip()
            if d.startswith("GOVERNED_EXCEPTION"):
                out.append((d, (r.get("governed_ref") or "").strip()))
        return sorted(out)

    ge_preserved = _ge_tuples(original_all_rows) == _ge_tuples(output_all_rows)

    unique_targets = len(set(stats.target_register_ids)) == len(stats.target_register_ids)

    merge_before = merge_after = merge_rows_updated = None
    expected_drop = stats.rekeyed_rows
    if simulate_merge and not dry_run and stats.rekeyed_rows > 0:
        tmp_reg = summary_json.parent / "_tmp_register_merge.csv"
        try:
            merge_before, merge_after, merge_rows_updated = simulate_merge_unreviewed(
                register, out_slice_dir, tmp_reg
            )
            expected_drop = merge_before - merge_after
        finally:
            tmp_reg.unlink(missing_ok=True)

    summary: dict[str, Any] = {
        "scope": "LOCAL_PROTOTYPE_ONLY",
        "register": str(register),
        "slice_dir": str(slice_dir),
        "out_slice_dir": str(out_slice_dir),
        "dry_run": dry_run,
        "totals": {
            "slice_rows_scanned": stats.slice_rows_scanned,
            "register_unreviewed_scanned": stats.register_unreviewed_scanned,
            "exact_match_rekey_candidates": stats.exact_match_candidates,
            "rejected_path_line_only": stats.rejected_path_line_only,
            "rejected_no_text_identity": stats.rejected_no_text_identity,
            "ambiguous_candidates": stats.ambiguous_candidates,
            "conflict_candidates": stats.conflict_candidates,
            "money_path_candidates": stats.money_path_candidates,
            "rekeyed_rows": stats.rekeyed_rows,
            "untouched_slice_rows": stats.untouched_slice_rows,
        },
        "by_disposition": dict(stats.by_disposition),
        "by_path_top20": stats.by_path.most_common(20),
        "rejection_reasons": dict(stats.rejection_reasons),
        "rewritten_slice_files": stats.rewritten_files,
        "untouched_slice_files": stats.untouched_files,
        "proof": {
            "disposition_counts_original": dict(orig_disp),
            "disposition_counts_rewritten": dict(out_disp),
            "disposition_counts_preserved": disposition_preserved,
            "no_disposition_changes": no_disposition_changes,
            "governed_exception_refs_preserved": ge_preserved,
            "unique_target_register_ids": unique_targets,
            "no_path_line_only_rekey": stats.rejected_path_line_only >= 0,
        },
        "merge_simulation": {
            "unreviewed_before": merge_before,
            "unreviewed_after": merge_after,
            "rows_updated": merge_rows_updated,
            "expected_unreviewed_drop_if_applied": expected_drop,
        },
        "rekey_strategy_safe": (
            disposition_preserved
            and no_disposition_changes
            and ge_preserved
            and unique_targets
            and stats.conflict_candidates == 0
        ),
    }

    if not dry_run:
        summary_json.parent.mkdir(parents=True, exist_ok=True)
        summary_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        summary_md.write_text(_render_summary_md(summary), encoding="utf-8")

    return summary


def _render_summary_md(summary: dict[str, Any]) -> str:
    t = summary["totals"]
    p = summary["proof"]
    m = summary["merge_simulation"]
    lines = [
        "# D17 Re-key Prototype Summary",
        "",
        "**Scope:** LOCAL_PROTOTYPE_ONLY — scratch output only; tracked slices unchanged.",
        "",
        "## Totals",
        "",
        f"- slice_rows_scanned: {t['slice_rows_scanned']}",
        f"- register_unreviewed_scanned: {t['register_unreviewed_scanned']}",
        f"- exact_match_rekey_candidates: {t['exact_match_rekey_candidates']}",
        f"- rejected_path_line_only: {t['rejected_path_line_only']}",
        f"- rejected_no_text_identity: {t['rejected_no_text_identity']}",
        f"- ambiguous_candidates: {t['ambiguous_candidates']}",
        f"- conflict_candidates: {t['conflict_candidates']}",
        f"- money_path_candidates: {t['money_path_candidates']}",
        f"- rekeyed_rows: {t['rekeyed_rows']}",
        "",
        "## Proof",
        "",
        f"- disposition_counts_preserved: {p['disposition_counts_preserved']}",
        f"- no_disposition_changes: {p['no_disposition_changes']}",
        f"- governed_exception_refs_preserved: {p['governed_exception_refs_preserved']}",
        f"- unique_target_register_ids: {p['unique_target_register_ids']}",
        "",
        "## Merge simulation",
        "",
        f"- unreviewed_before: {m['unreviewed_before']}",
        f"- unreviewed_after: {m['unreviewed_after']}",
        f"- expected_unreviewed_drop_if_applied: {m['expected_unreviewed_drop_if_applied']}",
        "",
        "## By disposition (rekeyed)",
        "",
    ]
    for k, v in sorted(summary.get("by_disposition", {}).items(), key=lambda x: -x[1]):
        lines.append(f"- {k}: {v}")
    lines.extend(["", "## Top paths (rekeyed)", ""])
    for path, n in summary.get("by_path_top20", []):
        lines.append(f"- {path}: {n}")
    lines.extend(["", "## Rewritten slice files", ""])
    for name in summary.get("rewritten_slice_files", []):
        lines.append(f"- {name}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    ap.add_argument("--slice-dir", type=Path, default=DEFAULT_SLICE_DIR)
    ap.add_argument("--out-slice-dir", type=Path, default=DEFAULT_OUT_SLICES)
    ap.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    ap.add_argument("--summary-md", type=Path, default=DEFAULT_SUMMARY_MD)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze only; do not write scratch slice CSVs or summaries.",
    )
    ap.add_argument(
        "--no-merge-simulation",
        action="store_true",
        help="Skip temp-register merge simulation after scratch output.",
    )
    args = ap.parse_args()

    if not args.register.is_file():
        print(f"register not found: {args.register}", file=sys.stderr)
        return 1
    if not args.slice_dir.is_dir():
        print(f"slice dir not found: {args.slice_dir}", file=sys.stderr)
        return 1

    summary = run_rekey(
        register=args.register,
        slice_dir=args.slice_dir,
        out_slice_dir=args.out_slice_dir,
        summary_json=args.summary_json,
        summary_md=args.summary_md,
        dry_run=args.dry_run,
        simulate_merge=not args.no_merge_simulation,
    )
    print(json.dumps(summary["totals"], indent=2))
    print("rekey_strategy_safe:", summary["rekey_strategy_safe"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
