"""What every panel answers when the value it serves is not held: that it is not, and why."""

from __future__ import annotations

from typing import Any


def unavailable(ticker: str, reason: str, **fields: Any) -> dict[str, Any]:
    """Return a panel's answer when the value it serves is not held for `ticker`.

    It says why, with the panel's own `fields`.
    """
    return {"ticker": ticker, "available": False, **fields, "reason": reason}
