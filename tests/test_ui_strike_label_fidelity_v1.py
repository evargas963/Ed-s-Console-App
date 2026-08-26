"""STRIKE DISPLAY — ONE producer, many consumers, and a displayed strike must exist (2026-08-26).

WHAT WAS FOUND. The rule for turning a strike into text existed once PER SURFACE, and was wrong in
a different way on each:

    static/chart.html     fmt(k, 0)                      322.5 -> "323"     WRONG
    static/exposure.html  fmt(k, 0)                      322.5 -> "323"     WRONG
    static/index.html     r.k.toFixed(1)                 17.25 -> "17.3"    WRONG
    static/chart.html:1634 fmt(r[0], isInt ? 0 : 2)      322.5 -> "322.50"  correct
    market_state.py x2    str(int(k)) if is_integer()    322.5 -> "322.5"   correct, inlined twice

Four browser surfaces, four rules, one right. That is what a duplicated computation buys, so the
fix is not four corrected copies -- it is ONE PRODUCER: static/js/strike_format.js for the browser
and instrument_identity.format_strike_for_display for the server, asserted here to agree.

WHY THE ROUNDING MATTERS. toFixed(0) does not drop a decimal, it picks a different number (ECMA-262
rounds .5 to the larger n). Two harms: FABRICATION -- the console names a price at which no
contract trades, and this reached the CALL WALL / PUT WALL chips and the NET GEX PEAK banner, not
just axis ticks; and COLLISION -- on a 0.5 ladder two adjacent real strikes print the same label
(22.5 and 23.0 both "23"), erasing one from the display.

WHY IT SURVIVED. SPY/QQQ/IWM trade whole-dollar ladders, so on the three tickers everyone watches
the rounding is invisible. Measured live 2026-08-26: TSLA/AAPL/META/NVDA trade a 2.5 ladder,
XRT/CDE/CIFR/SMCI/KRE/PCG a 0.5 one. The defect was CORE-TICKER-SHAPED.

HOW THIS IS TESTED. The shipped functions are EXECUTED -- the JS under node, the Python imported --
not reimplemented and asserted about. What passes here is the code that runs.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PRODUCER_JS = REPO / "static" / "js" / "strike_format.js"

#: Every browser surface that renders a strike value must CONSUME the producer, never define one.
CONSUMER_SURFACES = ("static/chart.html", "static/exposure.html", "static/index.html")

#: Ladders measured live on 2026-08-26, plus finer ones this console has not met yet.
REAL_LADDERS = [320.0, 322.5, 325.0, 17.25, 7457.69, 0.5, 1.125, 187.5, 2.5, 1180.0, 96.5, 42.0]

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is required to execute the shipped browser code")


def _script(rel: str) -> str:
    src = (REPO / rel).read_text(encoding="utf-8")
    return "\n".join(re.findall(r"<script>(.*?)</script>", src, re.S))


def _run_node(body: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "probe.js"
        p.write_text(body, encoding="utf-8")
        r = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"node failed: {r.stderr[:900]}"
        return r.stdout


def _js_format(values: list) -> list[str]:
    """Run the REAL producer file under node against these values."""
    body = (PRODUCER_JS.read_text(encoding="utf-8")
            + "\nconst __v = " + json.dumps(values) + ";\n"
            + "console.log(JSON.stringify(__v.map(v => globalThis.fmtStrike(v))));\n")
    return json.loads(_run_node(body).strip())


# ── ONE PRODUCER ────────────────────────────────────────────────────────────────────────────

def test_the_browser_producer_exists_and_is_the_only_definition():
    """No surface may define its own strike formatter — that is how they drifted apart."""
    assert PRODUCER_JS.is_file(), "the shared strike formatter is gone"
    for rel in CONSUMER_SURFACES:
        js = re.sub(r"^\s*//.*$", "", _script(rel), flags=re.M)
        assert "fmtStrike =" not in js and "function fmtStrike" not in js, (
            f"{rel} defines its own fmtStrike — one displayed strike is one computation; "
            f"consume static/js/strike_format.js instead")


def test_every_consumer_surface_loads_the_producer():
    """A consumer that renders a strike without loading the producer throws at runtime."""
    for rel in CONSUMER_SURFACES:
        src = (REPO / rel).read_text(encoding="utf-8")
        assert "/static/js/strike_format.js" in src, (
            f"{rel} renders strikes but does not load the producer")
        # ...and it must load BEFORE the inline script that calls it.
        tag = src.index("/static/js/strike_format.js")
        first_inline = src.index("<script>")
        assert tag < first_inline, (
            f"{rel} loads the producer after its inline script — fmtStrike would be undefined")


@needs_node
def test_server_and_browser_producers_agree_exactly():
    """Two runtimes, ONE rule. A shared rule that drifts between them is two rules again."""
    from instrument_identity import format_strike_for_display

    js = _js_format(REAL_LADDERS)
    py = [format_strike_for_display(v) for v in REAL_LADDERS]
    assert js == py, (
        f"browser and server disagree about how a strike is written.\n"
        f"  js: {js}\n  py: {py}")


# ── THE INVARIANT ───────────────────────────────────────────────────────────────────────────

@needs_node
def test_a_displayed_strike_round_trips_to_the_same_number():
    """Not 'has decimals' -- names the SAME price. That is the honest requirement."""
    shown = _js_format(REAL_LADDERS)
    for want, got in zip(REAL_LADDERS, shown, strict=True):
        assert float(got) == pytest.approx(want), (
            f"strike {want} displays as {got!r} — a DIFFERENT price; the console would be naming "
            f"a level that does not exist")


@needs_node
def test_fractional_strikes_are_not_rounded_to_whole_dollars():
    """The exact reported symptom: 'TSLA appears to show only whole-dollar strikes.'"""
    assert _js_format([322.5, 327.5, 16.5, 187.5]) == ["322.5", "327.5", "16.5", "187.5"]


@needs_node
def test_adjacent_strikes_on_a_half_dollar_ladder_never_collide():
    """COLLISION harm: rounding made 22.5 and 23.0 both print '23', erasing a real strike."""
    ladder = [22.0, 22.5, 23.0, 23.5, 24.0]
    shown = _js_format(ladder)
    assert len(set(shown)) == len(ladder), (
        f"a 0.5 ladder collapses to {shown} — two real strikes share one label, so one vanishes "
        f"from the display entirely")


def test_python_producer_round_trips_and_handles_junk():
    from instrument_identity import format_strike_for_display

    for v in REAL_LADDERS:
        assert float(format_strike_for_display(v)) == pytest.approx(v)
    for junk in (None, "", "abc", float("nan"), float("inf")):
        assert format_strike_for_display(junk) == "—", (
            f"{junk!r} produced a number — junk must not render as a price")


# ── CLASS GUARDS ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", CONSUMER_SURFACES)
def test_no_strike_valued_label_goes_through_a_rounding_formatter(rel: str):
    """Guard the CLASS, not the instances that were fixed.

    fmt(x, 0) is fine for counts and dollar magnitudes; never for a strike.
    """
    js = re.sub(r"^\s*//.*$", "", _script(rel), flags=re.M)
    offenders = re.findall(
        r"fmt\(\s*(k|kk|strike|selRow\[0\]|king\[0\]|near\[0\]|r\[0\]|d\[0\]|row\[0\]|"
        r"T\.call_wall|T\.put_wall|T\.gamma_flip|T\.pin)\s*,\s*0\s*\)", js)
    assert not offenders, (
        f"{rel}: strike-valued labels routed through a rounding formatter again: {offenders}")
    # index.html's terrain map used toFixed(1), which truncates rather than rounds.
    assert not re.search(r"\br\.k\.toFixed\(", js), (
        f"{rel}: the terrain strike label is formatting r.k directly again — use fmtStrike")


def test_the_strike_axis_label_gate_carries_no_instrument_geometry():
    """Thinning must be geometric (pixels), never value-based.

    The original gate labelled only whole-dollar strikes divisible by five below 12px per band:
    a 1.0 ladder fully, a 0.5 ladder one strike in ten.
    """
    js = re.sub(r"^\s*//.*$", "", _script("static/chart.html"), flags=re.M)
    assert "%5===0" not in js.replace(" ", ""), (
        "a multiple-of-five strike rule is back in chart.html — ticker geometry in a label gate")
    assert "gLabelEvery" in js, "the geometric label-thinning stride is gone"
    assert "measureText" in js, (
        "label thinning no longer measures the rendered label — the stride would be a guess and "
        "variable-width labels ('320' vs '322.5') overlap or over-thin")


@pytest.mark.parametrize("rel", CONSUMER_SURFACES)
@needs_node
def test_the_shipped_script_still_parses(rel: str):
    """An unparseable page renders nothing."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.js"
        p.write_text(_script(rel), encoding="utf-8")
        r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{rel} script block is not valid JS:\n{r.stderr[:1200]}"


def test_the_server_producer_has_no_second_implementation():
    """market_state inlined this rule twice; nothing may inline it again."""
    import inspect

    import market_state

    src = inspect.getsource(market_state)
    src = re.sub(r"^\s*#.*$", "", src, flags=re.M)
    assert "format_strike_for_display" in src, "market_state no longer uses the one producer"
    assert not re.search(r"str\(int\([^)]*\)\)\s*if\s+[^\n]*is_integer\(\)", src), (
        "the strike-to-text rule is inlined in market_state again — import the producer")
