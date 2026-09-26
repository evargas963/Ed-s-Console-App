"""RC-429 — snapshots.gamma_pin is two quantities across time; analyses must not mix them.

Writer land is commit 95a61031 (2026-08-19T14:10:58Z): persist switched from
getattr(consensus_summary, "gamma_pin") (selected-expiry net-GEX peak) to
terrain_cache_get / pick_pin_and_strength (total-gamma pin). Historical values
are not rewritten. Research: tests/test_institutional_key_levels.py
test_net_gex_peak_uses_net_gex_when_dollarized (743.0 vs 745.0 on the SPY 0DTE
fixture) and math_exposure_core.py pick_pin_and_strength vs pick_net_gex_peak_strike.
"""
from __future__ import annotations

import re


REQUIRED = "SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC"
HELPER = "snapshots_gamma_pin_is_terrain_analysis_safe"
SEMANTIC_FN = "snapshots_gamma_pin_semantic"

_SELECT_PIN = re.compile(
    r"SELECT[\s\S]{0,1200}gamma_pin[\s\S]{0,1200}FROM\s+snapshots\b",
    re.IGNORECASE,
)


def snapshot_gamma_pin_sql_without_era_split(src: str) -> bool:
    """True when SQL reads snapshots.gamma_pin without naming the era split."""
    if not _SELECT_PIN.search(src):
        return False
    return REQUIRED not in src and HELPER not in src and SEMANTIC_FN not in src








def test_injected_unsplit_select_is_caught_and_tracked_readers_are_split(repo_index):
    bad = (
        "rows = con.execute('''SELECT ticker, ts_utc, gamma_pin "
        "FROM snapshots WHERE gamma_pin IS NOT NULL''')"
    )
    assert snapshot_gamma_pin_sql_without_era_split(bad) is True
    good_sql = (
        "from time_et import SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC\n"
        "SELECT gamma_pin FROM snapshots WHERE ts_utc >= "
        "SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC"
    )
    assert snapshot_gamma_pin_sql_without_era_split(good_sql) is False
    good_helper = (
        "from time_et import snapshots_gamma_pin_is_terrain_analysis_safe\n"
        "SELECT ticker, ts_utc, gamma_pin FROM snapshots WHERE spot IS NOT NULL"
    )
    assert snapshot_gamma_pin_sql_without_era_split(good_helper) is False
    offenders: list[str] = []
    scoped = {rel.as_posix(): text for rel, text, _tree in repo_index.items()
              if rel.as_posix().startswith(("tools/", "research/"))}
    for rel, src in sorted(scoped.items()):
        if snapshot_gamma_pin_sql_without_era_split(src):
            offenders.append(rel)
    assert offenders == [], (
        "snapshots.gamma_pin SQL readers must name the RC-429 era split: "
        + ", ".join(offenders)
    )
