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


def test_growth_in_an_unmapped_directory_blocks(tmp_path):
    bad = _bad(_repo(tmp_path, "c", BASE, {"reports/another.json": "{}\n"}))
    assert any("UNMAPPED-DIRECTORY GROWTH" in b for b in bad), bad


def test_migrated_code_moving_back_toward_root_blocks(tmp_path):
    """app/domain/value.py exists at base; re-owning it at the root is a one-way street run
    backwards."""
    bad = _bad(_repo(tmp_path, "d", BASE, {"value.py": "X = 1\n"}))
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
    assert R.TARGET_SHA256.startswith("23b688a7b996f724"), (
        "TARGET changed. That is not forbidden — it is the OPERATOR's to change — but it may "
        "not happen silently: update this pin in the same reviewed delta.")
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


def test_host_separation_distinguishes_not_yet_from_violated(tmp_path):
    """Day one is NOT_YET_SEPARATED, not VIOLATED — MEASURED: the first run returned VIOLATED
    for 224 inherited blobs and would have every day until the last one moved, which is a
    signal nobody can act on. VIOLATED means runtime state is being RE-CREATED."""
    root = _repo(tmp_path, "o", {**BASE, "models/a.pkl": "x\n"}, {"models/b.pkl": "y\n"})
    inherited = R.host_separation(root, baseline="main", ref="main")
    assert inherited["state"] == "NOT_YET_SEPARATED", inherited
    growing = R.host_separation(root, baseline="main", ref="cand")
    assert growing["state"] == "VIOLATED", growing
