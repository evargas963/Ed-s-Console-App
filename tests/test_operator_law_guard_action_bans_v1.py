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
D = "d" + "ata"


def test_a_whole_protected_tree_find_delete_and_cmd_c_are_refused():
    """Each passed the law guard (reviews, 2026-10-06): a remover given the tree itself (`data`,
    no trailing slash), `find ... -delete` or `-exec`, `cmd /c del`, and rm by its full path."""
    from tools.operator_law_guard import bash_violations
    for cmd in (f"rm -r {D}",
                f"Remove-Item -Recurse {D}",
                f"mv {D} /tmp/",
                f"find {D} -delete",
                f"find ./{D} -name '*.db' -exec rm {{}} +",
                f"cmd /c del {D}\\ed_console.db",
                f"cmd.exe /c \"del {D}\\ed_console.db\"",
                f"C:\\Git\\usr\\bin\\rm.exe -rf {D}/ed_console.db"):
        assert bash_violations(cmd), cmd
    for cmd in ("find . -name '*.pyc' -delete", "rm -r build", f"cmd /c dir {D}", f"find {D} -name '*.db'",
                "C:\\Git\\usr\\bin\\rm.exe -rf /tmp/scratch"):
        assert bash_violations(cmd) == [], cmd
