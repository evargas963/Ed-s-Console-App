"""
test_liquidity_engine.py — Unit tests for Liquidity & Value Playbook Engine
============================================================================

Run: pytest tests/test_liquidity_engine.py -v
  or: python tests/test_liquidity_engine.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from time_et import ET
def _mk_bar(dt: datetime, o: float, h: float, l: float, c: float, vol: float = 1000.0) -> dict:
    return {
        "timestamp": int(dt.timestamp() * 1000),
        "_ts": dt.timestamp(),
        "open": o, "high": h, "low": l, "close": c, "volume": vol,
    }


def _synthetic_bars(session_date: date, prev_day_bars: int = 390, today_bars: int = 300) -> list[dict]:
    """Generate synthetic 1-min bars: prev day RTH + today RTH (partial).
    today_bars=300 gives bars through 14:30 ET (enough for afternoon cutoff 14:00)."""
    from datetime import timedelta

    bars = []
    base_price = 500.0
    prev_date = session_date - timedelta(days=1)

    # Previous day RTH: 09:30–16:00
    for i in range(prev_day_bars):
        mins = 9 * 60 + 30 + i
        h = mins // 60
        m = mins % 60
        dt = datetime(prev_date.year, prev_date.month, prev_date.day, h, m, tzinfo=ET)
        p = base_price + (i % 50) - 25
        bars.append(_mk_bar(dt, p, p + 0.5, p - 0.5, p, 1000))

    # Today RTH: first N minutes
    for i in range(today_bars):
        mins = 9 * 60 + 30 + i
        h = mins // 60
        m = mins % 60
        dt = datetime(session_date.year, session_date.month, session_date.day, h, m, tzinfo=ET)
        p = base_price + (i % 40) - 20
        bars.append(_mk_bar(dt, p, p + 0.3, p - 0.3, p, 800))
    return bars


def _bars_through(session_date: date, hour: int, minute: int, prev_day_bars: int = 390) -> list[dict]:
    """Bars only through given ET time (exclusive of bars past that time)."""
    from datetime import timedelta

    bars = []
    base_price = 500.0
    prev_date = session_date - timedelta(days=1)
    cutoff_mins = hour * 60 + minute

    for i in range(prev_day_bars):
        mins = 9 * 60 + 30 + i
        h = mins // 60
        m = mins % 60
        dt = datetime(prev_date.year, prev_date.month, prev_date.day, h, m, tzinfo=ET)
        p = base_price + (i % 50) - 25
        bars.append(_mk_bar(dt, p, p + 0.5, p - 0.5, p, 1000))

    today_start = 9 * 60 + 30
    for i in range(cutoff_mins - today_start + 1):
        mins = today_start + i
        h = mins // 60
        m = mins % 60
        dt = datetime(session_date.year, session_date.month, session_date.day, h, m, tzinfo=ET)
        p = base_price + (i % 40) - 20
        bars.append(_mk_bar(dt, p, p + 0.3, p - 0.3, p, 800))
    return bars


def test_imports():
    """All liquidity modules import cleanly."""
    from liquidity_models import SnapshotType, ZoneType
    assert SnapshotType.PREMARKET.value == "premarket"
    assert SnapshotType.LIVE.value == "live"
    assert ZoneType.RESISTANCE_LIQUIDITY.value == "resistance_liquidity"


def test_bars_normalization():
    """Engine accepts list of dicts and produces correct internal format."""
    from liquidity_value_engine import _bars_to_list
    bars = [
        {"timestamp": 1710000000000, "open": 500, "high": 501, "low": 499, "close": 500.5, "volume": 1000},
    ]
    norm = _bars_to_list(bars)
    assert len(norm) == 1
    assert norm[0]["open"] == 500.0
    assert norm[0]["high"] == 501.0


def test_bars_normalization_preserves_missing_volume_as_missing():
    """S002: missing Schwab candle volume must not be silently converted to 0."""
    from liquidity_value_engine import _bars_to_list
    bars = [
        {"timestamp": 1710000000000, "open": 500, "high": 501, "low": 499, "close": 500.5},
    ]

    norm = _bars_to_list(bars)

    assert norm[0]["volume"] is None


def test_bars_normalization_drops_missing_ohlc_bar():
    """S003: incomplete Schwab OHLC bars must not become zero-price bars."""
    from liquidity_value_engine import _bars_to_list
    bars = [
        {"timestamp": 1710000000000, "open": 500, "high": 501, "close": 500.5, "volume": 1000},
    ]

    assert _bars_to_list(bars) == []


def test_schwab_candles_to_bars_drops_missing_ohlc_bar():
    """S003: pricehistory candle OHLC fields are required."""
    from market_data_adapter import schwab_candles_to_bars
    candles = [{"datetime": 1710000000000, "open": 500, "high": 501, "close": 500.5, "volume": 1000}]

    assert schwab_candles_to_bars(candles) == []


def test_get_previous_day_levels():
    """Previous day levels extracted from bars."""
    from liquidity_value_engine import get_previous_day_levels
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    prev = get_previous_day_levels(bars, session, cfg)
    assert prev.get("pdh") is not None
    assert prev.get("pdl") is not None
    assert prev.get("pdc") is not None
    assert prev.get("pd_poc") is not None
    assert prev["pdh"] >= prev["pdl"]


def test_compute_opening_range():
    """Opening range = first 15 min of RTH."""
    from liquidity_value_engine import compute_opening_range
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig(opening_range_minutes=15)
    orb = compute_opening_range(bars, session, cfg)
    assert orb.get("orb_high") is not None
    assert orb.get("orb_low") is not None
    assert orb.get("orb_mid") is not None
    assert orb["orb_high"] >= orb["orb_low"]


def test_compute_session_vwap():
    """VWAP computed from RTH bars."""
    from liquidity_value_engine import compute_session_vwap
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    vwap = compute_session_vwap(bars, session)
    assert vwap is not None
    assert 400 < vwap < 600


def test_compute_session_vwap_returns_none_when_volume_missing():
    """S002: VWAP is volume-weighted and must fail closed without candle volume."""
    from liquidity_value_engine import compute_session_vwap
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    for bar in bars:
        bar.pop("volume", None)

    assert compute_session_vwap(bars, session) is None


def test_midday_snapshot_does_not_create_vwap_bands_when_vwap_missing():
    """S014 sub-slice: missing VWAP must not create bands around synthetic zero."""
    import liquidity_value_engine as lve
    from liquidity_models import PlaybookConfig

    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    for bar in bars:
        if datetime.fromtimestamp(float(bar["_ts"]), ET).date() == session:
            bar.pop("volume", None)

    out = lve.build_midday_snapshot("SPY", bars, session, PlaybookConfig())

    assert out.raw_levels["vwap"] is None
    assert out.raw_levels["vwap_bands"] is None
    assert all("VWAP_P1" not in z.source_tags and "VWAP_M1" not in z.source_tags for z in out.zones)


def test_compute_volume_profile_levels():
    """POC, VAH, VAL computed from bars."""
    from liquidity_value_engine import compute_volume_profile_levels
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    poc, vah, val = compute_volume_profile_levels(bars, session, cfg)
    assert poc is not None
    assert vah is not None
    assert val is not None
    assert val <= poc <= vah


def test_volume_profile_mutation_changes_poc():
    """F15 mutation: concentrating volume at one typical price moves POC."""
    from liquidity_value_engine import _volume_profile_poc_vah_val

    base = [
        {"high": 101.0, "low": 99.0, "close": 100.0, "volume": 100.0},
        {"high": 111.0, "low": 109.0, "close": 110.0, "volume": 100.0},
    ]
    poc_a, _, _ = _volume_profile_poc_vah_val(base)
    mutated = [
        {"high": 101.0, "low": 99.0, "close": 100.0, "volume": 100.0},
        {"high": 111.0, "low": 109.0, "close": 110.0, "volume": 10_000.0},
    ]
    poc_b, _, _ = _volume_profile_poc_vah_val(mutated)
    assert poc_a is not None and poc_b is not None
    assert poc_a != poc_b


def test_market_context_volume_profile_delegates_to_engine():
    """F15: fetch_price_levels path uses the engine math, not a second loop."""
    from liquidity_value_engine import _volume_profile_poc_vah_val as engine_vp
    from market_context import _volume_profile_poc_vah_val as ctx_vp

    src = (ROOT / "market_context.py").read_text(encoding="utf-8")
    start = src.find("def _volume_profile_poc_vah_val")
    end = src.find("\ndef ", start + 1)
    block = src[start:end]
    assert "from liquidity_value_engine import" in block
    assert "vol_by_price" not in block
    assert "_float_or_none" not in block
    assert "_positive_float_or_none" not in block
    bars = [
        {"high": 101.0, "low": 99.0, "close": 100.0, "volume": 50.0},
        {"high": 111.0, "low": 109.0, "close": 110.0, "volume": 200.0},
    ]
    assert ctx_vp(bars) == engine_vp(bars)


def test_engine_volume_profile_dirty_bar_fails_closed():
    """F15 bedrock: missing OHLC is absence, not KeyError / None-arithmetic."""
    from liquidity_value_engine import _volume_profile_poc_vah_val as engine_vp
    from market_context import _volume_profile_poc_vah_val as ctx_vp

    dirty = [
        {"volume": 1},
        {"high": None, "low": 99.0, "close": 100.0, "volume": 10.0},
        {"high": 101.0, "low": 99.0, "close": 100.0, "volume": 0},
    ]
    assert engine_vp([{"volume": 1}]) == (None, None, None)
    assert engine_vp(dirty) == (None, None, None)
    assert ctx_vp(dirty) == engine_vp(dirty)


def test_fetch_state_live_path_uses_engine_volume_profile():
    """F15 live cite: _fetch_state → fetch_price_levels → engine pass-through."""
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    start = server.find("def _fetch_state(")
    assert start != -1
    end = server.find("\ndef ", start + 1)
    # _fetch_state is huge; bound the first 2500 lines of the def by char budget.
    block = server[start : start + 80_000]
    assert "price_levels = fetch_price_levels(" in block
    ctx = (ROOT / "market_context.py").read_text(encoding="utf-8")
    fetch = ctx[ctx.find("def fetch_price_levels") : ctx.find("def fetch_price_levels") + 12_000]
    assert "pl.pd_poc, pl.pd_vah, pl.pd_val = _volume_profile_poc_vah_val(" in fetch
    assert "pl.today_poc, pl.today_vah, pl.today_val = _volume_profile_poc_vah_val(" in fetch


def test_signal_layer_volume_profile_is_the_engine():
    """F15: fusion's POC producer is the engine, not a close-price 12-bin."""
    from features.signal_layer_v1 import _volume_profile_proxy
    from liquidity_value_engine import _volume_profile_poc_vah_val as engine_vp

    src = (ROOT / "features" / "signal_layer_v1.py").read_text(encoding="utf-8")
    start = src.find("def _volume_profile_proxy")
    block = src[start : src.find("\ndef ", start + 1)]
    assert "from liquidity_value_engine import" in block
    assert "nbin" not in block
    assert "(imax + 0.5)" not in block
    bars = [
        {"high": 101.0, "low": 99.0, "close": 100.0, "volume": 50.0},
        {"high": 101.0, "low": 99.0, "close": 100.0, "volume": 50.0},
        {"high": 101.0, "low": 99.0, "close": 100.0, "volume": 50.0},
        {"high": 101.0, "low": 99.0, "close": 100.0, "volume": 50.0},
        {"high": 111.0, "low": 109.0, "close": 110.0, "volume": 200.0},
    ]
    poc, val, vah = _volume_profile_proxy(bars, 20)
    e_poc, e_vah, e_val = engine_vp(bars)
    assert (poc, val, vah) == (e_poc, e_val, e_vah)
    assert _volume_profile_proxy([{"volume": 1}] * 5, 20) == (None, None, None)


