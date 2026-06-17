#!/usr/bin/env python3
"""Mechanical checks for repo hygiene policy + clean-as-we-touch (Phase 3I)."""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INVENTORY_PATH = REPO / "governance" / "artifacts" / "REPO_HYGIENE_INVENTORY.json"
BACKLOG_PATH = REPO / "governance" / "artifacts" / "REPO_HYGIENE_BACKLOG.json"
POLICY_MD = REPO / "governance" / "docs" / "REPO_HYGIENE_POLICY.md"
AGENTS_MD = REPO / "AGENTS.md"

HYGIENE_DISPOSITION_MARKERS = (
    "HYGIENE: cleaned",
    "HYGIENE: deferred_with_reason",
    "HYGIENE: manual_review_required",
)

# Backlog rows that may require commit-msg disposition — not generic weak-reference inventory.
ACTIONABLE_BACKLOG_CATEGORIES = frozenset(
    {
        "orphan_candidate",
        "dead_code_candidate",
        "duplicate_candidate",
        "deprecated_candidate",
    }
)

VAGUE_HYGIENE_RE = re.compile(r"\bHYGIENE\s*:", re.IGNORECASE)

# Same-directory intersection is too broad for these roots (100+ siblings).
_BROAD_PACKAGE_DIRS = frozenset(
    {
        "tools",
        "tests",
        "governance",
        "governance/artifacts",
        "governance/docs",
        "static",
        "features",
        "calibration",
    }
)


def _has_valid_hygiene_disposition(text: str) -> bool:
    """Exact disposition tokens only — 'HYGIENE: cleaned up' is not 'HYGIENE: cleaned'."""
    for marker in HYGIENE_DISPOSITION_MARKERS:
        for m in re.finditer(re.escape(marker), text):
            end = m.end()
            if end >= len(text) or text[end] in "\n\r":
                return True
    return False

AGENTS_MARKERS = (
    "Clean as we touch",
    "check_repo_hygiene_policy",
    "REPO_HYGIENE_INVENTORY.json",
    "REPO_HYGIENE_BACKLOG.json",
)


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _cone_prefix(rel: str) -> str:
    p = Path(rel)
    if len(p.parts) >= 2:
        return "/".join(p.parts[:2])
    return p.parts[0] if p.parts else rel


def _norm_rel(rel: str) -> str:
    return Path(rel.replace("\\", "/")).as_posix()


def _is_actionable_backlog_item(item: dict) -> bool:
    if item.get("status") != "open":
        return False
    return str(item.get("category") or "") in ACTIONABLE_BACKLOG_CATEGORIES


def staged_intersects_actionable_candidate(staged_rel: str, candidate: str) -> bool:
    """True when staged path is the candidate or an adjacent module (not broad package roots)."""
    staged = Path(_norm_rel(staged_rel))
    cand = Path(_norm_rel(candidate))
    if staged.as_posix() == cand.as_posix():
        return True
    if staged.parent.as_posix() != cand.parent.as_posix():
        return False
    parent = staged.parent.as_posix()
    if parent in _BROAD_PACKAGE_DIRS or parent == ".":
        return False
    return True


def actionable_backlog_hits_for_staged(staged: set[str], backlog: dict) -> list[dict]:
    """Open actionable backlog items intersecting any staged path (not whole-repo cone)."""
    hits: list[dict] = []
    seen: set[str] = set()
    for rel in staged:
        if not rel.endswith((".py", ".md", ".html", ".js", ".json")):
            continue
        for item in backlog.get("items") or []:
            if not _is_actionable_backlog_item(item):
                continue
            cand = str(item.get("candidate") or "")
            if not cand or cand in seen:
                continue
            if staged_intersects_actionable_candidate(rel, cand):
                seen.add(cand)
                hits.append(item)
    return hits


def open_backlog_in_cone(cone_prefix: str, backlog: dict) -> list[dict]:
    """Legacy helper — actionable items only, same cone prefix."""
    hits: list[dict] = []
    for item in backlog.get("items") or []:
        if not _is_actionable_backlog_item(item):
            continue
        cand = str(item.get("candidate") or "")
        if _cone_prefix(cand) == cone_prefix or cand.startswith(cone_prefix + "/"):
            hits.append(item)
    return hits


