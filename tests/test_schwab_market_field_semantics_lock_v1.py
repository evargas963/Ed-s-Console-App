"""Negative control for the enforced check `schwab_market_field_semantics` (RC-440; M4/M5).

Green-and-inert is byte-identical to green-and-working, so this test INJECTS each defect
the lock exists to catch and asserts it fires — and proves the reasoned marker suppresses.

M4: NUM_BIDS/NUM_ASKS labeled an order/market-maker count (vendor meaning NOT_PROVEN).
M5: exchange_quote_ts assigned a server wall clock (it must carry the exchange quote clock).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_schwab_market_field_semantics import scan_file
import tools.check_institutional_correctness as cic


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_num_bids_labeled_order_count_is_blocked(tmp_path):
    p = _write(tmp_path, "m4.py", 'depth = level["NUM_BIDS"]  # order count at this level\n')
    kinds = [k for _ln, k, _c in scan_file(p)]
    assert "num_order_count" in kinds


def test_num_asks_market_maker_count_is_blocked(tmp_path):
    p = _write(tmp_path, "m4b.py", 'n = row["NUM_ASKS"]  # market-maker count\n')
    kinds = [k for _ln, k, _c in scan_file(p)]
    assert "num_order_count" in kinds


def test_exchange_quote_ts_from_wall_clock_is_blocked(tmp_path):
    p = _write(tmp_path, "m5.py", '    out = {"exchange_quote_ts": time.time()}\n')
    kinds = [k for _ln, k, _c in scan_file(p)]
    assert "exchange_quote_ts_wallclock" in kinds


def test_exchange_quote_ts_from_server_received_ts_is_blocked(tmp_path):
    p = _write(tmp_path, "m5b.py", "    exchange_quote_ts = server_received_ts\n")
    kinds = [k for _ln, k, _c in scan_file(p)]
    assert "exchange_quote_ts_wallclock" in kinds


def test_truthful_usage_is_clean(tmp_path):
    """The real producer shape: exchange_quote_ts = exchange quote clock; NUM_* neutral."""
    body = (
        '    out = {"exchange_quote_ts": quote_ts}  # exchange QUOTE_TIME_MILLIS/sec\n'
        '    server_received_ts = time.time()\n'
        '    venue_count = level["NUM_BIDS"]  # count of nested per-exchange rows\n'
    )
    p = _write(tmp_path, "clean.py", body)
    assert scan_file(p) == []


def test_reasoned_markers_suppress(tmp_path):
    body = (
        '    n = row["NUM_BIDS"]  # order count  # num-semantics-ok: vendor spec §4 proves it\n'
        '    exchange_quote_ts = time.time()  # exchange-quote-ts-ok: unit-test synthetic clock\n'
    )
    p = _write(tmp_path, "marked.py", body)
    assert scan_file(p) == []


def test_check_is_registered_enforced():
    ids = {name for name, _fn, enforced in cic.CHECKS if enforced}
    assert "schwab_market_field_semantics" in ids


def test_gate_wrapper_runs_clean_on_current_tree():
    # The wrapper over the whole repo must be clean now (the audit closed M4/M5).
    assert cic.check_schwab_market_field_semantics() == []
