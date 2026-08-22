"""Seams for the mechanical 5-why recursive lock (operator law 2026-07-24)."""
from __future__ import annotations

from pathlib import Path

from tools.check_institutional_correctness import (
    FIVE_WHY_LOCK_CUTOVER,
    _five_why_lock_violations,
)

_P = Path("governance/root_cause_log.md")


def _row(rc="RC-90", status="OPEN", opened="2026-07-24", why=None, fix=None):
    why = why if why is not None else "(1) a -> (2) b -> (3) c -> (4) d -> (5) ROOT: the cause"
    fix = fix if fix is not None else "NOT FIXED - scoped"
    return f"| {rc} | {status} | {opened} | 2026-08-08 | defect text | {why} | {fix} |"


def test_clean_new_row_passes():
    assert _five_why_lock_violations([_row()], _P) == []


def test_missing_root_is_flagged_globally_even_pre_cutover():
    v = _five_why_lock_violations([_row(opened="2026-05-01", why="(1) a -> (2) b -> (3) c -> (4) d -> (5) deep cause")], _P)
    assert len(v) == 1 and "ROOT" in v[0].msg


def test_dangling_child_reference_breaks_the_recursive_regime():
    v = _five_why_lock_violations([_row(why="(1) a -> (2) spawns RC-77 -> (3) c -> (4) d -> (5) ROOT: x")], _P)
    assert len(v) == 1 and "RC-77" in v[0].msg
    ok = _five_why_lock_violations(
        [_row(), _row(rc="RC-91", why="(1) a -> (2) see RC-90 -> (3) c -> (4) d -> (5) ROOT: y")], _P
    )
    assert ok == []


def test_patch_vocabulary_banned_post_cutover_only():
    bad = _row(status="CLOSED", fix="shipped a temporary fix END-TO-END: producer to consumer, PROVEN 3 tests")
    v = _five_why_lock_violations([bad], _P)
    assert any("banned patch vocabulary" in x.msg for x in v)
    grandfathered = _row(opened="2026-07-19", status="CLOSED",
                         fix="MEASURED: reverted 5 circular-import workarounds, PROVEN 14 pass")
    assert _five_why_lock_violations([grandfathered], _P) == []


def test_closure_requires_end_to_end_declaration_post_cutover():
    v = _five_why_lock_violations(
        [_row(status="CLOSED", fix="PROVEN with 12 tests, OBSERVED live values 3.14")], _P
    )
    assert len(v) == 1 and "END-TO-END" in v[0].msg
    ok = _five_why_lock_violations(
        [_row(status="CLOSED", fix="PROVEN 12 tests. END-TO-END: writer through loader through UI, 3 sites.")], _P
    )
    assert ok == []


def test_cutover_constant_is_the_operator_law_date():
    assert FIVE_WHY_LOCK_CUTOVER == "2026-07-24"


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


def _fake_git(name_only, log_diff=None):
    """Simulate the staged-diff git seam: name-only listing + optional log -U0 diff."""
    def fake(args):
        if args[:3] == ["diff", "--cached", "--name-only"]:
            return name_only
        if args[:3] == ["diff", "--cached", "-U0"]:
            return log_diff or []
        return []
    return fake


def _install_fake_git(monkeypatch, name_only, log_diff=None):
    import tools.check_institutional_correctness as cic
    monkeypatch.setattr(cic, "_git_output_lines", _fake_git(name_only, log_diff))
    monkeypatch.setattr(cic, "_staged_has_real_change", lambda rel: True)
    return cic


def test_adversarial_lock_fires_on_prod_change_without_test(monkeypatch):
    cic = _install_fake_git(monkeypatch, ["server.py"])
    v = cic.check_adversarial_audit_test_lock()
    assert len(v) == 1 and "NO co-staged test" in v[0].msg


def test_adversarial_lock_passes_with_costaged_test(monkeypatch):
    cic = _install_fake_git(monkeypatch, ["server.py", "tests/test_server_gate.py"])
    assert cic.check_adversarial_audit_test_lock() == []


_SOLE_MASTER = "ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md"


def test_adversarial_lock_passes_with_no_test_lock_exemption(monkeypatch):
    cic = _install_fake_git(
        monkeypatch,
        ["scoreboard_report.py", _SOLE_MASTER],
        log_diff=["+- [ ] `OD-99` — STATUS=NOT_PROVEN — measurement-only. "
                  "NO-TEST-LOCK: measurement-only closure, no code path"],
    )
    assert cic.check_adversarial_audit_test_lock() == []


def test_adversarial_lock_exemption_requires_the_marker_not_just_a_staged_master(monkeypatch):
    # Master staged but the added line carries NO 'NO-TEST-LOCK:' marker -> still fires.
    cic = _install_fake_git(
        monkeypatch,
        ["scoreboard_report.py", _SOLE_MASTER],
        log_diff=["+- [ ] `OD-99` — STATUS=NOT_PROVEN — x without the marker"],
    )
    v = cic.check_adversarial_audit_test_lock()
    assert len(v) == 1 and "NO co-staged test" in v[0].msg


def test_adversarial_lock_rc_row_is_not_the_exemption_surface(monkeypatch):
    """A new | RC- row, even with NO-TEST-LOCK, does not exempt a production edit."""
    cic = _install_fake_git(
        monkeypatch,
        ["scoreboard_report.py", "governance/root_cause_log.md"],
        log_diff=["+| RC-99 | CLOSED | 2026-07-26 | 2026-08-02 | d | (1)->(2)->(3)->(4)->(5) ROOT: x | "
                  "MEASURED. NO-TEST-LOCK: measurement-only closure, no code path |"],
    )
    v = cic.check_adversarial_audit_test_lock()
    assert len(v) == 1 and "NO co-staged test" in v[0].msg


