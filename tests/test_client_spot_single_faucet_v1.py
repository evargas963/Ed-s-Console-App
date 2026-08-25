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

# audit_client() imports server lazily MID-TEST; under xdist distributions where this
# file runs first, the conftest ledger firewall could not pre-patch
# server.TERRAIN_QUARANTINE_LEDGER and a quarantine write landed in the tracked audit
# file (caught by the firewall in CI, 2026-08-24: +479 bytes, truncated back). Import
# server at module top so the autouse fixture always patches it before the test body.
import server  # noqa: F401

from tools.data_faucet_audit import CLIENT_CONCEPTS, _js_function_at, audit_client

STATIC = Path(__file__).resolve().parent.parent / "static"
CHART = STATIC / "chart.html"
CONSOLE = STATIC / "index.html"


def _mutate(sub: str, rep: str, path: Path = CHART) -> list[dict]:
    """Run the detector against a deliberately broken client file, then always restore it.

    RC-398: the restore went through `write_text`, which opens with newline=None and
    translates "\\n" to os.linesep. On Windows that round-trip is lossless, so the defect
    was invisible to every local run; on the required Linux runner it rewrote these CRLF
    files as LF and the "restore" did not restore. MEASURED there: static/chart.html and
    static/index.html left pytest reflowed with diffs of exactly 2x their CRLF counts
    (4220 = 2110*2, 28076 = 14038*2), tripping eol_style_invariant on files the change
    never touched.

    A mutation control that cannot put the tree back byte-for-byte is not a control — it
    is a mutation. Bytes in, bytes out; the platform gets no say.
    """
    raw = path.read_bytes()
    orig = raw.decode("utf-8")
    assert sub in orig, f"fixture drifted; anchor not found: {sub[:60]!r}"
    try:
        path.write_bytes(orig.replace(sub, rep, 1).encode("utf-8"))
        return audit_client()
    finally:
        path.write_bytes(raw)


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
    assert not offenders, f"spot read outside currentSpot()/as_of helpers: {offenders}"


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
    # RC-225: authority is /api/spot only (liveSpot); cycle fallback DELETED.
    assert "return liveSpot;" in src, (
        "the authority no longer returns the /api/spot binding — dual-age fallback may return"
    )
    assert "function _cycleSpot" not in src, (
        "cycle fallback faucet returned — strikes/terrain ages can paint as current (RC-225)"
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


def _collapse_js_literal_concat(src: str) -> str:
    """RC-117 v17: fold adjacent JS string-literal concatenation into a single literal.

    `'cv2-hd-' + 'px'` becomes `'cv2-hd-px'`, so an id assembled from literals is visible to
    the same text scan that catches the plain spelling. Runs to a fixed point so chains of
    three or more literals collapse too, and handles both quote styles plus the whitespace /
    line-continuation forms a minifier or a hand edit would produce.
    """
    pat = re.compile(r"(['\"])((?:[^'\"\\\n]|\\.)*)\1\s*\+\s*(['\"])((?:[^'\"\\\n]|\\.)*)\3")
    prev = None
    out = src
    while prev != out:
        prev = out
        out = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(4)}{m.group(1)}", out)
    return out


def test_rc117_concat_built_id_no_longer_evades_the_scan():
    """The boundary this row was held open for: the collapser must make a concat-built id
    indistinguishable from the plain spelling, and must not corrupt ordinary source."""
    assert "'cv2-hd-px'" in _collapse_js_literal_concat("T('cv2-hd-' + 'px', v);")
    assert "'cv2-hd-px'" in _collapse_js_literal_concat("T('cv2' + '-hd' + '-px', v);")
    assert '"cv2-hd-px"' in _collapse_js_literal_concat('T("cv2-hd-" + "px", v);')
    # identifier-valued concat is NOT folded (it is not a literal) and must stay untouched
    assert _collapse_js_literal_concat("T(a + b, v);") == "T(a + b, v);"
    # arithmetic and template usage survive unchanged
    assert _collapse_js_literal_concat("const n = x + 1;") == "const n = x + 1;"


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
    # hidden beside the markup, the blank used as a substring shield).
    # v17 (RC-117 close, 2026-08-04): the stated CONCAT boundary is now CLOSED. Building the id
    # from adjacent string literals ('cv2-hd-' + 'px') no longer evades the scan — the body is
    # normalized by _collapse_js_literal_concat first, which folds literal-to-literal '+' into
    # one literal exactly as the JS engine would. This is the deterministic subset of the
    # dataflow problem that a text scan can own; identifier-valued concat (id = a + b) remains
    # outside any scanner and is covered instead by the registry invariant below, since a
    # variable holding this id must still have been assigned from one of the sanctioned lines.
    body = _collapse_js_literal_concat(body)
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


