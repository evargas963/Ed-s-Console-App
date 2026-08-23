"""Canonical executable PM-authority reader (RC-456).

THE ONLY production computation of executable PM state.

Authoritative path (host-owned, not Git):
    /var/lib/ed-console-authority/pm_mission.json

Git-tracked ``governance/pm_mission.json`` and ``governance/sole_writer.json``
are NON-AUTHORITATIVE. This module never reads them as a fallback.

Missing, unreadable, malformed, pm-missing, or pm!='operator' → FAIL CLOSED.
Do not synthesize operator authority. Do not silently use old repo metadata.

writer/auditor fields are never authorization.

Tests monkeypatch ``CANONICAL_AUTHORITY_PATH``. There is no env-var override
that can point this reader at the repository JSON.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

CANONICAL_DIR = Path("/var/lib/ed-console-authority")
CANONICAL_AUTHORITY_PATH = CANONICAL_DIR / "pm_mission.json"
REPO_PM_MISSION_TEMPLATE = REPO / "governance" / "pm_mission.json"
REPO_SOLE_WRITER_TOMBSTONE = REPO / "governance" / "sole_writer.json"

REQUIRED_PM = "operator"


@dataclass(frozen=True)
class PmAuthorityLoad:
    doc: dict | None
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.doc is not None and not self.violations


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()


def path_is_inside_repo(path: Path) -> bool:
    try:
        resolved = _resolved(path)
        repo = REPO.resolve()
        return resolved == repo or repo in resolved.parents
    except (OSError, RuntimeError):
        return True


def is_canonical_authority_path(raw: str | Path) -> bool:
    """True when *raw* names the executable authority file (after resolve)."""
    try:
        p = Path(str(raw))
        if not p.is_absolute():
            p = REPO / p
        return _resolved(p) == _resolved(CANONICAL_AUTHORITY_PATH)
    except (OSError, RuntimeError):
        return False


def validate_pm_authority_document(
    new_text: str,
    *,
    current_text: str | None = None,
    current_exists: bool = True,
) -> list[str]:
    """THE only PM-authority document validator.

    writer/auditor are ignored. ``pm`` must be exactly ``operator``.
    When a current valid document exists, scope_paths may not expand and
    remaining[] may not be dropped (same rules as the former repo-file check).
    """
    try:
        new_doc = json.loads(new_text)
    except (ValueError, json.JSONDecodeError):
        return ["PM_AUTHORITY: proposed content is not valid JSON"]
    if not isinstance(new_doc, dict):
        return ["PM_AUTHORITY: proposed content is not a JSON object"]
    if "pm" not in new_doc:
        return ["PM_AUTHORITY: pm is missing — refuse to synthesize operator"]
    new_pm = new_doc.get("pm")
    if not isinstance(new_pm, str) or new_pm != REQUIRED_PM:
        return [
            f"PM_AUTHORITY: pm={new_pm!r} — required exactly {REQUIRED_PM!r}"
        ]

    cur_doc: dict = {}
    if current_exists and current_text is not None:
        try:
            parsed = json.loads(current_text)
            if isinstance(parsed, dict) and parsed.get("pm") == REQUIRED_PM:
                cur_doc = parsed
        except (ValueError, json.JSONDecodeError):
            cur_doc = {}
    if cur_doc:
        old_scope = set(map(str, cur_doc.get("scope_paths") or []))
        new_scope = set(map(str, new_doc.get("scope_paths") or []))
        if new_scope - old_scope:
            return [
                f"PM_AUTHORITY: expands scope_paths by {sorted(new_scope - old_scope)!r} "
                "— scope expansion is operator-only"
            ]
        if cur_doc.get("remaining") and not new_doc.get("remaining"):
            return [
                "PM_AUTHORITY: deletes remaining[] — dropping the work queue is operator-only"
            ]
    return []


def load_pm_authority() -> PmAuthorityLoad:
    """Read executable PM state. Never opens the Git-tracked template."""
    path = CANONICAL_AUTHORITY_PATH
    try:
        resolved = _resolved(path)
    except (OSError, RuntimeError):
        return PmAuthorityLoad(None, ["PM_AUTHORITY: canonical path unresolvable — FAIL CLOSED"])
    if path_is_inside_repo(resolved):
        return PmAuthorityLoad(
            None,
            [
                "PM_AUTHORITY: canonical path resolved inside the Git repository — "
                "refuse repo JSON as executable authority (no fallback)"
            ],
        )
    if not resolved.is_file():
        return PmAuthorityLoad(
            None,
            [
                f"PM_AUTHORITY: missing {resolved} — FAIL CLOSED; "
                "do not use governance/pm_mission.json"
            ],
        )
    try:
        if resolved.is_symlink():
            return PmAuthorityLoad(
                None,
                ["PM_AUTHORITY: authority file is a symlink — FAIL CLOSED"],
            )
    except OSError:
        return PmAuthorityLoad(None, ["PM_AUTHORITY: authority file unreadable — FAIL CLOSED"])
    try:
        raw = resolved.read_text(encoding="utf-8")
    except OSError:
        return PmAuthorityLoad(None, ["PM_AUTHORITY: authority file unreadable — FAIL CLOSED"])
    errs = validate_pm_authority_document(raw, current_text=None, current_exists=False)
    if errs:
        return PmAuthorityLoad(None, errs)
    doc = json.loads(raw)
    return PmAuthorityLoad(doc, [])


def executable_mission() -> dict:
    """Mission dict for gating. Empty when FAIL CLOSED (not in-progress)."""
    loaded = load_pm_authority()
    return loaded.doc if loaded.ok and isinstance(loaded.doc, dict) else {}


def authority_unavailable_reasons() -> list[str]:
    loaded = load_pm_authority()
    return [] if loaded.ok else list(loaded.violations)


def write_atomic_authority(text: str, *, dest: Path | None = None) -> list[str]:
    """Atomic replace of the canonical authority file. No caller output path on the CLI.

    *dest* is the module canonical path unless tests monkeypatch
    ``CANONICAL_AUTHORITY_PATH`` and pass that same object. A different path
    is refused (blocks path injection).
    """
    target = dest if dest is not None else CANONICAL_AUTHORITY_PATH
    try:
        if _resolved(target) != _resolved(CANONICAL_AUTHORITY_PATH):
            return ["PM_AUTHORITY: write target is not the canonical authority path"]
    except (OSError, RuntimeError):
        return ["PM_AUTHORITY: write target unresolvable"]
    if path_is_inside_repo(target):
        return ["PM_AUTHORITY: refuse to write Git-tracked JSON as executable authority"]
    parent = target.parent
    try:
        if parent.is_symlink() or target.is_symlink():
            return ["PM_AUTHORITY: symlink/path-redirection refused"]
    except OSError:
        return ["PM_AUTHORITY: parent/target unreadable — refuse"]
    current_text = None
    current_exists = False
    if target.is_file() and not target.is_symlink():
        try:
            current_text = target.read_text(encoding="utf-8")
            current_exists = True
        except OSError:
            return ["PM_AUTHORITY: current authority unreadable — refuse"]
    errs = validate_pm_authority_document(
        text, current_text=current_text, current_exists=current_exists
    )
    if errs:
        return errs
    tmp = parent / f".{target.name}.tmp.{os.getpid()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        if tmp.exists() or tmp.is_symlink():
            return ["PM_AUTHORITY: temp path exists or is a symlink — refuse"]
        fd = os.open(str(tmp), flags, 0o644)
        try:
            os.write(fd, text.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(str(tmp), str(target))
    except OSError as exc:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return [f"PM_AUTHORITY: atomic write failed: {exc}"]
    if target.is_symlink():
        return ["PM_AUTHORITY: result is a symlink — refuse"]
    return []
