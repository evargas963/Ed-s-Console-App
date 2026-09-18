#!/usr/bin/env python3
"""Discovery-completeness gate for fallback_discovery.

Arithmetic on inventory counts is not completeness. This gate requires that every
declared (file, pattern) hit is present in the discovery output. An omitted
executable fallback fails the gate. Planted fixture source lives in the test
module so this tool does not itself contain a fallback-shaped default.
"""
from __future__ import annotations

from tools.fallback_discovery import _finalize_ids, scan_python

PLANTED_REL = "planted_executable_fallback.py"
PLANTED_PATTERN = "OR_LADDER"
PLANTED_FALLBACK_SRC = (
    "def read(vendor_ctx):\n"
    "    spot = vendor_ctx.spot or vendor_ctx.last\n"
    "    return spot\n"
)


def discover(rel: str, src: str) -> list[dict]:
    hits = scan_python(rel, src)
    _finalize_ids(hits)
    return hits


def completeness_ok(discovered: list[dict], required: list[tuple[str, str]]) -> list[str]:
    """Return missing (file, pattern) requirements. Empty list means complete."""
    seen = {(c.get("file"), c.get("pattern")) for c in discovered}
    return [f"{rel}:{pattern}" for rel, pattern in required if (rel, pattern) not in seen]


def prove_planted_fallback_is_discovered(src: str) -> list[dict]:
    hits = discover(PLANTED_REL, src)
    missing = completeness_ok(hits, [(PLANTED_REL, PLANTED_PATTERN)])
    if missing:
        raise SystemExit(f"discovery completeness failed: {missing}")
    return hits


def prove_omitted_executable_fallback_fails(src: str) -> None:
    """Negative control: scanning a file that is not the planted one must fail
    the completeness requirement for the planted executable fallback."""
    decoy = discover(
        "unrelated.py",
        "def ok(x):\n    return x\n",
    )
    missing = completeness_ok(decoy, [(PLANTED_REL, PLANTED_PATTERN)])
    if not missing:
        raise SystemExit(
            "discovery completeness gate is defective: an omitted executable "
            "fallback was not reported as missing"
        )


def main() -> int:
    prove_planted_fallback_is_discovered(PLANTED_FALLBACK_SRC)
    prove_omitted_executable_fallback_fails(PLANTED_FALLBACK_SRC)
    print("discovery_completeness: planted hit found; omitted planted hit fails")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
