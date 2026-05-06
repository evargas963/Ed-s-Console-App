"""Draft v2 decision payload helpers.

Pilot 1A is advisory only: these helpers expose the v2 shape without changing
training, promotion, or authoritative v1.1 decision behavior.
"""

from .a2_option_expression import build_a2_option_expression
from .module_a_adapter import build_module_a_a1_decision
from .post_trade_attribution import (
    POST_TRADE_ATTRIBUTION_SCHEMA_VERSION,
    append_post_trade_attribution_record,
    build_post_trade_attribution_record,
    load_recent_post_trade_attribution_records,
)
from .schema import (
    ALLOWED_SOURCE_INDICATORS,
    SCHEMA_VERSION,
    V2_STATUS,
    validate_v2_decision,
)

__all__ = [
    "ALLOWED_SOURCE_INDICATORS",
    "SCHEMA_VERSION",
    "V2_STATUS",
    "POST_TRADE_ATTRIBUTION_SCHEMA_VERSION",
    "append_post_trade_attribution_record",
    "build_a2_option_expression",
    "build_module_a_a1_decision",
    "build_post_trade_attribution_record",
    "load_recent_post_trade_attribution_records",
    "validate_v2_decision",
]

