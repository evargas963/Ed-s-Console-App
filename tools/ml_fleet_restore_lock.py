#!/usr/bin/env python3
"""RC-437 — ENFORCEMENT lock: RC-436 must stay OPEN until the live ML fleet is restored.

Companion to ``tools/measure_rc435_abstain_impact.py``, which is REPORT-ONLY and exits 0.

WHAT WAS OBSERVED (RC-436): every active triclass XGB meta and every serveable
LSTM/Transformer checkpoint still lists the four structurally withheld OI/vanna
wall-distance ``*_pct`` features; live CONSENSUS walls are None, so RC-435 abstain
keeps the fleet dark. A measurement script that exits 0 can be mistaken for a
green gate ("we measured, therefore healthy").

THE RULE: if ``governance/root_cause_log.md`` marks RC-436 CLOSED while any active
triclass XGB meta still lists a withheld ``*_pct`` feature name, BLOCK. Honest
CLOSE requires promoted artifacts whose feature contracts omit those names
(Path A per ``reports/rc437_oi_vanna_wall_adjudication.md``).

Escape: none for premature CLOSE — restore the fleet or leave RC-436 OPEN.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

WITHHELD_PCT = frozenset(
    {
        "dist_call_oi_wall_pct",
        "dist_put_oi_wall_pct",
        "dist_call_vanna_wall_pct",
        "dist_put_vanna_wall_pct",
    }
)

_RC436_ROW = re.compile(
    r"^\|\s*RC-436\s*\|\s*(\w+)\s*\|",
    re.MULTILINE,
)


def rc436_status(repo: Path) -> str | None:
    """Return the status cell for RC-436, or None if the row is absent."""
    log = repo / "governance" / "root_cause_log.md"
    if not log.is_file():
        return None
    text = log.read_text(encoding="utf-8")
    m = _RC436_ROW.search(text)
    if not m:
        return None
    return m.group(1)


def active_triclass_metas_requiring_withheld(repo: Path) -> list[str]:
    """Paths (repo-relative) of active triclass XGB metas that still list withheld features."""
    active = repo / "models" / "active"
    if not active.is_dir():
        return []
    hits: list[str] = []
    for p in sorted(active.rglob("xgb_*_meta.json")):
        if "_dir_" in p.name or "_move_" in p.name:
            continue
        try:
            feats = json.loads(p.read_text(encoding="utf-8")).get("features") or []
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if set(feats) & WITHHELD_PCT:
            hits.append(str(p.relative_to(repo)).replace("\\", "/"))
    return hits


def violations(repo: Path | None = None) -> list[str]:
    """Return human-readable violations (empty = pass)."""
    root = Path(repo) if repo is not None else Path(__file__).resolve().parents[1]
    status = rc436_status(root)
    if status is None:
        return [
            "RC-436 row missing from governance/root_cause_log.md — "
            "fleet-dark restore tracker required until live ML is proven"
        ]
    if status != "CLOSED":
        return []
    hits = active_triclass_metas_requiring_withheld(root)
    if not hits:
        return []
    sample = ", ".join(hits[:3])
    more = f" (+{len(hits) - 3} more)" if len(hits) > 3 else ""
    return [
        "RC-436 CLOSED while active triclass XGB metas still require structurally "
        f"withheld OI/vanna wall-distance features ({len(hits)} metas; e.g. {sample}{more}). "
        "REPORT-ONLY measure_rc435_abstain_impact.py exits 0 by design — it is not a restore "
        "proof. Promote Path-A artifacts (no withheld *_pct) before closing RC-436 "
        "(reports/rc437_oi_vanna_wall_adjudication.md)."
    ]


def main() -> int:
    bad = violations()
    if bad:
        for line in bad:
            print(f"FAIL: {line}")
        return 1
    print(
        f"PASS: RC-436 status={rc436_status(Path(__file__).resolve().parents[1])!r}; "
        "no premature CLOSE against a withheld-feature fleet"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
