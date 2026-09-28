"""AUDIT-CAND-SERVER-PY-FULL-READ — FIND-SERVERPY-1..19 regression guards."""


def test_liquidity_zone_tradeable_score_authority_roundtrip():
    from liquidity_value_engine import liquidity_zone_tradeable_score

    assert liquidity_zone_tradeable_score(n_tags=1, n_opt=1, inside=False, dist_pen=0.0, spot=None) == 5.5
