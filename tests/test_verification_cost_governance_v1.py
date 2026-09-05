"""RC-517 / RC-518 / RC-519 — verification-cost governance: the mechanically enforceable part, attacked.

Observed 2026-09-04/05 (two agents, independently): a real-boundary campaign launched beside an
8-worker pytest-full wave; 43 minutes of blind waiting; a serial campaign that lost every
completed case to one crash; unchanged base-side proof recomputed; a guard that read the WORD
pytest (RC-518); a guard that authorized from the process table and so let two launches in one
breath both pass (RC-519, measured); a second shell parser beside the canonical one; proof reuse
keyed on the SHA alone while a copied venv had lost two packages.

Every control drives the real entrypoint — `process_lock_guard.pretooluse_block`, the lock's
lease and admission, the campaign's reuse, the delta gate's cache key — and the atomicity
controls carry a mutation control where removing the protection must let the attack through.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.check_delta_adds_no_debt as GATE  # noqa: E402
import tools.operating_process_lock as OPL  # noqa: E402
import tools.operator_law_guard as OLG  # noqa: E402
import tools.process_lock_guard as plg  # noqa: E402

CAMPAIGN = ROOT / "tests" / "institutional_e2e_boundary_campaign.py"


def _campaign():
    spec = importlib.util.spec_from_file_location("e2e_campaign", CAMPAIGN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FAKE_WAVE = [{"pid": 4242, "kind": "institutional_e2e_boundary_campaign", "age_seconds": 2580,
              "cpu_seconds": 1900.5, "children": 3, "create_time": 1.0,
              "command": "python tests/institutional_e2e_boundary_campaign.py --base-group dup"}]


@pytest.fixture
def lease_dir(tmp_path, monkeypatch) -> Path:
    """A private lease directory: the in-process controls must never touch the host's."""
    d = tmp_path / "lease"
    monkeypatch.setattr(OPL, "LEASE_DIR", d)
    return d


@pytest.fixture
def idle(monkeypatch, lease_dir):
    monkeypatch.setattr(OPL, "heavy_verification_jobs", lambda exclude_pids=None: [])
    return lease_dir


# ── ONE command interpretation: every launch form, through the canonical parser ───────

@pytest.mark.parametrize("cmd,kind", [
    ("python -m pytest -n 8 --dist loadfile -q", "pytest-parallel"),
    ("py -m pytest -n 8", "pytest-parallel"),
    ("py.exe -m pytest -n 8", "pytest-parallel"),
    ('"C:/Program Files/Python 313/python.exe" -m pytest -n 8', "pytest-parallel"),
    (".venv/Scripts/python.exe -m pytest -n auto", "pytest-parallel"),
    ("timeout 60s python -m pytest -n 8", "pytest-parallel"),
    ("timeout -k 5 60 python -m pytest -n 8", "pytest-parallel"),
    ("timeout 600 python -m pytest --dist loadfile -q", "pytest-parallel"),
    ("nice -n 10 python -m pytest -n 8", "pytest-parallel"),
    ("env -i python -m pytest -n 8", "pytest-parallel"),
    ("sudo -u ed python -m pytest -n 8", "pytest-parallel"),
    ('cmd.exe /c "python -m pytest -n 8"', "pytest-parallel"),
    ("cmd /c python -m pytest -n 8", "pytest-parallel"),
    ('pwsh -NoProfile -Command "python -m pytest -n 8"', "pytest-parallel"),
    ('powershell -c "py -m pytest -n auto"', "pytest-parallel"),
    ('bash -c "python -m pytest -n 8"', "pytest-parallel"),
    ("pytest -n 8", "pytest-parallel"),
    ("pytest", "pytest-whole-suite"),
    ("python -m pytest", "pytest-whole-suite"),
    ("python -m pytest tests/ -q", "pytest-whole-suite"),
    ("cd /c/x && VAR=1 timeout 600 python -m pytest --dist loadfile -q", "pytest-parallel"),
    ("make test-all", "e2e-suite"),
    ("npm run test:e2e", "e2e-suite"),
    ("npx playwright test", "e2e-suite"),
    ("python tools/check_delta_adds_no_debt.py --index --base origin/main", "check_delta_adds_no_debt"),
    ("python tools/check_institutional_correctness.py --enforced-only", "check_institutional_correctness"),
    ("python tests/institutional_e2e_boundary_campaign.py --parallel --out x.json", "institutional_e2e_boundary_campaign"),
    # interpreter payloads that ARE launches, read by AST (actions, not words)
    ("python -c \"import pytest; pytest.main(['-n','8'])\"", "pytest-parallel"),
    ('python -c "import pytest; pytest.main()"', "pytest-whole-suite"),
    ("python -c \"import subprocess; subprocess.run(['python','-m','pytest','-n','8'])\"", "pytest-parallel"),
    ("python -c \"import runpy; runpy.run_module('pytest')\"", "pytest-whole-suite"),
    ("python -c \"import os; os.system('make test-all')\"", "e2e-suite"),
])
def test_every_heavy_launch_form_is_one_action(cmd, kind):
    assert OPL.heavy_verification_kind(cmd) == kind


