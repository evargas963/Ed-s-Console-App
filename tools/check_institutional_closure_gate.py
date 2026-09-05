#!/usr/bin/env python3
"""Institutional closure ledger validator — parent / sub-lane closure integrity.

THE ONE RESPONSIBILITY THIS FILE OWNS: a scoped or sub-lane proof cannot mechanically close a
broader parent while a material dimension is unresolved (AGENTS.md laws 10, 11 and 14). It is
a validator, not a gate of its own: the ONE institutional gate,
`tools/check_institutional_correctness.py`, registers `validate_ledger` as the enforced check
`institutional_closure_ledger`, and required CI runs that gate on every PR through
`tools/check_delta_adds_no_debt.py`. The `main()` below is an operator/agent-side report.

Rules, every one objective:
  * a lane is CLOSED_WITH_EVIDENCE only when every applicable material dimension is PROVEN
    (or NOT_APPLICABLE with an evidence-backed rationale) — any blocked-vocabulary status
    (NOT_PROVEN, FAIL, PENDING, PARTIAL, UNKNOWN, NOT_AUDITED, RTH_REPROOF_PENDING) forces
    NOT_CLOSED;
  * unresolved material_limitations force NOT_CLOSED;
  * CI evidence must cite the declared final SHA; green CI is execution evidence, never
    semantic proof;
  * sub-lane closure never closes a parent;
  * component closure never implies real-money approval;
  * RC-516: a CLOSED_WITH_EVIDENCE lane may cite ONLY mechanisms and evidence that exist on
    the tree. The record once carried lanes whose MECHANICAL_ENFORCEMENT read PROVEN while
    every cited enforcement file had been deleted (the universal-fix gate, 41360574). A
    closure that rests on a mechanism that no longer exists is a stale claim, not history.
    History is kept under status RETIRED: such a lane asserts nothing current, carries a
    `retired` record (date, retiring commit, reason, current owner of the outcome) and its
    former dimensions under `retired.historical_dimensions`, and is exempt from the
    dimension rules because it makes no closure claim.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "governance" / "INSTITUTIONAL_CLOSURE_SCHEMA.json"

BLOCKED_VOCAB = {
    "NOT_PROVEN", "FAIL", "PENDING", "PARTIAL", "UNKNOWN", "NOT_AUDITED",
    "RTH_REPROOF_PENDING",
}
CLOSED = "CLOSED_WITH_EVIDENCE"
RETIRED = "RETIRED"
NOT_CLOSED = "NOT_CLOSED"
LANE_STATUSES = {CLOSED, RETIRED, NOT_CLOSED}
RETIRED_REQUIRED_FIELDS = ("date", "retired_in", "reason", "current_owner")

#: A repository path as it appears in prose or JSON: a tracked directory prefix followed by a
#: file with a source/record extension, or a bare root-level Python module. Globs (`*`),
#: directories and shell placeholders never match, so `tools/*.py` and `app/api/routes/`
#: are not citations. Used by the closure rule here and by the authority-document rule in
#: the institutional gate — ONE definition of "what counts as citing a mechanism".
MECHANISM_PATH_RE = re.compile(
    r"(?<![\w/.\-*])("
    r"(?:tools|tests|governance|config|calibration|docs|reports|research|static|features|"
    r"planes|scripts|verification|\.github/workflows|\.cursor|\.claude)"
    r"/[\w.\-]+(?:/[\w.\-]+)*\.(?:py|json|jsonl|yml|yaml|md|mdc|ps1|bat|csv|txt|html|js)"
    r"|[a-z_][a-z0-9_]*\.py"
    r")(?![\w/\-*])"
)


def cited_paths(text: str) -> set[str]:
    """Every repository path the text names (see MECHANISM_PATH_RE)."""
    return {m.group(1) for m in MECHANISM_PATH_RE.finditer(text)}


def missing_paths(paths: set[str], root: Path) -> list[str]:
    return sorted(p for p in paths if not (root / p).exists())


def _status_of(v: object) -> str:
    return str(v.get("status")) if isinstance(v, dict) else str(v)


def validate_ledger(doc: dict, root: Path = REPO_ROOT) -> list[str]:
    errors: list[str] = []
    dims_required = list(doc.get("required_dimensions") or [])
    if not dims_required:
        return ["schema missing required_dimensions"]
    lanes = doc.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        return ["schema missing lanes"]
    for row in lanes:
        lane_id = str(row.get("lane") or "<unnamed>")
        status = str(row.get("status") or "")
        if status not in LANE_STATUSES:
            errors.append(f"{lane_id}: unknown status {status!r} (one of {sorted(LANE_STATUSES)})")
            continue
        if status == RETIRED:
            rec = row.get("retired")
            if not isinstance(rec, dict):
                errors.append(f"{lane_id}: RETIRED without a `retired` record")
                continue
            for k in RETIRED_REQUIRED_FIELDS:
                if not str(rec.get(k) or "").strip():
                    errors.append(f"{lane_id}: RETIRED record missing {k!r}")
            if "dimensions" in row:
                errors.append(
                    f"{lane_id}: RETIRED lane still carries `dimensions` — a retired lane asserts "
                    f"nothing current; move them to retired.historical_dimensions")
            if row.get("final_sha") or row.get("remote_ci_status"):
                errors.append(
                    f"{lane_id}: RETIRED lane still carries final_sha/remote_ci_status as current "
                    f"authority — move them into the retired record")
            continue
        dims = row.get("dimensions") or {}
        for d in dims_required:
            if d not in dims:
                errors.append(f"{lane_id}: dimension {d} missing from ledger row")
                continue
            v = dims[d]
            if isinstance(v, dict):
                if str(v.get("status")) == "NOT_APPLICABLE" and not str(v.get("rationale") or "").strip():
                    errors.append(f"{lane_id}: {d} NOT_APPLICABLE without evidence-backed rationale")
        if status == CLOSED:
            for d, v in dims.items():
                sv = _status_of(v)
                if sv in BLOCKED_VOCAB:
                    errors.append(
                        f"{lane_id}: CLOSED_WITH_EVIDENCE with material dimension {d}={sv} — parent must be NOT_CLOSED"
                    )
            if row.get("material_limitations"):
                errors.append(
                    f"{lane_id}: CLOSED_WITH_EVIDENCE with unresolved material_limitations — parent must be NOT_CLOSED"
                )
            if not row.get("final_sha"):
                errors.append(f"{lane_id}: CLOSED_WITH_EVIDENCE without final_sha evidence tip")
            ci = str(row.get("remote_ci_status") or "")
            sha = str(row.get("final_sha") or "")
            if sha and ci and "at" in ci and sha[:7] not in ci and "cited tip" not in ci:
                errors.append(f"{lane_id}: CI evidence does not cite the declared final SHA")
            # RC-516: a closure may rest only on mechanisms and evidence that exist.
            missing = missing_paths(cited_paths(json.dumps(row)), root)
            if missing:
                errors.append(
                    f"{lane_id}: CLOSED_WITH_EVIDENCE cites path(s) that do not exist on this tree: "
                    f"{', '.join(missing)} — a closure resting on a deleted mechanism is a stale "
                    f"claim; retire the lane (status RETIRED with a `retired` record) or repair the "
                    f"citation")
        elif _status_of(dims.get("MECHANICAL_ENFORCEMENT")) == "PROVEN":
            # Even an open lane may not claim PROVEN enforcement by a mechanism that is gone.
            missing = missing_paths(cited_paths(json.dumps(row)), root)
            if missing:
                errors.append(
                    f"{lane_id}: MECHANICAL_ENFORCEMENT=PROVEN while citing path(s) that do not "
                    f"exist on this tree: {', '.join(missing)}")
        # Sub-lane closure must never imply parent closure.
        subs = row.get("sub_lanes") or []
        if subs and status == CLOSED:
            all_dims_proven = all(
                _status_of(v) in ("PROVEN", "NOT_APPLICABLE") for v in dims.values()
            )
            if not all_dims_proven:
                errors.append(
                    f"{lane_id}: parent closure rests on sub-lane closure without full parent dimensions"
                )
    # Real-money inference guard.
    if str(doc.get("real_money_approval") or "") != "NOT_APPROVED":
        closed_any = any(str(r.get("status")) == CLOSED for r in lanes)
        if closed_any:
            errors.append(
                "real_money_approval changed alongside component closures — component closure never implies real-money readiness"
            )
    return errors


def main() -> int:
    doc = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = validate_ledger(doc)
    if errors:
        print("institutional closure ledger FAILED:")
        for e in errors:
            print(" -", e)
        return 1
    print(
        f"institutional closure ledger coherent: {len(doc.get('lanes') or [])} lanes; "
        "no inflated parent closure; every CLOSED lane cites mechanisms that exist."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
