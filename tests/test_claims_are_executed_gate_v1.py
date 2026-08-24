"""RC-298 — negative control for the `test_claims_are_executed` enforced check.

THE DEFECT IT GUARDS. tests/test_charm_docstring_states_the_physics_v1.py, as shipped under
RC-294, contained eight assertions and every one read `assert "<a sentence I wrote>" in
DOC`. It confirmed only that the text had been written. The claim it locked — "calls sell,
puts buy" — was FALSE and the suite was green, because a string match cannot disagree with
the string. One call refuted it: `math_levels.bs_charm` takes no call/put argument, and its
sign tracks moneyness. RC-281 and RC-290 are the same shape.

WHAT THIS FILE PROVES. That the checker FIRES on the defect and does not fire on a healthy
file. A gate nobody has attacked is green-and-inert; these are the injected violations.

Note the shape of these tests: every one CALLS `analyse`/`violations` and asserts on the
returned value. A prose-only negative control for a prose-only checker would be the joke
that writes itself.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import check_test_claims_are_executed as C  # noqa: E402

# The RC-294 file, reconstructed: assertions about text, nothing executed.
PROSE_ONLY = '''
import inspect
from foo import bar
DOC = inspect.getdoc(bar)
def test_a():
    assert "SHORT call" in DOC
def test_b():
    assert "SELL stock" in DOC
def test_c():
    assert "BUY stock" in DOC
'''

# The RC-296 replacement: reads text AND runs the subject.
MIXED = '''
import inspect
from math_levels import bs_charm
DOC = inspect.getdoc(bs_charm)
def test_a():
    assert "moneyness" in DOC
def test_b():
    assert "side-independent" in DOC
def test_c():
    assert "OI IMBALANCE" in DOC
def test_runs_it():
    below = bs_charm(100.0, 90.0, 0.08, 0.20, 0.0)
    above = bs_charm(100.0, 105.0, 0.08, 0.20, 0.0)
    assert below > 0 > above
'''


def test_the_checker_fires_on_a_prose_only_file():
    """The injected violation. If this passes silently the gate is inert."""
    prose, calls = C.analyse(ast.parse(PROSE_ONLY))
    assert prose >= 3, f"the prose assertions were not counted: {prose}"
    assert calls == 0, f"a subject call was miscounted in a prose-only file: {calls}"


def test_the_checker_accepts_a_file_that_runs_the_subject():
    """The positive control: text assertions stay legal when the file also executes."""
    prose, calls = C.analyse(ast.parse(MIXED))
    assert prose >= 3
    assert calls > 0, "calling bs_charm was not recognised as exercising the subject"


def test_a_call_outside_the_assert_still_counts():
    """The false positive the first prototype produced, pinned so it cannot return.

    tests/test_pred_1c_horizon_persistence_v1.py calls the subject and THEN asserts on the
    result. Requiring the call inside the assert expression flagged five healthy files.
    """
    src = '''
import inspect
from foo import build
DOC = inspect.getdoc(build)
def test_a():
    assert "x" in DOC
def test_b():
    assert "y" in DOC
def test_c():
    assert "z" in DOC
def test_d():
    d = build(1, 2)
    assert d["k"] == 3
'''
    prose, calls = C.analyse(ast.parse(src))
    assert calls > 0, "a subject call placed before the assertion was not counted"


def test_builtins_do_not_count_as_exercising_the_subject():
    """`len(...)` in an assertion is not evidence the code under test ran."""
    src = '''
import inspect
from foo import bar
SRC = inspect.getsource(bar)
def test_a():
    assert "a" in SRC
def test_b():
    assert "b" in SRC
def test_c():
    assert len(SRC) > 0
'''
    prose, calls = C.analyse(ast.parse(src))
    assert calls == 0, "a builtin was mistaken for exercising the subject"


def test_the_live_repository_passes_on_merit():
    """Zero offenders and zero exemptions consumed — the reason this is ENFORCED, not ratcheted."""
    assert C.violations() == [], f"prose-only test files present: {C.violations()}"
    assert len(C.TEXT_ONLY_ALLOWED) <= 3, (
        "the text-only allowlist is growing; each entry silences a file that cannot detect "
        "a false claim, which is the RC-276 file-exemption habit returning")


def test_every_allowlist_entry_states_a_reason():
    for path, reason in C.TEXT_ONLY_ALLOWED:
        assert path and reason and len(reason) > 20, (
            f"{path} is exempt without a real reason — RC-281 is what unverified reasons do")


def test_the_module_scope_blind_spot_is_measured_not_silent():
    """RC-311: the gate judges FILES; the defect lives in FUNCTIONS. Count what it misses.

    This gate landed ENFORCED and green, and the next day RC-308 found six tests asserting a
    spelling, a count, a byte offset and the absence of a name — every one of them in a file
    this gate passes, because each sits beside a healthy test and the scope is module-wide.
    The widening to module scope was deliberate (the per-function form produced five false
    positives), and this is what it gave up.

    The number is asserted, not enforced at zero: most of the 264 are the inventory, register
    and wiring audits the checker's own docstring defends, and exempting them one by one
    would be the allowlist habit RC-276 removed. Asserting it means the next person who
    widens this gate's scope moves a visible figure instead of extending a silence.

    261 -> 265, accounted for function by function 2026-08-17. Thirteen entries appeared
    and four left; four of the arrivals REPLACE those four (a rename, a two-into-one
    consolidation, and a retitled edge test), leaving ten genuinely new. Each of the ten
    was classified by reading the property it asserts, per the distinction now written
    into the checker's `source_text_only_functions` docstring:

      INHERENTLY STRUCTURAL, retained (4) — a repository property with no faithful
      runtime call: RC-338 policy constants defined exactly once; RC-339 no feature
      formula re-encoded in either builder; the RC-355 lane resolver's WIRING (its
      behaviour is executed in node, which this Python AST scan cannot see); and the
      ML_ITEM4 policy artefact carrying the keys the row claims.

      AVOIDABLE SOURCE-TEXT PROXY, rewritten to assert the behaviour (6) — the delta
      gate's clean-worktree measurement (recorded argv, not the words "worktree"/
      "--detach"); the five-why silence on RC-315 (the checker's VERDICT, not its two
      regexes restated); the lstm_meta/load_lstm boundary (recorded events, not three
      `str.index` offsets); the LSTM edge slot (what the real producer PUBLISHES for a
      val_accuracy-only meta, not a matched call string); and both fetch_price_levels
      carriers (trapped helper modules and a no-fetch client, not name scans).

    Five of those six left the count. The sixth — the five-why control — still scores as
    source-text because its computed verdict takes a file-derived argument and the taint
    follows the argument; that coarseness is documented in the checker, and loosening it
    was tried and reverted rather than bent to move this number.

    265 -> 264 (RC-400), one entry, named: `test_rc250_advisory_never_returns_to_the_
    blocking_commit_path` LEFT. It asserted the literal "--enforced-only" in the pre-commit
    seam's source, which RC-391 had made an address rather than a property; RC-395 rewrote
    it to record the seam's actual subprocess launch and assert that no advisory work runs
    on the blocking path. Asserting the behaviour is exactly what removes an entry from
    this census, so the figure fell on its own — nothing was re-baselined to reach it, and
    no entry arrived.

    264 -> 265 (RC-292 GAMMA PIN SSOT), one entry, named:
    `test_pin_score_and_snapshot_use_terrain_ssot_pin_not_consensus_net` ARRIVED.
    INHERENTLY STRUCTURAL: the pin_score strike and snapshot persist must not read
    `getattr(consensus_summary, "gamma_pin")` (analytics net-GEX peak). That is a
    producer-string property of server.py; driving `_fetch_state` would need a live
    chain and would not name the deleted getattr. Overlay overwrite of payload
    `gamma_pin` is asserted as behaviour in
    `test_overlay_overwrites_payload_gamma_pin_with_terrain_total` and does not
    enter this census.

    265 -> 266 (F15 today_poc live path), one entry, named:
    `test_console_today_poc_binds_state_payload_not_a_second_book` ARRIVED.
    INHERENTLY STRUCTURAL: #dr-lvl-poc/#exec-poc (and VAH/VAL) must exist and bind
    `d.today_*` on both painters. That is markup/wiring; a live `/api/state` cycle
    cannot prove the DOM ids are the ones named in the F15 port. The stamp itself
    is asserted by extending `test_state_level_family_serves_raw_not_rounded`
    (already in the census) and does not add a function.

    266 -> 267 (RC-453 CODEOWNERS rails), one entry, named:
    `test_codeowners_covers_control_authority_set` ARRIVED.
    INHERENTLY STRUCTURAL: `.github/CODEOWNERS` must name the control-authority
    paths and must not name routine product (`/server.py`). That is a repository
    ownership map; no runtime call can express which paths GitHub will treat as
    owned. Behaviour of the assignment lock is executed in
    `tests/test_control_authority_surfaces_v1.py` and does not add this entry.

    267 -> 268 (Architecture A external PM authority, PR #181), one net arrival, named:
    `test_install_script_refuses_untrusted_checkout_and_smoke_tests` ARRIVED.
    INHERENTLY STRUCTURAL: `tools/install_pm_authority_host.sh` is a host-side shell
    script run as root off-repo; its hardening — hash-verify against an operator pin,
    self-containment smoke test, `env_reset` sudoers, no `NOPASSWD: ALL` — cannot be
    exercised by any Python runtime call in this environment, exactly like the
    CODEOWNERS ownership-map entry above. The candidate also briefly carried
    `test_helper_source_is_not_claimed_as_the_boundary`; it was REMOVED as a redundant
    source-text proxy because every security property it touched is asserted
    behaviorally (self-containment / stdin-only / non-isolated refusal), so the
    behaviour is asserted and that entry leaves the census on its own — net +1.

    268 -> 269 (RC-459 Windows host boundary), one net arrival, named:
    `test_windows_installer_moves_ownership_away_from_the_ai` ARRIVED.
    INHERENTLY STRUCTURAL: it asserts that `tools/install_pm_authority_host.ps1`
    ASSIGNS OWNERSHIP of the authority objects to the BUILTIN Administrators group
    SID S-1-5-32-544) and grants the AI account ReadAndExecute only. Ownership
    assignment is an ELEVATED Windows operation against a host path; no runtime call
    in this environment can execute it — CI runs unelevated on Linux, where the
    Win32 security APIs do not exist at all — exactly like the CODEOWNERS ownership-map
    and the POSIX installer entries above. The property is also not optional: MEASURED
    on the real host 2026-08-23, a read-only grant alone left `icacls <dir> /grant
    <ai>:(F)` SUCCEEDING because an OWNER always retains WRITE_DAC, so ownership is the
    load-bearing fact and a source assertion is the only way to pin it in CI.
    The ACCESS half of the same boundary IS asserted behaviorally (real `icacls` +
    real denied writes/deletes/renames) in
    `test_windows_negative_controls_read_only_authority`, and the authorized-mutation
    path in `test_windows_operator_authorized_mutation_succeeds`; both execute the
    behaviour and therefore do NOT enter this census.
    269 -> 267 (RC-461 simplification), TWO net departures, both REPAIRS - the count
    falls because the source-text proxies left with the architecture they described:
    `test_install_script_refuses_untrusted_checkout_and_smoke_tests` DEPARTED and
    `test_windows_installer_moves_ownership_away_from_the_ai` DEPARTED, because
    tests/test_pm_authority_external_v1.py and
    tests/test_pm_authority_windows_boundary_v1.py were DELETED along with the OS
    capability boundary, privileged helper and host installers they asserted. The
    operator ruled that architecture overbuilt: no OS sandbox, no separate account, no
    ProgramData authority service, no host provisioning. With no host artifact to
    describe there is no source text to inspect, so both entries leave the census on
    their own - the RC-308 preferred direction. No behaviour was lost with them: what
    the repo still promises (operator-controlled assignment, metadata grants nothing,
    no self-promotion, ordinary product autonomous) is asserted BEHAVIOURALLY through
    the live rail in tests/test_control_authority_surfaces_v1.py,
    tests/test_architecture_a_operator_writer_authority_v1.py and
    tests/test_writer_drift_lock_v1.py, none of which enter this census.
    `test_codeowners_covers_control_authority_set` REMAINS (its line moved only): the
    CODEOWNERS ownership map is still inherently structural - no runtime call can
    express which paths GitHub will treat as owned.

    267 -> 268 (RC-466 delta-gate base cache), one arrival, named:
    `test_rc466_candidate_side_is_never_cached` ARRIVED.
    INHERENTLY STRUCTURAL: it asserts the ABSENCE of a cache branch around the
    candidate-side measurement in the delta gate's main() - that the candidate is
    measured unconditionally, never served from cache. A runtime call cannot prove a
    negative of this shape: no cache key is ever derived for the candidate, so there is
    no hit one could construct to observe behaviourally; only the source structure
    carries the property. The cache's BEHAVIOUR (roundtrip, stale-key miss, corruption
    fail-open, key sensitivity) IS asserted behaviourally by the four sibling RC-466
    tests in the same suite, which do not enter this census.

    268 -> 269 (RC-468 declared-retirement seam in the delta gate), one arrival, named:
    `test_rc468_declaration_only_touches_removal_accounting` ARRIVED.
    INHERENTLY STRUCTURAL: it asserts that in the delta gate's main() the retirement
    manifest is read exactly once and flows ONLY into removal accounting
    (split_removals), never into the counts comparison - the ABSENCE of any second
    consumer. A runtime call cannot prove that negative: there is no input one could
    feed compare() to observe a manifest influence that structurally does not exist;
    only the call graph carries the property, exactly like the RC-466 candidate-cache
    entry above. The mechanism's BEHAVIOUR (parser rows, undeclared-removal blocking,
    fail-closed missing manifest) IS asserted behaviourally by the three sibling
    RC-468 tests in the same suite, which do not enter this census.
    """
    fns = C.source_text_only_functions()
    assert len(fns) == 269, (
        f"the per-function source-text-only count moved from the 269 measured on "
        f"2026-08-24 (RC-468) to {len(fns)}. This figure is not a defect count, so do not simply "
        f"re-baseline it. ACCOUNT for the move: name each function that arrived or left. "
        f"An arrival stays only if its property is INHERENTLY STRUCTURAL — uniqueness, "
        f"duplication or absence in the repository, which no runtime call can express. If "
        f"the property is behaviour, assert the behaviour and the entry leaves on its own; "
        f"that is RC-308. If you REPAIRED some, lower this number and say so in the row.\n"
        + "\n".join(fns[:20]))
    # The two RC-308 repairs that became executable in PYTHON are out of the list and must
    # stay out. The other four kept a source-text half on purpose — a correct function nobody
    # calls paints nothing, so the WIRING stays a source check — and moved their behavioural
    # half into node harnesses, which this Python-AST scan cannot see. Naming them here is
    # the honest form: two left the list, four did not, and the four are accounted for.
    names = {f.rsplit(" ", 1)[-1] for f in fns}
    for gone in ("test_accumulator_rejects_a_nonpositive_price_at_the_service_boundary",
                 "test_terrain_level_set_includes_new_levels_each_with_tooltip"):
        assert gone not in names, f"{gone} went back to asserting only source text (RC-308)"
    for harness in ("tests/index_html_contracts_node.mjs",
                    "tests/forces_provenance_node.mjs"):
        assert (REPO / harness).exists(), (
            f"{harness} is gone, so the behavioural half of the RC-308 repairs it holds is "
            "gone with it and the surviving source checks stand alone")


def test_the_gate_is_registered_as_enforced():
    """A rule nobody calls is a comment."""
    src = (REPO / "tools" / "check_institutional_correctness.py").read_text(
        encoding="utf-8", errors="replace")
    assert '("test_claims_are_executed", check_test_claims_are_executed, True)' in src, (
        "the check is not registered ENFORCED in the institutional gate")
