"""Seams for staged credential-leak firewall."""

import subprocess

import pytest

from tools.check_credential_leak import DiffUnreadable, find_credential_leaks

SECRET = "Authorization: Bearer supersecrettokenvalue99\n"


def _staged(root, files, config=()):
    """A new repository at `root` with `files` ({path: text}, written byte for byte) staged, as the
    hook finds it; `config` is (key, value) pairs set in that repository first."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for key, value in config:
        subprocess.run(["git", "config", key, value], cwd=root, check=True)
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(text.encode("utf-8"))
    if files:
        subprocess.run(["git", "add", *files], cwd=root, check=True)
    return root


def _staged_as(root, path: bytes, text):
    """Stage `text` under a name the disk may not hold, through the index itself."""
    sha = (
        subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=root,
            check=True,
            capture_output=True,
            input=text.encode(),
        )
        .stdout.decode()
        .strip()
    )
    subprocess.run(
        ["git", "update-index", "--add", "-z", "--index-info"],
        cwd=root,
        check=True,
        input=f"100644 {sha}\t".encode() + path + b"\0",
    )
    staged = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    ).stdout
    assert path + b"\0" in staged, staged
    return root


def _labels(root):
    return [h.split(": ")[:2] for h in find_credential_leaks(root)]


def test_a_secret_after_an_added_line_starting_plus_plus_is_refused(tmp_path):
    """An added `++ b/<skipped path>` line is a line of the file, not a header, and a secret
    written on a `++` line is scanned like any other."""
    root = _staged(
        tmp_path,
        {"app.py": "x = 1\n++ b/tests/test_credential_leak_v1.py\n" + SECRET + "++ " + SECRET},
    )
    assert _labels(root) == [["app.py", "bearer_token"]] * 2


def test_a_secret_in_a_file_git_quotes_after_a_skipped_file_is_refused(tmp_path):
    """git quotes a name holding a non-ASCII character; that header starts a new file, so the
    skipped file before it does not carry over."""
    root = _staged(tmp_path, {"tools/check_credential_leak.py": "x = 1\n", "tools/é.py": SECRET})
    assert _labels(root) == [["tools/é.py", "bearer_token"]]


def test_a_carriage_return_inside_an_added_line_neither_hides_a_secret_nor_starts_a_header(
    tmp_path,
):
    """git ends a line only at a line feed; a lone carriage return is text of the line."""
    root = _staged(
        tmp_path,
        {
            "app.py": "x = 1\r"
            + SECRET
            + "y\rdiff --git a/q b/q\r+++ b/tests/test_credential_leak_v1.py\r@@ -0,0 +1 @@\n"
            + SECRET
        },
    )
    assert _labels(root) == [["app.py", "bearer_token"]] * 2


@pytest.mark.parametrize(
    "files, config",
    [
        ({".gitattributes": "evil.txt -diff\n", "evil.txt": SECRET}, ()),
        ({"evil.txt": "\0" + SECRET}, ()),
        (
            {".gitattributes": "evil.txt diff=hide\n", "evil.txt": SECRET},
            (("diff.hide.textconv", "true"),),
        ),
        ({"evil.txt": SECRET}, (("diff.external", "true"),)),
    ],
    ids=["no-diff attribute", "NUL byte", "textconv", "external diff"],
)
def test_a_secret_git_would_show_otherwise_is_still_read(tmp_path, files, config):
    """The scan reads the bytes the commit publishes, whatever the repository's diff settings."""
    assert _labels(_staged(tmp_path, files, config)) == [["evil.txt", "bearer_token"]]


@pytest.mark.parametrize(
    "path", [b"tests\\test_credential_leak_v1.py", b"tests/test_credential_leak_v1.py "]
)
def test_only_the_skipped_path_itself_is_skipped(tmp_path, path):
    """A name that differs from a skip entry by a backslash or a trailing space is another file."""
    root = _staged_as(
        _staged(tmp_path, {}, (("core.protectNTFS", "false"),)), path, SECRET
    )  # names Windows cannot hold on disk
    assert _labels(root) == [[path.decode(), "bearer_token"]]


def test_a_file_name_that_is_not_utf8_is_not_a_clean_diff(tmp_path):
    """A header that cannot be read names no file, so nothing after it was scanned under its name:
    the diff is unread, never clean."""
    root = _staged_as(_staged(tmp_path, {}), b"a\xff.py", SECRET)
    with pytest.raises(DiffUnreadable, match="could not be read"):
        find_credential_leaks(root)


