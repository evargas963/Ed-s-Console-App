"""Seams for the no-terminal-null clause and the RC-49 adversarial test-lock.

RC-470: the five-why grammar validator (_five_why_lock_violations) and its check are
retired - governance/retired_checks.md - and their seven seams left with them. The
surviving occupants of this file test checks that STAY: no_terminal_null (surrender
vocabulary + null study reports) and the adversarial-audit test-lock family below.
"""
from __future__ import annotations

import datetime
from pathlib import Path

_P = Path("governance/root_cause_log.md")


def _row(rc="RC-90", status="OPEN", opened="2026-07-24", why=None, fix=None):
    why = why if why is not None else "(1) a -> (2) b -> (3) c -> (4) d -> (5) ROOT: the cause"
    fix = fix if fix is not None else "NOT FIXED - scoped"
    return f"| {rc} | {status} | {opened} | 2026-08-08 | defect text | {why} | {fix} |"


# ── No-terminal-null clause (operator law 2026-07-24, second clause) ─────────


def test_surrender_vocabulary_requires_next_depth():
    from tools.check_institutional_correctness import _surrender_violations

    bare = _row(why="(1) a -> (2) b -> (3) c -> (4) d -> (5) ROOT: this is a dead end")
    v = _surrender_violations([bare], _P)
    assert len(v) == 1 and "NEXT-DEPTH" in v[0].msg
    doored = _row(
        why="(1) a -> (2) b -> (3) c -> (4) d -> (5) ROOT: dead end at this depth. "
            "NEXT-DEPTH: external multi-year data acquisition unlocks it"
    )
    assert _surrender_violations([doored], _P) == []
    grandfathered = _row(opened="2026-07-19",
                         why="(1) a -> (2) b -> (3) c -> (4) d -> (5) ROOT: dead end")
    assert _surrender_violations([grandfathered], _P) == []


def test_null_reports_require_next_depth_post_cutover():
    from tools.check_institutional_correctness import _terminal_null_violations

    null_no_door = (_P, {"generated_utc": "2026-07-26T01:00:00", "n_survivors": 0})
    v = _terminal_null_violations([null_no_door])
    assert len(v) == 1 and "next_depth" in v[0].msg
    null_doored = (_P, {"generated_utc": "2026-07-26T01:00:00", "n_survivors": 0,
                        "next_depth": "run the reversion generator prereg"})
    assert _terminal_null_violations([null_doored]) == []
    pre_cutover = (_P, {"generated_utc": "2026-07-24T01:00:00", "n_survivors": 0})
    assert _terminal_null_violations([pre_cutover]) == []
    survivor = (_P, {"generated_utc": "2026-07-26T01:00:00", "n_survivors": 2})
    assert _terminal_null_violations([survivor]) == []


# ── RC-49: adversarial-audit test-lock (every fix ships a locking test) ────────



def _rth_scan(tmp_path, monkeypatch, name: str, src: str):
    """Run the real detector over a single synthetic file."""
    import tools.check_institutional_correctness as cic
    p = tmp_path / name
    p.write_text(src, encoding="utf-8")
    monkeypatch.setattr(cic, "_production_py_files", lambda: [p])
    monkeypatch.setattr(cic, "REPO", tmp_path)
    return cic.check_rth_only_market_measurement()


_MEASURE = (
    "import statistics\n"
    "rows = conn.execute('SELECT spot FROM option_chain_morning_full').fetchall()\n"
    "print(statistics.median([r[0] for r in rows]))\n"
)


def test_rth_lock_fires_on_unscoped_measurement(tmp_path, monkeypatch):
    v = _rth_scan(tmp_path, monkeypatch, "study_x.py", _MEASURE)
    assert len(v) == 1 and "trading-session scoping" in v[0].msg


def test_rth_lock_passes_when_a_calendar_authority_is_used(tmp_path, monkeypatch):
    src = "from time_et import is_trading_day_et\n" + _MEASURE
    assert _rth_scan(tmp_path, monkeypatch, "study_y.py", src) == []


