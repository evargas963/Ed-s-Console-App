"""SPY hourly gamma x volume storm scores for Chart tab (descriptive, not edge)."""
from __future__ import annotations

import json
import sqlite3
import statistics
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
DB = "data/ed_console.db"
TICKER = "SPY"
DAY = datetime.now(ET).date().isoformat()
BAND_PCT = 0.05  # ±5% of spot for z-score storm
HOURS = [10, 11, 12, 13, 14, 15]  # RTH hour marks; plus latest


def et_from_ts(ts: float) -> datetime:
    return datetime.fromtimestamp(float(ts), ET)


def census():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    # snapshots has ts_et (not et_date); day filter = substr(ts_et,1,10)
    rows = con.execute(
        "SELECT ts_utc, spot, "
        "CASE WHEN option_chain_json IS NULL THEN 0 ELSE length(option_chain_json) END "
        "FROM snapshots WHERE ticker=? AND substr(ts_et,1,10)=? ORDER BY ts_utc",
        (TICKER, DAY),
    ).fetchall()
    tabs = [
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1"
        ).fetchall()
        if any(x in r[0].lower() for x in ("chain", "morning", "terrain", "snapshot"))
    ]
    mf = con.execute(
        "SELECT et_date, spot, n_contracts, ts_utc, length(chain_json) "
        "FROM option_chain_morning_full WHERE ticker=? AND et_date=?",
        (TICKER, DAY),
    ).fetchall()
    by_h = Counter()
    with_chain = 0
    for ts, spot, jlen in rows:
        by_h[et_from_ts(ts).strftime("%H")] += 1
        if jlen and jlen > 10:
            with_chain += 1
    print("DAY", DAY)
    print("n_snapshots", len(rows), "with_chain_json", with_chain)
    if rows:
        print(
            "first",
            et_from_ts(rows[0][0]).strftime("%H:%M:%S"),
            "spot",
            rows[0][1],
            "jlen",
            rows[0][2],
        )
        print(
            "last",
            et_from_ts(rows[-1][0]).strftime("%H:%M:%S"),
            "spot",
            rows[-1][1],
            "jlen",
            rows[-1][2],
        )
    print("by_hour", dict(sorted(by_h.items())))
    print("related_tables", tabs)
    print("morning_full", mf)
    con.close()
    return rows


def pick_latest_at_or_before(con, hour_et: int | None, latest: bool = False):
    """Causal: latest option_chain snapshot at or before hour:00 ET (or absolute latest)."""
    if latest:
        row = con.execute(
            "SELECT ts_utc, spot, option_chain_json FROM snapshots "
            "WHERE ticker=? AND substr(ts_et,1,10)=? AND option_chain_json IS NOT NULL "
            "AND length(option_chain_json) > 10 "
            "ORDER BY ts_utc DESC LIMIT 1",
            (TICKER, DAY),
        ).fetchone()
        return row
    # hour mark as ET wall clock on DAY
    mark = datetime.strptime(f"{DAY} {hour_et:02d}:00:00", "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=ET
    )
    mark_utc = mark.astimezone(timezone.utc).timestamp()
    row = con.execute(
        "SELECT ts_utc, spot, option_chain_json FROM snapshots "
        "WHERE ticker=? AND substr(ts_et,1,10)=? AND option_chain_json IS NOT NULL "
        "AND length(option_chain_json) > 10 AND ts_utc <= ? "
        "ORDER BY ts_utc DESC LIMIT 1",
        (TICKER, DAY, mark_utc),
    ).fetchone()
    return row


