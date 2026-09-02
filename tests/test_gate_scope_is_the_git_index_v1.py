"""RC-286 — a gate's idea of "repo-wide" must be the git index, in EVERY gate.

RC-274 found the silent-zero gate walking `scratchpad/` — a directory `.gitignore:202`
excludes and which holds 0 tracked files — and fixed it by DEFINITION rather than by adding
a skip entry: repo-wide became `git ls-files`, which cannot drift. That repair was applied
to the one gate then failing. `tools/anti_pattern_sweep.py`, one directory away, kept its
`ROOT.rglob("*.py")` plus a hand-maintained `SKIP_DIR_PARTS`, and has been failing on
throwaway audit scripts ever since.

THE PATTERN THIS FILE EXISTS TO STOP. Three times in two days I have fixed the instance in
front of me and not swept the class: RC-283 (a cleanup tool that reached one table of
three), RC-284 (a harness that typed one outcome), and this. A root cause gets written, a
mechanism gets designed, and its second instance stays broken because nothing asked where
else the shape lives. So the last test here asks that question mechanically.
"""

from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.anti_pattern_sweep import iter_py_files  # noqa: E402


def _tracked() -> set[str]:
    out = subprocess.run(["git", "ls-files", "-z", "--", "*.py"],
                         cwd=REPO, capture_output=True, text=True, check=True).stdout
    return {p for p in out.split("\0") if p}


def test_untracked_scratch_is_out_of_scope():
    """The defect: gitignored scratch judged as production code."""
    rels = {p.relative_to(REPO).as_posix() for p in iter_py_files(production_only=True)}
    assert not [r for r in rels if r.startswith("scratchpad/")], (
        "untracked scratch is back inside a repo-wide product gate")


def test_the_scope_is_exactly_what_git_tracks():
    """Not a subset that happens to exclude scratch — the index itself."""
    rels = {p.relative_to(REPO).as_posix() for p in iter_py_files(production_only=False)}
    assert rels <= _tracked(), (
        f"the scanner reaches files git does not track: {sorted(rels - _tracked())[:5]}")


def test_the_scan_did_not_collapse():
    """A gate that passes because it stopped looking is worse than one that fails."""
    rels = {p.relative_to(REPO).as_posix() for p in iter_py_files(production_only=True)}
    assert len(rels) > 200, f"production scope collapsed to {len(rels)} files"
    for must in ("server.py", "math_levels.py", "lstm_data.py", "terrain_engine.py",
                 "desk_store.py", "db.py"):
        assert must in rels, f"{must} fell out of the production scan"


def test_tools_and_tests_stay_out_of_the_production_scan():
    rels = {p.relative_to(REPO).as_posix() for p in iter_py_files(production_only=True)}
    assert not [r for r in rels if r.startswith(("tools/", "tests/"))]


def _filesystem_enumerating_scanners() -> list[str]:
    """Every TRACKED module under tools/ or tests/ that builds its own file list from disk.

    RC-307 widened this. It read `(REPO / "tools").glob("*.py")` — the directory the RC-286
    instance happened to live in — so the same shape inside `tests/` went uncounted, and
    `tests/test_coh_sa2_et_authority.py` spent that time failing on 93 untracked scratch
    scripts. A sweep that inherits its instance's neighbourhood cannot find the class, which
    is the exact failure RC-286's docstring names. The scope is now the git index, which is
    also the answer this whole file is about.

    TEST_SYSTEM_REHAB_V2 (2026-08-31) — UNIFIED SCANNER AUTHORITY. This function used to run
    its own independent AST walk that matched `.rglob(` only, so it never saw `.glob(` or
    `os.walk(` sites — a second, weaker implementation of the exact same detection the
    duplicate-repo-observation recurrence lock (tools/check_institutional_correctness.py::
    check_no_new_independent_repo_scan_in_tests) already did correctly. There is now exactly
    ONE AST walk for this shape (`_find_py_source_scan_sites`); this function is a VIEW over
    its output that adds only the one thing that walk does not do itself: intersecting with
    the git index, so untracked scratch stays invisible (RC-274 -> RC-286).
    """
    from tools.check_institutional_correctness import _find_py_source_scan_sites
    tracked = _tracked()
    hits = (_find_py_source_scan_sites(REPO / "tools", name_glob="*.py")
            + _find_py_source_scan_sites(REPO / "tests", name_glob="*.py"))
    found: list[str] = []
    for path, lineno in hits:
        rel = path.relative_to(REPO).as_posix()
        if rel in tracked:
            found.append(f"{rel}:{lineno}")
    return sorted(found)


