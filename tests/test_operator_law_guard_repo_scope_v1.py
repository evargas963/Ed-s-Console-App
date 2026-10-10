"""operator_law_guard's universal protections fire whatever repository a command is aimed at:
the checkout in front of a command never exempts it (RC-258)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import operator_law_guard as G  # noqa: E402


@pytest.fixture()
def other_repo(tmp_path):
    """A real git repository that is NOT Ed Console (a stand-in for any other checkout)."""
    d = tmp_path / "OtherRepo"
    (d / ".git").mkdir(parents=True)
    return d


# Tree-destructive git has one owner on the PreToolUse chain,
# operating_process_lock.reset_guard_violations; it takes no repository at all.
DESTRUCTIVE_GIT = ("git reset --hard HEAD~1", "git clean -fd", "git push --force origin main")


@pytest.mark.parametrize("cmd", DESTRUCTIVE_GIT)
def test_destructive_git_has_one_owner_and_it_fires_unscoped(cmd):
    import tools.operating_process_lock as OPL
    assert any("destructive git" in v for v in OPL.reset_guard_violations(cmd)), cmd


def test_deleting_the_database_fires_in_this_repository():
    out = G.bash_violations("rm -rf data/ed_console.db")
    assert any("RC-273" in v for v in out), out


def test_guard_does_not_return_early_for_an_out_of_scope_repository(other_repo):
    """A banned action AND a commit in one chain aimed at another repository: the universal
    rule must still fire (RC-258: applicability is per rule, never an early return)."""
    out = G.bash_violations('cd "%s" && git add -A && git commit -m x' % other_repo)
    assert any("blind staging" in v for v in out), out
    chain = 'cd "%s" && git reset --hard HEAD~1' % other_repo
    import tools.operating_process_lock as OPL
    assert OPL.reset_guard_violations(chain), chain


def test_non_commit_commands_are_unaffected_by_repository_scoping():
    assert G.bash_violations("git status") == []
    assert G.bash_violations("python -c \"print(1)\"") == []


@pytest.mark.parametrize("cmd", [
    "git add a && git commit --no-verify -m x && git push --no-verify",
    "some_tool --no-verify",
    "ED_UI_MOCKUP_LOCK=off git commit --no-verify -m x",
])
def test_no_verify_is_refused_in_every_spelling(cmd):
    out = G.bash_violations(cmd)
    assert any("disables a mechanical lock" in v for v in out), (cmd, out)