def build_rows(contracts, spot):
    from math_exposure_core import (
        bucket_metric,
        compute_exposures_by_strike,
        total_gamma_raw_at_strike,
    )
    from numeric_contract import float_finite_or_none, float_nonnegative_or_none

    exposures, diag = compute_exposures_by_strike(contracts, spot=spot, require_oi=True)
    vol_by_k: dict[float, float] = {}
    for ct in contracts or []:
        if not isinstance(ct, dict):
            continue
        sk = float_finite_or_none(ct.get("strikePrice"))
        v = float_nonnegative_or_none(ct.get("totalVolume"))
        if sk is not None and v:
            vol_by_k[sk] = vol_by_k.get(sk, 0.0) + v
    rows = []
    for k, b in (exposures or {}).items():
        sk = float_finite_or_none(k)
        if sk is None:
            continue
        g = bucket_metric(b, "net_gex_1pct")
        if g is None:
            g = total_gamma_raw_at_strike(b)
        rows.append([round(sk, 2), float(g or 0.0), int(vol_by_k.get(sk, 0))])
    rows.sort(key=lambda r: r[0])
    return rows, diag


def levels_from_contracts(contracts, spot):
    """Best-effort Chart-relevant levels from same chain (if helpers available)."""
    out = {}
    try:
        from math_levels import compute_key_levels

        kl = compute_key_levels(contracts, spot=float(spot))
        if isinstance(kl, dict):
            for k in (
                "call_wall",
                "put_wall",
                "gamma_flip",
                "flip",
                "pin",
                "gamma_pin",
                "hvl",
                "net_gex_peak",
            ):
                if k in kl and kl[k] is not None:
                    out[k] = kl[k]
    except Exception as e:
        out["_levels_err"] = f"{type(e).__name__}: {e}"
    return out


def ranks_desc(vals):
    """Average ranks for ties; higher value -> better (lower) rank number... we want 1=best.
    Return map index -> rank (1=highest)."""
    order = sorted(range(len(vals)), key=lambda i: vals[i], reverse=True)
    rank = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-based average rank
        for k in range(i, j + 1):
            rank[order[k]] = avg
        i = j + 1
    return rank


def zscores(vals):
    if len(vals) < 2:
        return [0.0] * len(vals)
    mu = statistics.fmean(vals)
    sd = statistics.pstdev(vals)
    if sd <= 0:
        return [0.0] * len(vals)
    return [(v - mu) / sd for v in vals]


