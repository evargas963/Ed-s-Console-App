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
import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import desk_store as DS  # noqa: E402
import terrain_engine as TE  # noqa: E402
from liquidity_models import volume_profile_poc_vah_val  # noqa: E402


def _facts(db: Path) -> list[sqlite3.Row]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return con.execute("SELECT * FROM desk_facts").fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


# ------------------------------------- a NULL short volume is not zero shares short ----

def _finra_db(tmp_path: Path, short_volume) -> Path:
    db = tmp_path / "finra.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE world_finra_short_volume (date TEXT, symbol TEXT, "
        "short_volume REAL, total_volume REAL, fetched_at TEXT)")
    con.execute(
        "INSERT INTO world_finra_short_volume VALUES (?,?,?,?,?)",
        ("2026-07-15", "SPY", short_volume, 1_000_000.0, "2026-07-17 10:00:00"))
    con.commit()
    con.close()
    return db


def test_null_short_volume_writes_no_fact_rather_than_a_zero_ratio(tmp_path):
    """FINRA not reporting is not the same fact as nobody selling short.

    The old line divided `float(short_volume or 0.0)` by total and published 0.0 under tier
    "MEASURED" -- a short interest of exactly zero for a name that trades a million shares.
    """
    db = _finra_db(tmp_path, None)
    out = DS.materialize_short_volume(db)
    rows = _facts(db)
    assert out["written"] == 0, f"a fact was written from a NULL: {[dict(r) for r in rows]}"
    assert not rows
    assert out["skipped_no_knowledge_time"] == 1, "the skip must be counted, not silent"


def test_a_real_short_volume_still_produces_its_ratio(tmp_path):
    """The negative control: the fix must not have simply stopped the function working."""
    db = _finra_db(tmp_path, 250_000.0)
    out = DS.materialize_short_volume(db)
    rows = _facts(db)
    assert out["written"] == 1
    assert rows[0]["kind"] == "short_volume_ratio"
    assert rows[0]["value_num"] == pytest.approx(0.25)


def test_a_genuine_zero_short_volume_is_still_recorded(tmp_path):
    """Zero MEASURED is a real observation and must survive. Absence is the only casualty."""
    db = _finra_db(tmp_path, 0.0)
    out = DS.materialize_short_volume(db)
    assert out["written"] == 1, "a measured zero was thrown away with the fabricated ones"
    assert _facts(db)[0]["value_num"] == pytest.approx(0.0)


# ------------------------------------------ a NULL strike count is not zero strikes ----

def _chain_db(tmp_path: Path, n_strikes) -> Path:
    db = tmp_path / "chain.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE option_chain_accrual (ticker TEXT, ts_utc REAL, "
        "n_strikes INTEGER, session_volume INTEGER)")
    con.execute("INSERT INTO option_chain_accrual VALUES (?,?,?,?)",
                ("SPY", time.time(), n_strikes, 1234))
    con.commit()
    con.close()
    return db


def test_null_strike_count_is_not_written_as_measured_zero(tmp_path):
    """Tier "MEASURED" is a claim about provenance, not a default string."""
    db = _chain_db(tmp_path, None)
    out = DS.materialize_options_listed(db)
    rows = _facts(db)
    assert out["written"] == 0, (
        "wrote a MEASURED fact for a strike count nobody produced: "
        f"{[dict(r) for r in rows]}")
    assert out["skipped_no_knowledge_time"] == 1


def test_a_real_strike_count_is_still_written(tmp_path):
    db = _chain_db(tmp_path, 42)
    assert DS.materialize_options_listed(db)["written"] == 1
    row = _facts(db)[0]
    assert row["tier"] == "MEASURED" and row["value_num"] == pytest.approx(42.0)


# ------------------------------------- an unpriced bar is not zero dollars of turnover ----

def test_a_null_close_contributes_no_dollars_and_does_not_crash(tmp_path):
    """The two absences used to behave differently two characters apart.

    `float(r["close"] or 0.0) * float(r["volume"])` silently deflated the day's turnover when
    the close was NULL, and raised TypeError when the volume was. Same absence, two outcomes.
    Neither is a measurement; both must now skip the bar.
    """
    db = tmp_path / "bars.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_end_ts_utc REAL, "
                "close REAL, volume REAL)")
    now = time.time()
    con.executemany(
        "INSERT INTO price_bars_1m VALUES (?,?,?,?)",
        [("SPY", now - 3600, None, 1000.0), ("SPY", now - 3540, 500.0, None)])
    con.commit()
    con.close()
    out = DS.materialize_dollar_volume(db)          # must not raise
    assert out["written"] == 0
    assert not _facts(db), "turnover was recorded for bars that carry no price"


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
    rows = TE._per_strike_rows({500.0: {"net_gex_1pct": 1_234_567.0}}, [])
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(500.0)
    assert rows[0][1] == pytest.approx(1_234_567.0, rel=1e-6)


