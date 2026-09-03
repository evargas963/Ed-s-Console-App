"""RC-512 — the application runtime is independent of repository/agent governance.

The defect these controls exist for was not theoretical. MEASURED 2026-09-03 in the live
production checkout: `tools/check_live_path_is_main.py` returned one violation — "HEAD is 9
commit(s) BEHIND origin/main" — and because `start_ed_console.bat` ran it before `uvicorn`
and aborted on a non-zero exit, the desk could not start. No application defect of any kind
was involved: a repository position decided whether the app was allowed to run. The same
check opened with `git fetch origin main`, so startup also depended on reaching a remote.

The boundary these tests pin:

    governance MAY control agent actions, commit, and merge/CI
    governance MAY NOT decide whether the app starts, collects, serves, or computes

So each test below asks one behavioural question rather than reading intent out of prose:
does the launch path execute governance code, can the app come up with governance
unimportable, does any runtime module read a path under governance/, and — the other half,
because removing a control is only safe if the protection survives elsewhere — does the
agent seam still refuse to move the production checkout.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Directories that hold repository/agent governance. Nothing on the runtime path may
#: execute code out of them or read state out of them.
GOVERNANCE_DIRS = ("tools", "governance")

#: The real runtime entry points: the served app, the ops runner the panel drives, the
#: capture daemon spine, and the two leaves everything imports.
RUNTIME_ENTRY_POINTS = ("server.py", "ops_runner.py", "stream_spine.py", "config.py", "db.py")

LAUNCHER = REPO / "start_ed_console.bat"


def _executed_batch_lines(text: str) -> list[tuple[int, str]]:
    """Every line of a .bat that actually RUNS — comments and blanks removed.

    A `REM` line may legitimately discuss governance (the launcher now carries a long note
    explaining exactly what was removed and why); an EXECUTED line may not invoke it.
    """
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.upper().startswith("REM ") or line.upper() == "REM":
            continue
        out.append((n, line))
    return out


def test_the_launch_path_executes_nothing_out_of_governance():
    """The desk's startup sequence runs no governance code at all.

    Before RC-512 two statements here invoked `tools\\`: the live-Schwab preflight (which is
    app runtime — it asks whether Schwab calls will work — and moved to the app root as
    `live_schwab_env.py`) and the RC-350 repository check (which is governance, and is gone).
    """
    text = LAUNCHER.read_text(encoding="utf-8")
    offenders = []
    for n, line in _executed_batch_lines(text):
        low = line.lower()
        for d in GOVERNANCE_DIRS:
            if f"{d}\\" in low or f"{d}/" in low:
                offenders.append((n, line))
                break
    assert not offenders, (
        "the app launch path executes governance code — repository state can then decide "
        f"whether the desk runs (RC-512): {offenders}"
    )


def test_the_launcher_still_launches():
    """Positive control for the test above, which an empty or gutted launcher would pass."""
    text = LAUNCHER.read_text(encoding="utf-8")
    executed = "\n".join(line for _n, line in _executed_batch_lines(text))
    assert '"%VENV_PY%" -m uvicorn server:app' in executed, "the launcher no longer starts the app"
    assert "live_schwab_env.py --sanitize" in executed, (
        "the live-Schwab runtime preflight is gone — that one is app correctness, not "
        "governance, and must survive the decoupling"
    )
    assert "ED_OPS_RUNNER=1" in text and "ED_CALIBRATION_LOG=1" in text


def test_the_app_imports_and_answers_health_with_governance_unimportable():
    """Behavioural: with `tools` and `governance` refused at import, the app still serves.

    Run in a subprocess so the refusal cannot leak into the rest of the suite. The blocker is
    itself proven armed inside that process — a finder that silently matched nothing would
    make this test pass while proving nothing.
    """
    snippet = """
import importlib.abc, importlib.machinery, json, sys

REFUSED = ("tools", "governance")


