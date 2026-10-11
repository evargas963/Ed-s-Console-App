"""tools/shell_parse.read: one quote-aware reader of a shell command's statements, for every
command guard."""
from __future__ import annotations

import pytest

from tools.shell_parse import read


def _words(cmd: str) -> list[list[str]]:
    return [list(st.words) for st in read(cmd)]


@pytest.mark.parametrize("cmd", ["(python - </dev/null)", "if true; then python - </dev/null; fi",
                                 "timeout 60 python - </dev/null", "out=$(python - <<'EOF'\nprint(1)\nEOF\n)",
                                 'echo "$(python - </dev/null)"', "echo `python - </dev/null`",
                                 "bash -c \"python - </dev/null\"", "cmd /c python - <nul"])
def test_a_python_behind_a_keyword_subshell_wrapper_or_substitution_is_a_statement(cmd):
    assert ["python", "-"] in _words(cmd)


def test_text_inside_quotes_is_one_word_and_no_statement():
    assert _words('git commit -m "fix: guard (eval python - hang); next"') == [
        ["git", "commit", "-m", "fix: guard (eval python - hang); next"]]
    assert _words("echo '$(python - </dev/null)'") == [["echo", "$(python - </dev/null)"]]


def test_a_multi_line_quoted_argument_stays_in_its_statement():
    query = "gh api graphql -f query='\nmutation {\n  mergePullRequest(input: {x: 1}) { y }\n}'"
    assert _words(query) == [["gh", "api", "graphql", "-f", "query=\nmutation {\n  mergePullRequest(input: {x: 1}) { y }\n}"]]


def test_a_line_break_and_a_pipe_each_end_a_statement():
    assert _words("gh api repos/o/r/pulls/5 --jq .title\ngrep -n mergePullRequest f") == [
        ["gh", "api", "repos/o/r/pulls/5", "--jq", ".title"], ["grep", "-n", "mergePullRequest", "f"]]
    assert _words("gh pr view 5 | grep mergePullRequest") == [["gh", "pr", "view", "5"], ["grep", "mergePullRequest"]]