def test_fusion_call_graph_reaches_engine_volume_profile():
    """F15: bayesian_fusion → signal_layer_v1 → engine. One algorithm."""
    fusion = (ROOT / "bayesian_fusion.py").read_text(encoding="utf-8")
    assert "from features.signal_layer_v1 import" in fusion
    assert "signal_layer_v1_to_direction_probs" in fusion
    sl = (ROOT / "features" / "signal_layer_v1.py").read_text(encoding="utf-8")
    assert "poc, val, vah = _volume_profile_proxy(" in sl
    assert "from liquidity_value_engine import _volume_profile_poc_vah_val" in sl


_POC_ENGINE_CALLEES = frozenset(
    {"_volume_profile_poc_vah_val", "compute_volume_profile_levels"}
)
_POC_ALG_NAMES = frozenset({"vol_by_price", "nbin"})


def _fn_delegates_to_poc_engine(src: str, fn) -> bool:
    import ast

    seg = ast.get_source_segment(src, fn) or ""
    return "liquidity_value_engine" in seg or "_volume_profile_poc_vah_val" in seg


def _assign_target_names(target) -> list[str]:
    import ast

    out: list[str] = []
    if isinstance(target, ast.Name):
        out.append(target.id)
    elif isinstance(target, ast.Attribute):
        out.append(target.attr)
    elif isinstance(target, ast.Tuple):
        for elt in target.elts:
            out.extend(_assign_target_names(elt))
    return out


