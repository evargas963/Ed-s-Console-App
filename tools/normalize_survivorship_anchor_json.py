#!/usr/bin/env python3
"""Rewrite survivorship JSON anchors: abs() distances for Issue 19 SQL alignment (offline helper)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.canonical_distances import canonicalize_distance_read


def main() -> None:
    p = ROOT / "data" / "survivorship_multi_anchor_20.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    for a in data.get("anchors_used", []):
        nad, nbd = canonicalize_distance_read(
            float(a["nearest_above_dist"]) if a.get("nearest_above_dist") is not None else None,
            float(a["nearest_below_dist"]) if a.get("nearest_below_dist") is not None else None,
        )
        a["nearest_above_dist"] = nad
        a["nearest_below_dist"] = nbd
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("Updated", p)


if __name__ == "__main__":
    main()
