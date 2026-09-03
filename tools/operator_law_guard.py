"""OPERATOR LAW GUARD — bans ACTIONS, not words (RC-93).

OPERATOR 2026-07-27: "i don't want you to ban the terms i want you to ban the actions. non
negotiable."

He is right, and the first version of this file was wrong. It matched phrases — assumption words,
completion words — which is word-policing: any agent can rephrase around a list and the underlying
behaviour is untouched. Worse, it fired on its own author for DOCUMENTING the list, which would
have suppressed the lock inventory the operator had just asked for.

WHAT AN ACTION BAN LOOKS LIKE. The laws are about doing things without proof, so the enforcement
is: the ACTION cannot proceed unless a proof-shaped command RAN WITHOUT ERROR this turn
(operator requirement 2026-08-25 — issuance is not proof). The ledger written at PreToolUse
supplies WHICH commands ran and against WHICH repo (RC-258); the transcript on the hook payload
supplies the OUTCOME (each tool_use paired to its tool_result, is_error judged) — no new
governance lane, the payload already carries transcript_path at every event. A failed or
interrupted verification no longer counts. HONEST LIMIT: a non-error result proves the command
completed; whether its OUTPUT supports the close is the operator's read.
The guard keeps that per-turn LEDGER of every command executed, cleared at Stop.

  PreToolUse(Bash|PowerShell)
      * records the command in the turn ledger
      * BLOCKS: grep/rg against repo files (2026-05-22 law), destructive git, and any command
        that disables a lock
  PreToolUse(Edit|Write|MultiEdit)
      * BLOCKS writing status CLOSED into governance/root_cause_log.md when no verification
        command RAN WITHOUT ERROR this turn. Closing a root cause IS the assertion that it is
        fixed; the assertion is an action and it needs the evidence to exist first.
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
#: tools/pretooluse_guard.classify_path, and it is the only one.

#: The no-grep law (2026-05-22) as an ACTION predicate, replacing a spelling test that
#: flipped on file extensions, downstream pipes and wrappers (audit 2026-08-25:
#: 'grep foo x.py | head' passed, 'git grep -r foo .' passed, bare 'rg foo' passed,
#: while 'grep foo config.yaml' blocked and 'grep foo config.yml' passed). Violation =
#: a searcher (grep/egrep/fgrep/rg, incl. `git grep`) with a positional file/dir
#: operand beyond the pattern, a recursive/--include/--type/--glob form, an xargs
#: feed, `git grep` in any form (it always searches the tree, never stdin), or bare
#: `rg` at pipeline head (its default IS a recursive cwd search). Filtering another
#: command's stdout — later pipeline stage, no file operand — stays legal. A
#: downstream pipe never launders a file search. PowerShell's native searcher
#: (Select-String / sls) is in the set — the agent shell on this host IS PowerShell
#: (red-team 2026-08-25). HONEST LIMIT: `cat *.py | grep foo` rides the stdout-filter
#: carve-out while cat does the codebase read — an accepted, unmechanized bypass
#: (detecting it means classifying every upstream stage; operator review covers it).
_SEARCHERS = frozenset({"grep", "egrep", "fgrep", "rg", "select-string", "sls"})


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
#: RC-505: the destructive-git ban moved OUT of this file. It lived here as a second regex
#: beside operating_process_lock.reset_guard_violations, both firing on the same
#: PreToolUse(Bash) event through the same chain, and both files called the split deliberate.
#: MEASURED 2026-09-02 over 25 command forms: 8 blocked twice with two different messages, and
#: `git push -f origin main` blocked NOWHERE — this regex spelled the flag `--force` only,
#: and the other half does not cover push at all. The forms unique to this regex
#: (`checkout -- .`, force-push) are folded into that one owner, which additionally strips
#: message and heredoc payloads (RC-253) so a commit message quoting a wipe is prose, not an
#: action. process_lock_guard is registered on every Bash/PowerShell event this guard sees,
#: so the reach is unchanged.
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


def _successful_commands(transcript_path: str) -> frozenset[str] | None:
    """The commands that RAN WITHOUT ERROR this turn, from the transcript (2026-08-25).

    The ledger is written at PreToolUse and cannot know outcomes; the transcript pairs
    every tool_use with its tool_result and carries is_error (shape verified live:
    181/182 Bash tool_use ids in this session's transcript had a paired result, the
    unpaired one being the in-flight call). ONE producer: `turn_slice` below computes exactly
    this slice and every guard that needs it calls that one function, so they all agree on what
    "ran this turn" means. Returns None when the payload carries no transcript_path at all:
    unmeasurable, which the callers treat as no proof.
    """
    if not transcript_path:
        return None
    _text, executed = turn_slice(transcript_path)
    return frozenset(executed)


# ── transcript readers (RC-504) ───────────────────────────────────────────────────────────
# These moved here when tools/proof_only_guard.py was retired as Stop authority. They are
# STRUCTURAL: they parse a JSONL transcript into text blocks and executed commands and make no
# judgement about what any of it MEANS. The prose oracles that sat beside them — a
# memory-citation word list, a verdict word list, a defect-report word list — were the retired
# part. This module is where they belong: it already owns turn and session identity (the turn
# ledger, the session id, which commands actually ran without error).


def last_assistant_text(transcript_path: str) -> str | None:
    """Concatenated text of the final assistant message in the transcript."""
    p = Path(transcript_path)
    if not p.exists():
        return None
    last: str | None = None
    try:
        with p.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                msg = rec.get("message") or {}
                if rec.get("type") != "assistant" and msg.get("role") != "assistant":
                    continue
                content = msg.get("content")
                if isinstance(content, str):
                    last = content
                elif isinstance(content, list):
                    parts = [c.get("text", "") for c in content
                             if isinstance(c, dict) and c.get("type") == "text"]
                    if any(parts):
                        last = "\n".join(parts)
    except OSError:
        return None
    return last


def last_user_text(transcript_path: str) -> str | None:
    """Concatenated text of the final USER message (the turn's trigger)."""
    p = Path(transcript_path)
    if not p.exists():
        return None
    last: str | None = None
    try:
        with p.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                msg = rec.get("message") or {}
                if rec.get("type") != "user" and msg.get("role") != "user":
                    continue
                content = msg.get("content")
                if isinstance(content, str):
                    last = content
                elif isinstance(content, list):
                    parts = [c.get("text", "") for c in content
                             if isinstance(c, dict) and c.get("type") == "text"]
                    if any(parts):
                        last = "\n".join(parts)
    except OSError:
        return None
    return last


def turn_slice(transcript_path: str) -> tuple[str | None, list[str]]:
    """(assistant text of THIS turn, shell commands that RAN WITHOUT ERROR this turn).

    The turn boundary is the LAST user record carrying real text (tool_result records are
    user-role but carry no text block). Assistant text is every text block after that boundary
    concatenated. Commands are the input.command of every Bash/PowerShell tool_use block after
    the boundary; command-carrying tools only — a Read file_path is not an executed command.

    RESULT, NOT ISSUANCE (operator requirement, 2026-08-25): a command counts only when its
    tool_result exists in the same transcript and does not carry is_error=true — issuing
    `pytest` that then FAILED is not proof. A command with no result record at all (interrupted
    mid-call) does not count either. HONEST LIMIT: is_error=false proves the tool call completed
    without a harness-level error; it cannot judge whether the OUTPUT supports a claim.
    """
    p = Path(transcript_path)
    if not p.exists():
        return None, []
    records: list[tuple[str, list[str], list[tuple[str, str]]]] = []
    result_error_by_id: dict[str, bool] = {}
    try:
        with p.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                msg = rec.get("message") or {}
                role = (rec.get("type") if rec.get("type") in ("user", "assistant")
                        else msg.get("role"))
                if role not in ("user", "assistant"):
                    continue
                content = msg.get("content")
                texts: list[str] = []
                cmds: list[tuple[str, str]] = []
                if isinstance(content, str):
                    if content.strip():
                        texts.append(content)
                elif isinstance(content, list):
                    for c in content:
                        if not isinstance(c, dict):
                            continue
                        if c.get("type") == "text" and c.get("text", "").strip():
                            texts.append(c["text"])
                        elif (c.get("type") == "tool_use"
                              and c.get("name") in ("Bash", "PowerShell", "Shell")):
                            cmd = (c.get("input") or {}).get("command")
                            if isinstance(cmd, str) and cmd.strip():
                                cmds.append((str(c.get("id") or ""), cmd))
                        elif c.get("type") == "tool_result":
                            tid = str(c.get("tool_use_id") or "")
                            if tid:
                                result_error_by_id[tid] = bool(c.get("is_error"))
                records.append((role, texts, cmds))
    except OSError:
        return None, []
    boundary = -1
    for i, (role, texts, _c) in enumerate(records):
        if role == "user" and texts:
            boundary = i
    texts_out: list[str] = []
    cmds_out: list[str] = []
    for role, texts, cmds in records[boundary + 1:]:
        if role == "assistant":
            texts_out.extend(texts)
            for tid, cmd in cmds:
                # RESULT REQUIRED: no result record, or is_error=true -> not proof.
                if tid and result_error_by_id.get(tid) is False:
                    cmds_out.append(cmd)
    return ("\n".join(texts_out) if texts_out else None), cmds_out


def _result_ok(detail: str, ok_cmds: frozenset[str] | None) -> bool:
    """True only when THIS ledger command's tool_result exists and is not an error."""
    return ok_cmds is not None and detail in ok_cmds


def _verification_ran(detail: str) -> bool:
    """A proof-shaped token counts only where it could EXECUTE (audit 2026-08-25):
    scanned against shell_executed_part (so -m messages, -c payloads and heredoc bodies
    are data), in a segment whose head is not an output emitter ('echo pytest all
    green' used to mint proof), and in COMMAND position — the head token pair, or the
    script/module argument of a python interpreter. Probe URLs may ride as arguments
    of a non-emitter command (curl/Invoke-WebRequest). SHAPE ONLY: this classifies the
    command; whether it ran without error is judged separately (_result_ok against the
    transcript), so issuing `pytest` that then failed no longer mints proof."""
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
            # A `-m <module>` is executed only when no `-c` precedes it: a -c payload
            # consumes the interpreter and a following -m is inert argv (red-team
            # 2026-08-25: `python -c "pass" -m pytest` never runs pytest).
            if "-m" in args and not ("-c" in args and args.index("-c") < args.index("-m")):
                i = args.index("-m")
                cands.extend(args[i + 1:i + 2])
        if any(_VERIFICATION.search(c) for c in cands):
            return True
    return False


def _has_verification_any(ledger: list[dict], ok_cmds: frozenset[str] | None) -> bool:
    """Session-wide proof — the Stop clauses' question, which is about the TURN, not a repo.

    RESULT, NOT ISSUANCE (operator requirement, 2026-08-25): the issuance entry counts only
    when the same command's tool_result in the transcript is not an error."""
    return any(_verification_ran(e.get("detail", "")) and _result_ok(e.get("detail", ""), ok_cmds)
               for e in ledger if e.get("kind") == "bash")


def _has_verification(ledger: list[dict], repo: str = "",
                      ok_cmds: frozenset[str] | None = None) -> bool:
    """Proof that ran AGAINST `repo` (RC-258) and ran WITHOUT ERROR (2026-08-25).

    An entry whose `repo` is missing or empty can never satisfy this: legacy unscoped rows and
    commands whose target could not be resolved are inert rather than universally valid, which
    is the difference between a bearer token and a bound credential. An entry whose command has
    no non-error tool_result in the transcript is equally inert: a verification that FAILED is
    an argument against closing, not for it.
    """
    if not repo:
        return False
    for e in ledger:
        if e.get("kind") != "bash":
            continue
        if (e.get("repo") or "") != repo:
            continue
        if _verification_ran(e.get("detail", "")) and _result_ok(e.get("detail", ""), ok_cmds):
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
    # RC-505: destructive git is answered by operating_process_lock.reset_guard_violations,
    # reached through process_lock_guard on this same PreToolUse registration. One law, one
    # owner, one message — see the note where this regex used to live.
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


def edit_violations(path: str, new_text: str, ledger: list[dict],
                    ok_cmds: frozenset[str] | None = None) -> list[str]:
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
    if _has_verification(ledger, repo, ok_cmds):
        return []
    return [f"ACTION BLOCKED: closing a root-cause row in {repo} without a verification that "
            f"RAN WITHOUT ERROR against that repository this turn. Closing IS the assertion "
            f"that the defect is fixed; a command that was merely issued, or that failed, is "
            f"not that proof. Run the test that locks it, or the gate, or a live probe — "
            f"then close."]


# RC-125 probe-every-turn RETIRED (SIMPLICITY REHAB 2026-08-24): the predicate was a
# substring regex (any command mentioning `snapshots`/`schwab`/`sqlite3` satisfied it),
# forcing a token rather than an observation, and it blocked pure governance/read turns.
# The scoped form of the law survives: pm_verify_repo_violations (honesty_guard) blocks
# a verdict about repo/live state that carries no same-turn measurement.
# RC-505: the Stop-time supervised turn audit is GONE, not dormant. RC-190 retired the
# obligation on 2026-08-24 and left the supervisor (supervise_turn_audit,
# _write_turn_audit_receipt, _supervisor_incomplete) plus tools/turn_self_audit.py behind
# as a 'manual/CI tool'. MEASURED 2026-09-02: no workflow, pre-commit hook, Makefile
# target or npm script ran it, and the supervisor had no caller -- dead code inside a live
# guard, which reads as coverage that is not there. Everything it audited binds at a real
# seam: ruff (pre-commit + hardening), pytest (required pytest-full), index/worktree
# parity (operating_process_lock, pre-commit `operating-process`), and the enforced roster
# (precommit_institutional + check_delta_adds_no_debt).


def stop_violations(ledger: list[dict], ok_cmds: frozenset[str] | None = None) -> list[str]:
    out: list[str] = []
    # Stop clauses stay SESSION-scoped and behaviourally unchanged: they ask whether this TURN
    # verified/audited/probed, which is a property of the turn rather than of a repository.
    edits = _production_edits(ledger)
    if edits and not _has_verification_any(ledger, ok_cmds):
        out.append(f"ACTION BLOCKED: this turn changed production code without a verification "
                   f"that RAN WITHOUT ERROR. "
                   f"Edited: {', '.join(sorted(set(edits))[:6])}. Execute the affected tests or "
                   f"a live probe — and it must complete — before ending the turn.")
    # RC-190 same-turn supervised-audit obligation RETIRED (SIMPLICITY REHAB 2026-08-24):
    # it enforced ONE obligation twice (ledger clause + a 5.8s-measured Stop-time
    # supervised child), and the same CHECKS roster runs at commit
    # (tools/precommit_institutional.py) with the delta gate as merge authority
    # (check_delta_adds_no_debt --base origin/main in hardening.yml) enforcing strictly
    # more. RC-505 deleted the leftover tool and supervisor; nothing ran them.
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
        bad = edit_violations(path, body, ledger,
                              _successful_commands(str(payload.get("transcript_path") or "")))
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
    bad = stop_violations(ledger,
                          _successful_commands(str(payload.get("transcript_path") or "")))
    payload_repo = repo_root_of(payload_cwd) if payload_cwd else ""
    # RC-190/RC-368 Stop-time supervised audit child RETIRED (SIMPLICITY REHAB, operator
    # full-go 2026-08-24): the child re-ran the CHECKS roster at every Stop with
    # production edits (5.8s measured) on top of the same roster running at commit
    # (precommit_institutional) and the delta gate at merge (hardening.yml), which
    # enforces strictly more. RC-505 then deleted the child and its supervisor: a
    # retired control kept importable for its own tests is tests without a control.
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
