"""Enumerate every FunctionDef/AsyncFunctionDef in section files (all scopes)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from governance.section_inventory_gate import all_functions_in_file  # noqa: E402

SECTION1 = [
    "schwab_client.py",
    "reauth_schwab.py",
    "websocket_adapter.py",
    "polling_adapter.py",
    "sse_adapter.py",
    "market_data_adapter.py",
    "snapshot_normalizer.py",
    "snapshot_access.py",
]

SECTION4 = [
    "math_exposure.py",
    "math_exposure_core.py",
    "math_levels.py",
    "math_volatility.py",
    "math_probabilities.py",
    "levels.py",
]


def main(files: list[str]) -> None:
    for rel in files:
        fns = all_functions_in_file(ROOT, rel)
        print(f"\n{rel}: {len(fns)} defs")
        for fn in fns:
            print(f"  L{fn.line:4d} {fn.qualified_name:50s} scope={fn.scope}")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "1"
    main(SECTION1 if which == "1" else SECTION4)
