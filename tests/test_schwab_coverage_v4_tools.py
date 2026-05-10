"""V4 Deliverables 17–18 — metrics JSON + O-XX validator."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.schwab_coverage_v4_metrics import compute_full_metrics
from tools.schwab_oxx_validator import validate_register_messages


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
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