def test_rth_lock_passes_with_an_explicit_marker(tmp_path, monkeypatch):
    src = "# rth-scope-ok: schema census, session-independent\n" + _MEASURE
    assert _rth_scan(tmp_path, monkeypatch, "study_z.py", src) == []


def test_rth_lock_exempts_data_maintenance_which_must_process_every_row(tmp_path, monkeypatch):
    # A backfill that skipped weekends would corrupt the store — writes are exempt by design.
    src = _MEASURE + "conn.executemany('UPDATE snapshots SET x=?', vals)\n"
    assert _rth_scan(tmp_path, monkeypatch, "backfill_x.py", src) == []


def test_rth_lock_ignores_files_that_only_read_without_aggregating(tmp_path, monkeypatch):
    src = "rows = conn.execute('SELECT spot FROM snapshots').fetchall()\nprint(rows[0])\n"
    assert _rth_scan(tmp_path, monkeypatch, "peek.py", src) == []


# ── RC-56: a committed measured claim must carry its reproduce command ────────


def _register_md(rows: str) -> str:
    """A minimal register in the real file's shape: >=5 cells, status / _ / due / claim / _."""
    return ("| status | owner | due | claim | evidence |\n"
            "|---|---|---|---|---|\n" + rows)


def _in_date_register() -> str:
    """A synthetic register with nothing overdue. The due date is computed from TODAY so this
    fixture can never go stale the way a hard-coded date does."""
    due = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    return _register_md(f"| UNPROVEN | ops | {due} | synthetic in-date claim | pending |\n")


def _claims_scan(tmp_path, monkeypatch, added_line: str, file_body: str | None = None,
                 register: str | None = None):
    """Run the real detector over one staged governance .md with `added_line` in its diff.

    ISOLATION (the defect this fixture had): check_measured_claims_cite_evidence() is the
    CONSOLIDATED evidence gate, so it also runs _unproven_register_violations(). That reads
    module-level `_UNPROVEN_REGISTER`, which is bound to the REAL repository at import time and
    is therefore NOT redirected by monkeypatching `REPO`. These synthetic tests consequently
    inherited the real governance/unproven_register.md, and on 2026-08-29 five genuinely overdue
    rows began leaking in — five tests that assert an EXACT result started failing for reasons
    that have nothing to do with what they test. Point the register at a synthetic in-date one so
    the fixture sees only its own repo state. Real enforcement is untouched: the validator itself
    is unchanged and still reads the real file everywhere else.
    """
    import tools.check_institutional_correctness as cic
    rel = "governance/x.md"
    p = tmp_path / "governance"
    p.mkdir(exist_ok=True)
    (p / "x.md").write_text(file_body if file_body is not None else added_line, encoding="utf-8")
    reg = p / "unproven_register.md"
    reg.write_text(_in_date_register() if register is None else register, encoding="utf-8")
    def fake(args):
        if args[:3] == ["diff", "--cached", "--name-only"]:
            return [rel]
        if args[:3] == ["diff", "--cached", "-U0"]:
            return ["+++ b/" + rel, "+" + added_line]
        return []
    monkeypatch.setattr(cic, "_git_output_lines", fake)
    monkeypatch.setattr(cic, "REPO", tmp_path)
    monkeypatch.setattr(cic, "_UNPROVEN_REGISTER", reg)
    return cic.check_measured_claims_cite_evidence()


def test_claims_lock_fires_on_measured_claim_without_command(tmp_path, monkeypatch):
    v = _claims_scan(tmp_path, monkeypatch, "MEASURED: median shift 0.068 percent across 169 chains")
    assert len(v) == 1 and "no reproducible command" in v[0].msg


def test_claims_lock_passes_when_a_reproduce_command_is_present(tmp_path, monkeypatch):
    line = "MEASURED: median 0.36 percent over 118 chains. REPRODUCE: `python tools/flip_iv_sensitivity_v1.py`"
    assert _claims_scan(tmp_path, monkeypatch, line) == []


