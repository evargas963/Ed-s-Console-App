"""RC-184 — charm book-scope must SURVIVE to the surfaces (Cursor charm audit v2, P0).

RC-182 put `scope`/`expiry` on the producer and claimed "every consumer sees which question
was answered" — v2 REFUTED that end-to-end: the server read exactly four keys from the charm
payload and dropped the label one hop before the operator. Presence on `compute_net_charm` is
therefore NOT the lock (it already held while the product failed); these tests drive the REAL
consumer chain: build_market_state -> MarketState -> _ms_to_dict (the API JSON the Key Levels
UI reads), the Tier-C publisher's signature, and the terrain snapshot's full-chain declaration.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_scope_survives_build_market_state_to_api_dict():
    """The e2e strip: producer fields -> build_market_state kwargs -> MarketState fields ->
    _ms_to_dict output. This is the dict the console API serves to Key Levels."""
    import server as s
    from market_state import build_market_state

    ms = build_market_state(
        ticker="SPY", spot=744.12,
        selected_exp="2026-08-03", session_label="rth", bid=744.10, ask=744.14,
        consensus_summary=None, contracts_use=[], walls=[], totals=[],
        price_levels=None, mkt_ctx=None, live_on=False,
        zone_since_bars=None, prev_zone=None,
        charm_net=420.21, charm_direction="buying",
        charm_scope="single_expiry", charm_expiry="2026-08-03",
    )
    assert getattr(ms, "charm_scope", None) == "single_expiry", (
        "MarketState dropped charm_scope — the RC-184 strip is back at the dataclass hop"
    )
    assert getattr(ms, "charm_expiry", None) == "2026-08-03"

    d = s._ms_to_dict(ms)
    assert d.get("charm_scope") == "single_expiry", (
        "the API dict the UI reads lost charm_scope — the label died at serialization"
    )
    assert d.get("charm_expiry") == "2026-08-03"
    # the direction still rides beside its label — a labeled book is the whole point
    assert d.get("charm_direction") == "buying"


def test_tier_c_publisher_accepts_and_forwards_the_book_label():
    """The Tier-C cache is the OTHER path the console reads while analytics complete. Its
    signature must carry the label and its dict must publish it."""
    import inspect

    import server as s

    sig = inspect.signature(s._publish_progressive_tier_c_cache)
    assert "charm_scope" in sig.parameters and "charm_expiry" in sig.parameters, (
        "Tier-C publisher signature lost the book label parameters"
    )
    src = inspect.getsource(s._publish_progressive_tier_c_cache)
    assert '"charm_scope": charm_scope' in src, "Tier-C dict no longer publishes charm_scope"
    assert '"charm_expiry": charm_expiry' in src
    # and the _fetch_state read site must actually harvest them from the producer payload
    fsrc = inspect.getsource(s._fetch_state)
    assert '_charm_raw.get("scope")' in fsrc, (
        "_fetch_state stopped reading scope from the producer — the strip locus regressed"
    )
    assert '_charm_raw.get("expiry")' in fsrc


def test_terrain_walls_declare_the_full_chain_book():
    """The walls answer EVERY expiry; the scalar answers one. The snapshot says so."""
    import terrain_engine as te

    assert "charm_book_scope" in te.TerrainSnapshot.__dataclass_fields__, (
        "TerrainSnapshot has no charm_book_scope — the walls' book is unlabeled again"
    )
    assert te.TerrainSnapshot.__dataclass_fields__["charm_book_scope"].default == "full_chain"
    import inspect

    src = inspect.getsource(te)
    assert 'charm_book_scope="full_chain"' in src, (
        "the snapshot builder no longer stamps full_chain beside the charm walls"
    )


def test_ui_renders_book_labels_on_both_charm_surfaces():
    """VISIBLE_SURFACE contract: Charm Drift names its expiry book; CALL/PUT CHARM notes name
    full chain. Unlabeled sign disagreement between the two surfaces is the v2 FAIL."""
    ui = (REPO / "static" / "index.html").read_text(encoding="utf-8")
    assert "charm_scope" in ui, "Charm Drift row never reads the scope field"
    assert "charm_expiry" in ui
    assert "charm wall · full chain" in ui, (
        "CALL/PUT CHARM notes no longer declare the full-chain book"
    )
    chart = (REPO / "static" / "chart.html").read_text(encoding="utf-8")
    assert "FULL-CHAIN book" in chart, "chart charm wall labels lost their book declaration"


def test_both_production_call_sites_pin_the_shared_clock():
    """RC-185 (v2 soft P2, no longer deferred): each charm engine used to default its OWN
    `now` mid-call — two free-running clocks under one number. Both production call sites must
    pass now= from the single authority, time_et.now_et."""
    import inspect
    import re

    import server as s
    import terrain_engine as te

    fsrc = inspect.getsource(s._fetch_state)
    assert re.search(r"compute_net_charm\([^)]*now=_charm_clock\(\)", fsrc, re.S), (
        "server._fetch_state no longer pins now= on compute_net_charm"
    )
    assert "from time_et import now_et as _charm_clock" in fsrc
    tsrc = inspect.getsource(te)
    assert re.search(r"compute_charm_by_strike\([^)]*now=_charm_clock\(\)", tsrc, re.S), (
        "terrain_engine no longer pins now= on compute_charm_by_strike"
    )
    assert "from time_et import now_et as _charm_clock" in tsrc


def test_ui_fails_closed_when_the_book_label_is_missing():
    """RC-184/185 D1: a charm number with NO book label must not publish a direction — the
    Key Levels row and the cv2 tile both withhold and say 'unlabeled'."""
    ui = (REPO / "static" / "index.html").read_text(encoding="utf-8")
    assert "const charmLabeled = d.charm_scope != null" in ui, (
        "the Charm Drift fail-closed gate is gone — an unlabeled direction can publish again"
    )
    assert ui.count("'unlabeled'") >= 2, (
        "the withheld state no longer renders on both the Key Levels row and the cv2 tile"
    )
    assert "s.charm_net != null && !s.charm_scope" in ui, (
        "the cv2-g-charm tile publishes direction without checking the book label"
    )


def test_order_flow_confirm_requires_a_labeled_charm_book():
    """RC-184 closeout R9 (Cursor v4 soft residual): #dr-of-confirm judged CONFIRM/DIVERGENCE
    against a BOOKLESS d.charm_direction — the unlabeled-direction defect through a side door.
    A selected-expiry 'buying' may legitimately oppose the full-chain walls; without the book,
    the only honest verdict is MIXED (attack N1: inject charm_net without charm_scope — the
    confirm cell must not CONFIRM)."""
    ui = (REPO / "static" / "index.html").read_text(encoding="utf-8")
    i = ui.find("const ofConfirm")
    assert i > 0, "the of-confirm block vanished"
    block = ui[i:i + 700]
    assert "if (!d.charm_scope) return 'MIXED';" in block, (
        "of-confirm no longer fail-closes on a bookless charm direction"
    )
    assert block.index("charm_scope") < block.index("charm_direction"), (
        "the scope gate must run BEFORE the direction is consulted"
    )


def test_terrain_cells_never_pretend_a_book_they_were_not_given():
    """Attack N2: walls present but charm_book_scope omitted/null — the ct cells must render an
    explicit 'book?' rather than assuming full chain."""
    ui = (REPO / "static" / "index.html").read_text(encoding="utf-8")
    i = ui.find("var bk = t.charm_book_scope")
    assert i > 0, "the ct-cell book resolution block vanished"
    block = ui[i:i + 300]
    assert "book?" in block, (
        "a null charm_book_scope no longer renders as an explicit unknown — the cells would "
        "silently imply full chain"
    )


def test_surfaces_read_charm_book_scope_from_the_payload():
    """RC-184 D2: labels FOLLOW the data. The terrain cells and the chart tips read
    charm_book_scope from the payload; a hardcoded 'full chain' would silently lie the day the
    producer changes books."""
    ui = (REPO / "static" / "index.html").read_text(encoding="utf-8")
    assert "t.charm_book_scope" in ui, (
        "ct-ccharm/ct-pcharm no longer read the book from the terrain payload"
    )
    chart = (REPO / "static" / "chart.html").read_text(encoding="utf-8")
    assert "T.charm_book_scope" in chart, (
        "chart charm-wall tips no longer read the book from the terrain payload"
    )
    # and the payload really carries it: dataclass asdict serialization
    import terrain_engine as te

    assert "charm_book_scope" in te.TerrainSnapshot.__dataclass_fields__


def test_light_plane_carries_the_book_label_with_the_number():
    """RC-185 (live DOM hunt, 2026-08-02): the FOURTH strip locus — the B_light SSE payload's
    enumerated key list carried charm_net with no book, so the weekend console rendered
    'unlabeled' forever. Wherever charm_net travels, its label travels."""
    import planes.context_light as cl

    src = (REPO / "planes" / "context_light.py").read_text(encoding="utf-8")
    keys = None
    for name in dir(cl):
        v = getattr(cl, name)
        if isinstance(v, tuple) and "charm_net" in v:
            keys = v
            break
    assert keys is not None, "the light-plane key list with charm_net vanished"
    assert "charm_scope" in keys and "charm_expiry" in keys, (
        "charm_net travels in the light plane without its book label — the B_light strip is back"
    )
    assert src.index("charm_net") < src.index("charm_scope"), "keep the pair adjacent"


def test_terrain_tab_is_the_bound_visible_consumer_of_the_ct_charm_cells():
    """RC-184 closeout (stop-guard demand): the ct-ccharm/ct-pcharm cells paint ONLY inside the
    terrain view — the visible consumer is the #cv2-tab-terrain tab, whose click chain
    (goto('terrain') -> edSwitchView -> body.ed-terrain-mode) is what makes the labeled cells
    reachable. CDP-proven painted this mission ('750.00 · full chain' after the page's own tab
    click); this lock binds the CHAIN so a rename/regate can't silently orphan the cells."""
    ui = (REPO / "static" / "index.html").read_text(encoding="utf-8")
    # 1. the tab exists in markup
    assert 'id="cv2-tab-terrain"' in ui, "the terrain tab vanished from the markup"
    # 2. its click enters the terrain view (goto('terrain')) and the mode class is toggled
    assert "goto('terrain')" in ui, "the terrain tab no longer routes to the terrain view"
    assert "classList.toggle('ed-terrain-mode'" in ui, (
        "edSwitchView no longer stamps the ed-terrain-mode class the paint gate reads"
    )
    # 3. the terrain module refuses to paint OUTSIDE the view (the gate that hid the cells
    #    from every earlier headless probe), and the labeled-cell paint sits BEHIND it
    gate = ui.find("if (!document.body.classList.contains('ed-terrain-mode')) return;")
    assert gate > 0, "the terrain-mode paint gate vanished"
    bk = ui.find("var bk = t.charm_book_scope")
    assert 0 < bk, "the ct-cell book resolution block vanished"
    # 4. the module re-refreshes on the tab's own click so the cells paint promptly
    hook = ui.find("el('cv2-tab-terrain'); if (tt) tt.addEventListener('click'")
    assert hook > 0, "the terrain module no longer refreshes on the tab click"
    assert bk < hook, "the paint site must live in the same module the tab click drives"


