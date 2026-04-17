"""
signal_helpers.py
Small utility functions shared across the signal pipeline.
"""

def _ordinal(n: int) -> str:
    """Return ordinal string: 1 -> '1st', 2 -> '2nd', 3 -> '3rd', 4 -> '4th', etc."""
    if not isinstance(n, int) or n < 1:
        return str(n)
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


if __name__ == "__main__":
    assert _ordinal(1) == "1st"
    assert _ordinal(2) == "2nd"
    assert _ordinal(3) == "3rd"
    assert _ordinal(4) == "4th"
    assert _ordinal(11) == "11th"
    assert _ordinal(21) == "21st"
    print("signal_helpers self-test OK")
