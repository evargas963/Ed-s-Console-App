"""Regression for the schwab_client OAuth auth-context override.

schwab_client monkeypatches ``schwab.auth.get_auth_context`` with
``_get_auth_context_with_scope`` so the authorize URL carries an explicit
``scope=`` (Schwab otherwise omits ``refresh_token``). The override MUST stay
signature-compatible with whatever the installed schwab-py calls it with —
schwab-py 1.5.x added a ``base_url`` kwarg, which broke reauth with
``_get_auth_context_with_scope() got an unexpected keyword argument 'base_url'``.

These tests lock: (1) the override is called exactly as the library calls it
(incl. ``base_url``) without raising, (2) it still injects the scope, and
(3) a forward-drift guard — the override accepts every parameter the pristine
library ``get_auth_context`` declares, so the next added kwarg fails here, not at
a live reauth.
"""
from __future__ import annotations

import importlib.util
import inspect

import schwab.auth as auth  # noqa: F401  (import order: ensures schwab.auth loaded)
import schwab_client


def _ctx(**kw):
    return schwab_client._get_auth_context_with_scope(
        "FAKEKEY", "https://127.0.0.1:8182", **kw
    )


def test_override_accepts_base_url_kwarg_like_schwab_py_1_5():
    # The exact call shape from schwab.auth.client_from_login_flow in 1.5.x.
    ctx = _ctx(state=None, base_url="https://api.schwabapi.com")
    assert type(ctx).__name__ == "AuthContext"
    assert "/v1/oauth/authorize" in ctx.authorization_url
    assert "scope=" in ctx.authorization_url  # the whole reason the override exists


def test_override_defaults_base_url_for_older_callers():
    ctx = _ctx()  # older schwab-py passed only (api_key, callback_url[, state])
    assert "/v1/oauth/authorize" in ctx.authorization_url
    assert "scope=" in ctx.authorization_url


def test_override_signature_is_superset_of_installed_library():
    """Forward-drift guard: load a pristine (unpatched) schwab.auth and require our
    override to accept every parameter the library's get_auth_context declares."""
    spec = importlib.util.find_spec("schwab.auth")
    pristine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pristine)  # fresh copy; not registered in sys.modules

    lib_params = set(inspect.signature(pristine.get_auth_context).parameters)
    our_params = set(inspect.signature(schwab_client._get_auth_context_with_scope).parameters)
    missing = lib_params - our_params
    assert not missing, (
        f"schwab.auth.get_auth_context added param(s) {sorted(missing)} the override "
        f"does not accept — update _get_auth_context_with_scope to mirror the new signature"
    )
