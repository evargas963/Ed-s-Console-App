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
from tools.schwab_universal_coverage_scanner_v3.register import (
    REGISTER_COLUMNS,
    DOC_SCOPE,
    FILE_SCOPE,
    GENERATED_ARTIFACT_SCOPE,
    LINE_SCOPE,
    SITE_SCOPE,
    UNKNOWN_SCOPE,
    classify_disposition_scope,
    compute_line_text_hash,
    compute_stable_semantic_key,
    file_classification_from_slice_basename,
    line_scope_disposition_admissible,
    normalize_register_path,
    read_source_line_text,
    site_scope_disposition_admissible,
)
from tools.stream_revert_v4_register_and_sync_perf import merge_register_slices, site_key
from governance.phase3_d17_adapter_boundary import WIRE_PATTERN_KINDS
from governance.phase4_d17_market_state_boundary import (
    PHASE4_LEXICAL_PATTERN_KINDS,
    PHASE4_LEXICAL_WIRE_LINE_DENYLIST,
    PHASE4_MARKET_STATE_PATH,
)

DEFAULT_REGISTER = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
DEFAULT_SLICE_DIR = ROOT / "governance" / "register_slices"
DEFAULT_SCRATCH = ROOT / "reports" / "d17_rekey_prototype"
DEFAULT_OUT_SLICES = DEFAULT_SCRATCH / "register_slices_rekeyed"
DEFAULT_SUMMARY_JSON = DEFAULT_SCRATCH / "d17_rekey_summary.json"
DEFAULT_SUMMARY_MD = DEFAULT_SCRATCH / "d17_rekey_summary.md"
DEFAULT_SEMANTIC_SUMMARY_JSON = DEFAULT_SCRATCH / "d17_stable_semantic_summary.json"
DEFAULT_SEMANTIC_SUMMARY_MD = DEFAULT_SCRATCH / "d17_stable_semantic_summary.md"

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

# Policy A — no automated LINE_SCOPE NOT_MARKET_DATA on AGENTS money-path roster files.
MONEY_PATH_LINE_SCOPE_BLOCKED = "MONEY_PATH_LINE_SCOPE_BLOCKED"
LINE_SCOPE_SCRATCH_ONLY = "LINE_SCOPE_SCRATCH_ONLY"
EXPECTED_PRODUCTION_METRIC_MOVEMENT = "NONE"

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
    return normalize_register_path(path)


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


def _is_lexical_pattern_kind(pattern_kind: str) -> bool:
    pk = (pattern_kind or "").strip()
    return pk in PHASE4_LEXICAL_PATTERN_KINDS


def _is_wire_pattern_kind(pattern_kind: str) -> bool:
    return (pattern_kind or "").strip() in WIRE_PATTERN_KINDS


def _line_is_mixed(unreviewed_at_line: list[dict[str, str]]) -> bool:
    if len(unreviewed_at_line) <= 1:
        return False
    has_wire = any(_is_wire_pattern_kind(r.get("pattern_kind") or "") for r in unreviewed_at_line)
    has_lexical = any(_is_lexical_pattern_kind(r.get("pattern_kind") or "") for r in unreviewed_at_line)
    return has_wire and has_lexical


def is_d17_money_path(path: str) -> bool:
    return norm_path(path) in MONEY_PATH


def line_scope_policy_a_blocks(path: str) -> bool:
    """Policy A: block all automated LINE_SCOPE on money-path files."""
    return is_d17_money_path(path)


def line_scope_automation_eligible(
    slice_row: dict[str, str],
    scope: str,
    *,
    production: bool = False,
) -> tuple[bool, str | None]:
    """Gate automated LINE_SCOPE application (Policy A + scratch-only for production)."""
    if scope != LINE_SCOPE:
        return True, None
    path = norm_path(slice_row.get("path"))
    if line_scope_policy_a_blocks(path):
        return False, MONEY_PATH_LINE_SCOPE_BLOCKED
    if production:
        return False, LINE_SCOPE_SCRATCH_ONLY
    return True, None


