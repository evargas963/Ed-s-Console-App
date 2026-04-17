"""Repo-wide assertions: canonical paths, isolated debug modes, no duplicate MVP semantics."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_inspect_similar_set_exposes_canonical_and_raw_sql_debug_subcommands():
    src = (ROOT / "tools" / "inspect_similar_set.py").read_text(encoding="utf-8")
    assert "canonical" in src
    assert "raw-sql-debug" in src
    assert "similar_setup_filters_from_canonical_features" in src
    assert "RAW_SQL_DEBUG_NON_SEMANTIC" in src
    assert "CANONICAL_MVP_FILTERS" in src


def test_compute_rules_signature_requires_mvp_features():
    src = (ROOT / "rules_engine.py").read_text(encoding="utf-8")
    assert "def compute_rules(inp: SignalInput, *, mvp_features: dict)" in src


def test_compute_call_requires_mvp_features_keyword_only():
    tree = ast.parse((ROOT / "call_engine.py").read_text(encoding="utf-8"))
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "compute_call":
            for a in node.args.kwonlyargs:
                if a.arg == "mvp_features":
                    found = True
    assert found


def test_monte_carlo_resolve_documents_non_canonical_l1_keys():
    from features.monte_carlo_stack_input import MONTE_CARLO_NON_CANONICAL_L1_KEYS, resolve_monte_carlo_stack_inputs
    from tests.mvp_test_fixtures import minimal_mvp_features
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row

    feats = minimal_mvp_features()
    snap = build_inference_snapshot_v1_from_feature_row(
        ticker="SPY", expiry=None, as_of_ts=1.0, features=feats
    )
    inp = type("I", (), {"spot": 450.0, "call_gamma_wall": 1.0, "put_gamma_wall": 1.0, "em_upper": 460.0, "em_lower": 440.0, "realized_vol": None, "atr": None, "garch_sigma_bars": None})()
    out = resolve_monte_carlo_stack_inputs(inp, snap)
    assert out["_mc_context_lineage"]["non_canonical_l1_keys"] == tuple(sorted(MONTE_CARLO_NON_CANONICAL_L1_KEYS))
    assert "price.spot" in out["_mc_context_lineage"]["canonical_mvp_keys_used"]
