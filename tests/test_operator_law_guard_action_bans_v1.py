# institutional-synthetic-ok: these tests INJECT banned shell / edit spellings to prove the
# action bans BLOCK and the sanctioned forms flow — that is their entire purpose.
"""Action-ban controls for tools/operator_law_guard.py: each banned action is refused and the
sanctioned forms pass; the guard is wired for the edit tools."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.operator_law_guard import bash_violations

LOCK = "disables a mechanical lock"


def test_lock_disable_routes_are_git_and_precommits_own():
    """The lock-disable ban refuses the routes that bypass the pre-commit checks: git's
    (`--no-verify`, `-n`, `core.hooksPath`) and pre-commit's (`SKIP=`, uninstall)."""
    for cmd in ("git commit --no-verify -m x", "git commit -n -m x", "git -c core.hooksPath=/dev/null commit",
                "SKIP=institutional-correctness git commit -m x", "$env:SKIP='ruff-correctness'; git commit -m x",
                "pre-commit uninstall", "some_tool --no-verify",
                "ED_UI_MOCKUP_LOCK=off git commit --no-verify -m x",
                "git add a && git commit --no-verify -m x && git push --no-verify"):
        assert any(LOCK in b for b in bash_violations(cmd)), cmd
    for cmd in ("git commit -m 'skip the typo'", "SKIPPED=1 python x.py", "echo pre-commit installed",
                "git push -n origin main", "ED_UI_MOCKUP_LOCK=off git commit", "git commit -m 'normal'"):
        assert not any(LOCK in b for b in bash_violations(cmd)), cmd


@pytest.mark.parametrize("cmd", [
    # an empty heredoc inside a longer search command
    "cd tests/fixtures && grep -oiE '.{120}(stand-?in|synthetic|edited).{120}' "
    "real_cde_complete_chain_half_dollar.json real_options_stream_history_samples.json | head -5; "
    "python - <<'EOF' 2>/dev/null || true\nEOF\nhead -c 900 real_spy_2026_11_20_chain_and_quotes.json; echo",
    "python - <<'EOF'\nEOF\necho ok",
    "python - </dev/null",
    "eval 'python - <<'\"'\"'EOF'\"'\"' 2>/dev/null || true\nEOF\necho \"after python\"'",
    ".venv/Scripts/python.exe - <<'EOF'\nprint(1)\nEOF",
    "printf '' | python -",
    "python <<'EOF'\nprint(1)\nEOF",
    "bash -c \"python - </dev/null\"",
    "bash -lc \"python - </dev/null\"",
    "cmd /c \"python - <nul\"",
    "cmd /c python - <nul",
    "/usr/bin/bash -c \"python - </dev/null\"",
    "python -W ignore - </dev/null",
    "python3.13 - </dev/null",
    "@'\nprint(1)\n'@ | python -",
    "out=$(python - <<'EOF'\nprint(1)\nEOF\n)",                             # command substitution
    "echo \"$(python - </dev/null)\"",
])
def test_python_reading_its_program_from_stdin_is_refused(cmd):
    assert any("python -c" in b and "script file" in b for b in bash_violations(cmd))


@pytest.mark.parametrize("cmd", [
    "python script.py", "python -c \"print(1)\"", "python -m pytest -q", "python --version",
    ".venv/Scripts/python.exe tools/check_end_to_end.py --base origin/main",
    "python script.py < input.txt", "echo 'python - reads stdin'",
    "cat > notes.txt <<'EOF'\npython - <<'X'\nEOF",
    # a quoted `|` is not a pipe: `py` inside a regex is not a program
    "git ls-files | grep -E '^[^/]+\\.(js|mjs|py|html)$'", "grep -E 'a|py|b' f",
    # launcher listings and attached -m / -c read no program from stdin
    "py -0", "py -0p", "py --list", "python -mpytest -q", "python -c\"print(1)\"",
    # a shell or eval named only inside quoted text runs nothing
    "git commit -m \"fix: eval python - hang\"", "echo \"wrap it as bash -c python - </dev/null\"",
    "echo '$(python - </dev/null)'",
])
def test_python_with_a_script_or_c_or_m_runs(cmd):
    assert not any("python -c" in b for b in bash_violations(cmd))


def test_operator_law_guard_wired_for_edit_tools():
    """.claude/settings.json routes the edit tools to operator_law_guard, and pretooluse_guard is
    not on the roster."""
    settings = json.loads((Path(__file__).resolve().parent.parent / ".claude" / "settings.json")
                          .read_text(encoding="utf-8"))
    edit_matchers = [m for m in settings["hooks"]["PreToolUse"]
                     if "Edit" in (m.get("matcher") or "")]
    assert edit_matchers, "no PreToolUse matcher covers Edit tools at all"
    cmds = "\n".join(h["command"] for m in edit_matchers for h in m["hooks"])
    assert "operator_law_guard" in cmds, (
        "operator_law_guard is not wired for Edit/Write")
    assert "pretooluse_guard" not in cmds


#: The protected tree, as the commands below name it.
D = "data"


def test_a_whole_protected_tree_find_delete_and_cmd_c_are_refused():
    """A remover given the tree itself (`data`, no trailing slash), `find ... -delete` or `-exec`,
    `cmd /c del`, and rm by its full path are refused."""
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
