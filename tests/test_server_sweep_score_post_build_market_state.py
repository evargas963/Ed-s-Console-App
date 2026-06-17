"""FIND-SERVER-SWEEP-DEAD-FEED: sweep_score must compute AFTER build_market_state.

Prior to this refactor, server.py:_fetch_state computed sweep_score inside the Section 8 block
that ran BEFORE build_market_state was called. The block read:

    for _wname in ['nearest_above_dist', 'nearest_below_dist']:
        _wd = getattr(ms, _wname, None) if 'ms' in dir() else None

The `'ms' in dir()` defensive guard always evaluated False — `ms` was not yet assigned at that
point in execution. The loop always set _nearest_wall_dist=None and sweep_score was silently
degraded to None / empty on every tick. The feature (snapshot column sweep_score, ms_dict
sweep_score, sweep_label) was effectively dead.

Fix: move the sweep_score computation to AFTER build_market_state. By then ms.nearest_above_dist
and ms.nearest_below_dist are populated by build_market_state from walls + price_levels.

This test locks the shape so the dead-feed pattern cannot reappear.
"""

from __future__ import annotations

import inspect
from pathlib import Path


SERVER_SRC = Path(__file__).resolve().parent.parent / "server.py"


def _fetch_state_source() -> str:
    """Read _fetch_state source via inspect after importing the module."""
    import server

    return inspect.getsource(server._fetch_state)


def _strip_hash_comments(source: str) -> str:
    """Drop # comment lines and inline # tails so regression guards match executable code only."""
    out: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "#" in line:
            line = line[: line.index("#")]
        out.append(line)
    return "\n".join(out)


def test_no_dead_ms_in_dir_defensive_guard_in_fetch_state():
    """The exact dead pattern must not return to _fetch_state executable code."""
    src = _strip_hash_comments(_fetch_state_source())
    assert "'ms' in dir()" not in src, (
        "_fetch_state must not gate on `'ms' in dir()` — that always evaluates False "
        "when used before `ms = build_market_state(...)` runs"
    )
    assert '"ms" in dir()' not in src


def test_compute_sweep_score_called_after_build_market_state():
    """compute_sweep_score(... must execute strictly after the ms = build_market_state(...) line."""
    src = _fetch_state_source()
    # Single compute_sweep_score call site (the post-build one). Multiple is allowed as long as the
    # last one comes after build_market_state — but the prior dead-feed call was the only site, so
    # any single site must be post-build.
    sweep_calls = [i for i in range(len(src)) if src.startswith("compute_sweep_score(", i)]
    assert sweep_calls, "_fetch_state must call compute_sweep_score at least once"
    build_idx = src.find("build_market_state(")
    assert build_idx > 0, "_fetch_state must call build_market_state"
    # Every compute_sweep_score(...) call must appear after build_market_state(...
    for pos in sweep_calls:
        assert pos > build_idx, (
            "compute_sweep_score must be called AFTER build_market_state "
            f"(found call at offset {pos} but build_market_state at {build_idx})"
        )


def test_void_factor_default_hoisted_outside_section_8_try():
    """_void_factor must be defined before the Section 8 try block (sweep_score post-build relies on it)."""
    src = _fetch_state_source()
    # The default-init block above the Section 8 try must include _void_factor = 0.0.
    # Look for the Section 8 marker, then the init block immediately below it.
    sec8 = src.find("Section 8 — Predictive Positioning Signals")
    assert sec8 > 0, "Section 8 header marker must remain"
    init_window = src[sec8 : sec8 + 1500]
    assert "_void_factor = 0.0" in init_window, (
        "_void_factor = 0.0 must be initialized in the Section 8 default block "
        "(before the try) so the post-build sweep_score still has a value when "
        "Section 8 raises early"
    )


def test_post_build_sweep_block_reads_real_ms_attrs():
    """The new sweep block must read ms.nearest_above_dist / ms.nearest_below_dist directly."""
    src = _fetch_state_source()
    # Find the post-build sweep section by header text used in the fix.
    marker = "Section 8 (post-build) — Sweep Score"
    assert marker in src, "post-build sweep section marker must exist"
    deferred = _strip_hash_comments(src.split(marker, 1)[1][:1500])
    assert "nearest_above_dist" in deferred
    assert "nearest_below_dist" in deferred
    assert "getattr(ms," in deferred or "getattr(ms ," in deferred
    # The defensive `'ms' in dir()` pattern must NOT appear in the new block.
    assert "'ms' in dir()" not in deferred