def test_no_client_fallback_between_level_books():
    """RC-128 Lock 4: an `a || b` fallback between an analytics figure and an SSOT level key
    is the dual book at the paint site — whichever side exists wins silently. The straddle
    EM chains did exactly this at six legacy sites; the pattern is banned for level keys."""
    src = re.sub(r"/\*.*?\*/", "", re.sub(r"//.*$", "", CONSOLE.read_text(encoding="utf-8"),
                                          flags=re.M), flags=re.S)
    assert "em_straddle_upper ||" not in src and "em_straddle_lower ||" not in src, (
        "a straddle-vs-SSOT fallback chain is back — the EM dual book at the paint site"
    )
    assert not re.search(r"\|\|\s*d\.kl_em_(?:upper|lower)", src), (
        "something falls back INTO the SSOT EM key — pick one book, no silent winner"
    )


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


# ── v23 / RC-128 Lock 3: ONE key family per paint surface ────────────────────────────────────
# The same concept reaches the screen under two spellings — the analytics payload's kl_* keys
# (stamped FROM terrain by the overlay) and the terrain payload's bare keys. Both come from the
# ONE producer, so the remaining failure mode is a paint site that RESOLVES across families
# (`d.kl_call_gamma_wall || t.call_wall`): whichever payload refreshed last wins silently, and
# two tiles disagree seconds apart. Census 2026-07-29: zero mixed lines exist; this locks it.

_KL_FAMILY = re.compile(r"kl_(?:call_gamma_wall|put_gamma_wall|gamma_flip"
                        r"|absolute_gamma_strike|pin_candidate|hvl"
                        r"|max_pain|em_upper|em_lower|call_delta_wall|put_delta_wall)")
_TERRAIN_FAMILY = re.compile(r"(?<!kl_)\b(?:call_wall|put_wall|gamma_flip"
                             r"|absolute_gamma_strike|pin_candidate|hvl"
                             r"|max_pain)\b")


def _mixed_family_lines(src: str) -> list[tuple[int, str]]:
    """Lines where a kl_* SSOT key and a bare terrain-family key appear in ONE expression —
    the cross-family resolve path Lock 3 bans. Comments stripped so prose can explain the
    rule without tripping it."""
    src = re.sub(r"/\*.*?\*/", "", re.sub(r"//.*$", "", src, flags=re.M), flags=re.S)
    out = []
    for n, l in enumerate(src.splitlines(), 1):
        if _KL_FAMILY.search(l) and _TERRAIN_FAMILY.search(_KL_FAMILY.sub("", l)):
            out.append((n, l.strip()[:120]))
    return out


def test_no_paint_site_resolves_across_level_key_families():
    for path in (CONSOLE, CHART):
        offenders = _mixed_family_lines(path.read_text(encoding="utf-8"))
        assert offenders == [], (
            f"{path.name} mixes the kl_* and terrain key families in one expression — "
            f"whichever payload is newer wins silently (v23 Lock 3): {offenders}"
        )


def test_mixed_family_injection_is_caught():
    """Negative control: the classic fallback shape must fire; single-family lines must not."""
    assert _mixed_family_lines("x = d.kl_call_gamma_wall || t.call_wall;"), (
        "the cross-family fallback went undetected — Lock 3 is inert"
    )
    assert not _mixed_family_lines("x = t.call_wall; // kl_call_gamma_wall is the table's key"), (
        "a comment mentioning the other family tripped Lock 3 — use-vs-mention regression"
    )


def test_chart_page_binds_only_the_terrain_family():
    """chart.html reads /api/terrain directly; a kl_* read there would be a second payload
    fetch racing the first (and E-35 proved chart borrowing console spellings kills draw())."""
    src = re.sub(r"/\*.*?\*/", "", re.sub(r"//.*$", "", CHART.read_text(encoding="utf-8"),
                                          flags=re.M), flags=re.S)
    hits = _KL_FAMILY.findall(src)
    assert hits == [], f"chart.html binds analytics-family kl_* keys: {sorted(set(hits))}"


# ── RC-130: behavioral wall claims must be CONDITIONAL on the geometry state ─────────────────
# Live SPY 2026-07-29: put wall 740 sat ABOVE spot 735.13 while every surface said "dealer
# support". RC-83 (two-sided magnet) and RC-86 (invented range) were incident fixes of this
# same class — a painted claim no state supports — and the class was never locked. This is
# the lock: any client line that names a wall AND asserts support/resistance must carry a
# conditional marker (state ternary, 'while', 'BREACHED', or an explicit negation).

