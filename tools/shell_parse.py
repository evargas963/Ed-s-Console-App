"""SHELL PARSE — the ONE owner of "what does this shell command do, and where".

BEDROCK 2026-09-06 (dual-signoff, one owner per responsibility): this parser used to live
inside tools/operator_law_guard.py, and tools/process_lock_guard.py and tools/stop_chain.py
imported it from there — the checkout-protection rails and the Stop authority resolver
depended on the action-ban module to read a command. The code is unchanged; only its home is.
Every rule that needs to segment a command, track `cd` across a chain, find the git
invocations, resolve the repository a command targets, or strip the DATA out of a command
(heredoc bodies, -c payloads, -m messages) imports it from here. No policy lives in this file:
it answers structural questions and refuses nothing.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# ── repository identity (RC-258) ──────────────────────────────────────────────────────────
#: The guard is registered globally, so it sees commands aimed at ANY checkout on this host.
#: Until 2026-08-05 it had no notion of a target at all: `REPO` above is computed and never
#: consulted by a single rule. That is why one repository's proof authorised another's commit
#: and why an IEOS commit was judged by an Ed Console law. Identity is resolved from the
#: command's own execution context — never defaulted to this file's repository.
_WINDOWS = os.name == "nt"
#: Command segmentation. `shell_executed_part` has already removed heredoc bodies, -c payloads
#: and -m messages, so quoted separators inside DATA cannot reach this split.
_SEG_SPLIT = re.compile(r"\s*(?:&&|\|\||[;&|])\s*")
#: One shell argument: double-quoted, single-quoted, or bare. Quoted forms carry spaces, which
#: is the whole point on Windows (`C:/Program Files/...`).
_ARG = r"""(?:"([^"]*)"|'([^']*)'|([^\s;&|]+))"""
_CD_RE = re.compile(r"^(?:cd|pushd|Set-Location|sl|chdir)\s+(?:/d\s+)?" + _ARG, re.I)
_GIT_C_RE = re.compile(r"(?:^|\s)-C\s+" + _ARG)
_GIT_DIR_RE = re.compile(r"--(?:git-dir|work-tree)(?:=|\s+)" + _ARG, re.I)
_TOKEN_RE = re.compile(r"\"[^\"]*\"|'[^']*'|\S+")
_ABS_RE = re.compile(r"^(?:[A-Za-z]:[/\\]|[/\\])")


#: MSYS / Cygwin drive spellings. The Bash tool on this host IS Git Bash, so `cd "/c/Users/..."`
#: is the ORDINARY form, not an exotic one — MEASURED 2026-08-05 by reading the live ledger,
#: where every bash entry resolved to NOTHING because `/c/...` was treated as a rooted Windows
#: path and `C:\c\Users\...` does not exist. A resolver that cannot read the shell it actually
#: runs under resolves nothing, and "unresolved" would have become the normal case.
_MSYS_DRIVE_RE = re.compile(r"^/(?:cygdrive/)?([A-Za-z])(?=/|$)")


def _msys_to_windows(path: str) -> str:
    if not _WINDOWS or not path:
        return path
    m = _MSYS_DRIVE_RE.match(path.replace("\\", "/"))
    if not m:
        return path
    rest = path.replace("\\", "/")[m.end():]
    return f"{m.group(1).upper()}:{rest or '/'}"


def _arg_value(m: re.Match) -> str:
    for g in m.groups():
        if g is not None:
            return g
    return ""


def normalize_repo(path) -> str:
    """Repository identity: absolute, forward slashes, case-folded on Windows.

    Case folding is not cosmetic here — a drive-letter path spelled upper-case and the same
    path spelled lower-case are one repository, and a comparison that says otherwise would
    reject an agent's own proof.
    """
    try:
        p = Path(_msys_to_windows(str(path))).expanduser().resolve()
    except (OSError, ValueError, RuntimeError):
        return ""
    s = str(p).replace("\\", "/").rstrip("/")
    return s.casefold() if _WINDOWS else s


def repo_root_of(path) -> str:
    """Normalized root of the git repository containing `path`, or "" when there is none.

    Deliberately filesystem-only: a PreToolUse hook runs on every command, so shelling out to
    `git rev-parse` here would put a subprocess in front of every keystroke. Walking up for a
    `.git` entry answers the same question and handles a nonexistent path by returning "".
    """
    try:
        p = Path(_msys_to_windows(str(path))).expanduser()
        if not p.exists():
            return ""
        p = p.resolve()
        if p.is_file():
            p = p.parent
        for cand in (p, *p.parents):
            if (cand / ".git").exists():
                return normalize_repo(cand)
    except (OSError, ValueError, RuntimeError):
        return ""
    return ""


def _tokens(seg: str) -> list[str]:
    return _TOKEN_RE.findall(seg)


def is_git_commit(seg: str) -> bool:
    """True when this segment runs `git commit`, whatever the option placement.

    The old detector was the adjacency pattern `git\\s+commit`, and MEASURED 2026-08-05 it
    returned zero violations for `git -C . commit`, `git -C <path> commit` and
    `git --git-dir=... commit` — four typed characters walked any commit past the law. The
    action is "this git invocation commits", so the test is tokens, not adjacency.
    """
    toks = _tokens(seg.strip())
    if not toks:
        return False
    exe = toks[0].strip("\"'")
    if Path(exe).name.lower() not in ("git", "git.exe"):
        return False
    return any(t.strip("\"'") == "commit" for t in toks[1:])


def _join_dir(base: str, path: str) -> str:
    """Resolve `path` against `base`; "" when it is relative and `base` is unknown."""
    path = _msys_to_windows(path)
    if _ABS_RE.match(path):
        return path
    if not base:
        return ""
    return os.path.join(_msys_to_windows(base), path)