def storm_table(rows, spot, band_pct=BAND_PCT):
    if not rows or spot is None or spot <= 0:
        return None
    vols = [r[2] for r in rows]
    abs_g = [abs(r[1]) for r in rows]
    rv = ranks_desc(vols)
    rg = ranks_desc(abs_g)
    # storm1: rank(vol) * rank(|gex|) but ranks are 1=best so invert to score
    # Operator asked rank(vol)×rank(|gex|) — with rank 1 best, product SMALLER is stronger.
    # For "highest storm score" we use inv_rank = n+1-rank so larger=stronger.
    n = len(rows)
    inv_v = [n + 1 - r for r in rv]
    inv_g = [n + 1 - r for r in rg]
    s1 = [inv_v[i] * inv_g[i] for i in range(n)]

    # band ±band_pct
    lo, hi = spot * (1 - band_pct), spot * (1 + band_pct)
    band_idx = [i for i, r in enumerate(rows) if lo <= r[0] <= hi]
    s2 = [0.0] * n
    if len(band_idx) >= 3:
        bv = [vols[i] for i in band_idx]
        bg = [abs_g[i] for i in band_idx]
        zv = zscores(bv)
        zg = zscores(bg)
        # use max(0,z) so negative z doesn't invent "storm" via sign flip
        for j, i in enumerate(band_idx):
            s2[i] = max(0.0, zv[j]) * max(0.0, zg[j])

    # storm3a: vol among top-|gex| strikes (top 10)
    # storm3b: |gex| among top-vol strikes
    top_g_idx = sorted(range(n), key=lambda i: abs_g[i], reverse=True)[:10]
    top_v_idx = sorted(range(n), key=lambda i: vols[i], reverse=True)[:10]
    # per-strike: if in top10 |gex|, score = its volume; if in top10 vol, score = its |gex|
    s3 = [0.0] * n
    for i in top_g_idx:
        s3[i] = float(vols[i])  # volume among high-GEX
    s3b = [0.0] * n
    for i in top_v_idx:
        s3b[i] = float(abs_g[i])

    def top_i(scores, restrict=None):
        idxs = restrict if restrict is not None else range(n)
        return max(idxs, key=lambda i: (scores[i], abs_g[i], vols[i]))

    i_vol = top_i(vols)
    i_gex = top_i(abs_g)
    # primary "strongest combination" = max s1 in ±5% band (Chart-relevant near spot)
    band_or_all = band_idx if band_idx else list(range(n))
    i_s1 = top_i(s1, band_or_all)
    i_s2 = top_i(s2, band_or_all) if any(s2[i] > 0 for i in band_or_all) else i_s1
    i_s3 = top_i(s3, top_g_idx)  # busiest volume among top |GEX|
    i_s3b = top_i(s3b, top_v_idx)  # largest |GEX| among top volume

    align = rows[i_vol][0] == rows[i_gex][0]

    return {
        "n": n,
        "sum_vol": sum(vols),
        "band_n": len(band_idx),
        "top_vol": {"strike": rows[i_vol][0], "vol": vols[i_vol], "gex": rows[i_vol][1]},
        "top_abs_gex": {
            "strike": rows[i_gex][0],
            "vol": vols[i_gex],
            "gex": rows[i_gex][1],
            "abs_gex": abs_g[i_gex],
        },
        "storm1_rankprod": {
            "strike": rows[i_s1][0],
            "score": s1[i_s1],
            "vol": vols[i_s1],
            "gex": rows[i_s1][1],
            "vol_rank": rv[i_s1],
            "gex_rank": rg[i_s1],
            "formula": "inv_rank(vol)*inv_rank(|gex|) within ±5% spot (inv_rank = n+1-rank, rank1=highest)",
        },
        "storm2_zprod": {
            "strike": rows[i_s2][0],
            "score": round(s2[i_s2], 4),
            "vol": vols[i_s2],
            "gex": rows[i_s2][1],
            "vol_rank": rv[i_s2],
            "gex_rank": rg[i_s2],
            "formula": "max(0,z(vol))*max(0,z(|gex|)) within ±5% spot",
        },
        "storm3_vol_among_top_gex": {
            "strike": rows[i_s3][0],
            "score": s3[i_s3],
            "vol": vols[i_s3],
            "gex": rows[i_s3][1],
            "vol_rank": rv[i_s3],
            "gex_rank": rg[i_s3],
            "formula": "volume among top-10 |GEX| strikes (score=volume)",
        },
        "storm3b_gex_among_top_vol": {
            "strike": rows[i_s3b][0],
            "score": s3b[i_s3b],
            "vol": vols[i_s3b],
            "gex": rows[i_s3b][1],
            "vol_rank": rv[i_s3b],
            "gex_rank": rg[i_s3b],
            "formula": "|GEX| among top-10 volume strikes (score=|gex|)",
        },
        "vol_gex_coincide": align,
    }


def live_now():
    try:
        d = json.load(
            urllib.request.urlopen(
                "http://127.0.0.1:8000/api/terrain/strikes?ticker=SPY", timeout=15
            )
        )
        t = json.load(
            urllib.request.urlopen(
                "http://127.0.0.1:8000/api/terrain?ticker=SPY", timeout=15
            )
        )
        return d, t
    except Exception as e:
        return {"_err": str(e)}, None


