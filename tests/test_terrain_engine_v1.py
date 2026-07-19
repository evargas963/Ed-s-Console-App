"""terrain_engine.compute_terrain — the assembly step that the whole TERRAIN tab renders.

Every level shown to the operator comes through this function. It was shipped without a
direct test and flagged by the close-out orphan check for several runs.

Tests run on the REAL captured SPY chain, never a hand-built one, so the numbers are
whatever the actual data produces.
"""

from __future__ import annotations

import json
from pathlib import Path

from math_levels import GAMMA_FLIP_TRUSTED
from terrain_engine import TERRAIN_SCHEMA_VERSION, compute_terrain

_REAL_CHAIN = Path(__file__).parent / "fixtures" / "real_spy_0dte_chain_with_poison.json"


def _real_chain() -> tuple[list, float]:
    data = json.loads(_REAL_CHAIN.read_text(encoding="utf-8"))
    return data["chain"], float(data["spot"])


def test_fails_closed_on_every_missing_input() -> None:
    """No ticker, no chain, no spot -> a stand-aside payload, never a partial one."""
    for ticker, chain, spot in (
        ("", None, None),
        ("SPY", None, 743.0),
        ("SPY", [], 743.0),
        ("SPY", [{"strikePrice": 740}], None),
        ("SPY", [{"strikePrice": 740}], 0.0),
    ):
        snap = compute_terrain(ticker, chain, spot)
        assert snap.regime == "UNAVAILABLE"
        assert snap.posture == "STAND_ASIDE"
        assert snap.gamma_flip is None
        assert snap.call_wall is None and snap.put_wall is None
        assert snap.error, "a refusal must state its reason"


def test_real_chain_produces_a_complete_payload() -> None:
    chain, spot = _real_chain()
    snap = compute_terrain("SPY", chain, spot)

    assert snap.ticker == "SPY"
    assert snap.spot == spot
    assert snap.schema_version == TERRAIN_SCHEMA_VERSION
    assert snap.contracts_used > 0
    assert snap.strikes_used > 0
    assert snap.headline, "the operator always gets a sentence"
    assert isinstance(snap.lines, list)


def test_levels_are_real_strikes_or_absent() -> None:
    """A level must be a strike that exists in the chain — never interpolated or invented.

    The gamma flip is the one exception: it is interpolated between strikes by design.
    """
    chain, spot = _real_chain()
    snap = compute_terrain("SPY", chain, spot)
    strikes = {float(c["strikePrice"]) for c in chain if c.get("strikePrice") is not None}

    for name in ("call_wall", "put_wall", "gamma_pin", "hvl",
                 "call_charm_wall", "put_charm_wall"):
        value = getattr(snap, name)
        assert value is None or value in strikes, f"{name}={value} is not a chain strike"


def test_posture_is_never_issued_without_trusted_levels() -> None:
    """The core safety property: no trading posture on levels we do not trust."""
    chain, spot = _real_chain()
    snap = compute_terrain("SPY", chain, spot)
    if snap.confidence != GAMMA_FLIP_TRUSTED:
        assert snap.posture == "STAND_ASIDE"
        assert snap.regime == "UNAVAILABLE"


def test_payload_is_json_serialisable() -> None:
    """It is served over HTTP; a non-serialisable field breaks the tab silently."""
    chain, spot = _real_chain()
    payload = compute_terrain("SPY", chain, spot).to_dict()
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["ticker"] == "SPY"
    assert "spot" in round_tripped and "confidence" in round_tripped
    assert "flip_diag" in round_tripped


def test_is_deterministic() -> None:
    """Same chain, same spot, same payload — or nothing on the card is reproducible."""
    chain, spot = _real_chain()
    a = compute_terrain("SPY", chain, spot).to_dict()
    b = compute_terrain("SPY", chain, spot).to_dict()
    assert a == b
