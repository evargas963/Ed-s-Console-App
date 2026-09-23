"""
No-fallback lock repair (2026-09-17): tools/research/d2_dual_label_eval_report.py's
run_cell used fillna(0) on the tb_truncated_{hz} flag before filtering -- treating an
unrecorded truncation status as proven "not truncated" rather than genuinely unknown.
Repaired to a bare comparison, which excludes NaN rows naturally via pandas' NaN != 0
semantics (mirroring SQL NULL propagation).
"""
from __future__ import annotations

import inspect

import pandas as pd


def test_no_fillna_left_in_run_cell_source():
    from tools.research import d2_dual_label_eval_report as mod

    src = inspect.getsource(mod.run_cell)
    code_only = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )
    assert "fillna" not in code_only
    assert 'tb_truncated_{hz}"] == 0' in code_only


def test_null_truncation_flag_excludes_row_not_assumed_untruncated():
    """Direct proof of the repaired filter shape: a NaN truncation flag must not pass
    the exclude_truncated filter as though it were confirmed 0 (not truncated)."""
    df = pd.DataFrame({
        "tb_truncated_5c": [0.0, 1.0, None],
    })
    filtered = df[df["tb_truncated_5c"] == 0]
    assert len(filtered) == 1, "only the confirmed-0 row may pass; NaN is not proof of 0"
