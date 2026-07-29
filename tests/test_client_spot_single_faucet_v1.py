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
    bad = _mutate('<span id="metapx">${esc(fmt(currentSpot()))}</span>',
                  '<span id="metapx">${esc(fmt((s && s.spot) ?? t.spot))}</span>')
    assert len(bad) == 1, f"the aliased meta-bar bug went undetected: {bad}"
    # Assert the CONTENT, not a line number: an unrelated edit above this point must not be able
    # to fail the lock, or the lock gets weakened to shut it up.
    assert "chart.html:" in bad[0]["undeclared"][0]
    assert "s.spot" in bad[0]["undeclared"][0]


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


# ── RC-102: the console renders staleness, and the lane has ONE reader ───────────────────────
# /api/terrain published levels_stale/levels_age_sec/levels_stale_reason since RC-91, and
# index.html never read them — the terrain card rendered 90-minute-old walls beside a ticking
# price with no marker. And consoleSpot() + edLiveSpot() each read window._fastLaneSpot
# independently: two doors to one value ("dual spot clocks", operator Wave-1 audit).

def test_console_renders_levels_staleness():
    src = CONSOLE.read_text(encoding="utf-8")
    assert "levels_stale" in src, (
        "index.html no longer reads levels_stale — the terrain card will render frozen levels "
        "beside a live price with no marker, the exact RC-91 screen state"
    )
    assert "levels_stale_reason" in src, (
        "the stale marker must carry WHY (the reason tooltip), not just that it is stale"
    )
    assert "STALE" in src, "no visible STALE text — a class change alone is not a marker"


def test_trusted_badge_cannot_sit_over_stale_levels():
    """A TRUSTED chip over stale levels is a lie with a checkmark on it."""
    src = CONSOLE.read_text(encoding="utf-8")
    assert re.search(r"const trusted = d\.confidence === 'TRUSTED' && !_lvStale", src), (
        "TRUSTED no longer requires fresh levels — the badge can vouch for a frozen snapshot"
    )