@pytest.mark.parametrize("cmd", [
    "python -m pytest tests/test_one_producer_gate_v1.py -q",
    "python -m pytest tests/test_x.py::test_a -q -p no:cacheprovider",
    "python -m pytest tests/test_a.py tests/test_b.py -k collision",
    ".venv/Scripts/python.exe -m pytest tests/test_verification_cost_governance_v1.py -q",
    'pwsh -Command "python -m pytest tests/test_x.py"',
    "python -c \"from pytest import main; main(['tests/test_x.py'])\"",
    "python tools/operating_process_lock.py --heavy-jobs",
    "python tools/check_institutional_correctness.py --rebaseline",
    "git status --short",
    "python -c \"import tools.check_institutional_correctness as C; print(len(C.CHECKS))\"",
    # words are never launches (RC-518)
    "gh run watch 33945309566 --exit-status --interval 60 2>&1 | tail -3; echo \"pytest-full-rc=$?\"",
    "echo check_delta_adds_no_debt.py",
    "git log --oneline --grep pytest -5",
    "cat reports/pytest-full.log | tail -20",
    'git commit -m "run pytest -n 8 later"',
    "cat > notes.md <<'EOF'\nrun python -m pytest -n 8 later\nEOF",
    "python -c \"print('pytest -n 8')\"",
    "grep -c pytest x.txt",
    'sqlite3 -c "select 1" db',
])
def test_targeted_light_and_word_only_commands_are_not_launches(cmd):
    assert OPL.heavy_verification_kind(cmd) is None


def test_non_literal_payload_is_not_judged_at_the_command_seam():
    """`pytest.main(args)` with a non-literal argument cannot be classified from the text;
    the command seam does not guess, the launch seam (conftest admission) judges it when it
    runs. That disposition is stated, not hidden."""
    assert OPL.heavy_verification_kind('py -c "import pytest; pytest.main(args)"') is None


def test_the_lock_has_no_parser_of_its_own():
    """RC-519: one command interpretation. The lock must not carry a segment splitter,
    tokenizer or wrapper list beside the canonical one in operator_law_guard."""
    src = (ROOT / "tools" / "operating_process_lock.py").read_text(encoding="utf-8")
    assert "_segment_program" not in src and "_SEG_WRAPPERS" not in src
    assert "iter_command_segments" in src and "_segment_head" in src and "iter_launch_payloads" in src
    guard = (ROOT / "tools" / "operator_law_guard.py").read_text(encoding="utf-8")
    assert "iter_launch_payloads(raw)" in guard, "the write rule reads payloads through the same iterator"


