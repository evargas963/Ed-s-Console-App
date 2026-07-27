"""RC-75 / RC-76: the BROWSER obeys the single-spot law, and the detector can prove it fails.

RC-75: six sites in static/chart.html each inlined their own spot precedence, three skipping the
1.5s live poll. The operator was looking at the big legend (live) and the meta bar (15s cycle)
showing two different prices on one screen.

RC-76: the first detector matched an ENUMERATION of source spellings and scored that file clean,
because the meta bar reached the same sources through Promise.all aliases (`s.spot` / `t.spot`).
A detector whose coverage is capped by the author's memory cannot audit the author. It is now
STRUCTURAL — any `liveSpot` or `<anything>.spot` read outside the authority — so the tests below
include a source name that appears in no configuration anywhere.
"""
from __future__ import annotations

import re
from pathlib import Path

from tools.data_faucet_audit import CLIENT_CONCEPTS, _js_function_at, audit_client

STATIC = Path(__file__).resolve().parent.parent / "static"
CHART = STATIC / "chart.html"
CONSOLE = STATIC / "index.html"


def _mutate(sub: str, rep: str, path: Path = CHART) -> list[dict]:
    """Run the detector against a deliberately broken client file, then always restore it."""
    orig = path.read_text(encoding="utf-8")
    assert sub in orig, f"fixture drifted; anchor not found: {sub[:60]!r}"
    try:
        path.write_text(orig.replace(sub, rep, 1), encoding="utf-8")
        return audit_client()
    finally:
        path.write_text(orig, encoding="utf-8")


def test_shipped_client_has_one_spot_faucet():
    assert audit_client() == [], "a rendered spot is read outside the client authority"


def test_detector_catches_an_aliased_precedence():
    """The exact defect that shipped: same sources, different local names."""
    bad = _mutate("`spot ${fmt(currentSpot())} · regime",
                  "`spot ${fmt((s && s.spot) ?? t.spot)} · regime")
    assert len(bad) == 1, f"the aliased meta-bar bug went undetected: {bad}"
    assert "chart.html:308" in bad[0]["undeclared"][0]


def test_detector_catches_a_source_name_it_has_never_seen():
    """RC-76's whole point: coverage must not depend on the author having listed the name."""
    novel = "window.__quote.spot"
    assert novel not in str(CLIENT_CONCEPTS), "fixture is no longer a novel name"
    bad = _mutate("  const bl = document.getElementById('biglegend');",
                  f"  const hdr = {novel};\n  const bl = document.getElementById('biglegend');")
    assert len(bad) == 1, f"an unlisted source stayed invisible — the RC-76 defect: {bad}"


def test_authority_is_the_only_place_precedence_lives():
    """Read the shipped file directly, so this holds even if the detector itself regresses."""
    lines = CHART.read_text(encoding="utf-8").splitlines()
    owners = _js_function_at(lines)
    reader = re.compile(CLIENT_CONCEPTS["spot"]["reader"])
    spec = CLIENT_CONCEPTS["spot"]
    offenders = [
        (i, line.strip())
        for i, (line, owner) in enumerate(zip(lines, owners), 1)
        if reader.search(re.sub(r"//.*$", "", line))
        and owner not in spec["authorities"] and owner not in spec["writers"]
        and not re.search(spec["assign_only"], line)
    ]
    assert not offenders, f"spot read outside currentSpot()/_cycleSpot(): {offenders}"


def test_console_detector_catches_the_defect_it_was_built_for():
    """RC-77: the console v2 header rendered `fnum(s.spot, s.quote_mid, t.spot)` and never
    consulted the SSE fast lane, so it lagged the money-path card beside it."""
    bad = _mutate("var spot = consoleSpot(s) ?? consoleSpot(t);",
                  "var spot = fnum(s.spot, s.quote_mid, t.spot);", CONSOLE)
    assert len(bad) == 1, f"the console v2 header precedence went undetected: {bad}"
    assert "index.html:" in bad[0]["undeclared"][0]


def test_console_detector_catches_a_reintroduced_fast_lane_read():
    """A render that reaches past the authority straight into the lane global is the same defect
    wearing a different shape — the utility bar did exactly this."""
    bad = _mutate("  const spotNum = consoleSpot(dRowOk ? d : null) ?? NaN;",
                  "  const spotNum = window._fastLaneSpot;", CONSOLE)
    assert len(bad) == 1, f"a raw fast-lane read in a render went undetected: {bad}"


def test_console_reader_does_not_flag_row_flags():
    """`r.spot` marks WHICH LADDER ROW is the spot row — a boolean, not a price. Flagging it would
    make the check a false-positive generator, and this repo does not enforce one of those."""
    assert "some(i => i.spot)" in CONSOLE.read_text(encoding="utf-8"), "fixture drifted"
    assert audit_client() == [], "the shipped console page must measure clean with those flags present"


def test_render_sites_call_the_authority():
    """Absence of a violation is not presence of the fix — the render sites must actually call it."""
    src = CHART.read_text(encoding="utf-8")
    assert src.count("currentSpot()") >= 5, "render sites no longer route through the authority"
    assert "function currentSpot()" in src
    assert "if (liveSpot != null) return liveSpot;" in src, (
        "the authority no longer prefers the 1.5s live poll — the meta bar and the big legend "
        "would agree with each other while both lagging the market"
    )