def test_ed_live_spot_delegates_to_the_authority():
    """RC-102: edLiveSpot must not read window._fastLaneSpot itself — one lane, one reader."""
    src = CONSOLE.read_text(encoding="utf-8")
    m = re.search(r"function edLiveSpot\(\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "edLiveSpot missing"
    # Strip // comments first — USE versus MENTION. The body's comment EXPLAINS why the lane
    # must not be read directly, and a test that fails on the explanation forces deleting the
    # explanation to go green (the operator-law guard hit this exact trap on its own docs).
    body = re.sub(r"//.*$", "", m.group(1), flags=re.M)
    assert "consoleSpot(null)" in body, "edLiveSpot no longer delegates to consoleSpot"
    assert "_fastLaneSpot" not in body, (
        "edLiveSpot reads the lane directly again — the second door RC-102 closed"
    )


def test_visible_cv2_trust_chip_binds_levels_stale():
    """RC-106 close contract, applied to RC-102's defect: the test must assert the VISIBLE
    consumer, not a substring anywhere in index.html. The first RC-102 test passed while
    #cv2-kl-trust stayed blind because the hidden terrain chip also contained the string."""
    src = CONSOLE.read_text(encoding="utf-8")
    i = src.find("el('cv2-kl-trust')")
    assert i > 0, "the visible cv2 trust chip is no longer painted"
    # The staleness read must live in the SAME painter scope: within the 800 chars leading
    # up to the chip lookup, not merely somewhere in the file.
    window = src[max(0, i - 800):i + 800]
    window = re.sub(r"//.*$", "", window, flags=re.M)   # use vs mention
    assert "levels_stale" in window, (
        "#cv2-kl-trust is painted without reading t.levels_stale — the VISIBLE console "
        "can claim trusted over frozen levels again (RC-102 FAKE_CLOSE class)"
    )
    assert "STALE" in window, "the stale branch no longer renders a STALE chip"


def test_every_trust_chip_binds_levels_stale():
    """v8 audit found ct-trust blind AFTER cv2-kl-trust was fixed — the class is 'every trust
    chip', so the test ENUMERATES the class from the markup instead of naming survivors."""
    src = CONSOLE.read_text(encoding="utf-8")
    # RC-117: ct-conf evaded the first net because its id says 'conf', not 'trust' — the class
    # is every chip that RENDERS a confidence/trust verdict, so both name families are policed.
    # word-bounded: 'conf' must be a whole trailing segment, or 'confirm' cells false-positive.
    chips = sorted(set(re.findall(r'id="([a-z0-9-]*(?:trust|conf))"', src)))
    assert chips, "no trust/conf chips found — the markup moved and this test is guarding nothing"
    for chip in chips:
        i = src.find("el('" + chip + "')")
        if i < 0:
            i = src.rfind(chip)   # tv-trust binds through a var, not an el() literal
        window = re.sub(r"//.*$", "", src[max(0, i - 900):i + 900], flags=re.M)
        assert ("levels_stale" in window) or ("_lvStale" in window), (
            f"#{chip} is painted without reading levels_stale — a trust chip that cannot "
            f"say STALE claims trust over frozen levels (RC-102 class, third recurrence)"
        )


def test_cross_page_ticker_carrier_is_wired():
    """RC-123: ONE owner of THE ticker across pages (localStorage ed_ticker). Both pages must
    ADOPT it at load and WRITE it on commit; and the console's adoption must sit ABOVE the
    fetchState chokepoint persist, or the first poll writes the markup default over the
    operator's saved symbol (the write-before-read ordering the first probe caught)."""
    idx = CONSOLE.read_text(encoding="utf-8")
    cht = CHART.read_text(encoding="utf-8")
    for src, name in ((idx, "index"), (cht, "chart")):
        assert "localStorage.getItem('ed_ticker')" in src, f"{name} no longer ADOPTS the carrier"
        assert "localStorage.setItem('ed_ticker'" in src, f"{name} no longer WRITES the carrier"
    assert idx.find("localStorage.getItem('ed_ticker')") < idx.find("async function fetchState"), (
        "the console adopts ed_ticker BELOW the first fetch cycle — the first poll would "
        "overwrite the operator's saved ticker with the markup default"
    )
    # v21 escape closed: the persist lives INSIDE setActiveTicker — activeTicker's ONLY
    # canonical writer — so radar clicks and every other caller carry the ticker by
    # construction. fetchState must NOT persist too: two writers in one pipeline is the
    # multi-writer defect this whole file polices.
    m = re.search(r"function setActiveTicker\(.*?\n\}", idx, re.S)
    assert m and "localStorage.setItem('ed_ticker'" in m.group(0), (
        "setActiveTicker no longer writes the carrier — radar/watchlist switches will "
        "leave the chart page on the old symbol (the v21 escape reopened)"
    )
    fs = re.search(r"async function fetchState\(.*?\n\}", idx, re.S)
    assert fs and "localStorage.setItem('ed_ticker'" not in fs.group(0), (
        "fetchState persists the carrier AND setActiveTicker does — two writers, one pipeline"
    )


def test_rc117_named_victims_are_locked():
    """RC-117 close contract: the named victims, asserted literally.
    - cv2-hd-px has ONE value-writer (paintSpotDisplays); painters may only TRIGGER it.
    - Both footers (cv2-f-status / ct-foot-status) must derive live/STALE from levels_stale,
      never hardcode 'live'.
    - ct-conf is a member of the stale-gated chip class."""
    src = CONSOLE.read_text(encoding="utf-8")
    # use vs mention: strip BOTH comment forms — the strict reference count immediately caught
    # RC-81's own block-comment history lesson mentioning the id.
    body = re.sub(r"/\*.*?\*/", "", re.sub(r"//.*$", "", src, flags=re.M), flags=re.S)
    # v12 residual accepted: banning only T('cv2-hd-px', ...) left getElementById(...).textContent
    # open — the lock must ban the ACTION (any assignment reaching that element), not one syntax.
    # v13 residual accepted: a same-line accessor scan is escapable by fetching the element
    # into a variable and writing on the next line. The strict invariant: outside its markup,
    # the SPOT_DISPLAY_IDS registry, and the sanctioned tab-switch BLANK, NOTHING in the page
    # may reference this id at all — any new reference is a potential writer and fails here.
    # v14 kill accepted: exempting any line containing 'null' let a value-writer escape by
    # mentioning the word (e.g. `px || null`). The exemption is now the EXACT sanctioned
    # blank statement, nothing looser.
    # v16 hardening: every exemption is now LINE-EQUALITY or exact-literal, so an escape
    # cannot ride shotgun on a sanctioned line (writer appended to the registry line, code
    # hidden beside the markup, the blank used as a substring shield). Honest limit, stated:
    # building the id by string CONCAT ('cv2-hd-' + 'px') evades any text scan — that is the
    # AST/dataflow boundary; if an escape ever demonstrates it, the lock graduates to a parser.
    _REGISTRY = "const SPOT_DISPLAY_IDS = ['sb-spot', 'ub-price', 'cv2-hd-px', 'tv-px'];"
    _BLANK = "T('cv2-hd-px', null);"
    refs = []
    for ln in body.splitlines():
        if "cv2-hd-px" not in ln:
            continue
        t = ln.strip()
        if t == _REGISTRY or t == _BLANK:
            continue
        if 'id="cv2-hd-px"' in ln and "<span" in ln and "<script" not in ln.lower():
            continue                                 # the markup node, and only markup
        refs.append(t)
    assert refs == [], (
        f"unsanctioned references to cv2-hd-px — the only legal touchpoints are the markup, "
        f"the SPOT_DISPLAY_IDS registry, and the tab-switch blank: {refs}"
    )
    # v13/v14: every as-of/stamp surface reads the PAYLOAD clock, never the paint clock.
    # v14 kill accepted: a char-window bind is escapable by moving code — the bind is now the
    # full STATEMENT (from the writer call to its closing paren), and tv-stamp joins the class.
    for writer, painter in (("T('cv2-f-status'", "T"), ("T('ct-foot-status'", "T"),
                            ("set('tv-stamp'", "set")):
        i = body.find(writer)
        assert i > 0, f"{writer} painter is gone"
        stmt = body[i:body.find(");", i) + 2]
        assert "computed_ts_utc" in stmt or "_asOf" in stmt, (
            f"{writer} as-of no longer reads the payload clock (computed_ts_utc)"
        )
        # v16: ban EVERY paint-clock form, not one spelling — empty new Date(), Date.now(),
        # and any Date construction not fed by the payload epoch.
        assert "new Date()" not in stmt and "Date.now()" not in stmt, (
            f"{writer} stamps the PAINT clock — 'now' beside old data is the lying-clock class"
        )
        for m in re.finditer(r"new Date\(([^)]*)\)", stmt):
            arg = m.group(1).strip()
            assert arg and ("computed_ts_utc" in arg or "_asOf" in arg), (
                f"{writer} constructs a Date from {arg!r} — only the payload epoch is legal"
            )
    # ...and _asOf itself must be the payload clock, so the indirection cannot be repurposed.
    assert "var _asOf = fnum(t.computed_ts_utc)" in body, "_asOf no longer binds computed_ts_utc"
    for foot in ("cv2-f-status", "ct-foot-status"):
        i = body.find("T('" + foot + "'")
        assert i > 0, f"{foot} painter is gone"
        window = body[max(0, i - 700):i + 300]
        assert "levels_stale" in window, (
            f"{foot} paints 'live' without consulting levels_stale — the lying-clock class"
        )
    chips = sorted(set(re.findall(r'id="([a-z0-9-]*(?:trust|conf))"', src)))
    assert "ct-conf" in chips, "ct-conf left the policed chip class"


def test_chart_page_never_calls_console_only_helpers():
    """E-35: fnum() exists only in index.html; a chart.html edit called it and draw() died
    before the candles — the operator found a dead chart. The two pages are separate
    documents with separate helper sets; this bans every console-only helper from chart
    (extend the list when a new console-only helper is born)."""
    src = re.sub(r"/\*.*?\*/", "", re.sub(r"//.*$", "", CHART.read_text(encoding="utf-8"),
                                            flags=re.M), flags=re.S)
    for helper in ("fnum(", "fstr(", "consoleSpot(", "paintSpotDisplays(",
                   "edPaintTokenWarn(", "edLiveSpot("):
        assert helper not in src, (
            f"chart.html calls console-only {helper} — a ReferenceError there kills draw() "
            f"and the operator gets a blank chart (E-35)"
        )

