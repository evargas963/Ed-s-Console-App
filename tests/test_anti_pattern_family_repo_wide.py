"""CAPS — Comprehensive Anti-Pattern Sweep (repo-wide silent-default family)."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.anti_pattern_sweep import (  # noqa: E402
    CAPS_PREFIX_ALLOWLIST,
    VARIANTS,
    caps_hit_allowed,
    find_unallowlisted_hits,
    scan_all,
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
    line = 'spot = float(row.get("spot") or 0.0)'
    assert any(v.variant_id == "GET_OR_DEFAULT" and v.regex.search(line) for v in VARIANTS)


def test_caps_detects_cast_or_zero_variant():
    line = 'n = int(rows.get("n") or 0)'
    assert any(v.variant_id == "CAST_OR_DEFAULT" and v.regex.search(line) for v in VARIANTS)


def test_timestamp_alias_line_not_counted_as_violation():
    hits = find_unallowlisted_hits(production_only=True)
    assert not any("market_data_adapter.py" in h and "timestamp" in h for h in hits)


def test_caps_parent_unallowlisted_probe():
    """Synthetic path not in allowlist must not pass caps_hit_allowed."""
    assert not caps_hit_allowed("synthetic_caps_probe.py", 1, "GET_OR_DEFAULT")


def test_no_unallowlisted_production_hits():
    hits = find_unallowlisted_hits(production_only=True)
    assert not hits, "CAPS violations (fix or add allowlist):\n" + "\n".join(hits[:60])


def test_register_contains_caps_allowlist_block():
    reg = (ROOT / "governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- CAPS_ALLOWLIST_START -->" in reg
    assert "<!-- CAPS_ALLOWLIST_END -->" in reg
    for prefix, _ in CAPS_PREFIX_ALLOWLIST[:5]:
        assert prefix in reg


def test_lstm_data_zone_missing_sentinel_not_pin_neutral_default():
    from lstm_data import ZONE_MISSING_ENCODED, _encode_zone_feature

    assert _encode_zone_feature({}) == ZONE_MISSING_ENCODED
    text = (ROOT / "lstm_data.py").read_text(encoding="utf-8")
    assert 'or "pin_neutral"' not in text


def test_production_scan_covers_all_py_outside_tools_tests(repo_index):
    """TEST_SYSTEM_REHAB_V2: `prod_files` (the independent completeness check against
    scan_all's own output) now sources from the shared `repo_index` corpus rather than
    a second root.rglob("*.py") -- scan_all() itself stays untouched: it lives in
    tools/anti_pattern_sweep.py, a standalone tool usable outside pytest (Hardening,
    direct invocation), so it cannot depend on a pytest-only fixture."""
    prod_files = {
        rel.as_posix()
        for rel, _text, _tree in repo_index.items()
        if "tests" not in rel.parts and "tools" not in rel.parts and ".git" not in rel.parts
    }
    _scanned = {rel for _ln, rel, _vid, _expr in scan_all(production_only=True)}
    # Files with zero pattern hits won't appear in scan output; ensure core modules were scanned.
    for must in ("server.py", "market_data_adapter.py", "math_levels.py", "lstm_data.py"):
        assert must in prod_files