def main():
    print("=== CENSUS ===")
    census()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    marks = [(f"{h:02d}:00", h, False) for h in HOURS] + [("latest", None, True)]
    results = []
    for label, hour, is_latest in marks:
        row = pick_latest_at_or_before(con, hour, latest=is_latest)
        if not row:
            results.append({"hour": label, "status": "NO_SNAPSHOT"})
            print(json.dumps(results[-1]))
            continue
        ts, spot, raw = row
        contracts = json.loads(raw)
        rows, diag = build_rows(contracts, float(spot))
        storm = storm_table(rows, float(spot))
        lv = levels_from_contracts(contracts, float(spot))
        et = et_from_ts(ts)
        lag_min = None
        if hour is not None:
            mark = datetime.strptime(
                f"{DAY} {hour:02d}:00:00", "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=ET)
            lag_min = round((mark - et).total_seconds() / 60.0, 1)
        rec = {
            "hour": label,
            "snap_et": et.strftime("%Y-%m-%d %H:%M:%S%z"),
            "lag_to_mark_min": lag_min,
            "spot": float(spot),
            "n_contracts": len(contracts),
            "storm": storm,
            "levels": lv,
            "source": "snapshots.option_chain_json",
        }
        results.append(rec)
        # compact print
        s = storm or {}
        s1 = s.get("storm1_rankprod") or {}
        print(
            f"{label} snap={et.strftime('%H:%M:%S')} lag={lag_min} spot={spot} "
            f"storm1={s1.get('strike')} score={s1.get('score')} "
            f"volR={s1.get('vol_rank')} gexR={s1.get('gex_rank')} "
            f"topVol={s.get('top_vol')} topG={s.get('top_abs_gex')} "
            f"align={s.get('vol_gex_coincide')} levels={ {k:lv.get(k) for k in ('call_wall','put_wall','gamma_flip','gamma_pin','hvl','net_gex_peak') if k in lv} }"
        )

    # live "now" from API (may be stale post-close)
    d, t = live_now()
    live_rec = None
    if d and not d.get("_err"):
        rows = (d.get("today") or {}).get("all") or []
        spot = d.get("spot")
        # reshape API rows already [strike, gex, vol]
        storm = storm_table(rows, float(spot) if spot else None)
        lv = {}
        if t and isinstance(t, dict):
            for k in (
                "call_wall",
                "put_wall",
                "gamma_flip",
                "flip",
                "pin",
                "gamma_pin",
                "hvl",
                "net_gex_peak",
                "computed_ts_utc",
                "spot",
            ):
                if k in t:
                    lv[k] = t[k]
            # nested
            for nest in ("levels", "key_levels", "walls"):
                if isinstance(t.get(nest), dict):
                    for k, v in t[nest].items():
                        if k not in lv:
                            lv[k] = v
        _cts = None
        # age
        age = d.get("today_age_sec")
        live_rec = {
            "hour": "now_live_api",
            "today_source": d.get("today_source"),
            "today_age_sec": age,
            "spot": spot,
            "storm": storm,
            "levels": lv,
            "source": "/api/terrain/strikes + /api/terrain",
        }
        s1 = (storm or {}).get("storm1_rankprod") or {}
        print(
            f"NOW live age={age}s spot={spot} storm1={s1.get('strike')} "
            f"score={s1.get('score')} align={(storm or {}).get('vol_gex_coincide')} "
            f"levels_keys={list(lv)[:20]}"
        )
    else:
        print("LIVE_FAIL", d)

    out = {
        "day_et": DAY,
        "ticker": TICKER,
        "band_pct": BAND_PCT,
        "formulas": {
            "storm1": "inv_rank(vol)*inv_rank(|net_gex_1pct|) within ±5% spot; inv_rank=n+1-rank",
            "storm2": "max(0,z(vol))*max(0,z(|gex|)) within ±5% spot",
            "storm3": "volume of strike among top-10 |GEX|; also |GEX| among top-10 volume",
        },
        "field_map": {
            "yellow_bars": "row[2] = Schwab totalVolume summed per strike (session)",
            "blue_red": "row[1] = dealer net_gex_1pct$ (call_gex - put_gex)",
            "producer": "terrain_engine._per_strike_rows / get_terrain_strikes",
        },
        "hourly": results,
        "now_live": live_rec,
        "disclaimer": "Descriptive ranking of Chart surface today — NOT proven predictive edge.",
    }
    path = "scratchpad/_spy_hourly_gamma_vol_storm_out.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print("WROTE", path)
    con.close()


if __name__ == "__main__":
    main()
