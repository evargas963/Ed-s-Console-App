from enum import Enum

import httpx
from schwab.auth import TokenMetadata
from schwab.utils import EnumEnforcer

class BaseClient(EnumEnforcer):
    api_key: str
    session: httpx.Client | httpx.AsyncClient
    token_metadata: TokenMetadata | None
    def __init__(
        self,
        api_key: str,
        session: httpx.Client | httpx.AsyncClient,
        *,
        enforce_enums: bool = True,
        token_metadata: TokenMetadata | None = None,
    ) -> None: ...

    class MarketHours:
        class Market(Enum):
            EQUITY = "equity"
            OPTION = "option"
            BOND = "bond"
            FUTURE = "future"
            FOREX = "forex"