def test_adversarial_lock_ignores_test_only_and_non_py_commits(monkeypatch):
    cic = _install_fake_git(monkeypatch, ["tests/test_x.py", "README.md", "config.json"])
    assert cic.check_adversarial_audit_test_lock() == []


def test_adversarial_lock_noops_outside_a_commit_context(monkeypatch):
    import tools.check_institutional_correctness as cic
    monkeypatch.setattr(cic, "_git_output_lines", lambda args: None)
    assert cic.check_adversarial_audit_test_lock() == []


def test_front_loaded_blocks_production_without_master_admission(monkeypatch):
    import tools.pretooluse_guard as G
    monkeypatch.setattr(G, "master_admits_production_edit", lambda *a, **k: False)
    cic = _install_fake_git(monkeypatch, ["server.py"])
    v = cic.check_recursive_five_why_front_loaded()
    assert v and "master" in v[0].msg.lower()


def test_front_loaded_allows_when_master_admits(monkeypatch):
    import tools.pretooluse_guard as G
    monkeypatch.setattr(G, "master_admits_production_edit", lambda *a, **k: True)
    cic = _install_fake_git(monkeypatch, ["server.py"])
    assert cic.check_recursive_five_why_front_loaded() == []


def test_front_loaded_new_rc_row_does_not_admit(monkeypatch):
    import tools.pretooluse_guard as G
    monkeypatch.setattr(G, "master_admits_production_edit", lambda *a, **k: False)
    cic = _install_fake_git(
        monkeypatch,
        ["server.py", "governance/root_cause_log.md"],
        log_diff=["+| RC-99999 | OPEN | 2026-08-22 | 2026-09-22 | d | why | FIXED: x |"],
    )
    v = cic.check_recursive_five_why_front_loaded()
    assert v, "a new RC row must not admit a production edit"
    assert "server.py" in v[0].msg


def test_front_loaded_one_covered_file_does_not_launder_uncovered(monkeypatch):
    import tools.pretooluse_guard as G

    def admit(rel, **_k):
        return rel.replace("\\", "/") == "server.py"

    monkeypatch.setattr(G, "master_admits_production_edit", admit)
    cic = _install_fake_git(monkeypatch, ["server.py", "prediction_engine.py"])
    v = cic.check_recursive_five_why_front_loaded()
    assert v, "one covered file must not authorize an uncovered sibling"
    assert "uncovered path(s): prediction_engine.py" in v[0].msg
    assert "uncovered path(s): server.py" not in v[0].msg


def test_front_loaded_both_independently_covered(monkeypatch):
    import tools.pretooluse_guard as G
    monkeypatch.setattr(G, "master_admits_production_edit", lambda *a, **k: True)
    cic = _install_fake_git(monkeypatch, ["server.py", "prediction_engine.py"])
    assert cic.check_recursive_five_why_front_loaded() == []


# ── RC-54: RTH-only market measurement (market-closed rows bias every statistic) ──


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


def _claims_scan(tmp_path, monkeypatch, added_line: str, file_body: str | None = None):
    """Run the real detector over one staged governance .md with `added_line` in its diff."""
    import tools.check_institutional_correctness as cic
    rel = "governance/x.md"
    p = tmp_path / "governance"
    p.mkdir(exist_ok=True)
    (p / "x.md").write_text(file_body if file_body is not None else added_line, encoding="utf-8")
    def fake(args):
        if args[:3] == ["diff", "--cached", "--name-only"]:
            return [rel]
        if args[:3] == ["diff", "--cached", "-U0"]:
            return ["+++ b/" + rel, "+" + added_line]
        return []
    monkeypatch.setattr(cic, "_git_output_lines", fake)
    monkeypatch.setattr(cic, "REPO", tmp_path)
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


def test_open_item_ratchet_ignores_in_date_items_and_counts_overdue(tmp_path):
    """A defect opened today with a real due date is HONEST TRACKING and must not fail the
    gate; an item past its own due date is DEFERRAL and must. Counting all open items
    conflated the two and made recording a real defect fail the build (RC-65)."""
    from tools.check_institutional_correctness import _overdue_governance_items

    rc, reg = _write_ledgers(
        tmp_path,
        ["| RC-90 | OPEN | 2026-07-26 | 2099-01-01 | d | w | f |",     # in date -> ignored
         "| RC-91 | OPEN | 2026-07-01 | 2000-01-01 | d | w | f |",     # ROTTED -> counted
         "| RC-92 | CLOSED | 2026-07-01 | 2000-01-01 | d | w | f |"],  # closed -> ignored
        ["| UNPROVEN | 2026-07-26 | 2099-01-01 | fresh claim | e |",   # in date -> ignored
         "| UNPROVEN | 2026-07-01 | 2000-01-01 | rotted claim | e |",  # ROTTED -> counted
         "| PROVEN | 2026-07-01 | 2000-01-01 | settled claim | e |"],  # terminal -> ignored
    )
    items = _overdue_governance_items(rc, reg)
    assert len(items) == 2, items
    assert "RC-91" in items
    assert any("rotted claim" in i for i in items)
    assert "RC-90" not in items and "RC-92" not in items


def test_open_item_ratchet_does_not_double_report_a_malformed_due_date(tmp_path):
    """check_root_cause_log already fails loudly on an unparseable due date; the ratchet must
    not ALSO count it, or one defect reads as two."""
    from tools.check_institutional_correctness import _is_overdue, _overdue_governance_items

    assert _is_overdue("not-a-date") is False
    assert _is_overdue("") is False
    rc, reg = _write_ledgers(
        tmp_path, ["| RC-93 | OPEN | 2026-07-26 | garbage | d | w | f |"], [])
    assert _overdue_governance_items(rc, reg) == []