def test_canonical_head_resolver_sees_through_wrapper_options():
    assert OLG._segment_head("timeout 60s git commit -m x")[0] == "git"
    assert OLG._segment_head("sudo -u ed python -m pytest -n 8")[0] == "python"
    assert OLG._segment_head("nice -n 10 py.exe -m pytest")[0] == "py.exe"
    assert OLG._segment_head("cmd /c python -m pytest -n 8")[0] == "python"
    assert OLG._segment_head("echo git commit")[0] == "echo"


def test_write_rule_still_reads_payload_writes_through_the_one_iterator():
    assert OLG._payload_write_violation("python -c \"p='gov'+'ernance/x.json'; open(p,'w').write('1')\"")
    assert not OLG._payload_write_violation("python -c \"open('reports/x.json','w')\"")


_PRE_CONSOLIDATION_GUARD = "4a045921"     # the guard before the payload iterator became the one reader


def test_write_rule_parity_with_the_pre_consolidation_guard():
    """Consolidating the payload reader must not change ONE verdict of the write rule. The
    pre-RC-519 guard is loaded from git and asked the same questions."""
    p = subprocess.run(["git", "show", f"{_PRE_CONSOLIDATION_GUARD}:tools/operator_law_guard.py"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        pytest.skip("pre-consolidation guard commit not present in this clone (shallow checkout)")
    import types
    old = types.ModuleType("old_guard")
    old.__file__ = str(ROOT / "tools" / "operator_law_guard.py")
    exec(compile(p.stdout, "old_guard", "exec"), old.__dict__)
    cases = [
        "python -c \"open('governance/x.json','w')\"",
        "python -c \"open('reports/x.json','w')\"",
        "python -c \"p='gov'+'ernance/x.json'; open(p,'w').write('1')\"",
        "python -c \"open('static/chart.html','w').write('1')\"",
        "python -c \"from pathlib import Path; Path('governance/x.json').write_text('1')\"",
        "node -c \"open('governance/x.json','w')\"",
        "ruby -c \"open('static/x.html','w')\"",
        "grep -c \"open('governance/x.json','w')\" f",
        "sqlite3 -c \"open('governance/x.json','w')\" db",
        "python -c 'x = 1'",
        'git commit -m "python -c open(x,w)"',
    ]
    for c in cases:
        assert old._payload_write_violation(c) == OLG._payload_write_violation(c), c


def test_mutation_control_classifier_removed_reopens_every_launch_form(monkeypatch):
    monkeypatch.setattr(OPL, "heavy_verification_kind", lambda cmd: None)
    monkeypatch.setattr(OPL, "heavy_verification_jobs", lambda exclude_pids=None: list(FAKE_WAVE))
    for cmd in ("python -m pytest -n 8", 'cmd /c "python -m pytest -n 8"',
                "python -c \"import pytest; pytest.main(['-n','8'])\""):
        assert plg.pretooluse_block("Bash", {"command": cmd}) == [], cmd


# ── observed failure 2: competing wave while a job is alive → BLOCK; targeted → PASS ──

def test_attack_competing_pytest_wave_while_campaign_alive_is_blocked(monkeypatch, lease_dir):
    monkeypatch.setattr(OPL, "heavy_verification_jobs", lambda exclude_pids=None: list(FAKE_WAVE))
    bad = plg.pretooluse_block("Bash", {"command": "python -m pytest -n 8 --dist loadfile -q"})
    assert bad and "COMPETING_HEAVY_VERIFICATION" in bad[0], bad
    assert "pid 4242" in bad[0] and "--heavy-jobs" in bad[0]


def test_attack_every_bypass_form_is_blocked_beside_a_wave(monkeypatch, lease_dir):
    monkeypatch.setattr(OPL, "heavy_verification_jobs", lambda exclude_pids=None: list(FAKE_WAVE))
    for cmd in ("py -m pytest -n 8", "timeout 60s python -m pytest -n 8", 'cmd.exe /c "python -m pytest -n 8"',
                'pwsh -Command "python -m pytest -n 8"', "python -c \"import pytest; pytest.main(['-n','8'])\"",
                "python tests/institutional_e2e_boundary_campaign.py --out y.json",
                "python tools/check_delta_adds_no_debt.py --index"):
        assert plg.pretooluse_block("Bash", {"command": cmd}), cmd


def test_control_targeted_run_beside_a_wave_passes(monkeypatch, lease_dir):
    monkeypatch.setattr(OPL, "heavy_verification_jobs", lambda exclude_pids=None: list(FAKE_WAVE))
    assert plg.pretooluse_block("Bash", {"command": "python -m pytest tests/test_one_producer_gate_v1.py -q"}) == []
    assert plg.pretooluse_block("Bash", {"command": "gh run watch 1 --exit-status | tail -3; echo \"pytest-full-rc=$?\""}) == []


def test_control_heavy_launch_on_an_idle_host_passes_and_reserves(idle):
    assert plg.pretooluse_block("Bash", {"command": "python -m pytest -n 8 -q"}) == []
    res = OPL.reservation()
    assert res and res["kind"] == "pytest-parallel", "the launch right is now OWNED, not inferred"


# ── RC-519: the startup race is closed — A..F at the real entrypoints ────────────────

def test_A_two_near_simultaneous_heavy_launches_exactly_one_passes(idle):
    """Sixteen concurrent decisions through the REAL guard function, no process visible:
    exactly one is authorized; every other is refused for the reservation reason."""
    results: list[list[str]] = [None] * 16
    barrier = threading.Barrier(16)

    def decide(i: int) -> None:
        barrier.wait()
        results[i] = plg.pretooluse_block("Bash", {"command": "python -m pytest -n 8 -q"})
    threads = [threading.Thread(target=decide, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    passed = [r for r in results if r == []]
    blocked = [r for r in results if r]
    assert len(passed) == 1, f"exactly one may pass; {len(passed)} passed"
    assert len(blocked) == 15 and all("COMPETING_HEAVY_VERIFICATION" in b[0] for b in blocked)   # B


def test_B_loser_is_refused_for_the_reservation_reason(idle):
    assert plg.pretooluse_block("Bash", {"command": "python -m pytest -n 8"}) == []
    bad = plg.pretooluse_block("Bash", {"command": "python tools/check_delta_adds_no_debt.py --index"})
    assert bad and "COMPETING_HEAVY_VERIFICATION" in bad[0] and "not yet appeared in the process table" in bad[0]


def test_C_targeted_test_during_the_reserved_window_passes(idle):
    assert plg.pretooluse_block("Bash", {"command": "python -m pytest -n 8"}) == []
    assert plg.pretooluse_block("Bash", {"command": "python -m pytest tests/test_x.py -q"}) == []


def test_D_after_the_admitted_process_ends_the_next_wave_passes(idle):
    """A HELD lease whose pid is dead is stale by definition and reclaimed by the next
    decision — a crashed or finished wave never leaves a permanent lock."""
    _res, held = OPL._lease_paths()
    held.parent.mkdir(parents=True, exist_ok=True)
    dead = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    held.write_text(json.dumps({"pid": int(dead.stdout.strip()), "create_time": 1.0, "kind": "pytest-parallel",
                                "started_utc": "2026-09-05T00:00:00Z"}), encoding="utf-8")
    assert OPL.held_lease() is None
    assert plg.pretooluse_block("Bash", {"command": "python -m pytest -n 8"}) == []


def test_D2_a_live_held_lease_refuses_the_next_wave(idle):
    _res, held = OPL._lease_paths()
    held.parent.mkdir(parents=True, exist_ok=True)
    import psutil
    held.write_text(json.dumps({"pid": os.getpid(), "create_time": psutil.Process().create_time(),
                                "kind": "pytest-parallel", "started_utc": "x"}), encoding="utf-8")
    bad = plg.pretooluse_block("Bash", {"command": "python -m pytest -n 8"})
    assert bad and "holds the lease" in bad[0]


def test_E_crashed_reservation_is_reclaimed_by_bounded_objective_state(idle):
    res, _held = OPL._lease_paths()
    res.parent.mkdir(parents=True, exist_ok=True)
    fresh = {"reserved_at": time.time() - 5, "kind": "pytest-parallel", "command": "x", "by_pid": 1}
    res.write_text(json.dumps(fresh), encoding="utf-8")
    assert plg.pretooluse_block("Bash", {"command": "python -m pytest -n 8"}), "a fresh reservation is in flight"
    stale = dict(fresh, reserved_at=time.time() - OPL.RESERVATION_TTL_SECONDS - 1)
    res.write_text(json.dumps(stale), encoding="utf-8")
    assert plg.pretooluse_block("Bash", {"command": "python -m pytest -n 8"}) == [], "past the TTL it is a crash, reclaimed"
    res.write_text("{not json", encoding="utf-8")
    assert OPL.reservation() is None


def test_E2_filesystem_failure_fails_closed(idle, monkeypatch):
    monkeypatch.setattr(OPL, "_create_exclusive", lambda path, doc: (_ for _ in ()).throw(OSError("disk")))
    bad = plg.pretooluse_block("Bash", {"command": "python -m pytest -n 8"})
    assert bad and "could not be established" in bad[0]


def test_F_mutation_control_without_the_atomic_reservation_both_launches_pass(idle, monkeypatch):
    monkeypatch.setattr(OPL, "reserve_heavy_launch", lambda kind, cmd: (True, "no reservation (mutated)"))
    results = [plg.pretooluse_block("Bash", {"command": "python -m pytest -n 8"}) for _ in range(2)]
    assert results == [[], []], "with the reservation removed the simultaneous attack succeeds — the control is causal"


def test_admission_refuses_beside_a_live_holder_and_admits_inside_the_wave(idle, monkeypatch):
    """The in-process seam: another live holder -> refuse; the holder in my ancestry -> the
    launch is part of the admitted wave."""
    import psutil
    _res, held = OPL._lease_paths()
    held.parent.mkdir(parents=True, exist_ok=True)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        held.write_text(json.dumps({"pid": other.pid, "create_time": psutil.Process(other.pid).create_time(),
                                    "kind": "pytest-parallel", "started_utc": "x"}), encoding="utf-8")
        ok, why = OPL.admit_heavy_launch("check_delta_adds_no_debt", "x")
        assert not ok and "holds the lease" in why
        monkeypatch.setattr(OPL, "_my_ancestor_pids", lambda: {other.pid})
        ok, why = OPL.admit_heavy_launch("check_institutional_correctness", "x")
        assert ok and "inside the admitted wave" in why
    finally:
        other.kill()
        other.wait()


def test_admission_claims_the_held_lease_and_releases_it(idle):
    ok, why = OPL.admit_heavy_launch("pytest-parallel", "pytest -n 8")
    assert ok, why
    held = OPL.held_lease()
    assert held and held["pid"] == os.getpid() and held["kind"] == "pytest-parallel"
    assert OPL.reservation() is None, "the reservation was retired by the claim"
    OPL.release_heavy_launch()
    assert OPL.held_lease() is None


def test_admission_orders_two_processes_started_in_one_instant(idle, monkeypatch):
    import psutil
    mine = psutil.Process().create_time()
    older = [dict(FAKE_WAVE[0], create_time=mine - 10)]
    monkeypatch.setattr(OPL, "heavy_verification_jobs", lambda exclude_pids=None: older)
    ok, why = OPL.admit_heavy_launch("pytest-parallel", "x")
    assert not ok and "older heavy verification job" in why
    younger = [dict(FAKE_WAVE[0], create_time=mine + 10)]
    monkeypatch.setattr(OPL, "heavy_verification_jobs", lambda exclude_pids=None: younger)
    ok, why = OPL.admit_heavy_launch("pytest-parallel", "x")
    assert ok, why
    OPL.release_heavy_launch()


def _host_is_free() -> bool:
    return not OPL.heavy_verification_jobs() and OPL.held_lease() is None and OPL.reservation() is None


@pytest.mark.skipif(not _host_is_free(), reason="the real host lease is in use (an admitted wave, e.g. CI's own pytest-full); the in-process controls above prove atomicity")
def test_real_seam_two_concurrent_guard_processes_exactly_one_passes():
    """The REAL PreToolUse entrypoint as a subprocess, twice at once, on the real host lease."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "python -m pytest -n 8 -q"},
                          "cwd": str(ROOT)})
    procs = [subprocess.Popen([sys.executable, "tools/process_lock_guard.py"], cwd=ROOT, stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                              errors="replace") for _ in range(2)]
    outs = [p.communicate(payload, timeout=120) for p in procs]
    codes = [p.returncode for p in procs]
    try:
        assert sorted(codes) == [0, 2], (codes, [o[1][:300] for o in outs])
        loser = outs[codes.index(2)][1]
        assert "COMPETING_HEAVY_VERIFICATION" in loser
    finally:
        res, _held = OPL._lease_paths()
        if res.exists():
            res.unlink()


@pytest.mark.skipif(not _host_is_free(), reason="the real host lease is in use; the in-process controls above prove atomicity")
def test_real_seam_two_heavy_pytest_processes_exactly_one_runs():
    """Two parallel pytest sessions started in the same instant, each admitting itself in
    tests/conftest.py: exactly one runs, the other exits 2 with the refusal."""
    argv = [sys.executable, "-m", "pytest", "-n", "2", "-p", "no:cacheprovider", "-q",
            "tests/test_one_producer_gate_v1.py"]
    procs = [subprocess.Popen(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace") for _ in range(2)]
    outs = [p.communicate(timeout=900)[0] for p in procs]
    codes = [p.returncode for p in procs]
    assert 2 in codes and codes.count(2) == 1, (codes, [o[-400:] for o in outs])
    assert any("COMPETING_HEAVY_VERIFICATION" in o for o in outs)
    assert OPL.held_lease() is None, "the winner released its lease at exit"


# ── the inventory is real, excludes itself, and is the evidence tool ─────────────────

def test_inventory_excludes_the_pytest_it_runs_in_and_reports_real_fields():
    jobs = OPL.heavy_verification_jobs()
    assert os.getpid() not in {j["pid"] for j in jobs}
    for j in jobs:
        assert {"pid", "kind", "age_seconds", "cpu_seconds", "command", "create_time"} <= set(j)


def test_heavy_jobs_cli_prints_inventory_lease_and_identity():
    p = subprocess.run([sys.executable, "tools/operating_process_lock.py", "--heavy-jobs"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr
    doc = json.loads(p.stdout)
    assert {"measured_at_utc", "heavy_jobs", "lease", "evidence_identity"} <= set(doc)


def test_psutil_absent_is_unmeasurable_not_clean(monkeypatch, lease_dir):
    real_import = __import__

    def no_psutil(name, *a, **k):
        if name == "psutil":
            raise ImportError("psutil removed")
        return real_import(name, *a, **k)
    monkeypatch.setattr("builtins.__import__", no_psutil)
    jobs = OPL.heavy_verification_jobs()
    assert jobs and jobs[0]["kind"] == "UNMEASURABLE"
    assert OPL.competing_heavy_verification_violations("python -m pytest -n 8", jobs)
    ok, why = OPL.admit_heavy_launch("pytest-parallel", "x")
    assert not ok and "refusing" in why


# ── proof reuse: identity matches the claim ──────────────────────────────────────────

def _closure_third_party() -> set[str]:
    seen: set[str] = set()
    third: set[str] = set()
    queue = ["tools/check_institutional_correctness.py", "tools/check_delta_adds_no_debt.py",
             "tests/institutional_e2e_boundary_campaign.py", "tools/operating_process_lock.py"]
    std = set(sys.stdlib_module_names)
    while queue:
        rel = queue.pop()
        if rel in seen or not (ROOT / rel).exists():
            continue
        seen.add(rel)
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else (
                [n.module] if isinstance(n, ast.ImportFrom) and n.module else [])
            for name in names:
                top = name.split(".")[0]
                if top in std:
                    continue
                for cand in (f"{name.replace('.', '/')}.py", f"tools/{top}.py", f"{top}.py",
                             f"{name.replace('.', '/')}/__init__.py"):
                    if (ROOT / cand).exists():
                        queue.append(cand)
                        break
                else:
                    third.add(top)
    return third


def test_the_declared_third_party_closure_is_the_measured_one():
    """The evidence identity carries exactly the third-party modules the proof owners can
    reach. A new import must change this contract; execnet and openpyxl are proven outside it."""
    measured = _closure_third_party()
    assert measured == set(OPL.PROOF_THIRD_PARTY_MODULES), measured
    assert "execnet" not in measured and "openpyxl" not in measured


def test_identity_reuse_and_invalidation(tmp_path, monkeypatch):
    camp = _campaign()
    jsonl = tmp_path / "c.jsonl"
    ident = OPL.evidence_identity_hash()
    base = {"id": "A1_x", "head": "aaaa", "ok": True, "exit_code": 1, "expect": "FAIL", "got": "FAIL",
            "evidence_identity": ident}
    rows = [base,
            dict(base, id="A2_y", ok=False),                                   # failed: never reused
            dict(base, id="A3_z", head="bbbb"),                                # changed HEAD (covers base, gate, roster, driver, campaign)
            dict(base, id="A4_w", evidence_identity="stale-env"),              # changed interpreter/dependency semantics
            {"id": "A5_v", "head": "aaaa", "ok": True},                        # incomplete record: MISS
            ]
    jsonl.write_text("\n".join(json.dumps(r) for r in rows) + "\ngarbage{{\n", encoding="utf-8")
    assert set(camp.completed_cases(jsonl, "aaaa", ident)) == {"A1_x"}
    assert camp.completed_cases(jsonl, "bbbb", ident) and set(camp.completed_cases(jsonl, "bbbb", ident)) == {"A3_z"}
    # materially changed interpreter / dependency semantics -> a different identity -> remeasure
    monkeypatch.setattr(OPL, "verification_evidence_identity",
                        lambda: {"python": "CPython 3.99", "packages": {"psutil": "0.0"}})
    assert camp.completed_cases(jsonl, "aaaa", camp.evidence_identity()) == {}


def test_irrelevant_environment_change_is_proven_immaterial(monkeypatch):
    before = OPL.evidence_identity_hash()
    monkeypatch.setenv("TEMP_PROBE_IRRELEVANT", "1")
    monkeypatch.setenv("ED_RATCHET_NO_WRITE", "1")     # decides whether advisory debt is WRITTEN, never counted
    assert OPL.evidence_identity_hash() == before
    assert "openpyxl" not in OPL.verification_evidence_identity()["packages"]


def test_campaign_reuses_a_recorded_case_instead_of_running_the_gate(tmp_path, monkeypatch, idle):
    camp = _campaign()
    monkeypatch.setattr(camp, "_git", lambda repo, *a, **k: "deadbeefcafe\n" if a[:1] == ("rev-parse",) else "")
    head = "deadbeefcafe"
    out = tmp_path / "camp.json"
    jsonl = tmp_path / "camp.jsonl"
    rec = {"head": head, "id": "A5_new_root_production_module", "ok": True, "exit_code": 1,
           "expect": "FAIL", "got": "FAIL", "seconds": 1.0, "base_side_cached": True,
           "ended_utc": "2026-09-04T00:00:00Z", "evidence_identity": camp.evidence_identity()}
    jsonl.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    spawned: list[list[str]] = []

    def fake_run(argv, *a, **k):
        spawned.append(argv)
        raise AssertionError("the gate must not be spawned for a reused case")
    monkeypatch.setattr(camp.subprocess, "run", fake_run)
    monkeypatch.setattr(camp.shutil, "rmtree", lambda *a, **k: None)
    rc = camp.main(["--only", "A5_", "--out", str(out), "--skip-preflight"])
    OPL.release_heavy_launch()
    assert rc == 0 and spawned == []
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["cases"][0]["reused"] is True and payload["all_ok"] is True


def _git(repo: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    out = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=env)
    assert out.returncode == 0, (args, out.stderr)
    return out.stdout


def test_base_cache_key_follows_base_gate_driver_and_environment(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "tools").mkdir()
    (repo / "tools" / "check_institutional_correctness.py").write_text("CHECKS = []\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "gate v1")
    monkeypatch.setattr(GATE, "REPO", repo)
    k1 = GATE._base_cache_key("HEAD")
    assert k1 and GATE._base_cache_key("HEAD") == k1, "identical evidence identity -> reuse"
    (repo / "tools" / "check_institutional_correctness.py").write_text("CHECKS = [1]\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "gate v2")
    k2 = GATE._base_cache_key("HEAD")
    assert k2 and k2 != k1, "changed gate / base -> remeasure"
    assert GATE._base_cache_key("HEAD~1") == k1, "the old base keeps its identity"
    monkeypatch.setattr(OPL, "verification_evidence_identity",
                        lambda: {"python": "CPython 3.99", "packages": {"psutil": "0.0"}})
    assert GATE._base_cache_key("HEAD~1") != k1, "changed interpreter / dependency semantics -> remeasure"
    assert GATE._base_cache_key("no-such-ref") is None


def test_base_cache_corrupt_entry_is_a_miss_never_a_pass(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    monkeypatch.setattr(GATE, "REPO", repo)
    GATE._write_base_cache("k1", {"x": 1}, "abc", {"r"})
    assert GATE._read_base_cache("k1") is not None
    path = GATE._base_cache_path()
    path.write_text('{"entries": {"k1": {"counts": "not-a-map"}}}', encoding="utf-8")
    assert GATE._read_base_cache("k1") is None
    path.write_text("{garbage", encoding="utf-8")
    assert GATE._read_base_cache("k1") is None
    assert GATE._read_base_cache(None) is None


def test_base_cache_is_shared_across_worktrees_and_multi_entry(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "--detach", "-q", str(wt), "HEAD")
    try:
        monkeypatch.setattr(GATE, "REPO", repo)
        GATE._write_base_cache("k-main", {"x": 1}, "abc", {"r"})
        monkeypatch.setattr(GATE, "REPO", wt)
        GATE._write_base_cache("k-wt", {"y": 2}, "def", {"s"})
        assert GATE._read_base_cache("k-main") is not None
        assert GATE._read_base_cache("k-wt") is not None
        monkeypatch.setattr(GATE, "REPO", repo)
        assert GATE._read_base_cache("k-wt")[0] == {"y": 2}
    finally:
        _git(repo, "worktree", "remove", "--force", str(wt))


# ── the classes deliberately NOT mechanised are named, not pretended ─────────────────

def test_the_process_document_classifies_every_requirement_and_names_the_undetectable():
    text = (ROOT / "governance" / "AGENT_OPERATING_PROCESS_V1.md").read_text(encoding="utf-8")
    for cls in ("MECHANICALLY_ENFORCEABLE_EXISTING_OWNER", "DECLARATIVE_ONLY", "NOT_RELIABLY_DETECTABLE"):
        assert cls in text
    assert "ONE authorization path" in text and "start-up window is closed" in text
    law = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Verification discipline (RC-517)" in law and "Self-healing rule (RC-517)" in law
    assert "ONE authorization path (RC-519)" in law
    rehab = (ROOT / "governance" / "REHAB_PROGRAM.md").read_text(encoding="utf-8")
    assert "files this mission touched" not in rehab and "materially connected path" in rehab
