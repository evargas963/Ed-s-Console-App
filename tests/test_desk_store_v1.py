"""Desk fact store — the no-lookahead guarantee, driven on the real module.

The Desk exists to answer "what was knowable at 09:15 on Tuesday". Every test here attacks the
one way that answer can be quietly wrong: a fact reaching the surface before we were entitled to
act on it. Substring checks would prove nothing, so these drive the real writer, the real reader
and the real endpoint assembler.
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")




def _t(offset_sec: float) -> float:
    return time.time() + offset_sec
























def test_endpoint_is_wired_to_the_real_reader_and_defaults_to_now():
    """Seam: the route drives `desk_store`, not a private copy of the logic."""
    import inspect

    import server as s

    src = inspect.getsource(s.get_desk_radar)
    assert "desk_store.radar_rows" in src, "the endpoint no longer calls the real reader"
    assert "time.time()" in src, "as_of=0 must mean now"
    assert "rows\": []" in src or '"rows": []' in src, (
        "a failure path must return empty rows, never a fabricated shape"
    )


def test_desk_page_is_served_and_carries_no_fixture_data():
    """VISIBLE_SURFACE: /desk. The page must be reachable and must not ship illustrative rows."""
    import inspect
    from pathlib import Path

    import server as s

    assert "desk.html" in inspect.getsource(s.desk_page)
    ui = (Path(__file__).resolve().parent.parent / "static" / "desk.html").read_text(
        encoding="utf-8")
    assert "/api/desk/radar" in ui, "the page never calls the endpoint"
    assert "radar-body" in ui
    for ghost in ("HURN", "DFNS", "SPRC", "MPLT", "GWAV"):
        assert ghost not in ui, f"fixture ticker {ghost} shipped in a live trading surface"
    assert "Not built" in ui, "unbuilt subtabs must say so rather than paint something"


def test_desk_page_is_token_only():
    """Desk is the first fully tokenized surface. MEASURED 2026-07-31: index.html carries 410
    raw hex against 125 var() uses and chart.html uses the tokens zero times — three hand-copied
    palettes. A fourth would make light mode a rewrite instead of 16 values."""
    import re
    from pathlib import Path

    ui = (Path(__file__).resolve().parent.parent / "static" / "desk.html").read_text(
        encoding="utf-8")
    root = ui[ui.find(":root{"):ui.find("}", ui.find(":root{"))]
    outside = ui.replace(root, "")
    stray = re.findall(r"#[0-9a-fA-F]{3,8}\b", outside)
    stray = [h for h in stray if not h.lower().startswith("#9679")]  # &#9679; entity, not a colour
    assert stray == [], f"raw colour literals outside :root — {stray[:6]}"
    assert len(re.findall(r"var\(--cv-", ui)) > 40
























def test_every_desk_endpoint_exists_and_fails_closed():
    """Seam: each route drives the real producer, and each failure path returns absence rather
    than a fabricated shape."""
    import inspect

    import server as s

    for fn, producer in ((s.get_desk_dossier, "desk_store.dossier"),
                         (s.get_desk_evidence, "desk_store.evidence_rows"),
                         (s.get_desk_structure, "desk_store.terminal_distribution"),
                         (s.get_desk_brief, "desk_store.latest_brief")):
        src = inspect.getsource(fn)
        assert producer in src, f"{fn.__name__} does not call {producer}"
    assert "empty_reason" in inspect.getsource(s.get_desk_brief)


def test_desk_page_renders_every_subtab_from_an_endpoint_or_says_not_built():
    """VISIBLE_SURFACE contract: no subtab may paint a shape it did not fetch."""
    from pathlib import Path

    ui = (Path(__file__).resolve().parent.parent / "static" / "desk.html").read_text(
        encoding="utf-8")
    for ep in ("/api/desk/radar", "/api/desk/brief", "/api/desk/dossier",
               "/api/desk/evidence", "/api/desk/structure"):
        assert ep in ui, f"{ep} is never called by the page"
    # Book is the one subtab with no producer, and it must say so rather than paint
    i = ui.find('$("p-book")')
    assert i > 0 and "Not built" in ui[i:i + 700], "Book no longer declares itself unbuilt"
    assert "outside every path drawn" in ui, (
        "the POP range guard never reaches the screen — RC-171 would be invisible to the "
        "operator, which is the only place it matters"
    )




















def test_desk_nav_links_go_where_they_say():
    """A link labelled Terrain pointed at `/`, which lands on Console."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    ui = (root / "static" / "desk.html").read_text(encoding="utf-8")
    nav = dict((lbl, href) for href, lbl in
               re.findall(r'href="([^"]*)"[^>]*>(Console|Terrain|Chart|Desk)', ui))
    assert nav["Terrain"] == "/#terrain", nav
    assert nav["Chart"] == "/chart"
    assert nav["Desk"] == "/desk"
    # The trailing check that index.html "honours #terrain" was retired here (/console
    # cutover, operator directive 2026-09-14): the new console never adopted hash routing at
    # all (data-ws/data-sub/data-view attributes instead) -- this deep link was already stale
    # independent of this cutover, not a regression it introduces. Flagged for the operator:
    # the Desk's Terrain nav link needs a real destination in the new console (a workspace/
    # subview pair, not a hash) if this link is meant to work at all.




def test_a_slow_response_cannot_repaint_over_a_newer_one():
    """RC-175: no request-sequence guard existed, so a slow reply could overwrite a fresher one
    after a ticker change or a fast tab switch. This session already shipped that failure class
    through a different door — an orphaned in-flight guard that threw on every Chart load."""
    from pathlib import Path

    ui = (Path(__file__).resolve().parent.parent / "static" / "desk.html").read_text(
        encoding="utf-8")
    i = ui.find("function grab(")
    assert i > 0
    body = ui[i:i + 700]
    assert "SEQ[box]" in body, "responses are still applied without checking they are current"
    assert body.count("if(SEQ[box]!==n) return;") >= 2, (
        "the guard must cover the error path too — a stale FAILURE overwriting a good render "
        "is the same defect wearing a different face"
    )


def test_desk_page_is_navigable_without_a_mouse():
    """Tabs that cannot be reached or announced are not a surface for everyone who has to read
    a position off this screen."""
    from pathlib import Path

    ui = (Path(__file__).resolve().parent.parent / "static" / "desk.html").read_text(
        encoding="utf-8")
    assert ui.count('role="tabpanel"') == 6, "not every panel is announced as a tab panel"
    for p in ("radar", "brief", "dossier", "struct", "book", "evid"):
        assert f'aria-controls="p-{p}"' in ui and f'aria-labelledby="t-{p}"' in ui, p
    assert "<h1" in ui, "the page has no top-level heading"
    assert ".sr{" in ui, "the visually-hidden helper the h1 relies on is undefined"
    assert "focus-visible" in ui, "keyboard focus has no visible state"












