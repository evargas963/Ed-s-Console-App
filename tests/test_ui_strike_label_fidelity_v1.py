"""STRIKE DISPLAY — ONE COMPUTATION, repo-wide. The browser renders; it does not derive.

WHAT WAS FOUND. The rule for turning a strike into text existed once PER SURFACE and was wrong in
a different way on each:

    static/chart.html      fmt(k, 0)                    322.5 -> "323"      WRONG
    static/exposure.html   fmt(k, 0)                    322.5 -> "323"      WRONG
    static/index.html      r.k.toFixed(1)               17.25 -> "17.3"     WRONG  (terrain map)
    static/chart.html:1634 fmt(r[0], isInt ? 0 : 2)     322.5 -> "322.50"   correct, and alone
    market_state.py x2     str(int(k)) if is_integer()  322.5 -> "322.5"    correct, inlined twice

WHY ROUNDING IS NOT COSMETIC. toFixed(0) does not drop a decimal, it picks a different number.
FABRICATION: the console names a price at which no contract trades — this reached the CALL WALL /
PUT WALL chips and the NET GEX PEAK banner. COLLISION: on a 0.5 ladder two adjacent real strikes
print the same label, erasing one from the display. Measured on the live CDE ladder (40 strikes):
the old rule produced 26 distinct labels — 14 real strikes erased — and 16 of 40 named a different
price.

WHY IT SURVIVED. SPY/QQQ/IWM trade whole-dollar ladders, so on the three tickers everyone watches
it is invisible. Measured live 2026-08-26: TSLA/AAPL/META/NVDA on 2.5, XRT/CDE/CIFR/SMCI/KRE/PCG on
0.5. Core-ticker-shaped — right on the anchors, wrong on everything else.

THE FIX, AND WHY THE FIRST ONE WAS NOT ENOUGH. A first pass gave each surface a corrected
formatter, then a shared JS module. Both were still a SECOND implementation of one semantic, kept
in step by a parity test — and a rule that needs a test to stay synchronised is two computations,
not one. So the browser-side formatter was DELETED. instrument_identity.format_strike_for_display
is the only implementation repo-wide; the server emits the text (per-strike row index 3, and
`strike_labels` on the terrain payload) and every surface RENDERS it.

These tests enforce that shape, not merely the arithmetic: a surface that starts computing a label
again fails here even if its arithmetic is correct.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SURFACES = ("static/chart.html", "static/exposure.html", "static/index.html")

#: Ladders measured live 2026-08-26, plus finer ones this console has not met yet.
REAL_LADDERS = [320.0, 322.5, 325.0, 17.25, 7457.69, 0.5, 1.125, 187.5, 2.5, 1180.0, 96.5, 42.0]

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is required to parse the shipped browser code")


def _script(rel: str) -> str:
    src = (REPO / rel).read_text(encoding="utf-8")
    return "\n".join(re.findall(r"<script>(.*?)</script>", src, re.S))


def _script_no_comments(rel: str) -> str:
    return re.sub(r"^\s*//.*$", "", _script(rel), flags=re.M)


# ── ONE COMPUTATION ─────────────────────────────────────────────────────────────────────────

def test_no_browser_surface_implements_a_strike_formatter():
    """THE INVARIANT. Not 'the copies agree' — there must be no copy.

    A JS re-implementation kept in step by a parity test is still a second computation of one
    semantic. The rule lives once, on the server.
    """
    for rel in SURFACES:
        js = _script_no_comments(rel)
        assert "fmtStrike" not in js, (
            f"{rel} references a browser-side strike formatter. The server computes the label "
            f"(instrument_identity.format_strike_for_display); this page must render it.")
        # ...and no surface may hand-roll the arithmetic under another name.
        bad = re.findall(r"\.toFixed\(\s*\d\s*\)\s*[^;\n]{0,40}(?:strike|\br\.k\b)", js)
        assert not bad, f"{rel} formats a strike numerically again: {bad}"


def test_the_browser_producer_file_is_gone():
    """It existed briefly; leaving it would invite a surface to load it again."""
    assert not (REPO / "static" / "js" / "strike_format.js").exists(), (
        "static/js/strike_format.js is back — the browser must not carry a second implementation")
    for rel in SURFACES:
        assert "strike_format.js" not in (REPO / rel).read_text(encoding="utf-8"), (
            f"{rel} still loads the deleted browser formatter")


def test_the_server_has_exactly_one_implementation():
    import inspect

    import instrument_identity
    import market_state

    prod = inspect.getsource(instrument_identity)
    assert prod.count("def format_strike_for_display") == 1

    for mod, src in (("market_state", inspect.getsource(market_state)),):
        clean = re.sub(r"^\s*#.*$", "", src, flags=re.M)
        assert "format_strike_for_display" in clean, f"{mod} no longer uses the one producer"
        assert not re.search(r"str\(int\([^)]*\)\)\s*if\s+[^\n]*is_integer\(\)", clean), (
            f"{mod} inlines the strike-to-text rule again — import the producer")


# ── THE COMPUTATION ITSELF ──────────────────────────────────────────────────────────────────

def test_a_displayed_strike_round_trips_to_the_same_number():
    """Not 'has decimals' — names the SAME price."""
    from instrument_identity import format_strike_for_display

    for v in REAL_LADDERS:
        shown = format_strike_for_display(v)
        assert float(shown) == pytest.approx(v), (
            f"strike {v} displays as {shown!r} — a DIFFERENT price; the console would name a "
            f"level that does not exist")


def test_fractional_strikes_are_not_rounded_to_whole_dollars():
    """The reported symptom: 'TSLA appears to show only whole-dollar strikes.'"""
    from instrument_identity import format_strike_for_display

    assert [format_strike_for_display(k) for k in (322.5, 327.5, 16.5, 187.5)] == \
        ["322.5", "327.5", "16.5", "187.5"]


def test_adjacent_strikes_on_a_half_dollar_ladder_never_collide():
    """COLLISION harm: rounding made 22.5 and 23.0 both print '23', erasing a real strike."""
    from instrument_identity import format_strike_for_display

    ladder = [22.0, 22.5, 23.0, 23.5, 24.0]
    shown = [format_strike_for_display(k) for k in ladder]
    assert len(set(shown)) == len(ladder), f"a 0.5 ladder collapses to {shown}"


def test_junk_never_renders_as_a_price():
    from instrument_identity import format_strike_for_display

    for junk in (None, "", "abc", float("nan"), float("inf"), float("-inf")):
        assert format_strike_for_display(junk) == "—"


# ── THE WIRE CONTRACT ───────────────────────────────────────────────────────────────────────

def test_the_server_emits_a_label_with_every_per_strike_row():
    """Index 3 is the contract the surfaces consume. Losing it silently un-labels every ladder."""
    import inspect

    import server

    src = inspect.getsource(server.get_terrain_strikes)
    assert "format_strike_for_display" in src, (
        "/api/terrain/strikes no longer attaches a label to each per-strike row")


def test_the_terrain_payload_carries_labels_for_level_scalars():
    """The wall chips are not rows; they need their own labels from the same producer."""
    import inspect

    import server

    src = inspect.getsource(server._terrain_refresh_one)
    assert '"strike_labels"' in src, "the terrain payload no longer carries strike_labels"
    # Assert the DECLARED SET, not the function's source text. The emission now iterates
    # server.STRIKE_VALUED_PAYLOAD_KEYS, so a substring test would pass or fail on where the
    # list happens to live rather than on what is labelled.
    keys = set(server.STRIKE_VALUED_PAYLOAD_KEYS)
    for key in ("call_wall", "put_wall", "absolute_gamma_strike", "key_delta_strike",
                "net_gex_peak", "max_pain", "hvp", "lvp",
                "call_charm_wall", "put_charm_wall", "call_delta_wall", "put_delta_wall"):
        assert key in keys, f"strike_labels omits the strike {key}"
    # MEASURED 2026-08-26 against the live Schwab grid over 20 tickers: gamma_flip 0/11
    # on-grid, gsf 0/14, grc 0/3. They are interpolated CONTINUOUS prices, not vendor
    # strikes, and labelling them put a computed price under the vendor-truth rule -
    # printing "350.6" where every price on the page prints "350.60".
    for key in ("gamma_flip", "gsf", "grc"):
        assert key not in keys, (
            f"{key} is a continuous price, not a strike; it must not carry a strike label")


@pytest.mark.parametrize("rel", SURFACES)
def test_surfaces_consume_the_label_and_fall_back_to_the_raw_value(rel: str):
    """A missing label must degrade to the raw number, never to a fabricated one or 'undefined'."""
    js = _script_no_comments(rel)
    if rel == "static/index.html":
        assert "r.lbl" in js, f"{rel} does not read the server's per-strike label"
        assert "klLabelOf" in js, f"{rel} does not read the server's level labels"
        # The lookup must NOT format. A unit that knows about strikes AND renders text is a
        # second producer - this repo's own ONE FAUCET gate flagged exactly that when these
        # two jobs shared one helper. Formatting lives in klPx, which knows nothing of strikes.
        i = js.find("function klLabelOf")
        body = js[i:js.find("}", i)]
        assert "toFixed" not in body, (
            "the strike lookup formats; that makes it a second producer of strike text")
    elif rel == "static/chart.html":
        assert "strikeText" in js, f"{rel} does not consume a label"
    else:
        assert "strikeLabel" in js, f"{rel} does not consume a label"


# ── CLASS GUARDS ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", SURFACES)
def test_no_strike_valued_label_goes_through_a_rounding_formatter(rel: str):
    js = _script_no_comments(rel)
    offenders = re.findall(
        r"fmt\(\s*(k|kk|strike|selRow\[0\]|king\[0\]|near\[0\]|r\[0\]|d\[0\]|row\[0\]|"
        r"T\.call_wall|T\.put_wall|T\.gamma_flip|T\.pin)\s*,\s*0\s*\)", js)
    assert not offenders, f"{rel}: strike labels routed through a rounding formatter: {offenders}"
    assert not re.search(r"\br\.k\.toFixed\(", js), f"{rel}: terrain label formatted directly"


def test_the_strike_axis_label_gate_carries_no_instrument_geometry():
    """Thinning must be geometric (pixels), never value-based.

    The original gate labelled only whole-dollar strikes divisible by five below 12px per band:
    a 1.0 ladder fully, a 0.5 ladder one strike in ten.
    """
    js = _script_no_comments("static/chart.html")
    assert "%5===0" not in js.replace(" ", ""), "a multiple-of-five strike rule is back"
    assert "gLabelEvery" in js, "the geometric label-thinning stride is gone"
    assert "measureText" in js, "label thinning no longer measures the rendered label"


@pytest.mark.parametrize("rel", SURFACES)
@needs_node
def test_the_shipped_script_still_parses(rel: str):
    """An unparseable page renders nothing."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.js"
        p.write_text(_script(rel), encoding="utf-8")
        r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{rel} script block is not valid JS:\n{r.stderr[:1200]}"


def test_the_label_is_not_persisted_into_the_per_strike_row():
    """A display artifact has no business in option_chain_accrual.

    The label is attached at the API boundary. Putting it in the persisted row would change the
    stored shape and bloat every banked minute with derivable text.
    """
    import inspect

    import terrain_engine

    src = inspect.getsource(terrain_engine._per_strike_rows)
    assert "format_strike_for_display" not in src, (
        "the persisted per-strike row builder is attaching a display label — that belongs at the "
        "API boundary, not in stored data")
