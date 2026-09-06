"""RC-498 — the AGENTS.md Find -> Fix law, made executable at the two seams that decide.

THE LAW ALREADY EXISTED. AGENTS.md: "Find something broken -> fix it. Discovery creates the
obligation to remediate through the full blast radius in the active session. A material defect
is never disposed as queued / logged / TODO / follow-up / pre-existing / out-of-scope."

WHAT WAS MEASURED on 334c5daf, driving the real hook rosters from .claude/settings.json with a
fresh session id per attack: 13 of 26 required behaviours held. A production Edit or Write with
no root-cause row anywhere returned exit 0; `sed -i` / `cp` / `mv` / `tee` / `truncate` on
server.py, `git apply`, and a repo tool invoked `--write server.py` all returned exit 0; and at
Stop, a defect described only in prose, a row relabelled "follow-up / out of scope", and a row
relabelled "pre-existing" all returned exit 0.

Every test here attacks the REAL guard entrypoint, and every protection carries a behavioural
mutation control that removes it and requires the attack to succeed again — a test that passes
whether or not the code is there proves nothing.
"""
from __future__ import annotations

import contextlib
import datetime
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.check_institutional_correctness as CIC  # noqa: E402
import tools.mission_latch as ml  # noqa: E402
import tools.pretooluse_guard as pg  # noqa: E402
import tools.process_lock_guard as plg  # noqa: E402
import tools.stop_guard as sg  # noqa: E402

TODAY = datetime.date.today().isoformat()
HDR = "| id | status | opened | due | defect | why | fix |\n|---|---|---|---|---|---|---|\n"


