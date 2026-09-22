"""EdDB level-crossing + daily banking cluster (RC-REHAB-1, db.py decomposition slice 4).

LevelCrossingMixin owns: logging level-crossing events, daily ATM IV / per-strike OI
banking (RC-354/RC-359), tick-driven cross detection with debounce, and the crosses/
zone-distribution/level-test readers. Assumes `self._connect()` from the host `EdDB`
class (db.py).

Monkeypatch/circularity note: `LevelCrossEvent` and `utc_ts` stay defined in db.py and
are reached here via a LAZY `import db` inside each method body that needs them (not a
top-level `from db import ...`) -- db.py imports this module before either name exists
in its own namespace, so a top-level import would fail at db.py's own import time.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from db import LevelCrossEvent


class LevelCrossingMixin:
    # Pass 4: minimum seconds between two recorded crosses of the same
    # (ticker, level_name, direction). Prevents tape-oscillation spam without
    # losing signal when price genuinely reverses (an "up" cross does not
    # debounce a subsequent "down" cross of the same level).
    LEVEL_CROSS_DEBOUNCE_S: float = 60.0

    def log_level_cross(self, event: "LevelCrossEvent") -> int:
        """Log a level crossing event."""
        d = asdict(event)
        cols = ", ".join(d.keys())
        placeholders = ", ".join("?" for _ in d)
        sql = f"INSERT INTO level_crosses ({cols}) VALUES ({placeholders})"
        vals = list(d.values())

        def _do() -> int:
            with self._connect() as conn:
                cur = conn.execute(sql, vals)
                return int(cur.lastrowid)

        return _do()

    def bank_daily_atm_iv(self, ticker: str, date_et: str, atm_iv_pct: float,
                          dte_used: int | None, method: str | None,
                          ts_utc: float) -> None:
        """RC-354: UPSERT the day's ATM IV — last write of the session wins, so the
        banked value converges to the CLOSING ATM IV (the convention IV Rank/Percentile
        are defined against). One row per (ticker, ET date); idempotent."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO iv_daily (ticker, date_et, atm_iv_pct, dte_used, method, ts_utc) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(ticker, date_et) DO UPDATE SET "
                "atm_iv_pct=excluded.atm_iv_pct, dte_used=excluded.dte_used, "
                "method=excluded.method, ts_utc=excluded.ts_utc",
                (ticker, date_et, float(atm_iv_pct), dte_used, method, float(ts_utc)),
            )

    def bank_daily_strike_oi(self, ticker: str, date_et: str,
                             rows: list[tuple[float, float | None, float | None]],
                             ts_utc: float) -> None:
        """RC-359: batch-UPSERT the day's per-strike OI — last write of the session wins.
        rows = [(strike, call_oi, put_oi), ...]; empty rows write nothing (a gap is
        visible, a fabricated observation is not)."""
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO oi_daily (ticker, date_et, strike, call_oi, put_oi, ts_utc) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(ticker, date_et, strike) DO UPDATE SET "
                "call_oi=excluded.call_oi, put_oi=excluded.put_oi, ts_utc=excluded.ts_utc",
                [(ticker, date_et, float(k), c, p, float(ts_utc)) for k, c, p in rows],
            )

    def prev_session_strike_oi(self, ticker: str, before_date_et: str) -> dict[float, tuple[float | None, float | None]]:
        """RC-359: the most recent banked session STRICTLY BEFORE before_date_et, as
        {strike: (call_oi, put_oi)}. Empty dict when no prior session exists (fail-closed:
        the ΔOI walls then render 'banking' — never a fabricated diff)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(date_et) FROM oi_daily WHERE ticker=? AND date_et<?",
                (ticker, before_date_et)).fetchone()
            prev = row[0] if row else None
            if not prev:
                return {}
            out: dict[float, tuple[float | None, float | None]] = {}
            for k, c, p in conn.execute(
                    "SELECT strike, call_oi, put_oi FROM oi_daily WHERE ticker=? AND date_et=?",
                    (ticker, prev)):
                out[float(k)] = (c, p)
            return out

    def detect_and_log_level_crosses(
        self,
        *,
        ticker: str,
        prev_spot: float | None,
        cur_spot: float | None,
        levels: list[tuple[float, str]],
        ts_utc: float,
        ts_et: str,
        timeframe: str = "1m",
        zone_before: Optional[str] = None,
        zone_after: Optional[str] = None,
        debounce_s: Optional[float] = None,
    ) -> list[dict]:
        """Detect spot-vs-level crossings between two ticks and persist them.

        Pass 4 wire from server tick path. For each (level_value, level_name)
        in ``levels``, records a `level_crosses` row when prev_spot and cur_spot
        sit on opposite sides of level_value, debounced by
        (ticker, level_name, direction) within ``debounce_s`` seconds.

        Returns the list of crosses actually logged (so the caller can emit
        a single log line per cross — Pass 4 telemetry).
        """
        if prev_spot is None or cur_spot is None:
            return []
        if float(prev_spot) == float(cur_spot):
            return []
        import db  # module-attribute access only -- see this file's own docstring

        direction = "up" if cur_spot > prev_spot else "down"
        deb = float(debounce_s) if debounce_s is not None else self.LEVEL_CROSS_DEBOUNCE_S
        debounce_since = float(ts_utc) - deb
        logged: list[dict] = []
        for raw_value, name in levels:
            if raw_value is None or name is None:
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            crossed_up = float(prev_spot) < value <= float(cur_spot)
            crossed_down = float(cur_spot) <= value < float(prev_spot)
            if not (crossed_up or crossed_down):
                continue
            with self._connect() as conn:
                last = conn.execute(
                    "SELECT ts_utc FROM level_crosses "
                    "WHERE ticker = ? AND level_name = ? AND direction = ? "
                    "ORDER BY ts_utc DESC LIMIT 1",
                    (ticker, name, direction),
                ).fetchone()
            if last is not None and float(last["ts_utc"]) >= debounce_since:
                continue
            event = db.LevelCrossEvent(
                ticker=ticker,
                ts_utc=float(ts_utc),
                ts_et=str(ts_et),
                level_name=str(name),
                level_value=value,
                direction=direction,
                spot_at_cross=float(cur_spot),
                zone_before=zone_before,
                zone_after=zone_after,
                timeframe=str(timeframe),
            )
            self.log_level_cross(event)
            logged.append(
                {
                    "level_name": name,
                    "level_value": value,
                    "direction": direction,
                    "spot_at_cross": float(cur_spot),
                }
            )
        return logged

    def get_recent_crosses(self, ticker: str, n: int = 20) -> list:
        """Return most recent level crossing events."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM level_crosses
                WHERE ticker = ?
                ORDER BY ts_utc DESC
                LIMIT ?
            """, (ticker, n)).fetchall()
        return [dict(r) for r in rows]

    def get_zone_distribution(self, ticker: str, timeframe: str) -> dict[str, int]:
        """Count snapshots per zone for ticker/timeframe (debug / diagnostics)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT zone, COUNT(*) AS cnt
                FROM snapshots
                WHERE ticker = ? AND timeframe = ? AND zone IS NOT NULL
                GROUP BY zone
                ORDER BY cnt DESC
                """,
                (ticker, timeframe),
            ).fetchall()
        out: dict[str, int] = {}
        for row in rows:
            r = dict(row)
            zone = r.get("zone")
            if zone is not None:
                out[str(zone)] = int(r["cnt"])  # caps-ok: COUNT(*) under GROUP BY is never NULL for an emitted row
        return out

    def count_level_tests(self, ticker: str, level_name: str,
                           level_value: float, lookback_hours: float = 6.5) -> dict:
        """
        Count how many times price has tested a level today.
        Used for: "third test of 685 ceiling — rejection likely"
        """
        import db  # module-attribute access only -- see this file's own docstring

        since_ts = db.utc_ts() - (lookback_hours * 3600)
        tolerance = 0.50  # pts — within 0.50 of level counts as a test

        with self._connect() as conn:
            crosses = conn.execute("""
                SELECT direction, COUNT(*) as cnt
                FROM level_crosses
                WHERE ticker = ?
                  AND level_name = ?
                  AND ts_utc >= ?
                  AND ABS(level_value - ?) <= ?
                GROUP BY direction
            """, (ticker, level_name, since_ts, level_value, tolerance)).fetchall()

        result = {"up": 0, "down": 0, "total": 0}
        for row in crosses:
            result[row["direction"]] = row["cnt"]
            result["total"] += row["cnt"]
        return result