def test_the_two_repo_wide_product_gates_use_the_index():
    """The gates that make repo-wide CLAIMS about product code must not guess the scope.

    Narrowed deliberately, and the narrowing is the honest part. The class sweep below
    found 20 further sites; asserting all of them here would ship a permanently-red test,
    and exempting all of them would be the allowlist habit this session keeps removing.
    So this pins what is actually fixed, and the remainder is MEASURED, not waved away.
    """
    for rel in ("tools/anti_pattern_sweep.py",):
        src = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        assert "git ls-files" in src, f"{rel} no longer scopes to the git index"
        assert 'ROOT.rglob("*.py")' not in src, f"{rel} enumerates the filesystem again"
    gate = (REPO / "tests" / "test_ohlcv_schwab_first.py").read_text(
        encoding="utf-8", errors="replace")
    assert "git ls-files" in gate, "the silent-zero gate lost its index scope (RC-274)"


def test_the_remaining_filesystem_scanners_are_measured_not_forgotten():
    """RC-286's class sweep — the question I failed to ask three times running.

    A scanner that builds its own file list re-decides what "the repository" means, and
    every such list is correct exactly once. This does not fail the build for the ones
    still outstanding, because I have not read them and do not know which genuinely need
    the filesystem — `check_credential_leak` legitimately asks about UNTRACKED files, a
    question the index cannot answer. What it does is refuse to let the count drift out of
    sight: the number is asserted, so the next person to add one has to come here.

    2026-08-24 (audit T2-4) — NAMED-SET CONVERSION. The integer pin is CLOSED HISTORY
    (its ledger stays in the comments below): the census is now frozen BY NAME in
    tests/frozen/filesystem_scanner_files.txt, one "path.py::N" per line where N is that
    file's count of .py-rglob sites. Line numbers are deliberately stripped so line
    drift cannot churn the file, but N keeps a NEW site inside an already-listed file
    visible as a one-line diff (tools/check_institutional_correctness.py holds 5 sites
    today; a set of bare file names would absorb a 6th silently). A move now shows WHICH
    file gained or lost a scanner instead of forcing integer archaeology.
    """
    found = _filesystem_enumerating_scanners()
    # 44 -> 43 (RC-470): check_five_why_recursive_lock's tests/**/*.py rglob corpus scan
    # left the tree with its retired check (governance/retired_checks.md) — a scanner
    # REMOVED, not index-scoped.
    # 43 -> 40 (SIMPLICITY REHAB 2026-08-24): four per-test repo sweeps LEFT
    # (test_news_events_drop x2, test_session_log_drop, test_confluence_log_drop —
    # converted to the shared session RepoIndex), one ARRIVED (tests/conftest.py
    # RepoIndex builder, the single live pass those tests now consume).
    # tools/check_institutional_correctness.py 5 -> 7 (TEST_SYSTEM_REHAB_V2 2026-08-31):
    # two NEW, deliberate scanner sites ARRIVED inside this already-tracked file --
    # check_no_duplicate_tests and check_no_new_independent_repo_scan_in_tests, the two
    # mechanical recurrence locks that rehab required. Same file, no new file in the set.
    # 13 files LEFT the same day: test_anti_pattern_family_repo_wide.py,
    # test_coh_sa1_float_consolidation.py, test_datetime_silent_default_repo_wide.py,
    # test_direction_triplet_authority.py, test_find_cal_ts_rderive.py,
    # test_fusion_contract.py, test_mhmlb_namespace_v1.py, test_ml_feature_provenance.py,
    # test_position_sizing_policy.py, test_replay_hold_bars.py,
    # test_repo_sweep_error_propagation_v1.py, test_repo_sweep_magic_thresholds_v1.py,
    # test_stack_wire_4_v1.py -- each migrated its independent root.rglob("*.py") onto
    # the shared repo_index fixture (check_no_new_independent_repo_scan_in_tests, now
    # ENFORCED, requires it). This detector (`.rglob(` only) does not yet see the
    # further 4 files migrated the same day via `.glob(` (test_centralization.py,
    # test_execution_identity_v1.py, test_market_context_fetch_fail_closed.py,
    # test_path_authority_v1.py) -- they were never in this frozen set to begin with,
    # since this older detector never matched `.glob(` in the first place.
    # 21 -> 62 (TEST_SYSTEM_REHAB_V2, same day, continuation): the gap noted directly
    # above was CLOSED, not left unresolved. `_filesystem_enumerating_scanners()` no
    # longer runs its own AST walk -- it now calls the SAME `_find_py_source_scan_sites`
    # the duplicate-repo-observation lock uses, which also catches `.glob(` and both
    # `os.walk(` forms. The jump from 21 to 62 is not new scanners appearing; it is the
    # weaker of two competing implementations being retired. Every one of the 41
    # newly-visible sites was already there: 4 more `.glob(`-based test_*.py files
    # (already migrated, already counted by the OTHER detector, now also seen here), a
    # cluster of `tools/_build_sectionN_inventory.py` one-off scripts, and standalone
    # tools/ audit CLIs (agent_error_report.py, build_phase3_repo_cleanup.py,
    # operating_process_lock.py, repo_exposure_audit.py, repo_scoreboard.py,
    # universal_scope_lock.py x3) that legitimately walk the tree for their own
    # single-purpose reason and were simply invisible to the old `.rglob(`-only,
    # endswith(".py")-only matcher. None of these are test files subject to the
    # ENFORCED redundant-observation lock (that lock stays scoped to tests/test_*.py,
    # archive/ excluded, and still reports 0) -- this frozen set is the broader,
    # non-judgmental census the docstring above describes, now computed once.
    # tools\check_institutional_correctness.py 10 -> 12 (TEST_SYSTEM_REHAB_V2 final
    # remediation, 2026-08-31): the shared `_find_py_source_scan_sites` detector was
    # extended to also catch `subprocess.run(["git","ls-files",...])` + a subsequent
    # per-file content read (the bypass shape ~9-10 test files used, structurally
    # invisible to the original `.rglob`/`.glob`/`os.walk`-only matcher), and one
    # new, deliberate `.rglob(` scanner site arrived in this file (the third
    # recurrence lock, `_find_constant_true_or_assertions`, ENFORCED at 0 real
    # instances). Both extensions to an ALREADY-tracked file, no new file. 5 NEW
    # FILES arrived, all in tools/ (never test files, never subject to the ENFORCED
    # lock, which stays 0): check_one_producer.py, check_private_paths.py,
    # check_test_claims_are_executed.py, producer_inventory_v1.py,
    # turn_self_audit.py -- each already did the git-ls-files+read shape for its own
    # legitimate single-purpose census/audit reason, simply invisible to the old
    # detector before its git-ls-files extension. None of these are new scans; the
    # detector just stopped missing a call shape it was blind to.
    # tools/repo_rehab_status.py::1 ARRIVED 2026-09-02 (RC-505), and it is a DELIBERATE
    # `git ls-files` exception rather than a lapse into the RC-274 -> RC-286 loop. The
    # function is `physical_generated_state`, and its whole subject is runtime state that
    # is PHYSICALLY PRESENT IN THE SOURCE TREE BUT IGNORED, which `git ls-files` cannot
    # report by construction: measured on this host it finds 247 such files against 224
    # tracked, and the 23 it alone sees include data/ed_console.db and logs/ed_server.log.
    # The tracked count is computed separately, from the index, and reported separately.
    # A walk is the only instrument that can answer this question; every OTHER census in
    # that file reads the index.
    per_file = Counter(rel.rsplit(":", 1)[0] for rel in found)
    current = {f"{rel}::{n}" for rel, n in per_file.items()}
    frozen = frozenset(
        ln for ln in (REPO / "tests" / "frozen" / "filesystem_scanner_files.txt")
        .read_text(encoding="utf-8").splitlines() if ln)
    arrived = sorted(current - frozen)
    left = sorted(frozen - current)
    assert current == frozen, (
        f"the filesystem-enumerating scanner set moved (frozen 2026-08-24 at the "
        f"SIMPLICITY REHAB's 40 sites; RC-470 baseline 43).\n"
        f"ARRIVED (scanning now, not in the frozen set): {arrived}\n"
        f"LEFT (in the frozen set, not scanning now): {left}\n"
        f"A changed ::N for the same file means a scanner site was added or removed "
        f"INSIDE it. If you FIXED one, its line leaves the frozen file — a one-line edit "
        f"to tests/frozen/filesystem_scanner_files.txt in the same commit, reviewed by "
        f"name; do not bulk-regenerate. If you ADDED one, use `git ls-files` instead — "
        f"this is the RC-274 -> RC-286 loop.\n"
        + "\n".join(found))
    # RC-307: the number moved from 21 to 48 because the SCOPE moved, not because 27
    # scanners appeared. RC-286 counted `(REPO / "tools").glob("*.py")` and the same shape
    # lives 27 more times under tests/ — where it had already turned
    # tests/test_coh_sa2_et_authority.py red on untracked scratch. Both directories are
    # counted from the git index now, so neither can hide the other's drift.
    #
    # 48 -> 44, and how it was found is the point. The RC-307 commit set 48 and its own
    # sibling repair — three rglob sites in tests/test_calibration_bypass_closure.py — had
    # already made it 45, which I did not re-measure; RC-312's index-scoping of the
    # moving-reference sweep took it to 44. Pre-commit does not run this file, so the stale
    # number survived a commit. It did not survive the next run of the alarm, which is what
    # a counted sweep is for: the drift it caught was mine.
    by_dir = {rel.split("/")[0] for rel in found}
    assert by_dir <= {"tools", "tests"}, f"the sweep reached outside its scope: {by_dir}"
    assert "tests/test_coh_sa2_et_authority.py" not in {f.split(":")[0] for f in found}, (
        "the ET-authority scanner is walking the filesystem again (RC-307)")
    assert "tools/anti_pattern_sweep.py" not in {f.split(':')[0] for f in found}, (
        "the gate RC-286 repaired is enumerating the filesystem again")
