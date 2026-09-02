"""MISSION LATCH — the one computation of "is there active mission state, and is it finished".

WHY THIS EXISTS. AGENTS.md carries the surviving law: *"Find something broken → fix it.
Discovery creates the obligation to remediate through the full blast radius in the active
session. A material defect is never disposed as queued / logged / TODO / follow-up /
pre-existing / out-of-scope."* That law was prose at the decisive seam. The RC-66 PreToolUse
lane that once demanded a root-cause row before a production edit was retired under
RC-470/471, and `stop_guard` RC-72 fires only when the agent has ALREADY opened a same-day row
AND written one of a small marker vocabulary into its fix cell.

MEASURED on 334c5daf against the real hook rosters, 13 of 26 required behaviours held: a
production Edit/Write with no row anywhere passed, so did `sed -i` / `cp` / `mv` / `tee` /
`truncate` / `git apply` / `--write` on production, and so did a Stop whose only record of the
defect was prose. Reproduce: `pytest tests/test_find_fix_execution_latch_v1.py -q`.

CONTRACT. Four questions, each answered once here and consumed by the guards that already
exist — this module adds no hook, no registry and no tracked state file:
  * `has_active_mission()`     — is a row opened today? (PreToolUse gate)
  * `mission_blockers()`       — is that row finished or objectively blocked? (Stop gate)
  * `dirty_production_files()` — what actually changed? (Stop gate, outcome side)
  * `operator_halt_instruction()` — did the OPERATOR say stop? (the only escape)

It re-derives nothing: paths come from `pretooluse_guard.classify_path`, shell write
destinations from `process_lock_guard._shell_write_targets`, blocker vocabulary from the
`BLOCKED_ON_*` tokens `operating_process_lock.rc_redate_violations` already enforces.

Fails OPEN on an unreadable ledger — no rows means nothing to say. The retired find-it-fix-it
framework treated a missing ledger as an offender and so blocked every Stop and commit
repo-wide; a control that cannot be satisfied is a hang, not a control.
"""
from __future__ import annotations

import datetime
import json
import re
import subprocess
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent.parent
#: Module global, deliberately not a default argument, so tests and probes can redirect the
#: ledger without monkeypatching every call site.
RC_LOG = REPO / "governance" / "root_cause_log.md"


class MissionRow(NamedTuple):
    """One parsed root-cause row. Cell order is the format the log header pins:
    `| id | status | opened | due | defect | why-chain -> root | fix + verification |`"""

    rc_id: str
    status: str
    opened: str
    due: str
    defect: str
    why: str
    fix: str


# ── vocabulary ────────────────────────────────────────────────────────────────────────────
#: What the agent writes to mean "not done yet". Inherited VERBATIM from stop_guard RC-72, so
#: that guard's founding contract is preserved exactly while its parsing moves here.
UNFINISHED_MARKERS = ("IN PROGRESS", "VERIFICATION PENDING", "PENDING VERIFICATION",
                      "NOT FIXED", "PARTIALLY FIXED", "NOT DONE")

#: The blocker tokens the repo ALREADY enforces at pre-commit via
#: `operating_process_lock.rc_redate_violations`. Reused rather than reinvented: one
#: vocabulary for "objectively blocked", not two.
EXTERNAL_BLOCKERS = ("BLOCKED_ON_OPERATOR", "BLOCKED_ON_LIVE_SESSION",
                     "BLOCKED_ON_DATA_ACCRUAL", "BLOCKED_ON_EXTERNAL")

#: Operator halt authority (AGENTS.md: "Operator halt words: STOP / PAUSE / HANG IT UP /
#: DO NOT CONTINUE"). ANCHORED to the START of the operator's message, not searched inside it.
#:
#: MEASURED, on the unanchored version this replaces: "keep going, do not stop for anything"
#: returned STOP, "The pause between sweeps is 17 minutes" returned PAUSE, and "please review
#: the Stop hook wiring" returned STOP. The escape fired on instructions that said the
#: OPPOSITE of halting. A halt is an instruction the message OPENS with, not a word it happens
#: to contain.
OPERATOR_HALT = re.compile(
    r"(?i)^[\s\"'*_`>(\[-]*(stop|pause|hang it up|do not continue)\b")