def resolve_target_repo(cmd: str, payload_cwd: str = "") -> tuple[str, str]:
    """(normalized repository identity, reason). An empty identity means UNRESOLVED.

    Precedence, highest first: an explicit path on the git invocation (-C / --git-dir /
    --work-tree), then a directory change earlier in the same chained command, then the
    working directory the tool payload supplies. This function NEVER falls back to `REPO`:
    assuming the guard's own checkout is exactly how an IEOS commit came to be judged by an
    Ed Console rule.
    """
    executed = shell_executed_part(cmd or "")
    cur = str(payload_cwd or "")
    for seg in _SEG_SPLIT.split(executed):
        seg = seg.strip()
        if not seg:
            continue
        m = _CD_RE.match(seg)
        if m:
            cur = _join_dir(cur, _arg_value(m))
            continue
        if not is_git_commit(seg):
            continue
        target = ""
        for rx in (_GIT_C_RE, _GIT_DIR_RE):
            mm = rx.search(seg)
            if mm:
                target = _join_dir(cur, _arg_value(mm))
                if not target:
                    return "", "relative path on the git invocation with no known working directory"
                break
        target = target or cur
        if not target:
            return "", "no path on the command and no working directory supplied by the tool payload"
        root = repo_root_of(target)
        if not root:
            return "", f"target path is not inside a git repository: {target}"
        return root, "resolved from the command"
    if cur:
        root = repo_root_of(cur)
        return (root, "resolved from the tool payload working directory") if root else (
            "", f"working directory is not inside a git repository: {cur}")
    return "", "no repository identity in the command and no working directory supplied"


#: Command heads that wrap another command (its args are the real invocation).
_CMD_WRAPPERS = frozenset({"env", "time", "nice", "sudo", "xargs", "nohup", "stdbuf"})


def iter_command_segments(cmd: str, payload_cwd: str = ""):
    """Yield (cwd_in_effect, segment_text) for EACH statement in a chained shell command,
    tracking `cd`/`pushd` so a later segment's paths resolve against the directory actually in
    effect when it runs. Heredoc bodies and -c payloads are already stripped as data. This is the
    single segmenter every per-invocation rule shares (RC-129 one-faucet): so that every git
    invocation AND every file write in a chain is judged on its own, and a harmless first
    statement cannot launder a later one."""
    executed = shell_executed_part(cmd or "")
    cur = str(payload_cwd or "")
    for seg in _SEG_SPLIT.split(executed):
        seg = seg.strip()
        if not seg:
            continue
        m = _CD_RE.match(seg)
        if m:
            cur = _join_dir(cur, _arg_value(m))
            continue
        yield cur, seg


def _segment_head(seg: str) -> tuple[str, list[str]]:
    """(command head, its tokens) for a segment, skipping leading VAR=val assignments and
    command wrappers (env/sudo/time/...) so `sudo git checkout` reads as a git invocation and
    `echo git` does not."""
    toks = _tokens(seg)
    i = 0
    while i < len(toks):
        t = toks[i].strip("\"'")
        name = Path(t).name.lower().removesuffix(".exe")
        if ("=" in t and not t.startswith("-")) or name in _CMD_WRAPPERS:
            i += 1
            continue
        break
    if i >= len(toks):
        return "", []
    return Path(toks[i].strip("\"'")).name.lower(), toks[i:]


def iter_git_invocations(cmd: str, payload_cwd: str = ""):
    """Yield (normalized_target_repo, segment_text) for EVERY git invocation in a chained
    command — not only the first. A harmless leading git (or a `git -C` aimed elsewhere) cannot
    launder a later checkout/switch/commit/reset/merge, because each git segment is resolved and
    yielded independently. Target precedence per segment: an explicit `-C` / `--git-dir` /
    `--work-tree`, else the cwd in effect at that segment. Reuses the SAME path helpers as
    resolve_target_repo (RC-129 one-faucet)."""
    for cur, seg in iter_command_segments(cmd, payload_cwd):
        head, _toks = _segment_head(seg)
        if head not in ("git", "git.exe"):
            continue
        target = ""
        for rx in (_GIT_C_RE, _GIT_DIR_RE):
            mm = rx.search(seg)
            if mm:
                target = _join_dir(cur, _arg_value(mm))
                break
        yield repo_root_of(target or cur), seg


def shell_executed_part(cmd: str) -> str:
    """Only what the SHELL will run. Heredoc bodies and `-c` payloads are DATA.

    The guard blocked its own negative-control suite the first time it ran, because that suite
    passes strings like a destructive-git command as TEST FIXTURES inside a python heredoc. The
    shell never executes them — the interpreter receives them as text. Scanning data as if it
    were commands makes the guard fire on anything that merely DESCRIBES a banned action, which
    is the word-policing failure the operator rejected, reappearing one layer down.
    """
    # Strip heredoc bodies:  <<'TAG' ... TAG   /   <<TAG ... TAG
    cmd = re.sub(r"<<-?\s*(['\"]?)(\w+)\1.*?^\s*\2\s*$", " <<HEREDOC ", cmd,
                 flags=re.S | re.M)
    # Strip a quoted -c payload:  python -c "..."   /   python -c '...'
    cmd = re.sub(r"-c\s+(['\"])(?:\\.|(?!\1).)*\1", " -c PAYLOAD ", cmd, flags=re.S)
    # Strip quoted -m payloads (commit/tag messages): the FIRST live run of the blind-stage
    # rule blocked a commit whose MESSAGE described the ban — message text is data, and a
    # guard that fires on descriptions is the word-policing failure again (same lesson as
    # heredocs, same day it was written).
    cmd = re.sub(r"-m\s+(['\"])(?:\\.|(?!\1).)*\1", " -m MESSAGE ", cmd, flags=re.S)
    return cmd
