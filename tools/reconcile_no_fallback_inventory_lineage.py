#!/usr/bin/env python3
"""Reconcile the 1226-candidate prior inventory against the current 1125-candidate
inventory.

1226 - 1125 = 101 is the NET delta. Expression-level matching on
(file, pattern, snippet, context) shows 115 removals and 14 additions
(1111 retained). This tool emits a lineage row for every removal and every
addition and refuses to write unless:

    prior - removals + additions == current
    removals - additions == 101
"""
from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRIOR_REF = "05cc3bf4"
PRIOR_PATH = "reports/no_fallback_inventory.json"
OUT_PATH = REPO / "reports" / "no_fallback_inventory_lineage_1226_to_1125.json"
EXPECTED_PRIOR = 1226
EXPECTED_CURRENT = 1125
EXPECTED_NET_REMOVALS = 101

_WS = re.compile(r"\s+")


def _norm(s: object) -> str:
    return _WS.sub(" ", str(s or "")).strip()


def _key(c: dict) -> tuple[str, str, str, str]:
    return (
        _norm(c.get("file")),
        _norm(c.get("pattern")),
        _norm(c.get("snippet")),
        _norm(c.get("context")),
    )


def _load_prior() -> dict:
    r = subprocess.run(
        ["git", "show", f"{PRIOR_REF}:{PRIOR_PATH}"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 0:
        raise SystemExit(f"git show {PRIOR_REF}:{PRIOR_PATH} failed: {r.stderr}")
    return json.loads(r.stdout)


def _removal_classification(old: dict) -> tuple[str, str]:
    old_file = old.get("file") or ""
    if not (REPO / old_file).exists():
        return "DELETED_FILE", f"{old_file} is absent from the current tree"
    return (
        "EXPRESSION_REMOVED_OR_RESHAPED",
        f"{old_file} still exists but this (pattern, snippet, context) is no longer discovered",
    )


def build_lineage(prior: dict, current: dict) -> dict:
    old_cands = list(prior["candidates"])
    new_cands = list(current["candidates"])
    if len(old_cands) != EXPECTED_PRIOR:
        raise SystemExit(f"prior candidate_count {len(old_cands)} != {EXPECTED_PRIOR}")
    if len(new_cands) != EXPECTED_CURRENT:
        raise SystemExit(f"current candidate_count {len(new_cands)} != {EXPECTED_CURRENT}")

    new_by_key: dict[tuple, list[dict]] = {}
    for c in new_cands:
        new_by_key.setdefault(_key(c), []).append(c)

    used_new_ids: set[str] = set()
    removals: list[dict] = []
    retained = 0
    for old in old_cands:
        pool = new_by_key.get(_key(old), [])
        match = None
        for cand in pool:
            if cand["id"] not in used_new_ids:
                match = cand
                used_new_ids.add(cand["id"])
                break
        if match is not None:
            retained += 1
            continue
        classification, reason = _removal_classification(old)
        removals.append(
            {
                "old_id": old.get("id"),
                "new_id": None,
                "file": old.get("file"),
                "symbol": old.get("context"),
                "pattern": old.get("pattern"),
                "old_adjudication": old.get("adjudication"),
                "reason": reason,
                "evidence": {
                    "prior_ref": PRIOR_REF,
                    "snippet": old.get("snippet"),
                    "line": old.get("line"),
                    "file_exists_now": (REPO / (old.get("file") or "")).exists(),
                },
                "classification": classification,
            }
        )

    old_keys = {_key(c) for c in old_cands}
    additions = []
    for c in new_cands:
        if _key(c) in old_keys:
            continue
        additions.append(
            {
                "old_id": None,
                "new_id": c.get("id"),
                "file": c.get("file"),
                "symbol": c.get("context"),
                "pattern": c.get("pattern"),
                "old_adjudication": None,
                "reason": "new identity not present in the 1226-row prior inventory",
                "evidence": {
                    "snippet": c.get("snippet"),
                    "line": c.get("line"),
                },
                "classification": "ADDED_SINCE_PRIOR",
            }
        )

    if retained + len(removals) != EXPECTED_PRIOR:
        raise SystemExit(
            f"prior partition broken: retained={retained} removed={len(removals)} "
            f"!= {EXPECTED_PRIOR}"
        )
    if retained + len(additions) != EXPECTED_CURRENT:
        raise SystemExit(
            f"current partition broken: retained={retained} added={len(additions)} "
            f"!= {EXPECTED_CURRENT}"
        )
    if EXPECTED_PRIOR - len(removals) + len(additions) != EXPECTED_CURRENT:
        raise SystemExit("1226 - removals + additions != 1125")
    if len(removals) - len(additions) != EXPECTED_NET_REMOVALS:
        raise SystemExit(
            f"net removals {len(removals) - len(additions)} != {EXPECTED_NET_REMOVALS}"
        )

    by_class = Counter(r["classification"] for r in removals + additions)
    return {
        "prior_ref": PRIOR_REF,
        "prior_count": EXPECTED_PRIOR,
        "current_count": EXPECTED_CURRENT,
        "retained": retained,
        "removed": len(removals),
        "added": len(additions),
        "net_delta": EXPECTED_CURRENT - EXPECTED_PRIOR,
        "classification_counts": dict(by_class),
        "removals": removals,
        "additions": additions,
        "verdict": "RECONCILED",
        "note": (
            "101 is the NET (115 removals - 14 additions). Each removal and each "
            "addition has its own lineage row; arithmetic identity is not discovery "
            "completeness."
        ),
    }


def main() -> int:
    prior = _load_prior()
    current = json.loads((REPO / PRIOR_PATH).read_text(encoding="utf-8"))
    report = build_lineage(prior, current)
    OUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "wrote": str(OUT_PATH),
        "prior": report["prior_count"],
        "current": report["current_count"],
        "removed": report["removed"],
        "added": report["added"],
        "net_delta": report["net_delta"],
        "classifications": report["classification_counts"],
        "verdict": report["verdict"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
