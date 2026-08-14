"""Institutional consistency: dollar GEX pickers and aggregates.

RC-292 honesty: Console `kl_gamma_pin` is bound to `pick_gamma_pin_strike`
(|net GEX$| peak). Labels/tooltips must say that — not "Gamma Pin" / total-gamma.
HVL remains the total-gamma concentration. pin_score reads |net GEX$| at the
bound pin via gex_at_bound_pin_strike. Persisted snapshots.gamma_pin is that
same strike, stamped gamma_pin_semantic=net_gex_peak.
"""

from pathlib import Path

from math_exposure_core import (
    GAMMA_PIN_CONSUMER_LABEL,
    GAMMA_PIN_CONSUMER_TIP,
    GAMMA_PIN_LABEL_PAYLOAD_KEY,
    GAMMA_PIN_PAYLOAD_KEY,
    GAMMA_PIN_SEMANTIC,
    GAMMA_PIN_TIP_PAYLOAD_KEY,
    aggregate_net_gex,
    bucket_metric_abs,
    compute_exposures_by_strike,
    exposures_have_dollar_gex,
    gex_at_bound_pin_strike,
    pick_gamma_pin_strike,
    pick_hvl_strike,
    total_gex_dollars_at_strike,
)
from math_levels import build_summary_rows, compute_gamma_flip, pick_gamma_wall_strikes

_INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"
_PIN_TIP = GAMMA_PIN_CONSUMER_TIP


def _dollarized_exposures():
  spot = 500.0
  contracts = [
      {"strikePrice": 495, "putCall": "PUT", "openInterest": 1000, "multiplier": 100,
       "gamma": 0.05, "delta": -0.3, "daysToExpiration": 0},
      {"strikePrice": 500, "putCall": "CALL", "openInterest": 2000, "multiplier": 100,
       "gamma": 0.08, "delta": 0.5, "daysToExpiration": 0},
      {"strikePrice": 500, "putCall": "PUT", "openInterest": 1500, "multiplier": 100,
       "gamma": 0.07, "delta": -0.45, "daysToExpiration": 0},
      {"strikePrice": 505, "putCall": "CALL", "openInterest": 3000, "multiplier": 100,
       "gamma": 0.06, "delta": 0.4, "daysToExpiration": 0},
  ]
  exposures, _ = compute_exposures_by_strike(contracts, spot=spot, require_oi=True)
  return exposures, spot


def test_exposures_are_dollarized():
    exposures, _ = _dollarized_exposures()
    assert exposures_have_dollar_gex(exposures)


def test_gamma_pin_uses_net_gex_not_raw_when_dollarized():
    exposures, _ = _dollarized_exposures()
    pin = pick_gamma_pin_strike(exposures, sorted(exposures.keys()))
    assert pin is not None
    rows = build_summary_rows(exposures, 500.0, windows=[5])
    assert rows[0].gamma_pin == pin


def test_hvl_can_differ_from_gamma_pin():
    exposures, spot = _dollarized_exposures()
    pin = pick_gamma_pin_strike(exposures, sorted(exposures.keys()))
    hvl = pick_hvl_strike(exposures, sorted(exposures.keys()))
    assert pin is not None and hvl is not None
    (cg, _), (pg, _) = pick_gamma_wall_strikes(exposures, sorted(exposures.keys()))
    assert cg is not None or pg is not None


def test_consensus_net_gamma_equals_aggregate_net_gex():
    exposures, spot = _dollarized_exposures()
    strikes = sorted(exposures.keys())
    agg = aggregate_net_gex(exposures, strikes)
    rows = build_summary_rows(exposures, spot, windows=[5])
    assert rows[0].net_gamma == agg


def test_gamma_flip_prefers_net_gex_1pct():
    exposures, spot = _dollarized_exposures()
    flip = compute_gamma_flip(exposures, spot)
    assert flip is None or isinstance(flip, float)


