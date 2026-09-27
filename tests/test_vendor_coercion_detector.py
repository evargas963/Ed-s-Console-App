"""The vendor-field check (tools/check_vendor_field_coercion.py) flags every shape of Schwab field
read that let a bad value through, passes the two Schwab readers, and is clean on the repository.

Flag cases are the failures that happened: raw float() admitting NaN (2026-07-25), and the older
readers and their delegates admitting -999 / text and dropping a reported 0 (2026-09-27).
"""
from __future__ import annotations

import pytest

from tools.check_vendor_field_coercion import scan_source, violations

SHOULD_FLAG = {
    "raw_float": 'x = float(ct.get("strikePrice"))',
    "raw_subscript": 'x = float(ct["gamma"])',
    "int_float": 'n = int(float(ct.get("daysToExpiration")))',
    "intermediate": 'sp = ct.get("strikePrice")\nx = float(sp)',
    "multiline": 'x = float(\n    ct.get("strikePrice")\n)',
    "finite_reader": 'x = float_finite_or_none(ct.get("openInterest"))',
    "positive_reader": 'x = float_positive_or_none(item.get("BID_PRICE"))',
    "local_delegate": 'def _safe_float(v):\n    return float_finite_or_none(v)\nx = _safe_float(opt.get("delta"))',
    "if_delegate": 'def _safe_int(v):\n    f = float_finite_or_none(v)\n    return int(f) if f is not None else None\nn = _safe_int(item.get("BID_SIZE"))',
    "field_by_constant": 'LP = "LAST_PRICE"\nx = float_finite_or_none(item.get(LP))',
    "field_by_argument": 'x = float_finite_or_none(latest(items, "MARK", now=1))',
}

SHOULD_NOT_FLAG = {
    "schwab_number": 'x = schwab_number(ct.get("strikePrice"))',
    "schwab_count": 'x = schwab_count(item.get("TOTAL_VOLUME"))',
    "carried_parse": 'k = schwab_number(ct.get("strikePrice"))\ny = float(k)',
    "wrapper_over_reader": 'def _schwab_int(v):\n    n = schwab_number(v)\n    return int(n) if n is not None else None\nx = _schwab_int(ct.get("daysToExpiration"))',
    "not_a_schwab_field": 'x = float(row.get("server_received_ts"))',
    "literal": "x = float(3.5)",
}


@pytest.mark.parametrize("name,src", list(SHOULD_FLAG.items()))
def test_flags(name, src):
    assert scan_source(src), f"missed: {name}"


@pytest.mark.parametrize("name,src", list(SHOULD_NOT_FLAG.items()))
def test_passes(name, src):
    assert not scan_source(src), f"false positive: {name}"


def test_repository_is_clean():
    found = violations()
    assert not found, "\n".join(f"{r}:{ln} {m}" for r, ln, m in found)
