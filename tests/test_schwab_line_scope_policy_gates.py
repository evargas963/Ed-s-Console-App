"""Tests for D17 Policy A LINE_SCOPE gates (tool/test only — no production merge)."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.d17_rekey_register_slices import (
    MONEY_PATH,
    MONEY_PATH_LINE_SCOPE_BLOCKED,
    LINE_SCOPE_SCRATCH_ONLY,
    EXPECTED_PRODUCTION_METRIC_MOVEMENT,
    _line_scope_register_targets,
    evaluate_slice_row,
    line_scope_automation_eligible,
    line_scope_policy_a_blocks,
    load_unreviewed_register,
    run_stable_semantic_prototype_analysis,
)
from tools.schwab_universal_coverage_scanner_v3.register import (
    LINE_SCOPE,
    SITE_SCOPE,
    REGISTER_COLUMNS,
    RegisterRow,
    classify_disposition_scope,
    line_scope_disposition_admissible,
)
from tools.stream_revert_v4_register_and_sync_perf import (
    _resolve_slice_row,
    line_scope_production_merge_blocked,
    load_slice_disposition_maps,
    merge_register_slices,
    resolve_slice_row_prototype,
    site_key,
)


def _row(**kwargs) -> dict[str, str]:
    base = RegisterRow(
        register_id="id_a",
        language="python",
        path="example.py",
        line=10,
        col=4,
        pattern_kind="TEXT_LINE_MARKET_TOKEN",
        surface_form="spot_price",
        tokens="spot_price",
        csv_candidates="",
        csv_lexical_topk_note="",
        v2_trace="",
        disposition="NOT_MARKET_DATA",
    ).as_csv_dict()
    base.update({k: str(v) for k, v in kwargs.items()})
    return base


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


@pytest.mark.parametrize(
    "path",
    sorted(MONEY_PATH),
)
def test_policy_a_blocks_every_agents_money_path_file(path: str) -> None:
    assert line_scope_policy_a_blocks(path) is True


def test_policy_a_blocks_money_path_line_scope_even_when_lexical_unique() -> None:
    slice_row = _row(
        path="bayesian_fusion.py",
        line=601,
        pattern_kind="FORMAL_NMD",
        disposition="NOT_MARKET_DATA",
    )
    reg = _row(
        register_id="l",
        disposition="UNREVIEWED",
        path="bayesian_fusion.py",
        line=601,
        pattern_kind="TEXT_LINE_MARKET_TOKEN",
    )
    targets, reason = _line_scope_register_targets(
        slice_row, [reg], line_text_hash="deadbeefcafebabe"
    )
    assert targets == []
    assert reason == MONEY_PATH_LINE_SCOPE_BLOCKED


def test_non_money_line_scope_scratch_eligible_not_production() -> None:
    slice_row = _row(
        path="training_cache.py",
        pattern_kind="FORMAL_NMD",
        disposition="NOT_MARKET_DATA",
    )
    reg = _row(
        register_id="l",
        disposition="UNREVIEWED",
        path="training_cache.py",
        pattern_kind="TEXT_LINE_MARKET_TOKEN",
    )
    targets, reason = _line_scope_register_targets(
        slice_row, [reg], line_text_hash="abc123"
    )
    assert reason is None
    assert len(targets) == 1
    ok, prod_reason = line_scope_automation_eligible(
        slice_row, LINE_SCOPE, production=True
    )
    assert ok is False
    assert prod_reason == LINE_SCOPE_SCRATCH_ONLY
    blocked, merge_reason = line_scope_production_merge_blocked(slice_row)
    assert blocked is True
    assert merge_reason == LINE_SCOPE_SCRATCH_ONLY


@pytest.mark.parametrize(
    "disposition",
    [
        "REPLACED",
        "PASS_THROUGH",
        "KEEP_DERIVED",
        "GOVERNED_EXCEPTION (O-49)",
    ],
)
def test_line_scope_forbidden_dispositions_blocked(disposition: str) -> None:
    assert line_scope_disposition_admissible(disposition) is False
    slice_row = _row(
        path="training_cache.py",
        pattern_kind="FORMAL_REPLACED" if disposition == "REPLACED" else "FORMAL_NMD",
        disposition=disposition,
    )
    if disposition == "REPLACED":
        slice_row["pattern_kind"] = "FORMAL_REPLACED"
    targets, reason = _line_scope_register_targets(
        slice_row, [], line_text_hash="abc123"
    )
    assert targets == []
    assert reason in ("line_scope_disposition_forbidden", "governed_exception_line_scope")


def test_site_scope_unchanged_by_policy_a() -> None:
    row = _row(disposition="NOT_MARKET_DATA", path="signals.py")
    assert classify_disposition_scope(row) == SITE_SCOPE
    ok, reason = line_scope_automation_eligible(row, SITE_SCOPE, production=True)
    assert ok is True
    assert reason is None


def test_register_id_and_site_key_production_resolver_unchanged(tmp_path: Path) -> None:
    reg = tmp_path / "reg.csv"
    slice_dir = tmp_path / "slices"
    reg_row = _row(
        register_id="exact_id",
        disposition="UNREVIEWED",
        path="signals.py",
    )
    slice_row = _row(
        register_id="exact_id",
        disposition="NOT_MARKET_DATA",
        path="signals.py",
    )
    _write_csv(reg, [reg_row])
    _write_csv(slice_dir / "signals.csv", [slice_row])
    report = merge_register_slices(reg, slice_dir, dry_run=True)
    assert report["rows_updated"] == 1
    by_site, by_id, by_pl = load_slice_disposition_maps(slice_dir)
    resolved = _resolve_slice_row(reg_row, by_id, by_site, by_pl)
    assert resolved is not None
    assert resolved.get("register_id") == "exact_id"
    assert resolved.get("disposition") == "NOT_MARKET_DATA"
    matched, tier = resolve_slice_row_prototype(reg_row, by_id, by_site, {})
    assert tier == "register_id"
    assert matched is not None
    assert matched.get("register_id") == "exact_id"


def test_path_line_only_still_rejected(tmp_path: Path) -> None:
    reg = tmp_path / "reg.csv"
    reg_rows = [
        _row(
            register_id="reg_a",
            disposition="UNREVIEWED",
            pattern_kind="OTHER_KIND",
            surface_form="other",
            tokens="other",
            col=8,
        ),
    ]
    _write_csv(reg, reg_rows)
    _, by_strict = load_unreviewed_register(reg)
    pl_idx = {("example.py", 10): reg_rows}
    status, _, reason = evaluate_slice_row(
        _row(disposition="NOT_MARKET_DATA"),
        unreviewed_by_strict=by_strict,
        path_line_unreviewed=pl_idx,
        target_claims={},
    )
    assert status == "rejected_path_line_only"


def test_scratch_report_records_policy_a_counts(tmp_path: Path) -> None:
    reg = tmp_path / "reg.csv"
    slice_dir = tmp_path / "slices"
    py_mp = tmp_path / "signals.py"
    py_nm = tmp_path / "training_cache.py"
    py_mp.write_text("# mp\n", encoding="utf-8")
    py_nm.write_text("# nm\n", encoding="utf-8")
    _write_csv(
        reg,
        [
            _row(
                register_id="mp_reg",
                path="signals.py",
                line=1,
                col=4,
                disposition="UNREVIEWED",
            ),
            _row(
                register_id="nm_reg",
                path="training_cache.py",
                line=1,
                col=4,
                disposition="UNREVIEWED",
            ),
        ],
    )
    _write_csv(
        slice_dir / "signals_py_1_1.csv",
        [
            _row(
                register_id="old_mp",
                path="signals.py",
                line=1,
                col=400,
                pattern_kind="FORMAL_NMD",
                surface_form="L1 orchestration",
                tokens="L1_orchestration",
                disposition="NOT_MARKET_DATA",
            ),
        ],
    )
    _write_csv(
        slice_dir / "training_cache_py_1_1.csv",
        [
            _row(
                register_id="old_nm",
                path="training_cache.py",
                line=1,
                col=400,
                pattern_kind="FORMAL_NMD",
                surface_form="L1 orchestration",
                tokens="L1_orchestration",
                disposition="NOT_MARKET_DATA",
            ),
        ],
    )
    out_json = tmp_path / "semantic.json"
    summary = run_stable_semantic_prototype_analysis(
        register=reg,
        slice_dir=slice_dir,
        repo_root=tmp_path,
        summary_json=out_json,
        summary_md=tmp_path / "semantic.md",
    )
    assert summary["policy_a_block_count"] >= 1
    assert summary["line_scope_money_path_blocked_count"] >= 1
    assert summary["line_scope_non_money_scratch_eligible_count"] >= 1
    assert summary["expected_production_metric_movement"] == EXPECTED_PRODUCTION_METRIC_MOVEMENT
    assert summary["proof"]["policy_a_money_path_line_scope_blocked"] is True


def test_stable_semantic_key_remains_prototype_tier() -> None:
    reg = _row(register_id="r1", disposition="UNREVIEWED")
    slice_row = _row(register_id="other", disposition="NOT_MARKET_DATA")
    sk = site_key(reg)
    by_id: dict = {}
    by_site = {sk: slice_row}
    by_stable = {"stable_only": slice_row}
    matched, tier = resolve_slice_row_prototype(reg, by_id, by_site, by_stable)
    assert tier == "site_key"
    reg2 = _row(register_id="r2", disposition="UNREVIEWED", col=99)
    matched2, tier2 = resolve_slice_row_prototype(reg2, by_id, by_site, by_stable)
    assert tier2 == "none"
    assert matched2 is None
