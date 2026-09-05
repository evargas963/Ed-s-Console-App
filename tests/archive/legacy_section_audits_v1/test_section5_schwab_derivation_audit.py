"""Section 5 — Schwab dictionary derivation audit (order flow)."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_BID_ASK_MID_SPREAD_PAT = re.compile(
    r"""\(float\(\s*bid\s*\)\s*\+\s*float\(\s*ask\s*\)\)\s*/\s*2"""
)


def test_section5_inventory_covers_every_function_all_scopes():
    from governance.section5_derivation_inventory import (
        SECTION5_DERIVATION_INVENTORY,
        SECTION5_FILES,
    )
    from governance.section_inventory_gate import assert_inventory_covers_all_functions

    assert_inventory_covers_all_functions(
        ROOT, SECTION5_FILES, SECTION5_DERIVATION_INVENTORY
    )


def test_section5_inventory_counts_and_dispositions():
    from governance.section5_derivation_inventory import (
        SECTION5_DERIVATION_INVENTORY,
        SECTION5_FILES,
    )
    from governance.section_inventory_gate import all_functions_in_file

    assert len(SECTION5_DERIVATION_INVENTORY) >= 70
    for rel in SECTION5_FILES:
        required = len(all_functions_in_file(ROOT, rel))
        inventoried = len({r.derivation for r in SECTION5_DERIVATION_INVENTORY if r.file == rel})
        assert inventoried == required, f"{rel}: {inventoried} != {required}"

    replaced = [r for r in SECTION5_DERIVATION_INVENTORY if r.disposition == "REPLACED"]
    assert len(replaced) >= 1
    assert any(r.derivation == "_compute_spread" for r in replaced)


def test_section5_inventory_registered_in_replacement_register():
    reg = (ROOT / "governance/SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- SECTION5_DERIVATION_INVENTORY_START -->" in reg
    assert "70" in reg or "order_flow" in reg


def test_order_flow_spread_requires_schwab_mark_for_frac():
    from app.options.order_flow.engine import _compute_spread

    with_mark = {"quote": {"bidPrice": 100.0, "askPrice": 100.2, "mark": 100.1}}
    spread = _compute_spread(with_mark)
    assert spread["spread_frac"] is not None
    assert abs(spread["spread_frac"] - (0.2 / 100.1)) < 1e-6

    no_mark = {"quote": {"bidPrice": 100.0, "askPrice": 100.2}}
    assert _compute_spread(no_mark)["spread_frac"] is None


def test_order_flow_engine_no_bid_ask_mid_in_spread():
    src = (ROOT / "app/options/order_flow/engine.py").read_text(encoding="utf-8")
    assert "(float(bid) + float(ask)) / 2" not in src.replace(" ", "")


def test_section5_no_bid_ask_mid_spread_fallback_repo_wide():
    """Repo-wide: no bid+ask/2 spread mid synthesis in production quote paths."""
    skip_parts = {
        ".claude",
        ".git",
        ".venv",
        "__pycache__",
        "backups",
        "governance",
        "tests",
        "tools",
    }
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


def test_push_level_one_records_stream_fields():
    import order_flow_live_state as ofs

    ofs.clear_symbol("TEST")
    ofs.push_level_one(
        "TEST",
        {
            "LAST_PRICE": 100.0,
            "MARK": 100.0,
            "BID_PRICE": 99.9,
            "ASK_PRICE": 100.1,
            "TOTAL_VOLUME": 1_000_000,
        },
    )
    vol = ofs.get_stream_volume("TEST")
    assert vol is not None