def test_docstring_no_longer_advertises_the_inverted_formula():
    """v2 P2: the contract text printed `-phi(d1) * d2 / (2*T)` as ACTUALLY IMPLEMENTED while
    the body computes +phi via bs_charm. The header formula must match the faucet."""
    import inspect

    from math_exposure_core import compute_net_charm

    doc = inspect.getdoc(compute_net_charm) or ""
    head = doc.split("Relation to the textbook")[0]  # the textbook Haug reference may keep -phi
    assert "-phi(d1) * d2" not in head, (
        "the ACTUALLY IMPLEMENTED block shows the inverted formula again"
    )
    assert "+phi(d1) * d2" in head
    assert "bs_charm" in head, "the header no longer names the delegated single faucet"
    assert "plausibility gates account for the gap" not in doc, (
        "the retired-gate parity excuse is back — parity is exact since RC-182"
    )


def test_rc206_snapshot_charm_provenance_deferral_is_declared():
    """RC-206b -> RC-207: the charm_scope/charm_expiry columns CANNOT ship until the RC-207
    disk sequence (the migration's safety backup needs ~26GB free; 21GB measured — WinError
    112 killed every get_db() endpoint when the columns landed early). Until the operator
    sequence runs, db.py must DECLARE the deferral where the fields would live, and the
    producer side must still send the fields so the fix is a schema-only step."""
    from pathlib import Path

    from db import SnapshotRow

    dbsrc = (Path(__file__).resolve().parent.parent / "db.py").read_text(encoding="utf-8")
    ann = SnapshotRow.__annotations__
    if "charm_scope" in ann and "charm_expiry" in ann:
        # the RC-207 sequence ran: the columns must be in the migration list too
        assert '("charm_scope"' in dbsrc and '("charm_expiry"' in dbsrc, (
            "fields present but NEW_COLUMNS missing — older DBs never gain the columns")
    else:
        assert "RC-206b DEFERRED to RC-207" in dbsrc, (
            "charm provenance fields absent AND the deferral is undeclared — the drift "
            "warning storm (RC-206b) has no owner")
    ssrc = (Path(__file__).resolve().parent.parent / "server.py").read_text(
        encoding="utf-8", errors="replace")
    assert '"charm_scope": charm_scope' in ssrc, (
        "the producer no longer sends charm_scope — RC-184 provenance chain broken upstream")