def test_claims_lock_allows_an_explicitly_tagged_hypothesis(tmp_path, monkeypatch):
    line = "[UNVERIFIED] we think the median shift is near 0.4 percent on 118 chains"
    assert _claims_scan(tmp_path, monkeypatch, line) == []


def test_claims_lock_ignores_prose_without_numeric_findings(tmp_path, monkeypatch):
    assert _claims_scan(tmp_path, monkeypatch, "VERIFIED the wiring is correct end to end") == []


def test_claims_lock_does_not_count_dates_or_rc_ids_as_claims(tmp_path, monkeypatch):
    line = "PROVEN on 2026-07-26 per RC-43 and RC-54"
    assert _claims_scan(tmp_path, monkeypatch, line) == []


# ── The isolation fix must not weaken unproven-register enforcement ──────────


def _register_violations(monkeypatch, path):
    import tools.check_institutional_correctness as cic
    monkeypatch.setattr(cic, "_UNPROVEN_REGISTER", path)
    return cic._unproven_register_violations()


def test_an_overdue_synthetic_row_still_fails_the_register_validator(tmp_path, monkeypatch):
    """The fixture is isolated, not neutered: an overdue row in the register it points at still
    fails, so the synthetic register cannot be used to hide an open claim."""
    overdue = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    reg = tmp_path / "reg.md"
    reg.write_text(_register_md(f"| UNPROVEN | ops | {overdue} | synthetic overdue claim | none |\n"),
                   encoding="utf-8")
    v = _register_violations(monkeypatch, reg)
    assert len(v) == 1 and "3d past due" in v[0].msg


