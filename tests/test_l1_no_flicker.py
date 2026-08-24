"""
Issue 25 — Tier B / L1: no flicker under mixed HTTP + SSE (dedupe + existing guards).

EXECUTES the shipped client logic (2026-08-24 audit: the previous version of this file
re-implemented the pipeline in Python and tested the copy, so drift in the real JS could
never fail it). tests/l1_tier_b_no_flicker_node.mjs extracts the REAL functions from
static/index.html (renderTierBLight, l1TierBComputeVisiblePaintInputs,
l1TierBSemanticSignatureFromPaintInputs, authority get/set) plus the real
static/js/l1_sse_guards.js monotonic guard, runs the scenarios below through the real
renderer with DOM-paint stubs only, and prints one JSON outcome map.

Outcome vocabulary unchanged: "rejected" | "deduped" | "painted".
tests/test_l1_cold_start_transition.py drives the same harness (cold_* keys), so both
files exercise the identical shipped authority + monotonic pipeline by construction.
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


# --- A. Duplicate SSE (same scope, gen, semantic) → dedupe ---------------------------------


def test_a_duplicate_sse_no_repaint():
    assert _outcomes()["a_duplicate_sse"] == ["painted", "deduped"]


# --- B. Late HTTP after SSE does not repaint ------------------------------------------------


def test_b_late_http_after_sse_no_repaint():
    o = _outcomes()
    assert o["b_late_http"] == ["painted", "painted", "rejected"]
    assert o["b_authority"] == "SSE_LIVE"


# --- C. Same gen + newer ts, identical fingerprint → dedupe --------------------------------


def test_c_same_gen_newer_ts_identical_fp_no_repaint():
    assert _outcomes()["c_same_gen_newer_ts"] == ["painted", "deduped"]


# --- D. Higher generation repaints --------------------------------------------------------


def test_d_higher_generation_repaints():
    assert _outcomes()["d_higher_gen"] == ["painted", "painted"]


# --- E. Wrong ticker (old scope) rejected ---------------------------------------------------


def test_e_wrong_ticker_payload_rejected():
    assert _outcomes()["e_wrong_ticker"] == ["rejected"]


# --- Monotonic still enforced (no stale repaint after higher gen) ---------------------------


def test_monotonic_rejects_stale_after_paint():
    assert _outcomes()["f_monotonic_stale"] == ["painted", "rejected"]
