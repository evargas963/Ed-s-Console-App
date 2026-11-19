from collections.abc import Callable
from typing import Any, NamedTuple

from schwab.client.base import BaseClient

TOKEN_ENDPOINT: str

class TokenMetadata:
    creation_timestamp: int
    unwrapped_token_write_func: Callable[..., object]
    token: dict[str, Any]
    def __init__(
        self,
        token: dict[str, Any],
        creation_timestamp: int,
        unwrapped_token_write_func: Callable[..., object],
    ) -> None: ...
    @classmethod
    def from_loaded_token(
        cls, token: dict[str, Any], unwrapped_token_write_func: Callable[..., object]
    ) -> TokenMetadata: ...
    def token_age(self) -> int: ...
    def wrapped_token_write_func(self) -> Callable[..., object]: ...
    def wrap_token_in_metadata(self, token: dict[str, Any]) -> dict[str, Any]: ...

class AuthContext(NamedTuple):
    callback_url: str
    authorization_url: str
    state: str

def client_from_login_flow(
    api_key: str,
    app_secret: str,
    callback_url: str,
    token_path: str,
    asyncio: bool = False,
    enforce_enums: bool = False,
    token_write_func: Callable[..., object] | None = None,
    callback_timeout: float = 300.0,
    interactive: bool = True,
    requested_browser: str | None = None,
) -> BaseClient: ...
def client_from_manual_flow(
    api_key: str,
    app_secret: str,
    callback_url: str,
    token_path: str,
    asyncio: bool = False,
    token_write_func: Callable[..., object] | None = None,
    enforce_enums: bool = True,
) -> BaseClient: ...
def get_auth_context(api_key: str, callback_url: str, state: str | None = None) -> AuthContext: ...
def client_from_received_url(
    api_key: str,
    app_secret: str,
    auth_context: AuthContext,
    received_url: str,
    token_write_func: Callable[..., object],
    asyncio: bool = False,
    enforce_enums: bool = True,
) -> BaseClient: ...