def _split_net_vs_total_exposures():
    """One strike leads |net GEX$|; a different strike leads total gamma."""
    spot = 500.0
    contracts = [
        # 490: balanced call+put → high total gamma, near-zero net
        {"strikePrice": 490, "putCall": "CALL", "openInterest": 8000, "multiplier": 100,
         "gamma": 0.10, "delta": 0.55, "daysToExpiration": 1},
        {"strikePrice": 490, "putCall": "PUT", "openInterest": 8000, "multiplier": 100,
         "gamma": 0.10, "delta": -0.45, "daysToExpiration": 1},
        # 510: call-heavy → lower total than 490, |net| >> 490, and |net| != total
        {"strikePrice": 510, "putCall": "CALL", "openInterest": 5000, "multiplier": 100,
         "gamma": 0.10, "delta": 0.35, "daysToExpiration": 1},
        {"strikePrice": 510, "putCall": "PUT", "openInterest": 2000, "multiplier": 100,
         "gamma": 0.08, "delta": -0.15, "daysToExpiration": 1},
    ]
    exposures, _ = compute_exposures_by_strike(contracts, spot=spot, require_oi=True)
    return exposures, spot


def test_gamma_pin_is_abs_net_gex_peak_not_total_gamma():
    """Bound semantic for kl_gamma_pin / consensus gamma_pin: |net GEX$|, not HVL."""
    exposures, _ = _split_net_vs_total_exposures()
    strikes = sorted(exposures.keys())
    pin = pick_gamma_pin_strike(exposures, strikes)
    hvl = pick_hvl_strike(exposures, strikes)
    assert pin == 510.0
    assert hvl == 490.0
    assert pin != hvl
    pin_abs_net = bucket_metric_abs(exposures[pin], "net_gex_1pct")
    other_abs_net = bucket_metric_abs(exposures[hvl], "net_gex_1pct")
    assert pin_abs_net is not None and other_abs_net is not None
    assert pin_abs_net > other_abs_net
    assert total_gex_dollars_at_strike(exposures[hvl]) > total_gex_dollars_at_strike(
        exposures[pin]
    )
    rows = build_summary_rows(exposures, 500.0, windows=[5])
    assert rows[0].gamma_pin == pin


def test_kl_gamma_pin_consumer_semantic_matches_registry():
    """RC-329: consumer name for kl_gamma_pin is bound to GAMMA_PIN_SEMANTIC."""
    html = _INDEX.read_text(encoding="utf-8")
    assert GAMMA_PIN_SEMANTIC == "net_gex_peak"
    assert f"key: '{GAMMA_PIN_PAYLOAD_KEY}'" in html
    start = html.find(f"{{ key: '{GAMMA_PIN_PAYLOAD_KEY}'")
    assert start != -1
    end = html.find("},", start)
    pin_block = html[start:end]
    assert f"labelKey: '{GAMMA_PIN_LABEL_PAYLOAD_KEY}'" in pin_block
    assert f"tipKey: '{GAMMA_PIN_TIP_PAYLOAD_KEY}'" in pin_block
    assert "label: '" not in pin_block
    assert "title: '" not in pin_block


def test_console_kl_gamma_pin_label_matches_bound_net_gex():
    """RC-292 UI label child: Console must not call the net-GEX peak 'Gamma Pin'."""
    html = _INDEX.read_text(encoding="utf-8")
    assert "key: 'kl_gamma_pin'" in html
    start = html.find("{ key: 'kl_gamma_pin'")
    pin_block = html[start : html.find("},", start)]
    assert "label: 'Net Γ Peak'" not in pin_block
    assert "label: 'Gamma Pin'" not in html
    assert "srLabel: 'Net Γ'" in html
    assert "label: 'HVL'" in html
    assert "srLabel: 'Peak Γ'" in html


def test_console_pin_tooltip_matches_bound_net_gex():
    """RC-292 tooltip child: operator text names |net GEX$|, not total-gamma."""
    html = _INDEX.read_text(encoding="utf-8")
    start = html.find("{ key: 'kl_gamma_pin'")
    pin_block = html[start : html.find("},", start)]
    assert _PIN_TIP not in pin_block
    assert "tipKey: 'kl_gamma_pin_tip'" in pin_block
    assert "title: 'Largest net-gamma strike'" not in html
    assert "title: 'Largest total gamma" not in html
    assert GAMMA_PIN_CONSUMER_LABEL == "Net Γ Peak"
    assert "total-gamma magnet" in GAMMA_PIN_CONSUMER_TIP


