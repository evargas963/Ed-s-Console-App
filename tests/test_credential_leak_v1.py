"""tools/check_credential_leak.py: the lines a diff adds that carry a credential or an operator-home
path are refused; the repository's own placeholders pass. Values here are placeholders, never secrets."""
import shutil
import subprocess
import sys

import pytest

from tools.check_credential_leak import REPO, find_credential_leaks


def test_detects_bearer_and_home_path():
    # Payloads live under a non-skipped path so the detector can fire.
    diff = """\
+++ b/evil.py
@@ -0,0 +1,2 @@
+Authorization: Bearer supersecrettokenvalue99
+path = 'C:/Users/evarg/secret.json'
"""
    hits = find_credential_leaks(diff)
    assert any("bearer_token" in h for h in hits)
    assert any("windows_user_home" in h for h in hits)


def test_fixture_marker_suppresses():
    diff = """\
+++ b/tests/test_x.py
@@ -0,0 +1 @@
+Bearer supersecrettokenvalue99  # credential-leak-ok
"""
    assert find_credential_leaks(diff) == []


def test_scanner_own_suite_path_is_skipped():
    """Staging this test file must not trip the firewall on its own fixtures."""
    diff = """\
+++ b/tests/test_credential_leak_v1.py
@@ -0,0 +1,2 @@
+Authorization: Bearer supersecrettokenvalue99
+path = 'C:/Users/evarg/secret.json'
"""
    assert find_credential_leaks(diff) == []


def test_clean_addition_passes():
    diff = """\
+++ b/tools/run_provenance.py
@@ -0,0 +1 @@
+return {"git_commit": sha}
"""
    assert find_credential_leaks(diff) == []
PLACEHOLDER_SHAPED_TOKEN = "not-a-real-token-only-its-length-and-shape-0123456789"


def _added(path: str, lines: list[str]) -> str:
    return f"+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{x}\n" for x in lines)


def test_the_committed_examples_are_placeholders_and_pass():
    """.env.example and schwab_token.json.example, as committed, carry no value."""
    for name in (".env.example", "schwab_token.json.example"):
        text = (REPO / name).read_text(encoding="utf-8")
        assert find_credential_leaks(_added(name, text.splitlines())) == [], name


def test_a_schwab_token_file_body_is_refused():
    """schwab_token.json.example's shape with a token-length value in place of the placeholder."""
    example = (REPO / "schwab_token.json.example").read_text(encoding="utf-8")
    body = example.replace("<from OAuth — do not commit>", PLACEHOLDER_SHAPED_TOKEN)
    hits = find_credential_leaks(_added("schwab_token.json", body.splitlines()))
    assert [h.split(": ")[1] for h in hits] == ["schwab_token_json", "schwab_token_json"]


@pytest.mark.parametrize("line", [
    "SCHWAB_API_KEY=not-a-real-key",               # .env.example's line, uncommented, with a value
    "SCHWAB_APP_SECRET=not-a-real-secret",
    "set SCHWAB_APP_SECRET=not-a-real-secret",     # a .bat
    "export SCHWAB_API_KEY=not-a-real-key",        # a shell profile
])
def test_a_schwab_credential_set_with_a_value_is_refused(line):
    assert [h.split(": ")[1] for h in find_credential_leaks(_added(".env", [line]))] == ["schwab_env_credential"]


@pytest.mark.parametrize("path, line", [
    (".env.example", "# SCHWAB_API_KEY="),
    ("playwright.config.mjs", "  env.SCHWAB_API_KEY = 'ci-placeholder-api-key';"),
    ("tests/test_data_path_rules_v1.py",
     '        "access_token": "secret-access", "refresh_token": "secret-refresh", "token_type": "Bearer",'),
])
def test_the_repositorys_own_placeholder_lines_pass(path, line):
    assert find_credential_leaks(_added(path, [line])) == []


def test_ci_scans_the_pull_requests_diff(tmp_path):
    """`--base`: the lines a branch adds since its base, through the real script in a real repo."""
    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "tools").mkdir()
    for name in ("__init__.py", "check_credential_leak.py", "pretooluse_guard.py"):
        shutil.copy(REPO / "tools" / name, tmp_path / "tools" / name)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("add", "tools")
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "pr")
    (tmp_path / "token.json").write_text(f'{{"refresh_token": "{PLACEHOLDER_SHAPED_TOKEN}"}}\n', encoding="utf-8")
    git("add", "token.json")
    git("commit", "-q", "-m", "pr")
    run = subprocess.run([sys.executable, "tools/check_credential_leak.py", "--base", "main"], cwd=tmp_path,
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 1 and "token.json: schwab_token_json" in run.stdout, run.stdout + run.stderr
