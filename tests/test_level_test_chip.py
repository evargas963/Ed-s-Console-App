"""Pass 4b — Decision Command "Nth test of <level>" chip.

Source-level lock for the chip + helper + dispatch wire in static/index.html.
The chip reads /api/level_crosses (Pass 4 endpoint, `cfbff0f`) using
EdDB.count_level_tests under the hood; this Pass 4b adds the trader-visible
surface on the Decision Command rail.

Per AGENTS No-new-files: new test file is allowed (new topic; existing
tests/test_live_ui_*.py own per-horizon withhold + integrity behavior; none
owns the level-test chip).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "static" / "index.html"


def _read_index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_chip_dom_element_present_in_decision_command_header() -> None:
    """Lock the chip's DOM id + initial state on the Decision Command card."""
    html = _read_index()
    assert 'id="dr-level-test-chip"' in html, (
        "Pass 4b chip missing from static/index.html — Decision Command header "
        "must carry #dr-level-test-chip alongside the other dr-* chips"
    )
    # Initial state should be hidden + dim until first refresh resolves data.
    assert 'id="dr-level-test-chip"' in html
    # The chip element must be on a line that also sets display:none initially
    # (matches the existing dr-* chip pattern).
    for line in html.splitlines():
        if 'id="dr-level-test-chip"' in line:
            assert 'display:none' in line, (
                "Pass 4b chip must start hidden (display:none) — uncovered chip "
                "would render placeholder 'TEST —' before fetch resolves"
            )
            assert 'decision-chip' in line, (
                "Pass 4b chip must use decision-chip class for visual parity "
                "with sibling chips (LANE, MH, SESSION, etc.)"
            )
            break
    else:  # pragma: no cover — guarded by the assert above
        raise AssertionError("chip line not located")


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


def test_chip_severity_class_high_on_third_or_later_test() -> None:
    """Chip color should escalate to 'bad' (red-ish) at >=3 tests — that's
    the "third test of ceiling" pattern the chip is named for."""
    html = _read_index()
    assert "total >= 3 ? 'decision-chip bad' : 'decision-chip dim'" in html, (
        "Pass 4b chip should switch to 'bad' severity at >=3 tests — that "
        "matches the trader pattern (3rd test of a level often breaks). "
        "If the threshold needs to change, update this lock in the same commit."
    )