class RefuseGovernance(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        head = fullname.split(".", 1)[0]
        if head in REFUSED:
            raise ImportError("RC-512 control: %s is absent" % fullname)
        return None


sys.meta_path.insert(0, RefuseGovernance())

armed = False
try:
    import tools  # noqa: F401
except ImportError:
    armed = True

import server
from fastapi.testclient import TestClient

with TestClient(server.app) as client:
    resp = client.get("/api/health")
    status = resp.status_code

print(json.dumps({"armed": armed, "status": status}))
"""
    proc = subprocess.run(
        [sys.executable, "-c", snippet],
        cwd=str(REPO), capture_output=True, text=True, timeout=900,
        env={**_ci_env(), "PYTHONIOENCODING": "utf-8"},
    )
    assert proc.returncode == 0, (
        "the app could not come up with governance unimportable — a governance import on the "
        f"runtime path is a blocking dependency (RC-512).\nSTDOUT:\n{proc.stdout}\n"
        f"STDERR:\n{proc.stderr[-4000:]}"
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["armed"] is True, "the import blocker never fired — this proved nothing"
    assert payload["status"] == 200, f"/api/health returned {payload['status']}"


def _ci_env() -> dict:
    import os

    env = dict(os.environ)
    env.update({
        "ED_CI_OFFLINE": "1",
        "ED_CONSOLE_ALLOW_NONCANONICAL_DB": "1",
        "SCHWAB_API_KEY": "ci-not-live-placeholder",
        "SCHWAB_APP_SECRET": "ci-not-live-placeholder",
    })
    return env


def _runtime_closure(repo_index) -> dict[str, ast.AST]:
    """Repo modules reachable by import from the runtime entry points.

    Resolved from import NODES, never from text matching, and built off the shared index so
    this adds no independent repository scan.
    """
    trees: dict[str, ast.AST] = {}
    root_modules: dict[str, str] = {}
    pkg_modules: dict[str, str] = {}
    for raw_rel, _text, tree in repo_index.items():
        if tree is None:
            continue
        rel = Path(raw_rel).as_posix()      # the index yields Path objects, not strings
        trees[rel] = tree
        if "/" not in rel:
            root_modules[rel[:-3]] = rel
        else:
            pkg_modules[rel[:-3].replace("/", ".")] = rel
            if rel.endswith("/__init__.py"):
                pkg_modules[rel[: -len("/__init__.py")].replace("/", ".")] = rel

    def resolve(name: str) -> str | None:
        return root_modules.get(name) or pkg_modules.get(name)

    closure: dict[str, ast.AST] = {}
    frontier = [e for e in RUNTIME_ENTRY_POINTS if e in trees]
    assert frontier, "no runtime entry point found in the index"
    while frontier:
        rel = frontier.pop()
        if rel in closure:
            continue
        closure[rel] = trees[rel]
        for node in ast.walk(trees[rel]):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for nm in names:
                tgt = resolve(nm)
                if tgt and tgt not in closure:
                    frontier.append(tgt)
    return closure


def _docstring_lines(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if ast.get_docstring(node, clean=False) is not None and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr):
                    out.add(first.lineno)
    return out


def test_no_runtime_module_reads_state_under_governance(repo_index):
    """No module the app runtime imports resolves a path under `governance/`.

    Both spellings, because the first sweep for this only caught one: the slash form
    ``"governance/x.json"`` AND the segment form ``Path(...) / "governance" / "x.json"``.
    `decision_gate.py` used the second, so a slash-only search reported the runtime clean
    while a missing `governance/` directory still forced every trade call to WAIT.
    Docstrings are excluded: naming the old location in order to explain it is mention,
    not use (RC-186 / RC-253).
    """
    closure = _runtime_closure(repo_index)
    offenders: list[str] = []
    for rel, tree in sorted(closure.items()):
        skip = _docstring_lines(tree)
        for node in _governance_path_constants(tree):
            if node.lineno in skip:
                continue
            if node.value.startswith(_ARTIFACTS_OWNED_ELSEWHERE):
                continue
            offenders.append(f"{rel}:{node.lineno} {node.value[:80]!r}")
    assert not offenders, (
        "runtime code reads state under governance/, so pruning or staleness in the "
        f"governance directory changes what the app computes (RC-512): {offenders}"
    )


#: `governance/artifacts/**` is the ML ablation / feature-curation artifact family. It is
#: relocated to `reports/artifacts/**` by the GOVERNANCE_SIMPLIFICATION_V1 branch (PR #221,
#: RC-509), which rewrites the same producer files. Re-doing it here would collide with that
#: change for no added protection, so this control carves it out by name rather than
#: pretending it is clean. It is NOT on the blocking path: every module that reads it is
#: reached only through function-local imports, which is what
#: `test_the_app_imports_and_answers_health_with_governance_unimportable` proves.
_ARTIFACTS_OWNED_ELSEWHERE = ("governance/artifacts/",)


def _governance_path_constants(tree: ast.AST) -> list[ast.Constant]:
    """String constants used to build a FILESYSTEM path under `governance/`.

    Structural on purpose. A text sweep for "governance" over the same closure reports three
    classes of thing that are not filesystem reads at all, and a control that cries wolf on
    them gets deleted along with the protection:

      * `@app.get("/api/governance/panel")` — an HTTP route. `/governance` here is the
        product's model-promotion panel, a completely different sense of the word.
      * `ROUTING_GOVERNANCE = "governance"` — an alert-routing label.
      * a docstring naming the old location in order to explain the move.

    So a bare `"governance"` counts only where it is actually spliced into a path — an
    operand of a `/` (pathlib division) or an argument to a `Path(...)`-style call — and a
    slash-form string counts only when it is relative (a leading `/` means a URL).
    """
    hits: list[ast.Constant] = []
    parent: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[id(child)] = node

    def is_gov_segment(node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and node.value == "governance"

    def path_chain_segments(node: ast.AST) -> set[str]:
        """Every string segment of the whole `a / b / c` chain this node sits in.

        A segment-wise build splits the path across constants, so `"governance"` alone
        cannot say WHICH governance path it is. Ascending to the outermost `/` recovers the
        sibling segments — which is how the artifacts carve-out can be applied to
        `root / "governance" / "artifacts" / "x.json"` without a text match on the line.
        """
        top = node
        while True:
            up = parent.get(id(top))
            if isinstance(up, ast.BinOp) and isinstance(up.op, ast.Div):
                top = up
                continue
            break
        return {n.value for n in ast.walk(top)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}

    for node in ast.walk(tree):
        # `root / "governance" / "x.json"` and any nesting of it
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            for side in (node.left, node.right):
                if is_gov_segment(side):
                    if "artifacts" in path_chain_segments(side):
                        continue          # the family PR #221 relocates — see the note above
                    hits.append(side)
        # `Path("governance") / ...`
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if str(name).endswith("Path"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if arg.value == "governance" or arg.value.startswith("governance/"):
                            hits.append(arg)
        # a relative slash-form path literal; a leading "/" is a URL route, not a file
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            if v.startswith("governance/") and not v.endswith("/"):
                hits.append(node)

    # de-duplicate: a constant can be reached twice (BinOp operand and bare Constant walk)
    seen: set[tuple[int, int]] = set()
    unique: list[ast.Constant] = []
    for h in hits:
        key = (h.lineno, h.col_offset)
        if key in seen:
            continue
        seen.add(key)
        unique.append(h)
    return sorted(unique, key=lambda n: (n.lineno, n.col_offset))


def test_the_governance_path_detector_fires_and_does_not_cry_wolf():
    """Control for the test above, which a broken detector would pass silently.

    Both spellings must be CAUGHT — the slash form and the segment-wise build, because the
    first pass at this only caught the slash form and reported `decision_gate.py` clean while
    it still read `Path(...) / "governance" / "decision_path_admissions.json"`. And all three
    non-path senses must be MISSED, or the control gets switched off for noise.
    """
    caught = ast.parse(
        'A = "governance/decision_path_admissions.json"\n'
        'B = ROOT / "governance" / "decision_path_admissions.json"\n'
        'C = Path("governance") / "guard_applicability.json"\n'
    )
    found = {n.value for n in _governance_path_constants(caught)}
    assert found == {"governance", "governance/decision_path_admissions.json"}, found
    lines = {n.lineno for n in _governance_path_constants(caught)}
    assert lines == {1, 2, 3}, f"a spelling was missed: {sorted(lines)}"

    missed = ast.parse(
        '"""A docstring naming governance/decision_path_admissions.json to explain it."""\n'
        'ROUTING_GOVERNANCE = "governance"\n'
        '@app.get("/api/governance/panel")\n'
        'def panel(): ...\n'
        'D = ROOT / "governance" / "artifacts" / "feature_ablation_manifest.json"\n'
    )
    skip = _docstring_lines(missed)
    noise = [n.value for n in _governance_path_constants(missed)
             if n.lineno not in skip and not n.value.startswith(_ARTIFACTS_OWNED_ELSEWHERE)]
    assert noise == [], f"the detector fired on something that is not a governance file read: {noise}"


def test_the_runtime_registries_are_app_owned():
    """The two registries the runtime actually reads live under `config/`, not governance/.

    They are PRODUCT controls — which components may influence TRADE, and the ML migration
    policy — and both fail closed when absent. Fail-closed is correct for a product control
    and is unchanged here; what changed is that agent-governance housekeeping can no longer
    reach them. A `governance/` prune used to be able to silence trading.
    """
    import active_bundle_contract
    import decision_gate

    for rel in ("config/decision_path_admissions.json", "config/ML_ITEM4_MIGRATION_POLICY.json"):
        assert (REPO / rel).is_file(), f"{rel} is missing"
    for rel in ("governance/decision_path_admissions.json",
                "governance/ML_ITEM4_MIGRATION_POLICY.json"):
        assert not (REPO / rel).exists(), f"{rel} still exists — ownership was copied, not moved"

    admissions = Path(decision_gate._DEFAULT_REGISTRY_PATH).resolve()
    policy = Path(active_bundle_contract.MIGRATION_POLICY_PATH).resolve()
    assert admissions.parent.name == "config", admissions
    assert policy.parent.name == "config", policy
    # the registry still parses and still gates: an empty registry admits nothing
    data = json.loads(admissions.read_text(encoding="utf-8"))
    assert isinstance(data.get("admissions"), list)


def test_the_agent_seam_still_refuses_to_move_the_production_checkout():
    """The lineage invariant survives the launch gate's removal.

    `check_live_path_is_main.py` detected divergence at the next launch. The agent seam
    PREVENTS it at the moment of the command, and always did — which is why the launch copy
    was redundant as well as harmful. This is the control that makes the removal safe, so it
    is asserted here rather than assumed: derive the production primary at runtime (never a
    hardcoded operator path) and aim a branch move at it.
    """
    from tools.process_lock_guard import (
        REPO as GUARD_REPO,
        _primary_worktree_root,
        prod_checkout_git_move_violations,
    )

    primary = _primary_worktree_root(GUARD_REPO) or GUARD_REPO
    cmd = f'git -C "{primary}" checkout -b feature/should-never-land-here'
    violations = prod_checkout_git_move_violations(cmd)
    assert violations, (
        "an agent can move the PRODUCTION checkout onto a feature branch — the lineage "
        "invariant has no enforcement left anywhere (RC-512)"
    )
    assert any("PROD_CHECKOUT_LOCK" in v for v in violations), violations

    # negative half: the same verb aimed at a dev worktree is not the desk's business
    assert prod_checkout_git_move_violations('git -C "/tmp/some-dev-worktree" checkout -b wip') == []


def test_payload_work_tree_reads_only_what_the_payload_actually_names():
    """The narrow half of authority resolution. The full behaviour — including the Stop /
    no-file case and the delegation it drives — is proven end to end against real worktrees
    in tests/test_governance_authority_v1.py.
    """
    from tools.stop_chain import payload_work_tree

    assert payload_work_tree(json.dumps({
        "tool_name": "Edit", "tool_input": {"file_path": str(REPO / "server.py")},
    })) == REPO

    for empty in (json.dumps({"tool_name": "Stop"}),
                  json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}),
                  "not json at all",
                  json.dumps(["a", "list"]),
                  json.dumps({"tool_input": {"file_path": "   "}})):
        assert payload_work_tree(empty) is None, empty[:40]


def test_the_repository_lineage_check_is_no_longer_wired_to_anything_runtime():
    """Its own docstring claimed launch + pre-push + CI. Two never existed; one is removed.

    Pinned because a stale wiring claim is how the redundancy went unnoticed: the file read
    as a defence-in-depth control with three fail-closed seams while carrying exactly one,
    on the app's startup path.
    """
    precommit = (REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "default_stages: [pre-commit]" in precommit
    assert "check_live_path_is_main" not in precommit

    for wf in ("hardening.yml", "pytest.yml"):
        text = (REPO / ".github" / "workflows" / wf).read_text(encoding="utf-8")
        assert "check_live_path_is_main" not in text, f"{wf} invokes it after all"

    launcher = LAUNCHER.read_text(encoding="utf-8")
    executed = "\n".join(line for _n, line in _executed_batch_lines(launcher))
    assert "check_live_path_is_main" not in executed

    # still runnable on demand for an operator or an agent — removed from the runtime path,
    # not deleted, and its report is still meaningful
    from tools.check_live_path_is_main import violations

    assert isinstance(violations(), list)


@pytest.mark.parametrize("entry", RUNTIME_ENTRY_POINTS)
def test_runtime_entry_points_import_no_governance_module_at_module_level(repo_index, entry):
    """A module-level `import tools.x` in an entry point would break a governance-free tree.

    The five `tools/` modules the runtime can reach (the ablation / feature-curation family)
    are all imported INSIDE functions, so `import server` never touches them. That is what
    makes the behavioural test above pass, and it is load-bearing: promote any of those to a
    module-level import and a tree without `tools/` stops serving.
    """
    trees = {Path(rel).as_posix(): tree
             for rel, _t, tree in repo_index.items() if tree is not None}
    tree = trees.get(entry)
    if tree is None:
        pytest.skip(f"{entry} not in the index")
    bad = []
    for node in tree.body:                      # module level ONLY
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for nm in names:
            if nm.split(".", 1)[0] in GOVERNANCE_DIRS:
                bad.append(f"{entry}:{node.lineno} {nm}")
    assert not bad, f"module-level governance import on the runtime path (RC-512): {bad}"