def _today() -> str:
    return datetime.date.today().isoformat()


# ── the ledger ────────────────────────────────────────────────────────────────────────────
def ledger_path(repo: str | Path | None = None) -> Path:
    """The ledger of the repository being ACTED ON, not the one this file happens to live in.

    A linked worktree has its own checkout of the ledger, and the guards run from whichever
    checkout the session started in. MEASURED: with the session rooted at the production
    checkout while the work happened in `EdWebConsole-dev`, `| RC-498 ` resolved 0 times in
    the tree the Stop guard read and 1 time in the tree that held the work — so an honest
    same-day row looked exactly like a broken promise. Callers pass the repo that owns the
    file being edited or the command being run; `RC_LOG` remains the fallback and the test seam.
    """
    if repo is None:
        return RC_LOG
    try:
        return Path(repo) / "governance" / "root_cause_log.md"
    except (OSError, ValueError):
        return RC_LOG


def all_rows(repo: str | Path | None = None) -> list[MissionRow]:
    """Every parseable row in the ledger. The ONLY parser of this file's row grammar."""
    try:
        text = ledger_path(repo).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []             # unreadable ledger -> no rows; see the module docstring on why
    out: list[MissionRow] = []
    for line in text.splitlines():
        if not line.startswith("| RC-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        out.append(MissionRow(*cells[:7]))
    return out


def same_day_rows(today: str | None = None, repo: str | Path | None = None) -> list[MissionRow]:
    """Rows OPENED today, whatever their status. Calendar scope only — NOT authority."""
    today = today or _today()
    return [r for r in all_rows(repo) if r.opened == today]


def _rows_this_worktree_introduced(repo: str | Path | None = None) -> set[str]:
    """RC ids whose row exists HERE but not on the trunk — this worktree's own work.

    A git fact, not a new field and not a registry: `git diff origin/main -- <ledger>` compares
    the trunk against this working tree, so a row shows up when this branch added it, whether
    it is committed or still uncommitted. Once the PR merges, the row is on the trunk and stops
    appearing — which is exactly right, because a landed mission must not keep authorizing new
    work.

    Falls back to `HEAD` when the trunk cannot be resolved (no remote, fresh clone), so an
    offline worktree can still open a row and proceed.

    Returns None when the question CANNOT BE MEASURED at all — no git, or a directory that is
    not a checkout. None is not an empty set, and the distinction matters because the two
    callers must fail closed in OPPOSITE directions: authorization refuses (no proof of a
    mission), while the turn-end obligation falls back to every same-day row (an unmeasurable
    git state must not silence RC-72). Collapsing both to `set()` did exactly that — MEASURED
    in the hermetic mini-checkout, where a planted unfinished row stopped blocking the Stop.
    """
    log = ledger_path(repo)
    root = str(repo) if repo is not None else str(REPO)
    for base in ("origin/main", "main", "HEAD"):
        try:
            r = subprocess.run(["git", "diff", base, "--", str(log)], cwd=root,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=20)
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            continue
        return {m.group(1) for m in
                (re.match(r"\+\| (RC-\d+) ", ln) for ln in r.stdout.splitlines()) if m}
    return None


def active_mission_rows(today: str | None = None,
                        repo: str | Path | None = None) -> list[MissionRow]:
    """The mission(s) THIS worktree is executing right now.

    Three conditions, and the last two are the RC-500 repair:

      1. opened today          — session scope, unchanged.
      2. status OPEN           — a CLOSED row is a FINISHED mission. It records what was done;
                                 it does not authorize what comes next.
      3. introduced HERE       — the row must be this worktree's own, not one that arrived on
                                 the trunk. Authority binds to the mission being executed.
      4. NOT externally blocked — RC-502. A row carrying a `BLOCKED_ON_*` disposition says the
                                 work CANNOT PROCEED. A mission that cannot proceed cannot
                                 authorize proceeding; the two claims are contradictory, and
                                 the row is asserting the first while being used for the second.
                                 Reuses `external_blocker` — the same predicate that lets such
                                 a row end the turn legally, now also denying it authority.

    MEASURED before this repair: `has_active_mission` accepted any row opened today, so closing
    RC-498 still authorized fresh production edits, and a row opened by unrelated work
    authorized this worktree's. "Some row exists today" is a calendar fact; it was standing in
    for authority it never established. MEASURED again on the blocked case: RC-499, carrying
    BLOCKED_ON_OPERATOR, authorized every production edit of the session that opened it.

    A blocked row regains authority the only honest way: by ceasing to claim it is blocked —
    the disposition is removed and the row becomes ordinary active work again. Nothing else
    changes, and no new state records the transition.
    """
    introduced = _rows_this_worktree_introduced(repo)
    if introduced is None:
        return []                      # unmeasurable -> no proof of a mission -> no authority
    return [r for r in same_day_rows(today, repo)
            if r.status == "OPEN" and r.rc_id in introduced
            and external_blocker(r) is None]


def has_active_mission(today: str | None = None, repo: str | Path | None = None) -> bool:
    """Is there exactly ONE unambiguous mission authorizing work here? Fails closed.

    EXACTLY one, not at least one. With two OPEN same-day rows in the same checkout there is
    no fact that says which of them a given edit belongs to, so either would authorize work it
    has nothing to do with — worktree authority wearing a mission's name. MEASURED before this
    clause: two unrelated rows both counted and `has_active_mission` returned True, so the
    second licensed the first's edits and vice versa.

    Zero and many therefore fail the same way, and both are honestly repairable: open the row,
    or close the mission you are not executing. AGENTS.md already says ONE row for the
    session's mission; this is that sentence made arithmetic.
    """
    return len(active_mission_rows(today, repo)) == 1


# ── is the mission finished ───────────────────────────────────────────────────────────────
def external_blocker(row: MissionRow) -> str | None:
    """The objective blocker recorded on a row, or None.

    Two STRUCTURAL requirements, deliberately not a prose test: one of the repo's existing
    `BLOCKED_ON_*` tokens, and a `due` cell that parses as a date still in the future. The due
    date is the resume condition, and it is a field the repo already polices — moving it needs
    `operating_process_lock.rc_redate_violations` to see a `RE-DATED old->new: BLOCKED_ON_*`
    justification at commit.

    THIS REPLACED A PROSE TEST THAT DID NOT WORK. The earlier version searched the fix cell for
    resume words, one alternative being any ISO date. MEASURED against it:

        "BLOCKED_ON_EXTERNAL - ran out of runway, 2026-01-01"          -> EXEMPTED
        "BLOCKED_ON_OPERATOR - I would prefer another audit. 2026-01-01" -> EXEMPTED

    Both are precisely the dispositions the law forbids, and both walked through because they
    contained a date. Reading the `due` field instead makes a stale date fail on arithmetic
    rather than on vocabulary.

    HONEST LIMIT, stated rather than implied: this proves the row CARRIES a recognised blocker
    and a live due date. It cannot prove the blocker is truthful — no machine can read whether
    the market is really closed. Judging that stays with the operator, and the row is written
    in plain sight so it can be judged.
    """
    token = next((t for t in EXTERNAL_BLOCKERS if t in row.fix.upper()), None)
    if token is None:
        return None
    try:
        due = datetime.date.fromisoformat(row.due.strip())
    except (ValueError, AttributeError):
        return None                       # no parseable resume date -> not an objective blocker
    if due < datetime.date.today():
        return None                       # the date it promised to resume by has passed
    return token


def row_blockers(row: MissionRow) -> list[str]:
    """Why this row forbids ending the turn. Empty list = this row does not block Stop."""
    if row.status != "OPEN":
        return []                          # CLOSED / SUPERSEDED rows are finished
    if external_blocker(row):
        return []                          # objectively blocked: OPEN is the legal form
    hit = next((m for m in UNFINISHED_MARKERS if m in row.fix.upper()), None)
    # The marker adds nothing to the DECISION — measured decision-neutral across 30
    # cases — but naming what the agent itself wrote makes the block message actionable.
    return [f"fix cell still says {hit!r}" if hit else
            "row is OPEN with neither a finished fix (set it CLOSED with measured evidence) "
            "nor a recorded external blocker"]


def mission_blockers(today: str | None = None,
                     repo: str | Path | None = None) -> list[tuple[str, str]]:
    """(rc_id, reason) for every same-day row THIS worktree opened that forbids ending the turn.

    Scoped to this worktree's own rows for the same reason authorization is: a row that arrived
    on the trunk is somebody else's landed work, and holding this turn hostage to it would make
    the guard unsatisfiable by anything the agent can do.
    """
    introduced = _rows_this_worktree_introduced(repo)
    out: list[tuple[str, str]] = []
    for row in same_day_rows(today, repo):
        # None = the git question could not be measured; RC-72's duty then applies to every
        # same-day row rather than none, because an unmeasurable state must not grant passage.
        if introduced is not None and row.rc_id not in introduced:
            continue
        for reason in row_blockers(row):
            out.append((row.rc_id, reason))
    return out


# ── operator authority ────────────────────────────────────────────────────────────────────
def _user_texts(transcript_path: str) -> list[str]:
    """Text of every USER-authored message in the transcript, oldest first."""
    p = Path(transcript_path or "")
    if not p.exists():
        return []
    out: list[str] = []
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
                    texts = [content]
                elif isinstance(content, list):
                    texts = [b.get("text", "") for b in content
                             if isinstance(b, dict) and b.get("type") == "text"]
                else:
                    texts = []
                joined = "\n".join(t for t in texts if t)
                if joined.strip():          # tool_result records are user-role but carry no text
                    out.append(joined)
    except OSError:
        return []
    return out


def operator_halt_instruction(transcript_path: str) -> str | None:
    """The operator's halt word, read from the LAST USER-AUTHORED message, or None.

    Deliberately a USER record. The agent authors assistant records, so if this read the
    assistant side the subject could grant itself the escape by writing "STOP" in its own
    summary. Reading the user side is what makes this authority the operator's.
    """
    texts = _user_texts(transcript_path)
    if not texts:
        return None
    m = OPERATOR_HALT.search(texts[-1])
    return m.group(1).upper() if m else None


# ── the outcome question ──────────────────────────────────────────────────────────────────
def dirty_production_files(repo: Path | None = None) -> list[str]:
    """Production files currently modified in the working tree — the OUTCOME question.

    This is what makes the shell clause honest. The command-line enumerator
    (`process_lock_guard._shell_write_targets`) recognises NAMED mutation forms and can be
    evaded by choosing one it does not name — `python do_everything.py` can write any file and
    no static reading of that command line can say so. This asks what actually CHANGED instead,
    which no choice of command form evades. Prevention catches the known shapes at the moment
    of the call; this catches the rest before the turn can end.

    Abstains (returns []) when git cannot be run: a clause that cannot measure must not block
    on a guess, and the other clauses still bind.
    """
    root = (repo or REPO).resolve()
    try:
        r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                           cwd=str(root), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0 or not r.stdout.strip():
        return []
    # Imported only once there is something to classify. `tests/test_hook_chains_v1.py` runs
    # stop_guard inside a hermetic mini-checkout holding just the executor, this module and the
    # guard; importing the path authority unconditionally would demand the whole guard tree
    # there for a question that has no answer in a non-git directory anyway.
    from tools.pretooluse_guard import classify_path

    out: list[str] = []
    for line in r.stdout.splitlines():
        rel = line[3:].strip().strip('"')
        if " -> " in rel:                  # rename: the DESTINATION is what was written
            rel = rel.split(" -> ", 1)[1]
        if not rel:
            continue
        facts = classify_path(str(root / rel), repo=root)
        if facts.governed and facts.production and facts.rel not in out:
            out.append(facts.rel)
    return out