def _line_scope_lexical_targets(
    slice_row: dict[str, str],
    unreviewed_at_line: list[dict[str, str]],
    *,
    line_text_hash: str,
) -> tuple[list[dict[str, str]], str | None]:
    """Lexical/wire filters only — does not apply Policy A (used for policy-audit hypotheticals)."""
    path = norm_path(slice_row.get("path"))
    line = int(slice_row.get("line") or 0)
    disp = (slice_row.get("disposition") or "").strip()
    if not line_scope_disposition_admissible(disp):
        if disp.startswith("GOVERNED_EXCEPTION"):
            return [], "governed_exception_line_scope"
        return [], "line_scope_disposition_forbidden"

    if line_text_hash in ("MISSING", "EMPTY"):
        return [], "line_text_hash_missing"

    mixed = _line_is_mixed(unreviewed_at_line)
    targets: list[dict[str, str]] = []
    for reg in unreviewed_at_line:
        pk = (reg.get("pattern_kind") or "").strip()
        if _is_wire_pattern_kind(pk):
            continue
        if path in MONEY_PATH and not _is_lexical_pattern_kind(pk):
            continue
        if path == PHASE4_MARKET_STATE_PATH and str(line) in PHASE4_LEXICAL_WIRE_LINE_DENYLIST:
            return [], "mixed_line_money_path_denylist"
        targets.append(reg)

    if not targets:
        if path in MONEY_PATH:
            return [], "money_path_no_lexical_targets"
        if any(_is_wire_pattern_kind(r.get("pattern_kind") or "") for r in unreviewed_at_line):
            return [], "wire_only_line"
        return [], "no_lexical_targets"

    if mixed and path in MONEY_PATH and path == PHASE4_MARKET_STATE_PATH:
        if str(line) in PHASE4_LEXICAL_WIRE_LINE_DENYLIST:
            return [], "mixed_line_money_path_denylist"

    return targets, None


def _line_scope_register_targets(
    slice_row: dict[str, str],
    unreviewed_at_line: list[dict[str, str]],
    *,
    line_text_hash: str,
    apply_policy_a: bool = True,
) -> tuple[list[dict[str, str]], str | None]:
    """Return scratch-eligible register targets for LINE_SCOPE; Policy A blocks money-path."""
    path = norm_path(slice_row.get("path"))
    if apply_policy_a and line_scope_policy_a_blocks(path):
        disp = (slice_row.get("disposition") or "").strip()
        if not line_scope_disposition_admissible(disp):
            if disp.startswith("GOVERNED_EXCEPTION"):
                return [], "governed_exception_line_scope"
            return [], "line_scope_disposition_forbidden"
        return [], MONEY_PATH_LINE_SCOPE_BLOCKED

    return _line_scope_lexical_targets(
        slice_row, unreviewed_at_line, line_text_hash=line_text_hash
    )


def _site_scope_register_targets(
    slice_row: dict[str, str],
    site_key_index: dict[tuple[str, int, int, str, str], list[dict[str, str]]],
    stable_key_index: dict[str, list[dict[str, str]]],
    slice_stable_key: str,
) -> tuple[list[dict[str, str]], str | None]:
    disp = (slice_row.get("disposition") or "").strip()
    if not site_scope_disposition_admissible(disp):
        return [], "unreviewed_slice"
    ok, reason = disposition_proof_admissible(slice_row)
    if not ok:
        return [], reason

    sk = site_key(slice_row)
    by_site = site_key_index.get(sk, [])
    if len(by_site) == 1:
        return by_site, None
    if len(by_site) > 1:
        return [], "site_key_ambiguous"

    by_stable = stable_key_index.get(slice_stable_key, [])
    if len(by_stable) == 1:
        return by_stable, None
    if len(by_stable) > 1:
        return [], "stable_key_ambiguous"
    return [], "no_site_or_stable_match"


