"""tools/shell_parse.read: one quote-aware reader of a shell command's statements, for every
command guard."""

from __future__ import annotations

import pytest

from tools.shell_parse import read


def _words(cmd: str) -> list[list[str]]:
    return [list(st.words) for st in read(cmd)]


@pytest.mark.parametrize(
    "cmd",
    [
        "(python - </dev/null)",
        "if true; then python - </dev/null; fi",
        "timeout 60 python - </dev/null",
        "out=$(python - <<'EOF'\nprint(1)\nEOF\n)",
        'echo "$(python - </dev/null)"',
        "echo `python - </dev/null`",
        'bash -c "python - </dev/null"',
        "cmd /c python - <nul",
    ],
)
def test_a_python_behind_a_keyword_subshell_wrapper_or_substitution_is_a_statement(cmd):
    assert ["python", "-"] in _words(cmd)


def test_text_inside_quotes_is_one_word_and_no_statement():
    assert _words('git commit -m "fix: guard (eval python - hang); next"') == [
        ["git", "commit", "-m", "fix: guard (eval python - hang); next"]
    ]
    assert _words("echo '$(python - </dev/null)'") == [["echo", "$(python - </dev/null)"]]


def test_a_multi_line_quoted_argument_stays_in_its_statement():
    query = "gh api graphql -f query='\nmutation {\n  mergePullRequest(input: {x: 1}) { y }\n}'"
    assert _words(query) == [
        [
            "gh",
            "api",
            "graphql",
            "-f",
            "query=\nmutation {\n  mergePullRequest(input: {x: 1}) { y }\n}",
        ]
    ]


@pytest.mark.parametrize(
    "cmd, ps",
    [
        ("echo $'don\\'t'; gh pr merge 5", False),  # $'...' with an escaped quote
        ("cat <<\\EOF > n.txt\nhi\nEOF\ngh pr merge 5", False),  # a backslash-quoted heredoc tag
        ("a=($(gh pr merge 5))", False),
        ("echo ${X:-$(gh pr merge 5)}", False),  # $( ) inside ( ) or ${ }
        ("$o.Invoke((gh pr merge 5))", True),  # PowerShell ( ) in a word
        (
            "python -c \"import os; os.system('gh pr merge 5')\"",
            False,
        ),  # a shell command python runs
        ("@'\ngh pr merge 5\n'@ | iex", True),  # a here-string piped into iex
        ("env -S 'gh pr merge 5'", False),
        ("wsl gh pr merge 5", False),
        ("uv run gh pr merge 5", False),
    ],
)
def test_a_statement_after_or_inside_these_forms_is_read(cmd, ps):
    assert ["gh", "pr", "merge", "5"] in [list(st.words) for st in read(cmd, powershell=ps)]


def test_an_escaped_quote_in_dollar_single_quotes_inside_a_substitution_hides_nothing():
    assert ["gh", "pr", "merge", "5"] in [
        list(st.words) for st in read("x=$(echo $'it\\'s'); echo 'y)'; gh pr merge 5")
    ]


@pytest.mark.parametrize(
    "code",
    ["-" * 100000 + "1", "1" + "+1" * 200000, "x = '\ud800'"],
    ids=["deep-unary", "deep-sum", "lone-surrogate"],
)
def test_python_code_too_deep_or_unencodable_to_parse_runs_nothing(code):
    """Python cannot compile it either (MemoryError, RecursionError, UnicodeEncodeError from the parser)."""
    assert [list(st.words[:2]) for st in read(f'python -c "{code}"')] == [["python", "-c"]]


def test_a_python_argv_list_is_one_word_per_element():
    """`subprocess.run([...])` runs no shell: a `|` inside an element is not a pipe."""
    cmd = (
        "python -c \"import subprocess; subprocess.run(['powershell', '-Command', "
        '\'Get-Process | Where-Object {$_.CommandLine -like \\"*x*\\"}\'])"'
    )
    sts = read(cmd)
    assert not any(s.words[0].startswith("$_") and not s.powershell for s in sts)
    assert any(list(s.words[:2]) == ["powershell", "-Command"] for s in sts)


@pytest.mark.parametrize(
    "wrapper", ["command", "time", "nohup", "call", "exec", "time -f '$s: %es'", "time -o t.txt"]
)
def test_a_wrapper_without_valued_options_wraps(wrapper):
    assert ["gh", "pr", "merge", "5"] in [list(st.words) for st in read(f"{wrapper} gh pr merge 5")]


def test_a_called_quoted_path_is_a_program_word():
    st = read('& "C:\\Program Files\\GitHub CLI\\gh" pr merge 5', powershell=True)[-1]
    assert st.program == "gh" and st.raw[0] == '& "C:\\Program Files\\GitHub CLI\\gh"'


def test_shell_arithmetic_runs_only_its_substitutions():
    assert _words("(( $n > 5 )) && echo big") == [["echo", "big"]]
    assert _words("for (( i=0; i<$n; i++ )); do echo $i; done") == [["for"], ["echo", "$i"]]
    assert ["gh", "pr", "merge", "5"] in _words("(( $(gh pr merge 5) > 0 ))")
    assert ["gh", "pr", "merge", "5"] in _words(
        "(( ($(gh pr merge 5)) > 0 ))"
    )  # inside ( ) in the arithmetic
    assert _words("for((i=0; i<$n; i++)); do echo $i; done") == [
        ["for"],
        ["echo", "$i"],
    ]  # no space
    assert _words("((echo a); gh pr merge 5)") == [
        ["echo", "a"],
        ["gh", "pr", "merge", "5"],
    ]  # nested subshells


def test_a_line_break_and_a_pipe_each_end_a_statement():
    assert _words("gh api repos/o/r/pulls/5 --jq .title\ngrep -n mergePullRequest f") == [
        ["gh", "api", "repos/o/r/pulls/5", "--jq", ".title"],
        ["grep", "-n", "mergePullRequest", "f"],
    ]
    assert _words("gh pr view 5 | grep mergePullRequest") == [
        ["gh", "pr", "view", "5"],
        ["grep", "mergePullRequest"],
    ]
