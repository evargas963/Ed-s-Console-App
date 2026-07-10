#!/usr/bin/env python3
"""UNIVERSAL_INSTITUTIONAL_ENGINEERING_STANDARD_V1 — single-source enforcement.

One canonical machine-readable standard artifact governs HOW all repository
work must be done and proven:

    governance/standard/universal_institutional_engineering_standard_v1.json

This module is the single checker implementation (invoked from
tools/check_fix_everything_we_touch.py's repo-wide registry, which runs in
--enforce-all, --objective-audit, and the required CI gates — do not duplicate
this logic elsewhere). It enforces:

  1.  exactly one canonical objective (duplication scanner over governed files);
  2.  reference-only consumers carry the exact versioned reference token;
  3.  the generated human-readable rendering is byte-identical to the canonical;
  4.  canonical schema validity (required keys, principle IDs, version form);
  5.  separation of concerns (no priority/lane/SHA/PID/CI-state in the standard);
  6.  task-contract validation for any governed block declaring STANDARD_VERSION;
  7.  closure-contract gating when such a block claims closure;
  8.  explicit-exception format (UIES_EXCEPTION_APPROVED with all fields);
  9.  anti-weakening patterns in governed agent/operating files;
  10. no local redefinition of UIES principle IDs outside the canonical artifact.

Run standalone:  python tools/check_universal_standard.py
Regenerate MD:   python tools/check_universal_standard.py --render
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CANONICAL_PATH = REPO / "governance" / "standard" / "universal_institutional_engineering_standard_v1.json"
RENDERED_PATH = REPO / "governance" / "standard" / "UNIVERSAL_INSTITUTIONAL_ENGINEERING_STANDARD_V1.md"

# Governed agent/operating files that must reference (never restate) the standard.
REFERENCE_ONLY_CONSUMERS = (
    "AGENTS.md",
    "CLAUDE.md",
    ".cursor/rules/00-always.mdc",
    "governance/docs/AGENT_OPERATING_CONTRACT.md",
)

# Files scanned for duplicated objective text and weakening language.
GOVERNED_SCAN_GLOBS = (
    "AGENTS.md",
    "CLAUDE.md",
    "ACTIVE_PROGRAM.md",
    ".cursor/rules/*.mdc",
    "docs/governance/*.md",
    "governance/docs/*.md",
)

# Artifacts scanned for STANDARD_VERSION task-declaration blocks.
TASK_BLOCK_SCAN_GLOBS = (
    "OPEN_ITEMS.md",
    "ACTIVE_PROGRAM.md",
    "governance/*.md",
    "governance/docs/*.md",
    "reports/**/*.md",
)

REQUIRED_TOP_KEYS = (
    "artifact_id", "schema_version", "standard_version", "canonical",
    "primary_objective", "universal_principles", "required_task_declarations",
    "task_declaration_rules", "closure_contract", "prohibited_practices",
    "exception_rules", "reference_contract", "enforcement",
)
REQUIRED_PRINCIPLE_IDS = tuple(f"UIES-P{i:02d}" for i in range(1, 13))
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

TASK_DECLARATION_FIELDS = (
    "STANDARD_VERSION", "INSTITUTIONAL_CAPABILITY_ADVANCED", "ROOT_CAUSE_TARGET",
    "MONEY_PATH_IMPACT", "UNIVERSALITY_DIMENSIONS", "TRUTH_SEMANTICS",
    "FAIL_CLOSED_REQUIREMENT", "MECHANICAL_REGRESSION_LOCK", "REQUIRED_PROOF",
    "MISSION_OWNED_SCOPE", "EXCEPTIONS", "BINARY_ACCEPTANCE_CRITERIA",
)
_TASK_BLOCK_WINDOW = 60  # lines after STANDARD_VERSION within which fields must appear

# Vague-capability rejection (UIES-P01): concrete technical outcome required.
_VAGUE_CAPABILITY_RE = re.compile(
    r"^\s*(better|improve(d)?( quality)?|institutional[- ]grade|quality|good|nicer|cleanup|"
    r"polish|misc(ellaneous)?|general improvements?|n/?a|tbd)\s*\.?\s*$",
    re.IGNORECASE,
)

_CLOSURE_LANGUAGE_RE = re.compile(r"\bCLOSED_WITH_EVIDENCE\b|\bCLOSED\b")
_CLOSURE_CONTRACT_RE = re.compile(r"^CLOSURE_CONTRACT = ANSWERED @ (?P<ref>\S+)", re.MULTILINE)

_EXCEPTION_MARKER = "UIES_EXCEPTION_APPROVED"
_EXCEPTION_RE = re.compile(
    r"UIES_EXCEPTION_APPROVED:\s*scope=\S.*?justification=\S.*?approved_by=\S.*?bound=\S",
)

# Anti-weakening: governed files may reinforce but never override the standard.
_WEAKENING_RE = re.compile(
    r"(override|supersede|ignore|disregard|replace|instead of)[^.\n]{0,80}"
    r"(universal[^.\n]{0,40}standard|UIES-)",
    re.IGNORECASE,
)

# Local redefinition of principle IDs (definitions, not citations).
_REDEFINITION_RE = re.compile(r"[\"']UIES-P\d{2}[\"']\s*[:=]")

# Separation of concerns: the standard must never carry current work-selection data.
_PRIORITY_LEAK_TOKENS = (
    "next_lane", "active_lane", "priority_order", "current_priority",
    "recommended_next", "ci_state", "current_sha", "current_pid",
)
_HEX40_RE = re.compile(r"\b[0-9a-f]{40}\b")

_STATUS_FIELD_RE = re.compile(r"^([A-Z][A-Z0-9_]*_STATUS)\s*=\s*(.+)$")
_ALLOWED_STATUS_VALUES = {
    "PROVEN", "NOT_PROVEN", "APPROVED", "NOT_APPROVED", "PASS", "FAIL",
    "CLOSED_WITH_EVIDENCE", "NOT_CLOSED", "AUTHORIZED", "NOT_AUTHORIZED",
    "OPEN", "IN_PROGRESS", "BLOCKED", "YES", "NO",
}


def _load_canonical(path: Path = CANONICAL_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower())


def _objective_shingles(objective_text: str, width: int = 8) -> set[str]:
    words = _normalize(objective_text).split()
    return {" ".join(words[i : i + width]) for i in range(0, max(0, len(words) - width + 1))}


def _rel(p: Path) -> str:
    """Repo-relative display path; falls back to the raw path outside the repo
    (test fixtures exercise the checker against temp files)."""
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


def _iter_governed_files(globs=GOVERNED_SCAN_GLOBS) -> list[Path]:
    out: list[Path] = []
    for g in globs:
        out.extend(sorted(REPO.glob(g)))
    return [p for p in out if p.is_file()]


def render_markdown(artifact: dict) -> str:
    """Deterministic human-readable rendering — DERIVED from the canonical
    artifact; the on-disk MD must match this byte-for-byte (drift check)."""
    a = artifact
    lines = [
        "> **Classification:** Generated Rendering | **Scope:** Universal engineering"
        " standard (derived; canonical source is the JSON artifact).",
        "",
        "<!-- GENERATED FILE — DO NOT EDIT. Derived from "
        "governance/standard/universal_institutional_engineering_standard_v1.json "
        "by tools/check_universal_standard.py --render. Drift fails governance. -->",
        "",
        f"# {a['artifact_id']} (v{a['standard_version']})",
        "",
        f"**Answers:** {a['answers']}",
        f"**Does not answer:** {a['does_not_answer']}",
        "",
        f"**Applicability:** {a['applicability']}",
        "",
        f"## Primary objective ({a['primary_objective']['id']})",
        "",
        a["primary_objective"]["text"],
        "",
        "## Universal principles",
        "",
    ]
    for p in a["universal_principles"]:
        lines.append(f"### {p['id']} — {p['name']}")
        lines.append("")
        lines.append(p["text"])
        lines.append("")
    lines.append("## Required task declarations")
    lines.append("")
    for f in a["required_task_declarations"]:
        lines.append(f"- `{f}`")
    lines.append("")
    lines.append(f"- Trigger: {a['task_declaration_rules']['trigger']}")
    lines.append(f"- Priority exclusion: {a['task_declaration_rules']['priority_exclusion']}")
    lines.append("")
    lines.append(f"## Closure contract ({a['closure_contract']['id']})")
    lines.append("")
    for i, q in enumerate(a["closure_contract"]["questions"], 1):
        lines.append(f"{i}. {q}")
    lines.append("")
    lines.append(a["closure_contract"]["rule"])
    lines.append("")
    lines.append("## Prohibited practices")
    lines.append("")
    for pr in a["prohibited_practices"]:
        lines.append(f"- {pr}")
    lines.append("")
    lines.append("## Exceptions")
    lines.append("")
    lines.append(a["exception_rules"]["rule"])
    lines.append(f"- Format: `{a['exception_rules']['format']}`")
    lines.append("")
    lines.append("## Domain profiles")
    lines.append("")
    for d in a.get("domain_profiles", []):
        lines.append(f"- **{d['id']}** ({d['path']}): {d['relationship']}")
    lines.append("")
    lines.append("## Enforcement")
    lines.append("")
    lines.append(f"- Checker: `{a['enforcement']['checker']}`")
    for inv in a["enforcement"]["invoked_from"]:
        lines.append(f"- Invoked from: {inv}")
    lines.append(f"- Tests: `{a['enforcement']['tests']}`")
    lines.append("")
    return "\n".join(lines)


def check_universal_standard_canonical_integrity() -> list[str]:
    """Canonical artifact exists, is schema-valid, versioned, and carries the
    objective + all 12 principle IDs. Exactly one canonical source."""
    errors: list[str] = []
    if not CANONICAL_PATH.is_file():
        return [f"{CANONICAL_PATH}: canonical standard artifact missing"]
    try:
        a = _load_canonical()
    except ValueError as e:
        return [f"{CANONICAL_PATH}: canonical artifact is not valid JSON ({e})"]
    for k in REQUIRED_TOP_KEYS:
        if k not in a:
            errors.append(f"canonical standard: required key missing: {k}")
    if errors:
        return errors
    if a.get("canonical") is not True:
        errors.append("canonical standard: canonical flag must be true")
    if not _VERSION_RE.match(str(a.get("standard_version", ""))):
        errors.append(f"canonical standard: invalid standard_version {a.get('standard_version')!r}")
    if not str(a["primary_objective"].get("text", "")).strip():
        errors.append("canonical standard: primary objective text missing")
    ids = [p.get("id") for p in a.get("universal_principles", [])]
    for pid in REQUIRED_PRINCIPLE_IDS:
        if pid not in ids:
            errors.append(f"canonical standard: required principle id missing: {pid}")
    for p in a.get("universal_principles", []):
        if not str(p.get("text", "")).strip():
            errors.append(f"canonical standard: principle {p.get('id')} has empty text")
    if tuple(a.get("required_task_declarations", ())) != TASK_DECLARATION_FIELDS:
        errors.append("canonical standard: required_task_declarations do not match the enforced contract")
    # Separation of concerns: no work-prioritization or temporary runtime state.
    raw = CANONICAL_PATH.read_text(encoding="utf-8").lower()
    for tok in _PRIORITY_LEAK_TOKENS:
        if tok in raw:
            errors.append(f"canonical standard: prioritization/status leak token present: {tok}")
    if _HEX40_RE.search(raw):
        errors.append("canonical standard: contains a 40-hex SHA — temporary identity data is forbidden here")
    # Exactly-one-canonical: no other file may declare this artifact_id as canonical JSON.
    for p in REPO.glob("governance/**/*.json"):
        if p.resolve() == CANONICAL_PATH.resolve():
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if '"canonical": true' in txt and "UNIVERSAL_INSTITUTIONAL_ENGINEERING_STANDARD" in txt:
            errors.append(f"{p}: competing canonical standard artifact detected")
    return errors


def check_universal_standard_rendering() -> list[str]:
    """Generated MD rendering must exist and match the canonical byte-for-byte."""
    if not CANONICAL_PATH.is_file():
        return []  # canonical check reports the root failure
    a = _load_canonical()
    expected = render_markdown(a)
    if not RENDERED_PATH.is_file():
        return [f"{RENDERED_PATH}: generated rendering missing — run tools/check_universal_standard.py --render"]
    actual = RENDERED_PATH.read_text(encoding="utf-8")
    if actual != expected:
        return [
            f"{RENDERED_PATH}: rendering drift vs canonical artifact — regenerate with"
            " tools/check_universal_standard.py --render (do not hand-edit the MD)"
        ]
    return []


def check_universal_standard_references() -> list[str]:
    """Reference-only consumers carry the exact versioned token; governed files
    never duplicate the objective, weaken the standard, or redefine UIES ids."""
    if not CANONICAL_PATH.is_file():
        return []
    a = _load_canonical()
    token = a["reference_contract"]["required_reference_token"]
    errors: list[str] = []
    if a["standard_version"] not in token:
        errors.append("canonical standard: reference token does not embed the current standard_version")
    for rel in REFERENCE_ONLY_CONSUMERS:
        p = REPO / rel
        if not p.is_file():
            errors.append(f"{rel}: governed reference consumer missing")
            continue
        if token not in p.read_text(encoding="utf-8", errors="replace"):
            errors.append(f"{rel}: missing required standard reference token (or wrong version)")
    shingles = _objective_shingles(a["primary_objective"]["text"])
    exempt = {CANONICAL_PATH.resolve(), RENDERED_PATH.resolve()}
    for p in _iter_governed_files():
        if p.resolve() in exempt:
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        norm = _normalize(txt)
        dup_hits = sum(1 for s in shingles if s in norm)
        if dup_hits >= 2:
            errors.append(
                f"{_rel(p)}: duplicates the primary objective"
                f" ({dup_hits} matching phrases) — reference the canonical standard instead"
            )
        if _WEAKENING_RE.search(txt):
            errors.append(f"{_rel(p)}: language weakens/overrides the universal standard")
        if _REDEFINITION_RE.search(txt):
            errors.append(f"{_rel(p)}: redefines UIES principle ids locally")
    return errors


def _task_blocks(text: str) -> list[tuple[int, list[str]]]:
    lines = text.splitlines()
    blocks = []
    for i, ln in enumerate(lines):
        if re.match(r"^\s*STANDARD_VERSION\s*=", ln):
            blocks.append((i + 1, lines[i : i + _TASK_BLOCK_WINDOW]))
    return blocks


def check_universal_standard_task_contracts() -> list[str]:
    """Any governed block declaring STANDARD_VERSION must satisfy the full
    task contract; closure claims inside it require the closure contract."""
    if not CANONICAL_PATH.is_file():
        return []
    errors: list[str] = []
    seen: set[Path] = set()
    for g in TASK_BLOCK_SCAN_GLOBS:
        for p in sorted(REPO.glob(g)):
            if not p.is_file() or p.resolve() in seen or p.resolve() == RENDERED_PATH.resolve():
                continue
            seen.add(p.resolve())
            txt = p.read_text(encoding="utf-8", errors="replace")
            for lineno, block in _task_blocks(txt):
                body = "\n".join(block)
                errors.extend(_validate_task_block(p, lineno, body))
            for m in re.finditer(_EXCEPTION_MARKER, txt):
                line = txt[txt.rfind("\n", 0, m.start()) + 1 : txt.find("\n", m.end()) if txt.find("\n", m.end()) != -1 else len(txt)]
                if not _EXCEPTION_RE.search(line):
                    errors.append(
                        f"{_rel(p)}: {_EXCEPTION_MARKER} without required"
                        " fields (scope/justification/approved_by/bound) — silent/underspecified exception"
                    )
    return errors


def _validate_task_block(path: Path, lineno: int, body: str) -> list[str]:
    rel = _rel(path)
    errors: list[str] = []
    for field in TASK_DECLARATION_FIELDS:
        if not re.search(rf"^\s*{field}\s*=", body, re.MULTILINE):
            errors.append(f"{rel}:{lineno}: task contract missing declaration: {field}")
    m = re.search(r"^\s*INSTITUTIONAL_CAPABILITY_ADVANCED\s*=\s*(.+)$", body, re.MULTILINE)
    if m and _VAGUE_CAPABILITY_RE.match(m.group(1)):
        errors.append(
            f"{rel}:{lineno}: INSTITUTIONAL_CAPABILITY_ADVANCED is vague"
            f" ({m.group(1).strip()!r}) — name the concrete technical outcome"
        )
    m = re.search(r"^\s*STANDARD_VERSION\s*=\s*(\S+)", body, re.MULTILINE)
    if m:
        declared = m.group(1).strip()
        canonical_version = _load_canonical()["standard_version"]
        if declared != canonical_version:
            errors.append(
                f"{rel}:{lineno}: STANDARD_VERSION {declared!r} does not match"
                f" canonical {canonical_version!r}"
            )
    if _CLOSURE_LANGUAGE_RE.search(body) and not _CLOSURE_CONTRACT_RE.search(body):
        errors.append(
            f"{rel}:{lineno}: closure claimed inside a task-contract block without"
            " 'CLOSURE_CONTRACT = ANSWERED @ <evidence-artifact>'"
        )
    cm = _CLOSURE_CONTRACT_RE.search(body)
    if cm:
        ref = cm.group("ref")
        if not (REPO / ref).exists():
            errors.append(f"{rel}:{lineno}: closure-contract evidence artifact missing: {ref}")
    for ln in body.splitlines():
        sm = _STATUS_FIELD_RE.match(ln.strip())
        if sm and sm.group(2).strip().split()[0].upper() not in _ALLOWED_STATUS_VALUES:
            errors.append(
                f"{rel}:{lineno}: ambiguous status value in governed field"
                f" {sm.group(1)} = {sm.group(2).strip()!r}"
            )
    return errors


def check_universal_standard() -> list[str]:
    """Aggregate entry point for the enforcement registries."""
    return (
        check_universal_standard_canonical_integrity()
        + check_universal_standard_rendering()
        + check_universal_standard_references()
        + check_universal_standard_task_contracts()
    )


def main() -> int:
    if "--render" in sys.argv:
        a = _load_canonical()
        RENDERED_PATH.parent.mkdir(parents=True, exist_ok=True)
        RENDERED_PATH.write_text(render_markdown(a), encoding="utf-8")
        print(f"rendered: {RENDERED_PATH}")
        return 0
    errors = check_universal_standard()
    for e in errors:
        print(f"UNIVERSAL_STANDARD: {e}")
    print(f"check_universal_standard: {'FAIL' if errors else 'PASS'} ({len(errors)} error(s))")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