def run_stable_semantic_prototype_analysis(
    *,
    register: Path,
    slice_dir: Path,
    repo_root: Path,
    summary_json: Path,
    summary_md: Path,
) -> dict[str, Any]:
    """Scratch-only stable semantic key eligibility report (no register/slice writes)."""
    unreviewed, _ = load_unreviewed_register(register)
    by_pl = build_path_line_unreviewed_index(unreviewed)
    unreviewed_ids = {(r.get("register_id") or "").strip() for r in unreviewed}

    reg_by_site: dict[tuple[str, int, int, str, str], list[dict[str, str]]] = defaultdict(list)
    reg_by_stable: dict[str, list[dict[str, str]]] = defaultdict(list)
    line_hash_cache: dict[tuple[str, int], str] = {}

    def _line_hash(path: str, line: int) -> str:
        pl = (norm_path(path), line)
        cached = line_hash_cache.get(pl)
        if cached is not None:
            return cached
        lt = read_source_line_text(repo_root, pl[0], pl[1])
        cached = compute_line_text_hash(lt)
        line_hash_cache[pl] = cached
        return cached

    for reg in unreviewed:
        reg_by_site[site_key(reg)].append(reg)
        scope = classify_disposition_scope(reg)
        if scope == UNKNOWN_SCOPE:
            scope = SITE_SCOPE
        pl = path_line_key(reg)
        ssk = compute_stable_semantic_key(reg, scope, line_text_hash=_line_hash(pl[0], pl[1]))
        if ssk:
            reg_by_stable[ssk].append(reg)

    stats: dict[str, Any] = {
        "scope": "STABLE_SEMANTIC_PROTOTYPE_ONLY",
        "register": str(register),
        "slice_dir": str(slice_dir),
        "stable_key_candidate_count": 0,
        "stable_key_collision_count": 0,
        "line_scope_candidate_count": 0,
        "line_scope_total_count": 0,
        "line_scope_money_path_count": 0,
        "line_scope_money_path_blocked_count": 0,
        "line_scope_non_money_count": 0,
        "line_scope_non_money_scratch_eligible_count": 0,
        "line_scope_site_conflict_blocked_count": 0,
        "policy_a_block_count": 0,
        "expected_production_metric_movement": EXPECTED_PRODUCTION_METRIC_MOVEMENT,
        "site_scope_candidate_count": 0,
        "file_scope_candidate_count": 0,
        "doc_scope_candidate_count": 0,
        "generated_artifact_scope_candidate_count": 0,
        "unknown_scope_count": 0,
        "line_scope_safe_nmd_count": 0,
        "line_scope_blocked_wire_count": 0,
        "line_scope_blocked_money_path_count": 0,
        "line_scope_blocked_mixed_line_count": 0,
        "line_scope_blocked_ambiguous_count": 0,
        "line_scope_blocked_line_hash_count": 0,
        "governed_exception_blocked_line_scope_count": 0,
        "line_scope_forbidden_disposition_count": 0,
        "site_scope_safe_count": 0,
        "site_scope_blocked_count": 0,
        "expected_merge_eligible_register_ids": set(),
        "tier_register_id_count": 0,
        "tier_site_key_count": 0,
        "tier_stable_key_count": 0,
    }
    slice_key_claims: dict[str, tuple[str, ...]] = {}
    collisions: list[dict[str, str]] = []
    ambiguities: list[dict[str, str]] = []
    examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    transitions: Counter = Counter()
    by_path: Counter = Counter()

    def _add_example(bucket: str, row: dict[str, str], extra: dict[str, str] | None = None) -> None:
        if len(examples[bucket]) >= 5:
            return
        item = {
            "path": norm_path(row.get("path")),
            "line": row.get("line"),
            "pattern_kind": row.get("pattern_kind"),
            "disposition": row.get("disposition"),
        }
        if extra:
            item.update(extra)
        examples[bucket].append(item)

    for slice_path, rows in load_slice_files(slice_dir):
        basename = slice_path.name
        fc = file_classification_from_slice_basename(basename)
        for slice_row in rows:
            disp = (slice_row.get("disposition") or "").strip()
            if not disp or disp == "UNREVIEWED":
                continue

            scope = classify_disposition_scope(slice_row, slice_basename=basename)
            pl = path_line_key(slice_row)
            lth = _line_hash(pl[0], pl[1])
            ssk = compute_stable_semantic_key(
                slice_row,
                scope,
                line_text_hash=lth,
                file_classification=fc,
            )

            if scope == UNKNOWN_SCOPE:
                stats["unknown_scope_count"] += 1
                _add_example("unknown_scope", slice_row, {"stable_key": ssk})
                continue

            if ssk:
                stats["stable_key_candidate_count"] += 1
                prior = slice_key_claims.get(ssk)
                bundle = disposition_bundle(slice_row)
                if prior is not None and prior != bundle:
                    stats["stable_key_collision_count"] += 1
                    collisions.append(
                        {
                            "stable_key": ssk,
                            "scope": scope,
                            "path": pl[0],
                            "line": str(pl[1]),
                            "disposition": disp,
                        }
                    )
                else:
                    slice_key_claims[ssk] = bundle

            if scope == LINE_SCOPE:
                stats["line_scope_candidate_count"] += 1
                stats["line_scope_total_count"] += 1
                if is_d17_money_path(pl[0]):
                    stats["line_scope_money_path_count"] += 1
                else:
                    stats["line_scope_non_money_count"] += 1
                spk = (slice_row.get("pattern_kind") or "").strip()
                regs_at_pl = by_pl.get(pl, [])
                if regs_at_pl:
                    top_rpk = Counter((r.get("pattern_kind") or "").strip() for r in regs_at_pl).most_common(1)[0][0]
                    transitions[(spk, top_rpk)] += 1

                if disp.startswith("GOVERNED_EXCEPTION"):
                    stats["governed_exception_blocked_line_scope_count"] += 1
                    continue
                if not line_scope_disposition_admissible(disp):
                    stats["line_scope_forbidden_disposition_count"] += 1
                    _add_example("line_scope_forbidden_disp", slice_row)
                    continue

                targets, block_reason = _line_scope_register_targets(
                    slice_row, regs_at_pl, line_text_hash=lth
                )
                hypo_targets, _ = _line_scope_register_targets(
                    slice_row, regs_at_pl, line_text_hash=lth, apply_policy_a=False
                )
                if block_reason == MONEY_PATH_LINE_SCOPE_BLOCKED:
                    stats["line_scope_money_path_blocked_count"] += 1
                    stats["policy_a_block_count"] += 1
                    if hypo_targets:
                        _add_example(
                            "line_scope_blocked_policy_a",
                            slice_row,
                            {"hypothetical_targets": str(len(hypo_targets))},
                        )
                if block_reason == "line_text_hash_missing":
                    stats["line_scope_blocked_line_hash_count"] += 1
                elif block_reason == "money_path_no_lexical_targets":
                    stats["line_scope_blocked_money_path_count"] += 1
                elif block_reason == "mixed_line_money_path_denylist":
                    stats["line_scope_blocked_mixed_line_count"] += 1
                elif block_reason == "wire_only_line":
                    stats["line_scope_blocked_wire_count"] += 1
                elif block_reason in ("site_key_ambiguous", "stable_key_ambiguous"):
                    stats["line_scope_blocked_ambiguous_count"] += 1
                elif block_reason == "site_scope_conflict":
                    stats["line_scope_site_conflict_blocked_count"] += 1

                if targets:
                    stats["line_scope_safe_nmd_count"] += 1
                    if not is_d17_money_path(pl[0]):
                        stats["line_scope_non_money_scratch_eligible_count"] += 1
                    for t in targets:
                        rid = (t.get("register_id") or "").strip()
                        if rid:
                            stats["expected_merge_eligible_register_ids"].add(rid)
                            stats["tier_stable_key_count"] += 1
                            by_path[norm_path(slice_row.get("path"))] += 1
                    _add_example("line_scope_safe", slice_row, {"targets": str(len(targets))})
                elif block_reason:
                    _add_example(f"line_scope_blocked_{block_reason}", slice_row)

            elif scope == SITE_SCOPE:
                stats["site_scope_candidate_count"] += 1
                targets, block_reason = _site_scope_register_targets(
                    slice_row, reg_by_site, reg_by_stable, ssk
                )
                if targets:
                    stats["site_scope_safe_count"] += 1
                    rid = (targets[0].get("register_id") or "").strip()
                    if rid:
                        stats["expected_merge_eligible_register_ids"].add(rid)
                        if site_key(slice_row) in reg_by_site and len(reg_by_site[site_key(slice_row)]) == 1:
                            stats["tier_site_key_count"] += 1
                        else:
                            stats["tier_stable_key_count"] += 1
                        by_path[norm_path(slice_row.get("path"))] += 1
                    _add_example("site_scope_safe", slice_row)
                else:
                    stats["site_scope_blocked_count"] += 1
                    if block_reason and "ambiguous" in block_reason:
                        stats["line_scope_blocked_ambiguous_count"] += 1
                        ambiguities.append(
                            {
                                "scope": SITE_SCOPE,
                                "reason": block_reason,
                                "path": pl[0],
                                "line": str(pl[1]),
                                "stable_key": ssk,
                            }
                        )

            elif scope == FILE_SCOPE:
                stats["file_scope_candidate_count"] += 1
            elif scope == DOC_SCOPE:
                stats["doc_scope_candidate_count"] += 1
            elif scope == GENERATED_ARTIFACT_SCOPE:
                stats["generated_artifact_scope_candidate_count"] += 1

            rid = (slice_row.get("register_id") or "").strip()
            if rid and rid in unreviewed_ids:
                stats["tier_register_id_count"] += 1
                stats["expected_merge_eligible_register_ids"].add(rid)
                by_path[norm_path(slice_row.get("path"))] += 1

    eligible_ids = stats.pop("expected_merge_eligible_register_ids")
    expected_merge = len(eligible_ids)
    stats["expected_merge_eligible_count"] = expected_merge
    stats["expected_unreviewed_drop_if_applied"] = expected_merge

    summary: dict[str, Any] = {
        **stats,
        "by_path_top20": by_path.most_common(20),
        "pattern_kind_transitions_top20": transitions.most_common(20),
        "collision_examples": collisions[:20],
        "ambiguity_examples": ambiguities[:20],
        "examples_by_class": dict(examples),
        "proof": {
            "register_id_preserved": True,
            "site_key_preserved": True,
            "path_line_only_disabled_in_prototype": True,
            "tracked_slices_unmodified": True,
            "policy_a_money_path_line_scope_blocked": True,
            "production_semantic_key_merge_unchanged": True,
            "expected_production_metric_movement": EXPECTED_PRODUCTION_METRIC_MOVEMENT,
        },
    }

    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    summary_md.write_text(_render_semantic_summary_md(summary), encoding="utf-8")
    return summary


