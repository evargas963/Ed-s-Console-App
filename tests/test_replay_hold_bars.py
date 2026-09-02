"""COH-I-K replay max-hold bars single authority (replay_hold_bars.py)."""

from __future__ import annotations

import json
import re

from micro_structure import R_CHOP, R_TREND_UP
from replay_hold_bars import (
    replay_max_hold_bars_for_setup,
    replay_max_hold_bars_for_trade_type,
    replay_max_hold_bars_from_context,
    resolve_replay_max_hold_bars_for_payload,
)
from realized_contract_eval import build_replay_context_payload
from app.domain.time_et import RTH_SESSION_MINUTES

_SKIP_PY_TREE_DIRS = frozenset(
    {".claude", ".git", ".venv", "venv", "node_modules", "__pycache__"}
)
_REPLAY_HOLD_DEF = re.compile(r"""def\s+replay_max_hold_bars_""")


#: TEST_SYSTEM_REHAB_V2: was an independent root.rglob("*.py") + per-file read_text --
#: now sources from the shared tests/conftest.py `repo_index` corpus. Filter semantics
#: unchanged (skip tests/ and the same build-tool dirs).
def _iter_production_py(repo_index):
    for rel, text, _tree in repo_index.items():
        if rel.parts and rel.parts[0] == "tests":
            continue
        if any(part in _SKIP_PY_TREE_DIRS for part in rel.parts):
            continue
        yield rel, text


def test_replay_max_hold_bars_from_context_requires_explicit_value():
    assert replay_max_hold_bars_from_context({}) is None
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": None}) is None
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": 0}) is None
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": "bad"}) is None


def test_replay_max_hold_bars_from_context_accepts_valid_and_caps():
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": 15}) == 15
    assert replay_max_hold_bars_from_context({"replay_max_hold_bars": 500}) == RTH_SESSION_MINUTES


def test_setup_and_trade_type_fallback_agree_on_shared_trade_types():
    """Live prescription and logging fallback must not drift on common trade_type keys."""
    cases = [
        ("trend_continuation", R_TREND_UP, 60),
        ("breakout", R_TREND_UP, 15),
        ("reversal", R_CHOP, 20),
        ("fade", R_TREND_UP, 30),
        ("mean_reversion", R_TREND_UP, 30),
        # STACK-WIRE-6 FIND-WIRE6-2: "none" trade_type means no trade — 0-bar hold
        # in BOTH paths (prior divergence had fallback returning 20).
        ("none", R_TREND_UP, 0),
    ]
    for trade_type, micro_regime, expected in cases:
        assert replay_max_hold_bars_for_trade_type(trade_type) == expected
        assert replay_max_hold_bars_for_setup(micro_regime, trade_type) == expected


def test_resolve_replay_max_hold_bars_for_payload_provenance():
    resolved, src, fb = resolve_replay_max_hold_bars_for_payload(
        trade_type="breakout", replay_max_hold_bars_live=22
    )
    assert resolved == 22
    assert src == "call_card"
    assert fb == 15

    resolved2, src2, fb2 = resolve_replay_max_hold_bars_for_payload(
        trade_type="breakout", replay_max_hold_bars_live=None
    )
    assert resolved2 == 15
    assert src2 == "trade_type_fallback"
    assert fb2 == 15


def test_build_replay_context_payload_records_hold_provenance():
    raw = build_replay_context_payload(
        walls=[],
        totals=[],
        option_chain_selection_proof=None,
        regime_primary="trend",
        regime_confidence="high",
        zone="mid",
        vol_regime="normal",
        trade_type="breakout",
        time_qualifier="~15min",
        replay_max_hold_bars_live=None,
        vwap=None,
        vwap_side=None,
    )
    payload = json.loads(raw)
    assert payload["replay_max_hold_bars"] == 15
    assert payload["replay_max_hold_bars_source"] == "trade_type_fallback"
    assert payload["replay_max_hold_bars_fallback"] == 15
    assert "source=trade_type_fallback" in payload["replay_time_expiry_policy"]


def test_no_replay_max_hold_bars_defs_outside_authority_module(repo_index):
    offenders: list[str] = []
    for rel, src in _iter_production_py(repo_index):
        if rel.name == "replay_hold_bars.py":
            continue
        if _REPLAY_HOLD_DEF.search(src):
            offenders.append(str(rel).replace("\\", "/"))
    assert not offenders, offenders
