"""RC-274 — a missing measurement must not be stored, summed, or drawn as the number zero.

WHAT WAS MEASURED (2026-08-06). `test_no_schwab_leaf_zero_injection_repo_wide` had been
failing with 13 production hits of the `float(x or 0.0)` family. Nine were harmless: a
`<= 0` or RTH guard rejected the fabricated zero on the very next line. Four were not, and
those four are what this file drives:

    desk_store.materialize_short_volume    NULL short_volume / total -> ratio 0.0 stored
                                           under tier "MEASURED"
    desk_store.materialize_dollar_volume   NULL close * volume -> 0 dollars added to the
                                           turnover that ADV ranks names on
    desk_store.materialize_options_listed  NULL n_strikes -> written as 0, tier "MEASURED"
    terrain_engine._per_strike_rows        gamma unresolvable -> a 0.0 bar on the chart

WHY THE PATTERN SURVIVED SO LONG. `or 0.0` is a real type-narrowing idiom for Optional, and
at nine of the thirteen sites that is exactly what it was. One shape carried two meanings and
the reader had to hold both at once. These tests do not assert the shape is absent -- the
repo-wide gate does that. They assert the BEHAVIOUR: feed each function a NULL and prove the
zero never reaches the fact table, the sum, or the frame.

THE TEST THAT WOULD HAVE CAUGHT IT is not a stricter regex. It is this: write a NULL into the
source table and read what comes out the other end.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import terrain_engine as TE  # noqa: E402
from liquidity_models import volume_profile_poc_vah_val  # noqa: E402




# ------------------------------------- a NULL short volume is not zero shares short ----









# ------------------------------------------ a NULL strike count is not zero strikes ----







# ------------------------------------- an unpriced bar is not zero dollars of turnover ----



# ---------------------------------------- an unknown gamma is not a flat gamma bar ----

def test_a_strike_with_no_resolvable_gamma_draws_no_bar():
    """The exact law stated four lines above the defect, applied to the value as well.

    `terrain_engine` already refuses to draw a NaN STRIKE ("a NaN strike must never become a
    rendered bar"). An unknown GAMMA was drawn at 0.0 anyway -- visually identical to a strike
    measured at flat gamma, on the surface used to read where dealers are short.
    """
    rows = TE._per_strike_rows({500.0: {}}, [])
    assert rows == [], f"drew a bar for a strike with no gamma: {rows}"


def test_a_measured_gamma_still_draws_its_bar():
    """Negative control: absence is refused, presence is not."""
    rows = TE._per_strike_rows({500.0: {"has_oi": True, "has_valid_gamma": True, "dollarized": True,
                                        "net_gex_1pct": 1_234_567.0}}, [])
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(500.0)
    assert rows[0][1] == pytest.approx(1_234_567.0, rel=1e-6)


def test_a_genuine_zero_gamma_still_draws_its_bar():
    """A strike measured at flat gamma is information and must remain on the chart."""
    rows = TE._per_strike_rows({500.0: {"has_oi": True, "has_valid_gamma": True, "dollarized": True,
                                        "net_gex_1pct": 0.0}}, [])
    assert len(rows) == 1 and rows[0][1] == pytest.approx(0.0)


def test_a_strike_with_no_oi_at_all_draws_no_bar_even_with_a_nonzero_accumulator():
    """RC-SPX (2026-09-14, live reproduction): has_oi=False must win even when the
    pre-initialized accumulator field somehow carries a nonzero value -- has_oi is the ONE
    signal every consumer checks, not a redundant belt-and-suspenders re-derivation from the
    metric itself. This is the exact live SPX defect: a bucket that never cleared the OI gate
    must never present its accumulator as a computed value, regardless of what that
    accumulator happens to hold."""
    rows = TE._per_strike_rows({500.0: {"has_oi": False, "net_gex_1pct": 1_234_567.0}}, [])
    assert rows == [], f"drew a bar for a strike that never cleared the OI gate: {rows}"


# ------------------------------------- a NULL bar volume is not zero traded volume ----

def test_a_null_volume_bar_does_not_enter_the_volume_profile():
    """One bar priced and one bar absent must give the priced bar's POC, not a blend."""
    bars = [
        {"high": 100.0, "low": 100.0, "volume": None},
        {"high": 200.0, "low": 200.0, "volume": 5_000.0},
    ]
    poc, _vah, _val = volume_profile_poc_vah_val(bars)
    assert poc == pytest.approx(200.0), "an unmeasured bar moved the point of control"


def test_no_usable_volume_still_reads_as_absence():
    """The docstring's own promise: absence reads as absence, never a fabricated level."""
    assert volume_profile_poc_vah_val(
        [{"high": 100.0, "low": 99.0, "volume": None}]) == (None, None, None)


# ------------------------------------------- an unknown age is not a fresh block ----



def test_the_desk_ui_renders_an_unknown_age_as_a_dash():
    """JS `null / 3600` is 0, so the old cell printed a missing age as the freshest on screen."""
    html = (REPO / "static" / "desk.html").read_text(encoding="utf-8", errors="replace")
    assert "x.age_sec==null?'—'" in html.replace(" ", ""), (
        "desk.html divides age_sec without a null branch; null/3600 renders as 0.0h")




# ------------------------------------------------- the gate's own scope is measured ----

def test_the_repo_wide_gate_scopes_itself_to_what_git_tracks():
    """~25 of the gate's 38 hits were untracked scratch, which is not repository code.

    The fix must not be an allowlist entry -- that is a list somebody has to keep true. The
    git index already answers the question, and answers it for directories nobody has
    invented yet.
    """
    sys.path.insert(0, str(REPO / "tests"))
    import test_ohlcv_schwab_first as G

    rels = {p.relative_to(G.ROOT).as_posix() for p in G._iter_repo_py_files()}
    import subprocess
    top = {f for f in subprocess.run(["git", "ls-files", "*.py"], cwd=G.ROOT, capture_output=True,
                                     text=True).stdout.split() if "/" not in f}
    assert top <= rels, f"tracked top-level modules fell out of the scan: {sorted(top - rels)}"
    for must in ("desk_store.py", "terrain_engine.py", "liquidity_models.py", "server.py"):
        assert must in rels, f"{must} fell out of the scan"
    assert not [r for r in rels if r.startswith("scratchpad/")], (
        "untracked scratch is back in a repo-wide product gate")
    assert not G._repo_wide_silent_zero_hits()


def test_server_py_is_judged_like_every_other_file():
    """RC-276: the product's main file was exempt from the gate that guards this defect.

    A one-line reason -- "L1/SSE instrumentation timestamps, generations, volume deltas" --
    honestly described 16 sites and silently covered 7 more, two of which were the SAME
    per-strike gamma builder RC-274 had just removed from terrain_engine. An exemption's
    scope must match the scope of its justification, and a file entry cannot do that.
    """
    sys.path.insert(0, str(REPO / "tests"))
    import test_ohlcv_schwab_first as G

    assert not G._file_allowlisted("server.py"), (
        "server.py is exempt from the silent-zero gate again — 15,092 lines including the "
        "money path, silenced by one line of prose about instrumentation")


def test_the_per_line_escape_demands_an_actual_reason():
    """A marker that can be typed without saying anything is the file allowlist, per line."""
    sys.path.insert(0, str(REPO / "tests"))
    import test_ohlcv_schwab_first as G

    bare = 'x = float(a.get("b") or 0.0)  # silent-zero-ok:'
    with_reason = 'x = float(a.get("b") or 0.0)  # silent-zero-ok: absent means no rows counted'
    assert any(G._line_counts_as_violation(bare, s) for s in G.SILENT_ZERO_PATTERN_FAMILY), (
        "a reasonless escape suppressed the finding")
    assert not any(G._line_counts_as_violation(with_reason, s)
                   for s in G.SILENT_ZERO_PATTERN_FAMILY)


def test_the_server_strike_row_builder_draws_no_bar_for_unknown_gamma():
    """RC-276: server.py's own copy of the terrain_engine:202 defect, behind the allowlist.

    Driven through the real endpoint helper rather than asserted about the source text,
    because the source text was what the allowlist was hiding.
    """
    import server as srv

    src = inspect.getsource(srv.get_terrain_strikes)
    assert "round(float(g or 0.0), 1)" not in src, (
        "the per-strike row builder fabricates a 0.0 gamma bar again")
    # 2026-09-24: the server copy is gone -- it delegates to the ONE producer, which refuses
    # a bar for unknown / invalid gamma (tested above) and has no raw-gamma fallback (T-01).
    assert "_per_strike_rows(exposures, cts)" in src
    assert "total_gamma_raw_at_strike" not in src


def test_the_silent_zero_pattern_is_still_detectable():
    """A gate that passes because it stopped looking is worse than one that fails."""
    sys.path.insert(0, str(REPO / "tests"))
    import test_ohlcv_schwab_first as G

    assert any(G._line_counts_as_violation('tot = float(r["total_volume"] or 0.0)', spec)
               for spec in G.SILENT_ZERO_PATTERN_FAMILY)
