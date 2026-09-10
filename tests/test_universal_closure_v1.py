"""UNIVERSAL_QUANTITATIVE_CLOSURE_AND_NON_BYPASS_V1 — the adversarial controls (NC-01..NC-21).

Every negative control here is paired with its honest positive (NC-21): a gate that only
blocks is as broken as one that only passes. The subjects are the ONE acceptance authority
(governance/acceptance.py) and the trusted judge (tools/check_delta_adds_no_debt.py
--trusted); the GitHub-side controls (NC-11 same-name status spoof, the credential
boundary) are behavioural experiments recorded in governance/root_cause_log.md RC-539 —
no repository test can perform them.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance import acceptance as A  # noqa: E402


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GATE = _load("tools/check_delta_adds_no_debt.py", "_gate_under_test")
OLG = _load("tools/operator_law_guard.py", "_olg_under_test")


# ── contract helpers ───────────────────────────────────────────────────────────────────
def row(rid, kind, gate, scope, proof, parent="-", crit="criterion"):
    return f"| {rid} | {kind} | {gate} | {scope} | {proof} | {parent} | {crit} |"


def contract(*rows: str) -> str:
    return textwrap.dedent("""
    # spec
    ## Requirements (machine-read)
    | ID | KIND | GATE | SCOPE | PROOF | PARENT | CRITERION |
    |---|---|---|---|---|---|---|
    """) + "\n".join(rows) + "\n\n## Open acceptance items\n"


def _obl(status, detail=""):
    return {"status": status, "detail": detail}


def _verdict(verdicts, rid):
    return next(v for v in verdicts if v.requirement.id == rid)


# ── NC-01 finite subset: N-1 proven is NOT complete ────────────────────────────────────
def test_nc01_finite_subset_is_not_proven_and_full_population_is(tmp_path):
    base = A.parse_contract(contract(row("REQ-A", "FINITE", "MERGE", "delta:a", "STATIC")))
    pop = ["o1", "o2", "o3"]
    partial = {"REQ-A": {"canonical": pop, "obligations": {"o1": _obl("PROVEN"), "o2": _obl("PROVEN")}}}
    v = _verdict(A.evaluate(tmp_path, base, base_contract=base, injected=partial), "REQ-A")
    assert v.verdict == "NOT_PROVEN" and v.missing == 1 and v.proven == 2 and len(v.canonical) == 3
    full = {"REQ-A": {"canonical": pop, "obligations": {o: _obl("PROVEN") for o in pop}}}
    v = _verdict(A.evaluate(tmp_path, base, base_contract=base, injected=full), "REQ-A")
    assert v.verdict == "PASS" and v.missing == 0 and v.proven == 3


# ── NC-02 / NC-04: a sentinel or locally enumerated population is refused ──────────────
def test_nc02_nc04_only_registered_canonical_authorities_enumerate(tmp_path):
    base = A.parse_contract(contract(
        row("REQ-S", "FINITE", "PRODUCT", "tests.fake:sentinels", "STATIC"),
        row("REQ-N", "FINITE", "PRODUCT", "NONE", "STATIC"),
        row("REQ-D", "FINITE", "MERGE", "delta:only_the_gate", "STATIC")))
    vs = A.evaluate(tmp_path, base, base_contract=base)
    for rid in ("REQ-S", "REQ-N", "REQ-D"):
        v = _verdict(vs, rid)
        assert v.verdict == "NOT_PROVEN" and not v.authority_resolved, rid
    with pytest.raises(LookupError):
        A.resolve_scope("tests.fake:sentinels", tmp_path)
    with pytest.raises(LookupError):
        A.resolve_scope("delta:only_the_gate", ROOT)
    # honest positive: the judged tree's own owner enumerates the real population
    assert len(A.resolve_scope("tools.precommit_institutional:enforced_roster", ROOT)) >= 30
    assert set(A.resolve_scope("tools.check_ui_data_integration:page_status", ROOT)) >= {"static/index.html", "static/chart.html"}


# ── NC-03 open-domain allowlist: a local narrowing is FAIL even when samples pass ──────
def test_nc03_local_narrowing_fails_an_open_requirement_and_clean_is_never_proof(tmp_path, monkeypatch):
    req = A.Requirement("REQ-O", "OPEN", "PRODUCT", "narrowing:x", "STATIC", "-", "", 0)
    v = A.Verdict(req, "OPEN", "narrowing:x", True, canonical=["inv"], obligations={"inv": A.ObligationResult("PROVEN")},
                  adversarial_run=5, adversarial_caught=5)
    assert v.verdict == "PASS"
    v.narrowing_violations = ["tools/liquidity_x.py:3 --tickers default is SPY-only"]
    assert v.verdict == "FAIL"
    v.narrowing_violations = []
    v.authority_resolved = False       # no boundary authority: clean is NOT_PROVEN, never PASS
    assert v.verdict == "NOT_PROVEN"
    # the real seam: the tree's own narrowing detector fires on a planted SPY-only default
    C = _load("tools/check_institutional_correctness.py", "_cic_nc03")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "liquidity_probe_experiment.py").write_text(
        'import argparse\np = argparse.ArgumentParser()\np.add_argument("--tickers", default="SPY")\n', encoding="utf-8")
    monkeypatch.setattr(C, "REPO", tmp_path)
    assert C.check_universal_ticker_scope(), "the planted SPY-only default was not detected"
    assert A.narrowing_violations(ROOT, "universal_ticker_scope") == []


# ── NC-05 self-granted waiver: a candidate-side AUTHORIZE row excludes nothing ──────────
def test_nc05_candidate_waiver_is_inert_until_it_is_base_state(tmp_path):
    base = A.parse_contract(contract(row("REQ-A", "FINITE", "MERGE", "delta:a", "STATIC")))
    cand = A.parse_contract(contract(
        row("REQ-A", "FINITE", "MERGE", "delta:a", "STATIC"),
        row("AUTH-1", "AUTHORIZE", "-", "waive:REQ-A:o2", "-")))
    inj = {"REQ-A": {"canonical": ["o1", "o2"], "obligations": {"o1": _obl("PROVEN")}}}
    v = _verdict(A.evaluate(tmp_path, cand, base_contract=base, injected=inj), "REQ-A")
    assert v.verdict == "NOT_PROVEN" and v.missing == 1 and v.waived == []
    assert [r.id for r in A.candidate_only_grants(base, cand)] == ["AUTH-1"]
    # honest positive: the same row, once on the base, waives the obligation
    v = _verdict(A.evaluate(tmp_path, cand, base_contract=cand, injected=inj), "REQ-A")
    assert v.verdict == "PASS" and v.waived == ["o2"] and len(v.applicable) == 1


# ── NC-06 / NC-08 parent shrink and acceptance-row deletion ───────────────────────────
def test_nc06_nc08_weakening_or_deleting_a_base_row_is_a_regression():
    base = A.parse_contract(contract(
        row("REQ-A", "FINITE", "MERGE", "delta:a", "LIVE_RTH+EXACT_HEAD"),
        row("REQ-B", "OPEN", "PRODUCT", "NONE", "STATIC")))
    deleted = A.parse_contract(contract(row("REQ-B", "OPEN", "PRODUCT", "NONE", "STATIC")))
    assert any("DELETED" in x for x in A.contract_regressions(base, deleted))
    weaker = A.parse_contract(contract(
        row("REQ-A", "FINITE", "PRODUCT", "delta:a", "ISOLATED_E2E"),
        row("REQ-B", "OPEN", "PRODUCT", "NONE", "STATIC")))
    regs = A.contract_regressions(base, weaker)
    assert any("PROOF class weakened" in x for x in regs)
    assert any("PROOF flags dropped" in x for x in regs)
    assert any("GATE demoted" in x for x in regs)
    rescoped = A.parse_contract(contract(
        row("REQ-A", "FINITE", "MERGE", "delta:other", "LIVE_RTH+EXACT_HEAD", parent="REQ-B"),
        row("REQ-B", "OPEN", "PRODUCT", "NONE", "STATIC")))
    regs = A.contract_regressions(base, rescoped)
    assert any("SCOPE authority changed" in x for x in regs) and any("PARENT changed" in x for x in regs)
    # honest positive: stricter is not a regression, and additions are recognized
    stricter = A.parse_contract(contract(
        row("REQ-A", "FINITE", "MERGE", "delta:a", "LIVE_RTH+EXACT_HEAD+RUNTIME_IDENTITY"),
        row("REQ-B", "OPEN", "MERGE", "NONE", "REAL_POPULATION"),
        row("REQ-C", "FINITE", "MERGE", "delta:c", "STATIC")))
    assert A.contract_regressions(base, stricter) == []


# ── NC-07 a child's PASS never closes its parent ──────────────────────────────────────
def test_nc07_child_pass_does_not_close_parent(tmp_path):
    base = A.parse_contract(contract(
        row("REQ-P", "FINITE", "PRODUCT", "delta:p", "STATIC"),
        row("REQ-C", "FINITE", "PRODUCT", "delta:c", "STATIC", parent="REQ-P")))
    inj = {"REQ-P": {"canonical": ["p1", "p2"], "obligations": {"p1": _obl("PROVEN")}},
           "REQ-C": {"canonical": ["c1"], "obligations": {"c1": _obl("PROVEN")}}}
    vs = A.evaluate(tmp_path, base, base_contract=base, injected=inj)
    assert _verdict(vs, "REQ-C").verdict == "PASS"
    assert _verdict(vs, "REQ-P").verdict == "NOT_PROVEN" and _verdict(vs, "REQ-P").missing == 1


# ── NC-09 the trusted lane executes NO candidate code: the candidate is data ──────────
def test_nc09_the_trusted_lane_never_executes_the_candidate_validator():
    """The validator-monotonicity measurement ran the CANDIDATE's own gate inside the trusted
    lane. A validator change is a trust-anchor change (operator-authorized, reviewed); the
    trusted lane judges the candidate under the BASE validator only. Structural: `trusted_main`
    runs the gate on the base tree and on the judged (overlaid) tree — never on `cand_wt`."""
    import ast as _ast
    import inspect
    src = inspect.getsource(GATE.trusted_main)
    fn = _ast.parse(src).body[0]
    gate_runs = [n for n in _ast.walk(fn) if isinstance(n, _ast.Call) and getattr(n.func, "id", "") == "run_gate"]
    targets = {getattr(c.args[0], "id", "?") for c in gate_runs}
    assert targets == {"base_wt", "judged"}, targets
    closure_runs = [n for n in _ast.walk(fn) if isinstance(n, _ast.Call)
                    and getattr(n.func, "id", "") in ("run_closure_command", "execute_closures")]
    assert closure_runs == [], "the trusted lane executes a candidate-cited command"
    assert not hasattr(GATE, "validator_weakening")
    # the candidate lane is where closure proof executes (hardening runs this owner)
    wf = (ROOT / ".github" / "workflows" / "hardening.yml").read_text(encoding="utf-8")
    assert "check_delta_adds_no_debt.py --base origin/main" in wf
    main_src = inspect.getsource(GATE.main)
    assert "execute_closures(" in main_src


# ── NC-10 / NC-12 trust anchors: unauthorized change of a workflow/validator is a bypass ─
def test_nc10_nc12_trust_anchor_changes_need_base_side_authorization(tmp_path):
    auths = A.authorizations(A.parse_contract(contract(
        row("AUTH-A", "AUTHORIZE", "-", "anchor:.github/workflows/pytest.yml@feature/x", "-"),
        row("AUTH-B", "AUTHORIZE", "-", "anchor:tools/check_*.py@*", "-"),
        row("AUTH-M", "AUTHORIZE", "-", "marker:silent-zero-ok@app/**@feature/x", "-"))))
    assert not A.authorized(auths, "anchor", ".github/workflows/pytest.yml", "feature/y")
    assert A.authorized(auths, "anchor", ".github/workflows/pytest.yml", "feature/x")
    assert A.authorized(auths, "anchor", "tools/check_institutional_correctness.py", "any")
    assert not A.authorized(auths, "anchor", "tools/stop_guard.py", "any")
    assert A.authorized(auths, "marker", "app/x.py", "feature/x", token="silent-zero-ok")
    assert not A.authorized(auths, "marker", "app/x.py", "feature/x", token="fake-default-ok")
    assert not A.authorized([], "anchor", ".github/workflows/pytest.yml", "feature/x")
    # the population is derived from the wiring by its owner (the enforcement-path seam), and
    # the acceptance executor holds no population of its own
    PCI = _load("tools/precommit_institutional.py", "_pci_nc10")
    anchors = PCI.trust_anchor_paths(ROOT)
    assert A.resolve_scope("tools.precommit_institutional:trust_anchor_paths", ROOT) == anchors
    assert not hasattr(A, "trust_anchor_paths")
    for rel in (".github/workflows/pytest.yml", ".github/workflows/hardening.yml",
                ".github/workflows/trusted-closure.yml", ".claude/settings.json", ".pre-commit-config.yaml",
                "tools/check_institutional_correctness.py", "tools/check_delta_adds_no_debt.py",
                "tools/stop_guard.py", "tools/process_lock_guard.py", "governance/acceptance.py",
                "tools/precommit_institutional.py"):
        assert rel in anchors, rel
    # NC-12: the judged tree carries the BASE validator, whatever the candidate wrote
    base = tmp_path / "base"; cand = tmp_path / "cand"
    (base / "tools").mkdir(parents=True); (cand / "tools").mkdir(parents=True)
    (base / "tools" / "check_x.py").write_text("STRICT = True\n", encoding="utf-8")
    (cand / "tools" / "check_x.py").write_text("STRICT = False\n", encoding="utf-8")
    (cand / "tools" / "new_tool.py").write_text("x = 1\n", encoding="utf-8")
    copied = GATE.overlay(base, cand, ["tools/check_x.py", "tools/absent_in_base.py"])
    assert copied == ["tools/check_x.py"]
    assert (cand / "tools" / "check_x.py").read_text(encoding="utf-8") == "STRICT = True\n"
    assert (cand / "tools" / "new_tool.py").is_file()


# ── NC-13 / NC-14 / NC-15 / NC-21 evidence class, identity, provenance ────────────────
def test_nc13_nc14_nc15_evidence_falsifiers_all_caught(tmp_path):
    """The falsifiers live HERE (required CI), not inside the executor: a judge that runs its
    own self-test on every trusted run certifies itself. NC-13 synthetic-as-live, NC-14 wrong
    identity / moved code, NC-15 missing provenance, and the honest positive NC-21."""
    import os
    req = A.Requirement("REQ-X", "OPEN", "PRODUCT", "evidence:REQ-X", "LIVE_RTH+EXACT_HEAD+RUNTIME_IDENTITY", "-", "", 0)
    root = tmp_path / "repo"
    root.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "nc", "GIT_AUTHOR_EMAIL": "nc@local",
           "GIT_COMMITTER_NAME": "nc", "GIT_COMMITTER_EMAIL": "nc@local"}

    def g(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=str(root), capture_output=True, text=True, env=env, check=True).stdout.strip()
    g("init", "-q")
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    g("add", "app.py"); g("commit", "-q", "-m", "one")
    sha1 = g("rev-parse", "HEAD")
    base = {"requirement_id": "REQ-X", "evidence_class": "LIVE_RTH", "candidate_sha": sha1,
            "environment": "LIVE_RTH", "source": "capture.mjs", "captured_at": "2026-09-10T14:00:00Z",
            "population": {"authority": "router", "digest": "abc", "count": 7},
            "runtime_identity": {"git_sha": sha1, "dirty": False}}
    cases = [
        ("NC-21 honest positive", dict(base), "PROVEN"),
        ("NC-13 synthetic offered as live (class ISOLATED_E2E)", {**base, "evidence_class": "ISOLATED_E2E"}, "INVALID"),
        ("NC-13 payload label live:true is not provenance", {**base, "environment": "OFFLINE_CI", "payload": {"live": True, "source": "terrain_live_cache"}}, "INVALID"),
        ("NC-14 wrong sha", {**base, "candidate_sha": "0" * 40, "runtime_identity": {"git_sha": "0" * 40, "dirty": False}}, "INVALID"),
        ("NC-14 dirty runtime", {**base, "runtime_identity": {"git_sha": sha1, "dirty": True}}, "INVALID"),
        ("NC-15 missing runtime identity", {k: v for k, v in base.items() if k != "runtime_identity"}, "INVALID"),
        ("NC-15 missing population", {k: v for k, v in base.items() if k != "population"}, "INVALID"),
        ("NC-15 missing source", {k: v for k, v in base.items() if k != "source"}, "INVALID"),
    ]
    for name, rec, expect in cases:
        assert A.evidence_status(rec, req, root).status == expect, name
    (root / "app.py").write_text("x = 2\n", encoding="utf-8")
    g("add", "app.py"); g("commit", "-q", "-m", "two")
    assert A.evidence_status(dict(base), req, root).status == "INVALID", "NC-14 code moved past the evidence sha"
    assert not hasattr(A, "evidence_adversarial") and not hasattr(A, "evidence_invariant_status")


def test_evidence_class_rank_and_operator_accept_cannot_be_self_granted(tmp_path):
    req = A.Requirement("REQ-L", "OPEN", "PRODUCT", "evidence:REQ-L", "REAL_POPULATION+OPERATOR_ACCEPT", "-", "", 0)
    ok = {"requirement_id": "REQ-L", "evidence_class": "REAL_POPULATION", "candidate_sha": "0" * 40,
          "environment": "PREMARKET", "source": "capture.mjs", "captured_at": "t",
          "population": {"authority": "router", "digest": "d", "count": 3}}
    assert A.evidence_status(ok, req, tmp_path).status == "PROVEN"
    assert A.evidence_status({**ok, "evidence_class": "STATIC"}, req, tmp_path).status == "INVALID"
    # the record is valid, yet without an ACCEPT row on the base the requirement stays MISSING
    d = tmp_path / A.EVIDENCE_DIR / "REQ-L"; d.mkdir(parents=True)
    (d / "rec.json").write_text(json.dumps(ok), encoding="utf-8")
    base = A.parse_contract(contract(row("REQ-L", "OPEN", "PRODUCT", "evidence:REQ-L", "REAL_POPULATION+OPERATOR_ACCEPT")))
    v = _verdict(A.evaluate(tmp_path, base, base_contract=base), "REQ-L")
    assert v.verdict == "NOT_PROVEN" and "ACCEPT row" in v.obligations["REQ-L"].detail


# ── NC-16 malformed hook payload: every wired executable refuses it ───────────────────
def test_nc16_every_hook_executable_fails_closed_on_unreadable_payload():
    status = A.resolve_scope("tools.stop_chain:fail_closed_status", ROOT)
    assert status and all(o.status == "PROVEN" for o in status.values()), {k: (o.status, o.detail) for k, o in status.items()}
    assert {"tools/stop_guard.py", "tools/process_lock_guard.py", "tools/operator_law_guard.py",
            "tools/stop_chain.py", "tools/pretooluse_chain.py"} <= set(status)
    # honest positive: a readable, benign PreToolUse payload passes the process lock
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "process_lock_guard.py")], cwd=str(ROOT),
                       input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}}),
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr


# ── NC-17 local bypass routes: refused in session, and remotely owned anyway ──────────
def test_nc17_skip_routes_are_refused_and_every_local_hook_owner_runs_remotely():
    for cmd in ("SKIP=institutional-correctness git commit -m x", "$env:SKIP='ruff-correctness'; git commit -m x",
                "pre-commit uninstall", "git commit --no-verify -m x", "git commit -n -m x"):
        assert OLG._SKIP_HOOKS.search(cmd), cmd
    for cmd in ("git commit -m 'skip the typo'", "SKIPPED=1 python x.py", "echo pre-commit installed"):
        assert not OLG._SKIP_HOOKS.search(cmd), cmd
    parity = A.resolve_scope("tools.precommit_institutional:local_remote_parity", ROOT)
    assert parity and all(o.status == "PROVEN" for o in parity.values()), {k: (o.status, o.detail) for k, o in parity.items()}


# ── NC-18 false CLOSED command: executed, exit code decides ───────────────────────────
def test_nc18_closure_commands_are_executed_not_matched(tmp_path):
    good = "| RC-9001 | CLOSED | 2026-09-10 | 2026-09-11 | d | w -> ROOT | fixed. `python -c pass` |"
    bad = '| RC-9002 | CLOSED | 2026-09-10 | 2026-09-11 | d | w -> ROOT | fixed. `python -c "import sys; sys.exit(3)"` |'
    live = "| RC-9003 | CLOSED | 2026-09-10 | 2026-09-11 | d | w -> ROOT | fixed. `curl -s http://127.0.0.1:8000/api/build` |"
    assert GATE.executable_commands(good) == ["python -c pass"]
    assert GATE.executable_commands(live) == []
    # a backticked FILE NAME that starts like an interpreter is not a command (the judge once
    # executed `python -m pytest.yml` off a closure row that mentioned `pytest.yml`)
    named = "| RC-9004 | CLOSED | 2026-09-10 | 2026-09-11 | d | w -> ROOT | edited `pytest.yml` and `python_notes.md`; proof `python -c pass` |"
    assert GATE.executable_commands(named) == ["python -c pass"]
    assert GATE.run_closure_command(GATE.executable_commands(good)[0], tmp_path)[0] == 0
    assert GATE.run_closure_command(GATE.executable_commands(bad)[0], tmp_path)[0] == 3
    base = "| RC-9001 | OPEN | 2026-09-10 | 2026-09-11 | d | w | in progress |\n"
    cand = "\n".join([good, bad, live]) + "\n"
    closing = GATE.closing_rows(base, cand)
    assert sorted(closing) == ["RC-9001", "RC-9002", "RC-9003"]
    assert GATE.executable_commands(closing["RC-9001"]) == ["python -c pass"]   # a parsed row works too
    assert GATE.closing_rows(cand, cand) == {}          # already closed on base: not re-judged
    # the CANDIDATE lane executes: the failing and the live-only rows fail it, the good one passes
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance" / "root_cause_log.md").write_text(cand, encoding="utf-8")
    ledger_base = base
    failures = []
    for rc, r in sorted(GATE.closing_rows(ledger_base, cand).items()):
        cmds = GATE.executable_commands(r)
        if not cmds:
            failures.append(rc)
        elif GATE.run_closure_command(cmds[0], tmp_path)[0] != 0:
            failures.append(rc)
    assert failures == ["RC-9002", "RC-9003"]


# ── NC-19 one-computation slice: green slices never close the parent ──────────────────
def test_nc19_registered_slices_green_do_not_close_one_computation():
    rows = [r for r in A.load_contract(ROOT) if r.id in ("REQ-ONE-COMPUTATION", "REQ-DECISION-PATH-ADMISSION")]
    vs = A.evaluate(ROOT, rows, base_contract=rows)
    v = _verdict(vs, "REQ-ONE-COMPUTATION")
    assert v.proven > 0, "the registered slices ARE green"
    assert v.missing > 0 and v.verdict == "NOT_PROVEN"
    assert len(v.canonical) == v.proven + v.missing + v.failed + v.invalid
    # the same mechanism, another domain: the empty admission registry is MISSING per entry,
    # never a stored BUILT_EMPTY verdict
    d = _verdict(vs, "REQ-DECISION-PATH-ADMISSION")
    assert d.authority_resolved and len(d.canonical) == 5 and d.verdict == "NOT_PROVEN"


# ── NC-20 the known-bad evidence package is rejected for general reasons ──────────────
def test_nc20_known_bad_109f8da3_cannot_close_the_console_requirement(tmp_path):
    sha = "109f8da3f0a389424105e567bdc0bfa126e6d53d"
    have = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=str(ROOT), capture_output=True)
    if have.returncode != 0:
        pytest.skip("109f8da3 is not present in this clone")
    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "--detach", str(wt), sha], cwd=str(ROOT), check=True, capture_output=True)
    try:
        rows = [r for r in A.load_contract(ROOT) if r.id == "REQ-CONSOLE-GAMMA-UI"]
        v = _verdict(A.evaluate(wt, rows, base_contract=rows), "REQ-CONSOLE-GAMMA-UI")
        assert v.verdict == "NOT_PROVEN" and v.obligations["REQ-CONSOLE-GAMMA-UI"].status == "MISSING"
        # its E2E fixture wears `live: true` and `source: terrain_live_cache`; offered as evidence
        # it is INVALID for the class the row requires — labels are not provenance
        rec = {"requirement_id": "REQ-CONSOLE-GAMMA-UI", "evidence_class": "ISOLATED_E2E",
               "candidate_sha": sha, "environment": "OFFLINE_CI", "source": "tests/e2e/console-gamma-visual.spec.js",
               "captured_at": "2026-09-10T00:00:00Z", "payload": {"live": True, "source": "terrain_live_cache"}}
        assert A.evidence_status(rec, rows[0], wt).status == "INVALID"
        labelled_live = {**rec, "evidence_class": "LIVE_RTH", "environment": "LIVE_RTH"}
        st = A.evidence_status(labelled_live, rows[0], wt)
        assert st.status == "INVALID" and "population" in st.detail
        # and even a complete, valid live record cannot self-certify: no ACCEPT row exists
        full = {**labelled_live, "population": {"authority": "router", "digest": "x", "count": 1},
                "runtime_identity": {"git_sha": sha, "dirty": False}}
        d = wt / A.EVIDENCE_DIR / "REQ-CONSOLE-GAMMA-UI"; d.mkdir(parents=True)
        (d / "rec.json").write_text(json.dumps(full), encoding="utf-8")
        v = _verdict(A.evaluate(wt, rows, base_contract=rows), "REQ-CONSOLE-GAMMA-UI")
        assert v.verdict == "NOT_PROVEN" and "ACCEPT row" in v.obligations["REQ-CONSOLE-GAMMA-UI"].detail
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=str(ROOT), capture_output=True)


# ── contract shape is fail-closed ─────────────────────────────────────────────────────
def test_contract_shape_errors_raise_never_guess():
    with pytest.raises(A.ContractError):
        A.parse_contract("# nothing here\n")
    with pytest.raises(A.ContractError):
        A.parse_contract(contract(row("REQ-A", "FINITE", "MERGE", "delta:a", "SORT_OF")))
    with pytest.raises(A.ContractError):
        A.parse_contract(contract(row("REQ-A", "FINITE", "MERGE", "delta:a", "STATIC", parent="REQ-NOPE")))
    with pytest.raises(A.ContractError):
        A.parse_contract(contract(row("REQ-A", "FINITE", "MERGE", "", "STATIC")))
    with pytest.raises(A.ContractError):
        A.parse_contract(contract(row("ACC-1", "ACCEPT", "-", "REQ-A@notasha", "-")))
    # the live contract parses, and every requirement the mission names is in it
    ids = {r.id for r in A.load_contract(ROOT)}
    for rid in ("REQ-GOV-TRUSTED-VALIDATOR", "REQ-GOV-TRUST-ANCHORS", "REQ-GOV-CONTRACT-MONOTONIC",
                "REQ-GOV-CLOSURE-COMMANDS", "REQ-GOV-MARKER-AUTHORITY", "REQ-GOV-HOOKS-FAIL-CLOSED",
                "REQ-GOV-LOCAL-REMOTE-PARITY", "REQ-GOV-REMOTE-NON-BYPASS",
                "REQ-UI-PAGES-BOUND", "REQ-ONE-COMPUTATION", "REQ-DECISION-PATH-ADMISSION",
                "REQ-PREDICTIVE-VALIDITY", "REQ-REAL-MONEY-READINESS", "REQ-CARD-FIDELITY",
                "REQ-UNIVERSAL-TICKER", "REQ-CONSOLE-GAMMA-UI"):
        assert rid in ids, rid
    # ONE acceptance authority: no stored verdict table beside the computed contract
    text = (ROOT / "OPEN_ITEMS.md").read_text(encoding="utf-8")
    assert "## Top-level acceptance verdicts" not in text
    assert "UNIVERSALITY_STATUS = PASS" not in text and "ONE_FAUCET_STATUS = PASS" not in text


def test_report_carries_every_mandated_count_label(tmp_path):
    base = A.parse_contract(contract(row("REQ-A", "FINITE", "MERGE", "delta:a", "STATIC"),
                                     row("REQ-O", "OPEN", "PRODUCT", "NONE", "STATIC")))
    lines = "\n".join(A.report_lines(A.evaluate(tmp_path, base, base_contract=base)))
    for label in ("REQUIREMENT_ID=", "SCOPE_KIND=", "SCOPE_AUTHORITY=", "CANONICAL_COUNT=", "WAIVED_COUNT=",
                  "APPLICABLE_COUNT=", "PROVEN_COUNT=", "MISSING_COUNT=", "FAIL_COUNT=", "INVALID_EVIDENCE_COUNT=",
                  "BYPASS_COUNT=", "VERDICT=", "BOUNDARY_AUTHORITY=", "INVARIANT_ID=", "LOCAL_NARROWING_VIOLATIONS=",
                  "ADVERSARIAL_MUTATIONS_RUN=", "ADVERSARIAL_MUTATIONS_CAUGHT=", "TOTAL_REQUIRED_REQUIREMENTS=",
                  "PASS_COUNT=", "NOT_PROVEN_COUNT="):
        assert label in lines, label
    assert "%" not in lines
