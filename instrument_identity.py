"""Compatibility shim — the canonical owner is `app.domain.instrument_identity` (RC-505).

This module carries NO logic. It exists so the 91 existing importers of the root path keep
working while they are re-pointed a few at a time, which is what makes the rehabilitation
incremental instead of a flag-day rewrite. `tools/repo_rehab_status.py::is_compatibility_shim`
decides that structurally: imports, plain assignments, a docstring and `pass` only, and at
least one import from `app`. A single `def` here would make this a second owner of the ticker
key, however short — the duplicate-authority defect the ratchet exists to refuse.

New code must import from `app.domain.instrument_identity`. This file dies when nothing
imports it.
"""
from __future__ import annotations

from app.domain.instrument_identity import (
    BROKER_INDEX_BARE_ROOTS,
    ticker_storage_key,
)

__all__ = ["BROKER_INDEX_BARE_ROOTS", "ticker_storage_key"]