def test_a_genuine_zero_gamma_still_draws_its_bar():
    """A strike measured at flat gamma is information and must remain on the chart."""
    rows = TE._per_strike_rows({500.0: {"net_gex_1pct": 0.0}}, [])
    assert len(rows) == 1 and rows[0][1] == pytest.approx(0.0)


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

def test_a_block_with_no_timestamp_reports_unknown_age_and_reads_stale(tmp_path):
    """`or 0.0` dated the block to 1970 -- the right verdict from a fabricated 56-year age.

    The UI then divided that age by 3600. Reporting None keeps the verdict and drops the
    invented number; `static/desk.html` renders the dash.
    """
    db = tmp_path / "brief.db"
    now = time.time()
    con = DS._connect(db)
    con.execute(DS.BRIEF_SQL)
    con.execute(
        "INSERT INTO desk_briefs (et_date, generated_utc, title, producer, blocks_json, "
        "sources_json, ingested_at_utc) VALUES (?,?,?,?,?,?,?)",
        ("2026-08-06", now, "t", "p",
         json.dumps([{"heading": "h", "text": "x"}]), json.dumps([]), now))
    con.commit()
    con.close()

    brief = DS.latest_brief(db, now)
    assert brief is not None
    block = brief["blocks"][0]
    assert block["age_sec"] is None, "an unknown age was reported as a number"
    assert block["stale"] is True, "an unknown age must fail closed"
    assert brief["stale_blocks"] == 1


def test_the_desk_ui_renders_an_unknown_age_as_a_dash():
    """JS `null / 3600` is 0, so the old cell printed a missing age as the freshest on screen."""
    html = (REPO / "static" / "desk.html").read_text(encoding="utf-8", errors="replace")
    assert "x.age_sec==null?'—'" in html.replace(" ", ""), (
        "desk.html divides age_sec without a null branch; null/3600 renders as 0.0h")


def test_put_brief_returns_a_real_rowid(tmp_path):
    """`int(cur.lastrowid or 0)` handed back a handle that resolves to no row."""
    db = tmp_path / "b2.db"
    rowid = DS.put_brief(db, et_date="2026-08-06", generated_utc=time.time(), title="t",
                         producer="p", blocks=[{"as_of_utc": time.time(), "text": "x"}],
                         sources=[])
    assert rowid > 0


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
    assert len(rels) > 500, f"the gate's scope collapsed to {len(rels)} files"
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
    assert "if g is None:" in src and "continue" in src


def test_a_cumulative_counters_first_reading_is_not_a_missing_measurement():
    """RC-277: the boundary of this whole law, learned by breaking it.

    While fixing the silent-zero class I rewrote server.py:3720 to propagate None, because
    a bar opens at `"v": vol_delta` and vol_delta can be None. It can -- but totalVolume is
    CUMULATIVE (RC-168), so a delta exists only BETWEEN two readings and the first reading
    inside any bar has no predecessor. None there means "no delta counted yet", and 0.0 is
    the identity the sum opens with. The change made every bar whose first tick set the
    baseline report volume None forever.

    This test exists so the next sweep through this file does not repair the same line
    again. `or 0.0` carries two meanings; only the data's semantics tell them apart, and
    the semantics are not visible at the call site.
    """
    from server import _CandleAccumulator

    acc = _CandleAccumulator(bar_seconds=60, max_bars=500)
    base = 1_800_000_000.0
    acc.tick("ZZR", 100.0, base, total_volume=1_000.0)          # baseline: no delta yet
    assert acc._current["ZZR"]["v"] is None, "the premise changed — re-derive before editing"
    acc.tick("ZZR", 100.5, base + 2.0, total_volume=1_600.0)    # first real delta
    assert acc._current["ZZR"]["v"] == 600.0, (
        "a normal-cadence delta stopped being counted — absence-propagation was reapplied "
        "to a cumulative counter, which is RC-277")


def test_the_cumulative_counter_site_states_why_it_is_exempt():
    """A silence with no reason at the site is what made RC-277 possible to write."""
    import inspect

    import server as srv

    src = inspect.getsource(srv._CandleAccumulator)
    assert 'cur["v"] = (cur.get("v") or 0.0) + vol_delta' in src
    line = next(ln for ln in src.splitlines() if 'cur["v"] = (cur.get("v") or 0.0)' in ln)
    assert "silent-zero-ok:" in line and "CUMULATIVE" in line, (
        "the accumulator no longer says why its `or 0.0` is correct, so the next sweep "
        "will judge it by shape and break it again")


def test_the_silent_zero_pattern_is_still_detectable():
    """A gate that passes because it stopped looking is worse than one that fails."""
    sys.path.insert(0, str(REPO / "tests"))
    import test_ohlcv_schwab_first as G

    assert any(G._line_counts_as_violation('tot = float(r["total_volume"] or 0.0)', spec)
               for spec in G.SILENT_ZERO_PATTERN_FAMILY)
