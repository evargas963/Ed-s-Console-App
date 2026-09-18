#!/usr/bin/env python3
"""Reconcile the 1226-candidate prior inventory against the 1125-candidate inventory
that followed the point-5 fingerprint-identity migration.

1226 - 1125 = 101 is the NET delta. Expression-level matching on
(file, pattern, snippet, context) shows 115 removals and 14 additions
(1111 retained). This tool emits a lineage row for every removal and every
addition and refuses to write unless:

    prior - removals + additions == current
    removals - additions == 101

FROZEN HISTORICAL PROOF, not a live invariant (2026-09-18, PR #254 point 9): both sides
of this reconciliation are pinned to specific git refs, never read from the live,
currently-evolving reports/no_fallback_inventory.json. This tool's job was to prove
ONE specific transition (the point-5 migration) reconciled correctly; the codebase has
legitimately continued adjudicating since then (1125 -> 1132 -> 1155 -> 1132 -> 1115 and
counting), and re-deriving "current" from the live file made this test permanently
broken by every later legitimate discovery/adjudication change -- it failed CI on SHA
4c8e2520 for exactly this reason ("current candidate_count 1115 != 1125"), not because
anything regressed. Pinning CURRENT_REF makes this a pure historical regression proof
that passes forever regardless of later progress, while
reports/no_fallback_inventory_lineage_1226_to_1125.json stands as the permanent record.

PINNING THE INVENTORY INPUTS WAS INSUFFICIENT (2026-09-18, operator audit): pinning
PRIOR_REF/CURRENT_REF only fixed WHICH CANDIDATE ROWS get compared. The per-removal
CLASSIFICATION still called `(REPO / old_file).exists()` against the live, mutable
working tree -- a file this session deletes, restores, or later adds back at the same
path would silently flip a removal between DELETED_FILE and
EXPRESSION_REMOVED_OR_RESHAPED, and flip the `file_exists_now` evidence field, with
neither pinned ref changing at all. That is exactly the class of defect this mission
exists to remove: a "frozen historical proof" whose actual output still depends on
unpinned, currently-evolving state. Every fact this report asserts -- which candidates
existed, which survived, and whether a removed candidate's FILE survived -- must now
come from the two pinned git trees (`git cat-file -e <ref>:<path>`), never from
`Path.exists()` against whatever happens to be checked out when this runs. See
tests/test_no_fallback_lineage_pinned_trees_v1.py for the mutation test proving a
working-tree file add/delete cannot change the generated report.
"""
from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRIOR_REF = "05cc3bf4"
CURRENT_REF = "21468eb2"  # point-5 fingerprint-identity migration: candidate_count == 1125
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


def _load_at_ref(ref: str, path: str = PRIOR_PATH) -> dict:
    r = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 0:
        raise SystemExit(f"git show {ref}:{path} failed: {r.stderr}")
    return json.loads(r.stdout)


def _load_prior() -> dict:
    return _load_at_ref(PRIOR_REF)


def _load_current() -> dict:
    return _load_at_ref(CURRENT_REF)


def _file_exists_at_ref(ref: str, path: str) -> bool:
    """Existence within a PINNED git tree, never the live working directory.

    `git cat-file -e <ref>:<path>` resolves `path` inside the tree `ref` points to and
    exits 0 iff that exact blob exists there -- it never touches the working tree at all,
    so this answer cannot change no matter what the working tree later adds, deletes, or
    restores at that path."""
    if not path:
        return False
    r = subprocess.run(
        ["git", "cat-file", "-e", f"{ref}:{path}"],
        cwd=str(REPO),
        capture_output=True,
        timeout=60,
    )
    return r.returncode == 0


def _removal_classification(old: dict) -> tuple[str, str]:
    old_file = old.get("file") or ""
    # CURRENT_REF, not the live working tree: this classification answers "did this
    # candidate's file survive into the pinned CURRENT state", a fact about the historical
    # transition being proven, not about whatever happens to be checked out right now.
    if not _file_exists_at_ref(CURRENT_REF, old_file):
        return "DELETED_FILE", f"{old_file} is absent from {CURRENT_REF} (the pinned current tree)"
    return (
        "EXPRESSION_REMOVED_OR_RESHAPED",
        f"{old_file} still exists in {CURRENT_REF} but this (pattern, snippet, context) is no longer discovered",
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
                    "file_exists_at_current_ref": _file_exists_at_ref(CURRENT_REF, old.get("file") or ""),
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
    current = _load_current()
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
