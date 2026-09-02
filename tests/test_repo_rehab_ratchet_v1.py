"""RC-505 — the repo rehabilitation ratchet: block NEW divergence, never inherited debt.

Every case builds a REAL git repository with a base commit and a candidate commit and runs the
real `ratchet()`. Nothing is stubbed, because what is under test is a comparison of two git
trees — a stubbed tree would prove the stub.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.repo_rehab_status as R  # noqa: E402


def _git(root: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=str(root), capture_output=True, text=True, timeout=60)


def _repo(tmp_path: Path, name: str, base: dict[str, str], head: dict[str, str] | None,
          removed: tuple[str, ...] = ()) -> Path:
    """A repo whose `main` holds `base` and whose `cand` branch applies `head` + `removed`."""
    root = tmp_path / name
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "a@b.c")
    _git(root, "config", "user.name", "t")
    for rel, body in base.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    _git(root, "checkout", "-qb", "cand")
    if head or removed:
        for rel, body in (head or {}).items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        for rel in removed:
            (root / rel).unlink(missing_ok=True)
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "candidate")
    return root


#: A workflow that DOES invoke the ratchet, so self-protection has something to protect.
WF_OK = ("jobs:\n  hardening:\n    steps:\n"
         "      - run: python tools/repo_rehab_status.py --ratchet --base origin/main\n")
BASE = {
    ".github/workflows/hardening.yml": WF_OK,
    "tools/repo_rehab_status.py": "# the ratchet\n",
    "app/domain/value.py": "X = 1\n",
    "legacy_module.py": "Y = 2\n",
    "reports/old.json": "{}\n",
}


def _bad(root: Path) -> list[str]:
    return R.ratchet("main", "cand", root)


# ── regressions must BLOCK ────────────────────────────────────────────────────────────────
def test_new_root_production_module_blocks(tmp_path):
    bad = _bad(_repo(tmp_path, "a", BASE, {"new_thing.py": "Z = 3\n"}))
    assert any("NEW ROOT PRODUCTION MODULE" in b for b in bad), bad


@pytest.mark.parametrize("rel", [
    "data/ed_console.db", "logs/app.log", "backups/db/snap.db",
    "models/active/SPY/xgb.pkl", "app/models/trained.pt",
])
def test_new_tracked_runtime_state_blocks(tmp_path, rel):
    bad = _bad(_repo(tmp_path, "b" + rel.replace("/", "_"), BASE, {rel: "x\n"}))
    assert any("NEW TRACKED RUNTIME" in b for b in bad), (rel, bad)


def test_growth_in_a_legacy_directory_blocks(tmp_path):
    bad = _bad(_repo(tmp_path, "c", BASE, {"reports/another.json": "{}\n"}))
    assert any("LEGACY-DIRECTORY GROWTH" in b for b in bad), bad


# ── defect 5: a NEW non-TARGET top-level directory, detected dynamically ──────────────────
@pytest.mark.parametrize("rel", [
    "newthing/mod.py", "experiments/run.py", "lib/util.py", "src/main.py",
])
def test_new_non_target_top_level_directory_blocks(tmp_path, rel):
    """Dynamic, not a hardcoded list: anything that is neither TARGET source nor a legacy
    directory with a stated disposition is a NEW unexplained difference."""
    bad = _bad(_repo(tmp_path, "p" + rel.split("/")[0], BASE, {rel: "X = 1\n"}))
    assert any("NEW NON-TARGET TOP-LEVEL DIRECTORY" in b for b in bad), (rel, bad)


@pytest.mark.parametrize("rel", [
    "app/domain/more.py", "research/study.py", "tests/test_a.py", "tools/t.py",
    "static/x.js", "config/settings.toml", "governance/note.md", "docs/guide.md",
])
def test_target_top_level_directories_pass(tmp_path, rel):
    """...and every TARGET directory is fine, including docs/ which the operator added."""
    bad = _bad(_repo(tmp_path, "q" + rel.replace("/", "_"), BASE, {rel: "x\n"}))
    assert not any("NON-TARGET TOP-LEVEL" in b for b in bad), (rel, bad)


def test_every_legacy_directory_has_a_stated_disposition():
    """The goal is 'unexplained difference = NONE'. A directory with no destination can never
    reach it, so each one is named with where it goes."""
    import tools.repo_rehab_status as M

    for d in ("reports", "models", "docs", "calibration", "features", "arch_competition",
              "v2_decision", "verification", "planes", "schwab_field_inventory",
              "snapshot_sql", "scripts", "backups", "data"):
        assert d in M.TARGET["legacy_disposition"] or d in M.TARGET["source_top_level"], d


# ── defect 5b: inherited root shims pass; reintroduced root ownership blocks ──────────────
def test_unchanged_inherited_root_shim_passes(tmp_path):
    bad = _bad(_repo(tmp_path, "r", BASE, None))
    assert not any("ROOT" in b for b in bad), bad


def test_reintroduced_root_ownership_blocks(tmp_path):
    """The same module owned under app/ AND at the root in the same tree is two owners for one
    thing — the duplicate authority this rehabilitation removes."""
    bad = _bad(_repo(tmp_path, "s", BASE, {"value.py": "X = 1\n"}))
    assert any("ROOT OWNERSHIP REINTRODUCED" in b for b in bad), bad


def test_migrated_code_moving_back_toward_root_blocks(tmp_path):
    """app/domain/value.py exists at base; deleting it and re-owning it at the root runs the
    one-way street backwards."""
    bad = _bad(_repo(tmp_path, "d", BASE, {"value.py": "X = 1\n"},
                     removed=("app/domain/value.py",)))
    assert any("MOVED BACK TOWARD ROOT" in b for b in bad), bad


def test_forbidden_dependency_direction_blocks(tmp_path):
    """app/domain is the leaf: it may import nothing else in app/."""
    bad = _bad(_repo(tmp_path, "e", BASE,
                     {"app/domain/value.py": "from app.api import router\nX = 1\n"}))
    assert any("FORBIDDEN DEPENDENCY DIRECTION" in b for b in bad), bad


def test_allowed_dependency_direction_passes(tmp_path):
    """...and the rule is narrow: app/decision may import app/domain."""
    bad = _bad(_repo(tmp_path, "f", BASE,
                     {"app/decision/call.py": "from app.domain import value\n"}))
    assert not any("DEPENDENCY DIRECTION" in b for b in bad), bad


# ── self-protection ───────────────────────────────────────────────────────────────────────
def test_removing_the_ratchet_from_required_ci_blocks(tmp_path):
    bad = _bad(_repo(tmp_path, "g", BASE,
                     {".github/workflows/hardening.yml": "jobs:\n  hardening:\n    steps: []\n"}))
    assert any("REMOVED FROM REQUIRED CI" in b for b in bad), bad


def test_deleting_the_ratchet_blocks(tmp_path):
    bad = _bad(_repo(tmp_path, "h", BASE, {}, removed=("tools/repo_rehab_status.py",)))
    assert any("RATCHET DELETED" in b for b in bad), bad


@pytest.mark.parametrize("step", [
    "      - run: python tools/repo_rehab_status.py --base origin/main\n",          # no --ratchet
    "      - run: python tools/repo_rehab_status.py --ratchet --base origin/main || true\n",
])
def test_demoting_the_ratchet_to_advisory_blocks(tmp_path, step):
    bad = _bad(_repo(tmp_path, "i" + str(abs(hash(step))), BASE,
                     {".github/workflows/hardening.yml":
                      "jobs:\n  hardening:\n    steps:\n" + step}))
    assert any("DEMOTED" in b for b in bad), bad


# ── legitimate work must PASS ─────────────────────────────────────────────────────────────
def test_unchanged_inherited_debt_passes(tmp_path):
    """147 root modules and 224 trained blobs may stay. The ratchet blocks GROWTH, not history."""
    assert _bad(_repo(tmp_path, "j", BASE, None)) == []


def test_migration_toward_the_target_passes(tmp_path):
    """The intended move: a root module becomes an app package member and the root copy dies."""
    bad = _bad(_repo(tmp_path, "k", BASE, {"app/domain/legacy_module.py": "Y = 2\n"},
                     removed=("legacy_module.py",)))
    assert bad == [], bad


def test_deleting_inherited_debt_passes(tmp_path):
    bad = _bad(_repo(tmp_path, "l", BASE, {}, removed=("reports/old.json",)))
    assert bad == [], bad


def test_ordinary_product_work_in_an_existing_module_passes(tmp_path):
    bad = _bad(_repo(tmp_path, "m", BASE, {"legacy_module.py": "Y = 2\nZ = 3  # a bug fix\n"}))
    assert bad == [], bad


def test_new_tests_and_tools_pass(tmp_path):
    bad = _bad(_repo(tmp_path, "n", BASE,
                     {"tests/test_new.py": "def test_x():\n    assert True\n",
                      "tools/new_helper.py": "def f():\n    return 1\n"}))
    assert bad == [], bad


# ── the target may not move to make the score improve ─────────────────────────────────────
def test_target_is_hash_pinned():
    """RC-505: a rehabilitation that can redefine "done" measures nothing. Changing any value
    in TARGET changes this digest and fails here — which is the intended friction, because the
    target belongs to the operator."""
    import hashlib
    import json

    expect = hashlib.sha256(
        json.dumps(R.TARGET, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert R.TARGET_SHA256 == expect, "the digest must be computed from TARGET, not stored"
    # 3b7fe749… is the target as the operator ruled it on 2026-09-02: app/models KEPT, docs/
    # ADDED, every legacy directory dispositioned. It replaced 23b688a7… in that same reviewed
    # delta — which is the sanctioned path, and the reason this assertion fired at all.
    assert R.TARGET_SHA256.startswith("3b7fe74975d7f86b"), (
        "TARGET changed. That is not forbidden — it is the OPERATOR's to change — but it may "
        "not happen silently: update this pin in the same reviewed delta. Note the pin alone "
        "is NOT the protection; the ratchet also compares the BASE ref's target, so a delta "
        "that moves target+pin+test together is still refused.")
    assert R.TARGET["root_production_modules"] == 0
    assert R.TARGET["tracked_runtime_artifacts"] == 0
    assert R.TARGET["app_packages"] == [
        "api", "domain", "market_data", "options", "signals", "models", "decision",
        "infrastructure"]


def test_current_is_generated_not_declared():
    """CURRENT must come from the tree. A hand-entered number would make the whole report a
    claim rather than a measurement."""
    cur = R.current("HEAD", ROOT, with_loc=False)
    tracked = len(R.tracked_files("HEAD", ROOT))
    assert cur["tracked_files"] == tracked > 0
    assert cur["root_production_modules"] == len(
        [f for f in R.tracked_files("HEAD", ROOT) if "/" not in f and f.endswith(".py")])


# ── defect 4: TARGET drift blocks BASE->HEAD, even when target+pin+test move together ────
def _tool_src(target_literal: str) -> str:
    """A minimal module the ratchet can parse a TARGET out of."""
    return f"TARGET: dict = {target_literal}\n"


def test_target_drift_blocks_even_when_pin_and_tests_change_together(tmp_path):
    """THE POINT OF THIS CONTROL. A delta can edit the target, update the hash pin and update
    the asserting test in one commit — every test it ships with then passes. Only a comparison
    against the BASE ref can see it, which is why the ratchet re-derives the base's TARGET
    instead of trusting the digest that travelled with the change."""
    base = {**BASE, "tools/repo_rehab_status.py": _tool_src("{'root_production_modules': 0}")}
    head = {"tools/repo_rehab_status.py": _tool_src("{'root_production_modules': 147}")}
    bad = _bad(_repo(tmp_path, "t", base, head))
    assert any("TARGET DRIFT" in b for b in bad), bad
    assert any("root_production_modules" in b for b in bad), bad


def test_an_unchanged_target_passes(tmp_path):
    same = _tool_src("{'root_production_modules': 0}")
    bad = _bad(_repo(tmp_path, "u", {**BASE, "tools/repo_rehab_status.py": same},
                     {"tools/other.py": "x = 1\n"}))
    assert not any("TARGET DRIFT" in b for b in bad), bad


def test_an_unreadable_target_at_head_blocks(tmp_path):
    """Unmeasurable is not compliant: if HEAD no longer defines a literal TARGET, drift cannot
    be measured, so it is refused rather than assumed absent."""
    base = {**BASE, "tools/repo_rehab_status.py": _tool_src("{'a': 1}")}
    head = {"tools/repo_rehab_status.py": "TARGET = compute_it()\n"}
    bad = _bad(_repo(tmp_path, "v", base, head))
    assert any("TARGET UNREADABLE AT HEAD" in b for b in bad), bad


def test_the_live_target_carries_the_operator_ruling():
    """KEEP app/models (the app/ml recommendation was rejected); ADD docs/."""
    import tools.repo_rehab_status as M

    assert "models" in M.TARGET["app_packages"]
    assert "ml" not in M.TARGET["app_packages"]
    assert "docs" in M.TARGET["source_top_level"]


# ── defect 1: daily delta vs cumulative ───────────────────────────────────────────────────
def test_daily_delta_measures_from_the_prior_merged_point_not_the_start(tmp_path):
    """TODAY'S DELTA answers 'what moved since yesterday'; START->CURRENT answers 'how far have
    we come'. One number cannot do both, and reporting the cumulative figure as today's makes
    every day after day one look busy."""
    import tools.repo_rehab_status as M

    root = _repo(tmp_path, "w", BASE, {"tools/extra.py": "x = 1\n"})
    prior = M.prior_daily_point("main", hours=0, repo=root)
    assert prior, "the prior merged point is derived from git, not from stored state"
    a = M.current("main", root, with_loc=False)
    b = M.current("cand", root, with_loc=False)
    assert b["tools_py"] == a["tools_py"] + 1


def test_prior_daily_point_is_a_git_fact_and_writes_nothing(tmp_path):
    """No report archive: yesterday is found with rev-list, not read from a file the repo keeps."""
    import tools.repo_rehab_status as M

    root = _repo(tmp_path, "x", BASE, {"tools/extra.py": "x = 1\n"})
    before = {p.name for p in root.iterdir()}
    M.prior_daily_point("main", hours=24, repo=root)
    assert {p.name for p in root.iterdir()} == before


# ── defect 2: CI cannot see the host ──────────────────────────────────────────────────────
def test_host_status_from_ci_is_not_proven(monkeypatch, tmp_path):
    """A CI runner clones into an ephemeral path with no host layout around it. Any
    SEPARATED/VIOLATED verdict there would describe the runner, not the operator's machine."""
    import tools.repo_rehab_status as M

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    h = M.host_separation(tmp_path)
    assert h["state"] == "NOT_PROVEN_FROM_CI", h
    assert h["tracked_runtime_in_source"] is None


