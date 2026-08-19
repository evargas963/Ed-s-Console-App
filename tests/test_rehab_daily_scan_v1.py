"""RC-218: rehab daily scan is recommend-only and writes ledger artifacts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.rehab_daily_scan as scan  # noqa: E402


def test_collect_findings_flags_disk_only_when_present(tmp_path: Path, monkeypatch) -> None:
    measure = {"live_collect_disk_only": "DISK_ONLY: test", "index_worktree_mismatches": [], "staged_checks_not_on_head": []}
    status = {"porcelain_lines": 0, "staged_ish": 0, "untracked": 0, "modified_ish": 0}
    monkeypatch.setattr(scan, "_head", lambda: "deadbeef")
    # `_collect_findings` always starts by calling `_product_findings()`, which is the
    # daily-scan job: live faucet probe + db-health + duplication_audit + whole-repo
    # AST complexity. MEASURED on this tree: 315.51s for THIS unit test (CI ~564s)
    # when that callee ran for real. This test asserts only the disk_only flag.
    monkeypatch.setattr(scan, "_product_findings", lambda: [])
    findings = scan._collect_findings(measure, status)
    ids = {f["id"] for f in findings}
    assert "rehab.live_disk_only" in ids
    assert all(f.get("recommendation") for f in findings)


def test_product_findings_still_calls_the_existing_scanners() -> None:
    """The daily job must keep invoking the real scanners — hermetic unit tests
    must not become the only caller, and must not delete the call sites.
    """
    import inspect

    src = inspect.getsource(scan._product_findings)
    for name in (
        "check_one_faucet_live.py",
        "relabel_non_trading_sessions_v1.py",
        "check_db_health.py",
        "duplication_audit.py",
    ):
        assert name in src, f"_product_findings no longer invokes {name}"


def test_write_outputs_appends_queue_and_md(tmp_path: Path, monkeypatch) -> None:
    q = tmp_path / "rehab_queue.jsonl"
    md = tmp_path / "rehab_latest.md"
    js = tmp_path / "rehab_latest.json"
    monkeypatch.setattr(scan, "QUEUE_PATH", q)
    monkeypatch.setattr(scan, "LATEST_MD", md)
    monkeypatch.setattr(scan, "LATEST_JSON", js)
    monkeypatch.setattr(scan, "_head", lambda: "abc1234")
    findings = [
        {
            "id": "rehab.test",
            "severity": "P2",
            "facet": "test",
            "summary": "unit",
            "recommendation": "noop",
            "evidence": {},
            "scanned_at_utc": "t",
            "head": "abc1234",
        }
    ]
    payload = scan._write_outputs(findings, {}, {"porcelain_lines": 1})
    assert payload["mode"] == "recommend_only"
    assert payload["pm"] == "operator"
    assert q.is_file() and md.is_file() and js.is_file()
    row = json.loads(q.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["findings"][0]["id"] == "rehab.test"
    assert "Rehab latest" in md.read_text(encoding="utf-8")


def test_main_recommend_only_exit_zero(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(scan, "TQM_QUEUE_PATH", tmp_path / "tqm_queue_latest.json")  # RC-255
    monkeypatch.setattr(scan, "_measure", lambda: {"index_worktree_mismatches": [], "staged_checks_not_on_head": []})
    monkeypatch.setattr(scan, "_porcelain_stats", lambda: {"porcelain_lines": 0, "staged_ish": 0, "untracked": 0, "modified_ish": 0})
    monkeypatch.setattr(scan, "_collect_findings", lambda m, s: [])
    written: list[dict] = []

    def _wo(findings, measure, status):
        written.append({"findings": findings})
        return {"finding_count": 0, "mode": "recommend_only", "pm": "operator"}

    monkeypatch.setattr(scan, "_write_outputs", _wo)
    monkeypatch.setattr(scan, "_run_advisory_debt", lambda: {"ran": True, "exit": 0,
                                                             "total_advisory_violations": 0,
                                                             "checks": {}, "measured_at_utc": 1e12})
    assert scan.main(["--json-only"]) == 0
    assert written and written[0]["findings"] == []


# ── RC-250: the CALLER, not just the callee ──────────────────────────────────────────────
# RC-246 moved 7 ADVISORY checks off the blocking pre-commit path (145s/commit) on the PM's
# explicit condition that they still surface daily. I wrote that they "run on their own
# schedule" and wired nothing — the report existed only because I typed --advisory by hand.
# The RC-246 tests were green throughout, because they assert what advisory mode DOES when
# invoked and never ask WHO invokes it. These assert the invocation.


def test_rc250_the_scan_actually_invokes_advisory_mode(monkeypatch) -> None:
    """The launcher argv must contain --advisory. A capability with no caller is, from the
    inside, indistinguishable from a feature."""
    seen: list[list[str]] = []

    def _fake_run(argv, timeout=None):
        seen.append(list(argv))
        return 0, ""

    monkeypatch.setattr(scan, "_run", _fake_run)
    scan._run_advisory_debt()
    assert seen, "_run_advisory_debt never executed anything"
    argv = seen[0]
    assert "--advisory" in argv, f"advisory mode was not requested: {argv}"
    assert "tools.check_institutional_correctness" in " ".join(argv), (
        f"the advisory run does not call the gate: {argv}"
    )


def test_rc250_advisory_runs_by_default_and_is_opt_out_only(monkeypatch, tmp_path) -> None:
    """Default-ON is the whole point: an advisory run that must be asked for is the hand-typed
    one-shot this row was opened for."""
    monkeypatch.setattr(scan, "TQM_QUEUE_PATH", tmp_path / "tqm_queue_latest.json")  # RC-255
    calls = {"n": 0}
    monkeypatch.setattr(scan, "_measure", lambda: {"index_worktree_mismatches": [], "staged_checks_not_on_head": []})
    monkeypatch.setattr(scan, "_porcelain_stats", lambda: {"porcelain_lines": 0, "staged_ish": 0, "untracked": 0, "modified_ish": 0})
    monkeypatch.setattr(scan, "_collect_findings", lambda m, s: [])
    monkeypatch.setattr(scan, "_write_outputs", lambda f, m, s: {"finding_count": len(f)})

    def _adv():
        calls["n"] += 1
        return {"ran": True, "exit": 0, "total_advisory_violations": 1, "checks": {"x": 1},
                "measured_at_utc": 1e12}

    monkeypatch.setattr(scan, "_run_advisory_debt", _adv)
    scan.main(["--json-only"])
    assert calls["n"] == 1, "the daily scan did not run advisory debt by default"

    scan.main(["--json-only", "--skip-advisory"])
    assert calls["n"] == 1, "--skip-advisory did not actually skip"


def test_rc250_a_missing_or_stale_report_becomes_a_finding() -> None:
    """Silence is the failure mode. If the report cannot be produced, or is old enough to mean
    the schedule stopped, the scan must SAY so — not pass quietly."""
    missing = scan._advisory_findings({"ran": True, "exit": 0, "error": "boom"})
    assert missing and missing[0]["id"] == "rehab.advisory_report_missing"
    assert missing[0]["severity"] == "P1"

    stale = scan._advisory_findings({
        "ran": True, "exit": 0, "total_advisory_violations": 10, "checks": {},
        "measured_at_utc": 1.0,          # 1970 — far past any staleness bar
    })
    assert stale and stale[0]["id"] == "rehab.advisory_report_stale"

    fresh = scan._advisory_findings({
        "ran": True, "exit": 0, "total_advisory_violations": 10, "checks": {},
        "measured_at_utc": __import__("time").time(),
    })
    assert fresh == [], "a fresh report must not raise a finding"


# ── RC-251: TRIAGE must exist, be bounded, and carry kill criteria ───────────────────────
# MEASURE alone is where this repo's prior quality efforts died: a 3,360-line tally supports
# only "ignore" or "mass-rewrite", and the second is banned. These assert the loop's middle.


def test_rc251_queue_is_bounded_and_every_item_is_refusable() -> None:
    adv = {
        "total_advisory_violations": 100,
        "checks": {"ruff_quality": 60, "mypy_types": 40},
        "hotspots": {
            "ruff_quality": {f"pkg/mod{i}.py": 30 - i for i in range(8)},
            "mypy_types": {f"other/mod{i}.py": 20 - i for i in range(8)},
        },
    }
    q = scan._build_tqm_queue(adv)
    assert len(q["top_items"]) <= scan.TQM_MAX_ITEMS, "a queue longer than a session is a dump"
    assert q["top_items"], "hotspots present but triage produced nothing"
    for it in q["top_items"]:
        for key in ("id", "check", "path", "severity", "kill_criteria",
                    "suggested_smallest_change", "why_now"):
            assert it.get(key), f"queue item missing {key}: {it}"
        assert len(it["kill_criteria"]) > 20, (
            "kill criteria must say what would make this NOT worth doing — an item nobody can "
            "refuse is not triage"
        )


def test_rc251_schema_keys_are_present_for_machine_consumers() -> None:
    q = scan._build_tqm_queue({"total_advisory_violations": 5, "checks": {}, "hotspots": {}})
    for key in ("generated_at_utc", "advisory_total", "prior_total", "delta", "top_items", "cap"):
        assert key in q, f"tqm queue schema missing {key}"


def test_rc251_delta_is_computed_against_the_prior_run(monkeypatch, tmp_path) -> None:
    """Without a baseline, no action can be shown to have helped — that is how quality work
    becomes unfalsifiable."""
    monkeypatch.setattr(scan, "_load_prior_advisory_total", lambda: 3400)
    q = scan._build_tqm_queue({"total_advisory_violations": 3360, "checks": {}, "hotspots": {}})
    assert q["prior_total"] == 3400
    assert q["delta"] == -40, "a drop must read as a negative delta"


def test_rc251_hotspots_survive_the_gate_to_scan_handoff() -> None:
    """The bug that shipped once: the gate wrote hotspots, the reader dropped them, and triage
    produced ZERO items while every count looked healthy."""
    import inspect

    src = inspect.getsource(scan._run_advisory_debt)
    assert '"hotspots"' in src or "'hotspots'" in src, (
        "the advisory reader does not carry hotspots forward — the TQM queue will silently "
        "empty while the totals look fine"
    )


def test_rc251_report_renders_the_queue_section(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(scan, "LATEST_MD", tmp_path / "rehab_latest.md")
    monkeypatch.setattr(scan, "LATEST_JSON", tmp_path / "rehab_latest.json")
    monkeypatch.setattr(scan, "QUEUE_PATH", tmp_path / "rehab_queue.jsonl")
    measure = {
        "advisory_debt": {"total_advisory_violations": 42, "checks": {"ruff_quality": 42},
                          "hotspots": {"ruff_quality": {"a/b.py": 42}}},
        "tqm_queue": scan._build_tqm_queue({
            "total_advisory_violations": 42, "checks": {"ruff_quality": 42},
            "hotspots": {"ruff_quality": {"a/b.py": 42}},
        }),
    }
    scan._write_outputs([], measure, {"porcelain_lines": 0})
    md = (tmp_path / "rehab_latest.md").read_text(encoding="utf-8")
    assert "## TQM queue" in md, "the human report has no TQM queue section"
    assert "Advisory debt" in md and "hotspot" in md.lower()
    assert "kill criteria" in md.lower(), "queue items rendered without their kill criteria"
    assert "RE-MEASURE" in md, "the report does not tell the reader to re-measure"


def test_rc251_launcher_is_the_canonical_entry_point() -> None:
    """Schedules should call the repo launcher, not an inline command that lives only in the
    Task Scheduler UI — the EdTerrainScorecard defect class."""
    ps1 = (ROOT / "tools" / "run_rehab_daily.ps1").read_text(encoding="utf-8")
    assert "rehab_daily_scan.py" in ps1
    assert ".venv" in ps1, "the launcher must prefer the repo venv (venv parity)"


# ── RC-255: the test suite is not a writer of tracked state ──────────────────────────────
# The PM found reports/tqm_queue_latest.json committed with top_items: [] and advisory_total 1.
# That 1 is the fixture value above — a green test had overwritten the repo's real artifact,
# because _write_tqm_queue built its destination inline and was the one path a test could not
# redirect. The suite asserts what main() RETURNS and never what it TOUCHED.


def test_rc255_a_test_cannot_write_the_tracked_artifact(monkeypatch, tmp_path) -> None:
    """Drive main() WITHOUT redirecting the queue: the guard must raise, not write."""
    monkeypatch.setattr(scan, "_measure", lambda: {"index_worktree_mismatches": [], "staged_checks_not_on_head": []})
    monkeypatch.setattr(scan, "_porcelain_stats", lambda: {"porcelain_lines": 0, "staged_ish": 0, "untracked": 0, "modified_ish": 0})
    monkeypatch.setattr(scan, "_collect_findings", lambda m, s: [])
    monkeypatch.setattr(scan, "_write_outputs", lambda f, m, s: {"finding_count": 0})
    monkeypatch.setattr(scan, "_run_advisory_debt", lambda: {
        "ran": True, "exit": 0, "total_advisory_violations": 1, "checks": {"x": 1},
        "hotspots": {}, "measured_at_utc": 1e12})
    with pytest.raises(RuntimeError, match="RC-255"):
        scan.main(["--json-only"])


def test_rc255_the_guard_is_inert_for_a_redirected_path(tmp_path, monkeypatch) -> None:
    """Negative control: the guard must block only the TRACKED tree, or it breaks every test."""
    monkeypatch.setattr(scan, "TQM_QUEUE_PATH", tmp_path / "tqm_queue_latest.json")
    out = scan._write_tqm_queue({"advisory_total": 7, "top_items": []})
    assert out.is_file() and json.loads(out.read_text(encoding="utf-8"))["advisory_total"] == 7


def test_rc255_the_committed_queue_is_not_a_fixture() -> None:
    """The artifact on disk must look like a MEASUREMENT, not like test residue. advisory_total
    1 with an empty queue beside a 3,360-violation advisory report is the shipped defect."""
    qp = ROOT / "reports" / "tqm_queue_latest.json"
    adv = ROOT / "reports" / "advisory_debt_latest.json"
    if not (qp.is_file() and adv.is_file()):
        pytest.skip("artifacts not present in this checkout")
    q = json.loads(qp.read_text(encoding="utf-8"))
    a = json.loads(adv.read_text(encoding="utf-8"))
    total_adv = a.get("total_advisory_violations") or 0
    assert q.get("advisory_total") == total_adv, (
        f"queue advisory_total {q.get('advisory_total')} disagrees with the advisory report's "
        f"{total_adv} — the queue was not written by the run that produced the tally"
    )
    if total_adv > 0 and (a.get("hotspots") or {}):
        assert q.get("top_items"), (
            "hotspots exist but the committed queue has no items — a vacuous queue reads as "
            "'nothing to do' (RC-251/RC-255)"
        )


def test_rc250_advisory_never_returns_to_the_blocking_commit_path() -> None:
    """The fix for invisibility must not undo P1: ADVISORY work stays out of the blocking
    commit path.

    RC-406: the commit seam no longer runs the whole-tree catalog delta at all — that proof is
    RELOCATED to CI (hardening.yml runs the SAME owner). On the commit path the seam only reads
    the enforced-check ROSTER (`git show` of the checker, base vs staged index) and blocks on a
    removal. Advisory verdicts live inside that catalog, so if the catalog is not on the commit
    path, advisory cannot be either. Asserted on what the seam DOES: it launches NO
    check_delta_adds_no_debt / check_institutional_correctness subprocess and no `--advisory`,
    recording every real launch rather than reading the file.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "precommit_rc250", ROOT / "tools" / "precommit_institutional.py")
    seam = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seam)

    launches: list[list[str]] = []
    real_run = seam.subprocess.run

    def recording_run(args, **kw):
        launches.append([str(a) for a in args])
        return real_run(args, **kw)  # record AND actually run (the roster read must be real)

    seam.subprocess.run = recording_run
    try:
        rc = seam.main()
    finally:
        seam.subprocess.run = real_run

    assert isinstance(rc, int), "the seam did not produce an exit code"
    # The seam does only git roster reads (rev-parse + `git show` of the checker file). A `git
    # show ...:tools/check_institutional_correctness.py` names the checker but does NOT run it.
    # Any NON-git subprocess would mean the whole-tree catalog/delta — where advisory verdicts
    # live — is back on the commit path; RC-406 relocated that to CI.
    non_git = [a for a in launches if not (a and a[0] == "git")]
    assert not non_git, (
        f"the commit seam launched a non-git subprocess — the whole-tree catalog/delta (and its "
        f"advisory verdicts) is back on the commit path; RC-406 relocated it to CI: {non_git}")
    assert not any("--advisory" in " ".join(a) for a in launches), (
        f"advisory checks are back on the commit path — ~145s/commit for verdicts that cannot "
        f"veto (RC-246/RC-406): {launches}")
