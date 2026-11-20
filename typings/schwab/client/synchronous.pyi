# Every call returns Schwab's answer as httpx sent it. Every client Feed builds has
# enforce_enums=False, so a parameter is the value Schwab's API names; schwab-py's enums for them,
# which Feed never passes, are not stated.
import datetime
from collections.abc import Iterable

import httpx

from .base import BaseClient

class Client(BaseClient):
    def get_quotes(
        self,
        symbols: str | Iterable[str],
        *,
        fields: Iterable[str] | None = None,
        indicative: bool | None = None,
    ) -> httpx.Response: ...
    def get_option_chain(
        self,
        symbol: str,
        *,
        contract_type: str | None = None,
        strike_count: int | None = None,
        include_underlying_quote: bool | None = None,
        strategy: str | None = None,
        interval: float | None = None,
        strike: float | None = None,
        strike_range: str | None = None,
        from_date: datetime.date | None = None,
        to_date: datetime.date | None = None,
        volatility: float | None = None,
        underlying_price: float | None = None,
        interest_rate: float | None = None,
        days_to_expiration: int | None = None,
        exp_month: str | None = None,
        option_type: str | None = None,
        entitlement: str | None = None,
    ) -> httpx.Response: ...
    def get_option_expiration_chain(self, symbol: str) -> httpx.Response: ...
    def get_price_history(
        self,
        symbol: str,
        *,
        period_type: str | None = None,
        period: int | None = None,
        frequency_type: str | None = None,
        frequency: int | None = None,
        start_datetime: datetime.datetime | None = None,
        end_datetime: datetime.datetime | None = None,
        need_extended_hours_data: bool | None = None,
        need_previous_close: bool | None = None,
    ) -> httpx.Response: ...
    def get_market_hours(
        self,
        markets: BaseClient.MarketHours.Market | Iterable[BaseClient.MarketHours.Market | str],
        *,
        date: datetime.date | None = None,
    ) -> httpx.Response: ...