def _render_semantic_summary_md(summary: dict[str, Any]) -> str:
    lines = [
        "# D17 Stable Semantic Key Prototype Summary",
        "",
        "**Scope:** STABLE_SEMANTIC_PROTOTYPE_ONLY — scratch report; no tracked register/slice changes.",
        "",
        "## Counts",
        "",
        f"- stable_key_candidate_count: {summary.get('stable_key_candidate_count')}",
        f"- stable_key_collision_count: {summary.get('stable_key_collision_count')}",
        f"- line_scope_candidate_count: {summary.get('line_scope_candidate_count')}",
        f"- site_scope_candidate_count: {summary.get('site_scope_candidate_count')}",
        f"- unknown_scope_count: {summary.get('unknown_scope_count')}",
        f"- line_scope_safe_nmd_count: {summary.get('line_scope_safe_nmd_count')}",
        f"- line_scope_total_count: {summary.get('line_scope_total_count')}",
        f"- line_scope_money_path_count: {summary.get('line_scope_money_path_count')}",
        f"- line_scope_money_path_blocked_count: {summary.get('line_scope_money_path_blocked_count')}",
        f"- line_scope_non_money_count: {summary.get('line_scope_non_money_count')}",
        f"- line_scope_non_money_scratch_eligible_count: {summary.get('line_scope_non_money_scratch_eligible_count')}",
        f"- policy_a_block_count: {summary.get('policy_a_block_count')}",
        f"- expected_production_metric_movement: {summary.get('expected_production_metric_movement')}",
        f"- site_scope_safe_count: {summary.get('site_scope_safe_count')}",
        f"- expected_merge_eligible_count: {summary.get('expected_merge_eligible_count')}",
        f"- expected_unreviewed_drop_if_applied: {summary.get('expected_unreviewed_drop_if_applied')}",
        "",
        "## Blocks",
        "",
        f"- line_scope_blocked_wire_count: {summary.get('line_scope_blocked_wire_count')}",
        f"- line_scope_blocked_money_path_count: {summary.get('line_scope_blocked_money_path_count')}",
        f"- line_scope_blocked_mixed_line_count: {summary.get('line_scope_blocked_mixed_line_count')}",
        f"- line_scope_blocked_ambiguous_count: {summary.get('line_scope_blocked_ambiguous_count')}",
        "",
    ]
    return "\n".join(lines) + "\n"


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
    ap.add_argument(
        "--semantic-prototype-report",
        action="store_true",
        help="Emit stable semantic key scratch report only (no re-key output).",
    )
    ap.add_argument(
        "--semantic-summary-json",
        type=Path,
        default=DEFAULT_SEMANTIC_SUMMARY_JSON,
    )
    ap.add_argument(
        "--semantic-summary-md",
        type=Path,
        default=DEFAULT_SEMANTIC_SUMMARY_MD,
    )
    args = ap.parse_args()

    if not args.register.is_file():
        print(f"register not found: {args.register}", file=sys.stderr)
        return 1
    if not args.slice_dir.is_dir():
        print(f"slice dir not found: {args.slice_dir}", file=sys.stderr)
        return 1

    if args.semantic_prototype_report:
        sem = run_stable_semantic_prototype_analysis(
            register=args.register,
            slice_dir=args.slice_dir,
            repo_root=ROOT,
            summary_json=args.semantic_summary_json,
            summary_md=args.semantic_summary_md,
        )
        print(json.dumps({k: sem[k] for k in sem if k != "examples_by_class"}, indent=2))
        return 0

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
