# institutional-synthetic-ok: these tests INJECT banned shell / edit spellings to prove the
# action bans BLOCK and the sanctioned forms flow — that is their entire purpose.
"""Action-ban negative controls for tools/operator_law_guard.py and two gate seams.

BEDROCK PR B (2026-09-06): these controls lived in tests/test_ui_mockup_lock_v1.py because
the RC-189 mockup-registry rule was one of the actions banned there. The registry, its lock
and that rule are retired (governance/retired_checks.md, ui_mockup_approval); the general
bans they sat beside are unchanged and moved here verbatim: lock-disable env spellings
(RC-186/RC-189 GUN 2), constructed -c / PowerShell write targets (RC-189 v2), the
ledger-status honesty clause, the domain-faucet registry seam (RC-212), the Edit-tool hook
wiring (RC-205) and the UTF-8 git reader (RC-187).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


# RC-187 (the guard's `_git` must decode UTF-8): that `_git` was the RC-66 lane's reader in
# tools/pretooluse_guard.py, retired with the lane; the module is a path-facts library now and
# runs no git. The surviving git readers pin `encoding="utf-8"` at their own sites.



def test_lock_disable_routes_are_git_and_precommits_own():
    """The lock-disable ban names the routes that actually bypass the battery — git's
    (`--no-verify`, `-n`, `core.hooksPath`) and pre-commit's (`SKIP=`, uninstall). The
    `ED_*_GUARD=off` spellings it once also policed name switches that do not exist (RC-450)
    and were deleted 2026-09-10."""
    from tools.operator_law_guard import _SKIP_HOOKS
    for cmd in ("git commit --no-verify -m x", "git commit -n -m x", "git -c core.hooksPath=/dev/null commit",
                "SKIP=institutional-correctness git commit -m x", "$env:SKIP='ruff-correctness'; git commit -m x",
                "pre-commit uninstall"):
        assert _SKIP_HOOKS.search(cmd), cmd
    for cmd in ("git commit -m 'skip the typo'", "SKIPPED=1 python x.py", "echo pre-commit installed",
                "git push -n origin main", "ED_UI_MOCKUP_LOCK=off git commit", "git commit -m 'normal'"):
        assert _SKIP_HOOKS.search(cmd) is None, cmd


def test_operator_law_guard_wired_for_edit_tools():
    """RC-205: the Edit/Write branch of operator_law_guard was DEAD CODE because
    .claude/settings.json only routed Bash|PowerShell to it — the ledger never received
    'edit' entries and the RC-190/RC-203 Stop clauses were blind on edit-only turns
    (Cursor's lock research). This pins the wiring so it cannot silently unwire."""
    settings = json.loads((Path(__file__).resolve().parent.parent / ".claude" / "settings.json")
                          .read_text(encoding="utf-8"))
    edit_matchers = [m for m in settings["hooks"]["PreToolUse"]
                     if "Edit" in (m.get("matcher") or "")]
    assert edit_matchers, "no PreToolUse matcher covers Edit tools at all"
    cmds = "\n".join(h["command"] for m in edit_matchers for h in m["hooks"])
    assert "operator_law_guard" in cmds, (
        "operator_law_guard is not wired for Edit/Write — its ledger cannot see production "
        "edits and every edit-dependent Stop clause is blind (RC-205)")
    # BEDROCK 2026-09-06: pretooluse_guard is off the roster by design (its content gates and
    # the mutation-side latch are removed); an inert rostered guard is the E-05/E-07 class.
    assert "pretooluse_guard" not in cmds


#: Split so this file's own text is not read as the actions it names.
D = "d" + "ata/"


def test_a_program_named_by_its_full_path_or_exe_is_judged_as_that_program():
    """`C:\\Git\\usr\\bin\\rm.exe -rf data/ed_console.db` passed all four guards (reviewer,
    2026-10-06): the guard knew `rm`, not rm given by path or with `.exe`. The same spelling of
    git slipped past the blind-staging and lock-disable bans."""
    from tools.operator_law_guard import bash_violations
    for cmd in (f"C:\\Git\\usr\\bin\\rm.exe -rf {D}ed_console.db",
                f"rm.exe {D}ed_console.db",
                "C:\\Git\\cmd\\git.exe add " + "-A",
                "& \"C:\\Program Files\\Git\\cmd\\git.exe\" commit -n -m x"):
        assert bash_violations(cmd), cmd
    for cmd in ("C:\\Git\\usr\\bin\\rm.exe -rf /tmp/scratch", "C:\\Git\\cmd\\git.exe add tools/x.py"):
        assert bash_violations(cmd) == [], cmd


B = "b" + "ackups"


def test_python_by_its_full_path_and_whole_trees_are_judged():
    """Correctness and architecture reviews, 2026-10-06: each of these passed the law guard.
    `python.exe -c` code was read only for the bare word `python`; a remover given the tree
    itself (`data`, no trailing slash), `find ... -delete` and `cmd /c del` were not read."""
    from tools.operator_law_guard import bash_violations
    for cmd in (f"C:\\Python313\\python.exe -c \"import os; os.remove('{D}ed_console.db')\"",
                f"python3.13 -c \"import shutil; shutil.rmtree('{B}/db')\"",
                f"rm -r {B}",
                f"Remove-Item -Recurse {D[:-1]}",
                f"find {D[:-1]} -delete",
                f"mv {D[:-1]} /tmp/",
                f"cmd /c del {D[:-1]}\\ed_console.db",
                f"cmd.exe /c \"del {D[:-1]}\\ed_console.db\""):
        assert bash_violations(cmd), cmd
    for cmd in ("find . -name '*.pyc' -delete", "rm -r build", "cmd /c dir data"):
        assert bash_violations(cmd) == [], cmd


def test_rm_by_full_path_is_refused_through_the_hook_chain():
    """The real wiring: hook_chain with the four guards the settings run exits 2."""
    root = Path(__file__).resolve().parent.parent
    guards = ["tools/operator_law_guard.py", "tools/process_lock_guard.py",
              "tools/operator_yes_guard.py", "tools/sed_edit_guard.py"]
    payload = {"tool_name": "Bash", "hook_event_name": "PreToolUse", "cwd": str(root),
               "tool_input": {"command": f"C:\\Git\\usr\\bin\\rm.exe -rf {D}ed_console.db"}}
    r = subprocess.run([sys.executable, "tools/hook_chain.py", *guards], cwd=root,
                       input=json.dumps(payload), capture_output=True, text=True)
    assert r.returncode == 2 and "RC-273" in r.stderr, (r.returncode, r.stderr)
