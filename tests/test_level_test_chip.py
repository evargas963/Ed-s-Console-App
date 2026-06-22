"""Pass 4b — Signals Rail "Nth test of <level>" slot (slt-level-test).

Source-level lock for the slot + helper + dispatch wire in static/index.html.
The surface reads /api/level_crosses (Pass 4 endpoint) using
EdDB.count_level_tests under the hood. Operator 2026-06-10 migrated the
trader-visible surface from the retired Decision Command header chip
(#dr-level-test-chip) to #signals-rail / #slt-level-test — see
tests/test_issue18_ui_contract.py for the authoritative negative lock.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "static" / "index.html"


def _read_index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_level_test_slot_present_in_signals_rail() -> None:
    """Lock the slot DOM id + initial hidden state on the Signals Rail."""
    html = _read_index()
    assert 'id="slt-level-test"' in html, (
        "Pass 4b level-test slot missing — Signals Rail must carry "
        "#slt-level-test (operator 2026-06-10 migration)"
    )
    for line in html.splitlines():
        if 'id="slt-level-test"' in line and "signal-slot" in line:
            assert "display:none" in line, (
                "slt-level-test must start hidden — quiet state hides until "
                "level is under pressure (≥2 prior tests)"
            )
            assert "signal-slot--quiet" in line, (
                "slt-level-test must use signal-slot severity vocabulary"
            )
            break
    else:  # pragma: no cover — guarded by assert above
        raise AssertionError("slt-level-test opening tag not located")


def test_chip_helper_functions_defined() -> None:
    """JS-side: helper, ordinal, nearest-level picker, fetcher must all exist."""
    html = _read_index()
    for fn in (
        "_updateLevelTestChip",
        "_pickNearestLevelForChip",
        "_levelTestChipOrdinal",
    ):
        assert "function " + fn in html or "async function " + fn in html, (
            f"Pass 4b helper {fn} missing from static/index.html"
        )


def test_chip_dispatched_from_updateLiveUiAe() -> None:
    """The chip helper must be called from the main refresh dispatch
    (_updateLiveUiAe) — adding the helper without wiring it is the dormant
    pattern Pass 1b guards on the backend side."""
    html = _read_index()
    # Locate the _updateLiveUiAe function body and assert _updateLevelTestChip
    # is invoked inside it (not just defined).
    lines = html.splitlines()
    start = None
    for i, line in enumerate(lines):
        if "function _updateLiveUiAe(" in line:
            start = i
            break
    assert start is not None, "_updateLiveUiAe function missing"
    # Walk forward to the function's closing brace (simple depth count from
    # the opening brace on the def line).
    depth = 0
    seen_open = False
    body_lines: list[str] = []
    for line in lines[start:]:
        for ch in line:
            if ch == "{":
                depth += 1
                seen_open = True
            elif ch == "}":
                depth -= 1
        body_lines.append(line)
        if seen_open and depth == 0:
            break
    body = "\n".join(body_lines)
    assert "_updateLevelTestChip(" in body, (
        "Pass 4b helper _updateLevelTestChip is not called inside "
        "_updateLiveUiAe — chip will never update; wire it alongside the "
        "other _updateXxxChip calls"
    )


def test_chip_uses_pass_4_endpoint_with_correct_params() -> None:
    """The fetcher must call /api/level_crosses with level_name + level_value
    + lookback_hours params — this is the count_level_tests mode added in
    Pass 4 (cfbff0f). Hitting it without these params returns recent-crosses
    mode, which is the wrong shape for the chip."""
    html = _read_index()
    assert "'/api/level_crosses?ticker='" in html
    assert "'&level_name='" in html
    assert "'&level_value='" in html
    assert "'&lookback_hours=6.5'" in html


def test_chip_respects_throttle_constant() -> None:
    """The TTL constant gates how often /api/level_crosses fires per ticker.
    Lock the name (not the value) so a refactor can't silently remove the
    throttle and spam the endpoint."""
    html = _read_index()
    assert "_LEVEL_TEST_CHIP_TTL_MS" in html, (
        "Pass 4b chip throttle constant missing — without it every refresh "
        "would hit /api/level_crosses, which is contrary to the 30s cache "
        "design"
    )
    assert "_levelTestChipCache" in html


def test_chip_pickNearest_logic_prefers_closer_distance() -> None:
    """The ms_dict has nearest_above + nearest_below; the chip should pick
    whichever has the smaller absolute distance to spot. Lock the comparison
    so a future refactor can't silently switch to always-pick-above."""
    html = _read_index()
    # Look for the comparison pattern. We don't care about exact spelling;
    # we care that Math.abs is applied to BOTH above and below distances
    # somewhere inside the picker function so the picker is direction-aware.
    lines = html.splitlines()
    start = None
    for i, line in enumerate(lines):
        if "function _pickNearestLevelForChip(" in line:
            start = i
            break
    assert start is not None
    depth = 0
    seen_open = False
    body_lines: list[str] = []
    for line in lines[start:]:
        for ch in line:
            if ch == "{":
                depth += 1
                seen_open = True
            elif ch == "}":
                depth -= 1
        body_lines.append(line)
        if seen_open and depth == 0:
            break
    body = "\n".join(body_lines)
    assert "Math.abs(aboveDist)" in body
    assert "Math.abs(belowDist)" in body


def test_chip_severity_escalates_on_third_or_later_test() -> None:
    """Severity bands: quiet (≤1 prior), building (2nd), hot (≥3 prior tests)."""
    html = _read_index()
    assert "if (total >= 3) severity = 'hot'" in html, (
        "Pass 4b slot must escalate to hot at >=3 prior tests"
    )
    assert "else if (total === 2) severity = 'building'" in html
    assert "signal-slot--' + severity" in html or (
        "slot.className = 'signal-slot signal-slot--' + severity" in html
    ), "severity must map to signal-slot--{quiet|building|hot} classes"
