"""Mockup-before-code lock (RC-186) — a UI redesign surface may not be edited until the
operator has approved a rendered mockup variant.

WHY THIS EXISTS. Operator law, stated as NON-NEGOTIABLE on 2026-08-02 for the Chart-tab
redesign: "before we do anything and this is a non negotiable we render mock ups." Until this
module, design-approval was a chat event that never became machine-readable state, so no hook
could consult it — the RC-66/RC-93 goodwill-instead-of-lock class. The measured precedent is
the 2026-07-25 UI rebuild that wiped two working screens without consent.

STATE. `governance/ui_mockup_approvals.json` maps repo-relative surface paths to entries:
  status='design_pending'  -> edits BLOCKED until the operator approves a mockup variant
  status='approved' + approved_variant -> edits flow
Surfaces not listed are not gated by this lock (RC-66 and the other locks still apply).

CONTINUUM. Front end: tools/pretooluse_guard.py calls `mockup_approval_violation` and blocks
the Edit/Write. Back end: check `ui_mockup_approval` in tools/check_institutional_correctness.py
runs the same callee over staged files and blocks the commit.

ESCAPES (deliberate and visible, never silent): a non-redesign bug fix declares
`# ui-mockup-ok: <reason>` in the edited text; the operator may set ED_UI_MOCKUP_LOCK=off.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REGISTRY_REL = "governance/ui_mockup_approvals.json"
ESCAPE_TOKEN = "ui-mockup-ok:"
#: RC-189 GUN 3 — the escape is a DECLARATION, not a substring: it must be written as
#: `# ui-mockup-ok: <reason>` (comment marker, token, a real reason). Bare or mid-word
#: occurrences of the token no longer unlock anything.
_ESCAPE_RE = re.compile(r"(?:^|[^\w-])#\s*ui-mockup-ok:\s*\S", re.M)
#: RC-189 GUN 1 — the operator's approval grant. This env var is OPERATOR-CHANNEL ONLY: it is
#: read from the HOOK process environment (set at the Claude Code session level, which agents'
#: shell commands cannot reach), agents may not mint it into settings files, and
#: operator_law_guard blocks any shell command that even names it.
APPROVE_ENV = "ED_UI_MOCKUP_APPROVE"
_STATUS_APPROVED_RE = re.compile(r'"status"\s*:\s*"approved"')

#: The registry entry SCHEMA, stated in code so the shape is visible to static analysis (the
#: keys are authored in the JSON registry by the operator approval flow; this constant is the
#: single place a reader — or the orphan-key lead list — learns the field names).
REGISTRY_ENTRY_SCHEMA: dict = {
    "status": "design_pending",
    "opened": None,
    "scope": None,
    "mockups_rendered": None,
    "approved_variant": None,
    "approved_on": None,
    "operator_quote": None,
    "approved_channel": None,
}


def _norm_rel(rel: str) -> str:
    """One path spelling: forward slashes, dot-segments collapsed, lowercase (Windows paths
    are case-insensitive, so `Static/Chart.HTML` must gate like `static/chart.html`)."""
    return posixpath.normpath(rel.replace("\\", "/")).lower()

# RC-188 NOTE: a render-ban on unproven level identifiers briefly lived here (2026-08-02) and
# was REVERTED the same turn on operator correction: the law is "prove all the unproven",
# never "hide the unproven". Unresolved scientific claims live on the sole master.
# governance/unproven_register.md is historical evidence only and has zero commit-block
# authority. Render-rights are not gated on proof.


def _load_registry(repo: Path | None = None) -> dict:
    """Read the approvals registry; unreadable/absent reads as EMPTY (gate nothing), because a
    missing registry means no surface was ever placed under the law — not that all were."""
    root = repo if repo is not None else REPO
    try:
        data = json.loads((root / REGISTRY_REL).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def mockup_gated_entry(rel: str, repo: Path | None = None) -> dict | None:
    """The registry entry for a repo-relative path, or None when the path is not gated."""
    surfaces = _load_registry(repo).get("surfaces")
    if not isinstance(surfaces, dict):
        return None
    want = _norm_rel(rel)
    for key, entry in surfaces.items():
        if _norm_rel(str(key)) == want and isinstance(entry, dict):
            return entry
    return None


def _grant_present() -> bool:
    """The operator's session-level grant. Read from THIS process's environment — for hooks
    that is the Claude Code app environment, which agent shell commands cannot reach (and
    typing the variable in a shell is itself a blocked action in operator_law_guard)."""
    return os.environ.get(APPROVE_ENV, "").strip().lower() in ("1", "true", "yes")


def _entry_has_operator_provenance(entry: dict) -> bool:
    """RC-189 GUN 1: an approval unlocks ONLY when it carries the operator's provenance —
    a bare status flip (however it got written) grants nothing."""
    quote = entry.get("operator_quote")
    return (str(entry.get("status", "")).strip().lower() == "approved"
            and bool(entry.get("approved_variant"))
            and bool(entry.get("approved_on"))
            and isinstance(quote, str) and len(quote.strip()) >= 8)


def mockup_approval_violation(rel: str, new_text: str = "",
                              repo: Path | None = None) -> str | None:
    """Reason the edit is blocked under the mockup-before-code law, or None when it may flow.

    `new_text` is the text about to be written (Write content / ONE Edit new_string — the
    caller passes MultiEdit edits one at a time, RC-189 GUN 3); the `# ui-mockup-ok: <reason>`
    declaration is honoured only when it appears THERE, so the waiver travels with the change
    that claims it.
    """
    if os.environ.get("ED_UI_MOCKUP_LOCK", "").strip().lower() in ("off", "0", "false"):
        return None
    entry = mockup_gated_entry(rel, repo)
    if entry is None:
        return None
    # Cursor v2 compound seal: a forged-but-complete registry entry must still not unlock.
    # Provenance fields AND the live operator grant are required together — the fields are
    # the auditable record, the grant is the operator state no agent channel can produce.
    if _entry_has_operator_provenance(entry) and _grant_present():
        return None
    if _ESCAPE_RE.search(new_text or ""):
        return None
    status = str(entry.get("status", "")).strip().lower()
    return (
        f"{rel} is under the mockup-before-code law (RC-186; status={status or 'unset'!r}"
        f"{'' if status != 'approved' else (' WITHOUT the operator grant ' + APPROVE_ENV if not _grant_present() else ' WITHOUT operator provenance')}). "
        f"Render mockups INLINE IN CHAT (never repo files), get the operator to approve ONE "
        f"variant, record it in {REGISTRY_REL} (status='approved', approved_variant, "
        f"approved_on, operator_quote), then edit. Non-redesign bug fix: declare "
        f"'# {ESCAPE_TOKEN} <reason>' in the edit."
    )


def tool_input_texts(tool_input: dict) -> list[str]:
    """Every text the tool intends to write, ONE ENTRY PER EDIT (RC-189 GUN 3): a MultiEdit
    escape declaration must be judged per edit, so one waiver cannot unlock its siblings."""
    out: list[str] = []
    content = tool_input.get("content")
    if isinstance(content, str) and content:
        out.append(content)
    new_string = tool_input.get("new_string")
    if isinstance(new_string, str) and new_string:
        out.append(new_string)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for ed in edits:
            if isinstance(ed, dict) and isinstance(ed.get("new_string"), str) \
                    and ed.get("new_string"):
                out.append(ed["new_string"])
    return out


def registry_mutation_violation(rel: str, new_text: str = "") -> str | None:
    """RC-189 GUN 1: the approval REGISTRY and the approval GRANT are themselves gated.

    Blocks (returns a reason) when:
      * an Edit/Write to the registry introduces `"status": "approved"` without BOTH the
        operator grant env ({APPROVE_ENV}, set at the session level — an operator channel the
        agent's shell cannot reach) AND an `operator_quote` in the same written text; or
      * an Edit/Write to a `.claude` settings file introduces the grant variable name (an
        agent may not mint the operator's channel into session config).
    """
    text = new_text or ""
    nrel = _norm_rel(rel)
    if nrel.endswith((".claude/settings.json", ".claude/settings.local.json")) \
            and APPROVE_ENV in text:
        return (f"{rel}: writing {APPROVE_ENV} into session settings would mint the operator's "
                f"approval channel (RC-189). Only the operator sets that variable, outside "
                f"agent-editable files.")
    if nrel != _norm_rel(REGISTRY_REL):
        return None
    if not _STATUS_APPROVED_RE.search(text):
        return None
    granted = _grant_present()
    has_quote = '"operator_quote"' in text
    if granted and has_quote:
        return None
    missing = []
    if not granted:
        missing.append(f"{APPROVE_ENV} operator grant absent from the session environment")
    if not has_quote:
        missing.append("operator_quote absent from the written approval")
    return (
        f"{rel}: this edit records an APPROVAL, and approval is the OPERATOR'S action "
        f"(RC-189: {'; '.join(missing)}). Self-approve is the exact dodge Cursor proved. "
        f"The operator approves in chat, sets {APPROVE_ENV}=1 on the session, and the "
        f"recording carries their verbatim quote."
    )
