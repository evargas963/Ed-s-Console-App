"""The sign-in's callback URL is taken as configured.

One that names no port is refused with that reason, never a host or port filled in.
"""

from __future__ import annotations

import pytest

from feed.schwab_client import complete_oauth_from_redirect_url, run_login_flow

pytestmark = pytest.mark.rail

#: the sign-in's answer to a pasted URL that carries no code
NO_CODE = "Redirect URL missing OAuth code query parameter."


def test_a_callback_url_with_no_port_is_refused_by_name(tmp_path):
    ok, why = run_login_flow("key", "secret", "https://127.0.0.1", str(tmp_path / "token.json"))
    assert ok is False
    assert "the callback URL names no host or no port: 'https://127.0.0.1'" in why
    assert not (tmp_path / "token.json").exists()


@pytest.mark.parametrize(
    ("pasted", "why"),
    [
        ("  ", "Redirect URL is empty."),
        ("https://127.0.0.1:8182/?state=s", NO_CODE),
        ("https://127.0.0.1:8182/?code=&state=s", NO_CODE),
    ],
    ids=["blank", "no code", "a blank code"],
)
def test_a_pasted_redirect_url_with_no_code_is_refused_before_schwab_is_asked(
    tmp_path, pasted, why
):
    """The URL Ed pastes to reauth_schwab.py: with no code, nothing is sent and nothing saved."""
    token = tmp_path / "token.json"
    assert complete_oauth_from_redirect_url(
        pasted,
        api_key="key",
        app_secret="secret",
        callback_url="https://127.0.0.1:8182",
        token_path=str(token),
    ) == (False, why)
    assert not token.exists()
