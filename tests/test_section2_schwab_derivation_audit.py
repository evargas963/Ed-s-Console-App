"""Section 2 — Schwab dictionary derivation audit (server + live state)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SECTION2_FILES = frozenset(
    {
        "server.py",
        "live_market_plane.py",
        "live_decision_bundle.py",
        "live_pipeline_diag.py",
        "live_vs_replay_validation.py",
    }
)

_BID_ASK_MID_SPREAD_PAT = re.compile(
    r"""\(float\(\s*bid\s*\)\s*\+\s*float\(\s*ask\s*\)\)\s*/\s*2"""
)


def test_section2_inventory_covers_all_five_files():
    from governance.section2_derivation_inventory import SECTION2_DERIVATION_INVENTORY

    covered = {r.file for r in SECTION2_DERIVATION_INVENTORY}
    assert SECTION2_FILES <= covered


def test_section2_inventory_counts_and_dispositions():
    from governance.section2_derivation_inventory import SECTION2_DERIVATION_INVENTORY

    assert len(SECTION2_DERIVATION_INVENTORY) >= 15
    replaced = [r for r in SECTION2_DERIVATION_INVENTORY if r.disposition == "REPLACED"]
    assert len(replaced) >= 2
    assert any(r.file == "server.py" for r in replaced)
    assert any(r.file == "order_flow_engine.py" for r in replaced)


def test_section2_inventory_registered_in_replacement_register():
    reg = (ROOT / "governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- SECTION2_DERIVATION_INVENTORY_START -->" in reg
    assert "live_market_plane.py" in reg
    assert "REPLACED" in reg


def test_fetch_state_spread_no_bid_ask_mid_fallback():
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "(float(bid) + float(ask)) / 2.0" not in src


def test_section2_no_bid_ask_mid_spread_fallback_repo_wide():
    """Repo-wide: no bid+ask/2 spread mid synthesis in production quote paths."""
    skip_parts = {".claude", ".git", ".venv", "__pycache__", "backups", "tests", "tools"}
    hits: list[str] = []
    for path in ROOT.rglob("*.py"):
        if any(part in skip_parts for part in path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in ("v2_decision/a2_price_precedence.py",):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), start=1):
            if _BID_ASK_MID_SPREAD_PAT.search(line):
                hits.append(f"{rel}:{i}:{line.strip()}")
    assert hits == [], f"bid+ask/2 spread mid synthesis remains: {hits}"


def test_order_flow_spread_requires_schwab_mark_for_frac():
    from order_flow_engine import _compute_spread

    with_mark = {"quote": {"bidPrice": 100.0, "askPrice": 100.2, "mark": 100.1}}
    spread = _compute_spread(with_mark)
    assert spread["spread_frac"] is not None
    assert abs(spread["spread_frac"] - (0.2 / 100.1)) < 1e-6

    no_mark = {"quote": {"bidPrice": 100.0, "askPrice": 100.2}}
    assert _compute_spread(no_mark)["spread_frac"] is None


def test_live_plane_streaming_mark_denom_spread():
    import live_market_plane as lmp

    lmp.record_from_level_one_equity(
        "SPY",
        {
            "LAST_PRICE": 500.0,
            "MARK": 500.0,
            "BID_PRICE": 499.9,
            "ASK_PRICE": 500.1,
            "QUOTE_TIME_MILLIS": 1_710_000_000_000,
        },
    )
    row = lmp.get_quote("SPY")
    assert row is not None
    assert row["quote_mid"] == 500.0
    assert row["mid_source"] == "schwab_streaming_mark"
    assert row["spread"] == pytest.approx(0.2 / 500.0, rel=1e-6)