def check_hygiene_touch_disposition(*, staged: set[str], commit_text: str = "") -> list[str]:
    """Fail when staged paths intersect actionable backlog items without exact HYGIENE disposition."""
    errors: list[str] = []
    backlog = _load_json(BACKLOG_PATH)
    if not backlog:
        return errors
    text = commit_text or ""
    hits = actionable_backlog_hits_for_staged(staged, backlog)

    if VAGUE_HYGIENE_RE.search(text) and not _has_valid_hygiene_disposition(text):
        errors.append(
            "repo hygiene: commit message mentions HYGIENE without an exact disposition — "
            f"use one of {list(HYGIENE_DISPOSITION_MARKERS)!r}"
        )

    if not hits:
        return errors

    if not _has_valid_hygiene_disposition(text):
        sample = hits[0].get("candidate")
        errors.append(
            f"repo hygiene: staged paths intersect {len(hits)} actionable backlog item(s) "
            f"(e.g. {sample!r}) — commit message must include one of "
            f"{list(HYGIENE_DISPOSITION_MARKERS)!r}"
        )
    return errors


def check_repo_hygiene_policy() -> list[str]:
    errors: list[str] = []

    if not POLICY_MD.is_file():
        errors.append("governance/docs/REPO_HYGIENE_POLICY.md: missing")
    else:
        policy = POLICY_MD.read_text(encoding="utf-8", errors="replace")
        for marker in ("**Scope:**", "Clean as we touch", "safe_to_remove", "manual_review_required"):
            if marker not in policy:
                errors.append(f"REPO_HYGIENE_POLICY.md: missing marker {marker!r}")

    inv = _load_json(INVENTORY_PATH)
    if not inv:
        errors.append("governance/artifacts/REPO_HYGIENE_INVENTORY.json: missing or unreadable")
    else:
        if inv.get("schema_version") != 1:
            errors.append("REPO_HYGIENE_INVENTORY.json: schema_version must be 1")
        summary = inv.get("summary") or {}
        if not summary.get("by_category"):
            errors.append("REPO_HYGIENE_INVENTORY.json: summary.by_category empty")
        for cat in (
            "active_runtime",
            "generated_artifact",
            "manual_review_required",
        ):
            if cat not in (summary.get("by_category") or {}):
                errors.append(f"REPO_HYGIENE_INVENTORY.json: missing category count {cat!r}")

    backlog = _load_json(BACKLOG_PATH)
    if not backlog:
        errors.append("governance/artifacts/REPO_HYGIENE_BACKLOG.json: missing or unreadable")
    elif not isinstance(backlog.get("items"), list):
        errors.append("REPO_HYGIENE_BACKLOG.json: items must be a list")
    elif backlog.get("actionable_only") is not True:
        errors.append("REPO_HYGIENE_BACKLOG.json: actionable_only must be true (no weak-reference rows)")

    if AGENTS_MD.is_file():
        agents = AGENTS_MD.read_text(encoding="utf-8", errors="replace")
        for marker in AGENTS_MARKERS:
            if marker not in agents:
                errors.append(f"AGENTS.md: missing repo hygiene marker {marker!r}")
    else:
        errors.append("AGENTS.md: missing")

    builder = REPO / "tools" / "build_repo_hygiene_inventory.py"
    if not builder.is_file():
        errors.append("tools/build_repo_hygiene_inventory.py: missing")

    # safe_to_remove rows must cite removal proof in backlog (none in Phase 3I launch)
    if inv:
        safe_paths = [
            e["path"]
            for e in inv.get("entries") or []
            if e.get("category") == "safe_to_remove"
        ]
        for path in safe_paths:
            proof = any(
                str(i.get("candidate")) == path and i.get("status") == "removal_proven"
                for i in (backlog or {}).get("items") or []
            )
            if not proof:
                errors.append(
                    f"repo hygiene: {path!r} marked safe_to_remove without backlog removal_proven row"
                )

    return errors


def main() -> int:
    errs = check_repo_hygiene_policy()
    if errs:
        print("check_repo_hygiene_policy: FAIL\n- " + "\n- ".join(errs))
        return 1
    print("check_repo_hygiene_policy: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
