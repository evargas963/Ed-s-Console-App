"""RC-200 — Exposure Overlay tab v1 contracts (operator #1 project, LIVE 2026-08-02).

Binds the shipped surface to its producers and to the §R.5 honesty ledger: real endpoints
only, absences labeled, no client-side second producers, Decide untouched.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# RC-367: this suite reads and asserts on the exposure page end-to-end (producers,
# honesty ledger, lane resolver) — declare ownership so the turn audit maps
# static/exposure.html changes to a running suite instead of an unknown owner.



def _src() -> str:
    return (REPO / "static" / "exposure.html").read_text(encoding="utf-8")


def test_page_exists_with_static_surfaces():
    src = _src()
    for vid in ("cv", "lv", "ranked", "hedge", "dq", "clocks", "theme-btn", "tk",
                "ov-dots", "ov-bubbles", "ov-vwap", "ov-king", "ov-charm"):
        assert f'id="{vid}"' in src, f"#{vid} missing from static/exposure.html"


def test_reads_real_producers_only():
    src = _src()
    for ep in ("/api/bars1m?ticker=", "/api/terrain/strikes?ticker=", "/api/terrain?ticker=",
               "/api/forces?ticker=", "/api/liquidity-snapshot?ticker="):
        assert ep in src, f"page does not read {ep}"
    assert "kl_" not in src, "analytics-family kl_* keys bound — second payload faucet (RC-75 class)"


def test_honesty_ledger_on_the_face():
    """§R.5: absences labeled, never silently omitted or faked."""
    src = _src()
    assert "banked view (next)" in src, "call/put split absence is not labeled in the tooltip"
    assert "live-accrual" in src, "bubble layer does not declare its accrual-only nature"
    assert "Δ nightly" in src or "&Delta; nightly" in src, "OI staleness clock missing"
    assert "never a forecast" in src, "hedge-flow sentence lost its mechanical framing"
    assert "UNPROVEN" in src and "Decide WAIT" in src, "signal/decision posture missing"


def test_charm_is_payload_driven_never_vote_gated():
    """RC-199: the vote gate is revoked. Charm reads the REAL /api/forces keys and its only
    two states are fields-served (renders) and fields-not-served (says so)."""
    src = _src()
    assert "charm_below" in src and "charm_above" in src, (
        "charm overlay does not read the real payload fields")
    assert "charm_book_scope" in src, "the book label is not read from the payload (RC-184)"
    assert "fields not served" in src, "no honest absence state for missing charm fields"
    assert "on vote" not in src and "operator vote" not in src.lower(), (
        "vote-gate language survives on the exposure surface (RC-199 revoked it)")
    ssrc = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    for key in ('"charm_below"', '"charm_above"', '"charm_book_scope"'):
        assert key in ssrc, f"/api/forces no longer serves {key}"


def test_charm_error_is_stated_on_the_charm_line():
    """RC-305: /api/forces serves `charm_error` — the qualifier that says WHY charm is
    absent — and this surface rendered a FAILED charm exactly like fields never served.
    The gates line now states the served error (same `charm failed:` phrasing as the
    chart's forces_provenance idiom), and absence stays honest: no error served means the
    plain not-served line, never a fabricated failure."""
    src = _src()
    assert "charm_error" in src, "the exposure surface never reads the served charm_error"
    assert "charm failed:" in src, "a failed charm does not say so on the gates line"
    assert "fields not served" in src, (
        "the no-error absence state was lost — absence must stay distinct from failure")
    ssrc = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    assert '"charm_error"' in ssrc, "/api/forces no longer serves charm_error"


def test_theme_is_the_shared_cv2_system():
    src = _src()
    assert "ed_theme" in src and "body.light" in src, "theme does not follow the app"
    assert "cv-tab" in src, "nav is not the Console's tab component"
    assert "refreshPal" in src, "canvas is not theme-aware"


def test_server_route_serves_the_page():
    ssrc = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    assert '"/exposure"' in ssrc and "exposure.html" in ssrc, "no /exposure route"


def test_chart_nav_links_the_new_tab():
    csrc = (REPO / "static" / "chart.html").read_text(encoding="utf-8")
    assert 'href="/exposure"' in csrc, "chart nav has no Exposure entry"


def test_chart_charm_and_bias_live_contract():
    """RC-199 VISIBLE_SURFACE binding: the FORCES charm row is emitted at runtime from the
    `id="fr-${id}"` template and reads the REAL payload keys; Bias is the static #f-bias and
    says WAIT (empty admissions), never LOCKED; no vote language anywhere in the source."""
    csrc = (REPO / "static" / "chart.html").read_text(encoding="utf-8")
    assert 'id="fr-' in csrc, "the FORCES row id template vanished — fr-charm unreachable"
    assert "fz.charm_below" in csrc and "fz.charm_above" in csrc, (
        "the chart charm row does not read the real /api/forces keys")
    assert "charm_book_scope" in csrc, "the charm book label is not read from the payload"
    assert 'id="f-bias"' in csrc and "WAIT" in csrc, "Bias is not the honest WAIT surface"
    assert "operator charm vote" not in csrc and "on vote" not in csrc, (
        "vote-gate language survives in chart.html (RC-199 revoked it)")


def test_no_client_side_level_derivation():
    """RC-80: king/ranked come from argmax/sort over SERVED rows; HVL (a derived level the
    engine does not own yet) must not be computed here."""
    src = _src()
    assert "hvl" not in src.lower(), "HVL derived client-side — engine must own it first"
    assert "compute_gamma" not in src


def test_decide_untouched_admissions_empty():
    import json
    reg = json.loads((REPO / "governance" / "decision_path_admissions.json").read_text(encoding="utf-8"))
    admitted = reg.get("admissions") or reg.get("admitted") or []
    assert admitted == [], f"decision path is no longer empty: {admitted}"


def test_rc355_lane_resolver_never_overlaps_and_is_wired():
    """RC-355: the canvas lane resolver yields pairwise non-intersecting label lanes,
    and every de-conflicted text draw actually routes through laneL/laneB (executed in
    node against the REAL _claimLane extracted from exposure.html, not a re-implementation)."""
    import re
    import subprocess

    src = (REPO / "static" / "exposure.html").read_text(encoding="utf-8")
    m = re.search(r"function _claimLane\(reg, want, h\) \{.*?\n      \}", src, re.S)
    assert m, "_claimLane must exist in exposure.html draw()"
    fn = m.group(0)
    # wired: the five de-conflicted draws route through the lanes
    assert src.count("laneL(") >= 4, "left-column banners must claim lanes"
    assert src.count("laneB(") >= 1, "bubble labels must claim lanes"
    driver = (
        "const H=600, PADB=30;\n" + fn + "\n"
        "const reg=[]; const wants=[100,104,101,108,99,100,300,300,300,585,590,592];\n"
        "const got=wants.map(w=>_claimLane(reg,w,14));\n"
        "for(let i=0;i<got.length;i++)for(let j=i+1;j<got.length;j++){\n"
        "  if(Math.abs(got[i]-got[j])<14) throw new Error('overlap '+got[i]+' vs '+got[j]);\n"
        "  if(got[i]>H-PADB-4+0.001) throw new Error('below clamp');\n"
        "}\n"
        "console.log('LANES OK '+got.join(','));\n"
    )
    p = subprocess.run(["node", "-e", driver], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    assert p.returncode == 0, f"lane resolver failed: {p.stderr[:400]}"
    assert "LANES OK" in p.stdout
