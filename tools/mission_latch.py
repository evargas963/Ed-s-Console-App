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

CONTRACT (bedrock 2026-09-06). Two questions, each answered once here and consumed by the
Stop guard — this module adds no hook, no registry and no tracked state file:
  * `mission_blockers()`       — is a row THIS worktree introduced OPEN and neither finished
                                 nor BLOCKED with a live date? (Stop gate)
  * `operator_halt_instruction()` — did the OPERATOR say stop? (the only escape)
The mutation-side half (`has_active_mission`, `dirty_production_files`) is REMOVED: "a row
before a production mutation" was a proxy for "a defect found on the way gets recorded", a
property no mutation seam can see; it made every feature edit a defect mission, expired at
midnight (RC-521) and deadlocked on legitimate child rows. Work identity is the branch and
PR; defects get rows by doctrine (AGENTS.md); CLOSE requires cited evidence (the gate).

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

#: RC-503: "is this mission objectively blocked" is answered by the row's STATUS CELL — a
#: machine-parsed column of the schema — and by its DUE CELL. It is not answered by searching
#: the free-text fix cell for `BLOCKED_ON_*`, which is what this used to do.
#:
#: That earlier form was prose deciding authority: the substring could appear in a sentence
#: DESCRIBING a blocker, quoting one, or explaining why something was NOT blocked, and the
#: predicate could not tell those apart from a claim. The whole point of the surrounding work
#: is that a control must own an OUTCOME, not a VOCABULARY; the authority path was the last
#: place still violating it.
#:
#: The fix cell still SAYS which blocker and what clears it — that is how a human reviews the
#: claim, and `operating_process_lock.rc_redate_violations` separately requires the
#: `RE-DATED old->new: BLOCKED_ON_*` justification when a due date MOVES. Neither of those is
#: authority. This is.
BLOCKED_STATUS = "BLOCKED"

#: RC-520: a CLOSED row whose full text has left the live ledger. The compact form keeps the
#: seven cells (so every parser here and in the gate still reads it), the id (so citations
#: resolve), the dates, a headline, the audit tags the row processed, and ONE git pointer to
#: the blob that carries the complete five-why chain and evidence. Nothing about it is
#: authority: it opens nothing, blocks nothing and is skipped by the substance validators.
ARCHIVED_STATUS = "ARCHIVED"
_HEADLINE_CHARS = 160
_FIX_CHARS = 140
_AUDIT_TAG_RE = re.compile(r"\bv\d+\b")
_AUDIT_LINE_RE = re.compile(r"\baudit\b|\bprocessed\b", re.I)


def archive_closed_rows(text: str, before: str, pointer_sha: str, keep_ids=()) -> tuple[str, list[str]]:
    """Compact every CLOSED row opened before `before` (ISO date) to its ARCHIVED line.

    The ONE writer of the ARCHIVED form (the gate declares the status, this owns the grammar).
    `pointer_sha` must be a commit whose ledger carries the full rows — the caller passes the
    HEAD the compaction is made against, so `git show <sha>:governance/root_cause_log.md`
    reproduces every archived row verbatim. Rows in `keep_ids` and rows of any other status
    are returned unchanged. Returns (new text, archived ids) and never touches non-row lines.
    """
    out_lines: list[str] = []
    archived: list[str] = []
    for line in text.splitlines():
        if not _is_rc_row(line):
            out_lines.append(line)
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7 or cells[1] != "CLOSED" or cells[0] in keep_ids or cells[2] >= before:
            out_lines.append(line)
            continue
        rc_id, _status, opened, due, defect, _why, fix = cells[:7]
        head = defect.split(". ", 1)[0].strip()
        if len(head) > _HEADLINE_CHARS:
            head = head[:_HEADLINE_CHARS - 1].rstrip() + "…"
        tags = sorted(set(_AUDIT_TAG_RE.findall(line))) if _AUDIT_LINE_RE.search(line) else []
        audit_note = f" Adversarial audit {' '.join(tags)} processed in this row." if tags else ""
        why = (f"ARCHIVED {_today()}: the full five-why chain and closure evidence are carried "
               f"verbatim by `git show {pointer_sha}:governance/root_cause_log.md` (RC-520 compaction; "
               f"this line asserts nothing new).{audit_note}")
        fix_head = fix.strip()
        if len(fix_head) > _FIX_CHARS:
            fix_head = fix_head[:_FIX_CHARS - 1].rstrip() + "…"
        out_lines.append(f"| {rc_id} | {ARCHIVED_STATUS} | {opened} | {due} | {head} | {why} | "
                         f"ARCHIVED (was CLOSED): {fix_head} |")
        archived.append(rc_id)
    new_text = "\n".join(out_lines) + ("\n" if text.endswith("\n") else "")
    return new_text, archived

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


def _is_rc_row(line: str) -> bool:
    """The ONE recognizer of a ledger row line; `all_rows` parses, `archive_closed_rows` rewrites."""
    return line.startswith("| RC-")


def all_rows(repo: str | Path | None = None) -> list[MissionRow]:
    """Every parseable row in the ledger. The ONLY parser of this file's row grammar."""
    try:
        text = ledger_path(repo).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []             # unreadable ledger -> no rows; see the module docstring on why
    out: list[MissionRow] = []
    for line in text.splitlines():
        if not _is_rc_row(line):
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


