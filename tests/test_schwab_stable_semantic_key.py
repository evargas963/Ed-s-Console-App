"""Tests for D17 stable semantic key prototype (tool/test only)."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.d17_rekey_register_slices import (
    _line_scope_register_targets,
    _site_scope_register_targets,
    evaluate_slice_row,
    load_unreviewed_register,
    run_stable_semantic_prototype_analysis,
)
from tools.schwab_universal_coverage_scanner_v3.register import (
    LINE_SCOPE,
    SITE_SCOPE,
    UNKNOWN_SCOPE,
    RegisterRow,
    classify_disposition_scope,
    compute_line_text_hash,
    compute_stable_semantic_key,
    line_scope_disposition_admissible,
    read_source_line_text,
)
from tools.stream_revert_v4_register_and_sync_perf import (
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


def test_site_scope_key_deterministic() -> None:
    row = _row()
    scope = classify_disposition_scope(row)
    assert scope == SITE_SCOPE
    k1 = compute_stable_semantic_key(row, SITE_SCOPE)
    k2 = compute_stable_semantic_key(row, SITE_SCOPE)
    assert k1 == k2
    assert len(k1) == 20


def test_site_scope_ignores_pattern_kind_when_tokens_surface_match() -> None:
    a = _row(pattern_kind="TEXT_LINE_MARKET_TOKEN", col=8)
    b = _row(pattern_kind="DICT_GET_MARKET_NULLABLE", col=8)
    ka = compute_stable_semantic_key(a, SITE_SCOPE)
    kb = compute_stable_semantic_key(b, SITE_SCOPE)
    assert ka == kb


def test_site_scope_differs_when_col_differs() -> None:
    a = _row(col=4)
    b = _row(col=8)
    assert compute_stable_semantic_key(a, SITE_SCOPE) != compute_stable_semantic_key(b, SITE_SCOPE)


def test_site_scope_rejects_path_line_only_via_evaluate_slice_row(tmp_path: Path) -> None:
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
    assert reason == "path_line_only_no_strict_match"


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def test_site_scope_prototype_resolver_no_path_line_only(tmp_path: Path) -> None:
    reg_row = _row(
        register_id="reg_a",
        disposition="UNREVIEWED",
        pattern_kind="OTHER_KIND",
        surface_form="other",
        tokens="other",
        col=8,
    )
    by_id: dict = {}
    by_site: dict = {}
    by_stable: dict = {}
    matched, tier = resolve_slice_row_prototype(reg_row, by_id, by_site, by_stable)
    assert matched is None
    assert tier == "none"


def test_line_scope_key_deterministic(tmp_path: Path) -> None:
    py = tmp_path / "example.py"
    py.write_text("x = 1\n# market comment\n", encoding="utf-8")
    row = _row(pattern_kind="FORMAL_NMD", surface_form="L10 orchestration", tokens="L10_orchestration")
    scope = classify_disposition_scope(row)
    assert scope == LINE_SCOPE
    lt = read_source_line_text(tmp_path, "example.py", 10)
    lth = compute_line_text_hash(lt)
    k1 = compute_stable_semantic_key(row, LINE_SCOPE, line_text_hash=lth)
    k2 = compute_stable_semantic_key(row, LINE_SCOPE, line_text_hash=lth)
    assert k1 == k2


def test_line_scope_detects_line_text_hash_drift(tmp_path: Path) -> None:
    py = tmp_path / "example.py"
    py.write_text("original\n", encoding="utf-8")
    row = _row(line=1, pattern_kind="FORMAL_NMD")
    h1 = compute_line_text_hash(read_source_line_text(tmp_path, "example.py", 1))
    py.write_text("changed\n", encoding="utf-8")
    h2 = compute_line_text_hash(read_source_line_text(tmp_path, "example.py", 1))
    assert h1 != h2


def test_line_scope_allows_not_market_data_only() -> None:
    assert line_scope_disposition_admissible("NOT_MARKET_DATA") is True
    assert line_scope_disposition_admissible("REPLACED") is False
    assert line_scope_disposition_admissible("PASS_THROUGH") is False
    assert line_scope_disposition_admissible("KEEP_DERIVED") is False
    assert line_scope_disposition_admissible("GOVERNED_EXCEPTION (O-49)") is False


def test_line_scope_blocks_wire_pattern_kinds() -> None:
    slice_row = _row(pattern_kind="FORMAL_NMD", disposition="NOT_MARKET_DATA")
    reg_wire = _row(
        register_id="w",
        disposition="UNREVIEWED",
        pattern_kind="PYTHON_GETATTR_SETATTR",
        surface_form="x",
        tokens="x",
    )
    targets, reason = _line_scope_register_targets(
        slice_row, [reg_wire], line_text_hash="abc123"
    )
    assert targets == []
    assert reason == "wire_only_line"


def test_line_scope_blocks_ambiguous_mixed_line_money_path() -> None:
    slice_row = _row(
        path="market_state.py",
        line=1006,
        pattern_kind="FORMAL_NMD",
        disposition="NOT_MARKET_DATA",
    )
    reg_lex = _row(
        register_id="l",
        disposition="UNREVIEWED",
        path="market_state.py",
        line=1006,
        pattern_kind="TEXT_LINE_MARKET_TOKEN",
    )
    reg_wire = _row(
        register_id="w",
        disposition="UNREVIEWED",
        path="market_state.py",
        line=1006,
        pattern_kind="PYTHON_GETATTR_SETATTR",
        col=20,
        surface_form="y",
        tokens="y",
    )
    targets, reason = _line_scope_register_targets(
        slice_row,
        [reg_lex, reg_wire],
        line_text_hash="abc123",
    )
    assert targets == []
    assert reason == "mixed_line_money_path_denylist"


def test_line_scope_money_path_requires_lexical_targets() -> None:
    slice_row = _row(
        path="signals.py",
        pattern_kind="FORMAL_NMD",
        disposition="NOT_MARKET_DATA",
    )
    reg = _row(
        register_id="w",
        disposition="UNREVIEWED",
        path="signals.py",
        pattern_kind="PYTHON_GETATTR_SETATTR",
        surface_form="z",
        tokens="z",
    )
    targets, reason = _line_scope_register_targets(
        slice_row, [reg], line_text_hash="abc123"
    )
    assert targets == []
    assert reason in ("wire_only_line", "money_path_no_lexical_targets")


def test_line_scope_safe_lexical_target() -> None:
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


def test_unknown_scope_fails_closed() -> None:
    row = _row(pattern_kind="", surface_form="", tokens="", notes="", v2_trace="")
    row["pattern_kind"] = ""
    row["surface_form"] = ""
    row["tokens"] = ""
    row["notes"] = ""
    row["v2_trace"] = ""
    assert classify_disposition_scope(row) == UNKNOWN_SCOPE
    assert compute_stable_semantic_key(row, UNKNOWN_SCOPE) == ""


def test_stable_key_collision_blocks_site_merge(tmp_path: Path) -> None:
    from collections import defaultdict

    reg_rows = [
        _row(register_id="r1", disposition="UNREVIEWED", col=4),
        _row(register_id="r2", disposition="UNREVIEWED", col=4),
    ]
    site_index: dict = defaultdict(list)
    for r in reg_rows:
        site_index[site_key(r)].append(r)
    stable_index: dict = {}
    ssk = compute_stable_semantic_key(_row(disposition="NOT_MARKET_DATA"), SITE_SCOPE)
    targets, reason = _site_scope_register_targets(
        _row(disposition="NOT_MARKET_DATA"),
        site_index,
        stable_index,
        ssk,
    )
    assert targets == []
    assert reason == "site_key_ambiguous"


def test_register_id_site_key_unchanged_in_production_resolver() -> None:
    reg = _row(register_id="exact_id", disposition="UNREVIEWED")
    slice_row = _row(register_id="exact_id", disposition="NOT_MARKET_DATA")
    by_id = {"exact_id": slice_row}
    sk = site_key(reg)
    by_site = {sk: slice_row}
    matched, tier = resolve_slice_row_prototype(reg, by_id, by_site, {})
    assert tier == "register_id"
    assert matched is slice_row


def test_semantic_prototype_report_writes_scratch_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = tmp_path / "reg.csv"
    slice_dir = tmp_path / "slices"
    py = tmp_path / "training_cache.py"
    py.write_text("# comment only\n", encoding="utf-8")
    reg_id = RegisterRow.make_id("training_cache.py", 1, 400, "FORMAL_NMD", "python")
    _write_csv(
        reg,
        [
            _row(
                register_id=RegisterRow.make_id(
                    "training_cache.py", 1, 4, "TEXT_LINE_MARKET_TOKEN", "python"
                ),
                path="training_cache.py",
                line=1,
                col=4,
                disposition="UNREVIEWED",
            ),
        ],
    )
    _write_csv(
        slice_dir / "training_cache_py_1_1.csv",
        [
            _row(
                register_id=reg_id,
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
    out_md = tmp_path / "semantic.md"
    summary = run_stable_semantic_prototype_analysis(
        register=reg,
        slice_dir=slice_dir,
        repo_root=tmp_path,
        summary_json=out_json,
        summary_md=out_md,
    )
    assert out_json.is_file()
    assert summary["line_scope_candidate_count"] >= 1
    assert (slice_dir / "training_cache_py_1_1.csv").exists()
