"""Mega 4 (§H+§I) traceable inventory gate — cross-mega chain-of-trust with Mega 1–3."""

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
)
from governance.mega4_traceable_inventory import (  # noqa: E402
    MEGA4_FILES,
    MEGA4_TRACEABLE_INVENTORY,
    Mega4TraceableDerivation,
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
# CLOSED integer ledger for test_mega4_scope_complete (see the named-set conversion below).
# 1044 — RC-297 inventory drift repair 2026-08-09: +5 (ml_data_common._console_read_conn /
#        _read_with_retry / _read_one_row_with_retry, ml_predict._never_trained_ticker,
#        arch_competition/metrics._sklearn_metrics), all NONE and each traced from its own
#        body rather than from a neighbouring row's wording.
# 1070 — +1 RC-436 model_feature_wall_distance_cols; +4 RC-435 structurally withheld wall-distance serve gates (ml_train)  # +21 (RC-328/332/340/343/345 one-authority consolidations that shipped without inventory rows: active_bundle_contract.artifact_ticker_key; lstm_data encode_zone/_anchor_tolerance_s/_snapshot_ts/_spot_at_minutes_back; ml_data_common confluence_history_lookback_s/fetch_confluence_history/confluence_features_for_bar/prepare_row_for_xgb_features; the twelve ml_train fk_* feature kernels) 2026-08-17  # +1 resolve_live_v2_calibration_tail_action (calibration/v2_live_logging.py) — pre-existing inventory gap in uncommitted live-logging work, closed 2026-07-19 (prior: 1038)
#
# 2026-08-24 (audit T2-4) — NAMED-SET CONVERSION. The integer ledger above is CLOSED
# HISTORY: the row count is no longer hand-bumped. The inventory's membership now lives in
# tests/frozen/mega4_inventory_names.txt (one "file.py::qualified_name" per line, sorted),
# and test_mega4_scope_complete diffs the live inventory against it BY NAME, so a
# legitimate change shows WHICH row arrived or left instead of forcing integer
# archaeology. MEGA4_ROW_COUNT stays defined for any reader of this module but is DERIVED
# from the frozen set — never edit it by hand. MEGA4_FILE_COUNT is untouched by the
# conversion: file membership is already named by the inv_files == set(MEGA4_FILES) check.
MEGA4_FROZEN_FILE = ROOT / "tests" / "frozen" / "mega4_inventory_names.txt"
MEGA4_FROZEN_NAMES = frozenset(
    ln for ln in MEGA4_FROZEN_FILE.read_text(encoding="utf-8").splitlines() if ln
)
MEGA4_ROW_COUNT = len(MEGA4_FROZEN_NAMES)  # derived from the frozen name set
MEGA4_FILE_COUNT = 88  # +3 arch_competition PR4 modules
_PRIOR_MEGA_FILES = MEGA1_FILES | MEGA2_FILES | MEGA3_FILES


def _mega_bundles() -> tuple[MegaInventoryBundle, ...]:
    return (
        MegaInventoryBundle("Mega1", MEGA1_FILES, MEGA1_TRACEABLE_INVENTORY),
        MegaInventoryBundle("Mega2", MEGA2_FILES, MEGA2_TRACEABLE_INVENTORY),
        MegaInventoryBundle("Mega3", MEGA3_FILES, MEGA3_TRACEABLE_INVENTORY),
        MegaInventoryBundle("Mega4", MEGA4_FILES, MEGA4_TRACEABLE_INVENTORY),
    )


def _validate_row(row: Mega4TraceableDerivation) -> None:
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


def test_mega4_inventory_covers_every_function():
    assert_inventory_covers_all_functions(ROOT, MEGA4_FILES, MEGA4_TRACEABLE_INVENTORY)
    for rel in sorted(MEGA4_FILES):
        required = len(all_functions_in_file(ROOT, rel))
        covered = sum(1 for r in MEGA4_TRACEABLE_INVENTORY if r.file == rel)
        assert covered >= required, f"{rel}: inventory {covered} < AST defs {required}"


def test_mega4_scope_complete():
    """Named-set scope gate (T2-4, 2026-08-24): the inventory equals the frozen name set.

    The exact-count pin this replaces survives as the closed comment ledger above
    MEGA4_ROW_COUNT; from here on a move is accounted for BY NAME, not by integer.
    """
    inv_files = {r.file for r in MEGA4_TRACEABLE_INVENTORY}
    assert inv_files == set(MEGA4_FILES)
    assert len(MEGA4_FILES) == MEGA4_FILE_COUNT
    current = {f"{r.file}::{r.derivation}" for r in MEGA4_TRACEABLE_INVENTORY}
    arrived = sorted(current - MEGA4_FROZEN_NAMES)
    left = sorted(MEGA4_FROZEN_NAMES - current)
    assert current == MEGA4_FROZEN_NAMES, (
        f"Mega4 inventory membership moved.\n"
        f"ARRIVED (in the inventory, not in the frozen set): {arrived}\n"
        f"LEFT (in the frozen set, no longer in the inventory): {left}\n"
        f"A legitimate arrival/departure is a one-line edit to "
        f"tests/frozen/mega4_inventory_names.txt in the same commit, reviewed by name — "
        f"do not bulk-regenerate."
    )
    # Duplicate guard: set equality alone cannot see a repeated (file, derivation) row.
    assert len(MEGA4_TRACEABLE_INVENTORY) == MEGA4_ROW_COUNT, (
        "inventory row count differs from the frozen name count while the SETS are equal "
        "— a duplicate (file, derivation) row exists in MEGA4_TRACEABLE_INVENTORY"
    )


def test_mega4_row_schema_valid():
    for row in MEGA4_TRACEABLE_INVENTORY:
        _validate_row(row)


def test_mega4_chain_of_trust_closes():
    assert_mega_chain_closes(_mega_bundles())


def test_mega4_cross_mega_producer_refs_in_prior_inventories():
    prior = {(r.file, r.derivation) for r in MEGA1_TRACEABLE_INVENTORY}
    prior |= {(r.file, r.derivation) for r in MEGA2_TRACEABLE_INVENTORY}
    prior |= {(r.file, r.derivation) for r in MEGA3_TRACEABLE_INVENTORY}
    for row in MEGA4_TRACEABLE_INVENTORY:
        if row.disposition != "DERIVED":
            continue
        for ref in row.producer_refs:
            if ":" not in ref:
                continue
            file, _qual = ref.split(":", 1)
            if file in _PRIOR_MEGA_FILES:
                assert (file, _qual) in prior, f"Mega4 row missing prior-mega producer: {ref}"


def test_mega4_merged_index_has_no_duplicate_keys():
    idx = build_merged_index(_mega_bundles())
    assert len(idx) == (
        len(MEGA1_TRACEABLE_INVENTORY)
        + len(MEGA2_TRACEABLE_INVENTORY)
        + len(MEGA3_TRACEABLE_INVENTORY)
        + len(MEGA4_TRACEABLE_INVENTORY)
    )


def test_mega4_chain_rejects_missing_producer():
    idx = build_merged_index(_mega_bundles())
    with pytest.raises(AssertionError, match="missing from merged inventory"):
        resolve_producer_chain("ml_predict.py:__no_such__", idx)


def test_mega4_allowlist_entries_complete():
    mega4_ids = {e.id for e in CHAIN_OF_TRUST_ALLOWLIST if e.owner_section == "Mega4"}
    assert mega4_ids >= {"mega4_governed_stack_contract"}
    for entry in CHAIN_OF_TRUST_ALLOWLIST:
        if entry.owner_section != "Mega4":
            continue
        assert entry.justification and "TODO" not in entry.justification.upper()
        assert entry.added_in_sha
        assert entry.category in REQUIRED_CATEGORIES


def test_mega4_ml_predict_traces_to_market_state():
    idx = build_merged_index(_mega_bundles())
    row = idx[("ml_predict.py", "_predict_xgb_movement_heads")]
    assert "market_state.py:build_market_state" in row.producer_refs
    resolve_producer_chain("market_state.py:build_market_state", idx)
