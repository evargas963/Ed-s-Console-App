"""Mega 2 (§D+§E) traceable inventory gate — cross-mega chain-of-trust with Mega 1."""

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
    Mega2TraceableDerivation,
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
CLOSING_DISPOSITIONS = frozenset({"SCHWAB_LEAF", "REPLACED", "ALLOWLISTED"})
# Strict row count for test_mega2_scope_complete — bump when adding Mega2TraceableDerivation rows.
#   201 — baseline (1ece9b3)
#   205 — +3 (1fc5ce7): _strike_total_oi, _verdict_unavailable, _iwm_confluence_unavailable
#         +1 (a00e78e): _sector_strength_unavailable
#   206 — +1 big-audit inventory sync: _weighted_mean_present (order_flow_engine.py)
#   208 — +2 streaming disconnect/cache gate: streaming_l1_cache_usable, _is_stream_disconnect_error
MEGA2_ROW_COUNT = 211  # + classify_direction_pts (math_probabilities.py)


def _mega_bundles() -> tuple[MegaInventoryBundle, ...]:
    return (
        MegaInventoryBundle("Mega1", MEGA1_FILES, MEGA1_TRACEABLE_INVENTORY),
        MegaInventoryBundle("Mega2", MEGA2_FILES, MEGA2_TRACEABLE_INVENTORY),
    )


def _validate_row(row: Mega2TraceableDerivation) -> None:
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


def test_mega2_inventory_covers_every_function():
    assert_inventory_covers_all_functions(ROOT, MEGA2_FILES, MEGA2_TRACEABLE_INVENTORY)
    for rel in sorted(MEGA2_FILES):
        required = len(all_functions_in_file(ROOT, rel))
        covered = sum(1 for r in MEGA2_TRACEABLE_INVENTORY if r.file == rel)
        assert covered >= required, f"{rel}: inventory {covered} < AST defs {required}"


def test_mega2_scope_complete():
    inv_files = {r.file for r in MEGA2_TRACEABLE_INVENTORY}
    assert inv_files == set(MEGA2_FILES)
    assert len(MEGA2_TRACEABLE_INVENTORY) == MEGA2_ROW_COUNT


def test_mega2_row_schema_valid():
    for row in MEGA2_TRACEABLE_INVENTORY:
        _validate_row(row)


def test_mega2_chain_of_trust_closes():
    assert_mega_chain_closes(_mega_bundles())


def test_mega2_cross_mega_producer_refs_in_mega1_inventory():
    m1 = {(r.file, r.derivation) for r in MEGA1_TRACEABLE_INVENTORY}
    for row in MEGA2_TRACEABLE_INVENTORY:
        if row.disposition != "DERIVED":
            continue
        for ref in row.producer_refs:
            if ":" not in ref:
                continue
            file, _qual = ref.split(":", 1)
            if file in MEGA1_FILES:
                assert (file, _qual) in m1, f"Mega2 row missing Mega1 producer: {ref}"


def test_mega2_merged_index_has_no_duplicate_keys():
    idx = build_merged_index(_mega_bundles())
    assert len(idx) == len(MEGA1_TRACEABLE_INVENTORY) + len(MEGA2_TRACEABLE_INVENTORY)


def test_mega2_chain_rejects_missing_mega1_producer():
    idx = build_merged_index(_mega_bundles())
    with pytest.raises(AssertionError, match="missing from merged inventory"):
        resolve_producer_chain("math_levels.py:compute_max_pain", idx)
        resolve_producer_chain("server.py:__no_such__", idx)


def test_mega2_allowlist_entries_complete():
    mega2_ids = {e.id for e in CHAIN_OF_TRUST_ALLOWLIST if e.owner_section == "Mega2"}
    assert mega2_ids >= {
        "mega2_schwab_stream_l1",
        "mega2_display_formatter",
        "mega2_mc_simulation",
        "mega2_test_fixture",
        "mega2_internal_helper",
    }
    for entry in CHAIN_OF_TRUST_ALLOWLIST:
        if entry.owner_section != "Mega2":
            continue
        assert entry.justification and "TODO" not in entry.justification.upper()
        assert entry.added_in_sha
        assert entry.category in REQUIRED_CATEGORIES


def test_mega2_schwab_leaf_regex_rejects_aggregate():
    row = Mega2TraceableDerivation(
        file="math_levels.py",
        line=1,
        derivation="_probe",
        disposition="SCHWAB_LEAF",
        schwab_leaf="chains.*",
        producer_refs=(),
        allowlist_id=None,
        justification="Probe aggregate rejection for schema gate.",
    )
    with pytest.raises(AssertionError):
        _validate_row(row)
