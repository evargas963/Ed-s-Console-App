"""Mega 1 (§A+§B+§C) traceable inventory gate — literal AC enforcement."""

from __future__ import annotations

import ast
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
    Mega1TraceableDerivation,
)
from governance.section_inventory_gate import (  # noqa: E402
    all_functions_in_file,
    assert_inventory_covers_all_functions,
)

TRANSPORT_FILES = frozenset(
    {
        "schwab_client.py",
        "reauth_schwab.py",
        "polling_adapter.py",
        "websocket_adapter.py",
        "sse_adapter.py",
    }
)

SCHWAB_API_CALL_RE = re.compile(
    r"(?<![.\w])(safe_get_quote|safe_get_chain|safe_get_price_history|schwab_candles_to_bars)\s*\("
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


def _inventory_index() -> dict[tuple[str, str], Mega1TraceableDerivation]:
    return {(r.file, r.derivation): r for r in MEGA1_TRACEABLE_INVENTORY}


def _resolve_chain(
    ref: str,
    idx: dict[tuple[str, str], Mega1TraceableDerivation],
    *,
    stack: tuple[str, ...] = (),
) -> None:
    if ref in stack:
        raise AssertionError(f"cycle in producer_refs: {' -> '.join(stack + (ref,))}")
    if ":" not in ref:
        raise AssertionError(f"invalid producer_ref (expected file:fn): {ref!r}")
    file, qual = ref.split(":", 1)
    key = (file, qual)
    if key not in idx:
        raise AssertionError(f"producer_ref missing from inventory: {ref}")
    row = idx[key]
    if row.disposition in CLOSING_DISPOSITIONS:
        return
    if row.disposition == "NONE":
        raise AssertionError(f"NONE row cannot be producer for DERIVED chain: {ref}")
    if row.disposition != "DERIVED":
        raise AssertionError(f"unexpected disposition {row.disposition!r} at {ref}")
    if not row.producer_refs:
        raise AssertionError(f"DERIVED row has empty producer_refs: {ref}")
    for child in row.producer_refs:
        _resolve_chain(child, idx, stack=stack + (ref,))


def _validate_row(row: Mega1TraceableDerivation) -> None:
    if CATEGORICAL_JUST_RE.search(row.justification):
        raise AssertionError(
            f"{row.file}:{row.derivation} categorical justification: {row.justification!r}"
        )
    if len(row.justification.strip()) < 12:
        raise AssertionError(f"{row.file}:{row.derivation} justification too short")

    if row.disposition == "SCHWAB_LEAF":
        if row.producer_refs:
            raise AssertionError(f"{row.file}:{row.derivation} SCHWAB_LEAF must have empty producer_refs")
        if row.allowlist_id is not None:
            raise AssertionError(f"{row.file}:{row.derivation} SCHWAB_LEAF must have allowlist_id None")
        _assert_schwab_leaf(row.schwab_leaf, row)

    elif row.disposition == "REPLACED":
        if row.producer_refs:
            raise AssertionError(f"{row.file}:{row.derivation} REPLACED must have empty producer_refs")
        if row.allowlist_id is not None:
            raise AssertionError(f"{row.file}:{row.derivation} REPLACED must have allowlist_id None")
        _assert_schwab_leaf(row.schwab_leaf, row)

    elif row.disposition == "DERIVED":
        if row.schwab_leaf is not None:
            raise AssertionError(f"{row.file}:{row.derivation} DERIVED must have schwab_leaf None")
        if row.allowlist_id is not None:
            raise AssertionError(f"{row.file}:{row.derivation} DERIVED must have allowlist_id None")
        if not row.producer_refs:
            raise AssertionError(f"{row.file}:{row.derivation} DERIVED requires producer_refs")

    elif row.disposition == "ALLOWLISTED":
        if row.schwab_leaf is not None:
            raise AssertionError(f"{row.file}:{row.derivation} ALLOWLISTED must have schwab_leaf None")
        if row.producer_refs:
            raise AssertionError(f"{row.file}:{row.derivation} ALLOWLISTED must have empty producer_refs")
        if not row.allowlist_id or row.allowlist_id not in ALLOWLIST_BY_ID:
            raise AssertionError(f"{row.file}:{row.derivation} unknown allowlist_id {row.allowlist_id!r}")

    elif row.disposition == "NONE":
        if row.schwab_leaf is not None:
            raise AssertionError(f"{row.file}:{row.derivation} NONE must have schwab_leaf None")
        if row.producer_refs:
            raise AssertionError(f"{row.file}:{row.derivation} NONE must have empty producer_refs")
        if row.allowlist_id is not None:
            raise AssertionError(f"{row.file}:{row.derivation} NONE must have allowlist_id None")
        if "derivation" not in row.justification.lower() and "no market" not in row.justification.lower():
            raise AssertionError(
                f"{row.file}:{row.derivation} NONE justification must explain non-derivation"
            )
    else:
        raise AssertionError(f"unknown disposition {row.disposition!r}")


def _assert_schwab_leaf(leaf: str | None, row: Mega1TraceableDerivation) -> None:
    if not leaf:
        raise AssertionError(f"{row.file}:{row.derivation} missing schwab_leaf")
    if FORBIDDEN_AGGREGATE_LEAF_RE.match(leaf):
        raise AssertionError(f"{row.file}:{row.derivation} aggregate schwab_leaf rejected: {leaf!r}")
    if not SCHWAB_LEAF_RE.match(leaf):
        raise AssertionError(f"{row.file}:{row.derivation} invalid schwab_leaf format: {leaf!r}")


def test_mega1_inventory_covers_every_function():
    assert_inventory_covers_all_functions(ROOT, MEGA1_FILES, MEGA1_TRACEABLE_INVENTORY)
    for rel in sorted(MEGA1_FILES):
        required = len(all_functions_in_file(ROOT, rel))
        covered = sum(1 for r in MEGA1_TRACEABLE_INVENTORY if r.file == rel)
        assert covered >= required, f"{rel}: inventory {covered} < AST defs {required}"


def test_mega1_scope_complete():
    inv_files = {r.file for r in MEGA1_TRACEABLE_INVENTORY}
    assert inv_files == set(MEGA1_FILES)
    assert len(MEGA1_TRACEABLE_INVENTORY) == 421  # inventory sync @ UI_05 priority admission + VOL_OBSERVABILITY_V1: +6 server.py defs


def test_mega1_row_schema_valid():
    for row in MEGA1_TRACEABLE_INVENTORY:
        _validate_row(row)


def test_mega1_chain_of_trust_closes():
    idx = _inventory_index()
    for row in MEGA1_TRACEABLE_INVENTORY:
        if row.disposition != "DERIVED":
            continue
        for ref in row.producer_refs:
            _resolve_chain(ref, idx)


def test_mega1_allowlist_entries_complete():
    mega1 = [e for e in CHAIN_OF_TRUST_ALLOWLIST if e.owner_section == "Mega1"]
    assert len(mega1) >= 10
    for entry in mega1:
        assert entry.id
        assert entry.justification and "TODO" not in entry.justification.upper()
        assert entry.added_in_sha
        assert entry.category in REQUIRED_CATEGORIES


def _function_at_line(rel: str, lineno: int) -> str | None:
    fns = sorted(all_functions_in_file(ROOT, rel), key=lambda f: f.line)
    best: str | None = None
    best_line = -1
    for fn in fns:
        if fn.line <= lineno and fn.line >= best_line:
            best_line = fn.line
            best = fn.qualified_name
    return best


def _inventory_ref_for_call(rel: str, lineno: int, idx: dict[tuple[str, str], Mega1TraceableDerivation]) -> str:
    qual = _function_at_line(rel, lineno)
    if not qual:
        return f"{rel}:?"
    ref = f"{rel}:{qual}"
    row = idx.get((rel, qual))
    if row and row.disposition == "NONE" and row.derivation.count("."):
        parent = row.derivation.rsplit(".", 1)[0]
        if (rel, parent) in idx:
            return f"{rel}:{parent}"
    return ref


_TRANSPORT_PRODUCER_PREFIXES = (
    "schwab_client.py:safe_get_",
    "polling_adapter.py:fetch_bars",
    "market_data_adapter.py:schwab_candles_to_bars",
    "market_data_adapter.py:normalize_bar",
)


def _derives_from_schwab_transport(
    ref: str,
    idx: dict[tuple[str, str], Mega1TraceableDerivation],
    *,
    stack: tuple[str, ...] = (),
) -> bool:
    if ref in stack:
        return False
    if ":" not in ref:
        return False
    file, _qual = ref.split(":", 1)
    row = idx.get((file, _qual))
    if not row:
        return False
    if any(ref.startswith(p) for p in _TRANSPORT_PRODUCER_PREFIXES):
        return True
    if row.disposition in ("SCHWAB_LEAF", "REPLACED") and file in TRANSPORT_FILES:
        return True
    if row.disposition == "ALLOWLISTED":
        return False
    if row.disposition != "DERIVED":
        return False
    return any(
        _derives_from_schwab_transport(p, idx, stack=stack + (ref,)) for p in row.producer_refs
    )


def test_mega1_no_direct_schwab_api_outside_transport():
    """
    Non-transport Mega1 files may call safe_get_* only inside functions whose
    inventory DERIVED chain closes through schwab_client/polling_adapter producers.
    """
    idx = _inventory_index()
    violations: list[str] = []
    for rel in sorted(MEGA1_FILES):
        if rel in TRANSPORT_FILES:
            continue
        text = (ROOT / rel).read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            seg = ast.get_source_segment(text, node) or ""
            if not SCHWAB_API_CALL_RE.search(seg):
                continue
            lineno = getattr(node, "lineno", 0)
            ref = _inventory_ref_for_call(rel, lineno, idx)
            if ref.endswith(":?"):
                violations.append(f"{rel}:{lineno} call outside any inventoried function")
                continue
            if _derives_from_schwab_transport(ref, idx):
                continue
            violations.append(f"{rel}:{lineno} in {ref} — no inventory path to schwab transport")
    assert violations == [], "Schwab API calls outside transport layer:\n" + "\n".join(violations)


def test_mega1_schwab_leaf_regex_rejects_aggregate():
    row = Mega1TraceableDerivation(
        file="schwab_client.py",
        line=1,
        derivation="_probe",
        disposition="SCHWAB_LEAF",
        schwab_leaf="chains.*",
        producer_refs=(),
        allowlist_id=None,
        justification="Probe row for aggregate rejection in unit test.",
    )
    with pytest.raises(AssertionError):
        _assert_schwab_leaf(row.schwab_leaf, row)


def test_mega1_derived_ref_must_exist():
    idx = _inventory_index()
    with pytest.raises(AssertionError, match="missing from inventory"):
        _resolve_chain("server.py:__no_such_function__", idx)
