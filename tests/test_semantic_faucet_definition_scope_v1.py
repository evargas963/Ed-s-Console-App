"""RC-303 (spawned by RC-292/RC-302) — the (definition, chain-scope) semantic faucet.

`single_faucet_provenance` proves one WRITER per field and is blind to the MEANING behind
the write: a field can have exactly one writer and still carry a different quantity
depending on which chain reached it. That is how three producers published "gamma_pin"
under TWO definitions over TWO chain scopes while every writer-scan stayed green (RC-292).

THE LAW THIS FILE ENFORCES: a published level-bearing NAME maps to exactly ONE metric
definition repo-wide. The same definition may legitimately exist at both chain scopes
(full_book vs selected_expiry) — e.g. net_gex_peak on the terrain payload versus
summary_rows — but then the SCOPE is declared per surface, and the (name, surface) pair
resolves to exactly one (definition, scope). Two definitions under one name is the RC-292
defect and fails here BY CONSTRUCTION, not by review.

Behavioral teeth: the real SPY 0DTE fixture is a book where the two definitions genuinely
diverge (max-total-gamma 745 vs max-|net-GEX| 743 — the exact measurement recorded in the
RC-292 ledger row), so a name wired to the wrong metric produces a different NUMBER here,
never a silently agreeing one. This is a TEST in the suite, deliberately not a new
enforced check (teardown rule: no new governance mechanism).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FIXTURE = REPO / "tests" / "fixtures" / "real_spy_0dte_chain.json"

# ── The declaration table ────────────────────────────────────────────────────────────────
# (surface, name) -> (definition, chain_scope). Definitions are metric identities, not
# prose: two entries share a definition token iff the same function over the same inputs
# produces both. Scopes are the operator's two books (RC-292 disposition: "scope every
# level as full_book versus selected_expiry").

FULL = "full_book"
SEL = "selected_expiry"

DECLARED: dict[tuple[str, str], tuple[str, str]] = {
    # terrain payload (/api/terrain, TerrainSnapshot.to_dict) — the levels SSOT
    ("terrain", "absolute_gamma_strike"): ("max_total_gamma", FULL),
    ("terrain", "pin_candidate"): ("qualified_max_total_gamma", FULL),
    ("terrain", "net_gex_peak"): ("max_abs_net_gex", FULL),
    ("terrain", "call_wall"): ("max_call_gamma", FULL),
    ("terrain", "put_wall"): ("max_put_gamma", FULL),
    ("terrain", "gamma_flip"): ("net_gamma_zero_cross", FULL),
    ("terrain", "max_pain"): ("min_option_holder_value", FULL),
    ("terrain", "key_delta_strike"): ("max_total_delta", FULL),
    ("terrain", "call_charm_wall"): ("max_call_charm", FULL),
    ("terrain", "put_charm_wall"): ("max_put_charm", FULL),
    ("terrain", "call_delta_wall"): ("max_call_delta", FULL),
    ("terrain", "put_delta_wall"): ("max_put_delta", FULL),
    # analytics summary rows (/api/state summary_rows[]) — the SELECTED-EXPIRY book.
    # Same definition token as terrain net_gex_peak: same function, declared other scope.
    ("summary_rows", "net_gex_peak"): ("max_abs_net_gex", SEL),
    # KL overlay (analytics payload kl_* family) — stamped FROM terrain by the one writer
    ("kl_overlay", "kl_absolute_gamma_strike"): ("max_total_gamma", FULL),
    ("kl_overlay", "kl_pin_candidate"): ("qualified_max_total_gamma", FULL),
    ("kl_overlay", "kl_hvl"): ("max_abs_net_gex", FULL),
    ("kl_overlay", "kl_call_gamma_wall"): ("max_call_gamma", FULL),
    ("kl_overlay", "kl_put_gamma_wall"): ("max_put_gamma", FULL),
    ("kl_overlay", "kl_gamma_flip"): ("net_gamma_zero_cross", FULL),
    ("kl_overlay", "kl_max_pain"): ("min_option_holder_value", FULL),
    ("kl_overlay", "kl_call_delta_wall"): ("max_call_delta", FULL),
    ("kl_overlay", "kl_put_delta_wall"): ("max_put_delta", FULL),
    # charm faucet: drift_toward is WITHHELD (server passes drift_toward_strike=None —
    # RC-315: no "toward" strike without a validated directional mechanism; the RC-292
    # operator decision on charm's target remains open). Declaring the withhold keeps the
    # name in the table so a silently re-plumbed target must come back through here.
    ("charm", "drift_toward"): ("withheld_pending_rc292_operator_decision", SEL),
}

#: Names the LIVE payload law deliberately does not govern: the snapshots DB column
#: `gamma_pin` is HISTORICAL and era-split — its meaning per row is declared machine-
#: readably by time_et.snapshots_gamma_pin_semantic (RC-429) and locked by
#: tests/test_gamma_pin_semantic_split.py. It is listed here so coverage is a decision,
#: never an omission.
HISTORICAL_DB_COLUMNS = {("snapshots_db", "gamma_pin")}

# Level-shaped payload keys: price-level fields the coverage law forces into DECLARED.
_LEVEL_SUFFIXES = ("_wall", "_flip", "_strike", "_peak", "_candidate", "_pain")
_LEVEL_EXTRAS = {"hvp", "lvp", "gsf", "grc"}
#: hvp/lvp/gsf/grc are level-bearing but terrain-only diagnostics of the SAME materialized
#: full-book profile; they are declared here once rather than in the main table because no
#: second surface publishes those names (no collision is possible for a single-surface name,
#: but coverage still records the scope).
_SINGLE_SURFACE_FULL_BOOK = {"hvp", "lvp", "gsf", "grc"}


def _fixture_book():
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return fx["chain"], float(fx["spot"])


def _widened_book():
    """The fixture chain plus one far-expiry call — full_book != selected_expiry."""
    chain, spot = _fixture_book()
    src = next(
        c for c in chain
        if str(c.get("putCall", "")).upper() == "CALL"
        and float(c.get("strikePrice") or 0) == 773.0
    )
    extra = dict(src)
    extra["strikePrice"] = 775.0
    extra["daysToExpiration"] = int(src.get("daysToExpiration") or 0) + 30
    extra["expirationDate"] = "2026-10-22"
    extra["openInterest"] = 250_000
    extra["symbol"] = "SPY   261022C00775000"
    return chain, chain + [extra], spot


def test_one_name_one_definition_across_all_declared_surfaces():
    """The RC-292 defect shape fails by construction: a name may span surfaces and scopes,
    but never two DEFINITIONS."""
    by_name: dict[str, set[str]] = {}
    for (_surface, name), (definition, scope) in DECLARED.items():
        assert scope in (FULL, SEL), f"{name}: undeclared scope vocabulary {scope!r}"
        by_name.setdefault(name.removeprefix("kl_"), set()).add(definition)
    offenders = {n: sorted(d) for n, d in by_name.items() if len(d) > 1}
    assert not offenders, (
        f"one NAME carries two metric definitions — the RC-292 collision returned: "
        f"{offenders}")


def test_definitions_diverge_on_the_real_book_so_a_miswire_cannot_hide():
    """Premise: the two pin-shaped definitions disagree on this chain (773 vs 775; SPY 2026-09-22 12:46 ET).

    RC-292 measured live SPY where they AGREED (775 == 775) and named the coincidence the
    finding: nothing could tell two definitions apart. This fixture is the book where they
    split, so every name-to-metric wiring below is checked against a number the other
    metric cannot produce.
    """
    from math_exposure_core import (
        compute_exposures_by_strike,
        pick_net_gex_peak_strike,
        pick_pin_and_strength,
    )
    from math_exposure_core import key_level_strikes_with_gamma

    chain, spot = _fixture_book()
    ex, _ = compute_exposures_by_strike(chain, spot=spot, require_oi=True)
    ks = key_level_strikes_with_gamma(ex) or sorted(ex)
    total_leader, _strength = pick_pin_and_strength(ex, ks)
    net_leader = pick_net_gex_peak_strike(ex, ks, institutional=True)
    assert total_leader is not None and net_leader is not None
    assert total_leader != net_leader, (
        "the fixture no longer separates max-total-gamma from max-|net-GEX| — replace it "
        "with a book where the definitions diverge or every wiring check below is blind")
    assert (total_leader, net_leader) == (773.0, 775.0), (
        "the measured split (773 vs 775) no longer reproduces on this fixture")


def test_terrain_names_carry_their_declared_definitions():
    """absolute_gamma_strike ≡ pick_pin_and_strength; net_gex_peak ≡
    pick_net_gex_peak_strike — same book, same strikes, ONE faucet per definition."""
    from math_exposure_core import (
        compute_exposures_by_strike,
        pick_net_gex_peak_strike,
        pick_pin_and_strength,
    )
    from math_exposure_core import key_level_strikes_with_gamma
    from terrain_engine import compute_terrain

    chain, spot = _fixture_book()
    snap = compute_terrain("SPY", chain, spot)
    ex, _ = compute_exposures_by_strike(chain, spot=spot, require_oi=True)
    ks = key_level_strikes_with_gamma(ex) or sorted(ex)
    assert snap.absolute_gamma_strike == pick_pin_and_strength(ex, ks)[0]
    assert snap.net_gex_peak == pick_net_gex_peak_strike(ex, ks, institutional=True)
    # the cross-wire that RC-292 could never see: each name now refuses the other metric
    assert snap.absolute_gamma_strike != snap.net_gex_peak
    d = snap.to_dict()
    assert d["absolute_gamma_strike"] == snap.absolute_gamma_strike
    assert d["net_gex_peak"] == snap.net_gex_peak
    assert "gamma_pin" not in d, "the retired two-definition name returned to the payload"






def test_pin_candidate_is_published_only_through_the_qualification_gates():
    """RC-292 operator disposition, executed: every gate flips the claim off; all five
    passing publishes the strike; the real fixture withholds with named blockers."""
    from terrain_engine import compute_terrain, qualify_pin_candidate

    passing = dict(
        spot=100.0, absolute_gamma_strike=100.2, absolute_gamma_strength_pct=15.0,
        absolute_gamma_gex_dollars=60_000.0, absolute_gamma_oi=3_000.0,
        book_oi_total=10_000.0, net_gex_at_spot=5.0, front_dte=0.0,
    )
    strike, blockers = qualify_pin_candidate(**passing)
    assert (strike, blockers) == (100.2, [])
    for gate, patch in (
        ("regime", {"net_gex_at_spot": -5.0}),
        ("proximity", {"absolute_gamma_strike": 102.0}),
        ("dte", {"front_dte": 3.0}),
        ("liquidity", {"absolute_gamma_oi": 1.0}),
        ("completeness", {"book_oi_total": None}),
    ):
        strike, blockers = qualify_pin_candidate(**{**passing, **patch})
        assert strike is None and gate in blockers, (
            f"the {gate} gate did not withhold the pin claim: blockers={blockers}")
    # The real book: regime and liquidity fail today — the claim is withheld WITH reasons.
    chain, spot = _fixture_book()
    snap = compute_terrain("SPY", chain, spot)
    assert snap.pin_candidate is None
    assert snap.pin_candidate_blockers == ["regime", "liquidity"]
    assert snap.absolute_gamma_strike is not None, (
        "withholding the CLAIM must never delete the measured concentration (deliver, "
        "never delete)")


def test_every_level_shaped_payload_name_is_declared():
    """Coverage: a new level-bearing field cannot ship without a (definition, scope)
    declaration — the omission RC-303 names as the root becomes a failing test."""
    from terrain_engine import compute_terrain

    chain, spot = _fixture_book()
    payload = compute_terrain("SPY", chain, spot).to_dict()
    declared_terrain = {n for (s, n) in DECLARED if s == "terrain"}
    for key in payload:
        if key.endswith(("_state", "_range", "_blockers")):
            continue
        if key.endswith(_LEVEL_SUFFIXES) or key in _LEVEL_EXTRAS:
            assert key in declared_terrain or key in _SINGLE_SURFACE_FULL_BOOK, (
                f"terrain payload publishes level-shaped {key!r} with no declared "
                f"(definition, chain scope) — declare it in DECLARED before shipping")
    # every declared terrain name really is published (a stale declaration is a lie too)
    for name in declared_terrain:
        assert name in payload, f"declared terrain name {name!r} is not published"


