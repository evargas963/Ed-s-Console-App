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
    assert any("NEW FILES IN A LEGACY DIRECTORY" in b for b in bad), bad


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
#: A real compatibility shim: the migration step that keeps every existing import working.
SHIM = "from app.domain.value import *  # noqa: F401,F403\n"
#: The same stem carrying LOGIC — a second owner, however short.
NOT_A_SHIM = "def compute():\n    return 1\n"
#: A tree that ALREADY contains an inherited same-stem shim, so 'unchanged' is testable.
BASE_WITH_SHIM = {**BASE, "value.py": SHIM}


def test_creating_the_app_module_and_retaining_a_root_shim_passes(tmp_path):
    """THE INTENDED MIGRATION STEP. app/<pkg>/foo.py lands, root foo.py becomes a re-export, and
    every existing import keeps working. Blocking this would force a flag-day rewrite, which is
    the one thing the rehabilitation must not require."""
    base = {k: v for k, v in BASE.items() if k != "app/domain/value.py"}
    base["value.py"] = "def compute():\n    return 1\n"          # root owns it at the base
    bad = _bad(_repo(tmp_path, "r1", base,
                     {"app/domain/value.py": "def compute():\n    return 1\n",
                      "value.py": SHIM}))
    assert bad == [], bad


def test_unchanged_inherited_same_stem_shim_passes(tmp_path):
    """The shim is already there and this delta does not touch it."""
    bad = _bad(_repo(tmp_path, "r2", BASE_WITH_SHIM, {"tools/unrelated.py": "x = 1\n"}))
    assert bad == [], bad


def test_a_root_file_that_still_carries_logic_beside_app_blocks(tmp_path):
    """Two real owners for one module. Short is not the test — a def is."""
    bad = _bad(_repo(tmp_path, "r3", BASE, {"value.py": NOT_A_SHIM}))
    assert any("DUPLICATE PRODUCTION AUTHORITY" in b for b in bad), bad


def test_a_shim_regressing_back_into_a_real_module_blocks(tmp_path):
    """The inherited shim is re-filled with logic: root ownership reintroduced."""
    bad = _bad(_repo(tmp_path, "r4", BASE_WITH_SHIM, {"value.py": SHIM + NOT_A_SHIM}))
    assert any("DUPLICATE PRODUCTION AUTHORITY" in b for b in bad), bad


@pytest.mark.parametrize("body,is_shim", [
    ("from app.domain.value import *\n", True),
    ("from app.domain.value import compute\n__all__ = ['compute']\n", True),
    ('"""doc."""\nfrom app.domain import value\n', True),
    ("import app.domain.value\n", True),
    ("from other.mod import thing\n", False),          # re-export, but not from app/
    ("from app.domain.value import compute\ndef extra():\n    return 2\n", False),
    ("from app.domain.value import compute\nif True:\n    compute()\n", False),
    ("", False),
])
def test_shim_detection_is_structural_not_a_size_heuristic(body, is_shim):
    assert R.is_compatibility_shim(body) is is_shim, body


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
    """147 root modules and 224 trained blobs may stay. The ratchet blocks GROWTH, not history.

    The candidate carries a real (harmless) commit: an EMPTY delta is now its own violation,
    because base==head empties every comparison in the gate."""
    assert _bad(_repo(tmp_path, "j", BASE, {"docs/note.md": "unrelated\n"})) == []


def test_migration_toward_the_target_passes(tmp_path):
    """The intended move: a root module becomes an app package member and the root copy dies."""
    bad = _bad(_repo(tmp_path, "k", BASE, {"app/domain/legacy_module.py": "Y = 2\n"},
                     removed=("legacy_module.py",)))
    assert bad == [], bad


def test_deleting_inherited_debt_passes(tmp_path):
    bad = _bad(_repo(tmp_path, "l", BASE, {}, removed=("reports/old.json",)))
    assert bad == [], bad


def test_product_work_that_grows_a_root_module_on_net_now_blocks(tmp_path):
    """OPERATOR RULE, and a real workflow change worth stating plainly: inherited root LOC may
    remain or shrink, never grow on net. A one-line bug fix in a root module with nothing
    offsetting it is refused — the escape is to put the change in app/, or to pay for it by
    removing at least as much root code in the same delta."""
    bad = _bad(_repo(tmp_path, "m", BASE, {"legacy_module.py": "Y = 2\nZ = 3  # a bug fix\n"}))
    assert any("INHERITED ROOT LOC GREW" in b for b in bad), bad


