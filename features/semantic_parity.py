"""
Semantic parity at the MVP contract boundary: equivalent live vs DB source rows must
canonicalize to identical feature dicts when the same logical values are supplied.

This does not prove economic correctness; it proves identical transformation rules
(strict coercion + ordering) for controlled fixtures.
"""

from __future__ import annotations

from typing import Any

from features.db_feature_adapter import build_db_mvp_feature_row
from features.live_feature_adapter import build_live_mvp_feature_row


def assert_live_db_canonicalization_equivalent(
    live_payload: dict[str, Any],
    db_row: dict[str, Any],
) -> None:
    """
    Build both canonical rows and assert bitwise equality.

    Raises:
        AssertionError: if canonical rows differ.
        MvpFeatureSourceError: if either source payload is invalid (same as adapters).
    """
    a = build_live_mvp_feature_row(live_payload)
    b = build_db_mvp_feature_row(db_row)
    assert a == b, f"canonical mismatch: live={a!r} db={b!r}"