def test_detects_bearer_and_home_path(tmp_path):
    # Payloads live under a non-skipped path so the detector can fire.
    hits = find_credential_leaks(
        _staged(tmp_path, {"evil.py": SECRET + "path = 'C:/Users/someone/secret.json'\n"})
    )
    assert any("bearer_token" in h for h in hits)
    assert any("windows_user_home" in h for h in hits)


def test_detects_a_git_bash_home_path(tmp_path):
    """Git Bash spells the Windows home `/c/Users/<name>/`; it is an operator-home path too."""
    root = _staged(
        tmp_path, {"tests/test_x.py": 'cmd = "cd /c/Users/someone/Documents/repo && ls"\n'}
    )
    assert any("git_bash_user_home" in h for h in find_credential_leaks(root))


def test_fixture_marker_suppresses(tmp_path):
    root = _staged(
        tmp_path, {"tests/test_x.py": "Bearer supersecrettokenvalue99  # credential-leak-ok\n"}
    )
    assert find_credential_leaks(root) == []


def test_scanner_own_suite_path_is_skipped(tmp_path):
    """Staging this test file must not trip the firewall on its own fixtures."""
    root = _staged(
        tmp_path,
        {"tests/test_credential_leak_v1.py": SECRET + "path = 'C:/Users/someone/secret.json'\n"},
    )
    assert find_credential_leaks(root) == []


def test_clean_addition_passes(tmp_path):
    root = _staged(tmp_path, {"tools/run_provenance.py": 'return {"git_commit": sha}\n'})
    assert find_credential_leaks(root) == []


def test_a_secret_a_pull_request_commits_is_refused_against_its_base(tmp_path):
    """CI runs the scanner on each commit of the pull request (`--base`): a commit made where the
    pre-commit hook does not run (GitHub's editor, a skipped hook) is still read, and so is a
    secret a later commit removes again, since the merge publishes every commit."""
    root = _staged(tmp_path, {"app.py": "x = 1\n"})
    git = lambda *a: subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *a],
        cwd=root,
        check=True,
        capture_output=True,
    )
    git("commit", "-q", "-m", "base")
    git("branch", "base")
    (root / "app.py").write_text("x = 1\n" + SECRET, encoding="utf-8")
    git("commit", "-q", "-am", "adds a secret")
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    git("commit", "-q", "-am", "removes it again")
    assert find_credential_leaks(root) == []  # nothing staged
    assert [h.split(": ")[:2] for h in find_credential_leaks(root, base="base")] == [
        ["app.py", "bearer_token"]
    ]


def test_a_secret_typed_into_a_merge_resolution_is_refused(tmp_path):
    """A conflict resolved in a merge commit (GitHub's web conflict editor runs no hook) is read for
    what the resolution adds; the lines main brings in through the merge are not the PR's."""
    root = _staged(tmp_path, {"app.py": "x = 1\n"})
    git = lambda *a: subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *a],
        cwd=root,
        capture_output=True,
    )
    git("commit", "-q", "-m", "base")
    git("branch", "-M", "main")
    git("checkout", "-q", "-b", "pr")
    (root / "app.py").write_text("x = 2\n", encoding="utf-8")
    git("commit", "-q", "-am", "pr side")
    git("checkout", "-q", "main")
    # main's side carries a flagged line of its own (another label): the merge brings it in, and a
    # scan that reported main's lines would list it beside the resolution's token
    (root / "app.py").write_text("x = 3\n", encoding="utf-8")
    (root / "main_only.py").write_text("k = 'AKIA" + "ABCDEFGHIJKLMNOP'\n", encoding="utf-8")
    git("add", "main_only.py")
    git("commit", "-q", "-am", "main side")
    git("checkout", "-q", "pr")
    assert git("merge", "main").returncode != 0, "the merge must conflict"
    (root / "app.py").write_text("x = 4\n" + SECRET, encoding="utf-8")
    git("add", "app.py")
    assert git("commit", "-q", "--no-edit").returncode == 0
    assert [h.split(": ")[:2] for h in find_credential_leaks(root, base="main")] == [
        ["app.py", "bearer_token"]
    ]
