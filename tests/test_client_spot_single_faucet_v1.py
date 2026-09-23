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
    # RC-REHAB-1 (2026-09-23): the repo-wide dual-source rule ALSO reports this line -- two
    # independent detectors agreeing; the per-page authority finding must be among them.
    per_page = [b for b in bad if b["concept"] == "spot (client)"]
    assert len(per_page) == 1, f"the aliased meta-bar bug went undetected: {bad}"
    assert any(b["concept"] == "spot (client, dual source)" for b in bad), bad
    # Assert the CONTENT, not a line number: an unrelated edit above this point must not be able
    # to fail the lock, or the lock gets weakened to shut it up.
    assert "chart.html:" in per_page[0]["undeclared"][0]
    assert "s.spot" in per_page[0]["undeclared"][0]


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


# test_console_detector_catches_the_defect_it_was_built_for,
# test_console_detector_catches_a_reintroduced_fast_lane_read, and
# test_console_reader_does_not_flag_row_flags were retired here (/console cutover, operator
# directive 2026-09-14): all three anchor on exact legacy static/index.html source strings
# (consoleSpot(), window._fastLaneSpot, a ladder row's `i.spot` flag) that do not exist in the
# new console at all (confirmed: zero matches in static/console.html). The CLIENT_CONCEPTS
# "console_spot" detector these tests exercised (tools/data_faucet_audit.py) is itself
# calibrated only for legacy's shape and provides no real coverage of the new console's actual
# spot-reading code, which lives in static/js/ed-core.js and friends, files this detector never
# scans — flagged for the operator as a discovered, not-fixed gap alongside
# tools/spot_binding_lock.py's equivalent gap (see that file's console_binding_violations
# docstring).


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

# test_console_renders_levels_staleness, test_trusted_badge_cannot_sit_over_stale_levels,
# test_ed_live_spot_delegates_to_the_authority, test_visible_cv2_trust_chip_binds_levels_stale,
# and test_every_trust_chip_binds_levels_stale were retired here (/console cutover, operator
# directive 2026-09-14): all anchor on legacy-only markup/functions (cv2-kl-trust, ct-conf,
# edLiveSpot, the `_lvStale` trusted-badge gate) with zero equivalent in the new console
# (confirmed: no id matching the trust/conf naming class exists in static/console.html at all).
# The underlying invariant -- a trust/confidence indicator must not vouch for stale levels --
# is real and should be reinstated if/when the new console ever paints a confidence badge of
# its own; today it paints none, so there is nothing to bind the check to.
#
# test_cross_page_ticker_carrier_is_wired was retired for a narrower reason: the ticker-carrier
# logic it checked lives inline in legacy static/index.html's own <script>, but the new
# console's equivalent (ed-core.js's setTicker(), which persists to the SAME localStorage key
# via TICKER_KEY) is in an external JS file this test's INDEX.read_text() call never reads --
# console.html itself has almost no inline script. The real invariant (one carrier key, adopted
# at load, written on every commit) is verified live by tests/e2e specs that exercise the
# actual page rather than pattern-matching its source text.


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


# test_rc117_named_victims_are_locked was retired here (/console cutover, operator directive
# 2026-09-14): every named victim it locked (cv2-hd-px, cv2-f-status, ct-foot-status, tv-stamp,
# ct-conf) is legacy-only markup with zero equivalent in the new console (confirmed: none of
# these ids/functions appear in static/console.html). _collapse_js_literal_concat above it is
# a pure helper and is unaffected -- its own test_rc117_concat_built_id_no_longer_evades_the_scan
# exercises it directly with synthetic strings, not any real file.


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
    r"|(?:above|below)\s+spot|(?:above|below)\s+which|first\s+level\s+(?:above|below)"
    # New console's Key Levels rail (/console cutover, 2026-09-14): honestly-disclosed
    # not-yet-computed rows share class="notproven" -- the same semantic exemption as a
    # literal NOT\b, just carried on the markup's class attribute instead of its label
    # text (independent-review finding: "Charm Resistance" -> "→ CHARM WALL" was flagged
    # because its own badge text and both line-window neighbors happened to avoid the word
    # "NOT" verbatim, even though the row is exactly as honestly disclosed as its siblings).
    r'|class="notproven"',
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
    """RC-292: the ABS GAMMA row (formerly GAMMA PIN) must paint the terrain total-gamma SSOT
    key, and no row may resurrect the retired GAMMA PIN label. Repointed to
    static/js/ed-gamma-panels.js (/console cutover, operator directive 2026-09-14): the new
    console's Key Levels rail reads d.absolute_gamma_strike directly (the terrain-scope name,
    not legacy's kl_-prefixed overlay alias -- see test_semantic_faucet_definition_scope_v1.py's
    own repoint for that rename), a real equivalent of the same SSOT binding."""
    panels = (STATIC / "js" / "ed-gamma-panels.js").read_text(encoding="utf-8")
    assert "txt('klAbs', px(d.absolute_gamma_strike));" in panels, (
        "ABS GAMMA no longer binds d.absolute_gamma_strike — the SSOT key"
    )
    assert "GAMMA PIN" not in panels, (
        "a row under the retired GAMMA PIN label returned — the raw concentration "
        "must not paint under an unearned pin claim (RC-292)"
    )


# test_console_today_poc_binds_state_payload_not_a_second_book was retired here (/console
# cutover, operator directive 2026-09-14): today_poc/today_vah/today_val (point of control,
# value area high/low) have no consumer anywhere in the new console at all (grepped
# static/js/*.js and static/console.html, zero matches) -- not a presentation change, a
# dropped capability. Flagged for the operator alongside this cutover's other discovered
# gaps; chart.html's own TODAY_POC consumer (a separate, untouched page) is unaffected.


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



def test_dual_source_spot_rule_covers_every_static_script(tmp_path):
    """RC-REHAB-1 (2026-09-23): the live console's spot reads (static/js/*.js) were in no file
    any client rule scanned. A panel choosing between two payloads' spot is flagged anywhere
    under static/, and a single-payload read with a display fallback is not."""
    from tools.data_faucet_audit import audit_client_dual_source

    js = tmp_path / "static" / "js"
    js.mkdir(parents=True)
    (js / "ed-panel.js").write_text(
        "var a = (strikes && strikes.spot) ?? terrain.spot;\n"
        "var b = d.spot_disp || fmt(d.spot);\n", encoding="utf-8")
    hits = audit_client_dual_source(tmp_path)
    assert [h["undeclared"][0].split(" ")[0] for h in hits] == ["static/js/ed-panel.js:1"], hits


def test_a_concept_whose_authority_is_gone_is_reported_not_passed(monkeypatch):
    """The retired console_spot entry scored clean over a page defining neither authority."""
    import tools.data_faucet_audit as A

    monkeypatch.setitem(A.CLIENT_CONCEPTS, "ghost", {
        "files": ("static/chart.html",), "reader": r"\.spot\b",
        "authorities": ("noSuchAuthority",), "writers": (), "assign_only": r"$^"})
    assert any("guards nothing" in h["undeclared"][0] for h in A.audit_client())
