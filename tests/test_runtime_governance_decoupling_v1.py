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

Two behavioural questions: can the app come up with governance unimportable, and does the
agent seam still refuse to move the production checkout.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

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
