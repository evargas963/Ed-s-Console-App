from collections.abc import Callable
from typing import Any

from authlib.oauth2.rfc6749 import OAuth2Token

class OAuth2Client:
    leeway: int
    update_token: Callable[..., object] | None
    def __init__(
        self,
        session: object,
        client_id: str | None = None,
        client_secret: str | None = None,
        token_endpoint_auth_method: str | None = None,
        revocation_endpoint_auth_method: str | None = None,
        scope: str | list[str] | tuple[str, ...] | set[str] | None = None,
        state: str | None = None,
        redirect_uri: str | None = None,
        code_challenge_method: str | None = None,
        token: dict[str, Any] | None = None,
        token_placement: str = "header",
        update_token: Callable[..., object] | None = None,
        leeway: int = 60,
        **metadata: Any,
    ) -> None: ...
    # None: no token is held (the token given was None)
    @property
    def token(self) -> OAuth2Token | None: ...
    @token.setter
    def token(self, token: dict[str, Any] | None) -> None: ...
    # True: the token is active or was refreshed; None: it is expired and nothing refreshes it
    def ensure_active_token(self, token: OAuth2Token | None = None) -> bool | None: ...
