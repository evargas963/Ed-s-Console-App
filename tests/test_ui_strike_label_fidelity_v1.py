"""UI STRIKE FIDELITY — a displayed strike must be a strike that EXISTS (2026-08-26).

WHAT WAS FOUND. Every strike-valued label in both trading surfaces rendered through fmt(k, 0) --
Number(k).toFixed(0) -- which ROUNDS. A real 322.5 strike printed as "323": a price at which no
contract trades. It reached the CALL WALL / PUT WALL chips, the NET GEX PEAK callout, the ranked
level list and the coach lines, so the console named levels the operator cannot act on.

WHY IT SURVIVED, and why that is the point. SPY, QQQ and IWM trade whole-dollar ladders, so on the
three tickers anyone looks at most the rounding is invisible. Measured live on 2026-08-26:
TSLA/AAPL/META/NVDA all trade a 2.5 ladder; XRT/CDE/CIFR/SMCI/KRE/PCG a 0.5 one. The defect was
CORE-TICKER-SHAPED -- correct on the anchors, wrong on everything else -- which is exactly the
class of assumption this suite exists to catch.

The second defect was the label GATE: below 12px per band it drew a label only when
`Math.round(k) === k && k % 5 === 0`, i.e. only whole-dollar strikes divisible by five. On a 2.5
ladder that is one label in two; on a 0.5 ladder one in ten. An operator reading that axis sees a
whole-dollar ladder and reasonably concludes the chain has no half-dollar strikes.

HOW THIS IS TESTED. The formatter is not re-implemented in Python and asserted about -- that would
prove nothing about the shipped page. The real function is extracted from the real HTML and
EXECUTED under node, so what passes here is the code the browser runs.
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
SURFACES = ("static/chart.html", "static/exposure.html")

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is required to execute the shipped UI code")


def _script(rel: str) -> str:
    src = (REPO / rel).read_text(encoding="utf-8")
    return "\n".join(re.findall(r"<script>(.*?)</script>", src, re.S))


def _fmt_strike_source(rel: str) -> str:
    js = _script(rel)
    i = js.find("const fmtStrike")
    assert i >= 0, f"{rel} has no fmtStrike — the strike formatter was removed"
    return js[i:js.find("};", i) + 2]


def _run_node(body: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "probe.js"
        p.write_text(body, encoding="utf-8")
        r = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"node failed: {r.stderr[:800]}"
        return r.stdout


@pytest.mark.parametrize("rel", SURFACES)
def test_the_shipped_script_still_parses(rel: str):
    """An unparseable page renders nothing; the label fix must not have broken the surface."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.js"
        p.write_text(_script(rel), encoding="utf-8")
        r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{rel} script block is not valid JS:\n{r.stderr[:1200]}"


@pytest.mark.parametrize("rel", SURFACES)
def test_a_displayed_strike_round_trips_to_the_same_number(rel: str):
    """THE INVARIANT. Whatever is displayed must parse back to the strike we were given.

    This is the honest form of the requirement: not "has decimals" but "names the same price".
    Real ladders measured live on 2026-08-26 are covered -- 1.0, 2.5, 0.5 -- plus 0.25 and 0.125
    for instruments this console has not met yet, and index-scale values.
    """
    cases = [320.0, 322.5, 17.25, 7457.69, 0.5, 1.125, 187.5, 2.5, 1180.0, 96.5, 42.0]
    body = _fmt_strike_source(rel) + "\n" + (
        f"const cases = {json.dumps(cases)};\n"
        "console.log(JSON.stringify(cases.map(c => fmtStrike(c))));\n"
    )
    shown = json.loads(_run_node(body).strip())
    for want, got in zip(cases, shown, strict=True):
        assert float(got) == pytest.approx(want), (
            f"{rel}: strike {want} displays as {got!r}, which is a DIFFERENT price — the console "
            f"would be naming a level that does not exist")


@pytest.mark.parametrize("rel", SURFACES)
def test_fractional_strikes_are_not_rounded_to_whole_dollars(rel: str):
    """The exact reported symptom: 'TSLA appears to show only whole-dollar strikes.'"""
    body = _fmt_strike_source(rel) + "\n" + (
        "console.log(JSON.stringify([322.5, 327.5, 16.5, 187.5].map(fmtStrike)));\n"
    )
    shown = json.loads(_run_node(body).strip())
    assert shown == ["322.5", "327.5", "16.5", "187.5"], (
        f"{rel}: fractional strikes render as {shown} — a half-dollar strike is being shown as a "
        f"whole dollar, which is what made TSLA look like a whole-dollar ladder")


@pytest.mark.parametrize("rel", SURFACES)
def test_no_strike_valued_label_still_goes_through_the_rounding_formatter(rel: str):
    """Guard the whole class, not the instances that were fixed.

    fmt(x, 0) is legitimate for counts and dollar magnitudes; it is never legitimate for a strike.
    This fails if a strike-valued expression is routed back through it.
    """
    js = _script(rel)
    js = re.sub(r"^\s*//.*$", "", js, flags=re.M)          # drop comments (they discuss the bug)
    offenders = re.findall(
        r"fmt\(\s*(k|kk|strike|selRow\[0\]|king\[0\]|near\[0\]|r\[0\]|d\[0\]|row\[0\]|"
        r"T\.call_wall|T\.put_wall|T\.gamma_flip|T\.pin)\s*,\s*0\s*\)", js)
    assert not offenders, (
        f"{rel}: strike-valued labels routed through the rounding formatter again: {offenders}. "
        f"Use fmtStrike -- a rounded strike names a price that does not trade.")


def test_the_strike_axis_label_gate_carries_no_instrument_geometry():
    """The gate must not privilege whole-dollar or multiple-of-five strikes.

    The original condition was `bandW >= 12 || (Math.round(k) === k && Math.round(k) % 5 === 0)`,
    which is instrument geometry inside a label rule: it labels a 1.0 ladder fully and a 0.5
    ladder one strike in ten. Thinning must be geometric (pixels), never value-based.
    """
    js = _script("static/chart.html")
    js = re.sub(r"^\s*//.*$", "", js, flags=re.M)
    assert "% 5 === 0" not in js and "%5===0" not in js.replace(" ", ""), (
        "a multiple-of-five strike rule is back in chart.html — that is ticker geometry baked "
        "into a label gate")
    assert "gLabelEvery" in js, "the geometric label-thinning stride is gone"
    assert "measureText" in js, (
        "label thinning no longer measures the rendered label — without it the stride is a guess "
        "and variable-width labels ('320' vs '322.5') overlap or over-thin")