# ── is the mission finished ───────────────────────────────────────────────────────────────
def external_blocker(row: MissionRow) -> str | None:
    """The objective blocker recorded on a row, or None.

    TWO STRUCTURAL CELLS, no text anywhere: `status` is the declared token BLOCKED, and `due`
    parses as a date that has not passed. Both are machine-parsed columns of the row schema
    that `check_rc_status_vocabulary` and the overdue clause already police.

    THIS REPLACED PROSE DECIDING AUTHORITY (RC-503). The predicate used to search the free-text
    fix cell for a `BLOCKED_ON_*` substring, which cannot tell a CLAIM from a mention: the same
    characters appear in a sentence describing a blocker, quoting one, or explaining why
    something was NOT blocked. Two rounds earlier the resume condition was prose too, and it
    EXEMPTED "BLOCKED_ON_EXTERNAL - ran out of runway, 2026-01-01" and "I would prefer another
    audit. 2026-01-01" — the exact dispositions the law forbids — because they contained a
    date. Each round replaced one prose test with a field; this is the last of them.

    The due date remains the resume condition, so a stale one fails on arithmetic rather than
    on vocabulary, and an overdue BLOCKED row stays visible debt to the enforced overdue clause.

    HONEST LIMIT, stated rather than implied: this proves the row DECLARES itself blocked and
    carries a live date. No machine can read whether the market is really closed or the
    operator really unanswered. Judging that stays with the operator — but the declaration is
    now a single reviewable cell rather than a phrase buried in a paragraph.
    """
    if (row.status or "").strip() != BLOCKED_STATUS:
        return None
    try:
        due = datetime.date.fromisoformat(row.due.strip())
    except (ValueError, AttributeError):
        return None                       # no parseable resume date -> not an objective blocker
    if due < datetime.date.today():
        return None                       # the date it promised to resume by has passed
    return BLOCKED_STATUS


def row_blockers(row: MissionRow) -> list[str]:
    """Why this row forbids ending the turn. Empty list = this row does not block Stop."""
    status = (row.status or "").strip()
    if status == BLOCKED_STATUS:
        if external_blocker(row):
            return []                      # objectively blocked with a live date: legal
        return ["row is BLOCKED but its due date has passed or does not parse — a blocker "
                "without a live resume date is a deferral, not a blocker"]
    if status != "OPEN":
        return []                          # CLOSED / REMEDIATED rows are finished
    hit = next((m for m in UNFINISHED_MARKERS if m in row.fix.upper()), None)
    # The marker adds nothing to the DECISION — measured decision-neutral across 30
    # cases — but naming what the agent itself wrote makes the block message actionable.
    return [f"fix cell still says {hit!r}" if hit else
            "row is OPEN with neither a finished fix (set it CLOSED with measured evidence) "
            "nor a recorded external blocker"]


def mission_blockers(today: str | None = None,
                     repo: str | Path | None = None) -> list[tuple[str, str]]:
    """(rc_id, reason) for every row THIS worktree introduced that forbids ending the turn.

    Scoped to this worktree's own rows for the same reason authorization is: a row that arrived
    on the trunk is somebody else's landed work, and holding this turn hostage to it would make
    the guard unsatisfiable by anything the agent can do. RC-521: the obligation follows the
    worktree-owned unfinished row across midnight — the same rows that authorize work are the
    rows that must be finished before the turn ends, whatever date they were opened.
    """
    introduced = _rows_this_worktree_introduced(repo)
    out: list[tuple[str, str]] = []
    # None = the git question could not be measured; RC-72's duty then applies to every
    # same-day row rather than none, because an unmeasurable state must not grant passage.
    rows = (same_day_rows(today, repo) if introduced is None
            else [r for r in all_rows(repo) if r.rc_id in introduced])
    for row in rows:
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
def main(argv: list[str] | None = None) -> int:
    """Operator-invoked ledger housekeeping (RC-520): compact CLOSED rows opened before a date.

        .venv/Scripts/python.exe tools/mission_latch.py --archive-closed-before 2026-09-01 --pointer-sha <HEAD>

    The pointer must be the commit whose ledger still carries the full rows (the HEAD you are
    compacting against). Prints the ids archived; exit 2 when the pointer does not resolve.
    """
    import argparse
    ap = argparse.ArgumentParser(description=main.__doc__.splitlines()[0])
    ap.add_argument("--archive-closed-before", metavar="YYYY-MM-DD", required=True)
    ap.add_argument("--pointer-sha", required=True, help="commit carrying the full rows")
    ap.add_argument("--keep", action="append", default=[], help="RC id to leave in full")
    ap.add_argument("--ledger", default=None, help="ledger path (default: this repository's)")
    args = ap.parse_args(argv)
    path = Path(args.ledger) if args.ledger else RC_LOG
    probe = subprocess.run(["git", "cat-file", "-e", f"{args.pointer_sha}:governance/root_cause_log.md"],
                           cwd=str(path.parent.parent), capture_output=True, text=True)
    if probe.returncode != 0:
        print(f"pointer {args.pointer_sha} does not carry governance/root_cause_log.md; refusing to "
              f"archive rows whose full text would have no home")
        return 2
    text = path.read_text(encoding="utf-8")
    new_text, archived = archive_closed_rows(text, args.archive_closed_before, args.pointer_sha, set(args.keep))
    path.write_text(new_text, encoding="utf-8", newline="\n")
    print(f"archived {len(archived)} CLOSED row(s) opened before {args.archive_closed_before}: "
          f"{', '.join(archived[:12])}{' ...' if len(archived) > 12 else ''}")
    print(f"ledger {len(text):,} -> {len(new_text):,} bytes; full rows at git show "
          f"{args.pointer_sha}:governance/root_cause_log.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
