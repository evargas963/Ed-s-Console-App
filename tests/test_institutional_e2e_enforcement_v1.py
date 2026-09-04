"""RC-516 — INSTITUTIONAL END-TO-END EXECUTION LAW: negative and positive controls.

Every control drives the REAL registered check function (the one `CHECKS` in
tools/check_institutional_correctness.py points the gate at) against a real git repository
built in tmp_path, with the attack STAGED exactly as a commit would stage it. That is the
path the delta gate walks in required CI: materialise the candidate, stage its delta, run
the catalog. Nothing here asserts on prose in a document; every verdict comes from the
code delta, the closure ledger, or file existence.

Attack classes (mission RESTORE AND CONSOLIDATE INSTITUTIONAL END-TO-END ENFORCEMENT):
   1  canonical producer changed while a connected duplicate remains        -> FAIL
   2  new fallback independently computes the same semantic truth           -> FAIL
   3  backend fixed while a frontend reimplementation remains                -> FAIL
   4  superseded implementation remains callable after replacement          -> FAIL
   5  parent CLOSED while a material dimension is NOT_PROVEN                 -> FAIL
   6  parent CLOSED while a material dimension is PARTIAL                    -> FAIL
   7  historical deleted enforcement cited as current PROVEN enforcement     -> FAIL
   8  new root-level production module                                       -> FAIL
   9  legitimate consumer that only imports/calls the canonical computation  -> PASS
  10  legitimate unrelated change with no connected defect                   -> PASS
  11  correct root fix removing the duplicate and rewiring every consumer    -> PASS
  12  pure documentation/history that claims no current enforcement         -> PASS
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools import check_institutional_correctness as C  # noqa: E402
from tools import check_institutional_closure_gate as CLOSURE  # noqa: E402

CHECK = {name: fn for name, fn, _enforced in C.CHECKS}
ENFORCED = {name for name, _fn, enforced in C.CHECKS if enforced}

# ── fixture repository ────────────────────────────────────────────────────────────────

GEX_BODY = textwrap.dedent('''
    def compute_gex(rows, spot):
        """Dollar gamma per 1%: the canonical computation."""
        total = 0.0
        calls = 0.0
        puts = 0.0
        for r in rows:
            w = r["gamma"] * r["oi"] * spot * spot * 0.01
            if r["kind"] == "call":
                calls += w
            else:
                puts += w
        total = calls - puts
        return {"total": total, "calls": calls, "puts": puts}
''').lstrip()

OLD_BODY = textwrap.dedent('''
    def old_compute(rows, spot):
        acc = 0.0
        n = 0
        for r in rows:
            acc += r["gamma"] * r["oi"]
            n += 1
        if n == 0:
            return 0.0
        return acc * spot
''').lstrip()

FILES = {
    "app/__init__.py": "",
    "app/exposure/__init__.py": "",
    "app/exposure/gex.py": GEX_BODY,
    "svc/__init__.py": "",
    "svc/api.py": "from app.exposure.gex import compute_gex\n\n\ndef serve(rows, spot):\n    return compute_gex(rows, spot)\n",
    "legacy/__init__.py": "",
    "legacy/old_gex.py": OLD_BODY,
    "svc/legacy_api.py": "from legacy.old_gex import old_compute\n\n\ndef serve_old(rows, spot):\n    return old_compute(rows, spot)\n",
    # A research copy that already exists at the base: the whole-tree census would count it,
    # the delta-scoped checks must NOT charge it to a change that leaves it alone.
    "research/study.py": GEX_BODY.replace("def compute_gex(", "def compute_gex_copy("),
    "governance/level_faucets.json": json.dumps({"level_domain_producers": {}}),
    "governance/INSTITUTIONAL_CLOSURE_SCHEMA.json": json.dumps({
        "required_dimensions": ["ROOT_CAUSE", "END_TO_END_CORRECTNESS", "MECHANICAL_ENFORCEMENT"],
        "lanes": [{"lane": "L-OK", "parent_lane": None, "status": "NOT_CLOSED",
                   "dimensions": {"ROOT_CAUSE": "PROVEN", "END_TO_END_CORRECTNESS": "NOT_PROVEN",
                                  "MECHANICAL_ENFORCEMENT": "NOT_PROVEN"}}],
        "real_money_approval": "NOT_APPROVED",
    }),
    "AGENTS.md": "# law\n\nEnforced by `tools/real_gate.py` (exists).\n",
    "tools/real_gate.py": "def gate():\n    return 0\n",
}


def _git(repo: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(k, None)
    out = subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=str(repo),
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env=env)
    assert out.returncode == 0, (args, out.stderr)
    return out.stdout


def _write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture(scope="module")
def _seed(tmp_path_factory) -> Path:
    """The committed base tree, built ONCE: every git call costs ~1s on Windows, and the
    seed is identical for every control."""
    root = tmp_path_factory.mktemp("seed") / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    for rel, text in FILES.items():
        _write(root, rel, text)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


@pytest.fixture
def repo(_seed, tmp_path, monkeypatch) -> Path:
    """A private copy of the committed base tree; every control stages ONE attack on it."""
    root = tmp_path / "repo"
    shutil.copytree(_seed, root)
    monkeypatch.setattr(C, "REPO", root)
    return root


def _stage(repo: Path, rel: str, text: str | None) -> None:
    """Write (or delete) a file and stage it — the exact shape of a change under commit."""
    if text is None:
        _git(repo, "rm", "-q", rel)
    else:
        _write(repo, rel, text)
        _git(repo, "add", rel)


def _run(name: str) -> list[str]:
    assert name in ENFORCED, f"{name} must be ENFORCED — an advisory law check enforces nothing"
    return [str(v) for v in CHECK[name]()]


# ── registration: the checks are on the real gate path ────────────────────────────────

def test_the_law_checks_are_registered_and_enforced_in_the_one_gate():
    """No second gate: the five law checks are rows of CHECKS with enforced=True, which is
    exactly what the delta gate's roster read (`check_delta_adds_no_debt.enforced_roster`)
    and the commit seam (`precommit_institutional._enforced_roster`) see."""
    for name in ("no_superseded_path_survives", "changed_computation_leaves_no_twin",
                 "no_new_root_production_module", "institutional_closure_ledger",
                 "authority_docs_cite_existing_mechanisms"):
        assert name in ENFORCED, name
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "precommit_seam", REPO / "tools" / "precommit_institutional.py")
    seam = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seam)
    roster = seam._enforced_roster((REPO / "tools" / "check_institutional_correctness.py")
                                   .read_text(encoding="utf-8"))
    assert {"no_superseded_path_survives", "changed_computation_leaves_no_twin",
            "institutional_closure_ledger"} <= roster


def test_no_context_and_no_delta_are_silent(repo):
    """Nothing staged: every delta-scoped check returns [] — the base side of the delta gate."""
    for name in ("no_superseded_path_survives", "changed_computation_leaves_no_twin",
                 "no_new_root_production_module"):
        assert _run(name) == [], name


# ── 1: canonical producer changed while a connected duplicate remains → FAIL ─────────

def test_attack_1_canonical_changed_duplicate_left_diverged(repo):
    _stage(repo, "app/exposure/gex.py",
           GEX_BODY.replace("    total = 0.0\n", "    if spot <= 0:\n        raise ValueError(spot)\n    total = 0.0\n"))
    hits = _run("changed_computation_leaves_no_twin")
    assert len(hits) == 1, hits
    assert "research/study.py" in hits[0].replace("\\", "/")
    assert "compute_gex_copy" in hits[0] and "identical copy" in hits[0] and "diverged" in hits[0]


# ── 2: new fallback independently computes the same truth → FAIL ─────────────────────

def test_attack_2_new_fallback_with_identical_body(repo):
    _stage(repo, "svc/fallback.py",
           GEX_BODY.replace("def compute_gex(", "def compute_gex_fallback(")
           + "\n\ndef serve_with_fallback(rows, spot):\n    try:\n        from app.exposure.gex import compute_gex\n"
             "        return compute_gex(rows, spot)\n    except Exception:\n        return compute_gex_fallback(rows, spot)\n")
    hits = _run("changed_computation_leaves_no_twin")
    assert any("compute_gex_fallback" in h and "second computation" in h for h in hits), hits


# greek-faucet-ok: the d1 formulas below are the ATTACK TEXT the controls feed to the faucet
# clause as strings; nothing in this file computes a greek (RC-516 negative controls).
def test_attack_2b_new_inline_greek_formula_in_python_backend():
    """The registered-formula faucet (RC-212) is the other objective owner of law 6: a
    d1-style formula added outside math_levels.py fails regardless of what it is named."""
    added = "def my_delta(spot, strike, t, sigma):\n    d1 = (math.log(spot / strike) + 0.5 * sigma * sigma * t) / (sigma * math.sqrt(t))\n    return d1\n"
    reasons = C.domain_faucet_violations("planes/helper.py", added, json.dumps({"level_domain_producers": {}}))
    assert reasons and "greek formula" in reasons[0]


# ── 3: backend fixed while a frontend reimplementation remains → FAIL ────────────────

def test_attack_3_frontend_reimplements_the_greek_formula(repo):
    _stage(repo, "static/chart.js",
           "function d1(spot, strike, t, sigma) {\n"
           "  return (Math.log(spot / strike) + 0.5 * sigma * sigma * t) / (sigma * Math.sqrt(t));\n}\n")
    hits = _run("domain_faucet_registry")
    assert len(hits) == 1 and "frontend" in hits[0] and "static/chart.js" in hits[0].replace("\\", "/"), hits


def test_attack_3_control_served_value_rendered_in_frontend_passes(repo):
    _stage(repo, "static/chart.js", "function render(payload) {\n  return payload.gex_total.toFixed(2);\n}\n")
    assert _run("domain_faucet_registry") == []


# ── 4: superseded implementation remains callable after replacement → FAIL ───────────

def test_attack_4_rewired_caller_leaves_old_path_defined(repo):
    _stage(repo, "svc/legacy_api.py",
           "from app.exposure.gex import compute_gex\n\n\ndef serve_old(rows, spot):\n    return compute_gex(rows, spot)\n")
    hits = _run("no_superseded_path_survives")
    assert len(hits) == 1, hits
    assert "legacy/old_gex.py" in hits[0].replace("\\", "/") and "old_compute" in hits[0]
    assert "superseded path" in hits[0]


def test_attack_4g_a_test_reference_does_not_keep_the_old_path_alive(repo):
    """Law 8: tests conform to the architecture; a test import is not a production caller."""
    _stage(repo, "tests/test_old.py",
           "from legacy.old_gex import old_compute\n\n\ndef test_old():\n    assert old_compute([], 1.0) == 0.0\n")
    _stage(repo, "svc/legacy_api.py",
           "from app.exposure.gex import compute_gex\n\n\ndef serve_old(rows, spot):\n    return compute_gex(rows, spot)\n")
    hits = _run("no_superseded_path_survives")
    assert len(hits) == 1 and "old_compute" in hits[0], hits


def test_attack_4_control_decorated_entry_points_are_registered_by_their_decorator(repo):
    """A route handler has no caller by design; losing an incidental direct call does not
    orphan it."""
    _stage(repo, "svc/routes.py",
           "app = object()\n\n\ndef route(p):\n    def deco(fn):\n        return fn\n    return deco\n\n\n"
           "@route('/x')\ndef handler(rows, spot):\n    a = 1\n    b = 2\n    c = a + b\n    d = c * 2\n    e = d - 1\n    return e\n\n\n"
           "def caller():\n    return handler([], 1.0)\n")
    _git(repo, "commit", "-qm", "routes")
    _stage(repo, "svc/routes.py",
           "app = object()\n\n\ndef route(p):\n    def deco(fn):\n        return fn\n    return deco\n\n\n"
           "@route('/x')\ndef handler(rows, spot):\n    a = 1\n    b = 2\n    c = a + b\n    d = c * 2\n    e = d - 1\n    return e\n")
    assert _run("no_superseded_path_survives") == []


# ── 5 / 6: parent CLOSED over NOT_PROVEN / PARTIAL → FAIL, through the real check ─────

def _closure_doc(status_of_e2e: str) -> str:
    return json.dumps({
        "required_dimensions": ["ROOT_CAUSE", "END_TO_END_CORRECTNESS", "MECHANICAL_ENFORCEMENT"],
        "lanes": [{"lane": "PARENT", "parent_lane": None, "status": "CLOSED_WITH_EVIDENCE",
                   "dimensions": {"ROOT_CAUSE": "PROVEN", "END_TO_END_CORRECTNESS": status_of_e2e,
                                  "MECHANICAL_ENFORCEMENT": "PROVEN"},
                   "material_limitations": [], "final_sha": "a" * 40,
                   "remote_ci_status": "4/4 success at cited tip",
                   "sub_lanes": [{"sub_lane": "PARENT-SUB", "status": "CLOSED_WITH_EVIDENCE"}]}],
        "real_money_approval": "NOT_APPROVED",
    })


@pytest.mark.parametrize("blocked", ["NOT_PROVEN", "PARTIAL", "PENDING", "NOT_AUDITED", "FAIL"])
def test_attack_5_6_parent_closed_over_a_blocked_dimension(repo, blocked):
    _write(repo, "governance/INSTITUTIONAL_CLOSURE_SCHEMA.json", _closure_doc(blocked))
    hits = _run("institutional_closure_ledger")
    assert any(f"END_TO_END_CORRECTNESS={blocked}" in h for h in hits), hits
    assert any("sub-lane" in h for h in hits), "a sub-lane closure must not close the parent"


def test_attack_5_6_control_fully_proven_parent_closes(repo):
    _write(repo, "governance/INSTITUTIONAL_CLOSURE_SCHEMA.json", _closure_doc("PROVEN"))
    assert _run("institutional_closure_ledger") == []


# ── 7: historical deleted enforcement cited as current PROVEN → FAIL ─────────────────

def test_attack_7_closed_lane_cites_a_deleted_mechanism(repo):
    doc = json.loads(_closure_doc("PROVEN"))
    doc["lanes"][0]["evidence"] = {"engine": "tools/deleted_gate.py + tests/test_deleted_gate.py"}
    _write(repo, "governance/INSTITUTIONAL_CLOSURE_SCHEMA.json", json.dumps(doc))
    hits = _run("institutional_closure_ledger")
    assert len(hits) == 1 and "tests/test_deleted_gate.py, tools/deleted_gate.py" in hits[0], hits
    assert "retire the lane" in hits[0]


def test_attack_7b_open_lane_claims_proven_enforcement_by_a_deleted_mechanism(repo):
    doc = json.loads(_closure_doc("NOT_PROVEN"))
    doc["lanes"][0]["status"] = "NOT_CLOSED"
    doc["lanes"][0]["evidence"] = {"engine": "tools/deleted_gate.py"}
    _write(repo, "governance/INSTITUTIONAL_CLOSURE_SCHEMA.json", json.dumps(doc))
    hits = _run("institutional_closure_ledger")
    assert any("MECHANICAL_ENFORCEMENT=PROVEN while citing" in h for h in hits), hits


def test_attack_7c_authority_document_names_a_deleted_mechanism(repo):
    _write(repo, "AGENTS.md", "# law\n\nEnforced by `tools/gone_gate.py` at commit.\n")
    hits = _run("authority_docs_cite_existing_mechanisms")
    assert len(hits) == 1 and "tools/gone_gate.py" in hits[0] and "AGENTS.md:3" in hits[0].replace("\\", "/"), hits


def test_attack_7_control_retired_lane_keeps_history_and_asserts_nothing(repo):
    doc = json.loads(_closure_doc("PROVEN"))
    lane = doc["lanes"][0]
    lane["status"] = "RETIRED"
    lane["retired"] = {"date": "2026-09-04", "retired_in": "abc1234", "reason": "mechanism deleted",
                       "current_owner": "tools/real_gate.py",
                       "historical_dimensions": lane.pop("dimensions"),
                       "historical_record": {"engine": "tools/deleted_gate.py", "final_sha": lane.pop("final_sha")}}
    lane.pop("remote_ci_status")
    _write(repo, "governance/INSTITUTIONAL_CLOSURE_SCHEMA.json", json.dumps(doc))
    assert _run("institutional_closure_ledger") == []


def test_attack_7d_retired_lane_may_not_keep_current_authority_fields(repo):
    doc = json.loads(_closure_doc("PROVEN"))
    lane = doc["lanes"][0]
    lane["status"] = "RETIRED"
    lane["retired"] = {"date": "2026-09-04", "retired_in": "abc1234", "reason": "r", "current_owner": "x"}
    _write(repo, "governance/INSTITUTIONAL_CLOSURE_SCHEMA.json", json.dumps(doc))
    hits = _run("institutional_closure_ledger")
    assert any("still carries `dimensions`" in h for h in hits), hits
    assert any("final_sha/remote_ci_status" in h for h in hits), hits


# ── 8: new root-level production module → FAIL ───────────────────────────────────────

def test_attack_8_new_root_module(repo):
    _stage(repo, "gex_helpers.py", "def helper():\n    return 1\n")
    hits = _run("no_new_root_production_module")
    assert len(hits) == 1 and "gex_helpers.py" in hits[0] and "docs/ARCHITECTURE.md" in hits[0], hits


def test_attack_8b_module_moved_into_root(repo):
    _git(repo, "mv", "svc/api.py", "api.py")
    hits = _run("no_new_root_production_module")
    assert len(hits) == 1 and "api.py" in hits[0], hits


def test_attack_8_control_module_moved_out_of_root_passes(repo):
    _stage(repo, "root_thing.py", "def r():\n    return 2\n")
    _git(repo, "commit", "-qm", "root")
    _git(repo, "mv", "root_thing.py", "app/root_thing.py")
    assert _run("no_new_root_production_module") == []


# ── 9: legitimate consumer that only imports/calls → PASS ────────────────────────────

def test_control_9_consumer_that_carries_the_canonical_value(repo):
    _stage(repo, "svc/report.py",
           "from app.exposure.gex import compute_gex\n\n\ndef report(rows, spot):\n    g = compute_gex(rows, spot)\n"
           "    lines = []\n    lines.append(f\"total={g['total']}\")\n    lines.append(f\"calls={g['calls']}\")\n"
           "    lines.append(f\"puts={g['puts']}\")\n    return '\\n'.join(lines)\n")
    for name in ("no_superseded_path_survives", "changed_computation_leaves_no_twin",
                 "no_new_root_production_module", "institutional_closure_ledger",
                 "authority_docs_cite_existing_mechanisms"):
        assert _run(name) == [], name


# ── 10: unrelated change with no connected defect → PASS ─────────────────────────────

def test_control_10_unrelated_change(repo):
    _stage(repo, "svc/api.py", "from app.exposure.gex import compute_gex\n\n\ndef serve(rows, spot):\n    # comment only\n    return compute_gex(rows, spot)\n")
    _stage(repo, "docs/notes.md", "notes\n")
    for name in ("no_superseded_path_survives", "changed_computation_leaves_no_twin",
                 "no_new_root_production_module", "domain_faucet_registry"):
        assert _run(name) == [], name


# ── 11: correct root fix — duplicate removed, every consumer rewired → PASS ──────────

def test_control_11_root_fix_removes_duplicate_and_rewires_consumers(repo):
    _stage(repo, "app/exposure/gex.py",
           GEX_BODY.replace("    total = 0.0\n", "    if spot <= 0:\n        raise ValueError(spot)\n    total = 0.0\n"))
    _stage(repo, "research/study.py", "from app.exposure.gex import compute_gex\n\n\ndef study(rows, spot):\n    return compute_gex(rows, spot)\n")
    _stage(repo, "svc/legacy_api.py", "from app.exposure.gex import compute_gex\n\n\ndef serve_old(rows, spot):\n    return compute_gex(rows, spot)\n")
    _stage(repo, "legacy/old_gex.py", None)
    for name in ("no_superseded_path_survives", "changed_computation_leaves_no_twin",
                 "no_new_root_production_module"):
        assert _run(name) == [], name


# ── 12: pure documentation / history that claims no current enforcement → PASS ──────

def test_control_12_history_in_the_ledger_is_not_a_claim(repo):
    _write(repo, "governance/root_cause_log.md",
           "| RC-1 | CLOSED | 2026-01-01 | 2026-01-02 | d | w | tools/deleted_gate.py was retired in abc1234 |\n")
    assert _run("authority_docs_cite_existing_mechanisms") == []


def test_control_12_authority_document_naming_existing_mechanisms_passes(repo):
    assert _run("authority_docs_cite_existing_mechanisms") == []


# ── the path grammar is one definition, shared ───────────────────────────────────────

def test_mechanism_path_grammar_ignores_globs_directories_and_placeholders():
    text = ("`tools/*.py`, `app/api/routes/`, `static/*.html|*.js`, `mega*_traceable_inventory.py`, "
            "`tools/check_x.py`, `db.py`, `.github/workflows/hardening.yml`, `governance/a/b.json`")
    assert CLOSURE.cited_paths(text) == {
        "tools/check_x.py", "db.py", ".github/workflows/hardening.yml", "governance/a/b.json"}