def test_local_host_check_looks_for_ed_console_specific_paths():
    """Not generic directory names some other project on the host might own."""
    import tools.repo_rehab_status as M

    assert M.TARGET["host_paths"] == [
        "runtime/EdWebConsole", "recovery/EdWebConsole", "artifacts/EdWebConsole", "worktrees"]


def test_local_host_check_reports_separated_when_the_paths_exist(monkeypatch, tmp_path):
    import tools.repo_rehab_status as M

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)
    src = _repo(tmp_path / "host", "EdWebConsole", {"tools/x.py": "x = 1\n"}, None)
    for p in M.TARGET["host_paths"]:
        (tmp_path / "host" / p).mkdir(parents=True, exist_ok=True)
    h = M.host_separation(src, baseline="main", ref="main")
    assert h["state"] == "SEPARATED", h
    assert all(h["host_paths_present"].values())


def test_host_separation_distinguishes_not_yet_from_violated(tmp_path):
    """Day one is NOT_YET_SEPARATED, not VIOLATED — MEASURED: the first run returned VIOLATED
    for 224 inherited blobs and would have every day until the last one moved, which is a
    signal nobody can act on. VIOLATED means runtime state is being RE-CREATED."""
    root = _repo(tmp_path, "o", {**BASE, "models/a.pkl": "x\n"}, {"models/b.pkl": "y\n"})
    inherited = R.host_separation(root, baseline="main", ref="main")
    assert inherited["state"] == "NOT_YET_SEPARATED", inherited
    growing = R.host_separation(root, baseline="main", ref="cand")
    assert growing["state"] == "VIOLATED", growing
