# institutional-synthetic-ok: these tests INJECT violations to prove checks can fail — that is
# their entire purpose (RC-95); every injection is restored in a finally block.
"""RC-95: negative controls for the ENFORCED checks that had none.

Four instruments shipped INERT in one session (RC-76, RC-84, RC-87, RC-90) — each reported 0
violations while incapable of firing, and green-and-inert is byte-identical to green-and-working.
The only discriminator is a control that injects the defect and demands the check scream. This
file is that control for verdicts_declare_their_power (folded into measured_claims_cite_evidence),
single_spot_authority, ui_data_integration, and several ledger validators.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.check_institutional_correctness as C  # noqa: E402

# RC-368: declared direct owner — the negative-control battery drives the guard's
# action clauses (test_operator_law_guard_action_battery).
TURN_AUDIT_OWNS = [
    "tools/operator_law_guard.py",
]



# BEDROCK 2026-09-06: the verdict-power controls left with the verdict-power fold — it
# matched KILL/RETIRED/PROVEN words in prose and demanded n=/CI tokens beside them, which
# AGENTS.md rules out as enforcement. The evidence substance (a numeric finding cites its
# reproduce command) is exercised by test_citation_check_* below.


def test_spot_authority_check_is_alive_on_the_real_tree():
    """single_spot_authority guards the RC-14 law. Full source injection is expensive, so this
    control asserts the check RUNS and returns a list on the real tree, and that the authority it
    guards (resolve_spot) is still present for it to guard — a deleted authority with a silent
    check is exactly the inert-instrument shape."""
    v = C.check_single_spot_authority()
    assert isinstance(v, list)
    assert "def resolve_spot" in (ROOT / "server.py").read_text(encoding="utf-8"), (
        "resolve_spot is gone; the spot-authority check is guarding nothing"
    )


def test_ui_data_integration_tier1_screams_on_a_dead_placeholder(tmp_path, monkeypatch):
    """Tier 1 of ui_data_integration: a data cell shipped as '—' with NO JS writer must fail."""
    from tools import check_ui_data_integration as U
    fake = tmp_path / "static"
    fake.mkdir()
    # Tier 1 scans the fixed _HTML_FILES paths and only ids with the known cell prefixes
    # (cv2|ct|dr|kl|hd) — the injected cell must be one the check actually polices.
    (fake / "index.html").write_text(
        '<span id="cv2-zz-dead">—</span><script>var x = 1;</script>',
        encoding="utf-8")
    monkeypatch.setattr(U, "REPO", tmp_path)
    bad = U.static_binding_violations()
    assert bad, "a '—' placeholder with no writer anywhere was not flagged — Tier 1 is inert"



def test_rc_citation_check_screams_on_a_phantom_id(tmp_path, monkeypatch):
    """RC-99: an RC-N in source with no log row must be flagged.

    This check found EIGHT live phantoms on first run — including its own docstring citing
    RC-99 — after the operator's audit found two by hand. It is the lock for the class where
    RC-96 recurred as RC-98 within a single turn."""
    from tools import check_institutional_correctness as M
    fake = tmp_path
    (fake / "governance").mkdir()
    (fake / "governance" / "root_cause_log.md").write_text(
        "| RC-1 | CLOSED | 2026-01-01 | 2026-01-08 | w | y | f |\n", encoding="utf-8")
    (fake / "tools").mkdir()
    (fake / "tools" / "zz_probe.py").write_text('"""cites RC-4242 which does not exist."""\n',
                                                encoding="utf-8")
    monkeypatch.setattr(M, "REPO", fake)
    bad = M.check_rc_citations_resolve()
    assert any("RC-4242" in str(b) for b in bad), (
        "a phantom RC citation in source was not flagged — the check is inert"
    )


def test_rc_citation_check_accepts_a_resolvable_id(tmp_path, monkeypatch):
    from tools import check_institutional_correctness as M
    fake = tmp_path
    (fake / "governance").mkdir()
    (fake / "governance" / "root_cause_log.md").write_text(
        "| RC-4242 | CLOSED | 2026-01-01 | 2026-01-08 | w | y | f |\n", encoding="utf-8")
    (fake / "tools").mkdir()
    (fake / "tools" / "zz_probe.py").write_text('"""cites RC-4242 which DOES exist."""\n',
                                                encoding="utf-8")
    monkeypatch.setattr(M, "REPO", fake)
    assert not [b for b in M.check_rc_citations_resolve() if "RC-4242" in str(b)]


def test_inert_producer_check_screams_on_a_fatal_run_log(tmp_path, monkeypatch):
    """RC-97: a scheduled producer whose log ends in a fatal has been failing silently.

    A fail-closed CONSUMER hides this — it withholds the stale artifact and the system merely
    looks quiet. Measured 2026-07-27: the scorecard artifact was 119.4h old behind exactly this."""
    from tools import check_institutional_correctness as M
    fake = tmp_path
    (fake / "reports").mkdir()
    (fake / "reports" / "zzjob_run.log").write_text(
        "starting\nFatal Python error: preconfig_init_utf8_mode\n", encoding="utf-8")
    monkeypatch.setattr(M, "REPO", fake)
    assert M.check_scheduled_producers_are_not_inert(), "a fatal run log was not flagged"


def test_inert_producer_check_accepts_a_healthy_run_log(tmp_path, monkeypatch):
    from tools import check_institutional_correctness as M
    fake = tmp_path
    (fake / "reports").mkdir()
    (fake / "reports" / "zzjob_run.log").write_text(
        "[job] start\nwrote artifact\n[job] exit=0\n", encoding="utf-8")
    monkeypatch.setattr(M, "REPO", fake)
    assert not M.check_scheduled_producers_are_not_inert()


def test_price_bars_session_check_screams_on_an_ungated_reader(tmp_path, monkeypatch):
    """RC-103: a NEW ungated price_bars_1m reader must be flagged; a gated one must pass."""
    from tools import check_institutional_correctness as M
    fake = tmp_path
    (fake / "tools").mkdir()
    (fake / "research").mkdir()
    (fake / "tools" / "zz_bar_probe.py").write_text(
        'q = "SELECT close FROM price_bars_1m WHERE ticker=?"\n', encoding="utf-8")
    monkeypatch.setattr(M, "REPO", fake)
    bad = M.check_price_bars_readers_name_their_session()
    assert any("zz_bar_probe" in str(b) for b in bad), "an ungated bar reader was not flagged"
    (fake / "tools" / "zz_bar_probe.py").write_text(
        'from time_et import is_trading_day_et\n'
        'q = "SELECT close FROM price_bars_1m WHERE ticker=?"\n', encoding="utf-8")
    assert not [b for b in M.check_price_bars_readers_name_their_session()
                if "zz_bar_probe" in str(b)], "a gated reader was wrongly flagged"


def test_rc_log_row_schema_control(tmp_path, monkeypatch):
    """RC-105: an off-schema row (interior pipe) must be flagged; a 7-cell row must pass."""
    from tools import check_institutional_correctness as M
    fake = tmp_path
    (fake / "governance").mkdir()
    log = fake / "governance" / "root_cause_log.md"
    good = "| RC-900 | CLOSED | 2026-07-28 | 2026-07-28 | desc | whys | evidence |"
    bad = "| RC-901 | CLOSED | 2026-07-28 | 2026-07-28 | desc | whys | ev with |pipe| bars |"
    log.write_text(good + "\n" + bad + "\n", encoding="utf-8")
    monkeypatch.setattr(M, "REPO", fake)
    hits = M.check_rc_log_rows_keep_schema()
    assert len(hits) == 1 and "9 cells" in str(hits[0]), (
        f"the 9-cell row was not flagged (or the clean row was): {hits}"
    )
    log.write_text(good + "\n", encoding="utf-8")
    assert M.check_rc_log_rows_keep_schema() == [], "a clean 7-cell log must pass"


# RC-470: the close-contract controls (test_close_contract_controls and
# test_close_contract_deferral_matches_whole_words_only) left with their validator
# (_five_why_lock_violations, retired - governance/retired_checks.md).


def test_operator_law_guard_action_battery():
    """v19: the fire/quiet battery, promoted from ad-hoc probes to a permanent suite. Every
    banned ACTION spelling must fire; every sanctioned form must stay quiet — one list, both
    directions, so widening a lock reruns the whole surface."""
    from pathlib import Path as _P

    from tools.operator_law_guard import bash_violations, normalize_repo
    # RC-258: proof is now bound to the repository it ran against, and the target repository is
    # resolved from the caller's working directory. This battery drives the pure callee, so it
    # supplies both exactly as the hook does — the SPELLINGS under test are unchanged.
    _repo = _P(__file__).resolve().parent.parent
    _cwd = str(_repo)
    led = [{"kind": "bash", "detail": "pytest ok", "repo": normalize_repo(_repo)}]
    fire = [
        "git add -A", "git add --all", "git add .", "git add -u", "git add *", "git add -- .",
        "python - <<EOF\nio.open('tests/x.py','w').write(s)\nEOF",
        "python - <<EOF\nopen('tools/x.py', 'w').write(s)\nEOF",
        "python - <<EOF\nfrom pathlib import Path\nPath('tests/x.py').write_text(s)\nEOF",
        "python - <<EOF\nPath('tools/x.py').open('w').write(s)\nEOF",   # v19
        "cat > foo.py <<EOF\nx = 1\nEOF",                               # v19: shell redirect
        "echo 'x = 1' > tools/probe.py",
    ]
    quiet = [
        "git add server.py tools/x.py", "git add -- server.py",
        "git commit -m \"note: git add -A and open(x.py,w) are banned\"",
        "python - <<EOF\nio.open('governance/root_cause_log.md','w').write(s)\nEOF",
        "python - <<EOF\nPath('reports/out.json').write_text(s)\nEOF",
        "python x.py > reports/run.log 2>&1",
        "pytest tests/test_x.py -q",
    ]
    for c in fire:
        assert bash_violations(c, led, _cwd), f"DID NOT FIRE: {c[:60]!r}"
    for c in quiet:
        assert not bash_violations(c, led, _cwd), f"WRONGLY FIRED: {c[:60]!r}"


# RC-470: test_stop_guard_freshness_tells_broken_from_closed left with the guard's
# freshness duty (removed - see tools/stop_guard.py and governance/retired_checks.md).


def test_gate_reader_survives_a_vanished_file(tmp_path):
    """RC-116: a file that vanishes between glob and read is EMPTY to the gate, not a crash —
    two agents share this worktree and a crashed gate protects nothing."""
    from tools.check_institutional_correctness import _read_or_empty
    assert _read_or_empty(tmp_path / "never_existed.py") == ""
    real = tmp_path / "real.py"
    real.write_text("x = 1", encoding="utf-8")
    assert _read_or_empty(real) == "x = 1"


def test_audit_answer_check_control(tmp_path, monkeypatch):
    """RC-118: an audit file with no ledger citation must fire; a cited one must pass."""
    from tools import check_institutional_correctness as M
    (tmp_path / "reports").mkdir()
    (tmp_path / "governance").mkdir()
    (tmp_path / "reports" / "claude_finish_adversarial_audit_v99.md").write_text("x", encoding="utf-8")
    log = tmp_path / "governance" / "root_cause_log.md"
    log.write_text("| RC-1 | CLOSED | 2026-01-01 | 2026-01-01 | d | w | f |" + chr(10), encoding="utf-8")
    monkeypatch.setattr(M, "REPO", tmp_path)
    assert M.check_adversarial_audits_are_answered(), "an unanswered audit was not flagged"
    log.write_text("| RC-1 | CLOSED | 2026-01-01 | 2026-01-01 | d | w | audit v99 processed |" + chr(10), encoding="utf-8")
    assert M.check_adversarial_audits_are_answered() == [], "a cited audit was wrongly flagged"


# RC-504 (operator 2026-09-02): test_defect_report_requires_probe_artifact was REMOVED with
# `defect_report_needs_probe`. It matched a word list — "not work", "broken", "went dark",
# "blank screen" — against the OPERATOR's own message to decide whether a reply owed a probe.
# That is prose deciding enforcement, and it went with the rest of proof_only_guard once the
# approach was experimentally confirmed to false-block a denial. The substance it aimed at —
# measure the live system before explaining it — survives as an instruction in AGENTS.md, the
# honest home for a rule no machine can decide. No successor check was built.


def _citation_row(evidence: str) -> str:
    """A 7-cell ledger row whose fix cell carries `evidence` beside four numeric claims.
    RC-900 is outside the grandfathered range, so the citation rule binds it."""
    return ("| RC-900 | CLOSED | 2026-07-28 | 2026-07-28 | desc | a -> b -> c -> d -> ROOT: e | "
            f"reclaimed 0.25 GB across 1,328 rows in 42 s over 3 tables. {evidence} |")


def test_citation_check_fires_when_numbers_carry_no_command(tmp_path, monkeypatch):
    """RC-136 FIRE control: the rule's strength must be untouched by the allowlist widening —
    numeric claims with no backticked command still fail, and a backticked span that is PROSE
    rather than a command still fails (otherwise `any text` would buy a free pass)."""
    from tools import check_institutional_correctness as M
    (tmp_path / "governance").mkdir()
    log = tmp_path / "governance" / "root_cause_log.md"
    monkeypatch.setattr(M, "REPO", tmp_path)

    log.write_text(_citation_row("Verified by careful review.") + "\n", encoding="utf-8")
    assert len(M.check_rc_numeric_claims_cite_a_command()) == 1, (
        "numbers with no citation were not flagged — the rule went inert"
    )
    log.write_text(_citation_row("Verified `by careful review`.") + "\n", encoding="utf-8")
    assert len(M.check_rc_numeric_claims_cite_a_command()) == 1, (
        "backticked PROSE satisfied the citation rule — any text would buy a free pass"
    )


def test_citation_check_accepts_the_repos_live_probe_forms(tmp_path, monkeypatch):
    """RC-136 QUIET control: the operator's RC-125 live-probe law is curl-shaped, and a python
    urllib probe is the same evidence in another idiom. Both must satisfy the rule — measured
    2026-07-29, a true curl citation on RC-134 was rejected and the evidence had to be reworded
    to pass, which is the citation theater this rule exists to prevent."""
    from tools import check_institutional_correctness as M
    (tmp_path / "governance").mkdir()
    log = tmp_path / "governance" / "root_cause_log.md"
    monkeypatch.setattr(M, "REPO", tmp_path)

    for evidence in (
        'Measured by `curl -s "http://127.0.0.1:8000/api/terrain?ticker=SPY"`.',
        "Measured by `python -c \"import urllib.request; "
        "print(urllib.request.urlopen('http://127.0.0.1:8000/api/health').status)\"`.",
        "Measured by `SELECT COUNT(*) FROM snapshots`.",
        "Measured by `python -m pytest tests/test_terrain_engine_v1.py -q`.",
    ):
        log.write_text(_citation_row(evidence) + "\n", encoding="utf-8")
        assert M.check_rc_numeric_claims_cite_a_command() == [], (
            f"a re-runnable citation was rejected — false reject remains: {evidence}"
        )


def test_closed_row_must_ship_its_code_controls():
    """RC-137: a CLOSED row must not name FIXED source files that are still dirty.

    FIRE on the exact shape that shipped: RC-134 was committed CLOSED naming terrain_engine.py
    while that file sat uncommitted, so HEAD still had `hvl=pick_hvl_strike` while the ledger
    said otherwise. QUIET on the three legitimate shapes, or the check would block honest
    commits in a shared worktree."""
    import inspect

    from tools.check_institutional_correctness import CHECKS
    from tools.check_institutional_correctness import _closed_row_code_not_shipped as V
    from tools.check_institutional_correctness import _root_cause_ledger_folded_violations

    # Consolidated 2026-08-24 (governance/retired_checks.md): the substance is ENFORCED
    # through root_cause_log, whose fold table must still run this validator's helper.
    assert ("root_cause_log", True) in [(n, e) for n, _f, e in CHECKS], (
        "root_cause_log is not registered ENFORCED — an unregistered check cannot block anything"
    )
    assert "_closed_rows_ship_their_code_violations" in inspect.getsource(
        _root_cause_ledger_folded_violations), (
        "closed_rows_ship_their_code's validation is no longer folded into root_cause_log — "
        "the substance was dropped, not consolidated"
    )

    def row(status, fix):
        return (f"| RC-134 | {status} | 2026-07-29 | 2026-08-01 | desc | "
                f"a -> b -> c -> d -> ROOT: e | {fix} |")

    fixed = "FIXED: terrain_engine.py, server.py (Tier-C kwargs)."

    hits = V([row("CLOSED", fixed)], {"terrain_engine.py", "server.py"})
    assert len(hits) == 1 and hits[0][0] == "RC-134", f"the RC-134 shape did not fire: {hits}"
    assert hits[0][1] == ["server.py", "terrain_engine.py"], (
        f"the violation must name the exact unshipped files: {hits}"
    )

    # QUIET 1 — the fix ships in this commit: nothing dirty AND the files are staged.
    # (Under RC-139 "nothing dirty" alone is NOT quiet — a clean tree is not evidence.)
    assert V([row("CLOSED", fixed)], set(),
             staged={"server.py", "terrain_engine.py"}) == [], "a shipped fix was flagged"
    # QUIET 2 — the row is not CLOSED yet; work in progress may leave files dirty.
    assert V([row("PARTIAL", fixed)], {"terrain_engine.py"}) == [], "a non-CLOSED row fired"
    # QUIET 3 — churny evidence artifacts are not "the fix": a row that ships real source may
    # also cite a report that daily runs leave dirty, and that must not block the commit.
    # (RC-140 note: a row naming ONLY a report now fires as an unverifiable claim — correct,
    # since no source is named; the guarantee preserved here is that report churn ALONE
    # cannot block a closure that does ship code.)
    assert V([row("CLOSED", "FIXED: terrain_engine.py; evidence in "
                            "reports/terrain_backtest_latest.json")],
             {"reports/terrain_backtest_latest.json"},
             staged={"terrain_engine.py"}) == [], (
        "a dirty report artifact fired — daily runs would block every ledger commit"
    )


def test_closed_row_cannot_close_on_an_empty_tree():
    """RC-139 (escape v30 measured in RC-137's first cut): keying only on DIRTY files let the
    worst shape through — a row CLOSED with a CLEAN worktree, because the fix was never written
    or was reverted to HEAD. A clean tree reads identically either way, so a NEW closure must
    ship its files or cite the commit that carried them."""
    from tools.check_institutional_correctness import _closed_row_code_not_shipped as V

    def row(status, fix, rc="RC-950"):
        return (f"| {rc} | {status} | 2026-07-29 | 2026-08-01 | desc | "
                f"a -> b -> c -> d -> ROOT: e | {fix} |")

    fixed = "FIXED: terrain_engine.py."
    closed, was_open = row("CLOSED", fixed), row("PARTIAL", fixed)

    # FIRE — the v30 escape: newly CLOSED, nothing dirty, nothing staged, no SHA cited.
    hits = V([closed], set(), removed_rows=[was_open], staged=set())
    assert len(hits) == 1 and hits[0][1] == ["terrain_engine.py"], (
        f"a closure with no shipped code and a clean tree went undetected: {hits}"
    )
    # ...and a brand-new row (no prior version at all) is the same claim.
    assert V([closed], set(), removed_rows=[], staged=set()), "a brand-new CLOSED row escaped"

    # QUIET 1 — the fix ships in this very commit.
    assert V([closed], set(), removed_rows=[was_open],
             staged={"terrain_engine.py"}) == [], "a closure carrying its fix was flagged"

    # QUIET 2 — the fix landed earlier and the row points at that commit.
    cited = row("CLOSED", "FIXED: terrain_engine.py — landed in 1a384d0b.")
    assert V([cited], set(), removed_rows=[was_open], staged=set(),
             sha_touches=lambda sha, rel: sha == "1a384d0b" and rel == "terrain_engine.py") == [], (
        "a closure citing the commit that carried the fix was flagged"
    )
    # ...but a cited SHA that did NOT touch the file must not launder the claim.
    assert V([cited], set(), removed_rows=[was_open], staged=set(),
             sha_touches=lambda _sha, _rel: False), "an unrelated SHA laundered an empty closure"

    # QUIET 3 — a text edit to a row that was ALREADY closed cannot re-litigate old history.
    assert V([closed], set(), removed_rows=[closed], staged=set()) == [], (
        "editing a long-closed row's prose was treated as a new closure claim"
    )


# RC-470: test_close_contract_deferral_matches_whole_words_only removed with its
# validator (see the note beside the close-contract controls above).


def test_closed_row_semantics_escapes_are_closed():
    """RC-140 (v31): the lock bound path TOKENS it recognized, not the CLAIM that a fix exists.
    Three measured escapes — a prose-only FIXED claim, a fix in an unlisted language, and a
    'touched' file that was never really changed — all read as compliant."""
    from tools.check_institutional_correctness import _UNNAMED_FIX
    from tools.check_institutional_correctness import _closed_row_code_not_shipped as V

    def row(fix, rc="RC-960", status="CLOSED"):
        return (f"| {rc} | {status} | 2026-07-29 | 2026-08-01 | desc | "
                f"a -> b -> c -> d -> ROOT: e | {fix} |")

    # FIRE 1 — prose-only claim: nothing machine-readable to verify.
    hits = V([row("FIXED: the overlay now owns the whole level set.")], set(), staged=set())
    assert len(hits) == 1 and hits[0][1] == [_UNNAMED_FIX], (
        f"a FIXED claim naming no checkable path was graded compliant: {hits}"
    )
    # QUIET — a closure that HONESTLY changes no code says so.
    assert V([row("FIXED: no code change — disposition only, the radar stays as declared.")],
             set(), staged=set()) == [], "an explicit no-code closure was blocked"

    # FIRE 2 — extensions beyond py/html/js must be checkable too (v31 used .ts / .css).
    for path in ("static/app.ts", "static/theme.css", "tools/deploy.ps1", "db/migrate.sql"):
        hits = V([row(f"FIXED: {path}")], set(), staged=set())
        assert len(hits) == 1 and hits[0][1] == [path], (
            f"a fix named in {path} was invisible to the lock: {hits}"
        )
        assert V([row(f"FIXED: {path}")], set(), staged={path}) == [], (
            f"{path} staged with its row should be quiet"
        )

    # FIRE 3 — 'touched != fixed': a cited SHA that changed nothing real must not satisfy it.
    cited = row("FIXED: static/app.ts — landed in deadbee.")
    assert V([cited], set(), staged=set(),
             sha_touches=lambda _s, _r: False), "a no-real-change commit satisfied the closure"
    assert V([cited], set(), staged=set(),
             sha_touches=lambda _s, _r: True) == [], "a real cited change should be quiet"

    # FIRE 4 (RC-141, v32) — the obligation attaches to CLOSING, not to the word "FIXED".
    # Keying on that token meant a closure could simply omit it: the same omit-the-watched-
    # token escape the prose case was supposed to end.
    no_token = V([row("See VERIFIED below; the behaviour is correct now.")], set(), staged=set())
    assert len(no_token) == 1 and no_token[0][1] == [_UNNAMED_FIX], (
        f"a closure that never says FIXED slipped through: {no_token}"
    )
    # ...and the honest disposition-only closure still passes by SAYING it changed no code.
    assert V([row("Disposition only — the radar fallback stays as declared, no code change.")],
             set(), staged=set()) == [], "an explicit no-code closure was blocked"


# ── RC-246 (P1): the blocking path runs ENFORCED only; advisory still RUNS and is recorded ──


def test_rc246_precommit_path_excludes_advisory_checks():
    """The blocking gate must not pay for verdicts that cannot veto.

    Advisory checks print and return 0 by construction, so charging every commit for them
    (153s of a 244s wall) bought nothing and made the gate expensive enough to route around —
    a cost this repo already paid in piped commits and hooks killed mid-run.

    RC-391 moved WHERE the flag is passed without changing the property: the seam now
    delegates its verdict to tools/check_delta_adds_no_debt.py, which is what runs the gate
    — with --enforced-only — on each side. This control follows the seam rather than
    asserting a literal at an address that has moved, and still fails if any link in the
    chain starts paying for verdicts that cannot veto.
    """
    import tools.check_institutional_correctness as gate

    tools_dir = Path(gate.__file__).parent
    seam = (tools_dir / "precommit_institutional.py").read_text(encoding="utf-8")
    decider = "check_delta_adds_no_debt.py"
    if decider in seam:
        src = (tools_dir / decider).read_text(encoding="utf-8")
    else:
        src = seam
    assert '"--enforced-only"' in src, (
        "the pre-commit blocking path no longer asks for the enforced-only path (RC-246)"
    )


