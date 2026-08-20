"""RC-437 — negative controls for check_rc436_closed_requires_ml_fleet_restore.

Distinguishes REPORT-ONLY ``measure_rc435_abstain_impact.py`` (exit 0 even when fleet
dark) from the ENFORCEMENT lock that blocks closing RC-436 while active triclass metas
still require structurally withheld OI/vanna wall-distance features.
"""
from __future__ import annotations

from pathlib import Path

import tools.check_institutional_correctness as C
from tools import ml_fleet_restore_lock as L

REPO = Path(__file__).resolve().parents[1]


def test_measure_tool_is_report_only_and_exits_zero():
    """REPORT-ONLY contract: completing a dark-fleet measure exits 0 with banner."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, str(REPO / "tools" / "measure_rc435_abstain_impact.py")],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "REPORT_ONLY=1" in proc.stdout
    assert "ml_fleet_restore_lock" in proc.stdout
    assert "prove_path_a_ml_restore" in proc.stdout
    assert "require_withheld=" in proc.stdout


def test_live_open_rc436_passes_restore_lock():
    """Live ledger keeps RC-436 OPEN while fleet still requires withheld features."""
    assert L.rc436_status(REPO) == "OPEN"
    assert L.active_triclass_metas_requiring_withheld(REPO), (
        "expected live active metas to still list withheld *_pct (RC-436)"
    )
    assert L.violations(REPO) == []
    assert C.check_rc436_closed_requires_ml_fleet_restore() == []


def test_negative_control_closed_rc436_while_fleet_dark_blocks(tmp_path):
    """Injected CLOSED RC-436 against a withheld-feature fleet must scream."""
    active_src = REPO / "models" / "active"
    assert active_src.is_dir()
    # Minimal repo: CLOSED RC-436 + copy one real meta that requires withheld features.
    gov = tmp_path / "governance"
    gov.mkdir()
    metas = L.active_triclass_metas_requiring_withheld(REPO)
    assert metas, "need at least one live withheld meta as the injection target"
    sample_rel = metas[0]
    sample_src = REPO / sample_rel
    dest = tmp_path / sample_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(sample_src.read_bytes())
    row = (
        "| RC-436 | CLOSED | 2026-08-20 | 2026-08-27 | fake close | "
        "a -> b -> c -> d -> e ROOT: fake | "
        "FIXED: claimed restore without Path-A artifacts. END-TO-END. |\n"
    )
    (gov / "root_cause_log.md").write_text(row, encoding="utf-8")
    bad = L.violations(tmp_path)
    assert len(bad) >= 1
    assert "RC-436 CLOSED" in bad[0]
    assert "withheld" in bad[0].lower()


def test_negative_control_registered_check_name_present_for_meta_gate():
    """ENFORCED check id is registered (RC-95 name-presence via CHECKS roster)."""
    names = {name for name, _fn, enforced in C.CHECKS if enforced}
    assert "rc436_closed_requires_ml_fleet_restore" in names
    # Name-presence proxy for check_enforced_checks_have_negative_controls:
    assert any(
        name == "rc436_closed_requires_ml_fleet_restore" for name, _fn, _en in C.CHECKS
    )


def test_closed_rc436_with_clean_metas_passes(tmp_path):
    """After Path-A promote (no withheld names in metas), CLOSED RC-436 is legal."""
    gov = tmp_path / "governance"
    gov.mkdir()
    (gov / "root_cause_log.md").write_text(
        "| RC-436 | CLOSED | 2026-08-20 | 2026-08-27 | restored | "
        "a -> b -> c -> d -> e ROOT: path A | "
        "FIXED: Path-A artifacts. END-TO-END. |\n",
        encoding="utf-8",
    )
    meta_dir = tmp_path / "models" / "active" / "SPY"
    meta_dir.mkdir(parents=True)
    meta_dir.joinpath("xgb_SPY_1c_meta.json").write_text(
        '{"features": ["dist_call_gamma_wall_pct", "dist_put_gamma_wall_pct"]}\n',
        encoding="utf-8",
    )
    assert L.violations(tmp_path) == []


def test_prove_path_a_restore_exits_nonzero_while_fleet_dark():
    """Host E2E prove script must FAIL until Path-A artifacts land (not REPORT-ONLY)."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, str(REPO / "tools" / "prove_path_a_ml_restore.py")],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "NOT_RESTORED" in proc.stdout or "NOT_RESTORED" in proc.stderr


def test_prove_require_stack_probs_wires_real_unified_stack_not_missing_helper():
    """--require-stack-probs must call predict_direction, not a nonexistent probe helper.

    OUT-OF-SCOPE: claiming STACK_PROBS_RESTORED while the fleet is still dark — this
    lock only proves the host acceptance surface is executable (no AttributeError /
    soft-pass on a missing ml_predict.probe_unified_stack_probs).
    """
    import re
    import subprocess
    import sys

    src = (REPO / "tools" / "prove_path_a_ml_restore.py").read_text(encoding="utf-8")
    # Must not call a nonexistent helper (comment mentions of the old name are OK).
    assert "getattr(ml_predict, \"probe_unified_stack_probs\"" not in src
    assert "probe_unified_stack_probs(" not in src
    assert re.search(r"from ml_predict import predict_direction", src)
    assert "run_unified_stack_ml_once" in src
    assert "stack_probs_triplet_complete" in src

    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "tools" / "prove_path_a_ml_restore.py"),
            "--require-stack-probs",
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "stack_probe:" in out
    assert "AttributeError" not in out
    assert "no ml_predict.probe_unified_stack_probs" not in out


def test_stack_probs_probe_reaches_predict_direction_on_real_snapshot_row(tmp_path):
    """With one Collect snapshot row, the probe must hit the live unified stack authority.

    Expect honest fail (stack_probs=None) while RC-436 fleet is dark — not a missing
    helper, and not a synthetic green.
    """
    import os
    import shutil
    import sqlite3
    import time

    from tools.prove_path_a_ml_restore import _stack_probs_via_unified_stack

    src_db = REPO / "data" / "ed_console.db"
    assert src_db.is_file()
    dbp = tmp_path / "ed_console.db"
    shutil.copy2(src_db, dbp)
    conn = sqlite3.connect(dbp)
    try:
        conn.execute(
            "INSERT INTO snapshots_1m_normalized (ticker, ts_utc) VALUES (?, ?)",
            ("SPY", time.time()),
        )
        conn.commit()
    finally:
        conn.close()

    prev = os.environ.get("ED_CONSOLE_ALLOW_NONCANONICAL_DB")
    os.environ["ED_CONSOLE_ALLOW_NONCANONICAL_DB"] = "1"
    try:
        ok, detail = _stack_probs_via_unified_stack("SPY", db_path=dbp)
    finally:
        if prev is None:
            os.environ.pop("ED_CONSOLE_ALLOW_NONCANONICAL_DB", None)
        else:
            os.environ["ED_CONSOLE_ALLOW_NONCANONICAL_DB"] = prev

    assert ok is False
    assert "predict_direction" in detail or "run_unified_stack_ml_once" in detail
    assert "stack_probs" in detail
    assert "probe_unified_stack_probs" not in detail
