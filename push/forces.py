"""The `forces` panel: a ticker's forces, as the levels producer computed them."""

from __future__ import annotations

from math_forces import Forces, forces_absent
from state.level_store import published_levels


def forces(ticker: str) -> Forces:
    """Return the `forces` panel: the ticker's held forces, each number None before the first."""
    held = published_levels(ticker)
    return forces_absent(ticker) if held is None else held.forces
