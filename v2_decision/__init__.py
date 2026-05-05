"""Draft v2 decision payload helpers.

Pilot 1A is advisory only: these helpers expose the v2 shape without changing
training, promotion, or authoritative v1.1 decision behavior.
"""

from .module_a_adapter import build_module_a_a1_decision
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
    "build_module_a_a1_decision",
    "validate_v2_decision",
]

