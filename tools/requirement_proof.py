"""Parent/child requirement proof (RC-459).

Sole master: ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md
Derived machine view: governance/requirement_tree.json (must match master REQ comments)
Derived proof: reports/requirement_proof_latest.json
RC log is historical evidence, not a work queue.

Proof status (PASS/FAIL/NOT_PROVEN/UNAVAILABLE) is not execution state.
A child PASS never closes a parent.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOLE_MASTER = REPO / "ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md"
TREE_PATH = REPO / "governance" / "requirement_tree.json"
DERIVED_PATH = REPO / "reports" / "requirement_proof_latest.json"
VALID_PROOF = frozenset({"PASS", "FAIL", "NOT_PROVEN", "UNAVAILABLE"})

_REQ_RE = re.compile(
    r"<!--\s*REQ\s+id=(?P<id>\S+)\s+proof=(?P<proof>\S+)\s+"
    r"execution=(?P<execution>\S+)\s+closable=(?P<closable>\S+)"
    r"(?:\s+children=(?P<children>\S+))?"
    r"(?:\s+title=\"(?P<title>[^\"]*)\")?\s*-->"
)


def parse_master(path: Path | None = None) -> dict:
    p = path or SOLE_MASTER
    text = p.read_text(encoding="utf-8")
    items: list[dict] = []
    for m in _REQ_RE.finditer(text):
        children = [c for c in (m.group("children") or "").split(",") if c]
        items.append({
            "id": m.group("id"),
            "title": m.group("title") or m.group("id"),
            "proof": m.group("proof"),
            "execution": m.group("execution"),
            "closable": str(m.group("closable")).lower() == "true",
            "children": children,
        })
    if not items:
        raise ValueError("sole master has no REQ comments")
    return {
        "authority": "ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md",
        "derived_proof": "reports/requirement_proof_latest.json",
        "items": items,
    }


def load_tree(path: Path | None = None) -> dict:
    if path is not None:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
            raise ValueError("requirement tree must be an object with items[]")
        return doc
    if SOLE_MASTER.is_file():
        return parse_master()
    doc = json.loads(TREE_PATH.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
        raise ValueError("requirement_tree.json must be an object with items[]")
    return doc


def _by_id(items: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for it in items:
        if isinstance(it, dict) and it.get("id"):
            out[str(it["id"])] = it
    return out


def compute_item_proof(item: dict, by_id: dict[str, dict], *, _stack: frozenset[str] | None = None) -> str:
    iid = str(item.get("id") or "")
    stack = _stack or frozenset()
    if iid in stack:
        return "FAIL"
    declared = str(item.get("proof") or "NOT_PROVEN").upper()
    if declared not in VALID_PROOF:
        declared = "NOT_PROVEN"
    children = [str(c) for c in (item.get("children") or []) if str(c)]
    if not children:
        return declared
    child_proofs = []
    for cid in children:
        ch = by_id.get(cid)
        if ch is None:
            child_proofs.append("NOT_PROVEN")
            continue
        child_proofs.append(compute_item_proof(ch, by_id, _stack=stack | {iid}))
    if any(p == "FAIL" for p in child_proofs):
        return "FAIL"
    if any(p == "NOT_PROVEN" for p in child_proofs):
        return "NOT_PROVEN"
    if any(p == "UNAVAILABLE" for p in child_proofs):
        return "UNAVAILABLE"
    if all(p == "PASS" for p in child_proofs):
        if item.get("closable") is False:
            return "NOT_PROVEN"
        return "PASS"
    return "NOT_PROVEN"


def compute_proof_state(tree: dict | None = None) -> dict:
    tree = tree if tree is not None else load_tree()
    items = [i for i in tree.get("items") or [] if isinstance(i, dict)]
    by_id = _by_id(items)
    derived_items = []
    for it in items:
        proof = compute_item_proof(it, by_id)
        derived_items.append({
            "id": it.get("id"),
            "title": it.get("title"),
            "proof": proof,
            "execution": it.get("execution") or "PASSIVE",
            "closable": bool(it.get("closable", True)),
            "children": list(it.get("children") or []),
            "evidence": list(it.get("evidence") or []),
        })
    return {
        "authority": "ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md",
        "defect_ledger": "governance/root_cause_log.md",
        "items": derived_items,
    }


def requirement_proof_violations(
    *,
    tree: dict | None = None,
    derived: dict | None = None,
) -> list[str]:
    """BLOCK when derived view disagrees, or a parent is hand-set PASS over unfinished children."""
    try:
        tree = tree if tree is not None else load_tree()
    except (OSError, ValueError) as e:
        return [f"REQUIREMENT_PROOF: requirement_tree.json unreadable ({e})"]
    computed = compute_proof_state(tree)
    by_id = _by_id(list(tree.get("items") or []))
    out: list[str] = []
    for it in tree.get("items") or []:
        if not isinstance(it, dict):
            continue
        declared = str(it.get("proof") or "NOT_PROVEN").upper()
        computed_p = compute_item_proof(it, by_id)
        if declared == "PASS" and computed_p != "PASS":
            out.append(
                f"REQUIREMENT_PROOF: {it.get('id')} declared PASS but computed "
                f"{computed_p} — a child PASS never closes a parent"
            )
        if it.get("closable") is False and declared == "PASS":
            out.append(
                f"REQUIREMENT_PROOF: {it.get('id')} is a non-closable parent set PASS — "
                "parent boxes close only when complete stated parent scope passes"
            )
    if derived is None and DERIVED_PATH.is_file():
        try:
            derived = json.loads(DERIVED_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return out + ["REQUIREMENT_PROOF: derived proof file unreadable"]
    if isinstance(derived, dict):
        got = {
            str(i.get("id")): str(i.get("proof"))
            for i in (derived.get("items") or [])
            if isinstance(i, dict)
        }
        for i in computed["items"]:
            iid = str(i.get("id"))
            if got.get(iid) != i.get("proof"):
                out.append(
                    f"REQUIREMENT_PROOF: derived {iid} proof={got.get(iid)!r} "
                    f"!= computed {i.get('proof')!r}"
                )
    if SOLE_MASTER.is_file() and TREE_PATH.is_file() and tree is None:
        try:
            disk = json.loads(TREE_PATH.read_text(encoding="utf-8"))
            master = parse_master()
            disk_ids = [str(i.get("id")) for i in (disk.get("items") or []) if isinstance(i, dict)]
            master_ids = [str(i.get("id")) for i in master["items"]]
            if disk_ids != master_ids:
                out.append(
                    "REQUIREMENT_PROOF: governance/requirement_tree.json is not a "
                    "strict derive of the sole master"
                )
        except (OSError, ValueError, json.JSONDecodeError) as e:
            out.append(f"REQUIREMENT_PROOF: derived tree unreadable ({e})")
    return out


def write_derived(path: Path | None = None) -> dict:
    state = compute_proof_state()
    p = path or DERIVED_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tree = parse_master() if SOLE_MASTER.is_file() else load_tree()
    TREE_PATH.write_text(json.dumps(tree, indent=2) + "\n", encoding="utf-8")
    return state