def _ledger(tmp_path, monkeypatch, *rows: str) -> Path:
    """A hermetic ledger for the guards under test.

    `ledger_path` is patched rather than `RC_LOG` because the guards now resolve the ledger
    from the repo that OWNS the target — the RC-500 fix — so a patched module constant would
    be bypassed the moment a real path is passed.

    `_rows_this_worktree_introduced` defaults to "every row here is this worktree's", which
    keeps every pre-existing test asking what it was written to ask (status, blockers, paths).
    Tests about AUTHORITY override it with `_introduced()`.
    """
    p = tmp_path / "root_cause_log.md"
    p.write_text(HDR + "".join(r.rstrip() + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(ml, "RC_LOG", p)
    monkeypatch.setattr(ml, "ledger_path", lambda repo=None: p)
    monkeypatch.setattr(ml, "_rows_this_worktree_introduced",
                        lambda repo=None: {r.rc_id for r in ml.all_rows()})
    return p


def _row(rc="RC-900", status="OPEN", opened=None, fix="IN PROGRESS") -> str:
    return (f"| {rc} | {status} | {opened or TODAY} | 2099-01-01 | a defect | "
            f"(1) a -> (2) b -> (3) c -> (4) d -> (5) ROOT: e | {fix} |")


def _stop(payload: dict, monkeypatch) -> int:
    monkeypatch.setattr(sg.sys, "stdin", io.StringIO(json.dumps(payload)))
    with contextlib.redirect_stderr(io.StringIO()):
        return sg.main()


def _transcript(tmp_path, name: str, user_last: str | None = None,
                agent_text: str = "Here is my report.") -> str:
    recs = [{"type": "user", "message": {"role": "user",
                                         "content": [{"type": "text", "text": "do the work"}]}}]
    if user_last is not None:
        recs.append({"type": "assistant",
                     "message": {"role": "assistant",
                                 "content": [{"type": "text", "text": "working"}]}})
        recs.append({"type": "user", "message": {"role": "user",
                                                 "content": [{"type": "text",
                                                              "text": user_last}]}})
    recs.append({"type": "assistant",
                 "message": {"role": "assistant",
                             "content": [{"type": "text", "text": agent_text}]}})
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    return str(p)


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — a production mutation requires durable same-day mission state
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# RC-500 — AUTHORITY BINDS TO THE MISSION BEING EXECUTED, NOT TO THE CALENDAR
#
# The first build asked "does any row exist opened today". MEASURED: closing RC-498
# still authorized fresh production edits, and a row opened by unrelated work
# authorized this worktree's. "A row exists today" is a calendar fact that was
# standing in for authority it never established.
# ─────────────────────────────────────────────────────────────────────────────
def _introduced(monkeypatch, *rc_ids: str) -> None:
    """Pin which rows this worktree introduced — the git fact, stubbed for hermeticity."""
    monkeypatch.setattr(ml, "_rows_this_worktree_introduced", lambda repo=None: set(rc_ids))


# ─────────────────────────────────────────────────────────────────────────────
# RC-501 — the two residual authority gaps
# ─────────────────────────────────────────────────────────────────────────────
def _real_repo(tmp_path: Path, name: str, trunk: list[str], branch: list[str]) -> Path:
    """A REAL git checkout with a trunk and a feature branch.

    Not stubbed: the defect being closed is precisely that resolution followed the guard
    file's own repo, so a test that patches resolution away could not observe it.
    """
    import subprocess

    root = tmp_path / name
    (root / "governance").mkdir(parents=True)

    def git(*a):
        subprocess.run(["git", *a], cwd=str(root), capture_output=True, text=True, timeout=60)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "a@b.c")
    git("config", "user.name", "t")
    (root / "governance" / "root_cause_log.md").write_text(
        HDR + "".join(r + "\n" for r in trunk), encoding="utf-8")
    (root / "server.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "trunk")
    git("checkout", "-qb", "feature")
    if branch:
        (root / "governance" / "root_cause_log.md").write_text(
            HDR + "".join(r + "\n" for r in trunk + branch), encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "mission")
    return root


# ─────────────────────────────────────────────────────────────────────────────
# RC-502 — a BLOCKED mission cannot authorize the work it says cannot proceed
# ─────────────────────────────────────────────────────────────────────────────
#: RC-503: "blocked" is the row's STATUS cell, not a phrase in its fix cell. The fix cell still
#: explains WHICH blocker so a human can judge the claim; it carries no authority.
_BLOCKED_WHY = "awaiting the operator's decision on the retirement step; resumes when they answer."


def _blocked_row(rc: str, due: str = "2099-01-01") -> str:
    return (f"| {rc} | BLOCKED | {TODAY} | {due} | a defect | "
            f"(1) a -> (2) b -> (3) c -> (4) d -> (5) ROOT: e | {_BLOCKED_WHY} |")


def test_prose_in_the_fix_cell_cannot_declare_a_row_blocked(tmp_path, monkeypatch):
    """RC-503, the point of the whole change: an OPEN row whose fix cell CONTAINS the old
    `BLOCKED_ON_*` phrasing is NOT blocked. Authority reads the status cell.

    The old predicate substring-matched the free-text cell, which cannot tell a CLAIM from a
    mention — the same characters appear when describing a blocker, quoting one, or saying
    something is not blocked. Here the sentence explicitly denies being blocked, and under the
    old rule that denial would have granted the exemption."""
    _ledger(tmp_path, monkeypatch, _row(
        rc="RC-726",
        fix="This is NOT BLOCKED_ON_OPERATOR and never was; work continues. 2099-01-01"))
    _introduced(monkeypatch, "RC-726")
    row = next(r for r in ml.all_rows() if r.rc_id == "RC-726")
    assert ml.external_blocker(row) is None
    assert ml.row_blockers(row), "an OPEN unfinished row must still block the turn"


def test_blocked_authority_reads_structure_not_prose():
    """RC-503. One definition of 'objectively blocked', and it reads CELLS.

    Structural, because the point is that no substring search survives anywhere in the
    authority path: the status cell decides the declaration, the due cell decides whether it is
    still live, and `BLOCKED` is a token the enforced status-vocabulary check polices."""
    import inspect

    assert Path(ml.__file__).read_text(encoding="utf-8").count("def external_blocker") == 1
    assert ml.BLOCKED_STATUS == "BLOCKED"
    assert not hasattr(ml, "EXTERNAL_BLOCKERS"), "the prose vocabulary must be gone"

    # THE FUNCTION BODY, not the file: comments may still DISCUSS the old phrasing (they
    # explain why it was removed), but the predicate must not READ the prose cell.
    body = inspect.getsource(ml.external_blocker)
    body = body.split('"""')[2] if body.count('"""') >= 2 else body   # drop the docstring
    assert "row.fix" not in body, "authority must not read the free-text fix cell"
    assert "row.status" in body and "row.due" in body

    import tools.check_institutional_correctness as CIC
    assert "BLOCKED" in CIC.DECLARED_RC_STATUSES, "the token must be a declared status"
    assert "BLOCKED" not in CIC.CLOSED_CLASS_RC_STATUSES, (
        "a blocked defect is unfinished work; the close contract must not treat it as dealt "
        "with")


def test_a_landed_row_stops_authorizing_once_it_is_on_the_trunk():
    """The git fact that binds authority: a row shows as introduced-here only while it exists
    in this worktree and not on the trunk. After the PR merges it is on the trunk, and a landed
    mission must not keep authorizing new work."""
    src = Path(ml.__file__).read_text(encoding="utf-8")
    assert "_rows_this_worktree_introduced" in src
    assert 'r"\\+\\| (RC-\\d+) "' in src or "git diff" in src
    # BEDROCK 2026-09-06: one consumer remains — the Stop obligation. The mutation-side
    # authority gate is gone with the latch's PreToolUse half.
    assert src.count("_rows_this_worktree_introduced(repo)") == 1


# RC-521 (2026-09-06): a mission is not a calendar day. OBSERVED: RC-520, reopened by operator
# verdict and still OPEN and unfinished, stopped authorizing its own repair the moment the
# clock passed midnight, and the latch demanded a new row for an unchanged root cause. The
# key is the worktree-owned unfinished row — status OPEN, introduced here, exactly one — and
# the Stop obligation follows that same row across midnight.
YESTERDAY = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


def test_the_stop_obligation_follows_the_same_row_across_midnight(tmp_path, monkeypatch):
    _ledger(tmp_path, monkeypatch, _row(rc="RC-906", opened=YESTERDAY, fix="IN PROGRESS"))
    _introduced(monkeypatch, "RC-906")
    assert _stop({"transcript_path": _transcript(tmp_path, "t.jsonl")}, monkeypatch) == 2
    assert [rc for rc, _why in ml.mission_blockers()] == ["RC-906"]


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — the shell-equivalent continuum
# ─────────────────────────────────────────────────────────────────────────────
_SHELL_MUTATIONS = [
    "sed -i 's/a/b/' server.py",
    "cp /tmp/new.py server.py",
    "mv /tmp/new.py server.py",
    "echo 'x=1' | tee server.py",
    "truncate -s 0 server.py",
    "dd of=server.py if=/tmp/x",
    "git apply /tmp/change.patch",
    "git checkout HEAD -- monte_carlo.py",
    "git restore --source=HEAD~1 monte_carlo.py",
    "patch -p1 < /tmp/x.patch",
    ".venv/Scripts/python.exe tools/codemod.py --write server.py",
    "python tools/fmt.py --in-place static/app.js",
    "curl -o static/app.js https://example.test/app.js",
    "cd tools && cp /tmp/x.py mission_latch.py",
]


def test_the_shell_clause_reuses_the_one_destination_enumerator():
    """ONE FAUCET. The production-checkout rail and the mission latch must consume the SAME
    resolve loop; a second copy is how carry-then-recompute drift starts."""
    src = Path(plg.__file__).read_text(encoding="utf-8")
    assert src.count("def _shell_write_dest_paths") == 1
    assert src.count("def _shell_write_targets") == 1
    assert "_shell_write_targets(cmd, payload_cwd, base_root=primary_res)" in src, (
        "the production-checkout rail must consume the extracted loop, not its own copy")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — Stop may not end on a report
# ─────────────────────────────────────────────────────────────────────────────
def test_stop_blocked_while_the_mission_is_unfinished(tmp_path, monkeypatch):
    _ledger(tmp_path, monkeypatch, _row())
    assert _stop({"transcript_path": _transcript(tmp_path, "t.jsonl")}, monkeypatch) == 2


@pytest.mark.parametrize("fix", [
    "Root cause identified. Fix deferred as a follow-up.",
    "Confirmed but out of scope for this mission.",
    "Pre-existing; not introduced by this change.",
    "Logged for the next mission.",
    "Recommendation: address this in a separate mission.",
    "Queued in the backlog.",
    "TODO in a later session.",
    "Tracked separately; future work.",
    "Ran out of runway; deferred.",
    "Needs another audit first.",
])
def test_stop_cannot_be_cleared_by_renaming_the_work(tmp_path, monkeypatch, fix):
    """The rename attack. RC-72 asked "does this cell contain one of six markers", so writing
    different words cleared it.

    NOTE WHAT BLOCKS THESE, because it is the whole design: NOT a list of forbidden words. An
    earlier draft carried a 24-alternative deferral regex and it was deleted after being
    MEASURED redundant — with the pattern disabled all ten of these still block. The reliable
    question is the row's STATE: a relabelled row is still OPEN, still not finished, and still
    carries no external blocker. A word list would only have promised to catch phrasings
    somebody already thought of."""
    _ledger(tmp_path, monkeypatch, _row(fix=fix))
    assert _stop({"transcript_path": _transcript(tmp_path, "t.jsonl")}, monkeypatch) == 2


def test_stop_blocked_when_an_open_row_says_nothing_at_all(tmp_path, monkeypatch):
    """SILENCE WAS THE HOLE. Matching a vocabulary makes an empty cell a PASS, so the cheapest
    evasion was to write nothing. The question is now the row's STATE, not its wording."""
    _ledger(tmp_path, monkeypatch, _row(fix="—"))
    assert _stop({"transcript_path": _transcript(tmp_path, "t.jsonl")}, monkeypatch) == 2


@pytest.mark.parametrize("due", ["2020-01-01", "soon", "", "next week"])
def test_a_blocker_without_a_live_resume_date_is_only_a_label(tmp_path, monkeypatch, due):
    """A blocker needs a resume condition, and the resume condition is the row's `due` FIELD.

    Two prose tests were removed on the way here. The resume condition was once a regex over
    the fix cell whose date alternative EXEMPTED "ran out of runway, 2026-01-01" and "I would
    prefer another audit. 2026-01-01" — the dispositions the law most explicitly forbids. Then
    the blocker DECLARATION itself was a `BLOCKED_ON_*` substring in the same cell, which could
    not tell a claim from a mention. Both are fields now, and a stale or unparseable date fails
    on arithmetic rather than on vocabulary."""
    _ledger(tmp_path, monkeypatch, _blocked_row("RC-900", due=due))
    assert _stop({"transcript_path": _transcript(tmp_path, "t.jsonl")}, monkeypatch) == 2


def test_agent_preference_cannot_become_a_blocker(tmp_path, monkeypatch):
    """"Ran out of runway" and "I'd prefer another audit" are the mission's named non-blockers.
    They do not exempt, and the reason they cannot is structural: neither produces a live due
    date, and a stale one is refused whatever words accompany it."""
    for why in ("ran out of runway",
                "I would prefer to run another audit first",
                "BLOCKED_ON_EXTERNAL - ran out of runway"):     # the old phrasing, now inert
        # Declared BLOCKED in the status cell AND carrying a stale due date: the declaration is
        # structural, so what refuses it is arithmetic on the date, not the words beside it.
        _ledger(tmp_path, monkeypatch,
                f"| RC-900 | BLOCKED | {TODAY} | 2020-01-01 | d | (1)->(5) ROOT: e | {why} |")
        assert _stop({"transcript_path": _transcript(tmp_path, "t.jsonl")}, monkeypatch) == 2, why


def test_operator_halt_ends_the_turn(tmp_path, monkeypatch):
    _ledger(tmp_path, monkeypatch, _row())
    t = _transcript(tmp_path, "halt.jsonl", user_last="STOP. Hang it up for tonight.")
    assert _stop({"transcript_path": t}, monkeypatch) == 0


@pytest.mark.parametrize("word", ["STOP", "PAUSE", "hang it up", "do not continue"])
def test_every_operator_halt_word_is_honoured(tmp_path, monkeypatch, word):
    _ledger(tmp_path, monkeypatch, _row())
    t = _transcript(tmp_path, "halt.jsonl", user_last=f"{word} — we will pick this up tomorrow.")
    assert _stop({"transcript_path": t}, monkeypatch) == 0


def test_the_agent_cannot_grant_itself_the_operator_halt(tmp_path, monkeypatch):
    """The escape reads the USER side precisely because the agent authors assistant records.
    If it read the assistant side, "STOP" in a summary would end any turn."""
    _ledger(tmp_path, monkeypatch, _row())
    t = _transcript(tmp_path, "self.jsonl", agent_text="STOP. I am hanging it up. Paused.")
    assert _stop({"transcript_path": t}, monkeypatch) == 2


def test_mutation_control_restoring_the_marker_only_question_lets_the_rename_through(
        tmp_path, monkeypatch):
    """NEGATIVE CONTROL for the rename attack: restore RC-72's marker-only question — "does
    this cell contain one of six strings" — and the relabelled row is permitted again, exactly
    as measured on 334c5daf. This is what proves the STATE question is load-bearing."""
    _ledger(tmp_path, monkeypatch, _row(fix="Deferred as a follow-up; out of scope."))
    monkeypatch.setattr(ml, "row_blockers", lambda row: [
        f"fix cell still says {m!r}" for m in ml.UNFINISHED_MARKERS if m in row.fix.upper()])
    assert _stop({"transcript_path": _transcript(tmp_path, "t.jsonl")}, monkeypatch) == 0, (
        "MUTATION CONTROL FAILED TO BITE: under the marker-only question the renamed row must "
        "pass again")


def test_rc72_founding_predicate_is_preserved_exactly(tmp_path, monkeypatch):
    """RC-498 generalises RC-72; it must not quietly replace it. The original predicate still
    answers the original question."""
    _ledger(tmp_path, monkeypatch,
            _row(rc="RC-91", fix="VERIFICATION PENDING"),
            _row(rc="RC-92", fix="NOT FIXED - scoped"),
            _row(rc="RC-93", status="CLOSED", fix="done"),
            _row(rc="RC-94", opened="2020-01-01", fix="IN PROGRESS"))
    assert {r[0] for r in sg.unfinished_rows_opened_today(TODAY)} == {"RC-91", "RC-92"}


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4 — a cleanup closure must close the producer
# ─────────────────────────────────────────────────────────────────────────────
def test_no_generalized_cleanup_framework_exists(monkeypatch):
    """A draft of this work added a ledger-wide validator requiring every CLEANUP closure to
    name producer repair plus a recurrence control, matched by three regexes over the free-text
    fix cell. It was DELETED, for two reasons that are the same reason:

      * it was a GENERALIZED framework for a requirement that belongs at the actual producer
        being repaired, and
      * it decided a real question — "will this population come back?" — by pattern-matching
        English, so a correct closure phrased differently failed and a wrong one phrased well
        passed. That is enforcement credit given to prose.

    The substantive rule survives where it can actually be proven: in the repairing change's
    own tests, which must show recurrence fails. This test pins the deletion so the framework
    is not reintroduced."""
    src = Path(CIC.__file__).read_text(encoding="utf-8")
    for gone in ("_cleanup_closures_close_the_producer_violations", "_CLEANUP_POPULATION",
                 "_PRODUCER_CLOSED", "_RECURRENCE_PROOF"):
        assert gone not in src, f"the generalized cleanup framework is back: {gone}"
    assert not hasattr(CIC, "_cleanup_closures_close_the_producer_violations")


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 6 — one authority, reached by both continua
# ─────────────────────────────────────────────────────────────────────────────
def test_claude_and_cursor_hook_configs_reach_the_same_guards():
    """A lock Cursor does not run is not a lock (RC-208)."""
    claude = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cursor = json.loads((ROOT / ".cursor" / "hooks.json").read_text(encoding="utf-8"))

    def _guards(cmd: str) -> set[str]:
        return {t for t in cmd.split() if t.startswith("tools/") and t.endswith(".py")
                and "chain" not in t}

    claude_edit = _guards(claude["hooks"]["PreToolUse"][0]["hooks"][0]["command"])
    cursor_pre = _guards(cursor["hooks"]["preToolUse"][0]["command"])
    assert claude_edit == cursor_pre, (claude_edit, cursor_pre)

    claude_stop = _guards(claude["hooks"]["Stop"][0]["hooks"][0]["command"])
    cursor_stop = _guards(cursor["hooks"]["stop"][0]["command"])
    assert claude_stop == cursor_stop, (claude_stop, cursor_stop)

    # PIN THE LIVE ROSTERS, not a default constant. tools/stop_chain.py builds the roster it
    # actually runs from argv (`_argv_members(sys.argv[1:]) or STOP_CHAIN`), and these config
    # files supply that argv — so a guard deleted from the command line here stops running
    # while STOP_CHAIN, the constant other tests assert, stays untouched and green. Nothing
    # else compares hook rosters: precommit_institutional and check_delta_adds_no_debt both
    # compare only the CHECKS registry.
    # BEDROCK 2026-09-06: pretooluse_guard left the roster (its gates and latch are gone).
    assert claude_edit == {"tools/operator_law_guard.py", "tools/process_lock_guard.py"}, claude_edit
    # RC-504: proof_only_guard is deliberately absent — removed as Stop authority and deleted.
    # BEDROCK 2026-09-06: honesty_guard likewise — a prose matcher, retired with the doctrine.
    assert claude_stop == {"tools/stop_guard.py", "tools/operator_law_guard.py"}, claude_stop

    # The Bash matcher is a separate registration and carries its own roster.
    claude_bash = _guards(claude["hooks"]["PreToolUse"][1]["hooks"][0]["command"])
    assert claude_bash == {"tools/operator_law_guard.py", "tools/process_lock_guard.py"}, claude_bash


def test_mission_state_has_exactly_one_producer():
    """ONE FAUCET, checked structurally.

    The question that must have ONE producer is "what is this session's mission state" — the
    same-day row scan plus the finished/blocked predicate. Other modules legitimately parse the
    ledger for DIFFERENT predicates (check_institutional_correctness asks which rows are
    OVERDUE and reads staged diff lines; repo_exposure_audit takes a not-CLOSED census), and
    collapsing those into this faucet would be a different error.

    What is asserted: stop_guard no longer keeps its own row scan — it consumes mission_latch —
    and every guard that needs mission state imports that one module. The operator's own record
    notes the faucet lock enforces unique DEFINITION sites only, so a carried-then-recomputed
    second loop would pass that lock and still be a real violation; this reads the source."""
    sg_src = Path(sg.__file__).read_text(encoding="utf-8")
    assert 'startswith("| RC-")' not in sg_src, (
        "stop_guard must not keep a second copy of the ledger row scan")
    assert "mission_latch" in sg_src

    # BEDROCK 2026-09-06: the mutation-side consumers are gone; the Stop guard is the ONE
    # consumer of mission state, and the guards that once imported the latch no longer do.
    for mod in (pg, plg):
        assert "from tools.mission_latch import" not in Path(mod.__file__).read_text(encoding="utf-8"), mod.__name__

    ml_src = Path(ml.__file__).read_text(encoding="utf-8")
    assert ml_src.count('startswith("| RC-")') == 1, "one row scan, in one place"
    assert ml_src.count("def same_day_rows") == 1
    assert ml_src.count("def row_blockers") == 1

    # And the path question is not re-derived either: classify_path is imported, never copied.
    assert "PRODUCTION_SUFFIXES" not in ml_src, (
        "mission_latch must ask pretooluse_guard.classify_path, not carry its own suffix list")


def test_the_latch_adds_no_new_tracked_state_file():
    """The retired find-it-fix-it framework was a tracked JSON offender registry read
    fail-closed, so a corrupt file blocked every Stop and commit repo-wide. RC-498 reads only
    the ledger the repo already keeps."""
    for gone in ("active_defects.json", "pm_mission.json", "operator_go.json",
                 "sole_writer.json", "mission_latch.json"):
        assert not (ROOT / "governance" / gone).exists(), gone
    src = Path(ml.__file__).read_text(encoding="utf-8")
    assert "root_cause_log.md" in src
    assert ".json" not in src.split("ONE FAUCET")[-1].split("def all_rows")[0]


