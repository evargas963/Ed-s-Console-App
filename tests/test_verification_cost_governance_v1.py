"""RC-517 — verification-cost governance: the mechanically enforceable part, attacked.

Observed 2026-09-04 (two agents, independently): a real-boundary campaign launched beside an
8-worker pytest-full wave; 43 minutes of blind waiting; a serial campaign that lost every
completed case to one crash; unchanged base-side proof recomputed. AGENTS.md now states the
verification discipline; THIS file proves the three classes that have an existing mechanical
owner and documents, by name, the classes that deliberately do not.

Every control drives the real entrypoint (`process_lock_guard.pretooluse_block`, the lock's
inventory, the campaign's reuse, the delta gate's cache key) and carries a mutation control
where removing the protection must let the attack through again.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.check_delta_adds_no_debt as GATE  # noqa: E402
import tools.operating_process_lock as OPL  # noqa: E402
import tools.process_lock_guard as plg  # noqa: E402

CAMPAIGN = ROOT / "tests" / "institutional_e2e_boundary_campaign.py"


def _campaign():
    spec = importlib.util.spec_from_file_location("e2e_campaign", CAMPAIGN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FAKE_WAVE = [{"pid": 4242, "kind": "institutional_e2e_boundary_campaign", "age_seconds": 2580,
              "cpu_seconds": 1900.5, "children": 3,
              "command": "python tests/institutional_e2e_boundary_campaign.py --base-group dup"}]


# ── what counts as a heavy wave (judged on the command, never on prose) ─────────────

@pytest.mark.parametrize("cmd,kind", [
    ("python -m pytest -n 8 --dist loadfile -q", "pytest-parallel"),
    (".venv/Scripts/python.exe -m pytest -n auto", "pytest-parallel"),
    ("python -m pytest", "pytest-whole-suite"),
    ("python -m pytest tests/ -q", "pytest-whole-suite"),
    ("make test-all", "e2e-suite"),
    ("npm run test:e2e", "e2e-suite"),
    ("python tools/check_delta_adds_no_debt.py --index --base origin/main", "check_delta_adds_no_debt"),
    ("python tools/check_institutional_correctness.py --enforced-only", "check_institutional_correctness"),
    ("python tests/institutional_e2e_boundary_campaign.py --parallel --out x.json", "institutional_e2e_boundary_campaign"),
])
def test_heavy_wave_commands_are_recognised(cmd, kind):
    assert OPL.heavy_verification_kind(cmd) == kind


@pytest.mark.parametrize("cmd", [
    "python -m pytest tests/test_one_producer_gate_v1.py -q",
    "python -m pytest tests/test_x.py::test_a -q -p no:cacheprovider",
    "python -m pytest tests/test_a.py tests/test_b.py -k collision",
    "python tools/operating_process_lock.py --heavy-jobs",
    "python tools/check_institutional_correctness.py --rebaseline",
    "git status --short",
    "python -c \"import tools.check_institutional_correctness as C; print(len(C.CHECKS))\"",
])
def test_targeted_and_light_commands_are_not_heavy(cmd):
    assert OPL.heavy_verification_kind(cmd) is None


# ── observed failure 2: competing full pytest while the campaign is alive → BLOCK ────

def test_attack_competing_pytest_wave_while_campaign_alive_is_blocked(monkeypatch):
    monkeypatch.setattr(OPL, "heavy_verification_jobs", lambda exclude_pids=None: list(FAKE_WAVE))
    bad = plg.pretooluse_block("Bash", {"command": "python -m pytest -n 8 --dist loadfile -q"})
    assert bad and "COMPETING_HEAVY_VERIFICATION" in bad[0], bad
    assert "pid 4242" in bad[0] and "--heavy-jobs" in bad[0], "the block must name the job and the evidence tool"


def test_attack_second_campaign_or_delta_gate_beside_a_wave_is_blocked(monkeypatch):
    monkeypatch.setattr(OPL, "heavy_verification_jobs", lambda exclude_pids=None: list(FAKE_WAVE))
    for cmd in ("python tests/institutional_e2e_boundary_campaign.py --out y.json",
                "python tools/check_delta_adds_no_debt.py --index"):
        assert plg.pretooluse_block("Bash", {"command": cmd}), cmd


def test_control_targeted_run_beside_a_wave_passes(monkeypatch):
    monkeypatch.setattr(OPL, "heavy_verification_jobs", lambda exclude_pids=None: list(FAKE_WAVE))
    assert plg.pretooluse_block("Bash", {"command": "python -m pytest tests/test_one_producer_gate_v1.py -q"}) == []


def test_control_heavy_launch_on_an_idle_host_passes(monkeypatch):
    monkeypatch.setattr(OPL, "heavy_verification_jobs", lambda exclude_pids=None: [])
    assert plg.pretooluse_block("Bash", {"command": "python -m pytest -n 8 -q"}) == []


def test_mutation_control_removing_the_clause_reopens_the_attack(monkeypatch):
    monkeypatch.setattr(OPL, "heavy_verification_jobs", lambda exclude_pids=None: list(FAKE_WAVE))
    monkeypatch.setattr(OPL, "competing_heavy_verification_violations", lambda cmd, jobs=None: [])
    assert plg.pretooluse_block("Bash", {"command": "python -m pytest -n 8 -q"}) == [], (
        "with the clause removed the attack must walk through — otherwise this test proves nothing")


def test_heredoc_body_is_data_not_a_launch(monkeypatch):
    """A heredoc that MENTIONS pytest -n is data (the executed part is `cat`)."""
    monkeypatch.setattr(OPL, "heavy_verification_jobs", lambda exclude_pids=None: list(FAKE_WAVE))
    cmd = "cat > notes.md <<'EOF'\nrun python -m pytest -n 8 later\nEOF"
    assert plg.pretooluse_block("Bash", {"command": cmd}) == []


# ── the inventory is real, excludes itself, and is the evidence tool ─────────────────

def test_inventory_excludes_the_pytest_it_runs_in_and_reports_real_fields():
    jobs = OPL.heavy_verification_jobs()
    assert os.getpid() not in {j["pid"] for j in jobs}, "a guard inside pytest must not report that pytest"
    for j in jobs:
        assert {"pid", "kind", "age_seconds", "cpu_seconds", "command"} <= set(j)


def test_heavy_jobs_cli_prints_a_timestamped_inventory():
    p = subprocess.run([sys.executable, "tools/operating_process_lock.py", "--heavy-jobs"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr
    doc = json.loads(p.stdout)
    assert "measured_at_utc" in doc and isinstance(doc["heavy_jobs"], list)


def test_psutil_absent_is_unmeasurable_not_clean(monkeypatch):
    real_import = __import__

    def no_psutil(name, *a, **k):
        if name == "psutil":
            raise ImportError("psutil removed")
        return real_import(name, *a, **k)
    monkeypatch.setattr("builtins.__import__", no_psutil)
    jobs = OPL.heavy_verification_jobs()
    assert jobs and jobs[0]["kind"] == "UNMEASURABLE"
    assert OPL.competing_heavy_verification_violations("python -m pytest -n 8", jobs), (
        "an inventory that cannot look must block a heavy launch, never wave it through")


# ── observed failure 4: restart-all after one group fails → completed proof is REUSED ─

def test_completed_proof_for_the_same_head_is_reused_and_other_heads_are_not(tmp_path):
    camp = _campaign()
    jsonl = tmp_path / "c.jsonl"
    rows = [
        {"head": "aaaa", "id": "A1_x", "ok": True, "exit_code": 1},
        {"head": "aaaa", "id": "A2_y", "ok": False, "exit_code": 0},     # failed: never reused
        {"head": "bbbb", "id": "A3_z", "ok": True, "exit_code": 1},      # other head: not ours
    ]
    jsonl.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    done = camp.completed_cases(jsonl, "aaaa")
    assert set(done) == {"A1_x"}
    assert camp.completed_cases(None, "aaaa") == {}


def test_campaign_reuses_a_recorded_case_instead_of_running_the_gate(tmp_path, monkeypatch):
    """The real main(): a case recorded ok for THIS head is reused and the delta gate is
    never spawned. `--force` re-measures."""
    camp = _campaign()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    out = tmp_path / "camp.json"
    jsonl = tmp_path / "camp.jsonl"
    rec = {"head": head, "id": "A5_new_root_production_module", "ok": True, "exit_code": 1,
           "expect": "FAIL", "got": "FAIL", "seconds": 1.0, "base_side_cached": True,
           "ended_utc": "2026-09-04T00:00:00Z"}
    jsonl.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    spawned: list[list[str]] = []
    real_run = camp.subprocess.run

    def fake_run(argv, *a, **k):
        if any("check_delta_adds_no_debt.py" in str(x) for x in argv):
            spawned.append(argv)
            raise AssertionError("the gate must not be spawned for a reused case")
        return real_run(argv, *a, **k)          # git plumbing for the worktree is fine
    monkeypatch.setattr(camp.subprocess, "run", fake_run)
    rc = camp.main(["--only", "A5_", "--out", str(out), "--skip-preflight"])
    assert rc == 0 and spawned == []
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["cases"][0]["reused"] is True and payload["all_ok"] is True


# ── observed failure 5: unchanged base-side proof recomputed → identity-keyed cache ───

def _git(repo: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    out = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=env)
    assert out.returncode == 0, (args, out.stderr)
    return out.stdout


def test_base_cache_key_follows_the_gate_blob_and_the_base_commit(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "tools").mkdir()
    (repo / "tools" / "check_institutional_correctness.py").write_text("CHECKS = []\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "gate v1")
    monkeypatch.setattr(GATE, "REPO", repo)
    k1 = GATE._base_cache_key("HEAD")
    assert k1 and GATE._base_cache_key("HEAD") == k1, "same base, same gate -> same identity"
    (repo / "tools" / "check_institutional_correctness.py").write_text("CHECKS = [1]\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "gate v2")
    k2 = GATE._base_cache_key("HEAD")
    assert k2 and k2 != k1, "a changed gate is a different measurement identity"
    assert GATE._base_cache_key("HEAD~1") == k1, "the old base keeps its identity"
    assert GATE._base_cache_key("no-such-ref") is None


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
        assert GATE._read_base_cache("k-main") is not None, "an entry written in the primary is visible from the linked worktree"
        assert GATE._read_base_cache("k-wt") is not None, "and the linked worktree's entry did not evict it"
        monkeypatch.setattr(GATE, "REPO", repo)
        assert GATE._read_base_cache("k-wt")[0] == {"y": 2}
    finally:
        _git(repo, "worktree", "remove", "--force", str(wt))


# ── the classes deliberately NOT mechanised are named, not pretended ─────────────────

def test_the_process_document_classifies_every_requirement_and_names_the_undetectable():
    text = (ROOT / "governance" / "AGENT_OPERATING_PROCESS_V1.md").read_text(encoding="utf-8")
    for cls in ("MECHANICALLY_ENFORCEABLE_EXISTING_OWNER", "DECLARATIVE_ONLY", "NOT_RELIABLY_DETECTABLE"):
        assert cls in text
    law = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Verification discipline (RC-517)" in law and "Self-healing rule (RC-517)" in law
    # the guard exists for the one class with a mechanical owner, and nothing pretends more
    assert "competing_heavy_verification_violations" in (ROOT / "tools" / "process_lock_guard.py").read_text(encoding="utf-8")
