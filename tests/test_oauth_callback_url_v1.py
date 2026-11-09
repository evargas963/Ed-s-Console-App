"""The sign-in's callback URL is taken as configured.

One that names no port is refused with that reason, never a host or port filled in.
"""

from __future__ import annotations

from schwab_client import run_login_flow


def test_a_callback_url_with_no_port_is_refused_by_name(tmp_path):
    ok, why = run_login_flow("key", "secret", "https://127.0.0.1", str(tmp_path / "token.json"))
    assert ok is False
    assert "the callback URL names no host or no port: 'https://127.0.0.1'" in why
    assert not (tmp_path / "token.json").exists()
