import json
import ssl
from enum import Enum
from typing import Any, Self

from schwab.client.base import BaseClient
from schwab.utils import EnumEnforcer
from websockets.legacy.client import WebSocketClientProtocol

# schwab-py's base of every field enum has no members, as an enum subclassed must not (typing
# spec, Enums); mypy's own check refuses a member-less enum in a stub (mypy/checker.py check_enum)
class _BaseFieldEnum(Enum):  # type: ignore[misc]
    @classmethod
    def all_fields(cls) -> list[Self]: ...
    @classmethod
    def relabel_message(cls, old_msg: dict[str, Any], new_msg: dict[str, Any]) -> None: ...

class UnparsableMessage(Exception):
    raw_msg: str | bytes
    json_parse_exception: json.JSONDecodeError
    def __init__(
        self,
        raw_msg: str | bytes,
        json_parse_exception: json.JSONDecodeError,
        *args: object,
        **kwargs: Any,
    ) -> None: ...

class StreamClient(EnumEnforcer):
    _socket: WebSocketClientProtocol | None
    def __init__(
        self,
        client: BaseClient,
        *,
        account_id: object = None,
        enforce_enums: bool = True,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None: ...
    async def _send(self, obj: object) -> None: ...
    # a frame as schwab-py's JSON decoder returns it
    async def _receive(self) -> Any: ...
    def _make_request(
        self, *, service: str, command: str, parameters: dict[str, Any]
    ) -> tuple[dict[str, Any], int]: ...
    async def login(self, websocket_connect_args: dict[str, Any] | None = None) -> None: ...
    async def logout(self) -> None: ...

    class ChartEquityFields(_BaseFieldEnum):
        SYMBOL = 0
        SEQUENCE = 1
        OPEN_PRICE = 2
        HIGH_PRICE = 3
        LOW_PRICE = 4
        CLOSE_PRICE = 5
        VOLUME = 6
        CHART_TIME_MILLIS = 7
        CHART_DAY = 8

    class LevelOneEquityFields(_BaseFieldEnum):
        SYMBOL = 0
        BID_PRICE = 1
        ASK_PRICE = 2
        LAST_PRICE = 3
        BID_SIZE = 4
        ASK_SIZE = 5
        ASK_ID = 6
        BID_ID = 7
        TOTAL_VOLUME = 8
        LAST_SIZE = 9
        HIGH_PRICE = 10
        LOW_PRICE = 11
        CLOSE_PRICE = 12
        EXCHANGE_ID = 13
        MARGINABLE = 14
        DESCRIPTION = 15
        LAST_ID = 16
        OPEN_PRICE = 17
        NET_CHANGE = 18
        HIGH_PRICE_52_WEEK = 19
        LOW_PRICE_52_WEEK = 20
        PE_RATIO = 21
        DIVIDEND_AMOUNT = 22
        DIVIDEND_YIELD = 23
        NAV = 24
        EXCHANGE_NAME = 25
        DIVIDEND_DATE = 26
        REGULAR_MARKET_QUOTE = 27
        REGULAR_MARKET_TRADE = 28
        REGULAR_MARKET_LAST_PRICE = 29
        REGULAR_MARKET_LAST_SIZE = 30
        REGULAR_MARKET_NET_CHANGE = 31
        SECURITY_STATUS = 32
        MARK = 33
        QUOTE_TIME_MILLIS = 34
        TRADE_TIME_MILLIS = 35
        REGULAR_MARKET_TRADE_MILLIS = 36
        BID_TIME_MILLIS = 37
        ASK_TIME_MILLIS = 38
        ASK_MIC_ID = 39
        BID_MIC_ID = 40
        LAST_MIC_ID = 41
        NET_CHANGE_PERCENT = 42
        REGULAR_MARKET_CHANGE_PERCENT = 43
        MARK_CHANGE = 44
        MARK_CHANGE_PERCENT = 45
        HTB_QUANTITY = 46
        HTB_RATE = 47
        HARD_TO_BORROW = 48
        IS_SHORTABLE = 49
        POST_MARKET_NET_CHANGE = 50
        POST_MARKET_NET_CHANGE_PERCENT = 51

    class LevelOneOptionFields(_BaseFieldEnum):
        SYMBOL = 0
        DESCRIPTION = 1
        BID_PRICE = 2
        ASK_PRICE = 3
        LAST_PRICE = 4
        HIGH_PRICE = 5
        LOW_PRICE = 6
        CLOSE_PRICE = 7
        TOTAL_VOLUME = 8
        OPEN_INTEREST = 9
        VOLATILITY = 10
        MONEY_INTRINSIC_VALUE = 11
        EXPIRATION_YEAR = 12
        MULTIPLIER = 13
        DIGITS = 14
        OPEN_PRICE = 15
        BID_SIZE = 16
        ASK_SIZE = 17
        LAST_SIZE = 18
        NET_CHANGE = 19
        STRIKE_TYPE = 20
        CONTRACT_TYPE = 21
        UNDERLYING = 22
        EXPIRATION_MONTH = 23
        DELIVERABLES = 24
        TIME_VALUE = 25
        EXPIRATION_DAY = 26
        DAYS_TO_EXPIRATION = 27
        DELTA = 28
        GAMMA = 29
        THETA = 30
        VEGA = 31
        RHO = 32
        SECURITY_STATUS = 33
        THEORETICAL_OPTION_VALUE = 34
        UNDERLYING_PRICE = 35
        UV_EXPIRATION_TYPE = 36
        MARK = 37
        QUOTE_TIME_MILLIS = 38
        TRADE_TIME_MILLIS = 39
        EXCHANGE_ID = 40
        EXCHANGE_NAME = 41
        LAST_TRADING_DAY = 42
        SETTLEMENT_TYPE = 43
        NET_PERCENT_CHANGE = 44
        MARK_CHANGE = 45
        MARK_CHANGE_PERCENT = 46
        IMPLIED_YIELD = 47
        IS_PENNY = 48
        OPTION_ROOT = 49
        HIGH_PRICE_52_WEEK = 50
        LOW_PRICE_52_WEEK = 51
        INDICATIVE_ASKING_PRICE = 52
        INDICATIVE_BID_PRICE = 53
        INDICATIVE_QUOTE_TIME = 54
        EXERCISE_TYPE = 55

    class BookFields(_BaseFieldEnum):
        SYMBOL = 0
        BOOK_TIME = 1
        BIDS = 2
        ASKS = 3

    class BidFields(_BaseFieldEnum):
        BID_PRICE = 0
        TOTAL_VOLUME = 1
        NUM_BIDS = 2
        BIDS = 3

    class PerExchangeBidFields(_BaseFieldEnum):
        EXCHANGE = 0
        BID_VOLUME = 1
        SEQUENCE = 2

    class AskFields(_BaseFieldEnum):
        ASK_PRICE = 0
        TOTAL_VOLUME = 1
        NUM_ASKS = 2
        ASKS = 3

    class PerExchangeAskFields(_BaseFieldEnum):
        EXCHANGE = 0
        ASK_VOLUME = 1
        SEQUENCE = 2
