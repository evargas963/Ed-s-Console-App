#!/usr/bin/python3 -I
"""SELF-CONTAINED source of the privileged PM-authority write seam (Architecture A).

THIS REPO FILE IS NOT THE SECURITY BOUNDARY. The boundary is the *installed* copy
(root-owned, outside the Git checkout, e.g. /usr/local/sbin/ed_pm_authority_write),
plus the OS facts that the assigned-AI user (a) does not own it, (b) cannot write
the authority file/dir, and (c) has NOPASSWD sudo for ONLY this one command.

Design law (why every line below is inline stdlib):
  Whatever runs as root must NOT load a single byte of AI-writable code. So this
  file imports ONLY the standard library, never `tools.*`, never the repo reader,
  never anything reachable via PYTHONPATH / cwd / user-site. It also REFUSES to run
  its privileged CLI unless the interpreter is in isolated mode (`python3 -I`), so a
  hostile PYTHONPATH cannot shadow even a stdlib name (`json`, `pathlib`, ...).

Contract (identical to the in-repo advisory validator in tools/pm_authority.py; a
test diffs the two so they cannot drift, but they are NEVER wired by import):
  - candidate JSON on stdin ONLY; any argv (flag or positional path) -> refuse
  - top-level JSON object; `pm` present and EXACTLY "operator"
  - writer / auditor / vendor fields are IGNORED (never authorization)
  - against an existing valid authority doc: no scope_paths expansion, no remaining[] drop
  - destination is a compiled-in constant; never from argv/env/stdin
  - atomic O_EXCL|O_NOFOLLOW replace; symlink/redirection refused
  - nonzero exit on every refusal; writes nothing on refusal

Installed as: install copies THIS file verbatim to the root-owned path only after
verifying its SHA-256 against an operator-supplied pin (see install_pm_authority_host.sh).
"""
# ruff: noqa: E402  -- the isolated-mode guard intentionally precedes imports-as-usual
import sys

# --- stdlib only; no repo import, no sys.path manipulation, ever ---------------
import json
import os

# Compiled-in canonical destination, resolved for the host OS at import time. The
# value is NEVER taken from argv/stdin; on Windows only the OS-provided ProgramData
# root is consulted. This privileged helper runs only on the provisioned host.
if os.name == "nt":
    CANONICAL_AUTHORITY_PATH = os.path.join(
        os.environ.get("ProgramData") or r"C:\ProgramData",
        "ed-console-authority", "pm_mission.json",
    )
else:
    CANONICAL_AUTHORITY_PATH = "/var/lib/ed-console-authority/pm_mission.json"
REQUIRED_PM = "operator"


def validate_candidate(new_text, current_text=None):
    """Return a list of refusal reasons; empty list means the candidate is valid.

    Pure function (stdlib only). writer/auditor/vendor are never consulted.
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
        return [f"PM_AUTHORITY: pm={new_pm!r} — required exactly {REQUIRED_PM!r}"]

    cur_doc = {}
    if current_text is not None:
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
                "PM_AUTHORITY: expands scope_paths by "
                f"{sorted(new_scope - old_scope)!r} — scope expansion is operator-only"
            ]
        if cur_doc.get("remaining") and not new_doc.get("remaining"):
            return [
                "PM_AUTHORITY: deletes remaining[] — dropping the work queue is operator-only"
            ]
    return []


def _lstat_is_symlink(path):
    try:
        return os.path.islink(path)
    except OSError:
        return True  # unreadable -> treat as unsafe


def write_authority(new_text, *, dest=None):
    """Validate then atomically replace the canonical authority file.

    `dest` exists ONLY so tests can point at a tmp path; production always uses the
    compiled-in constant. Any dest other than the module constant is refused when
    running the real CLI (see main()); the parameter is not reachable from argv.
    """
    target = CANONICAL_AUTHORITY_PATH if dest is None else str(dest)

    # Refuse symlinked parent or target (no redirection).
    parent = os.path.dirname(target) or "."
    if _lstat_is_symlink(parent):
        return ["PM_AUTHORITY: parent is a symlink — refuse"]
    if os.path.lexists(target) and _lstat_is_symlink(target):
        return ["PM_AUTHORITY: target is a symlink — refuse"]

    current_text = None
    if os.path.isfile(target) and not _lstat_is_symlink(target):
        try:
            with open(target, encoding="utf-8") as fh:
                current_text = fh.read()
        except OSError:
            return ["PM_AUTHORITY: current authority unreadable — refuse"]

    errs = validate_candidate(new_text, current_text=current_text)
    if errs:
        return errs

    tmp = os.path.join(parent, f".{os.path.basename(target)}.tmp.{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        if os.path.lexists(tmp):
            return ["PM_AUTHORITY: temp path already exists — refuse"]
        fd = os.open(tmp, flags, 0o644)
        try:
            os.write(fd, new_text.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, target)
    except OSError as exc:
        try:
            if os.path.lexists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        return [f"PM_AUTHORITY: atomic write failed: {exc}"]
    if _lstat_is_symlink(target):
        return ["PM_AUTHORITY: result is a symlink — refuse"]
    return []


def run(stdin_text):
    """Programmatic entry used by tests; returns process-style exit code."""
    errs = write_authority(stdin_text)
    if errs:
        sys.stderr.write("".join(f"{e}\n" for e in errs))
        return 2
    return 0


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)

    # PRIVILEGED-EXECUTION GUARD: the installed helper is invoked by the narrow
    # sudoers rule as `python3 -I ... ed_pm_authority_write`. Refuse to run the
    # privileged path in a non-isolated interpreter, so a hostile PYTHONPATH / cwd
    # / user-site cannot shadow even a stdlib import. Tests call the pure functions
    # (validate_candidate / write_authority / run) directly and are unaffected;
    # the CLI-contract tests invoke this via a real `python3 -I` subprocess.
    if not sys.flags.isolated:
        sys.stderr.write(
            "PM_AUTHORITY: privileged CLI must run under an isolated interpreter "
            "(python3 -I); refusing non-isolated invocation\n"
        )
        return 2

    # stdin ONLY: any flag or positional path is a failure (no output-path arg).
    if args:
        sys.stderr.write(
            "PM_AUTHORITY: helper accepts JSON on stdin only; "
            "no output path or extra arguments permitted\n"
        )
        return 2
    try:
        text = sys.stdin.read()
    except OSError as exc:
        sys.stderr.write(f"PM_AUTHORITY: stdin unreadable: {exc}\n")
        return 2
    return run(text)


if __name__ == "__main__":
    raise SystemExit(main())
