# authlib takes httpx2 when it is installed, else httpx (authlib/integrations/httpx_client/
# _compat.py); this program runs httpx, so the client is an httpx.Client.
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

import httpx
from authlib.oauth2.client import OAuth2Client as _OAuth2Client
from httpx._client import UseClientDefault
from httpx._types import AuthTypes

class OAuth2Client(_OAuth2Client, httpx.Client):
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        token_endpoint_auth_method: str | None = None,
        revocation_endpoint_auth_method: str | None = None,
        scope: str | list[str] | tuple[str, ...] | set[str] | None = None,
        redirect_uri: str | None = None,
        token: dict[str, Any] | None = None,
        token_placement: str = "header",
        update_token: Callable[..., object] | None = None,
        **kwargs: Any,
    ) -> None: ...
    def request(
        self,
        method: str,
        url: httpx.URL | str,
        withhold_token: bool = False,
        auth: AuthTypes | UseClientDefault | None = ...,
        **kwargs: Any,
    ) -> httpx.Response: ...
    # httpx.Client.stream's context manager, returned as httpx made it (@contextmanager)
    @contextmanager
    def stream(
        self,
        method: str,
        url: httpx.URL | str,
        withhold_token: bool = False,
        auth: AuthTypes | UseClientDefault | None = ...,
        **kwargs: Any,
    ) -> Generator[httpx.Response]: ...
