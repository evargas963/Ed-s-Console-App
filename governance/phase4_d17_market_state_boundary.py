"""Phase 4 D17 — market_state.py lexical NOT_MARKET_DATA boundary (register disposition only).

Scope: market_state.py UNREVIEWED rows with lexical scanner pattern kinds only.
Lines that also carry non-lexical UNREVIEWED scanner rows are excluded so
register slice path+line merge cannot NMD collateral wire/canopy rows on the same line.
"""

from __future__ import annotations

from typing import Final

from governance.phase3_d17_adapter_boundary import WIRE_PATTERN_KINDS

PHASE4_MARKET_STATE_PATH: Final[str] = "market_state.py"

PHASE4_LEXICAL_PATTERN_KINDS: frozenset[str] = frozenset(
    {
        "TEXT_LINE_MARKET_TOKEN",
        "pattern_kind_miss",
    }
)

PHASE4_NMD_NOTE: Final[str] = (
    "Phase 4 D17 market_state lexical NOT_MARKET_DATA — prose/docstring/label false positives only"
)

# Lines with both lexical and non-lexical UNREVIEWED rows @ Phase 4 investigation baseline.
PHASE4_LEXICAL_WIRE_LINE_DENYLIST: frozenset[str] = frozenset(
    {
        "1006",
        "1029",
        "1030",
        "1410",
        "1456",
        "1486",
        "1502",
        "1506",
        "1513",
        "1585",
        "1677",
        "1678",
        "1726",
        "1730",
        "1797",
        "595",
        "596",
        "613",
        "649",
        "651",
        "663",
        "702",
        "831",
        "836",
        "837",
        "843",
        "853",
        "875",
        "889",
        "920",
        "970",
        "989",
        "992",
        "993",
        "996",
    }
)

PHASE4_LEXICAL_REGISTER_DENYLIST: frozenset[str] = frozenset(
    {
        "0315e7083881702be5c2",
        "05995602d4184d057e05",
        "10a7ab0f04a5b1e2b738",
        "1843ae040cf7c4c31af3",
        "18ce31805a94efa14a6d",
        "1c446e3b0765e36a0eb9",
        "214d434d3814c830ffad",
        "24792e7466b50c990c59",
        "28c5fac7be7cb8f99fff",
        "2aed52be1672cf844044",
        "2fa29c3227ca7f7e9c0b",
        "31c01473b90fe47d3f76",
        "3632469052328c91cbd8",
        "408b8ba9e4cf4e6302b1",
        "4509a4e18c0861cfd803",
        "57abc81aff5299f4837b",
        "5a7ec9ff08a05f922f2c",
        "61388c98cef16bcf9d2e",
        "6b285cdb444a3c8b0b95",
        "6bfce5954e97aed6e144",
        "7b3f2a87208c289faa97",
        "7ce9457829d242d71654",
        "87b6160cb4ca63b7c5ac",
        "9ea8b2bd88f5617379c9",
        "a0a2257a2826749c5dd1",
        "ad38b0b19f7b5c0a376c",
        "b0dae654c91c19dce513",
        "c4fd6c188ca62ec1d03f",
        "dc49a381c249dfd22e7a",
        "e5e7cc8826f1b8a24fbd",
        "eff6a2fde2444143dd14",
        "f436bec2e8df0b5e3bf3",
        "f8961c2e31b50df4e152",
        "f89b9a35f3254785faa6",
        "fddb4687df5d69bcfb3a",
    }
)

__all__ = (
    "PHASE4_LEXICAL_PATTERN_KINDS",
    "PHASE4_LEXICAL_REGISTER_DENYLIST",
    "PHASE4_LEXICAL_WIRE_LINE_DENYLIST",
    "PHASE4_MARKET_STATE_PATH",
    "PHASE4_NMD_NOTE",
    "WIRE_PATTERN_KINDS",
)