def test_net_neutral_product_work_across_root_modules_passes(tmp_path):
    """NET, not per-module: growing one root module while shrinking another by as much is not
    growth of the debt, so it passes. This is the escape hatch that keeps the rule survivable."""
    base = {**BASE, "other_legacy.py": "A = 1\nB = 2\nC = 3\n"}
    bad = _bad(_repo(tmp_path, "m2", base,
                     {"legacy_module.py": "Y = 2\nZ = 3\n", "other_legacy.py": "A = 1\n"}))
    assert not any("ROOT LOC" in b for b in bad), bad


def test_the_same_product_work_placed_in_app_passes(tmp_path):
    """The intended direction: new logic goes to app/, and the root file is untouched."""
    bad = _bad(_repo(tmp_path, "m3", BASE, {"app/domain/fix.py": "Z = 3  # a bug fix\n"}))
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
    assert R.TARGET_SHA256.startswith("c1079c06fab96b87"), (
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


# ── independent self-protection: owned OUTSIDE the ratchet it protects ────────────────────
def _ci_gate_violations(tmp_repo: Path, workflow: str | None, tool: bool = True) -> list[str]:
    """Drive the INSTITUTIONAL check (not the ratchet) against a planted tree."""
    import tools.check_institutional_correctness as CIC

    (tmp_repo / "tools").mkdir(parents=True, exist_ok=True)
    (tmp_repo / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    if tool:
        (tmp_repo / "tools" / "repo_rehab_status.py").write_text("# gate\n", encoding="utf-8")
    if workflow is not None:
        (tmp_repo / ".github" / "workflows" / "hardening.yml").write_text(
            workflow, encoding="utf-8")
    old = CIC.REPO
    try:
        CIC.REPO = tmp_repo
        return [str(v.msg) for v in CIC._declared_gate_is_actually_invoked_violations()]
    finally:
        CIC.REPO = old


_LIVE_STEP = ("jobs:\n  hardening:\n    steps:\n"
              "      - run: python tools/repo_rehab_status.py --ratchet --base origin/main\n")


def test_a_live_ratchet_invocation_passes(tmp_path):
    assert _ci_gate_violations(tmp_path / "ok", _LIVE_STEP) == []


def test_deleting_the_ci_invocation_blocks_from_the_institutional_owner(tmp_path):
    """THE POINT: this fires even though the rehab step no longer runs. A self-protection clause
    living inside the ratchet cannot notice its own step being deleted."""
    bad = _ci_gate_violations(tmp_path / "gone", "jobs:\n  hardening:\n    steps: []\n")
    assert any("never runs it" in b for b in bad), bad


def test_commenting_out_the_ci_invocation_blocks(tmp_path):
    """A YAML comment reads like wiring to any substring search over the raw file and enforces
    nothing. The check strips comment lines before looking."""
    wf = ("jobs:\n  hardening:\n    steps:\n"
          "      # - run: python tools/repo_rehab_status.py --ratchet --base origin/main\n")
    bad = _ci_gate_violations(tmp_path / "cmt", wf)
    assert any("COMMENTED OUT" in b for b in bad), bad


@pytest.mark.parametrize("step", [
    "      - run: python tools/repo_rehab_status.py --base origin/main\n",        # no --ratchet
    "      - run: python tools/repo_rehab_status.py --ratchet --base origin/main || true\n",
])
def test_demoting_the_ci_invocation_blocks(tmp_path, step):
    bad = _ci_gate_violations(tmp_path / ("dem" + str(abs(hash(step)))),
                              "jobs:\n  hardening:\n    steps:\n" + step)
    assert any("cannot fail it" in b for b in bad), bad


def test_a_missing_gate_is_reported_against_the_gate_not_the_workflow(tmp_path):
    """Companion to the deletion control below: the violation must name the absent TOOL, so the
    message points at what has to come back rather than at a workflow that is intact."""
    bad = _ci_gate_violations(tmp_path / "none", _LIVE_STEP, tool=False)
    assert any("does not exist in the tree" in b for b in bad), bad


def test_the_live_repo_wires_the_ratchet_into_required_ci():
    """And the real tree satisfies it, so this is not a rule nobody meets."""
    import tools.check_institutional_correctness as CIC

    assert CIC._declared_gate_is_actually_invoked_violations() == []


def test_self_protection_is_not_owned_only_by_the_ratchet():
    """Structural: the institutional catalog must carry the clause, or deleting the rehab step
    would delete its own guard."""
    import tools.check_institutional_correctness as CIC

    assert hasattr(CIC, "_declared_gate_is_actually_invoked_violations")
    src = Path(CIC.__file__).read_text(encoding="utf-8")
    assert "_declared_gate_is_actually_invoked_violations()" in src, "must be CALLED, not just defined"
    names = {n for n, _f, e in CIC.CHECKS if e}
    assert "scheduled_producers_are_not_inert" in names, "the calling check must be ENFORCED"


# ── FINAL HARDENING: the bypasses the independent reviews accepted ───────────────────────
def test_growing_an_inherited_root_module_blocks(tmp_path):
    """START_SHA root debt may remain or shrink — feeding it is drift wearing inherited debt's
    name. MEASURED before this rule: +33 LOC landed in one day and passed."""
    bad = _bad(_repo(tmp_path, "h1", BASE, {"legacy_module.py": "Y = 2\n" + "Z = 3\n" * 20}))
    assert any("INHERITED ROOT LOC GREW" in b for b in bad), bad


def test_shrinking_an_inherited_root_module_passes(tmp_path):
    bad = _bad(_repo(tmp_path, "h2", {**BASE, "legacy_module.py": "Y = 2\n" * 30},
                     {"legacy_module.py": "Y = 2\n"}))
    assert not any("ROOT LOC" in b for b in bad), bad


@pytest.mark.parametrize("rel", [
    "app/loose.py",                       # directly under app/, in no package
    "app/undeclared_pkg/mod.py",          # a package the TARGET never declared
    "app/models/sub/deep.py",             # declared package, nested — must PASS
])
def test_undeclared_app_children_block_and_declared_ones_pass(tmp_path, rel):
    bad = _bad(_repo(tmp_path, "h3" + rel.replace("/", "_"), BASE, {rel: "X = 1\n"}))
    hit = any("UNDECLARED APP CHILD" in b for b in bad)
    assert hit is (not rel.startswith("app/models/")), (rel, bad)


def test_the_app_package_initializer_is_not_an_undeclared_child(tmp_path):
    """`app/__init__.py` is what MAKES app/ a package, so demanding it live inside a package is
    circular. MEASURED: the rule as first written refused it, and required CI failed on the day
    the skeleton landed — the ratchet blocking the first legitimate step toward its own TARGET.
    It passed locally only because the ratchet was run before the commit, so `ls-tree HEAD`
    could not yet see an untracked file."""
    bad = _bad(_repo(tmp_path, "h3init", BASE, {"app/__init__.py": '"""pkg."""\n'}))
    assert not any("UNDECLARED APP CHILD" in b for b in bad), bad


@pytest.mark.parametrize("rel", [
    "app/helper.py",
    "app/__main__.py",
    "app/utils/__init__.py",
])
def test_the_initializer_exception_is_one_exact_path_not_a_pattern(tmp_path, rel):
    """The escape must not widen into 'anything at app/ top level' or 'any __init__.py'.
    Without this, the fix for the CI failure would have opened the hole the rule closes."""
    bad = _bad(_repo(tmp_path, "h3x" + rel.replace("/", "_"), BASE, {rel: "X = 1\n"}))
    assert any("UNDECLARED APP CHILD" in b for b in bad), (rel, bad)


@pytest.mark.parametrize("rel,blocks", [
    (".internal/mod.py", True),           # dot-prefixed top level was a blind spot
    (".hidden/data.py", True),
    (".github/workflows/x.yml", False),   # declared
    (".claude/settings.json", False),
])
def test_dot_prefixed_top_level_population_is_closed(tmp_path, rel, blocks):
    bad = _bad(_repo(tmp_path, "h4" + rel.replace("/", "_").replace(".", "d"), BASE,
                     {rel: "x\n"}))
    assert any("NON-TARGET TOP-LEVEL" in b for b in bad) is blocks, (rel, bad)


_APP_BASE = {**BASE, "app/domain/value.py": "X = 1\n"}


@pytest.mark.parametrize("body", [
    "import legacy_module\n",                                   # absolute root module
    "from legacy_module import Y\n",                            # from-import of a root module
    "from reports import thing\n",                              # legacy directory
    "import importlib\nm = importlib.import_module('legacy_module')\n",   # dynamic, literal
    "def f():\n    import legacy_module\n    return legacy_module\n",     # nested in a function
    "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import legacy_module\n",
])
def test_app_to_legacy_dependency_growth_blocks_for_every_import_form(tmp_path, body):
    """A rule that only reads module-scope `import x` is a rule about formatting."""
    bad = _bad(_repo(tmp_path, "h5" + str(abs(hash(body))), _APP_BASE,
                     {"app/domain/uses.py": body}))
    assert any("APP->LEGACY DEPENDENCIES GREW" in b for b in bad), (body, bad)


def test_app_to_legacy_dependency_shrinking_passes(tmp_path):
    base = {**_APP_BASE, "app/domain/uses.py": "import legacy_module\n"}
    bad = _bad(_repo(tmp_path, "h6", base, {"app/domain/uses.py": "X = 2\n"}))
    assert not any("APP->LEGACY" in b for b in bad), bad


def test_relative_imports_inside_app_are_direction_checked(tmp_path):
    """`from ...api import x` inside app/domain must be caught like the absolute form."""
    bad = _bad(_repo(tmp_path, "h7", BASE,
                     {"app/domain/rel.py": "from ..api import router\n"}))
    assert any("FORBIDDEN DEPENDENCY DIRECTION" in b for b in bad), bad


@pytest.mark.parametrize("name,size,sample,expected", [
    ("weights.safetensors", 10, b"", True),        # extension the old list never had
    ("blob.unknownext", 5, b"\x00\x01\x02", True),  # binary content, unknown suffix
    ("dump.unknownext", 2_000_000, b"text", True),  # large + not known source
    ("mod.py", 2_000_000, b"def f(): pass", False),  # large but known source
    ("notes.md", 10, b"# hi", False),
])
def test_generated_state_detection_is_structural_not_only_suffix(name, size, sample, expected):
    """A suffix list can always be stepped around by choosing another name — the same failure
    mode as deciding enforcement by vocabulary."""
    assert R.is_generated_state(name, size, sample) is expected, name


def test_physical_host_scan_counts_ignored_files(tmp_path):
    """THE SEVERE ONE. .gitignore on this repository already carries models/**, data/*,
    backups/db/* and logs/, so a tracked-file rule cannot see new contamination at all, and
    `git rm --cached` would have reported 224 -> 0 while every byte stayed on disk."""
    src = tmp_path / "src"
    (src / "models" / "active").mkdir(parents=True)
    (src / ".gitignore").write_text("models/**\n", encoding="utf-8")
    (src / "models" / "active" / "m.pt").write_bytes(b"\x00binary")
    found = R.physical_generated_state(src)
    assert any(f.endswith("m.pt") for f in found), found


def test_physical_scan_skips_tool_caches(tmp_path):
    src = tmp_path / "src2"
    (src / ".mypy_cache").mkdir(parents=True)
    (src / ".mypy_cache" / "c.db").write_bytes(b"x")
    assert R.physical_generated_state(src) == []


def test_the_rehab_files_are_protected_by_test_ownership():
    """Tests are not CHECKS, so nothing else noticed the suite being deleted."""
    import tools.gate_test_ownership as G

    assert "tools/repo_rehab_status.py" in G.SELF_PROTECTED_PATHS
    assert "tests/test_repo_rehab_ratchet_v1.py" in G.SELF_PROTECTED_PATHS


def test_the_trust_root_is_named_and_not_claimed_to_be_in_repo():
    """Every protection here runs from the pull request's own code, so a delta can weaken the
    checker and ship the weakened checker together. The recursion terminates OUTSIDE the
    repository, and saying otherwise would be the false-enforcement defect this repo removed."""
    assert len(R.TRUST_ANCHOR_LOCK_SURFACE) >= 8
    for p in (".github/workflows/hardening.yml", "tools/repo_rehab_status.py",
              "tools/check_institutional_correctness.py", "tools/check_delta_adds_no_debt.py",
              "tests/test_repo_rehab_ratchet_v1.py", "tools/gate_test_ownership.py"):
        assert p in R.TRUST_ANCHOR_LOCK_SURFACE, p
    src = Path(R.__file__).read_text(encoding="utf-8")
    assert "not editable by the PR" in src or "OUTSIDE the repository" in src


# ── controls for the bypasses the adversarial review found ───────────────────────────────
def test_base_equal_head_cannot_neuter_the_ratchet(tmp_path):
    """MEASURED PASS before this: every rule is a set difference between two trees, so
    `--base HEAD` emptied all of them and the gate reported success. The workflow supplies the
    base, so the gate must not trust it."""
    root = _repo(tmp_path, "b1", BASE, {"new_thing.py": "X = 1\n"})
    assert any("NEUTERED BY ARGUMENT" in b for b in R.ratchet("cand", "cand", root))
    assert any("NEW ROOT PRODUCTION MODULE" in b for b in R.ratchet("main", "cand", root))


@pytest.mark.parametrize("body", [
    "from app import api\n",              # the package arrives via names, not module
    "from app import api as a\n",
    "from .. import api\n",               # the relative twin
])
def test_alias_import_forms_cannot_walk_around_the_dependency_lattice(tmp_path, body):
    bad = _bad(_repo(tmp_path, "b2" + str(abs(hash(body))), BASE,
                     {"app/domain/al.py": body}))
    assert any("FORBIDDEN DEPENDENCY DIRECTION" in b for b in bad), (body, bad)


def test_churning_a_legacy_directory_flat_still_blocks(tmp_path):
    """One aggregate over 13 directories stays flat while 100 curated files leave and 99
    generated ones arrive. Additions are refused, not net movement."""
    base = {**BASE, "reports/a.json": "{}\n", "reports/b.json": "{}\n"}
    bad = _bad(_repo(tmp_path, "b3", base, {"reports/c.json": "{}\n"},
                     removed=("reports/a.json", "reports/b.json")))
    assert any("NEW FILES IN A LEGACY DIRECTORY" in b for b in bad), bad


@pytest.mark.parametrize("body", [
    "from app.domain.value import *\nRESULT = (lambda: 1)()\n",
    "from app.domain.value import *\nTABLE = {k: k for k in range(3)}\n",
    "from app.domain.value import *\nCFG = build_config()\n",
])
def test_a_shim_that_executes_logic_in_an_assignment_is_not_a_shim(body):
    """Checking the statement TYPE let a module keep all its logic in assignment VALUES and
    still be certified a re-export."""
    assert R.is_compatibility_shim(body) is False, body


@pytest.mark.parametrize("name", ["model.pt.bak", "console.sqlite.old", "weights.pkl.1"])
def test_double_suffix_artifacts_are_still_generated_state(name):
    assert R.is_generated_state(name, 10, b"") is True, name


def test_deleting_the_declared_gate_is_a_violation_not_a_skip(tmp_path):
    """The fail-open: `if not tool.exists(): continue` meant the cheapest way past the guard was
    to remove the thing it guards."""
    import tools.check_institutional_correctness as CIC

    root = tmp_path / "nogate"
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / ".github" / "workflows" / "hardening.yml").write_text(
        "jobs: {}\n", encoding="utf-8")
    old = CIC.REPO
    try:
        CIC.REPO = root
        bad = [str(v.msg) for v in CIC._declared_gate_is_actually_invoked_violations()]
    finally:
        CIC.REPO = old
    assert any("declared as a required CI gate but does not exist" in b for b in bad), bad


def test_a_target_mutated_after_the_digest_is_caught(tmp_path, monkeypatch):
    """The attack that defeats BOTH other protections: `TARGET[...].append(x)` after the digest
    is computed leaves TARGET_SHA256 untouched (already taken) and the AST literal untouched
    (a separate statement), while every predicate reads the mutated object."""
    root = _repo(tmp_path, "b4", {**BASE, "tools/repo_rehab_status.py": _tool_src("{'a': 1}")},
                 {"tools/repo_rehab_status.py": _tool_src("{'a': 1}") + "\nX = 1\n"})
    monkeypatch.setattr(R, "TARGET", {"a": 2})           # live object != file literal
    bad = R.ratchet("main", "cand", root)
    assert any("MUTATED AT RUNTIME" in b for b in bad), bad


def test_adding_a_submodule_blocks(tmp_path):
    """A gitlink has no slash, no suffix and no blob, so it entered none of the path rules.
    Review PROVED a submodule carrying 1500 LOC and a 2 MB database passed."""
    import subprocess

    inner = _repo(tmp_path, "sub_inner", {"engine.py": "X = 1\n"}, None)
    outer = _repo(tmp_path, "sub_outer", BASE, None)
    subprocess.run(["git", "-c", "protocol.file.allow=always", "submodule", "add",
                    "-q", str(inner), "core"], cwd=str(outer), capture_output=True, timeout=120)
    subprocess.run(["git", "add", "-A"], cwd=str(outer), capture_output=True, timeout=60)
    subprocess.run(["git", "commit", "-qm", "add submodule"], cwd=str(outer),
                   capture_output=True, timeout=60)
    links = R.tracked_gitlinks("cand", outer)
    if not links:                       # submodule support unavailable in this environment
        pytest.skip("git submodule add unavailable here")
    assert any("NEW SUBMODULE" in b for b in R.ratchet("main", "cand", outer))


@pytest.mark.parametrize("wf,marker", [
    ("jobs:\n  hardening:\n    steps:\n      - run: python tools/repo_rehab_status.py"
     " --ratchet --base origin/main\n        continue-on-error: true\n", "continue-on-error"),
    ("jobs:\n  hardening:\n    steps:\n      - if: false\n        run: python"
     " tools/repo_rehab_status.py --ratchet --base origin/main\n", "if:"),
    ("jobs:\n  hardening:\n    steps:\n      - run: python tools/repo_rehab_status.py"
     " --ratchet --base origin/main ; exit 0\n", "swallow"),
    ("jobs:\n  hardening:\n    steps:\n      - run: python tools/repo_rehab_status.py"
     " --ratchet --base origin/main || echo skipped\n", "swallow"),
    ("jobs:\n  hardening:\n    steps:\n      - run: python tools/repo_rehab_status.py"
     " --ratchet --base HEAD\n", "--base origin/main"),
])
def test_every_proven_ci_demotion_form_blocks(tmp_path, wf, marker):
    """Only `|| true` was enumerated before; review proved nine other forms pass. A step that
    is present and cannot fail is worse than a missing one, because the wiring looks intact."""
    bad = _ci_gate_violations(tmp_path / ("dm" + str(abs(hash(wf)))), wf)
    assert bad, (marker, wf)


def test_deleting_tooling_or_governance_is_not_scored_as_improvement():
    """`good = d > 0 if key.startswith('app_')` scored a FALL in tools/ and governance/ as
    better, rewarding deletion of the machinery holding the line — and scored a RISE in
    app_imports_legacy as better, which is the facade metric read backwards."""
    directions = {key: direction for _l, key, _t, direction in R._METRICS}
    assert directions["tools_py"] == "info"
    assert directions["governance_files"] == "info"
    assert directions["app_imports_legacy"] == "down"
    assert directions["app_modules"] == "up"


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
    signal nobody can act on. VIOLATED means runtime state is being RE-CREATED.

    `force_local` is required because this asserts the LOCAL verdicts, and under CI the honest
    answer is NOT_PROVEN_FROM_CI — which is the other half of the same fix. Without it this test
    passed locally and failed in CI, asserting the environment rather than the logic."""
    root = _repo(tmp_path, "o", {**BASE, "models/a.pkl": "x\n"}, {"models/b.pkl": "y\n"})
    inherited = R.host_separation(root, baseline="main", ref="main", force_local=True)
    assert inherited["state"] == "NOT_YET_SEPARATED", inherited
    growing = R.host_separation(root, baseline="main", ref="cand", force_local=True)
    assert growing["state"] == "VIOLATED", growing
