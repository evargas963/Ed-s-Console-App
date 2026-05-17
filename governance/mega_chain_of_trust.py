"""
Cross-mega chain-of-trust resolver.

Merges Mega 1 + Mega 2 (and future megas) so DERIVED producer_refs may point
across inventory modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, Sequence

MegaDisposition = Literal["SCHWAB_LEAF", "REPLACED", "DERIVED", "ALLOWLISTED", "NONE"]

CLOSING_DISPOSITIONS = frozenset({"SCHWAB_LEAF", "REPLACED", "ALLOWLISTED"})


class TraceableRow(Protocol):
    file: str
    derivation: str
    disposition: MegaDisposition
    producer_refs: tuple[str, ...]


@dataclass(frozen=True)
class MegaInventoryBundle:
    name: str
    files: frozenset[str]
    inventory: tuple[TraceableRow, ...]


def build_merged_index(
    bundles: Sequence[MegaInventoryBundle],
) -> dict[tuple[str, str], TraceableRow]:
    idx: dict[tuple[str, str], TraceableRow] = {}
    for bundle in bundles:
        for row in bundle.inventory:
            key = (row.file, row.derivation)
            if key in idx:
                raise ValueError(
                    f"duplicate inventory row {key[0]}:{key[1]} in bundles"
                )
            idx[key] = row
    return idx


def resolve_producer_chain(
    ref: str,
    idx: dict[tuple[str, str], TraceableRow],
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
        raise AssertionError(f"producer_ref missing from merged inventory: {ref}")
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
        resolve_producer_chain(child, idx, stack=stack + (ref,))


def assert_mega_chain_closes(bundles: Sequence[MegaInventoryBundle]) -> None:
    idx = build_merged_index(bundles)
    for bundle in bundles:
        for row in bundle.inventory:
            if row.disposition != "DERIVED":
                continue
            for ref in row.producer_refs:
                resolve_producer_chain(ref, idx)
