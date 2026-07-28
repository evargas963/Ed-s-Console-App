"""RC-58: every study loader refuses non-trading days.

A market-closed day's bars are frozen — realized range ~0.05% vs ~2.21% on trading days with no
distribution overlap (measured under RC-58) — so weekend contamination is a deterministic bias
toward "nothing moved", not noise. Minute-of-day windows alone admit Saturday 10:00 bars; the
calendar gate is the missing half. These tests drive the REAL loaders with a Saturday and a
Monday and require the Saturday to vanish.
"""
from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from time_et import et_date_str_from_ts_utc  # noqa: E402

SAT = datetime.datetime(2026, 7, 25, 14, 0, tzinfo=datetime.timezone.utc).timestamp()  # Sat 10:00 ET
MON = datetime.datetime(2026, 7, 27, 14, 0, tzinfo=datetime.timezone.utc).timestamp()  # Mon 10:00 ET


def test_gamma_conditioned_medians_drop_saturday():
    from research.pilot_step3.gamma_conditioned_study_v1 import session_gamma_medians
    out = session_gamma_medians([(SAT, 1.0), (MON, 2.0)], et_date_str_from_ts_utc)
    assert list(out) == ["2026-07-27"], f"Saturday survived the calendar gate: {out}"


def test_day_level_gex_morning_gamma_drops_saturday():
    from tools.run_day_level_gex_study_v1 import morning_gamma_by_session
    out = morning_gamma_by_session([(SAT, 5.0), (MON, 6.0)])
    assert list(out) == ["2026-07-27"], f"Saturday survived: {out}"


def test_every_named_rc58_loader_carries_the_gate():
    """Source-level lock: the seven RC-58 loaders each call the one calendar authority.

    Behavioural tests above cover the two pure functions; the bar-loop loaders read the live DB,
    so their lock is structural — the gate call must sit in the source between the day assembly
    and the row admission."""
    files = [
        "tools/study_card2_am_pm_v1.py",
        "tools/study_timeslice_reversal_v1.py",
        "tools/study_card_lateday_v1.py",
        "tools/study_card_lateday_v2.py",
        "tools/run_day_level_gex_study_v1.py",
        "research/gex_r1_screen_v1/signal.py",
        "research/pilot_step3/gamma_conditioned_study_v1.py",
    ]
    missing = []
    for rel in files:
        text = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        if not re.search(r"if not is_trading_day_et\(", text):
            missing.append(rel)
    assert not missing, f"RC-58 regression — calendar gate removed from: {missing}"
