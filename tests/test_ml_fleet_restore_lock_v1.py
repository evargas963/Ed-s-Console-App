"""RC-437 — negative controls for check_rc436_closed_requires_ml_fleet_restore.

Distinguishes REPORT-ONLY ``measure_rc435_abstain_impact.py`` (exit 0 even when fleet
dark) from the ENFORCEMENT lock that blocks closing RC-436 while active triclass metas
still require structurally withheld OI/vanna wall-distance features.
"""
from __future__ import annotations

import re
from pathlib import Path

import tools.check_institutional_correctness as C
from tools import ml_fleet_restore_lock as L

REPO = Path(__file__).resolve().parents[1]
LOG = REPO / "governance" / "root_cause_log.md"


def test_measure_tool_is_report_only_and_exits_zero():
    """REPORT-ONLY contract: banner present; completing a dark-fleet measure exits 0."""
    src = (REPO / "tools" / "measure_rc435_abstain_impact.py").read_text(encoding="utf-8")
    assert "REPORT-ONLY" in src or "REPORT_ONLY" in src
    assert "ml_fleet_restore_lock" in src
    assert "return 0" in src
    # Live measure must not fail the process when the fleet is dark.
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
    """ENFORCED check id must appear in tests corpus (RC-95 name-presence proxy)."""
    assert "rc436_closed_requires_ml_fleet_restore" in (
        Path(__file__).read_text(encoding="utf-8")
    )
    names = {name for name, _fn, enforced in C.CHECKS if enforced}
    assert "rc436_closed_requires_ml_fleet_restore" in names


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


def test_rc436_row_still_open_in_live_ledger():
    """Operator law: do not close RC-436 until live ML restore is proven."""
    text = LOG.read_text(encoding="utf-8")
    m = re.search(r"^\|\s*RC-436\s*\|\s*(\w+)\s*\|", text, re.M)
    assert m is not None
    assert m.group(1) == "OPEN"
