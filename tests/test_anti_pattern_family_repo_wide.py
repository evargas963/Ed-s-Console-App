"""CAPS — Comprehensive Anti-Pattern Sweep (repo-wide silent-default family)."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.anti_pattern_sweep as A  # noqa: E402
from tools.anti_pattern_sweep import (  # noqa: E402
    VARIANTS,
    find_unmarked_hits,
    iter_py_files,
)


def test_caps_enumerates_all_variant_shapes():
    assert len(VARIANTS) >= 8
    ids = {v.variant_id for v in VARIANTS}
    assert {
        "GET_WITH_DEFAULT",
        "GET_OR_DEFAULT",
        "GET_NONE_OR_DEFAULT",
        "CAST_OR_DEFAULT",
        "IF_NOT_NONE_ELSE",
        "IF_TRUTHY_ELSE",
        "GETATTR_DEFAULT",
        "SETDEFAULT",
        "NEXT_DEFAULT",
        "EXCEPT_RETURN_DEFAULT",
    } <= ids


def test_caps_detects_get_or_zero_variant():
    line = 'spot = float(row.get("spot") or 0.0)'  # caps-ok: scanner false positive: string fixture proving the CAPS GET_OR_DEFAULT regex still fires
    assert any(v.variant_id == "GET_OR_DEFAULT" and v.regex.search(line) for v in VARIANTS)


def test_caps_detects_cast_or_zero_variant():
    line = 'n = int(rows.get("n") or 0)'  # caps-ok: scanner false positive: string fixture proving the CAPS CAST_OR_DEFAULT regex still fires
    assert any(v.variant_id == "CAST_OR_DEFAULT" and v.regex.search(line) for v in VARIANTS)


def test_timestamp_alias_line_not_counted_as_violation():
    hits = find_unmarked_hits()
    assert not any("market_data_adapter.py" in h and "timestamp" in h for h in hits)


def test_no_location_allowlist_exists():
    """RC-REHAB-1 (2026-09-23): CAPS_PREFIX_ALLOWLIST (106 whole-file/folder rows) and
    CAPS_LINE_ALLOWLIST (line-number pins) hid 1,967 unreviewed hits. Both are gone; the only
    escape is a reasoned marker on the hit line. A reintroduced location allowlist fails here."""
    for name in ("CAPS_PREFIX_ALLOWLIST", "CAPS_LINE_ALLOWLIST", "caps_hit_allowed",
                 "hit_is_allowlisted", "SCAN_SKIP_PREFIXES"):
        assert not hasattr(A, name), f"{name} is back -- a location exemption hides review"


def test_no_unmarked_hits_anywhere_in_the_repo():
    hits = find_unmarked_hits()
    assert not hits, "CAPS violations (fix, or add a line-specific # caps-ok: reason):\n" + "\n".join(hits[:60])


def test_register_records_that_there_is_no_allowlist():
    reg = (ROOT / "schwab_field_inventory/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- CAPS_ALLOWLIST_START -->" not in reg, "the mirrored allowlist table is back"
    assert "CAPS silent-default substitution family — no allowlist" in reg


def test_lstm_data_zone_missing_sentinel_not_pin_neutral_default():
    from lstm_data import ZONE_MISSING_ENCODED, _encode_zone_feature

    assert _encode_zone_feature({}) == ZONE_MISSING_ENCODED
    text = (ROOT / "lstm_data.py").read_text(encoding="utf-8")
    assert 'or "pin_neutral"' not in text


def test_scan_covers_the_whole_repo_including_tools_tests_and_governance():
    """The pass/fail scan used to skip tools/, tests/ and governance/ outright."""
    rels = {p.relative_to(ROOT).as_posix() for p in iter_py_files()}
    for must in ("server.py", "market_data_adapter.py", "math_levels.py", "lstm_data.py",
                 "tools/anti_pattern_sweep.py", "tests/test_anti_pattern_family_repo_wide.py",
                 "governance/provenance_inventory.py", "calibration/writer.py"):
        assert must in rels, f"{must} fell out of the CAPS scan"


def test_caps_detects_call_or_default_variant():
    """RC-REHAB-1: the shape every other variant missed -- the default follows a CALL."""
    hit = 'oi = float_nonnegative_or_none(ct.get("openInterest")) or 0.0'  # caps-ok: scanner false positive: fixture string this test feeds the CALL_OR_DEFAULT regex
    miss = 'oi = float_nonnegative_or_none(ct.get("openInterest"))'
    spec = next(v for v in VARIANTS if v.variant_id == "CALL_OR_DEFAULT")  # caps-ok: scanner false positive: next() has NO default; a missing variant raises StopIteration and fails the test
    assert spec.regex.search(hit) and not spec.regex.search(miss)
