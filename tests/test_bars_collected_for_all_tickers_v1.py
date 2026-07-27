"""RC-69: the 1-minute accumulator must build bars from the collection service's call shape.

SUPERSEDED SCOPE NOTE: an earlier version of this file asserted that
`_base_money_path_capture_one` fed and persisted bars. That was a WRONG FIX — it moved bar
collection from one capture path to another instead of making it a service, leaving collection
riding a snapshot writer and covering only the 3 sentinel tickers of 57 enrolled. The
architecture assertions now live in tests/test_bars_collection_service_v1.py; what remains here
is the numeric contract of the accumulator itself.
"""
from __future__ import annotations


def test_accumulator_builds_bars_from_collection_service_call_shape():
    """Drive the REAL accumulator exactly as _bars_collect_one calls it
    (ticker, price, ts, total_volume=) and prove completed bars appear."""
    import os

    os.environ.setdefault("PYTEST_CURRENT_TEST", "rc69")
    import server as srv

    tk = "ZZRC69"
    base = 1_785_168_000.0
    for i, px in enumerate((740.0, 740.5, 741.0, 740.8)):
        srv._candles_1m.tick(tk, px, base + i * 60, total_volume=1000 * (i + 1))
    bars = srv._candles_1m.get_bars(tk)
    assert len(bars) >= 3, f"expected completed bars from sequential ticks, got {len(bars)}"
    assert bars[0].open == 740.0


def test_accumulator_rejects_a_nonpositive_price_at_the_service_boundary():
    """_bars_collect_one refuses to tick on a missing/zero price — absence must read as absence,
    never a fabricated bar. This locks the guard's presence at the seam."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    seg = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_bars_collect_one":
            seg = ast.get_source_segment(src, node) or ""
    assert seg, "_bars_collect_one not found"
    assert "float(px) <= 0" in seg and "skip:no_price" in seg