_WALL_WORD = re.compile(r"wall", re.I)
_CLAIM_WORD = re.compile(r"resistance|support", re.I)
#: What makes a support/resistance claim legitimate under RC-130: the text says WHEN it
#: holds. Two shapes qualify and both are the same requirement.
#:   1. A state/breach condition — the original vocabulary ("while", "BREACHED", "holds").
#:   2. An explicit SPOT-RELATIVE GEOMETRY — "above spot", "the level below which". RC-130
#:      was a PUT WALL painted 'support' while sitting ABOVE spot, i.e. a claim with no
#:      geometry at all; a line that states its own side of spot is not that defect, it is
#:      the repair. This was added 2026-08-17 because the RC-354 GSF/GRC rows state their
#:      geometry in exactly this form ("the first level above spot", "the level below
#:      which") and were flagged anyway — the detector could not read the very condition
#:      the test is named for, and the neighbouring row was then contaminated through the
#:      ±1-line window. Recognising a stated geometry is not a widening: a bare
#:      `sr: 'support'` on a wall still carries no such phrase and still trips, which the
#:      planted-defect control below proves.
_CONDITIONAL = re.compile(
    r"while|BREACHED|breached|holds|NOT\b|not\s+(?:resistance|support)"
    r"|(?:above|below)\s+spot|(?:above|below)\s+which|first\s+level\s+(?:above|below)",
    re.I,
)


def _unconditional_wall_claims(src: str) -> list[tuple[int, str]]:
    """A claim line is judged with its ±1-line window: splitting the label and the claim
    across adjacent lines (multi-line object literals) must not evade the lock."""
    src = re.sub(r"/\*.*?\*/", "", re.sub(r"//.*$", "", src, flags=re.M), flags=re.S)
    lines = src.splitlines()
    out = []
    for i, l in enumerate(lines):
        if not _CLAIM_WORD.search(l):
            continue
        window = lines[max(0, i - 1):i + 2]
        if any(_WALL_WORD.search(w) for w in window) \
                and not any(_CONDITIONAL.search(w) for w in window):
            out.append((i + 1, l.strip()[:120]))
    return out


def test_no_unconditional_wall_support_resistance_claims():
    for path in (CONSOLE, CHART):
        offenders = _unconditional_wall_claims(path.read_text(encoding="utf-8"))
        assert offenders == [], (
            f"{path.name} asserts support/resistance on a wall with no geometry condition — "
            f"the RC-130 class (put wall painted 'support' above spot): {offenders}"
        )


def test_containment_claims_require_a_positive_contains_gate():
    """RC-131 (v25): the RC-130 fix put the containment claim in the ternary's DEFAULT
    branch — a payload predating the state fields fell through to 'dealer support' /
    'DEALERS BUY' on a put wall above spot, the exact lie the fix existed to kill (E-35
    class: new static + old payload; MEASURED live on :8000). This lock makes the claim
    exist ONLY behind an explicit === 'contains' comparison: absent state, absent claim."""
    claim = re.compile(r"dealer supply|dealer support|DEALERS SELL|DEALERS BUY"
                       r"|Resistance while|Support while")
    for path in (CONSOLE, CHART):
        src = re.sub(r"/\*.*?\*/", "", re.sub(r"//.*$", "", path.read_text(encoding="utf-8"),
                                              flags=re.M), flags=re.S)
        lines = src.splitlines()
        offenders = []
        for i, l in enumerate(lines):
            if claim.search(l) and not any(
                    "=== 'contains'" in w for w in lines[max(0, i - 1):i + 2]):
                offenders.append((i + 1, l.strip()[:120]))
        assert offenders == [], (
            f"{path.name}: a containment claim is reachable without a positive "
            f"=== 'contains' gate — absent state falls through to the old lie (RC-131): "
            f"{offenders}"
        )


def test_fallthrough_containment_shape_is_caught():
    """Negative control: the exact shipped defect shape must fire; the gated shape not."""
    claim = re.compile(r"dealer supply|dealer support|DEALERS SELL|DEALERS BUY"
                       r"|Resistance while|Support while")

    def scan(text):
        lines = text.splitlines()
        return [i for i, l in enumerate(lines)
                if claim.search(l) and not any(
                    "=== 'contains'" in w for w in lines[max(0, i - 1):i + 2])]

    shipped_defect = "note: s === 'breached' ? 'BREACHED — spot below' : 'dealer support',"
    assert scan(shipped_defect), "the fall-through containment shape went undetected"
    gated = "note: s === 'contains' ? 'dealer support' : 'γ concentration',"
    assert not scan(gated), "the positively-gated shape tripped the lock"


