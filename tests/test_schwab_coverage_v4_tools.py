"""V4 Deliverables 17–18 — metrics JSON + O-XX validator + register slice merge."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.schwab_coverage_v4_metrics import compute_full_metrics
from tools.schwab_oxx_validator import validate_register_messages, validate_replaced_perf_bindings
from tools.stream_revert_v4_register_and_sync_perf import (
    export_register_baseline,
    is_canonical_v4_register,
    merge_register_slices,
    site_key,
    update_register_meta_if_canonical,
)
from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow


def _op_with_narrative(oxx: str = "O-77") -> str:
    return (
        f"# Op\n\n### {oxx}\n\n"
        "Why: Unit test narrative for coverage tooling.\n\n"
        "Constraint: Synthetic fixture only.\n\n"
        "Permanent or interim: Interim until 2099-12-31.\n"
    )


def test_v4_metrics_json_shape(tmp_path: Path) -> None:
    import csv

    from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

    op = tmp_path / "op.md"
    op.write_text(_op_with_narrative("O-77"), encoding="utf-8")
    reg = tmp_path / "r.csv"
    base = RegisterRow(
        register_id="x",
        language="python",
        path="p.py",
        line=1,
        col=0,
        pattern_kind="T",
        surface_form="",
        tokens="",
        csv_candidates="",
        csv_lexical_topk_note="",
        v2_trace="",
    )
    rows = [
        RegisterRow(**{**base.as_csv_dict(), "register_id": "a", "disposition": "REPLACED"}),
        RegisterRow(
            **{
                **base.as_csv_dict(),
                "register_id": "b",
                "disposition": "GOVERNED_EXCEPTION (O-77)",
                "governed_ref": "O-77",
            }
        ),
        RegisterRow(
            **{
                **base.as_csv_dict(),
                "register_id": "c",
                "disposition": "GOVERNED_EXCEPTION",
                "governed_ref": "",
            }
        ),
        RegisterRow(
            **{
                **base.as_csv_dict(),
                "register_id": "d",
                "disposition": "UNREVIEWED",
            }
        ),
    ]
    with reg.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r.as_csv_dict())

    m = compute_full_metrics(reg, op)
    assert m["replaced_count"] == 1
    assert m["governed_exception_with_oxx_count"] == 1
    assert m["bare_governed_exception_count"] == 1
    assert m["unreviewed_count"] == 1
    assert m["closure_admissible"] is False
    assert "c" in m["v4_a_violations"]


def test_oxx_validator_pass_and_fail(tmp_path: Path) -> None:
    op = tmp_path / "op.md"
    op.write_text(_op_with_narrative("O-88"), encoding="utf-8")
    import csv

    from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

    def _row(**kw: str) -> RegisterRow:
        d = RegisterRow(
            register_id="x",
            language="python",
            path="p.py",
            line=1,
            col=0,
            pattern_kind="T",
            surface_form="",
            tokens="",
            csv_candidates="",
            csv_lexical_topk_note="",
            v2_trace="",
        ).as_csv_dict()
        d.update(kw)
        return RegisterRow(**{k: d[k] for k in REGISTER_COLUMNS})

    reg_ok = tmp_path / "ok.csv"
    with reg_ok.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(
            _row(
                disposition="GOVERNED_EXCEPTION (O-88)",
                governed_ref="O-88",
            ).as_csv_dict()
        )
    assert validate_register_messages(reg_ok, op) == []

    reg_bad = tmp_path / "bad.csv"
    with reg_bad.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(_row(disposition="GOVERNED_EXCEPTION", governed_ref="").as_csv_dict())
    assert len(validate_register_messages(reg_bad, op)) >= 1


def test_v4_metrics_module_exit_code(tmp_path: Path) -> None:
    op = tmp_path / "op.md"
    op.write_text(_op_with_narrative("O-91"), encoding="utf-8")
    import csv

    from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

    reg = tmp_path / "r.csv"
    r0 = RegisterRow(
        register_id="z",
        language="python",
        path="p.py",
        line=1,
        col=0,
        pattern_kind="T",
        surface_form="",
        tokens="",
        csv_candidates="",
        csv_lexical_topk_note="",
        v2_trace="",
        disposition="GOVERNED_EXCEPTION (O-91)",
        governed_ref="O-91",
    )
    with reg.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(r0.as_csv_dict())

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.schwab_coverage_v4_metrics",
            "--register",
            str(reg),
            "--operator-register",
            str(op),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["bare_governed_exception_count"] == 0


def test_oxx_validator_subprocess(tmp_path: Path) -> None:
    op = tmp_path / "op.md"
    op.write_text(_op_with_narrative("O-92"), encoding="utf-8")
    import csv

    from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

    reg = tmp_path / "r.csv"
    r0 = RegisterRow(
        register_id="z",
        language="python",
        path="p.py",
        line=1,
        col=0,
        pattern_kind="T",
        surface_form="",
        tokens="",
        csv_candidates="",
        csv_lexical_topk_note="",
        v2_trace="",
        disposition="GOVERNED_EXCEPTION (O-92)",
        governed_ref="O-92",
    )
    with reg.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(r0.as_csv_dict())
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.schwab_oxx_validator",
            "--register",
            str(reg),
            "--operator-register",
            str(op),
            "--perf-dir",
            str(tmp_path / "empty_perf"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_register_slice_merge_by_site_key(tmp_path: Path) -> None:
    reg = tmp_path / "reg.csv"
    slice_dir = tmp_path / "slices"
    slice_dir.mkdir()
    base = RegisterRow(
        register_id="rid1",
        language="python",
        path="server.py",
        line=10,
        col=0,
        pattern_kind="TEXT_LINE_MARKET_TOKEN",
        surface_form="bid",
        tokens="bid",
        csv_candidates="",
        csv_lexical_topk_note="",
        v2_trace="",
        disposition="UNREVIEWED",
    )
    with reg.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(base.as_csv_dict())
    merged = RegisterRow(
        **{
            **base.as_csv_dict(),
            "disposition": "REPLACED",
            "canonical_field_citation": "quotes.quote.bidPrice",
            "notes": "slice merge test",
        }
    )
    with (slice_dir / "server_py.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(merged.as_csv_dict())
    rep = merge_register_slices(reg, slice_dir, dry_run=False)
    assert rep["rows_updated"] == 1
    row = next(csv.DictReader(reg.open(encoding="utf-8")))
    assert row["disposition"] == "REPLACED"
    assert row["canonical_field_citation"] == "quotes.quote.bidPrice"


def test_merge_slices_does_not_update_global_meta_for_tmp_register(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = tmp_path / "meta.json"
    meta.write_text(
        json.dumps(
            {
                "register_content_sha256": "deadbeef",
                "register_rows_written": 999999,
                "register_size_bytes": 123,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "tools.stream_revert_v4_register_and_sync_perf.META_PATH",
        meta,
    )
    reg = tmp_path / "reg.csv"
    slice_dir = tmp_path / "slices"
    slice_dir.mkdir()
    base = RegisterRow(
        register_id="rid1",
        language="python",
        path="server.py",
        line=10,
        col=0,
        pattern_kind="TEXT_LINE_MARKET_TOKEN",
        surface_form="bid",
        tokens="bid",
        csv_candidates="",
        csv_lexical_topk_note="",
        v2_trace="",
        disposition="UNREVIEWED",
    )
    with reg.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(base.as_csv_dict())
    merged = RegisterRow(
        **{
            **base.as_csv_dict(),
            "disposition": "REPLACED",
            "canonical_field_citation": "quotes.quote.bidPrice",
        }
    )
    with (slice_dir / "server_py.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(merged.as_csv_dict())
    assert not is_canonical_v4_register(reg)
    merge_register_slices(reg, slice_dir, dry_run=False)
    doc = json.loads(meta.read_text(encoding="utf-8"))
    assert doc["register_rows_written"] == 999999
    assert doc["register_content_sha256"] == "deadbeef"


def test_update_register_meta_if_canonical_skips_tmp_register(tmp_path: Path) -> None:
    reg = tmp_path / "reg.csv"
    reg.write_text("register_id\nx\n", encoding="utf-8")
    assert (
        update_register_meta_if_canonical(reg, "abc", 3, 1) is False
    )


def test_export_register_baseline_filters_path_and_lines(tmp_path: Path) -> None:
    reg = tmp_path / "reg.csv"
    out = tmp_path / "base.csv"
    rows = [
        RegisterRow(
            register_id="a",
            language="python",
            path="call_engine.py",
            line=5,
            col=0,
            pattern_kind="T",
            surface_form="",
            tokens="",
            csv_candidates="",
            csv_lexical_topk_note="",
            v2_trace="",
        ),
        RegisterRow(
            register_id="b",
            language="python",
            path="call_engine.py",
            line=999,
            col=0,
            pattern_kind="T",
            surface_form="",
            tokens="",
            csv_candidates="",
            csv_lexical_topk_note="",
            v2_trace="",
        ),
    ]
    with reg.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r.as_csv_dict())
    n = export_register_baseline(reg, path="call_engine.py", line_lo=1, line_hi=100, out=out)
    assert n == 1
    exported = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(exported) == 1
    assert exported[0]["register_id"] == "a"


def test_replaced_perf_binding_validator_pass_and_fail(tmp_path: Path) -> None:
    op = tmp_path / "op.md"
    op.write_text(_op_with_narrative("O-93"), encoding="utf-8")
    perf_dir = tmp_path / "perf"
    perf_dir.mkdir()
    proof_name = "pp_v4b_test_leaf_provenance.json"
    proof_path = perf_dir / proof_name
    proof_path.write_text(
        json.dumps(
            {
                "perf_proof_id": "pp_v4b_test_leaf_provenance",
                "register_link": {"status": "bound", "replaced_register_ids": ["rid_ok"]},
            }
        ),
        encoding="utf-8",
    )
    gov_ref = f"governance/artifacts/perf_proof/replacements/{proof_name}"

    def _row(**kw: str) -> dict[str, str]:
        d = RegisterRow(
            register_id="rid_ok",
            language="python",
            path="p.py",
            line=1,
            col=0,
            pattern_kind="T",
            surface_form="",
            tokens="",
            csv_candidates="",
            csv_lexical_topk_note="",
            v2_trace="",
            disposition="REPLACED",
            canonical_field_citation="quotes.quote.lastPrice",
            governed_ref=gov_ref,
        ).as_csv_dict()
        d.update(kw)
        return d

    reg_ok = tmp_path / "ok.csv"
    with reg_ok.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(_row())

    assert validate_replaced_perf_bindings(reg_ok, perf_dir) == []

    reg_bad = tmp_path / "bad.csv"
    with reg_bad.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(_row(governed_ref="", register_id="rid_bad"))

    msgs = validate_replaced_perf_bindings(reg_bad, perf_dir)
    assert any("governed_ref" in m for m in msgs)


def test_site_key_normalizes_path() -> None:
    k = site_key(
        {
            "path": "server.py",
            "line": "1",
            "col": "0",
            "pattern_kind": "T",
            "language": "python",
        }
    )
    assert k == ("server.py", 1, 0, "T", "python")


def _write_reg(path: Path, rows: list[RegisterRow]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r.as_csv_dict())


def test_slice_merge_refuses_on_surface_form_mismatch(tmp_path: Path) -> None:
    """CONTENT-BINDING lock (2026-07-15 root cause): register_id and site_key hash
    coordinates, never content — after source lines shift, DIFFERENT code occupies
    reviewed coordinates. A slice disposition must apply only when the reviewed
    surface_form byte-equals the current row's; observed at scale pre-fix: 4,903
    register rows carried dispositions for code that was never reviewed, including
    a bidPrice read classified NOT_MARKET_DATA from an old _vix_tracker row."""
    reg = tmp_path / "reg.csv"
    slice_dir = tmp_path / "slices"
    slice_dir.mkdir()
    current = RegisterRow(
        register_id="rid1",
        language="python",
        path="server.py",
        line=10,
        col=0,
        pattern_kind="TEXT_LINE_MARKET_TOKEN",
        surface_form='bid = _safe_float_quote(_q.get("bidPrice"))',
        tokens="bid",
        csv_candidates="",
        csv_lexical_topk_note="",
        v2_trace="",
        disposition="UNREVIEWED",
    )
    _write_reg(reg, [current])
    # same register_id AND same site coordinates, but the REVIEWED content differs
    reviewed_other_code = RegisterRow(
        **{
            **current.as_csv_dict(),
            "surface_form": "_vix_tracker.tick(float(mkt_ctx.vix))",
            "disposition": "NOT_MARKET_DATA",
            "notes": "reviewed when different code occupied this line",
        }
    )
    with (slice_dir / "server_py.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(reviewed_other_code.as_csv_dict())
    rep = merge_register_slices(reg, slice_dir, dry_run=False)
    assert rep["rows_updated"] == 0
    row = next(csv.DictReader(reg.open(encoding="utf-8")))
    assert row["disposition"] == "UNREVIEWED", (
        "a coordinate-matched slice row with different reviewed content must never "
        "disposition the current code (fail closed to UNREVIEWED)"
    )


def test_slice_merge_applies_on_exact_surface_match(tmp_path: Path) -> None:
    """Complement lock: identical reviewed content at the same identity still merges."""
    reg = tmp_path / "reg.csv"
    slice_dir = tmp_path / "slices"
    slice_dir.mkdir()
    current = RegisterRow(
        register_id="rid1",
        language="python",
        path="server.py",
        line=10,
        col=0,
        pattern_kind="TEXT_LINE_MARKET_TOKEN",
        surface_form='bid = _safe_float_quote(_q.get("bidPrice"))',
        tokens="bid",
        csv_candidates="",
        csv_lexical_topk_note="",
        v2_trace="",
        disposition="UNREVIEWED",
    )
    _write_reg(reg, [current])
    reviewed_same = RegisterRow(
        **{
            **current.as_csv_dict(),
            "disposition": "REPLACED",
            "canonical_field_citation": "quotes.quote.bidPrice",
        }
    )
    with (slice_dir / "server_py.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(reviewed_same.as_csv_dict())
    rep = merge_register_slices(reg, slice_dir, dry_run=False)
    assert rep["rows_updated"] == 1
    row = next(csv.DictReader(reg.open(encoding="utf-8")))
    assert row["disposition"] == "REPLACED"


def test_slice_merge_id_collision_resolved_by_content(tmp_path: Path) -> None:
    """Identity-collision lock: when two slice generations claim the SAME
    register_id (a stale row reviewed for code that used to occupy the
    coordinates + a rekeyed row for the current code), the content-matching
    claimant applies and the stale one can never shadow it by load order."""
    reg = tmp_path / "reg.csv"
    slice_dir = tmp_path / "slices"
    slice_dir.mkdir()
    current = RegisterRow(
        register_id="rid_shared",
        language="py",
        path="server.py",
        line=4810,
        col=0,
        pattern_kind="TEXT_LINE_MARKET_TOKEN",
        surface_form='bid = _safe_float_quote(_q.get("bidPrice"))',
        tokens="bid",
        csv_candidates="",
        csv_lexical_topk_note="",
        v2_trace="",
        disposition="UNREVIEWED",
    )
    _write_reg(reg, [current])
    rekeyed = RegisterRow(
        **{
            **current.as_csv_dict(),
            "disposition": "REPLACED",
            "canonical_field_citation": "quotes.quote.bidPrice",
            "governed_ref": "governance/artifacts/perf_proof/replacements/pp_x.json",
        }
    )
    stale_other_code = RegisterRow(
        **{
            **current.as_csv_dict(),
            "surface_form": "_vix_tracker.tick(float(mkt_ctx.vix))",
            "disposition": "NOT_MARKET_DATA",
        }
    )
    # the stale claimant lives in a slice file that sorts AFTER the rekeyed one:
    # last-writer-wins map semantics would shadow the rekeyed row
    with (slice_dir / "a_rekeyed.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(rekeyed.as_csv_dict())
    with (slice_dir / "z_stale.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(stale_other_code.as_csv_dict())
    rep = merge_register_slices(reg, slice_dir, dry_run=False)
    assert rep["rows_updated"] == 1
    row = next(csv.DictReader(reg.open(encoding="utf-8")))
    assert row["disposition"] == "REPLACED"
    assert row["canonical_field_citation"] == "quotes.quote.bidPrice"


@pytest.mark.parametrize("order", ["rekeyed_first", "stale_first"])
def test_conflicting_same_surface_dispositions_fail_closed(tmp_path: Path, order: str) -> None:
    """Conflict lock: two claimants with the SAME reviewed surface but CONFLICTING
    dispositions must fail closed to UNREVIEWED — and claimant load order (slice
    file name sort) must not change the result."""
    reg = tmp_path / "reg.csv"
    slice_dir = tmp_path / "slices"
    slice_dir.mkdir()
    current = RegisterRow(
        register_id="rid_c",
        language="py",
        path="server.py",
        line=100,
        col=0,
        pattern_kind="TEXT_LINE_MARKET_TOKEN",
        surface_form="ask = q.get('askPrice')",
        tokens="ask",
        csv_candidates="",
        csv_lexical_topk_note="",
        v2_trace="",
        disposition="UNREVIEWED",
    )
    _write_reg(reg, [current])
    claim_a = RegisterRow(**{**current.as_csv_dict(), "disposition": "REPLACED",
                             "governed_ref": "governance/artifacts/perf_proof/replacements/pp_a.json"})
    claim_b = RegisterRow(**{**current.as_csv_dict(), "disposition": "NOT_MARKET_DATA"})
    first, second = (claim_a, claim_b) if order == "rekeyed_first" else (claim_b, claim_a)
    for name, row in (("a_first.csv", first), ("z_second.csv", second)):
        with (slice_dir / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
            w.writeheader()
            w.writerow(row.as_csv_dict())
    rep = merge_register_slices(reg, slice_dir, dry_run=False)
    assert rep["rows_updated"] == 0
    row = next(csv.DictReader(reg.open(encoding="utf-8")))
    assert row["disposition"] == "UNREVIEWED", (
        "conflicting same-surface reviewed claims must never silently apply"
    )


def test_empty_surface_claims_never_inherit(tmp_path: Path) -> None:
    """Empty-surface lock: a historical claimant with an EMPTY surface_form has no
    content identity — even a register_id + coordinate + empty-vs-empty match must
    fail closed (otherwise identity degrades to coordinates, the PR-#41 class)."""
    reg = tmp_path / "reg.csv"
    slice_dir = tmp_path / "slices"
    slice_dir.mkdir()
    current = RegisterRow(
        register_id="rid_e",
        language="py",
        path="server.py",
        line=7,
        col=0,
        pattern_kind="T",
        surface_form="",
        tokens="",
        csv_candidates="",
        csv_lexical_topk_note="",
        v2_trace="",
        disposition="UNREVIEWED",
    )
    _write_reg(reg, [current])
    claim = RegisterRow(**{**current.as_csv_dict(), "disposition": "NOT_MARKET_DATA"})
    with (slice_dir / "s.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(claim.as_csv_dict())
    rep = merge_register_slices(reg, slice_dir, dry_run=False)
    assert rep["rows_updated"] == 0
    row = next(csv.DictReader(reg.open(encoding="utf-8")))
    assert row["disposition"] == "UNREVIEWED"


def test_merge_slices_auto_syncs_perf_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Universal-sync lock: merging slices into the CANONICAL register must
    re-derive every pp_*.json register_link in the same operation — no supported
    path may leave stale links behind (the PR-#41 incident class)."""
    import tools.stream_revert_v4_register_and_sync_perf as srv

    reg = tmp_path / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
    perf_dir = tmp_path / "perf"
    perf_dir.mkdir()
    meta = tmp_path / "meta.json"
    meta.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(srv, "DEFAULT_REGISTER", reg)
    monkeypatch.setattr(srv, "PERF_DIR", perf_dir)
    monkeypatch.setattr(srv, "META_PATH", meta)
    proof_name = "pp_v4b_autosync_test.json"
    (perf_dir / proof_name).write_text(
        json.dumps({"register_link": {"status": "unbound", "replaced_register_ids": []}}),
        encoding="utf-8",
    )
    gov_ref = f"governance/artifacts/perf_proof/replacements/{proof_name}"
    current = RegisterRow(
        register_id="rid_s",
        language="py",
        path="server.py",
        line=5,
        col=0,
        pattern_kind="T",
        surface_form="bid = q.get('bidPrice')",
        tokens="bid",
        csv_candidates="",
        csv_lexical_topk_note="",
        v2_trace="",
        disposition="UNREVIEWED",
    )
    _write_reg(reg, [current])
    claim = RegisterRow(**{**current.as_csv_dict(), "disposition": "REPLACED",
                           "canonical_field_citation": "quotes.quote.bidPrice",
                           "governed_ref": gov_ref})
    slice_dir = tmp_path / "slices"
    slice_dir.mkdir()
    with (slice_dir / "s.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerow(claim.as_csv_dict())
    rep = srv.merge_register_slices(reg, slice_dir, dry_run=False)
    assert rep["rows_updated"] == 1
    assert rep.get("perf_links_synced") is True
    doc = json.loads((perf_dir / proof_name).read_text(encoding="utf-8"))
    assert doc["register_link"]["status"] == "bound"
    assert doc["register_link"]["replaced_register_ids"] == ["rid_s"]


def test_oxx_validator_replaced_perf_only_flag(tmp_path: Path) -> None:
    """--replaced-perf-only validates ONLY the pp binding (PR-time gate): a bare
    GOVERNED_EXCEPTION row that fails full mode must not fail this mode, while a
    stale register_link still must."""
    op = tmp_path / "op.md"
    op.write_text(_op_with_narrative("O-94"), encoding="utf-8")
    perf_dir = tmp_path / "perf"
    perf_dir.mkdir()
    proof_name = "pp_v4b_flag_test.json"
    (perf_dir / proof_name).write_text(
        json.dumps({"register_link": {"status": "bound", "replaced_register_ids": ["rid_ok"]}}),
        encoding="utf-8",
    )
    gov_ref = f"governance/artifacts/perf_proof/replacements/{proof_name}"
    rows = [
        RegisterRow(
            register_id="rid_ok", language="python", path="p.py", line=1, col=0,
            pattern_kind="T", surface_form="", tokens="", csv_candidates="",
            csv_lexical_topk_note="", v2_trace="",
            disposition="REPLACED", canonical_field_citation="quotes.quote.lastPrice",
            governed_ref=gov_ref,
        ),
        RegisterRow(
            register_id="rid_bare", language="python", path="p.py", line=2, col=0,
            pattern_kind="T", surface_form="", tokens="", csv_candidates="",
            csv_lexical_topk_note="", v2_trace="",
            disposition="GOVERNED_EXCEPTION", governed_ref="",
        ),
    ]
    reg = tmp_path / "r.csv"
    _write_reg(reg, rows)
    root = Path(__file__).resolve().parents[1]

    def _run(*extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "tools.schwab_oxx_validator",
             "--register", str(reg), "--operator-register", str(op),
             "--perf-dir", str(perf_dir), *extra],
            cwd=root, capture_output=True, text=True, check=False,
        )

    assert _run().returncode == 1  # full mode: bare GOVERNED_EXCEPTION fails
    assert _run("--replaced-perf-only").returncode == 0  # binding coherent
    # now break the binding: link cites an id that is not REPLACED
    (perf_dir / proof_name).write_text(
        json.dumps({"register_link": {"status": "bound",
                                      "replaced_register_ids": ["rid_ok", "rid_stale"]}}),
        encoding="utf-8",
    )
    assert _run("--replaced-perf-only").returncode == 1
    # the legacy --skip-replaced-perf escape is removed: an unknown flag must
    # refuse loudly (argparse exit 2), never silently narrow validation
    assert _run("--skip-replaced-perf").returncode == 2
