"""CLI: Phase 4 explainability from a JSON file (saved /api/state) or stdin."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from verification.decision_explain import explain_market_state_dict


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", type=Path, help="JSON file; omit for stdin")
    args = ap.parse_args()
    if args.path:
        raw = args.path.read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()
    ms = json.loads(raw)
    print(json.dumps(explain_market_state_dict(ms), indent=2, default=str))


if __name__ == "__main__":
    main()
