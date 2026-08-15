# institutional-synthetic-ok: static-asset and call-site assertions over the shipped landing
# page; there is no market data in this surface to exercise with real inputs.
"""Axiom brand landing integration (mission axiom-brand-landing-v1, RC-249).

The load-bearing assertion is the DISMISSAL CALL SITE. The integration spec said to dismiss
"after first successful accepted full render via _renderMoneyPathCore success return true" —
but that function has TWO `return true` sites, and the earlier one is the
`_shouldSkipTierCCardRender` duplicate-fingerprint SKIP, which returns true having painted
NOTHING. Wiring to the return VALUE rather than the accepted BRANCH would uncover an unpainted
console on any duplicate Tier-C payload: exactly the failure the spec's own
DOMContentLoaded / SSE-onopen / quote-only exclusions exist to prevent.

A splash is a promise that pixels exist underneath it. These tests hold that promise.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INDEX = REPO / "static" / "index.html"


def _index() -> str:
    return INDEX.read_text(encoding="utf-8")


def test_axiom_assets_are_deployed_and_self_contained():
    """Every asset the page references must exist on disk, and pull nothing from the network."""
    for rel in (
        "static/css/axiom-splash.css",
        "static/js/axiom-splash.js",
        "static/site.webmanifest",
        "static/icons/axiom.ico",
        "static/icons/axiom-192.png",
        "static/icons/axiom-256.png",
        "static/icons/axiom-512.png",
    ):
        p = REPO / rel
        assert p.is_file(), f"missing deployed asset: {rel}"
        assert p.stat().st_size > 0, f"empty asset: {rel}"

    for rel in ("static/css/axiom-splash.css", "static/js/axiom-splash.js"):
        src = (REPO / rel).read_text(encoding="utf-8")
        assert "http://" not in src and "https://" not in src, (
            f"{rel} reaches the network — the brand kit must stay self-contained"
        )
        assert "@import" not in src, f"{rel} pulls an external stylesheet"


def test_manifest_is_valid_json_and_points_at_deployed_icons():
    data = json.loads((REPO / "static" / "site.webmanifest").read_text(encoding="utf-8"))
    assert data["name"] and data["start_url"] == "/"
    for icon in data["icons"]:
        rel = icon["src"].lstrip("/")
        assert (REPO / rel).is_file(), f"manifest names a missing icon: {icon['src']}"


def test_index_references_the_assets_and_carries_the_overlay():
    s = _index()
    for ref in (
        "/static/css/axiom-splash.css",
        "/static/js/axiom-splash.js",
        "/static/site.webmanifest",
        "/static/icons/axiom.ico",
    ):
        assert ref in s, f"index.html does not reference {ref}"
    assert 'id="axiom-splash"' in s, "the splash overlay markup is gone"


def test_overlay_is_the_first_body_child():
    """It must cover the console BEFORE anything paints, or it is decoration, not a splash."""
    s = _index()
    body = s.index("<body")
    body_open_end = s.index(">", body) + 1
    after = s[body_open_end:body_open_end + 1200]
    first_tag = re.search(r"<(\w[\w-]*)", after)
    assert first_tag and first_tag.group(1) == "div", (
        f"first body element is <{first_tag.group(1) if first_tag else '?'}>, not the overlay"
    )
    assert 'id="axiom-splash"' in after[:first_tag.end() + 200]


def test_dismiss_is_wired_to_the_accepted_render_branch_only():
    """RC-249: exactly ONE dismissal call, and it must sit on the painted branch."""
    s = _index()
    lines = s.splitlines()
    sites = [i for i, ln in enumerate(lines, 1) if "AxiomSplash.dismiss()" in ln]
    assert len(sites) == 1, f"expected exactly one dismissal call site, found {sites}"

    line_no = sites[0]
    preceding = " ".join(x.strip() for x in lines[max(0, line_no - 8):line_no])
    assert "_edMplOnRenderComplete" in preceding, (
        "the dismissal is not on the accepted full-render branch — it must follow "
        "_edMplOnRenderComplete, which only runs when cards actually painted (RC-249)"
    )


def _strip_comments(text: str) -> str:
    """Remove JS line/block comments and HTML comments.

    The scan must judge CODE, not prose: a comment that NAMES a forbidden trigger (explaining
    why the dismissal must not be wired to it) is documentation, not a call. Scanning raw text
    flagged this file's own explanatory comment — the same false-positive shape RC-117 hit,
    and the same answer: normalise before scanning.
    """
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def test_dismiss_is_not_reachable_from_the_forbidden_triggers():
    """DOMContentLoaded, SSE onopen, a quote-only tick, and the dedup SKIP all mean
    'something happened', not 'the console is painted'."""
    lines = _strip_comments(_index()).splitlines()
    sites = [i for i, ln in enumerate(lines, 1) if "AxiomSplash.dismiss()" in ln]
    assert len(sites) == 1, f"expected one dismissal call in CODE, found {len(sites)}"
    site = sites[0]
    window = " ".join(lines[max(0, site - 25):site + 5])
    for forbidden in ("DOMContentLoaded", "EventSource", "onopen", "_shouldSkipTierCCardRender"):
        assert forbidden not in window, (
            f"the dismissal sits within reach of {forbidden!r} — a splash may only lift on a "
            f"branch that produced pixels"
        )


def test_the_dedup_skip_branch_still_returns_true_untouched():
    """The hazard this row is about must still EXIST — if the skip branch were removed, this
    test would pass vacuously and the guarantee above would be meaningless."""
    s = _index()
    assert "_shouldSkipTierCCardRender" in s, (
        "the duplicate-fingerprint skip is gone; re-verify the dismissal contract"
    )


def test_splash_never_blocks_the_money_path():
    """A brand overlay must not be able to break rendering: the call is guarded."""
    s = _index()
    lines = s.splitlines()
    site = [i for i, ln in enumerate(lines, 1) if "AxiomSplash.dismiss()" in ln][0]
    call_line = lines[site - 1]
    assert "try {" in call_line and "catch" in call_line, (
        "the dismissal must be try/caught so a missing or broken splash cannot take down the "
        "money path"
    )


def test_no_global_rename_and_no_service_worker():
    """PM defaults: the product keeps its name, and no offline PWA layer is introduced."""
    s = _index()
    assert "<title>Ed Console</title>" in s, "the title was renamed; PM default says it stays"
    assert "serviceWorker" not in s, "a service worker was introduced against the PM default"
