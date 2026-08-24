"""
Issue 27 — cold start → live: authority state machine + generation acceptance.

EXECUTES the shipped client logic (2026-08-24 audit: the previous version of this file
re-implemented renderTierBLight + l1ApplyTierBLightMonotonic in Python and tested the
COPY, so drift in the real JS could never fail it — same defect class fixed in
tests/test_l1_no_flicker.py). tests/l1_tier_b_no_flicker_node.mjs extracts the REAL
functions from static/index.html (renderTierBLight, l1GetAuthority/l1SetAuthority,
paint-input + semantic-signature helpers) plus the real static/js/l1_sse_guards.js
monotonic guard, drives the cold-start scenarios below through the real renderer with
DOM-paint stubs only, and prints one JSON map; this file asserts on the cold_* traces.

Each trace records per step: real renderer outcome ("painted" | "deduped" | "rejected"),
the l1_generation sent, and the post-step authority string + accepted-generation store
for scope 'SPY|'. Proves, on the shipped code:

- No HTTP overwrite after SSE_LIVE (HTTP fully ignored).
- No generation regression vs lastAcceptedGeneration (monotonic store).
- No authority oscillation (SSE_LIVE never reverts; HTTP blocked after SSE).
"""
from __future__ import annotations

import functools
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / "tests" / "l1_tier_b_no_flicker_node.mjs"

ACCEPTED = ("painted", "deduped")


@functools.lru_cache(maxsize=1)
def _outcomes() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.fail("Node.js is required on PATH (runs tests/l1_tier_b_no_flicker_node.mjs)")
    r = subprocess.run(
        [node, str(HARNESS)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr
    return json.loads(r.stdout)


def test_a_http_to_sse_transition_then_http_blocked():
    """HTTP loads (gen=1), SSE (gen=2) becomes authority; later HTTP ignored."""
    t = _outcomes()["cold_a"]
    assert t["outcomes"] == ["painted", "painted", "rejected"]
    assert t["auth"] == ["HTTP_INIT", "SSE_LIVE", "SSE_LIVE"]
    assert t["gen"] == [1, 2, 2]


def test_b_late_stale_http_rejected_after_sse():
    """SSE gen=10 accepted; late HTTP gen=9 rejected; accepted store stays 10."""
    t = _outcomes()["cold_b"]
    assert t["outcomes"] == ["painted", "painted", "rejected"]
    assert t["auth"][1:] == ["SSE_LIVE", "SSE_LIVE"]
    assert t["gen"][1:] == [10, 10]


def test_c_no_oscillation_http_higher_gen_still_ignored():
    """After SSE_LIVE, HTTP with higher gen=3 must still be ignored (hard HTTP block)."""
    t = _outcomes()["cold_c"]
    assert t["outcomes"] == ["painted", "painted", "rejected"]
    assert t["auth"] == ["HTTP_INIT", "SSE_LIVE", "SSE_LIVE"]
    assert t["gen"][-1] == 2


def test_d_strict_monotonic_rendered_generations():
    """Accepted sequence must never decrease l1_generation."""
    t = _outcomes()["cold_d"]
    rendered = [g for g, o in zip(t["sent"], t["outcomes"]) if o in ACCEPTED]
    assert rendered == [1, 2, 3]
    for i in range(1, len(rendered)):
        assert rendered[i] >= rendered[i - 1]
    assert t["gen"] == sorted(t["gen"])  # accepted-generation store is monotonic too


def test_sse_never_reverts_authority():
    """Once SSE_LIVE, authority string never goes back to HTTP_INIT."""
    t = _outcomes()["cold_e"]
    assert t["auth"][1] == "SSE_LIVE"
    assert t["auth"][2] == "SSE_LIVE"
    assert t["outcomes"][2] == "rejected"


def test_init_to_http_init_without_generation():
    """HTTP payload with no l1_generation still promotes INIT → HTTP_INIT (real client)."""
    t = _outcomes()["cold_f"]
    assert t["outcomes"] == ["painted"]
    assert t["auth"] == ["HTTP_INIT"]
    assert t["gen"] == [None]  # nothing entered the accepted-generation store