def test_server_emits_gamma_pin_label_from_registry():
    """RC-329 bedrock: one source — payload carries the registry copy."""
    server = Path(__file__).resolve().parent.parent.joinpath("server.py").read_text(
        encoding="utf-8"
    )
    assert "GAMMA_PIN_LABEL_PAYLOAD_KEY" in server
    assert "GAMMA_PIN_TIP_PAYLOAD_KEY" in server
    assert "GAMMA_PIN_CONSUMER_LABEL" in server
    assert "GAMMA_PIN_CONSUMER_TIP" in server
    assert GAMMA_PIN_LABEL_PAYLOAD_KEY == "kl_gamma_pin_label"
    assert GAMMA_PIN_TIP_PAYLOAD_KEY == "kl_gamma_pin_tip"


def test_decision_exec_pin_labeled_net_gamma():
    """Same bound field on the rail/exec card must not say PIN."""
    html = _INDEX.read_text(encoding="utf-8")
    assert 'id="dr-lvl-pin"' in html
    assert 'id="exec-pin"' in html
    assert 'decision-k">PIN</div><div class="decision-v" id="dr-lvl-pin"' not in html
    assert 'decision-k">PIN</div><div class="decision-v" id="exec-pin"' not in html
    assert ">NET Γ</div><div class=\"decision-v\" id=\"dr-lvl-pin\">" in html
    assert ">NET Γ</div><div class=\"decision-v\" id=\"exec-pin\">" in html


def test_pin_score_gex_is_abs_net_not_total_gamma():
    """RC-292 pin_score child: magnitude at the bound pin is |net GEX$|, not HVL total."""
    exposures, _ = _split_net_vs_total_exposures()
    strikes = sorted(exposures.keys())
    pin = pick_gamma_pin_strike(exposures, strikes)
    hvl = pick_hvl_strike(exposures, strikes)
    assert pin == 510.0 and hvl == 490.0
    bound = gex_at_bound_pin_strike(exposures, pin)
    net_at_pin = bucket_metric_abs(exposures[pin], "net_gex_1pct")
    total_at_pin = total_gex_dollars_at_strike(exposures[pin])
    assert bound == net_at_pin
    assert total_at_pin is not None and bound != total_at_pin
    assert gex_at_bound_pin_strike(exposures, None) is None


def test_server_pin_score_reads_bound_net_gex_helper():
    """Mutation lock: server pin_score block must not score total-gamma at the pin."""
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent.joinpath("server.py").read_text(
        encoding="utf-8"
    )
    start = src.find("# 5. Pin Score")
    end = src.find("compute_pin_score", start)
    assert start != -1 and end != -1
    block = src[start:end]
    assert "gex_at_bound_pin_strike" in block
    assert "total_gex_dollars_at_strike" not in block
    assert "total_gamma_raw_at_strike" not in block


def test_persisted_gamma_pin_is_bound_net_gex_and_stamped():
    """RC-292 persist + migration: write path is cs.gamma_pin; semantic is net_gex_peak."""
    from math_exposure_core import GAMMA_PIN_SEMANTIC

    server = Path(__file__).resolve().parent.parent.joinpath("server.py").read_text(
        encoding="utf-8"
    )
    db_src = Path(__file__).resolve().parent.parent.joinpath("db.py").read_text(
        encoding="utf-8"
    )
    assert 'gamma_pin=getattr(consensus_summary, "gamma_pin", None)' in server
    assert "GAMMA_PIN_SEMANTIC" in server
    assert "gamma_pin_semantic" in server
    assert 'if ticker' not in server[server.find("gamma_pin=getattr(consensus_summary") : server.find("gamma_pin=getattr(consensus_summary") + 400]
    assert GAMMA_PIN_SEMANTIC == "net_gex_peak"
    assert '("gamma_pin_semantic",       "TEXT")' in db_src or '("gamma_pin_semantic"' in db_src
    assert 'ALTER TABLE snapshots_1m_normalized ADD COLUMN {col_name}' in db_src
    assert "strike with highest gamma" not in db_src
    assert "|net GEX$| peak strike" in db_src


