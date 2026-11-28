"""The sign-in's callback URL is taken as configured, and reauth_schwab.py's offline paths.

One that names no port is refused with that reason, never a host or port filled in. Ed's
re-sign-in command (reauth_schwab.py) with no credentials, with a pasted URL that has no code, its
removal of the old token file and its validation of a saved one: each runs with no request to
Schwab, whose token host the sign-in itself posts to.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import reauth_schwab
from feed import schwab_client as sc
from feed.schwab_client import complete_oauth_from_redirect_url, run_login_flow

pytestmark = pytest.mark.rail

REPO = Path(__file__).resolve().parent.parent

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


def _reauth(tmp_path, *args: str, key: str = "LiveLookingKey") -> subprocess.CompletedProcess:
    """`python reauth_schwab.py *args` as Ed runs it, its token file in `tmp_path`.

    Not in the suite's offline mode (ED_CI_OFFLINE), which takes the credentials away as it is
    built to: the paths these tests run return before any request, and the keys are no one's.
    """
    env = {
        **{k: v for k, v in os.environ.items() if k != "ED_CI_OFFLINE"},
        "SCHWAB_API_KEY": key,
        "SCHWAB_APP_SECRET": "LiveLookingSecret",
        "SCHWAB_TOKEN_PATH": str(tmp_path / "schwab_token.json"),
    }
    return subprocess.run(
        [sys.executable, "reauth_schwab.py", *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_reauth_with_no_credentials_says_what_to_set_and_asks_schwab_nothing(tmp_path):
    done = _reauth(tmp_path, key="")
    assert done.returncode == 1
    assert "No Schwab credentials: set SCHWAB_API_KEY and SCHWAB_APP_SECRET in .env" in done.stderr
    assert not (tmp_path / "schwab_token.json").exists()


def test_reauth_given_a_pasted_url_with_no_code_fails_and_saves_nothing(tmp_path):
    """The redirect-URL flow Ed runs when the browser's callback did not save the token."""
    done = _reauth(tmp_path, "--redirect-url", "https://127.0.0.1:8182/?state=s")
    assert done.returncode == 1
    assert f"Token path: {tmp_path / 'schwab_token.json'}" in done.stdout
    assert f"FAILURE: {NO_CODE}" in done.stdout
    assert not (tmp_path / "schwab_token.json").exists()


@pytest.mark.parametrize("refreshable", [True, False], ids=["refreshable", "no refresh token"])
def test_after_a_save_reauth_prints_what_the_token_holds_and_fails_one_it_cannot_refresh(
    tmp_path, capsys, refreshable
):
    """The validation reauth prints after a new sign-in is saved (no secret value shown)."""
    token = tmp_path / "schwab_token.json"
    saved = {"access_token": "a", "expires_at": 1, "scope": "api"}
    sc.write_token_file_atomically(
        str(token),
        {
            "creation_timestamp": 1,
            "token": {**saved, **({"refresh_token": "r"} if refreshable else {})},
        },
    )
    if refreshable:
        reauth_schwab._print_post_reauth_validation(str(token))
    else:
        with pytest.raises(SystemExit) as ended:
            reauth_schwab._print_post_reauth_validation(str(token))
        assert ended.value.code == 1
    shown = capsys.readouterr().out
    assert f"  refreshable:       {refreshable}" in shown
    assert "  scope:             'api'" in shown
    assert ("FAILURE: Token file has no usable refresh_token" in shown) is not refreshable
    assert '"a"' not in shown and "'a'" not in shown, "no secret value shown"


def test_reauth_removes_the_old_token_file_before_a_new_sign_in(tmp_path, capsys):
    token = tmp_path / "schwab_token.json"
    token.write_text("{}", encoding="utf-8")
    reauth_schwab._remove_old_token(str(token))
    assert not token.exists()
    assert "Removed existing token file." in capsys.readouterr().out
