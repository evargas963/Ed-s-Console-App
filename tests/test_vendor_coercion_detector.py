"""Effectiveness lock for the vendor-coercion detector (RC-FAUCET).

OBSERVED (2026-07-25/26): a mechanical lock is only worth its detection. During the
self-adversarial sweep the detector was found blind to (a) the intermediate-variable form
(sp = ct.get('strikePrice'); float(sp)), (b) direct float(ct.get(...)) because a nested-paren
regex could not reach inside, and (c) float( matching inside _safe_float(. Each was a silent
false-negative that let real bugs through until fixed. This test pins the detector's
true-positive and true-negative behaviour so a future regex edit cannot quietly re-open a hole.

VALIDATED: run against the current detector on 2026-07-26 — every case below is classified as
asserted. New known-good / known-bad shapes should be ADDED here when discovered.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_vendor_field_coercion import scan_file


def _n_findings(src: str) -> int:
    p = Path(tempfile.mktemp(suffix=".py"))
    p.write_text(src, encoding="utf-8")
    try:
        return len(scan_file(p))
    finally:
        os.unlink(p)


SHOULD_FLAG = {
    "direct_get": 'x = float(ct.get("strikePrice"))',
    "direct_subscript": 'x = float(ct["gamma"])',
    "int_float_direct": 'n = int(float(ct.get("daysToExpiration")))',
    "intermediate_var": 'sp = ct.get("strikePrice")\nx = float(sp)',
    "abs_float_get": 'if abs(float(ct.get("strikePrice")) - k) < 1: pass',
    "newly_added_field": 'x = float(ct.get("breakEven"))',
    "underlying_price": 'x = float(chain.get("underlyingPrice"))',
}

SHOULD_NOT_FLAG = {
    "canonical_f": 'x = _f(ct.get("strikePrice"))',
    "canonical_finite": 'x = float_finite_or_none(ct.get("gamma"))',
    "canonical_nonneg": 'x = float_nonnegative_or_none(ct.get("totalVolume"))',
    "nonvendor_field": 'x = float(ct.get("someInternalScore"))',
    "safe_float_helper": 'x = _safe_float(opt.get("delta"))',
    "denylist_source": 'b = pq["bid"]\nx = float(b)',
    "float_literal": "x = float(3.5)",
    "marked_ok": 'x = float(ct.get("gamma"))  # vendor-coercion-ok: diagnostic, isfinite-gated below',
}


@pytest.mark.parametrize("name,src", list(SHOULD_FLAG.items()))
def test_detector_flags_raw_vendor_coercion(name, src):
    assert _n_findings(src) >= 1, f"detector MISSED a raw vendor coercion: {name!r} -> {src!r}"


@pytest.mark.parametrize("name,src", list(SHOULD_NOT_FLAG.items()))
def test_detector_ignores_safe_forms(name, src):
    assert _n_findings(src) == 0, f"detector FALSE-POSITIVE on a safe form: {name!r} -> {src!r}"


def test_detector_multiline_float_is_a_known_limitation():
    """The detector is line-based: a float() split across lines is NOT caught. This is
    documented, not silently assumed away — if this ever starts passing (detector gained
    multi-line support) tighten it to an assert-flag. Until then, code review + the fact
    that the canonical readers are the path of least resistance carry this edge."""
    multiline = 'x = float(\n    ct.get("strikePrice")\n)'
    # Known limitation: currently 0. Pinned so a future change is a conscious decision.
    assert _n_findings(multiline) == 0
