# Every call returns Schwab's answer as httpx sent it. A parameter takes schwab-py's enum or, as
# every client Feed builds has enforce_enums=False, the value Schwab's API names.
import datetime
from collections.abc import Iterable

import httpx

from .base import BaseClient

class Client(BaseClient):
    def get_quotes(
        self,
        symbols: str | Iterable[str],
        *,
        fields: BaseClient.Quote.Fields | Iterable[BaseClient.Quote.Fields | str] | None = None,
        indicative: bool | None = None,
    ) -> httpx.Response: ...
    def get_option_chain(
        self,
        symbol: str,
        *,
        contract_type: BaseClient.Options.ContractType | str | None = None,
        strike_count: int | None = None,
        include_underlying_quote: bool | None = None,
        strategy: BaseClient.Options.Strategy | str | None = None,
        interval: float | None = None,
        strike: float | None = None,
        strike_range: BaseClient.Options.StrikeRange | str | None = None,
        from_date: datetime.date | None = None,
        to_date: datetime.date | None = None,
        volatility: float | None = None,
        underlying_price: float | None = None,
        interest_rate: float | None = None,
        days_to_expiration: int | None = None,
        exp_month: BaseClient.Options.ExpirationMonth | str | None = None,
        option_type: BaseClient.Options.Type | str | None = None,
        entitlement: BaseClient.Options.Entitlement | str | None = None,
    ) -> httpx.Response: ...
    def get_option_expiration_chain(self, symbol: str) -> httpx.Response: ...
    def get_price_history(
        self,
        symbol: str,
        *,
        period_type: BaseClient.PriceHistory.PeriodType | str | None = None,
        period: BaseClient.PriceHistory.Period | int | None = None,
        frequency_type: BaseClient.PriceHistory.FrequencyType | str | None = None,
        frequency: BaseClient.PriceHistory.Frequency | int | None = None,
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
