"""OUT-OF-SCOPE: audit-only gap measurement for RC-159 claim; not production."""
from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

DB = "data/ed_console.db"
ET = ZoneInfo("America/New_York")
CT = ZoneInfo("America/Chicago")
DATE = "2026-07-30"


def et_hm(ts: float | int | str) -> str:
    t = float(ts)
    return datetime.fromtimestamp(t, ET).strftime("%Y-%m-%d %H:%M:%S %Z")


def main() -> None:
    print("db_exists", os.path.exists(DB), "size", os.path.getsize(DB) if os.path.exists(DB) else None)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    tabs = [
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%chain%'"
        )
    ]
    print("chain_tables", tabs)
    for t in tabs:
        cols = [tuple(x) for x in con.execute(f"PRAGMA table_info({t})")]
        print("SCHEMA", t, cols)

    # morning_full for DATE
    print("\n=== option_chain_morning_full et_date=", DATE, "===")
    rows = list(
        con.execute(
            "SELECT ticker, et_date, ts_utc, n_contracts, "
            "CASE WHEN option_chain_json IS NULL THEN 0 ELSE length(option_chain_json) END AS jlen "
            "FROM option_chain_morning_full WHERE et_date=? ORDER BY ticker",
            (DATE,),
        )
    )
    print("COUNT_morning_full", len(rows))
    for r in rows:
        print(dict(r), "et=", et_hm(r["ts_utc"]))

    # accrual table existence + counts
    if "option_chain_accrual" in tabs:
        print("\n=== option_chain_accrual ===")
        print("COUNT_all", con.execute("SELECT COUNT(*) FROM option_chain_accrual").fetchone()[0])
        by = list(
            con.execute(
                "SELECT ticker, et_date, COUNT(*) c, MIN(et_minute) mn, MAX(et_minute) mx, "
                "MIN(ts_utc) t0, MAX(ts_utc) t1 FROM option_chain_accrual GROUP BY ticker, et_date "
                "ORDER BY et_date DESC, ticker LIMIT 40"
            )
        )
        for r in by:
            d = dict(r)
            d["t0_et"] = et_hm(r["t0"])
            d["t1_et"] = et_hm(r["t1"])
            print(d)
    else:
        print("\nNO option_chain_accrual TABLE (expected if schema never applied live)")

    # snapshots option_chain_json sampling for DATE — narrow vs wide
    print("\n=== snapshots.option_chain_json census DATE=", DATE, "===")
    # find columns
    snap_cols = [x[1] for x in con.execute("PRAGMA table_info(snapshots)")]
    print("snap_cols_sample", [c for c in snap_cols if "chain" in c.lower() or c in ("ticker", "ts_utc", "et_date")])

    # Determine how et_date / ts stored
    has_et = "et_date" in snap_cols
    has_json = "option_chain_json" in snap_cols
    print("has_et_date", has_et, "has_option_chain_json", has_json)

    if has_json:
        if has_et:
            q = (
                "SELECT ticker, ts_utc, et_date, "
                "length(option_chain_json) AS jlen "
                "FROM snapshots WHERE et_date=? AND option_chain_json IS NOT NULL "
                "ORDER BY ticker, ts_utc"
            )
            snaps = list(con.execute(q, (DATE,)))
        else:
            # derive from ts
            t0 = datetime(2026, 7, 30, 0, 0, tzinfo=ET).timestamp()
            t1 = datetime(2026, 7, 31, 0, 0, tzinfo=ET).timestamp()
            snaps = list(
                con.execute(
                    "SELECT ticker, ts_utc, length(option_chain_json) AS jlen "
                    "FROM snapshots WHERE ts_utc>=? AND ts_utc<? AND option_chain_json IS NOT NULL "
                    "ORDER BY ticker, ts_utc",
                    (t0, t1),
                )
            )
        print("COUNT_snaps_with_chain", len(snaps))
        # classify by contract count via JSON parse for first/last few per ticker and hourly samples
        for ticker in ("SPY", "QQQ", "IWM"):
            tsnaps = [s for s in snaps if s["ticker"] == ticker]
            print(f"\n--- {ticker} snaps_with_chain={len(tsnaps)} ---")
            if not tsnaps:
                continue
            # sample by hour ET + first/last + any jlen outliers
            samples = []
            seen_hour = set()
            for s in tsnaps:
                dt = datetime.fromtimestamp(float(s["ts_utc"]), ET)
                h = dt.hour
                if h not in seen_hour or s == tsnaps[0] or s == tsnaps[-1]:
                    seen_hour.add(h)
                    samples.append(s)
            # also pick max jlen and min jlen
            by_len = sorted(tsnaps, key=lambda r: r["jlen"])
            for s in (by_len[0], by_len[-1]):
                if s not in samples:
                    samples.append(s)

            # exact n_contracts for each unique jlen class via one parse each
            jlen_to_n: dict[int, tuple] = {}
            for s in samples:
                jl = int(s["jlen"])
                if jl in jlen_to_n:
                    continue
                row = con.execute(
                    "SELECT option_chain_json FROM snapshots WHERE ticker=? AND ts_utc=? LIMIT 1",
                    (s["ticker"], s["ts_utc"]),
                ).fetchone()
                n_c, n_strikes, vol_sum = parse_chain(row["option_chain_json"] if row else None)
                jlen_to_n[jl] = (n_c, n_strikes, vol_sum)

            # full timeline of class
            classes = Counter()
            first_wide = None
            first_any = None
            _vol_nonzero = None
            for s in tsnaps:
                jl = int(s["jlen"])
                # approximate class by jlen buckets if not parsed
                cls = "WIDE" if jl > 200_000 else "NARROW"
                classes[cls] += 1
                if first_any is None:
                    first_any = s
                if cls == "WIDE" and first_wide is None:
                    first_wide = s
            print("class_counts_by_jlen_threshold", dict(classes))
            if first_any:
                print("first_any", et_hm(first_any["ts_utc"]), "jlen", first_any["jlen"])
            if first_wide:
                print("first_wide_approx", et_hm(first_wide["ts_utc"]), "jlen", first_wide["jlen"])

            # Parse ALL unique jlens for exact census (cheap if few shapes)
            unique_jlens = sorted({int(s["jlen"]) for s in tsnaps})
            print("unique_jlen_count", len(unique_jlens), "values", unique_jlens[:20])
            jl_meta = {}
            for jl in unique_jlens:
                s = next(x for x in tsnaps if int(x["jlen"]) == jl)
                row = con.execute(
                    "SELECT option_chain_json FROM snapshots WHERE ticker=? AND ts_utc=? LIMIT 1",
                    (s["ticker"], s["ts_utc"]),
                ).fetchone()
                jl_meta[jl] = parse_chain(row["option_chain_json"] if row else None)
            print("jlen_meta", {k: jl_meta[k] for k in jl_meta})

            # exact first wide / narrow timeline
            narrow_times = []
            wide_times = []
            volpos_times = []
            for s in tsnaps:
                n_c, n_strikes, vol_sum = jl_meta[int(s["jlen"])]
                kind = "WIDE" if n_c >= 500 else "NARROW"
                if kind == "NARROW":
                    narrow_times.append(s)
                else:
                    wide_times.append(s)
                if vol_sum and vol_sum > 0:
                    volpos_times.append((s, vol_sum, n_c, n_strikes))
            print(
                "COUNT_narrow",
                len(narrow_times),
                "COUNT_wide",
                len(wide_times),
            )
            if narrow_times:
                print(
                    "first_narrow",
                    et_hm(narrow_times[0]["ts_utc"]),
                    "last_narrow",
                    et_hm(narrow_times[-1]["ts_utc"]),
                    "n_c/strikes/vol",
                    jl_meta[int(narrow_times[0]["jlen"])],
                )
            if wide_times:
                print(
                    "first_wide",
                    et_hm(wide_times[0]["ts_utc"]),
                    "last_wide",
                    et_hm(wide_times[-1]["ts_utc"]),
                    "n_c/strikes/vol",
                    jl_meta[int(wide_times[0]["jlen"])],
                )
            if volpos_times:
                s, vol_sum, n_c, n_strikes = volpos_times[0]
                print(
                    "first_vol_gt0",
                    et_hm(s["ts_utc"]),
                    "vol_sum",
                    vol_sum,
                    "n_c",
                    n_c,
                    "strikes",
                    n_strikes,
                )
            else:
                print("first_vol_gt0", None)

            # morning window before 10:00 ET: exact counts
            pre10 = [
                s
                for s in tsnaps
                if datetime.fromtimestamp(float(s["ts_utc"]), ET).hour < 10
            ]
            pre10_narrow = sum(1 for s in pre10 if jl_meta[int(s["jlen"])][0] < 500)
            pre10_wide = sum(1 for s in pre10 if jl_meta[int(s["jlen"])][0] >= 500)
            print("pre10_ET_COUNT", len(pre10), "narrow", pre10_narrow, "wide", pre10_wide)

    # morning_full chain parse
    print("\n=== morning_full parsed ===")
    for r in con.execute(
        "SELECT ticker, ts_utc, option_chain_json, n_contracts FROM option_chain_morning_full WHERE et_date=?",
        (DATE,),
    ):
        meta = parse_chain(r["option_chain_json"])
        print(r["ticker"], et_hm(r["ts_utc"]), "n_contracts_col", r["n_contracts"], "parsed", meta)

    con.close()


def parse_chain(raw) -> tuple:
    if not raw:
        return (0, 0, 0.0)
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return (-1, -1, -1.0)
    # Schwab shape: callExpMap / putExpMap -> strike -> quote
    n = 0
    strikes = set()
    vol = 0.0
    for key in ("callExpDateMap", "putExpDateMap"):
        m = d.get(key) or {}
        if not isinstance(m, dict):
            continue
        for _exp, smap in m.items():
            if not isinstance(smap, dict):
                continue
            for strike, quotes in smap.items():
                strikes.add(str(strike))
                if isinstance(quotes, list):
                    for q in quotes:
                        n += 1
                        if isinstance(q, dict):
                            v = q.get("totalVolume")
                            if v is not None:
                                try:
                                    vol += float(v)
                                except Exception:
                                    pass
                elif isinstance(quotes, dict):
                    n += 1
                    v = quotes.get("totalVolume")
                    if v is not None:
                        try:
                            vol += float(v)
                        except Exception:
                            pass
    return (n, len(strikes), vol)


if __name__ == "__main__":
    main()
