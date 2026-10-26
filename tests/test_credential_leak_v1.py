"""Seams for staged credential-leak firewall."""
import subprocess

import pytest

from tools.check_credential_leak import StagedDiffUnreadable, _staged_text, find_credential_leaks

SECRET = "Authorization: Bearer supersecrettokenvalue99\n"


def _staged(root, files):
    """The staged diff of `files` ({path: text}) in a new repository at `root`, as the hook reads it."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", *files], cwd=root, check=True)
    return _staged_text(root)


def test_a_secret_after_an_added_line_starting_plus_plus_is_refused(tmp_path):
    """An added `++ b/<skipped path>` line is a line of the file, not a header, and a secret
    written on a `++` line is scanned like any other."""
    diff = _staged(tmp_path, {"app.py": "x = 1\n++ b/tests/test_credential_leak_v1.py\n" + SECRET
                              + "++ " + SECRET})
    assert [h.split(": ")[:2] for h in find_credential_leaks(diff)] == [["app.py", "bearer_token"]] * 2


def test_a_secret_in_a_file_git_quotes_after_a_skipped_file_is_refused(tmp_path):
    """git quotes a name holding a non-ASCII character; that header starts a new file, so the
    skipped file before it does not carry over."""
    diff = _staged(tmp_path, {"tools/check_credential_leak.py": "x = 1\n", "tools/é.py": SECRET})
    assert [h.split(": ")[:2] for h in find_credential_leaks(diff)] == [["tools/é.py", "bearer_token"]]


def test_a_file_name_that_is_not_utf8_is_not_a_clean_diff(tmp_path):
    """A header that cannot be read names no file, so nothing after it was scanned under its name:
    the diff is unread, never clean."""
    _staged(tmp_path, {})
    sha = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=tmp_path, check=True,
                         capture_output=True, input=SECRET.encode()).stdout.decode().strip()
    subprocess.run(["git", "update-index", "--add", "-z", "--index-info"], cwd=tmp_path, check=True,
                   input=f"100644 {sha}\t".encode() + b"a\xff.py\0")
    with pytest.raises(StagedDiffUnreadable, match="could not be read"):
        find_credential_leaks(_staged_text(tmp_path))


def test_detects_bearer_and_home_path(tmp_path):
    # Payloads live under a non-skipped path so the detector can fire.
    hits = find_credential_leaks(_staged(tmp_path, {"evil.py": SECRET + "path = 'C:/Users/someone/secret.json'\n"}))
    assert any("bearer_token" in h for h in hits)
    assert any("windows_user_home" in h for h in hits)


def test_detects_a_git_bash_home_path(tmp_path):
    """Git Bash spells the Windows home `/c/Users/<name>/`; it is an operator-home path too."""
    diff = _staged(tmp_path, {"tests/test_x.py": 'cmd = "cd /c/Users/someone/Documents/repo && ls"\n'})
    assert any("git_bash_user_home" in h for h in find_credential_leaks(diff))


def test_fixture_marker_suppresses(tmp_path):
    diff = _staged(tmp_path, {"tests/test_x.py": "Bearer supersecrettokenvalue99  # credential-leak-ok\n"})
    assert find_credential_leaks(diff) == []


def test_scanner_own_suite_path_is_skipped(tmp_path):
    """Staging this test file must not trip the firewall on its own fixtures."""
    diff = _staged(tmp_path, {"tests/test_credential_leak_v1.py": SECRET + "path = 'C:/Users/someone/secret.json'\n"})
    assert find_credential_leaks(diff) == []


def test_clean_addition_passes(tmp_path):
    diff = _staged(tmp_path, {"tools/run_provenance.py": 'return {"git_commit": sha}\n'})
    assert find_credential_leaks(diff) == []