# ── RC-132: pin/HVL vocabulary truth ─────────────────────────────────────────────────────────
# A2: the ladder's GAMMA PIN tip still DEFINED the pin on the net book ("Largest |net gamma|
# strike") months after RC-124 moved the producer to total gamma — a definition change that
# never swept every paint site. A3: pick_hvl_strike and pick_pin_and_strength are the SAME
# metric (max total GEX$) by construction, yet 'HVL' and 'PIN' painted that one strike as two
# concepts on the ladder and the cv2 tag strip. These locks make both classes recur-proof.

def _pin_tips_defining_net(src: str) -> list[tuple[int, str]]:
    """Lines in a ±1 window of a GAMMA PIN label whose tip defines the pin on the net book."""
    src = re.sub(r"/\*.*?\*/", "", re.sub(r"//.*$", "", src, flags=re.M), flags=re.S)
    lines = src.splitlines()
    net_def = re.compile(r"net gamma|\|net\||net GEX|net dealer GEX", re.I)
    row_start = re.compile(r"\{\s*(t|key)\s*:")
    out = []
    for i, line in enumerate(lines):
        # RC-292: the operator labels are now ABS GAMMA / Absolute Gamma; the retired
        # GAMMA PIN spellings stay scanned so a resurrected old row is still caught. The
        # match is on the row's LABEL position, not any mention — the Net GEX Peak row
        # legitimately SAYS "Distinct from Absolute Gamma" while defining the net book.
        if not any(lbl in line for lbl in (
                'GAMMA PIN', 'Gamma Pin',
                "t: 'ABS GAMMA'", "label: 'Absolute Gamma'", "'ABS GAMMA',")):
            continue
        for j in range(i, min(len(lines), i + 3)):
            if j > i and row_start.search(lines[j]):
                break   # a NEW row object began — its tip belongs to another concept
            if 'tip' in lines[j] and net_def.search(lines[j]):
                out.append((j + 1, lines[j].strip()[:120]))
    return out


def test_pin_tip_states_the_producers_metric_not_the_net_book():
    for path in (CONSOLE, CHART):
        offenders = _pin_tips_defining_net(path.read_text(encoding="utf-8"))
        assert offenders == [], (
            f"{path.name}: a GAMMA PIN tip defines the pin on the NET book — the producer is "
            f"max TOTAL GEX$ (pick_pin_and_strength, RC-124); the net book is 'Net Γ peak' "
            f"(RC-132): {offenders}"
        )


def test_net_definition_pin_tip_injection_is_caught():
    """Negative control: the exact stale tip that shipped must fire; the total tip not."""
    stale = "{ t: 'GAMMA PIN', v: d.gamma_pin,\n  tip: 'Largest |net gamma| strike — pin.' },"
    assert _pin_tips_defining_net(stale), "the stale net-book pin tip went undetected"
    honest = "{ t: 'GAMMA PIN', v: d.kl_gamma_pin,\n  tip: 'Largest TOTAL gamma strike.' },"
    assert not _pin_tips_defining_net(honest), "the total-gamma pin tip tripped the lock"


def test_gamma_pin_ladder_binds_kl_ssot_not_unstamped_gamma_pin() -> None:
    """RC-292: the console ABS GAMMA row (formerly GAMMA PIN) must paint the terrain
    total-gamma SSOT key, and no ladder row may resurrect the retired GAMMA PIN label."""
    src = CONSOLE.read_text(encoding="utf-8")
    m = re.search(r"\{ t: 'ABS GAMMA',\s*v:\s*([^,]+)", src)
    assert m is not None and "kl_absolute_gamma_strike" in m.group(1), (
        f"ABS GAMMA ladder binds {m.group(1) if m else 'nothing'} — must be "
        f"d.kl_absolute_gamma_strike"
    )
    assert re.search(r"\{ t: 'GAMMA PIN'", src) is None, (
        "a ladder row under the retired GAMMA PIN label returned — the raw concentration "
        "must not paint under an unearned pin claim (RC-292)"
    )


