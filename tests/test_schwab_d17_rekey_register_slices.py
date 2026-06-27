"""Tests for D17 disposition-preserving register slice re-key prototype."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.d17_rekey_register_slices import (
    disposition_bundle,
    evaluate_slice_row,
    load_unreviewed_register,
    run_rekey,
    text_identity_admissible,
)
from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow


def _row(**kwargs) -> dict[str, str]:
    base = RegisterRow(
        register_id="old_id_aaaaaaaaaaaaaaa",
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


def test_text_identity_requires_fields_in_both() -> None:
    ok, reason = text_identity_admissible(
        _row(surface_form="a", tokens=""),
        _row(surface_form="a", tokens="", register_id="new"),
    )
    assert ok is True
    ok, reason = text_identity_admissible(
        _row(surface_form="", tokens=""),
        _row(surface_form="a", tokens="", register_id="new"),
    )
    assert ok is False
    assert reason == "surface_form_missing_in_slice"


def test_no_path_line_only_rekey(tmp_path: Path) -> None:
    reg = tmp_path / "reg.csv"
    reg_rows = [
        _row(
            register_id="reg_a",
            disposition="UNREVIEWED",
            pattern_kind="OTHER_KIND",
            surface_form="other",
            tokens="other",
        ),
    ]
    _write_csv(reg, reg_rows)
    _, by_strict = load_unreviewed_register(reg)
    pl_idx = {("example.py", 10): reg_rows}
    status, _, reason = evaluate_slice_row(
        _row(disposition="NOT_MARKET_DATA", pattern_kind="TEXT_LINE_MARKET_TOKEN"),
        unreviewed_by_strict=by_strict,
        path_line_unreviewed=pl_idx,
        target_claims={},
    )
    assert status == "rejected_path_line_only"
    assert reason == "path_line_only_no_strict_match"


def test_ambiguous_target_rejected(tmp_path: Path) -> None:
    reg = tmp_path / "reg.csv"
    reg_rows = [
        _row(register_id="reg_a", disposition="UNREVIEWED"),
        _row(register_id="reg_b", disposition="UNREVIEWED"),
    ]
    _write_csv(reg, reg_rows)
    _, by_strict = load_unreviewed_register(reg)
    status, _, reason = evaluate_slice_row(
        _row(disposition="NOT_MARKET_DATA"),
        unreviewed_by_strict=by_strict,
        path_line_unreviewed={("example.py", 10): reg_rows},
        target_claims={},
    )
    assert status == "ambiguous"
    assert reason == "multiple_register_candidates"


def test_conflicting_dispositions_rejected(tmp_path: Path) -> None:
    reg = tmp_path / "reg.csv"
    reg_rows = [_row(register_id="reg_a", disposition="UNREVIEWED")]
    _write_csv(reg, reg_rows)
    _, by_strict = load_unreviewed_register(reg)
    claims: dict[str, tuple[str, ...]] = {}
    s1 = _row(disposition="NOT_MARKET_DATA")
    s2 = _row(disposition="KEEP_DERIVED", notes="different")
    pl_idx = {("example.py", 10): reg_rows}
    status1, row1, _ = evaluate_slice_row(
        s1, unreviewed_by_strict=by_strict, path_line_unreviewed=pl_idx, target_claims=claims
    )
    status2, _, reason2 = evaluate_slice_row(
        s2, unreviewed_by_strict=by_strict, path_line_unreviewed=pl_idx, target_claims=claims
    )
    assert status1 == "rekey"
    assert row1 is not None
    assert status2 == "conflict"
    assert reason2 == "conflicting_dispositions_for_target"


def test_disposition_preserving_rewrite(tmp_path: Path) -> None:
    reg = tmp_path / "reg.csv"
    slice_dir = tmp_path / "slices"
    out_dir = tmp_path / "out_slices"
    new_id = RegisterRow.make_id("example.py", 10, 8, "TEXT_LINE_MARKET_TOKEN", "python")
    reg_rows = [
        _row(
            register_id=new_id,
            col=8,
            disposition="UNREVIEWED",
        ),
    ]
    _write_csv(reg, reg_rows)
    slice_row = _row(
        register_id="old_id_aaaaaaaaaaaaaaa",
        col=4,
        disposition="NOT_MARKET_DATA",
        notes="keep me",
    )
    _write_csv(slice_dir / "example.csv", [slice_row])

    summary = run_rekey(
        register=reg,
        slice_dir=slice_dir,
        out_slice_dir=out_dir,
        summary_json=tmp_path / "summary.json",
        summary_md=tmp_path / "summary.md",
        dry_run=False,
        simulate_merge=True,
    )
    assert summary["totals"]["rekeyed_rows"] == 1
    assert summary["proof"]["disposition_counts_preserved"] is True
    assert summary["proof"]["no_disposition_changes"] is True

    with (out_dir / "example.csv").open(newline="", encoding="utf-8") as f:
        out = next(csv.DictReader(f))
    assert out["register_id"] == new_id
    assert out["col"] == "8"
    assert disposition_bundle(out) == disposition_bundle(slice_row)


def test_governed_exception_oxx_preserved(tmp_path: Path) -> None:
    reg = tmp_path / "reg.csv"
    slice_dir = tmp_path / "slices"
    out_dir = tmp_path / "out_slices"
    new_id = RegisterRow.make_id("example.py", 10, 8, "TEXT_LINE_MARKET_TOKEN", "python")
    _write_csv(
        reg,
        [_row(register_id=new_id, col=8, disposition="UNREVIEWED")],
    )
    slice_row = _row(
        disposition="GOVERNED_EXCEPTION (O-49)",
        governed_ref="O-49",
        notes="n",
    )
    _write_csv(slice_dir / "ge.csv", [slice_row])
    summary = run_rekey(
        register=reg,
        slice_dir=slice_dir,
        out_slice_dir=out_dir,
        summary_json=tmp_path / "summary.json",
        summary_md=tmp_path / "summary.md",
        dry_run=False,
        simulate_merge=False,
    )
    assert summary["proof"]["governed_exception_refs_preserved"] is True
    with (out_dir / "ge.csv").open(newline="", encoding="utf-8") as f:
        out = next(csv.DictReader(f))
    assert out["governed_ref"] == "O-49"
    assert out["disposition"] == "GOVERNED_EXCEPTION (O-49)"


def test_replaced_without_pp_proof_rejected(tmp_path: Path) -> None:
    reg = tmp_path / "reg.csv"
    _write_csv(reg, [_row(register_id="reg_a", disposition="UNREVIEWED")])
    _, by_strict = load_unreviewed_register(reg)
    status, _, reason = evaluate_slice_row(
        _row(disposition="REPLACED", governed_ref=""),
        unreviewed_by_strict=by_strict,
        path_line_unreviewed={("example.py", 10): [_row(register_id="reg_a", disposition="UNREVIEWED")]},
        target_claims={},
    )
    assert status == "rejected"
    assert reason == "replaced_missing_pp_proof"


def test_dry_run_does_not_write_output(tmp_path: Path) -> None:
    reg = tmp_path / "reg.csv"
    slice_dir = tmp_path / "slices"
    out_dir = tmp_path / "out_slices"
    _write_csv(reg, [_row(register_id="reg_a", disposition="UNREVIEWED")])
    _write_csv(slice_dir / "s.csv", [_row(disposition="NOT_MARKET_DATA")])
    orig = (slice_dir / "s.csv").read_text(encoding="utf-8")
    summary = run_rekey(
        register=reg,
        slice_dir=slice_dir,
        out_slice_dir=out_dir,
        summary_json=tmp_path / "summary.json",
        summary_md=tmp_path / "summary.md",
        dry_run=True,
        simulate_merge=False,
    )
    assert summary["dry_run"] is True
    assert not out_dir.exists()
    assert not (tmp_path / "summary.json").exists()
    assert (slice_dir / "s.csv").read_text(encoding="utf-8") == orig


def test_original_slices_unchanged_after_prototype_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scratch run must not mutate governance/register_slices when using isolated fixture."""
    reg = tmp_path / "reg.csv"
    slice_dir = tmp_path / "slices"
    new_id = RegisterRow.make_id("example.py", 10, 8, "TEXT_LINE_MARKET_TOKEN", "python")
    _write_csv(reg, [_row(register_id=new_id, col=8, disposition="UNREVIEWED")])
    before = _row(disposition="NOT_MARKET_DATA")
    _write_csv(slice_dir / "s.csv", [before])
    before_text = (slice_dir / "s.csv").read_text(encoding="utf-8")
    run_rekey(
        register=reg,
        slice_dir=slice_dir,
        out_slice_dir=tmp_path / "out",
        summary_json=tmp_path / "summary.json",
        summary_md=tmp_path / "summary.md",
        dry_run=False,
        simulate_merge=False,
    )
    assert (slice_dir / "s.csv").read_text(encoding="utf-8") == before_text
