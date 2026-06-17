"""Emit Section 11 register block for SCHWAB_DERIVED_FIELD_REPLACEMENT_REGISTER_V1.md."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys

sys.path.insert(0, str(ROOT))

from governance.section11_derivation_inventory import SECTION11_DERIVATION_INVENTORY  # noqa: E402

by: dict[str, dict[str, int]] = defaultdict(
    lambda: dict(REPLACED=0, KEEP_DERIVED=0, PASS_THROUGH=0, NONE=0, n=0)
)
for r in SECTION11_DERIVATION_INVENTORY:
    by[r.file][r.disposition] += 1
    by[r.file]["n"] += 1

rows = sorted(by.items(), key=lambda x: (-x[1]["n"], x[0]))
lines = [
    "## Section 11 derivation audit inventory",
    "",
    "Walked **66** modules (51 calibration + 13 arch_competition + "
    "bayesian_fusion + governed_stack_contract) at **full AST scope**. "
    "**466** inventory rows: **0** REPLACED, **338** KEEP_DERIVED, "
    "**0** PASS_THROUGH, **128** NONE. Calibration/fusion reads persisted "
    "snapshots/outcomes and model outputs only; no direct Schwab API. "
    "Gate: `governance/section_inventory_gate.py`. Full rows: "
    "`governance/section11_derivation_inventory.py`. Tests: "
    "`tests/test_section11_schwab_derivation_audit.py`.",
    "",
    "<!-- SECTION11_DERIVATION_INVENTORY_START -->",
    "| file | functions inventoried | REPLACED | KEEP_DERIVED | PASS_THROUGH | NONE |",
    "|---|---:|---:|---:|---:|---:|",
]
tot = dict(REPLACED=0, KEEP_DERIVED=0, PASS_THROUGH=0, NONE=0, n=0)
for f, b in rows:
    lines.append(
        f"| {f} | {b['n']} | {b['REPLACED']} | {b['KEEP_DERIVED']} | "
        f"{b['PASS_THROUGH']} | {b['NONE']} |"
    )
    for k in tot:
        tot[k] += b[k]
lines.append(
    f"| **total** | **{tot['n']}** | **{tot['REPLACED']}** | "
    f"**{tot['KEEP_DERIVED']}** | **{tot['PASS_THROUGH']}** | **{tot['NONE']}** |"
)
lines.extend(
    [
        "",
        "Per-function detail in `governance/section11_derivation_inventory.py`.",
        "<!-- SECTION11_DERIVATION_INVENTORY_END -->",
    ]
)
print("\n".join(lines))
