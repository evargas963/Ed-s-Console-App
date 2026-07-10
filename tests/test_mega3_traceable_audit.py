"""Mega 3 (§F+§G) traceable inventory gate — cross-mega chain-of-trust with Mega 1+2."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

from governance.CHAIN_OF_TRUST_ALLOWLIST import (  # noqa: E402
    ALLOWLIST_BY_ID,
    CHAIN_OF_TRUST_ALLOWLIST,
    REQUIRED_CATEGORIES,
)
from governance.mega1_traceable_inventory import (  # noqa: E402
    MEGA1_FILES,
    MEGA1_TRACEABLE_INVENTORY,
)
from governance.mega2_traceable_inventory import (  # noqa: E402
    MEGA2_FILES,
    MEGA2_TRACEABLE_INVENTORY,
)
from governance.mega3_traceable_inventory import (  # noqa: E402
    MEGA3_FILES,
    MEGA3_TRACEABLE_INVENTORY,
    Mega3TraceableDerivation,
)
from governance.mega_chain_of_trust import (  # noqa: E402
    MegaInventoryBundle,
    assert_mega_chain_closes,
    build_merged_index,
    resolve_producer_chain,
)
from governance.section_inventory_gate import (  # noqa: E402
    all_functions_in_file,
    assert_inventory_covers_all_functions,
)

SCHWAB_LEAF_RE = re.compile(
    r"^(chains|quotes|pricehistory)\.([a-zA-Z0-9_*]+\.)+([a-zA-Z0-9_*]+)$"
)
FORBIDDEN_AGGREGATE_LEAF_RE = re.compile(
    r"^(chains|quotes|pricehistory)\.\*$|^(chains|quotes|pricehistory)\.[a-zA-Z0-9_*]+\.\*$"
)
CATEGORICAL_JUST_RE = re.compile(
    r"\b(upstream schwab|schwab fields|market data|derived intermediate|"
    r"no single schwab|reads or composes market fields)\b",
    re.I,
)
MEGA3_ROW_COUNT = 153  # inventory sync @ VOL_INPUT_CONTRACT 1.0.0 V1: +1 _replay_vol_decimal (replay_signal_input_v1.py)
_PRIOR_MEGA_FILES = MEGA1_FILES | MEGA2_FILES


def _mega_bundles() -> tuple[MegaInventoryBundle, ...]:
    return (
        MegaInventoryBundle("Mega1", MEGA1_FILES, MEGA1_TRACEABLE_INVENTORY),
        MegaInventoryBundle("Mega2", MEGA2_FILES, MEGA2_TRACEABLE_INVENTORY),
        MegaInventoryBundle("Mega3", MEGA3_FILES, MEGA3_TRACEABLE_INVENTORY),
    )


def _validate_row(row: Mega3TraceableDerivation) -> None:
    if CATEGORICAL_JUST_RE.search(row.justification):
        raise AssertionError(
            f"{row.file}:{row.derivation} categorical justification: {row.justification!r}"
        )
    if len(row.justification.strip()) < 12:
        raise AssertionError(f"{row.file}:{row.derivation} justification too short")

    if row.disposition in ("SCHWAB_LEAF", "REPLACED"):
        if row.producer_refs:
            raise AssertionError(f"{row.file}:{row.derivation} leaf row must have empty producer_refs")
        if row.allowlist_id is not None:
            raise AssertionError(f"{row.file}:{row.derivation} leaf row must have allowlist_id None")
        leaf = row.schwab_leaf
        if not leaf or FORBIDDEN_AGGREGATE_LEAF_RE.match(leaf) or not SCHWAB_LEAF_RE.match(leaf):
            raise AssertionError(f"{row.file}:{row.derivation} invalid schwab_leaf: {leaf!r}")

    elif row.disposition == "DERIVED":
        if row.schwab_leaf is not None:
            raise AssertionError(f"{row.file}:{row.derivation} DERIVED must have schwab_leaf None")
        if row.allowlist_id is not None:
            raise AssertionError(f"{row.file}:{row.derivation} DERIVED must have allowlist_id None")
        if not row.producer_refs:
            raise AssertionError(f"{row.file}:{row.derivation} DERIVED requires producer_refs")

    elif row.disposition == "ALLOWLISTED":
        if row.schwab_leaf is not None or row.producer_refs:
            raise AssertionError(f"{row.file}:{row.derivation} ALLOWLISTED must have null leaf and empty refs")
        if not row.allowlist_id or row.allowlist_id not in ALLOWLIST_BY_ID:
            raise AssertionError(f"{row.file}:{row.derivation} unknown allowlist_id {row.allowlist_id!r}")

    elif row.disposition == "NONE":
        if row.schwab_leaf is not None or row.producer_refs or row.allowlist_id is not None:
            raise AssertionError(f"{row.file}:{row.derivation} NONE must have null leaf, refs, allowlist")
        if "derivation" not in row.justification.lower() and "no market" not in row.justification.lower():
            raise AssertionError(
                f"{row.file}:{row.derivation} NONE justification must explain non-derivation"
            )


def test_mega3_inventory_covers_every_function():
    assert_inventory_covers_all_functions(ROOT, MEGA3_FILES, MEGA3_TRACEABLE_INVENTORY)
    for rel in sorted(MEGA3_FILES):
        required = len(all_functions_in_file(ROOT, rel))
        covered = sum(1 for r in MEGA3_TRACEABLE_INVENTORY if r.file == rel)
        assert covered >= required, f"{rel}: inventory {covered} < AST defs {required}"


def test_mega3_scope_complete():
    inv_files = {r.file for r in MEGA3_TRACEABLE_INVENTORY}
    assert inv_files == set(MEGA3_FILES)
    assert len(MEGA3_TRACEABLE_INVENTORY) == MEGA3_ROW_COUNT


def test_mega3_row_schema_valid():
    for row in MEGA3_TRACEABLE_INVENTORY:
        _validate_row(row)


def test_mega3_chain_of_trust_closes():
    assert_mega_chain_closes(_mega_bundles())


def test_mega3_cross_mega_producer_refs_in_prior_inventories():
    prior = {(r.file, r.derivation) for r in MEGA1_TRACEABLE_INVENTORY}
    prior |= {(r.file, r.derivation) for r in MEGA2_TRACEABLE_INVENTORY}
    for row in MEGA3_TRACEABLE_INVENTORY:
        if row.disposition != "DERIVED":
            continue
        for ref in row.producer_refs:
            if ":" not in ref:
                continue
            file, _qual = ref.split(":", 1)
            if file in _PRIOR_MEGA_FILES:
                assert (file, _qual) in prior, f"Mega3 row missing prior-mega producer: {ref}"


def test_mega3_merged_index_has_no_duplicate_keys():
    idx = build_merged_index(_mega_bundles())
    assert len(idx) == (
        len(MEGA1_TRACEABLE_INVENTORY)
        + len(MEGA2_TRACEABLE_INVENTORY)
        + len(MEGA3_TRACEABLE_INVENTORY)
    )


def test_mega3_chain_rejects_missing_producer():
    idx = build_merged_index(_mega_bundles())
    with pytest.raises(AssertionError, match="missing from merged inventory"):
        resolve_producer_chain("features/live_feature_adapter.py:__no_such__", idx)


def test_mega3_allowlist_entries_complete():
    mega3_ids = {e.id for e in CHAIN_OF_TRUST_ALLOWLIST if e.owner_section == "Mega3"}
    assert mega3_ids >= {"mega3_internal_helper"}
    for entry in CHAIN_OF_TRUST_ALLOWLIST:
        if entry.owner_section != "Mega3":
            continue
        assert entry.justification and "TODO" not in entry.justification.upper()
        assert entry.added_in_sha
        assert entry.category in REQUIRED_CATEGORIES


def test_mega3_live_feature_row_traces_to_market_state():
    idx = build_merged_index(_mega_bundles())
    row = idx[("features/live_feature_adapter.py", "build_live_mvp_feature_row")]
    assert row.producer_refs == ("market_state.py:build_market_state",)
    resolve_producer_chain("market_state.py:build_market_state", idx)