def test_console_today_poc_binds_state_payload_not_a_second_book() -> None:
    """F15: console POC/VAH/VAL paint /api/state today_* carried from the snapshot.

    Chart already extracts TODAY_POC by id from /api/levels. The live-path hole was
    /api/state dropping the carry so #dr-lvl-poc / #exec-poc could not exist.
    """
    src = CONSOLE.read_text(encoding="utf-8")
    for dom_id, field in (
        ("dr-lvl-poc", "today_poc"),
        ("dr-lvl-vah", "today_vah"),
        ("dr-lvl-val", "today_val"),
        ("exec-poc", "today_poc"),
        ("exec-vah", "today_vah"),
        ("exec-val", "today_val"),
    ):
        assert f'id="{dom_id}"' in src, f"missing #{dom_id}"
        assert src.count(f"pxTxt(d.{field})") >= 2, (
            f"{field} is not painted on both structure-level painters"
        )
        assert f"domIf('{dom_id}'" in src, f"#{dom_id} exists but is not bound"


def test_terrain_hvl_is_never_painted_as_its_own_level():
    """A3/RC-134: terrain `hvl` was the pin under a second name; field removed from payload.
    Client bindings of `.hvl` stay banned. kl_hvl (net peak, 'Net Γ peak') remains legal."""
    for path in (CONSOLE, CHART):
        src = re.sub(r"/\*.*?\*/", "", re.sub(r"//.*$", "", path.read_text(encoding="utf-8"),
                                              flags=re.M), flags=re.S)
        offenders = [(n, line.strip()[:120]) for n, line in enumerate(src.splitlines(), 1)
                     if re.search(r"[a-zA-Z_$][\w$]*\.hvl\b", line)]
        assert offenders == [], (
            f"{path.name}: terrain .hvl bound at a paint site — the pin painted twice under "
            f"a second name (RC-132/134): {offenders}"
        )


def test_kl_hvl_tag_is_net_peak_not_legacy_hvl():
    """RC-134: any tag/label that carries kl_hvl must not say bare HVL (total-gamma name)."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for rel in ("server.py", "live_decision_bundle.py", "liquidity_value_engine.py"):
        src = (root / rel).read_text(encoding="utf-8")
        for n, line in enumerate(src.splitlines(), 1):
            if "kl_hvl" in line and re.search(r'["\']HVL["\']', line):
                offenders.append((rel, n, line.strip()[:100]))
    assert offenders == [], f"kl_hvl still tagged as legacy HVL: {offenders}"


def test_hvl_rebind_injection_is_caught():
    """Negative control for the .hvl scan shape: a re-added ladder binding must match."""
    assert re.search(r"[a-zA-Z_$][\w$]*\.hvl\b", "{ t: 'HVL', v: d.hvl, g: '◇' },"), (
        "the .hvl binding regex no longer matches the shipped shape — the lock is inert"
    )
    assert not re.search(r"[a-zA-Z_$][\w$]*\.hvl\b", "d.kl_hvl"), (
        "kl_hvl tripped the terrain-hvl lock — the net-peak row would be banned by mistake"
    )


def test_unconditional_wall_claim_injection_is_caught():
    """Negative control: the shipped defect's exact shape must fire; conditional text and
    non-wall S/R prose must stay quiet."""
    assert _unconditional_wall_claims(
        "{ key: 'kl_put_gamma_wall', tip: 'Dealer hedging cushions selloffs, acting as support.' }"
    ), "the RC-130 defect shape (single line) went undetected — the label lock is inert"
    assert _unconditional_wall_claims(
        "{ t: 'PUT WALL', v: d.put_wall,\n  tip: 'Dealer hedging supports dips here.' }"
    ), "the split label/claim shape (adjacent lines) evaded the lock"
    assert not _unconditional_wall_claims(
        "tip: 'Put wall: support while spot holds above it.'"
    ), "a properly conditioned wall claim tripped the lock"
    assert not _unconditional_wall_claims(
        "tip: 'A regime boundary, NOT support/resistance.'"
    ), "non-wall prose tripped the wall-claim lock"
    # 2026-08-17: an explicit spot-relative GEOMETRY is the other legitimate condition
    # (RC-354's GSF/GRC state theirs this way and mention the Call Wall descriptively).
    assert not _unconditional_wall_claims(
        "tip: 'GRC: the first level above spot where suppression decays; often at/beyond "
        "the Call Wall.'"
    ), "a level that states its own side of spot tripped the wall-claim lock"
    # …and the geometry vocabulary must not become a free pass: naming a wall and claiming
    # support with NO side-of-spot statement is still the RC-130 defect.
    assert _unconditional_wall_claims(
        "{ t: 'PUT WALL', tip: 'A durable support level for the session.' }"
    ), "the geometry vocabulary widened the lock into accepting an unconditioned claim"

