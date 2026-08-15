"""Seams for staged credential-leak firewall."""
from tools.check_credential_leak import find_credential_leaks


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
