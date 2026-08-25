"""OPERATOR LAW GUARD — bans ACTIONS, not words (RC-93).

OPERATOR 2026-07-27: "i don't want you to ban the terms i want you to ban the actions. non
negotiable."

He is right, and the first version of this file was wrong. It matched phrases — assumption words,
completion words — which is word-policing: any agent can rephrase around a list and the underlying
behaviour is untouched. Worse, it fired on its own author for DOCUMENTING the list, which would
have suppressed the lock inventory the operator had just asked for.

WHAT AN ACTION BAN LOOKS LIKE. The laws are about doing things without proof, so the enforcement
is: the ACTION cannot proceed unless a proof-shaped command was ISSUED this turn — the ledger is
written at PreToolUse and observes no exit status, so "ran and passed" is not knowable here; a
failed or interrupted verification still counts. (The smallest true fix would be a PostToolUse
lane stamping exit codes — a new governance surface, the operator's call, not this audit's.)
The guard keeps that per-turn LEDGER of every command executed, cleared at Stop.

  PreToolUse(Bash|PowerShell)
      * records the command in the turn ledger
      * BLOCKS: grep/rg against repo files (2026-05-22 law), destructive git, and any command
        that disables a lock
      * BLOCKS `git commit` when the ledger holds NO verification command this turn — committing
        without having run the gate or the tests is the action, not the claim about it
  PreToolUse(Edit|Write|MultiEdit)
      * BLOCKS writing status CLOSED into governance/root_cause_log.md when the ledger holds no
        verification command this turn. Closing a root cause IS the assertion that it is fixed;
        the assertion is an action and it needs the evidence to exist first.
  Stop
      * BLOCKS ending a turn that CHANGED production code and ran no test/gate at all. Editing
        the money path and stopping without executing anything is the action.
      * clears the ledger for the next turn

Nothing here inspects prose. A turn may say whatever it likes; it may not DO these things without
the proof having run. Architecture A (RC-450): ED_OPERATOR_LAW_GUARD cannot disable this
control; --no-verify has no grant path.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# ── the turn ledger ───────────────────────────────────────────────────────────────────────
def _ledger_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "nosession")[:80]
    return Path(tempfile.gettempdir()) / f"ed_turn_ledger_{safe}.jsonl"


def _record(session_id: str, kind: str, detail: str, repo: str = "") -> None:
    """Append a ledger entry BOUND to the repository the action targeted (RC-258).

    The `repo` field is what makes proof non-transferable. Without it the ledger was a
    session-wide bearer token, MEASURED failing both ways on 2026-08-05: an Ed Console pytest
    authorised an IEOS commit, and a probe run inside IEOS authorised an Ed Console commit.
    An entry written with an unresolved target keeps `repo` empty, and an empty repo never
    satisfies a repository-scoped rule — legacy entries are inert by the same clause.
    """
    try:
        with _ledger_path(session_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": kind, "detail": detail[:600], "repo": repo}) + "\n")
    except OSError:
        pass


def _record_edit_attempt(session_id: str, path: str, repo: str = "") -> None:
    """Record an edit REQUEST together with the file's pre-edit mtime (RC-258).

    The baseline is captured here, before the tool runs, because that is the only moment the
    "unmodified" state is observable. Stop compares against it to separate an edit that landed
    from one a later hook refused.
    """
    try:
        entry = {"kind": "edit_attempt", "detail": (path or "")[:600], "repo": repo,
                 "mtime_before": _mtime_or_none(path)}
        with _ledger_path(session_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _ledger(session_id: str) -> list[dict]:
    p = _ledger_path(session_id)
    if not p.exists():
        return []
    out = []
    try:
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                out.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
    except OSError:
        return []
    return out


def _clear(session_id: str) -> None:
    try:
        _ledger_path(session_id).unlink(missing_ok=True)
    except OSError:
        pass


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


# ── applicability machinery: REMOVED 2026-08-25 (independent-audit round 2) ────────────────
# rc93_applies_to/_load_applicability/_mechanism scoped the RC-93 commit-before-proof rule,
# which was retired 2026-08-24 (SIMPLICITY REHAB — see the commit-clause notes below). The
# machinery had no production callers left; governance/guard_applicability.json marks the
# ED-OPERATOR-LAW-GUARD/RC-93-COMMIT-BEFORE-PROOF entry retired.

# ── what counts as PROOF HAVING RUN ───────────────────────────────────────────────────────
#: A command that produces evidence about this repo's behaviour: the test suite, a gate, a
#: checker, an audit, or a live probe. Reading a file is not proof; executing something is.
_VERIFICATION = re.compile(
    r"\b(?:pytest|check_[a-z_]+\.py|tools/[a-z_]+_audit\.py|tools/[a-z_]+_report\.py|"
    r"code_health_panel\.py|data_faucet_audit|repo_exposure_audit|ruff\s+check|mypy|"
    r"node\s+--check|urllib\.request|127\.0\.0\.1:8000)\b", re.I)

#: FC-13: this module used to carry its own production-surface geometry here. The constants
#: were dead — nothing read them — but a dead copy of a semantic rule is still a second
#: producer waiting to be picked up. The one authority is
#: tools/pretooluse_guard.classify_path, reached through turn_self_audit.is_production_path.

#: The no-grep law (2026-05-22) as an ACTION predicate, replacing a spelling test that
#: flipped on file extensions, downstream pipes and wrappers (audit 2026-08-25:
#: 'grep foo x.py | head' passed, 'git grep -r foo .' passed, bare 'rg foo' passed,
#: while 'grep foo config.yaml' blocked and 'grep foo config.yml' passed). Violation =
#: a searcher (grep/egrep/fgrep/rg, incl. `git grep`) with a positional file/dir
#: operand beyond the pattern, a recursive/--include/--type/--glob form, an xargs
#: feed, `git grep` in any form (it always searches the tree, never stdin), or bare
#: `rg` at pipeline head (its default IS a recursive cwd search). Filtering another
#: command's stdout — later pipeline stage, no file operand — stays legal. A
#: downstream pipe never launders a file search.
_SEARCHERS = frozenset({"grep", "egrep", "fgrep", "rg"})


def _repo_search_violation(cmd: str) -> bool:
    for stmt in re.split(r"&&|\|\||;|\n", cmd):
        for idx, stage in enumerate(stmt.split("|")):
            toks = [t.strip("\"'") for t in _tokens(stage.strip())]
            fed_by_xargs = False
            while toks and Path(toks[0]).name.lower().removesuffix(".exe") in (
                    "time", "env", "nice", "sudo", "xargs"):
                fed_by_xargs |= Path(toks[0]).name.lower().removesuffix(".exe") == "xargs"
                toks = toks[1:]
            if not toks:
                continue
            name = Path(toks[0]).name.lower().removesuffix(".exe")
            args = toks[1:]
            if name == "git":
                if any(a == "grep" for a in args):
                    return True
                continue
            if name not in _SEARCHERS:
                continue
            flags = [a for a in args if a.startswith("-")]
            positionals = [a for a in args if not a.startswith("-")]
            recursive = any(
                a in ("-r", "-R", "--recursive", "-t") or
                a.startswith(("--include", "--type", "--glob")) or
                (len(a) > 1 and a[1] != "-" and ("r" in a[1:] or "R" in a[1:]))
                for a in flags)
            if positionals[1:] or recursive or fed_by_xargs:
                return True
            if name == "rg" and idx == 0:
                return True
    return False
#: Deliberate split with operating_process_lock.reset_guard_violations (both stay firing):
#: THIS regex bans the universal hard forms anywhere on the host; LOCK-2 over there bans the
#: full reset/restore/checkout--/clean/stash verb class on protected/bare targets.
_DESTRUCTIVE_GIT = re.compile(
    r"\bgit\s+(?:reset\s+--hard|checkout\s+--\s|clean\s+-[a-z]*f|push\s+--force(?!-with-lease))", re.I)
#: RC-273 — the trees that are gitignored and therefore UNRECOVERABLE.
#: `.gitignore:31 data/*` means the 27 GB database has no history at all, so the
#: single most valuable artefact in this repository is the one every
#: version-control-shaped rule above was built to ignore.
#:
#: MEASURED 2026-08-06: the agent destroyed data/ed_console.db TWICE in ten
#: minutes. Once with `mv` to exercise a missing-file branch; once with `rm -f`
#: while TESTING the ACL meant to prevent the first. Both were "just a test";
#: both destroyed 27 GB. `_DESTRUCTIVE_GIT` refused `git checkout --` in that
#: same session, so the guard was awake — it simply did not consider `rm` on an
#: untracked file to be destruction.
#:
#: An OS ACL cannot carry this: the account OWNS the file and a Windows owner
#: can always rewrite the DACL. Proven by a canary that deleted cleanly with
#: deny rules in place. A file-level ACL now exists as defence in depth, but the
#: binding lock has to be here, in the agent channel that actually failed.
#:
#: Destructive is defined by the TARGET's recoverability, never by the verb.
#: Path-SEGMENT anchored (audit 2026-08-25): the bare substring matched 'AppData/' in
#: every Windows temp/scratchpad path, misreading scratch redirects as truncation under
#: data/. The lookbehind refuses a word character before the tree name: foo/data/,
#: "data/, >data/ still match; AppData/, mydata/, _data/ do not.
_PROTECTED_TREE = r"(?<![A-Za-z0-9_.-])(?:data|backups|models)[\\/]"
_PROTECTED_DESTRUCTIVE = re.compile(
    r"(?:\brm\b|\bdel\b|\berase\b|\brmdir\b|Remove-Item|\bunlink\b|shutil\.rmtree"
    r"|os\.remove|os\.unlink|\.unlink\(|\btruncate\b)"
    r"[^\n;|&]{0,200}?" + _PROTECTED_TREE
    + r"|(?:\bmv\b|\bmove\b|Move-Item|shutil\.move|os\.rename|os\.replace)\s+"
      r"[^\n;|&]{0,40}?" + _PROTECTED_TREE
    + r"|>\s*[^\n;|&>]{0,80}?" + _PROTECTED_TREE,
    re.I)


def _protected_path_violation(raw: str) -> bool:
    """True when a command would delete, move or truncate an unrecoverable artefact.

    Reads the RAW command text, including heredocs and -c payloads, because
    those are the channels that dodge the Edit/Write hook.

    A COPY INTO a protected tree is a restore and stays legal — restoring the
    database from backups/ is the recovery path and must never be blocked. It
    is removal of what is already there that has no undo.
    """
    if not raw:
        return False
    # A commit does not touch the working tree. This rule fired on its OWN
    # landing commit, because the message DESCRIBES the incident and therefore
    # contains the command text that caused it. A lock that stops you writing
    # down what went wrong is a lock that gets deleted -- and the honest record
    # is the whole point of the row. `git commit` cannot remove a file.
    if re.search(r"\bgit\s+commit\b", raw, re.I):
        return False
    if re.search(r"\b(?:cp|copy|Copy-Item)\b", raw, re.I) and not re.search(
            r"(?:\brm\b|\bdel\b|Remove-Item|\bmv\b|Move-Item)", raw, re.I):
        return False
    return bool(_PROTECTED_DESTRUCTIVE.search(raw))
# RC-186 self-audit finding (2026-08-02): the enumerated list covered only the four *_GUARD
# names, so the mockup lock's ED_UI_MOCKUP_LOCK=off escape was silently agent-usable the day it
# shipped. Generalized: ANY ED_*_GUARD/ED_*_LOCK=off is a lock-disable action — operator-only.
# RC-189 GUN 2 (Cursor audit v1): the generalization kept the single unquoted-POSIX SHAPE while
# this host's agent shell is PowerShell. Widened to quoted values, spaced assignment, $env:,
# Set-Item/New-Item on the env: drive, and [Environment]::SetEnvironmentVariable. The negative
# lookahead keeps ED_*_GUARD_TIMEOUT-style names out; grant vars (ED_UI_MOCKUP_APPROVE=1) and
# non-disable values ('on', '1') never match.
# Cursor v2 residuals sealed (RC-189): `${env:NAME}` braces, `PSVariable.Set`, and a COMPUTED
# value (`("o"+"ff")`) — a lock variable has no legitimate computed assignment, so ANY
# parenthesized/expression value is refused outright rather than pattern-matching its pieces.
_SKIP_HOOKS = re.compile(
    r"--no-verify"
    r"|hooksPath"
    r"|\bgit\s+commit\b[^\n]*?(?:\s-n\b)"
    r"|(?:\$\{?env:)?ED_[A-Z_]*(?:_GUARD|_LOCK)(?![A-Z0-9_])['\"\s\]\}]*=\s*"
    r"(?:['\"]?\s*(?:off|false|0)\b|\()"
    r"|(?:Set-Item|New-Item|SetEnvironmentVariable|PSVariable)[^\n]{0,80}?"
    r"ED_[A-Z_]*(?:_GUARD|_LOCK)(?![A-Z0-9_])[^\n]{0,60}?['\"\s,(](?:off|false|0)\b",
    re.I)
#: RC-189 GUN 1 — the approval registry and the operator grant are OPERATOR CHANNELS. Shell
#: access to either (read, write, heredoc, -c payload — RAW command text, deliberately wider
#: than shell_executed_part, because heredocs and payloads ARE the write channels that dodge
#: the Edit/Write hook) is refused outright: the registry is read with the Read tool and
#: mutated only through Edit/Write, where the RC-189 provenance hook judges it.
#: Cursor v2: the contiguous-token ban lost to string concatenation, so the scan (a) first
#: strips the LEGITIMATE code-path spellings (the lock module and its test file), then
#: (b) matches FRAGMENTS of the registry name and grant var. Deep concatenation of fragments
#: is backstopped by the constructed-write bans below: a write whose target is not a literal
#: safe-data path is refused no matter what it spells.
_APPROVAL_ALLOWED_SPELLINGS = re.compile(
    r"(?:tools[/\\])?(?:test_)?ui_mockup_lock(?:_v1)?(?:\.py)?", re.I)
_APPROVAL_FRAGMENT = re.compile(
    r"ui_mockup|mockup_approv|approvals\.json|ED_UI_MOCKUP", re.I)
#: SIMPLICITY REHAB 2026-08-24 (T2-7): the fragment ban alone blocked READS — measured
#: twice in one session (a json.load of the registry; a git commit whose MESSAGE named
#: the gate). The registry-forge risk is a WRITE risk, so the fragment must co-occur
#: with a write verb before it blocks. Constructed-write bans below still backstop
#: deep-concatenation forgeries regardless of spelling.
_APPROVAL_WRITE_VERB = re.compile(
    r">{1,2}|Set-Content|Out-File|Add-Content|json\.dump|write_text|write_bytes|"
    r"\bopen\s*\([^)]*['\"](?:w|a)", re.I)
#: Setting the grant variable IS a write (grant-minting), whatever the shell spelling.
_APPROVAL_GRANT_SET = re.compile(r"ED_UI_MOCKUP\w*\s*[:=]", re.I)


def _approval_channel_violation(raw: str) -> bool:
    stripped = _APPROVAL_ALLOWED_SPELLINGS.sub("", raw)
    if _APPROVAL_GRANT_SET.search(stripped):
        return True
    return bool(_APPROVAL_FRAGMENT.search(stripped) and _APPROVAL_WRITE_VERB.search(stripped))


def _safe_data_target(target: str) -> bool:
    """A write target is safe only as a string LITERAL with a data extension, and never the
    approval registry or anything under .claude/ (Cursor v2: a literal .json there is the
    registry-forge / grant-mint channel wearing a legal extension). Other governance data
    files stay heredoc-legal — governance-row edits are HOW agents comply (battery contract)."""
    if not _DATA_TARGET_LITERAL.match(target):
        return False
    return not re.search(r"\.claude[/\\]|ui_mockup|approvals\.json", target, re.I)


#: Cursor v2: `python -c "p='gov'+'ernance/...'; open(p,'w')"` — the -c payload is stripped
#: from the executed-part scan as data, but the WRITE it performs is an action. Payload writes
#: obey the same E-37 rule as heredocs: literal safe-data targets only. This also closes the
#: compounding escape `python -c "open('static/chart.html','w')"` — .html is not a data
#: extension, so a production-surface write from a payload is refused.
_C_PAYLOAD = re.compile(r"-c\s+(['\"])((?:\\.|(?!\1).)*)\1", re.S)


_INTERPRETER_HEADS = frozenset({
    "python", "python3", "py", "pwsh", "powershell", "sh", "bash", "zsh",
    "node", "perl", "ruby"})


def _payload_write_violation(raw: str) -> bool:
    # A commit/tag MESSAGE that DESCRIBES a payload write is data, not a write — the
    # same lesson _protected_path_violation already applies for RC-273 incidents.
    raw = re.sub(r"-m\s+(['\"])(?:\\.|(?!\1).)*\1", " -m MESSAGE ", raw, flags=re.S)
    for pm in _C_PAYLOAD.finditer(raw):
        # -c is an interpreter payload only when an INTERPRETER launches it (grep -c
        # is a counter, sqlite3 -c is config; blocking those stopped honest work).
        seg_start = max((raw.rfind(ch, 0, pm.start()) for ch in ";|&\n"), default=-1) + 1
        head_toks = _tokens(raw[seg_start:pm.start()])
        if not head_toks:
            continue
        exe = Path(head_toks[0].strip("\"'")).name.lower().removesuffix(".exe")
        if exe not in _INTERPRETER_HEADS and not exe.startswith("python"):
            continue
        body = pm.group(2)
        for m in _HEREDOC_WRITE_SITE.finditer(body):
            if m.group(3):
                return True
            target = (m.group(1) or "").strip()
            if m.group(2) is not None:
                tm = re.search(r"\(\s*(['\"][^'\"]+['\"])\s*\)\s*$", m.group(2))
                target = tm.group(1) if tm else ""
            if not _safe_data_target(target):
                return True
    return False


#: Cursor v2: PowerShell write cmdlets with a CONSTRUCTED destination (Join-Path, $(),
#: string concat) or a destination in the governance/.claude trees or with a production
#: suffix dodge every token ban by never spelling the name. Source and governance mutations
#: go through Edit/Write, where the hooks judge them.
_PS_WRITE_BAD = re.compile(
    r"(?:Copy-Item|Move-Item|Set-Content|Add-Content|Out-File)\b[^\n;|]{0,160}?"
    r"(?:Join-Path|\$\(|['\"]\s*\+|governance[/\\]|\.claude[/\\]|"
    r"\.(?:py|html|js|css|ts|sql)\b)", re.I)
_GIT_COMMIT = re.compile(r"\bgit\s+commit\b", re.I)
#: 2026-07-28: `git add -A` swept another agent's in-flight files into MY commits twice in one
#: day (a 530KB runtime log; audit scratch). In a two-agent worktree, blind staging asserts
#: authorship over work the committer never saw.
#: v18 widened: `*`, `-- .`, and `-u` are the same blind action wearing other flags.
_BLIND_STAGE = re.compile(
    r"\bgit\s+add\s+(?:--\s+)?(?:-A\b|--all\b|-u\b|--update\b|\*|\.(?:\s|$))")
#: 2026-07-28 (E-15 class, 4th recurrence today): writing SOURCE files through shell-heredoc
#: python scripts keeps mangling escapes (literal \n breaking string literals, backspace bytes
#: in regexes). The Edit/Write tools are the sanctioned path for source; heredoc scripts stay
#: legal for governance-row edits and data tasks. The scan looks at the RAW command because the
#: banned ACTION is the write performed by the interpreter the shell launches.
#: v18 widened; GRADUATED 2026-07-29 (E-37): the stated variable-path escape was demonstrated
#: the SAME DAY it was written down — a heredoc broke a test file through
#: `p='tests/x.py'; io.open(p,'w')`, exactly the named boundary. Per the graduation clause:
#: every heredoc file-write is now inspected; it is legal ONLY when the opened path is a
#: string LITERAL ending in a data extension (.md/.json/.jsonl/.txt/.csv/.log). A variable
#: path cannot be verified from the command text, so it is refused outright.
_HEREDOC_WRITE_SITE = re.compile(
    r"(?:(?:io\.)?open\(\s*([^,)]+?)\s*,\s*['\"][wa]b?['\"]"
    r"|([A-Za-z_][\w.()'\"/\\-]*)\.write_text\("
    r"|\.py(['\"])\s*\)\s*\.open\(\s*(['\"])[wa]\4)", re.S)
_DATA_TARGET_LITERAL = re.compile(r"^['\"][^'\"]+\.(?:md|json|jsonl|txt|csv|log)['\"]$")


def _heredoc_write_violation(raw: str) -> bool:
    """True when a heredoc body performs a file-write whose target is not a verifiable
    safe-data string literal (E-37 graduation; Cursor v2 tightened governance/.claude out
    of the legal target set — see _safe_data_target)."""
    hd = re.search(r"<<-?\s*(['\"]?)(\w+)\1(.*?)^\s*\2\s*$", raw, re.S | re.M)
    if not hd:
        return False
    body = hd.group(3)
    for m in _HEREDOC_WRITE_SITE.finditer(body):
        if m.group(3):                       # Path('x.py').open('w') — source, always banned
            return True
        target = (m.group(1) or "").strip()
        if m.group(2) is not None:           # <expr>.write_text( — target is the expr's path
            pm = re.search(r"\(\s*(['\"][^'\"]+['\"])\s*\)\s*$", m.group(2))
            target = pm.group(1) if pm else ""
        if not _safe_data_target(target):
            return True
    return False
#: v19: `cat > foo.py <<EOF` writes source through the SHELL itself — no interpreter involved,
#: so the heredoc rule never saw it. Any shell redirect INTO a .py file is the same banned
#: action (writing source outside Edit/Write); .py targets only, so log/json redirects stay legal.
_SHELL_REDIRECT_SOURCE = re.compile(r"(?:^|[^&\d])>{1,2}\s*([^\s;|&<>]+\.py)\b")


def _redirect_source_violation(cmd: str) -> bool:
    """SIMPLICITY REHAB 2026-08-24 (T2-8): the bare regex blocked writing a scratch
    analyzer to the session TEMP directory — outside any repository, not repo source,
    not the law's stated subject. The ban now binds only targets that resolve INSIDE a
    git repository (relative targets count: the working directory is a repo checkout);
    an absolute .py target outside every repo is scratch tooling and stays legal."""
    for m in _SHELL_REDIRECT_SOURCE.finditer(cmd):
        target = m.group(1).strip("'\"")
        if not _ABS_RE.match(_msys_to_windows(target)):
            return True                   # relative → lands in the repo checkout
        if repo_root_of(Path(_msys_to_windows(target)).parent):
            return True
    return False


_EMITTERS = frozenset({"echo", "printf", "rem", "write-host", "write-output"})
_VERIF_WRAPPERS = ("time", "env", "nice", "xargs", "sudo")
_PROBE_TOKEN = re.compile(r"\burllib\.request\b|\b127\.0\.0\.1:8000\b", re.I)


def _verification_ran(detail: str) -> bool:
    """A proof-shaped token counts only where it could EXECUTE (audit 2026-08-25):
    scanned against shell_executed_part (so -m messages, -c payloads and heredoc bodies
    are data), in a segment whose head is not an output emitter ('echo pytest all
    green' used to mint proof), and in COMMAND position — the head token pair, or the
    script/module argument of a python interpreter. Probe URLs may ride as arguments
    of a non-emitter command (curl/Invoke-WebRequest). HONEST LIMIT: this proves a
    verification command was ISSUED this turn, never that it completed or passed — the
    ledger is written at PreToolUse and carries no exit status."""
    for seg in _SEG_SPLIT.split(shell_executed_part(detail or "")):
        toks = [t.strip("\"'") for t in _tokens(seg.strip())]
        while toks and Path(toks[0]).name.lower().removesuffix(".exe") in _VERIF_WRAPPERS:
            toks = toks[1:]
        if not toks:
            continue
        head = Path(toks[0]).name.lower().removesuffix(".exe")
        if head in _EMITTERS:
            continue
        if _PROBE_TOKEN.search(seg):
            return True
        cands = [" ".join(toks[:2])]     # 'ruff check', 'node --check', 'pytest -q', 'tools/x_audit.py'
        if head.startswith("python") or head == "py":
            args = toks[1:]
            script = next((a for a in args if not a.startswith("-")), "")
            if script:
                cands.append(script)
            if "-m" in args:
                i = args.index("-m")
                cands.extend(args[i + 1:i + 2])
        if any(_VERIFICATION.search(c) for c in cands):
            return True
    return False


def _has_verification_any(ledger: list[dict]) -> bool:
    """Session-wide proof — the Stop clauses' question, which is about the TURN, not a repo."""
    return any(_verification_ran(e.get("detail", "")) for e in ledger if e.get("kind") == "bash")


def _has_verification(ledger: list[dict], repo: str = "") -> bool:
    """Proof that ran AGAINST `repo` (RC-258).

    An entry whose `repo` is missing or empty can never satisfy this: legacy unscoped rows and
    commands whose target could not be resolved are inert rather than universally valid, which
    is the difference between a bearer token and a bound credential.
    """
    if not repo:
        return False
    for e in ledger:
        if e.get("kind") != "bash":
            continue
        if (e.get("repo") or "") != repo:
            continue
        if _verification_ran(e.get("detail", "")):
            return True
    return False


def _mtime_or_none(path: str):
    try:
        return Path(path).stat().st_mtime_ns
    except (OSError, ValueError, RuntimeError):
        return None


def _edit_took_effect(entry: dict) -> bool:
    """Did this recorded edit ATTEMPT actually reach the disk (RC-258, fifth failure)?

    PreToolUse fires before the tool runs and before every LATER hook has had its say, so an
    edit this guard permits may still be refused downstream. It was: on 2026-08-05 an Edit to
    tools/operator_law_guard.py was recorded as a production change, the operating-process lock
    then blocked it, the file never changed — and the Stop clause demanded a self-adversarial
    audit for work that did not exist. Intent is not outcome.

    The signal is the file's own modification time, captured BEFORE the tool ran and compared
    after. That is exact where git status is not: a file edited and then committed inside the
    same turn is clean against HEAD yet genuinely changed, and dropping its obligation would
    weaken the very clause this repairs.

    Two deliberate biases, both toward keeping the obligation: an entry with no recorded
    baseline (a legacy `edit` row, or a stat that failed) counts as changed, and so does any
    case the comparison cannot decide. An unmeasurable outcome is never treated as "nothing
    happened" — RC-57: unmeasurable is never compliant.
    """
    if "mtime_before" not in entry:
        return True                      # legacy row — behave exactly as before
    before = entry.get("mtime_before")
    after = _mtime_or_none(entry.get("detail", ""))
    if after is None and before is None:
        return True                      # cannot tell either side
    return after != before


def _production_edits(ledger: list[dict], confirm=None) -> list[str]:
    """Production surfaces this turn actually CHANGED — attempts that were refused drop out."""
    try:
        from tools.pretooluse_guard import classify_path
    except ImportError:
        from pretooluse_guard import classify_path  # type: ignore
    confirm = _edit_took_effect if confirm is None else confirm
    out = []
    for e in ledger:
        if e.get("kind") not in ("edit", "edit_attempt"):
            continue
        p = e.get("detail", "").replace("\\", "/")
        # FC-13: the per-entry relativisation that used to sit here was a third producer of
        # the path semantic, and it only worked when the ledger row carried a `repo` value —
        # otherwise it fell through to the absolute path, which is exactly the case that
        # misclassified session scratchpad files as production. The authority now owns both
        # the relativisation and the classification, and fails closed on an unresolvable
        # path. The ledger's own repo scope (RC-258) is passed through rather than reinvented.
        if not classify_path(p, repo=e.get("repo") or None).production:
            continue
        if not confirm(e):
            continue
        out.append(p)
    return out


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


def bash_violations(cmd: str, ledger: list[dict], payload_cwd: str = "") -> list[str]:
    """Every UNIVERSAL protection, plus the repository-SCOPED ones where they are declared.

    Applicability is decided per rule, never by returning early (RC-258). Returning early for a
    non-Ed-Console target would have exempted that repository from destructive-git, blind-stage,
    lock-disable and unsafe-write protections, which are host-wide safety rules that have
    nothing to do with which checkout is in front of them.
    """
    raw = cmd
    cmd = shell_executed_part(cmd)
    out: list[str] = []
    if _BLIND_STAGE.search(cmd):
        out.append("ACTION BLOCKED: blind staging (git add -A/--all/.) swept another agent's "
                   "in-flight files into a commit twice on 2026-07-28. Stage EXPLICIT paths — "
                   "a commit asserts authorship of everything in it.")
    if _heredoc_write_violation(raw):
        out.append("ACTION BLOCKED (E-37 graduation): heredoc file-writes are legal ONLY to a "
                   "string-LITERAL data target (.md/.json/.jsonl/.txt/.csv/.log). Variable "
                   "paths and source files are refused — the variable-path escape broke a test "
                   "file the same day it was written down as a boundary. Use Edit/Write.")
    if _redirect_source_violation(cmd):
        out.append("ACTION BLOCKED: shell redirect into a .py file writes source outside the "
                   "Edit/Write tools (v19: `cat > x.py <<EOF` walked around the heredoc rule). "
                   "Same action, same ban; non-source redirects stay legal.")
    if _repo_search_violation(cmd):
        out.append("ACTION BLOCKED: shell grep/rg pointed at repo FILES. Standing law "
                   "(2026-05-22): read files end-to-end or use structural/AST analysis. Filtering "
                   "a command's own stdout is allowed; searching the codebase is not. "
                   "Piping a search into head/wc does not make it a stdout filter.")
    if _DESTRUCTIVE_GIT.search(cmd):
        out.append("ACTION BLOCKED: destructive git can discard operator work. Hand it to the "
                   "operator.")
    if _protected_path_violation(raw):
        out.append("ACTION BLOCKED (RC-273): this deletes, moves or truncates something under "
                   "data/, backups/ or models/. Those trees are gitignored -- there is NO "
                   "history and NO undo. The agent destroyed the 27GB database twice in ten "
                   "minutes this way, both times while 'just testing'. Test destructive "
                   "behaviour against a COPY in a temp directory, never the real artefact. "
                   "Restores INTO these trees stay legal; removal from them is operator-only.")
    if _SKIP_HOOKS.search(cmd):
        out.append("ACTION BLOCKED: this disables a mechanical lock. Only the operator may.")
    if _approval_channel_violation(raw):
        out.append("ACTION BLOCKED (RC-189): shell access to the mockup-approval registry or "
                   "the operator grant variable. Self-approve through a shell write was "
                   "Cursor's top break. Read the registry with the Read tool; mutate it only "
                   "through Edit/Write (the provenance hook judges those); the grant is set by "
                   "the operator outside agent channels.")
    if _payload_write_violation(raw):
        out.append("ACTION BLOCKED (RC-189 v2): a -c payload performs a file-write whose "
                   "target is not a literal safe-data path (constructed paths and "
                   "governance/.claude/source targets are how self-approve dodged the token "
                   "ban). Use the Edit/Write tools — the hooks judge those.")
    if _PS_WRITE_BAD.search(cmd):
        out.append("ACTION BLOCKED (RC-189 v2): PowerShell write cmdlet with a constructed, "
                   "governance/.claude, or production-suffix destination. Use the Edit/Write "
                   "tools — a destination the command never spells cannot be audited.")
    # RC-258 commit-needs-prior-verification RETIRED (SIMPLICITY REHAB, operator full-go
    # 2026-08-24): a commit cannot run without executing the pre-commit battery
    # (.pre-commit-config.yaml — ruff, market-correctness, institutional-correctness,
    # db-health), so "committing without having run anything" is unreachable, and the
    # unresolved-repo branch turned a resolver failure into a work stoppage. The
    # close-a-row form (edit_violations) and the Stop-time "edited and ran nothing"
    # clause stay.
    return out


def edit_violations(path: str, new_text: str, ledger: list[dict]) -> list[str]:
    p = (path or "").replace("\\", "/")
    if not p.endswith("governance/root_cause_log.md"):
        return []
    if not re.search(r"\|\s*CLOSED\s*\|", new_text or ""):
        return []
    # The suffix test above matches ANY repository's same-named ledger, so the proof required
    # is the proof for the repository that file lives in (RC-258).
    repo = repo_root_of(path)
    if not repo:
        return [f"ACTION BLOCKED (RC-258): cannot resolve which repository owns {p}, so no "
                f"verification can be matched to it. Closing a row is an assertion about a "
                f"specific repository's code."]
    if _has_verification(ledger, repo):
        return []
    return [f"ACTION BLOCKED: closing a root-cause row in {repo} without having RUN a "
            f"verification against that repository this turn. Closing IS the assertion that "
            f"the defect is fixed. Run the test that locks it, or the gate, or a live probe — "
            f"then close."]


# RC-125 probe-every-turn RETIRED (SIMPLICITY REHAB 2026-08-24): the predicate was a
# substring regex (any command mentioning `snapshots`/`schwab`/`sqlite3` satisfied it),
# forcing a token rather than an observation, and it blocked pure governance/read turns.
# The scoped form of the law survives: pm_verify_repo_violations (honesty_guard) blocks
# a verdict about repo/live state that carries no same-turn measurement.


def _supervisor_incomplete(message: str) -> dict:
    """A typed parent-owned result for a child that produced no valid audit result."""
    return {
        "schema_version": 1,
        "contract_id": "CLEAN_FOR_TURN_CONTRACT_V1",
        "authoritative": True,
        "completed": False,
        "verdict": "INCOMPLETE",
        "exit_code": 3,
        "internal_errors": [message],
    }


def _write_turn_audit_receipt(
    session_id: str,
    result: dict,
    *,
    observed_exit_code: int,
    validation_errors: list[str],
) -> str | None:
    """Persist parent-observed evidence atomically outside the repository.

    Receipts are diagnostics, never inputs to Stop authorization.
    """
    safe_session = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:80]
    run_id = re.sub(
        r"[^A-Za-z0-9_.-]", "_", str(result.get("audit_run_id") or "unknown")
    )[:80]
    directory = Path(tempfile.gettempdir()) / "ed_turn_audit_receipts" / safe_session
    target = directory / f"{run_id}.json"
    payload = {
        "observed_exit_code": observed_exit_code,
        "validation_errors": validation_errors,
        "result": result,
        "recorded_at": __import__("time").time(),
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(target)
    except OSError as exc:
        return f"authoritative receipt write failed: {type(exc).__name__}: {exc}"
    return None


def supervise_turn_audit(
    repo: str | Path,
    session_id: str,
    *,
    command: list[str] | None = None,
    timeout: float = 1800,
    required_session_paths: list[str] | tuple[str, ...] | None = None,
) -> tuple[list[str], dict]:
    """Launch, observe, and validate the authoritative audit child for this Stop.

    A repository artifact is never read here.  The only candidate result is the
    stdout of this exact child process, whose actual exit status the parent owns.
    """
    root = Path(repo).resolve()
    if not session_id:
        result = _supervisor_incomplete("missing session identity")
        return ["TURN AUDIT INCOMPLETE: missing session identity"], result
    session_paths = sorted({
        path.replace("\\", "/").removeprefix("./")
        for path in required_session_paths or ()
        if path
    })
    argv = command or [
        sys.executable,
        str(REPO / "tools" / "turn_self_audit.py"),
        "--authoritative",
        "--repo",
        str(root),
        "--session-id",
        session_id,
        *[
            item
            for path in session_paths
            for item in ("--required-session-file", path)
        ],
    ]
    try:
        proc = subprocess.run(
            argv,
            cwd=str(REPO),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        result = _supervisor_incomplete(f"audit child timed out after {timeout}s")
        return [f"TURN AUDIT INCOMPLETE: audit child timed out after {timeout}s"], result
    except (OSError, subprocess.SubprocessError) as exc:
        result = _supervisor_incomplete(
            f"audit child launch failed: {type(exc).__name__}: {exc}"
        )
        return [f"TURN AUDIT INCOMPLETE: {result['internal_errors'][0]}"], result

    raw = (proc.stdout or "").strip()
    if proc.returncode not in (0, 1, 2, 3) and not raw:
        message = (
            f"audit child did not complete successfully (unexpected exit {proc.returncode})"
        )
        return [f"TURN AUDIT INCOMPLETE: {message}"], _supervisor_incomplete(message)
    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        message = (
            f"malformed structured audit result from child exit {proc.returncode}: "
            f"{raw[:200]!r}"
        )
        result = _supervisor_incomplete(message)
        return [f"TURN AUDIT INCOMPLETE: {message}"], result
    if not isinstance(result, dict):
        message = "malformed structured audit result: top level is not an object"
        return [f"TURN AUDIT INCOMPLETE: {message}"], _supervisor_incomplete(message)

    try:
        from tools.turn_self_audit import validate_result
    except ImportError:
        from turn_self_audit import validate_result  # type: ignore
    try:
        validation = validate_result(
            result,
            repo=root,
            session_id=session_id,
            observed_exit_code=proc.returncode,
            required_session_paths=session_paths,
        )
    except Exception as exc:  # fail closed if the validator itself encounters hostile structure
        validation = [
            f"structured result validation crashed: {type(exc).__name__}: {exc}"
        ]
    violations = [f"TURN AUDIT RESULT REJECTED: {item}" for item in validation]
    receipt_error = _write_turn_audit_receipt(
        session_id,
        result,
        observed_exit_code=proc.returncode,
        validation_errors=validation,
    )
    if receipt_error:
        violations.append(f"TURN AUDIT INCOMPLETE: {receipt_error}")
    verdict = str(result.get("verdict") or "")
    if proc.returncode not in (0, 1, 2, 3):
        violations.append(
            f"TURN AUDIT INCOMPLETE: audit child did not complete successfully "
            f"(unexpected exit {proc.returncode})"
        )
    if verdict not in ("CLEAN", "NO_RELEVANT_PRODUCTION_CHANGE"):
        violations.append(f"TURN AUDIT BLOCKED: authoritative verdict is {verdict or 'UNKNOWN'}")
    return violations, result


def stop_violations(ledger: list[dict]) -> list[str]:
    out: list[str] = []
    # Stop clauses stay SESSION-scoped and behaviourally unchanged: they ask whether this TURN
    # verified/audited/probed, which is a property of the turn rather than of a repository.
    edits = _production_edits(ledger)
    if edits and not _has_verification_any(ledger):
        out.append(f"ACTION BLOCKED: this turn changed production code and ran NOTHING. "
                   f"Edited: {', '.join(sorted(set(edits))[:6])}. Execute the affected tests or "
                   f"a live probe before ending the turn.")
    # RC-190 same-turn turn_self_audit obligation RETIRED (SIMPLICITY REHAB 2026-08-24):
    # it enforced ONE obligation twice (ledger clause + a 5.8s-measured Stop-time
    # supervised child), and the same CHECKS roster runs at commit
    # (tools/precommit_institutional.py) with the delta gate as merge authority
    # (check_delta_adds_no_debt --base origin/main in hardening.yml) enforcing strictly
    # more. tools/turn_self_audit.py stays available as a manual/CI tool.
    # RC-125 probe-every-turn RETIRED here (SIMPLICITY REHAB 2026-08-24) — see the note
    # where _LIVE_PROBE lived: a substring regex forced a token, not an observation, and
    # blocked pure governance/read turns. pm_verify_repo_violations keeps the scoped form.
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.stderr.write("BLOCKED: invalid hook payload — unmeasurable is not compliant.\n")
        return 2

    sid = payload.get("session_id") or ""
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    ledger = _ledger(sid)

    # Claude Code supplies the working directory on the payload when it knows it. Absence is
    # handled as UNRESOLVED rather than guessed — see resolve_target_repo.
    payload_cwd = str(payload.get("cwd") or "")

    if tool in ("Bash", "PowerShell"):
        cmd = ti.get("command") or ""
        bad = bash_violations(cmd, ledger, payload_cwd)
        if bad:
            sys.stderr.write("BLOCKED (RC-93) — OPERATOR LAW: ban the ACTION, not the word.\n\n"
                             + "\n".join(f"    {b}" for b in bad) + "\n")
            return 2
        repo, _why = resolve_target_repo(cmd, payload_cwd)
        _record(sid, "bash", cmd, repo)
        return 0

    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = ti.get("file_path") or ""
        body = ti.get("new_string") or ti.get("content") or ""
        bad = edit_violations(path, body, ledger)
        if bad:
            sys.stderr.write("BLOCKED (RC-93) — OPERATOR LAW: ban the ACTION, not the word.\n\n"
                             + "\n".join(f"    {b}" for b in bad) + "\n")
            return 2
        # ATTEMPTED, not executed: later hooks in the chain may still refuse this edit, and one
        # did (RC-258 fifth failure). Capture the pre-edit mtime so Stop can tell whether the
        # write ever landed, then confirm the outcome rather than assuming it.
        _record_edit_attempt(sid, path, repo_root_of(path))
        return 0

    # Stop
    if not sid:
        sys.stderr.write("BLOCKED: Stop payload has no session identity.\n")
        return 2
    if not payload_cwd:
        sys.stderr.write(
            "BLOCKED: Stop payload has no working-directory identity; "
            "the repository/worktree subject cannot be proven.\n"
        )
        return 2
    if payload.get("stop_hook_active") is True:
        # The flag proves only that the host is retrying a blocked Stop. It grants no
        # authorization: the complete Stop policy, including a fresh supervised audit,
        # is evaluated again against the current subject below.
        if not any(entry.get("kind") == "stop_blocked" for entry in ledger):
            # RC-379: the HOST sets this flag after ANY Stop hook in the chain blocks, so a
            # SIBLING guard's block (honesty_guard, RC-209) arrives here as a retry THIS guard
            # never recorded. Reading that as forgery returned before stop_violations ever ran
            # and deadlocked every later Stop for the rest of the session — measured live,
            # 15+ identical blocks naming no unmet obligation while the turn's work was done.
            # Absence of an own entry is now RECORDED and never fatal; the clauses below stay
            # the sole gate, which is exactly what the comment above already promises. The
            # entry is written with an empty repo, so it can never satisfy a repository-scoped
            # rule (RC-258) — it is observability, not authority.
            _record(sid, "sibling_stop_retry",
                    "stop_hook_active with no own stop_blocked entry — a sibling Stop hook "
                    "blocked first; falling through to the full Stop policy")
    bad = stop_violations(ledger)
    payload_repo = repo_root_of(payload_cwd) if payload_cwd else ""
    # RC-190/RC-368 Stop-time supervised audit child RETIRED (SIMPLICITY REHAB, operator
    # full-go 2026-08-24): the child re-ran the CHECKS roster at every Stop with
    # production edits (5.8s measured) on top of the same roster running at commit
    # (precommit_institutional) and the delta gate at merge (hardening.yml), which
    # enforces strictly more. tools/turn_self_audit.py remains a manual/CI tool;
    # supervise_turn_audit stays importable for its contract tests.
    if bad:
        _record(sid, "stop_blocked", "operator_law_guard", payload_repo or "")
        sys.stderr.write("BLOCKED (RC-93) — OPERATOR LAW: ban the ACTION, not the word.\n\n"
                         + "\n".join(f"    {b}" for b in bad)
                         + "\n\nRun it, then end the turn.\n")
        return 2
    _clear(sid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
