"""RC-133: NO trade-shaped paint under !tradeable — the Decide direction gate.

MEASURED (operator Decide mandate + audits v10/v13/v26, all grading Decide OUTSTANDING):
resolveHorizonCardVisualState kept per-horizon pills painting up/down (green LONG / red
SHORT arrows, glow) when engineTradeableSetup(d) was FALSE — the 2026-06-11 render
contract explicitly legalized it ("may dim actionability but must not erase horizon
direction"). With the admission registry empty, final_bias is WAIT every session; the
pills were fail-open exposure advice from an engine with nothing admitted.

These tests run the REAL function extracted from static/index.html under node — the
contract is executed, not pattern-matched — plus structural locks that the paint site
cannot reinterpret the gate, and a negative control proving the checker fails the exact
shipped defect shape.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

CONSOLE = Path(__file__).resolve().parent.parent / "static" / "index.html"


def _extract_function(src: str, name: str) -> str:
    i = src.index(f"function {name}(")
    j = src.index("{", i)
    depth, k = 0, j
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                break
    return src[i:k + 1]


def _run_contract(fn_source: str, cases: list[list]) -> list[dict]:
    """Execute a resolveHorizonCardVisualState implementation under node on `cases`
    ([slug, dir, tradeable, confPct]) and return the raw results."""
    node = shutil.which("node")
    assert node, "node is required for the Decide paint-contract lock (RC-133) — do not skip"
    driver = (
        fn_source
        + "\nconst cases = " + json.dumps(cases) + ";\n"
        + "console.log(JSON.stringify(cases.map(c => "
          "resolveHorizonCardVisualState(c[0], c[1], c[2], c[3]))));\n"
    )
    p = subprocess.run([node, "-e", driver], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert p.returncode == 0, f"node execution failed: {p.stderr[:400]}"
    return json.loads(p.stdout.strip().splitlines()[-1])


def _shipped_fn() -> str:
    return _extract_function(CONSOLE.read_text(encoding="utf-8"),
                             "resolveHorizonCardVisualState")


def test_not_tradeable_never_paints_direction():
    """E1: tradeable=false => dim, no glow, no LONG/SHORT text on horizon pills."""
    out = _run_contract(_shipped_fn(), [
        ["5c", "LONG", False, 80],
        ["1c", "SHORT", False, 95],
        ["60c", "LONG", False, None],
        ["consolidated", "FLAT", False, None],
    ])
    for r in out[:3]:
        assert r["state"] == "dim", f"!tradeable painted state={r['state']} — fail-open pill"
        assert r["glow"] == "", f"!tradeable painted glow={r['glow']}"
        assert r["dirText"] == "—", (
            f"!tradeable pill text is {r['dirText']!r} — LONG/SHORT text is trade-shaped paint"
        )
        assert r["nonActionable"] is True, "withheld direction must still explain itself"
    assert out[3]["state"] == "dim" and out[3]["dirText"] == "NEUTRAL"


def test_tradeable_direction_still_paints():
    """E3 quiet control: the gate must not over-blank — tradeable=true keeps direction."""
    out = _run_contract(_shipped_fn(), [
        ["5c", "LONG", True, 80],
        ["5c", "SHORT", True, 50],
        ["consolidated", "LONG", True, 65],
        ["5c", "FLAT", True, None],
        ["5c", "UNAVAILABLE", False, None],
    ])
    assert out[0]["state"] == "up" and out[0]["glow"] == "tf-glow-3" \
        and out[0]["dirText"] == "LONG"
    assert out[1]["state"] == "down" and out[1]["glow"] == "tf-glow-1" \
        and out[1]["dirText"] == "SHORT"
    assert out[2]["state"] == "up" and out[2]["glow"] == "tf-glow-2"
    assert out[3]["state"] == "dim" and out[3]["dirText"] == "NEUTRAL"
    assert out[4]["state"] == "dim" and out[4]["dirText"] == "UNAVAILABLE" \
        and out[4]["nonActionable"] is False


# The exact function that shipped until 2026-07-29 — the defect this lock exists to kill.
# Kept verbatim as a fixture so the checker is proven able to FAIL it (fire control).
_OLD_SHAPE = """
function resolveHorizonCardVisualState(slug, dir, tradeable, confPct) {
  const isConsolidated = slug === 'consolidated';
  let state = 'dim';
  let nonActionable = false;
  if (isConsolidated) {
    if (tradeable && dir === 'LONG') state = 'up';
    else if (tradeable && dir === 'SHORT') state = 'down';
  } else if (dir === 'LONG') {
    state = 'up';
    if (!tradeable) nonActionable = true;
  } else if (dir === 'SHORT') {
    state = 'down';
    if (!tradeable) nonActionable = true;
  }
  let glow = '';
  if (state === 'up' || state === 'down') glow = 'tf-glow-1';
  return { state, glow, sigDir: 'long', nonActionable, dirText: dir };
}
"""


def test_old_fail_open_shape_fires_the_contract():
    """E3 fire control: run the SHIPPED-DEFECT function through the same contract — it must
    violate. If this stops failing the old shape, the lock has gone inert."""
    out = _run_contract(_OLD_SHAPE, [["5c", "LONG", False, 80]])
    assert out[0]["state"] == "up", "fixture drifted — no longer reproduces the defect"
    # ...and the contract assertion used in test_not_tradeable_never_paints_direction
    # would therefore FAIL on it:
    assert not (out[0]["state"] == "dim" and out[0]["glow"] == ""), (
        "the checker passed the fail-open shape — the lock is inert"
    )


def test_paint_site_cannot_reinterpret_the_gate():
    """E2 structural: every direction-shaped pixel on the horizon row derives from the one
    contract helper; the legalizing 2026-06-11 sentence is gone; tags are gated."""
    src = CONSOLE.read_text(encoding="utf-8")
    assert "must not erase horizon direction" not in src, (
        "the 2026-06-11 contract that legalized LONG paint under !tradeable is back"
    )
    assert "const visual = resolveHorizonCardVisualState(" in src, (
        "the horizon paint site no longer routes through the contract helper"
    )
    assert "dirEl.textContent = visual.dirText" in src, (
        "the direction text is set outside the contract — a site can paint LONG on its own"
    )
    assert "tradeable ? deriveTag(slug, dir) : null" in src, (
        "AGREE/CONFLICT/PRIMARY tags escaped the gate — their titles print directions"
    )
    assert "planTradeable ? dir : 'FLAT'" in src, (
        "the PLAN card no longer FLATs its direction under !tradeable"
    )
    # the tf-state- class family is assembled at exactly three censused sites, all gated:
    # the horizon row (contract helper) and paintTradePlanCard's veto + normal branches
    # (both fed by planTradeable-gated state). A fourth site is an unreviewed escape.
    hits = re.findall(r"'tf-signal-card tf-state-'", src)
    assert len(hits) == 3, (
        f"tf-state- class assembly sites changed ({len(hits)} != 3) — census the new site "
        "and route it through the gate before this number moves"
    )
