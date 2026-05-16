"""KEY LEVELS zero-OPEN sweep vs Schwab dictionary (register item 19)."""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DICT_CSV = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"

KEY_LEVELS_DATA_FLOW_FILES = (
    "math_exposure_core.py",
    "math_levels.py",
    "math_volatility.py",
    "server.py",
    "market_state.py",
    "live_decision_bundle.py",
    "live_market_plane.py",
    "planes/context_light.py",
    "static/index.html",
    "snapshot_normalizer.py",
    "market_data_adapter.py",
    "mc_fusion_adjustment.py",
    "signals.py",
)

# Patterns that indicate unregistered Schwab-replaceable silent defaults in KL path.
FORBIDDEN_PATTERNS = (
    (r'get\("multiplier"\)\s*or\s*100', "multiplier_or_100"),
    (r"_fallback_hours\s*=\s*max\(_hours_rem,\s*6\.5\)", "em_65h_fallback"),
    (r"MC_FALLBACK", "mc_fallback_label"),
    (r'spot\s*=\s*last\s+or\s+mark\s+or\s+0\.0', "fast_quote_spot_zero"),
    (r'get\("spot"\)\s+or\s+0\.0', "spot_or_zero"),
)

# Closed register IDs — derivations allowed with provenance in these modules.
REGISTERED_KL_DERIVATIONS = frozenset(
    {
        "compute_max_pain",
        "pick_gamma_wall",
        "pick_hvl",
        "aggregate_net_gex",
        "compute_expected_move_straddle",
        "compute_expected_move_iv",
        "resolve_kl_em_anchor",
        "resolve_mc_iv_for_kl_em_anchor",
        "compute_exposures_by_strike",
        "_oe_bid_ask_mid",
        "resolve_a2_contract_spread",
    }
)


def _load_dictionary_leaves() -> set[str]:
    leaves: set[str] = set()
    with DICT_CSV.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            cf = (row.get("canonical_field") or "").strip()
            if cf:
                leaves.add(cf.split(".")[-1])
    assert len(leaves) > 100
    return leaves


def test_schwab_dictionary_loads():
    assert DICT_CSV.is_file()
    _load_dictionary_leaves()


def test_key_levels_files_have_no_forbidden_silent_defaults():
    findings: list[str] = []
    for rel in KEY_LEVELS_DATA_FLOW_FILES:
        path = ROOT / rel
        if not path.is_file():
            findings.append(f"missing:{rel}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern, label in FORBIDDEN_PATTERNS:
            if re.search(pattern, text):
                findings.append(f"{rel}:{label}")
    assert not findings, f"KEY LEVELS sweep findings: {findings}"


def test_key_levels_sweep_scope_files_exist():
    missing = [f for f in KEY_LEVELS_DATA_FLOW_FILES if not (ROOT / f).is_file()]
    assert not missing, missing