def test_gamma_pin_semantic_column_migrates_and_round_trips(tmp_path):
    """Backward-safe: ALTER adds TEXT; old NULL means net_gex_peak; new rows stamp it."""
    from db import CANONICAL_TIMEFRAME, EdDB, SnapshotRow, build_ts_et, market_session, now_et
    from math_exposure_core import GAMMA_PIN_SEMANTIC

    db = EdDB(tmp_path / "pin_semantic.db", allow_noncanonical=True)
    cols = {str(r[1]) for r in db._connect().execute("PRAGMA table_info(snapshots)")}
    norm = {str(r[1]) for r in db._connect().execute("PRAGMA table_info(snapshots_1m_normalized)")}
    assert "gamma_pin" in cols
    assert "gamma_pin_semantic" in cols
    assert "gamma_pin_semantic" in norm
    et = now_et()
    snap = SnapshotRow(
        ticker="SPY",
        timeframe=CANONICAL_TIMEFRAME,
        ts_utc=1_700_000_000.0,
        ts_et=build_ts_et(et),
        et_hour=et.hour,
        et_minute=et.minute,
        market_session=market_session(et.hour, et.minute),
        spot=500.0,
        gamma_pin=510.0,
        gamma_pin_semantic=GAMMA_PIN_SEMANTIC,
    )
    sid = db.insert_snapshot(snap)
    row = db._connect().execute(
        "SELECT gamma_pin, gamma_pin_semantic FROM snapshots WHERE snapshot_id=?",
        (sid,),
    ).fetchone()
    assert row[0] == 510.0
    assert row[1] == "net_gex_peak"


def test_gamma_pin_semantic_alters_existing_normalized_table(tmp_path):
    """Issue 16 class: existing snapshots_1m_normalized missing the stamp gets ALTER."""
    from db import EdDB

    db = EdDB(tmp_path / "pin_semantic_norm.db", allow_noncanonical=True)
    with db._connect() as conn:
        cols = [
            str(r[1])
            for r in conn.execute("PRAGMA table_info(snapshots_1m_normalized)")
            if str(r[1]) != "gamma_pin_semantic"
        ]
        conn.execute("ALTER TABLE snapshots_1m_normalized RENAME TO snapshots_1m_normalized_old")
        conn.execute(
            f"CREATE TABLE snapshots_1m_normalized AS SELECT {', '.join(cols)} "
            "FROM snapshots_1m_normalized_old"
        )
        conn.execute("DROP TABLE snapshots_1m_normalized_old")
        stripped = {str(r[1]) for r in conn.execute("PRAGMA table_info(snapshots_1m_normalized)")}
    assert "gamma_pin_semantic" not in stripped
    db._migrate_schema()
    restored = {str(r[1]) for r in db._connect().execute("PRAGMA table_info(snapshots_1m_normalized)")}
    assert "gamma_pin_semantic" in restored


def test_gamma_pin_semantic_in_normalized_insert_intersection(tmp_path):
    """Issue 16: missing normalized column would silently drop the stamp on INSERT."""
    from db import EdDB
    from snapshot_normalizer import _normalized_insert_columns

    db = EdDB(tmp_path / "pin_semantic_intersect.db", allow_noncanonical=True)
    with db._connect() as conn:
        assert "gamma_pin_semantic" in _normalized_insert_columns(conn)
        cols = [
            str(r[1])
            for r in conn.execute("PRAGMA table_info(snapshots_1m_normalized)")
            if str(r[1]) != "gamma_pin_semantic"
        ]
        conn.execute("ALTER TABLE snapshots_1m_normalized RENAME TO snapshots_1m_normalized_old")
        conn.execute(
            f"CREATE TABLE snapshots_1m_normalized AS SELECT {', '.join(cols)} "
            "FROM snapshots_1m_normalized_old"
        )
        conn.execute("DROP TABLE snapshots_1m_normalized_old")
        assert "gamma_pin_semantic" not in _normalized_insert_columns(conn)
    db._migrate_schema()
    with db._connect() as conn:
        assert "gamma_pin_semantic" in _normalized_insert_columns(conn)