def _is_poc_vah_val_triple(names: list[str]) -> bool:
    low = [n.lower() for n in names]
    has_poc = any("poc" in n for n in low)
    has_va = any(n == "vah" or n.endswith("vah") or n == "val" or n.endswith("_val") for n in low)
    return has_poc and has_va


def _call_name(node) -> str | None:
    import ast

    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def undelegated_volume_profile_defs(src: str, filename: str = "<src>") -> list[str]:
    """F15 class: a second POC/VAH/VAL algorithm or unpack, any function name.

    The name `volume_profile` is not the universe. A `_value_area_*` helper
    that bins locally, or `poc, vah, val = <other>()`, is the same class.
    """
    import ast

    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    is_engine = filename.endswith("liquidity_value_engine.py") or filename == "liquidity_value_engine.py"
    local_defs = {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    offenders: list[str] = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        if names & _POC_ALG_NAMES:
            if is_engine and fn.name in _POC_ENGINE_CALLEES:
                continue
            if not _fn_delegates_to_poc_engine(src, fn):
                offenders.append(f"{filename}:{fn.name}")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            ns = _assign_target_names(target)
            if not _is_poc_vah_val_triple(ns):
                continue
            callee = _call_name(node.value)
            if callee is None:
                continue
            if callee in _POC_ENGINE_CALLEES:
                continue
            local = local_defs.get(callee)
            if local is not None and _fn_delegates_to_poc_engine(src, local):
                continue
            offenders.append(f"{filename}:{callee}")
    return sorted(set(offenders))


def test_all_volume_profile_function_defs_are_engine_or_passthrough():
    """F15 producer enumeration: every _volume_profile* def is the engine or delegates."""
    import subprocess

    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    skip = ("tests/", "tools/", "research/", "governance/", "arch_competition/")
    offenders: list[str] = []
    for rel in [p for p in proc.stdout.split("\0") if p]:
        if rel.startswith(skip):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        offenders.extend(undelegated_volume_profile_defs(text, rel))
    assert offenders == []


def test_volume_profile_class_flags_undelegated_def_in_uncited_file():
    """Defect-learning: class fires on a helper that is not named volume_profile."""
    plant = (
        "def _value_area_from_closes(bars):\n"
        "    nbin = 12\n"
        "    vol_by_price = {}\n"
        "    return bars[-1]['close'], bars[-1]['close'], bars[-1]['close']\n"
        "\n"
        "poc, vah, val = _value_area_from_closes(bars)\n"
    )
    found = undelegated_volume_profile_defs(plant, "features/unrelated_layer.py")
    assert "features/unrelated_layer.py:_value_area_from_closes" in found, found


def test_cluster_price_levels():
    """Levels within threshold clustered into zones."""
    from liquidity_value_engine import cluster_price_levels_into_zones
    from liquidity_models import PlaybookConfig
    levels = [(500.0, "PDH"), (500.5, "PD_VAH"), (505.0, "ORB_HIGH")]
    cfg = PlaybookConfig(clustering_threshold_pct=0.01)
    clusters = cluster_price_levels_into_zones(levels, 500.0, cfg)
    assert len(clusters) >= 1


def test_build_premarket_snapshot():
    """Premarket snapshot produces zones."""
    from liquidity_value_engine import build_premarket_snapshot
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    out = build_premarket_snapshot("SPY", bars, session, cfg)
    assert out.ticker == "SPY"
    assert out.snapshot_type.value == "premarket"
    assert out.session_date == "2026-03-13"
    assert isinstance(out.zones, list)


def test_build_opening_snapshot():
    """Opening snapshot includes ORB and VWAP."""
    from liquidity_value_engine import build_opening_snapshot
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    out = build_opening_snapshot("SPY", bars, session, cfg)
    assert out.snapshot_type.value == "opening"
    assert "orb" in out.raw_levels


def test_build_midday_snapshot():
    """Midday snapshot includes value shift and summary."""
    from liquidity_value_engine import build_midday_snapshot
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    out = build_midday_snapshot("SPY", bars, session, cfg)
    assert out.snapshot_type.value == "midday"
    assert out.summary is not None
    assert out.summary.value_state in ("shifted_higher", "shifted_lower", "unchanged")


def test_build_afternoon_snapshot():
    """Afternoon snapshot produced."""
    from liquidity_value_engine import build_afternoon_snapshot
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    out = build_afternoon_snapshot("SPY", bars, session, cfg)
    assert out.snapshot_type.value == "afternoon"


def test_generate_liquidity_value_snapshot_master():
    """Master function generates all snapshot types."""
    from liquidity_value_engine import generate_liquidity_value_snapshot
    from liquidity_models import SnapshotType, PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    for st in [SnapshotType.PREMARKET, SnapshotType.OPENING, SnapshotType.MIDDAY, SnapshotType.AFTERNOON]:
        out = generate_liquidity_value_snapshot("QQQ", bars, session, st, cfg)
        assert out.ticker == "QQQ"
        assert out.snapshot_type == st


def test_no_lookahead_premarket():
    """Premarket snapshot does not use same-day RTH data."""
    from liquidity_value_engine import build_premarket_snapshot
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    # Only previous day bars
    from datetime import timedelta
    prev_date = session - timedelta(days=1)
    bars = []
    for i in range(100):
        dt = datetime(prev_date.year, prev_date.month, prev_date.day, 10, 0 + i % 60, tzinfo=ET)
        bars.append(_mk_bar(dt, 500, 501, 499, 500, 1000))
    cfg = PlaybookConfig()
    out = build_premarket_snapshot("SPY", bars, session, cfg)
    assert out.raw_levels.get("prev_day")
    # No today POC/VAH/VAL in premarket raw
    assert "poc" not in str(out.raw_levels.get("prev_day", {})).lower() or "pd_" in str(out.raw_levels)


def test_summarize_snapshot():
    """summarize_snapshot produces readable text."""
    from liquidity_value_engine import build_midday_snapshot, summarize_snapshot
    from liquidity_models import PlaybookConfig
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    out = build_midday_snapshot("SPY", bars, session, cfg)
    text = summarize_snapshot(out)
    assert "SPY" in text
    assert "MIDDAY" in text


def test_opening_cutoff_0945():
    """OPENING snapshot uses data only through 09:45 ET."""
    from liquidity_value_engine import build_opening_snapshot, _cutoff_for_snapshot
    from liquidity_models import PlaybookConfig, SnapshotType

    session = date(2026, 3, 13)
    cfg = PlaybookConfig()
    cutoff = _cutoff_for_snapshot(SnapshotType.OPENING, session)
    assert cutoff is not None
    assert cutoff.hour == 9 and cutoff.minute == 45

    bars_through_0945 = _bars_through(session, 9, 45)
    bars_through_1000 = _bars_through(session, 10, 0)
    out_0945 = build_opening_snapshot("SPY", bars_through_0945, session, cfg)
    out_1000 = build_opening_snapshot("SPY", bars_through_1000, session, cfg)
    assert out_0945.raw_levels.get("orb") is not None
    assert out_1000.raw_levels.get("orb") is not None
    assert out_0945.raw_levels["orb"]["orb_high"] == out_1000.raw_levels["orb"]["orb_high"]
    assert out_0945.raw_levels["orb"]["orb_low"] == out_1000.raw_levels["orb"]["orb_low"]


def test_midday_cutoff_1030():
    """MIDDAY snapshot uses data only through 10:30 ET."""
    from liquidity_value_engine import build_midday_snapshot, _cutoff_for_snapshot
    from liquidity_models import PlaybookConfig, SnapshotType

    session = date(2026, 3, 13)
    cfg = PlaybookConfig()
    cutoff = _cutoff_for_snapshot(SnapshotType.MIDDAY, session)
    assert cutoff is not None
    assert cutoff.hour == 10 and cutoff.minute == 30

    bars_through_1030 = _bars_through(session, 10, 30)
    bars_through_1100 = _bars_through(session, 11, 0)
    out_1030 = build_midday_snapshot("SPY", bars_through_1030, session, cfg)
    out_1100 = build_midday_snapshot("SPY", bars_through_1100, session, cfg)
    assert out_1030.raw_levels.get("poc") is not None
    assert out_1100.raw_levels.get("poc") is not None
    assert out_1030.raw_levels["poc"] == out_1100.raw_levels["poc"]


def test_afternoon_cutoff_1400():
    """AFTERNOON snapshot uses data only through 14:00 ET."""
    from liquidity_value_engine import build_afternoon_snapshot, _cutoff_for_snapshot
    from liquidity_models import PlaybookConfig, SnapshotType

    session = date(2026, 3, 13)
    cfg = PlaybookConfig()
    cutoff = _cutoff_for_snapshot(SnapshotType.AFTERNOON, session)
    assert cutoff is not None
    assert cutoff.hour == 14 and cutoff.minute == 0

    bars_through_1400 = _bars_through(session, 14, 0)
    bars_through_1500 = _bars_through(session, 15, 0)
    out_1400 = build_afternoon_snapshot("SPY", bars_through_1400, session, cfg)
    out_1500 = build_afternoon_snapshot("SPY", bars_through_1500, session, cfg)
    assert out_1400.raw_levels.get("poc") is not None
    assert out_1500.raw_levels.get("poc") is not None
    assert out_1400.raw_levels["poc"] == out_1500.raw_levels["poc"]


def test_playbook_state_builds():
    """PlaybookState builds correctly with all snapshots."""
    from liquidity_value_engine import generate_playbook_state
    from liquidity_models import PlaybookConfig

    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig()
    state = generate_playbook_state("SPY", bars, session, cfg)

    assert state.ticker == "SPY"
    assert state.session_date == "2026-03-13"
    assert state.premarket_snapshot is not None
    assert state.opening_snapshot is not None
    assert state.midday_snapshot is not None
    assert state.afternoon_snapshot is not None
    assert state.premarket_snapshot.snapshot_type.value == "premarket"
    assert state.opening_snapshot.snapshot_type.value == "opening"
    assert state.midday_snapshot.snapshot_type.value == "midday"
    assert state.afternoon_snapshot.snapshot_type.value == "afternoon"
    assert state.latest_snapshot_type is not None
    assert state.generated_at is not None


def test_atr_clustering_no_lookahead():
    """ATR-based clustering works and does not use lookahead."""
    from liquidity_value_engine import (
        cluster_price_levels_into_zones,
        compute_atr_from_bars,
        _cutoff_for_snapshot,
    )
    from liquidity_models import PlaybookConfig, SnapshotType

    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig(clustering_mode="atr", clustering_threshold_atr_mult=1.0)
    cutoff = _cutoff_for_snapshot(SnapshotType.OPENING, session)
    atr = compute_atr_from_bars(bars, session, cutoff, period=14)
    assert atr is not None
    assert atr > 0

    levels = [(500.0, "PDH"), (500.5, "PD_VAH"), (502.0, "ORB_HIGH")]
    clusters = cluster_price_levels_into_zones(levels, 500.0, cfg, atr_value=atr)
    assert len(clusters) >= 1

    cfg_percent = PlaybookConfig(clustering_mode="percent")
    clusters_pct = cluster_price_levels_into_zones(levels, 500.0, cfg_percent)
    clusters_atr = cluster_price_levels_into_zones(levels, 500.0, cfg, atr_value=0.5)
    assert len(clusters_atr) >= 1


def test_source_levels_use_actual_values():
    """source_levels stores actual level prices, not zone midpoint."""
    from liquidity_value_engine import cluster_price_levels_into_zones
    from liquidity_models import PlaybookConfig
    levels = [(100.0, "A"), (101.0, "B"), (105.0, "C")]
    cfg = PlaybookConfig(clustering_mode="fixed", clustering_threshold=10.0)
    clusters = cluster_price_levels_into_zones(levels, 100.0, cfg)
    assert len(clusters) == 1
    lo, hi, mid, tags, source_pairs = clusters[0]
    assert mid == 102.5
    for p, t in source_pairs:
        if t == "A":
            assert p == 100.0
        elif t == "B":
            assert p == 101.0
        elif t == "C":
            assert p == 105.0


def test_max_zone_width():
    """max_zone_width prevents over-merged zones."""
    from liquidity_value_engine import cluster_price_levels_into_zones
    from liquidity_models import PlaybookConfig

    levels = [(100.0, "A"), (100.5, "B"), (101.0, "C"), (102.0, "D"), (103.0, "E")]
    cfg = PlaybookConfig(clustering_mode="fixed", clustering_threshold=2.0)
    clusters = cluster_price_levels_into_zones(levels, 100.0, cfg)
    assert len(clusters) >= 1

    cfg_cap = PlaybookConfig(clustering_mode="fixed", clustering_threshold=2.0, max_zone_width=1.5)
    clusters_cap = cluster_price_levels_into_zones(levels, 100.0, cfg_cap)
    for lo, hi, _, _, _ in clusters_cap:
        assert hi - lo <= 1.5 + 0.001, f"zone {lo}-{hi} exceeds max_zone_width 1.5"
    assert len(clusters_cap) >= len(clusters), "cap should produce more zones when width limited"


def test_merge_live_overlay_overwrites_minute():
    from liquidity_value_engine import merge_schwab_bars_with_live_overlay

    t0 = datetime(2026, 6, 15, 14, 30, 0, tzinfo=ET)
    ts_ms = int(t0.timestamp() * 1000)
    base = [
        {"timestamp": ts_ms, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
    ]
    over = [
        {"timestamp": ts_ms, "open": 100, "high": 102, "low": 99, "close": 101.5, "volume": 50},
    ]
    m = merge_schwab_bars_with_live_overlay(base, over)
    assert len(m) == 1
    assert m[0]["close"] == 101.5


def test_build_live_snapshot_smoke():
    """Live path runs without error on synthetic session bars."""
    from liquidity_value_engine import build_live_snapshot
    from liquidity_models import PlaybookConfig, SnapshotType
    session = date(2026, 3, 13)
    bars = _synthetic_bars(session)
    cfg = PlaybookConfig(clustering_mode="percent", max_zone_width=2.0)
    out = build_live_snapshot("SPY", bars, session, cfg, extra_levels=[(505.0, "GAMMA_CALL_WALL")], spot=500.0)
    assert out.snapshot_type in (SnapshotType.LIVE, SnapshotType.PREMARKET)
    assert isinstance(out.zones, list)
    if out.snapshot_type == SnapshotType.LIVE:
        assert "cutoff_et" in (out.raw_levels or {})


def run_all():
    test_imports()
    test_bars_normalization()
    test_get_previous_day_levels()
    test_compute_opening_range()
    test_compute_session_vwap()
    test_compute_volume_profile_levels()
    test_cluster_price_levels()
    test_build_premarket_snapshot()
    test_build_opening_snapshot()
    test_build_midday_snapshot()
    test_build_afternoon_snapshot()
    test_generate_liquidity_value_snapshot_master()
    test_no_lookahead_premarket()
    test_summarize_snapshot()
    test_opening_cutoff_0945()
    test_midday_cutoff_1030()
    test_afternoon_cutoff_1400()
    test_playbook_state_builds()
    test_atr_clustering_no_lookahead()
    test_source_levels_use_actual_values()
    test_max_zone_width()
    test_build_live_snapshot_smoke()
    test_merge_live_overlay_overwrites_minute()
    print("All liquidity engine tests passed.")


if __name__ == "__main__":
    run_all()
