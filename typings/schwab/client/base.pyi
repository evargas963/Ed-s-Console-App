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

    class Quote:
        class Fields(Enum):
            QUOTE = "quote"
            FUNDAMENTAL = "fundamental"
            EXTENDED = "extended"
            REFERENCE = "reference"
            REGULAR = "regular"

    class Options:
        class ContractType(Enum):
            CALL = "CALL"
            PUT = "PUT"
            ALL = "ALL"

        class Strategy(Enum):
            SINGLE = "SINGLE"
            ANALYTICAL = "ANALYTICAL"
            COVERED = "COVERED"
            VERTICAL = "VERTICAL"
            CALENDAR = "CALENDAR"
            STRANGLE = "STRANGLE"
            STRADDLE = "STRADDLE"
            BUTTERFLY = "BUTTERFLY"
            CONDOR = "CONDOR"
            DIAGONAL = "DIAGONAL"
            COLLAR = "COLLAR"
            ROLL = "ROLL"

        class StrikeRange(Enum):
            IN_THE_MONEY = "ITM"
            NEAR_THE_MONEY = "NTM"
            OUT_OF_THE_MONEY = "OTM"
            STRIKES_ABOVE_MARKET = "SAK"
            STRIKES_BELOW_MARKET = "SBK"
            STRIKES_NEAR_MARKET = "SNK"
            ALL = "ALL"

        class Type(Enum):
            STANDARD = "S"
            NON_STANDARD = "NS"
            ALL = "ALL"

        class ExpirationMonth(Enum):
            JANUARY = "JAN"
            FEBRUARY = "FEB"
            MARCH = "MAR"
            APRIL = "APR"
            MAY = "MAY"
            JUNE = "JUN"
            JULY = "JUL"
            AUGUST = "AUG"
            SEPTEMBER = "SEP"
            OCTOBER = "OCT"
            NOVEMBER = "NOV"
            DECEMBER = "DEC"
            ALL = "ALL"

        class Entitlement(Enum):
            PAYING_PRO = "PP"
            NON_PRO = "NP"
            NON_PAYING_PRO = "PN"

    class PriceHistory:
        class PeriodType(Enum):
            DAY = "day"
            MONTH = "month"
            YEAR = "year"
            YEAR_TO_DATE = "ytd"

        class Period(Enum):
            ONE_DAY = 1
            TWO_DAYS = 2
            THREE_DAYS = 3
            FOUR_DAYS = 4
            FIVE_DAYS = 5
            TEN_DAYS = 10
            ONE_MONTH = 1
            TWO_MONTHS = 2
            THREE_MONTHS = 3
            SIX_MONTHS = 6
            ONE_YEAR = 1
            TWO_YEARS = 2
            THREE_YEARS = 3
            FIVE_YEARS = 5
            TEN_YEARS = 10
            FIFTEEN_YEARS = 15
            TWENTY_YEARS = 20
            YEAR_TO_DATE = 1

        class FrequencyType(Enum):
            MINUTE = "minute"
            DAILY = "daily"
            WEEKLY = "weekly"
            MONTHLY = "monthly"

        class Frequency(Enum):
            EVERY_MINUTE = 1
            EVERY_FIVE_MINUTES = 5
            EVERY_TEN_MINUTES = 10
            EVERY_FIFTEEN_MINUTES = 15
            EVERY_THIRTY_MINUTES = 30
            DAILY = 1
            WEEKLY = 1
            MONTHLY = 1

    class MarketHours:
        class Market(Enum):
            EQUITY = "equity"
            OPTION = "option"
            BOND = "bond"
            FUTURE = "future"
            FOREX = "forex"