def test_an_in_date_or_terminal_synthetic_row_passes(tmp_path, monkeypatch):
    future = (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
    past = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    reg = tmp_path / "reg.md"
    reg.write_text(_register_md(
        f"| UNPROVEN | ops | {future} | still in date | pending |\n"
        f"| PROVEN | ops | {past} | terminal, past due date is irrelevant | evidence |\n"
        f"| REMEDIATED | ops | {past} | terminal via a landed fix | commit |\n"), encoding="utf-8")
    assert _register_violations(monkeypatch, reg) == []


def test_the_real_register_is_still_enforced_after_the_isolation_fix(monkeypatch):
    """Run the UNCHANGED validator against the ACTUAL repository register and require it to report
    exactly the rows that are genuinely past due — five of them dated 2026-08-28 as of 2026-08-29.
    Computed from the file rather than hard-coded, so this proves enforcement survives on any day.
    """
    import tools.check_institutional_correctness as cic
    real = Path(__file__).resolve().parent.parent / "governance" / "unproven_register.md"
    assert real.is_file(), "the real register must exist — missing register is itself a violation"

    today = datetime.date.today()
    expected = 0
    for ln in real.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 5 or cells[0].upper() not in ("UNPROVEN", "DISPROVED"):
            continue
        try:
            due = datetime.date.fromisoformat(cells[2])
        except ValueError:
            expected += 1
            continue
        if (today - due).days > 0:
            expected += 1

    monkeypatch.setattr(cic, "_UNPROVEN_REGISTER", real)
    got = cic._unproven_register_violations()
    assert len(got) == expected, (
        f"real-register enforcement changed: validator reported {len(got)}, "
        f"file contains {expected} genuinely open past-due row(s)")
    assert all(v.path == real for v in got)


# ── RC-65: the open-item ratchet must measure DEFERRAL, not discovery ─────────


def _write_ledgers(tmp_path, rc_rows: list[str], reg_rows: list[str]):
    g = tmp_path / "governance"
    g.mkdir(exist_ok=True)
    (g / "root_cause_log.md").write_text(
        "| id | status | opened | due | defect | why | fix |\n" + "\n".join(rc_rows) + "\n",
        encoding="utf-8")
    (g / "unproven_register.md").write_text(
        "| status | opened | due | claim | evidence |\n" + "\n".join(reg_rows) + "\n",
        encoding="utf-8")
    return g / "root_cause_log.md", g / "unproven_register.md"


def test_overdue_law_ignores_in_date_items_and_counts_rotted_ones(tmp_path, monkeypatch):
    """A defect opened today with a real due date is HONEST TRACKING and must not fail the
    gate; an item past its own due date is DEFERRAL and must. Counting all open items
    conflated the two and made recording a real defect fail the build (RC-65).

    RC-505 drives this against the SURVIVING owners. `check_open_item_cap` and its
    `_overdue_governance_items` are retired — they reported, item for item, what
    check_root_cause_log reports for RC rows and check_measured_claims_cite_evidence reports
    for register claims. The LAW is unchanged; only the number of checks stating it is.
    """
    import tools.check_institutional_correctness as M

    rc, reg = _write_ledgers(
        tmp_path,
        ["| RC-90 | OPEN | 2026-07-26 | 2099-01-01 | d | (1) a -> (2) b -> (3) c -> (4) d -> "
         "(5) ROOT: e | f |",                                            # in date -> ignored
         "| RC-91 | OPEN | 2026-07-01 | 2000-01-01 | d | (1) a -> (2) b -> (3) c -> (4) d -> "
         "(5) ROOT: e | f |",                                            # ROTTED -> counted
         "| RC-92 | CLOSED | 2026-07-01 | 2000-01-01 | d | (1) a -> (2) b -> (3) c -> (4) d "
         "-> (5) ROOT: e | verified: measured 1 of 1 |"],                # closed -> ignored
        ["| UNPROVEN | 2026-07-26 | 2099-01-01 | fresh claim | e |",     # in date -> ignored
         "| UNPROVEN | 2026-07-01 | 2000-01-01 | rotted claim | e |",    # ROTTED -> counted
         "| PROVEN | 2026-07-01 | 2000-01-01 | settled claim | e |"],    # terminal -> ignored
    )
    monkeypatch.setattr(M, "REPO", tmp_path)
    monkeypatch.setattr(M, "_UNPROVEN_REGISTER", reg)
    rc_overdue = [v for v in M.check_root_cause_log() if "past its due date" in str(v.msg)]
    assert [v for v in rc_overdue if "RC-91" in str(v.msg)], rc_overdue
    assert not [v for v in rc_overdue if "RC-90" in str(v.msg) or "RC-92" in str(v.msg)], (
        "an in-date OPEN row or a CLOSED row was counted as deferral")

    reg_overdue = [v for v in M.check_measured_claims_cite_evidence()
                   if "past due" in str(v.msg)]
    assert [v for v in reg_overdue if "rotted claim" in str(v.msg)], reg_overdue
    assert not [v for v in reg_overdue
                if "fresh claim" in str(v.msg) or "settled claim" in str(v.msg)]


def test_a_malformed_due_date_is_reported_once_not_twice(tmp_path, monkeypatch):
    """One defect must read as one defect. A junk due date is reported by the row-schema
    clause; it must not ALSO be counted as overdue, in either ledger."""
    import tools.check_institutional_correctness as M

    rc, reg = _write_ledgers(
        tmp_path,
        ["| RC-93 | OPEN | 2026-07-26 | garbage | d | (1) a -> (2) b -> (3) c -> (4) d -> "
         "(5) ROOT: e | f |"],
        ["| UNPROVEN | 2026-07-26 | garbage | junk-dated claim | e |"])
    monkeypatch.setattr(M, "REPO", tmp_path)
    monkeypatch.setattr(M, "_UNPROVEN_REGISTER", reg)

    msgs = [str(v.msg) for v in M.check_root_cause_log()]
    assert not [m for m in msgs if "past its due date" in m], msgs
    assert [m for m in msgs if "RC-93" in m and "due date" in m], (
        "a junk due date must still be reported ONCE, by the schema clause")

    reg_msgs = [str(v.msg) for v in M.check_measured_claims_cite_evidence()]
    assert not [m for m in reg_msgs if "past due" in m], reg_msgs
    assert [m for m in reg_msgs if "unparseable due date" in m], reg_msgs
