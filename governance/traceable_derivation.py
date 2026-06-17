"""
Traceable derivation schema (v1) — replaces categorical schwab_leaf strings.

Every inventory row must declare structured inputs and either:
  - validated Schwab leaf path(s), or
  - an explicit allowlist_id for non-Schwab sources.

Categorical trust claims like "upstream ms_dict / SignalInput" are rejected at validation time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Sequence

Disposition = Literal["REPLACED", "KEEP_DERIVED", "PASS_THROUGH", "NONE"]

# Schwab dictionary path prefixes (must match governance crosswalk / wire JSON)
SCHWAB_LEAF_PREFIXES = ("chains.", "quotes.", "pricehistory.")

# Forbidden in schwab leaf paths — categorical hand-waves
FORBIDDEN_LEAF_SUBSTRINGS = (
    "upstream",
    "ms_dict",
    "signalinput",
    "signal_input",
    "inference",
    "snapshots.*",
    "—",
)

# Explicit non-Schwab sources (NONE disposition)
ALLOWLIST_IDS = frozenset(
    {
        "clock_et",
        "session_calendar",
        "sqlite_schema",
        "sql_template",
        "cli_entrypoint",
        "display_formatter",
        "external_finnhub",
        "external_alphavantage",
        "external_event_calendar",
        "http_429_observability",
        "labeled_count_audit",
        "feature_contract_schema",
        "model_contract_schema",
        "training_metadata",
        "composition_root_verified",  # build_market_state after deps close
    }
)

_LEAF_PATH_RE = re.compile(
    r"^(chains\.|quotes\.|pricehistory\.)[a-zA-Z0-9_.*\[\]]+$"
)


@dataclass(frozen=True)
class SchwabLeafRef:
    """Validated Schwab dictionary path (not a free-text category)."""

    path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _normalize_leaf_path(self.path))


@dataclass(frozen=True)
class FieldInputRef:
    """Structured upstream field dependency (producer must be another inventoried function)."""

    carrier: str
    field: str
    producer_file: str
    producer_fn: str


@dataclass(frozen=True)
class TraceableDerivation:
    file: str
    line: int
    derivation: str
    disposition: Disposition
    inputs: tuple[FieldInputRef, ...]
    schwab_leaves: tuple[SchwabLeafRef, ...]
    allowlist_id: str | None
    outputs: tuple[str, ...]
    justification: str

    def __post_init__(self) -> None:
        validate_traceable_derivation(self)


def _normalize_leaf_path(path: str) -> str:
    p = (path or "").strip()
    if not p:
        raise ValueError("schwab leaf path cannot be empty")
    return p


def is_valid_schwab_leaf_path(path: str) -> bool:
    p = path.lower().replace(" ", "")
    if any(bad in p for bad in FORBIDDEN_LEAF_SUBSTRINGS):
        return False
    if not any(p.startswith(prefix) for prefix in SCHWAB_LEAF_PREFIXES):
        return False
    return bool(_LEAF_PATH_RE.match(path.strip()))


def validate_traceable_derivation(row: TraceableDerivation) -> None:
    """Raise ValueError if row violates traceable schema."""
    for leaf in row.schwab_leaves:
        if not is_valid_schwab_leaf_path(leaf.path):
            raise ValueError(
                f"{row.file}:{row.derivation} invalid schwab leaf path {leaf.path!r}"
            )

    if row.disposition in ("REPLACED", "PASS_THROUGH"):
        if not row.schwab_leaves:
            raise ValueError(
                f"{row.file}:{row.derivation} {row.disposition} requires schwab_leaves"
            )
        if row.inputs and row.disposition == "PASS_THROUGH":
            # PASS_THROUGH from wire may still list inputs for documentation; allow either
            pass
        return

    if row.disposition == "KEEP_DERIVED":
        if not row.inputs and not row.schwab_leaves:
            raise ValueError(
                f"{row.file}:{row.derivation} KEEP_DERIVED requires inputs and/or schwab_leaves"
            )
        return

    if row.disposition == "NONE":
        if not row.allowlist_id:
            raise ValueError(
                f"{row.file}:{row.derivation} NONE requires allowlist_id"
            )
        if row.allowlist_id not in ALLOWLIST_IDS:
            raise ValueError(
                f"{row.file}:{row.derivation} unknown allowlist_id {row.allowlist_id!r}"
            )
        return

    raise ValueError(f"unknown disposition {row.disposition!r}")


def reject_categorical_schwab_leaf(leaf: str) -> None:
    """Migrate guard: legacy inventories used categorical schwab_leaf strings."""
    low = (leaf or "").lower()
    if any(bad in low for bad in FORBIDDEN_LEAF_SUBSTRINGS):
        raise ValueError(f"categorical schwab_leaf rejected: {leaf!r}")
    if leaf.strip() in ("—", "-", ""):
        raise ValueError("empty schwab_leaf must use allowlist_id on NONE rows")


def assert_inventory_is_traceable(inventory: Sequence[TraceableDerivation]) -> None:
    for row in inventory:
        validate_traceable_derivation(row)
