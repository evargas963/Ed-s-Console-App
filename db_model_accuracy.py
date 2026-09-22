"""EdDB model-accuracy cluster (RC-REHAB-1, db.py decomposition slice 4).

ModelAccuracyMixin owns Pass 5a/5b: RTH-scoped prediction-accuracy computation, the
model_accuracy writer/reader/history, and the dedup-throttled writer. Assumes
`self._connect()` from the host `EdDB` class (db.py).

Monkeypatch/circularity note: `utc_ts` stays defined in db.py and is reached here via a
LAZY `import db` inside `log_model_accuracy` (not a top-level `from db import ...`) --
db.py imports this module before `utc_ts` exists in its own namespace, so a top-level
import would fail at db.py's own import time.
"""
from __future__ import annotations

from typing import Optional

from snapshot_access import require_snapshot_timeframe
from time_et import RTH_START_MINS as _RTH_START_MINS_AUTH, RTH_END_MINS as _RTH_END_MINS_AUTH


class ModelAccuracyMixin:
    # RTH window for accuracy scoping: 9:30 inclusive to 16:00 exclusive, using the row's
    # stamped et_hour/et_minute. RC-345 / F09: the boundary is owned by the one authority,
    # time_et.RTH_START_MINS / RTH_END_MINS — not a second 570/960 literal here.
    ACCURACY_RTH_START_MIN: int = _RTH_START_MINS_AUTH
    ACCURACY_RTH_END_MIN: int = _RTH_END_MINS_AUTH

    def compute_accuracy(self, ticker: str, timeframe: str,
                          model_version: str = "statistical_v1",
                          *, rth_only: bool = False) -> dict:
        """
        Compute prediction accuracy for a given model version.
        Compares pred_Nc_up/down/flat_prob to actual outcome_Nc.

        rth_only (2026-07-06 operator decision): restrict to rows stamped inside
        RTH (09:30–16:00 ET). The model-accuracy audit measured SPY 5c at 40.1%
        all-hours but 34.5% RTH-only vs a 38.1% RTH majority baseline — the
        all-hours number flatters tradeable-session performance, so trading-facing
        surfaces read rth_only=True and keep all-hours as audit context only.

        Each horizon entry also carries the majority-class baseline of the SAME
        row set (baseline_pct / baseline_label / edge_vs_baseline_pp) so raw
        accuracy can never masquerade as edge, plus a scope stamp.
        """
        timeframe = require_snapshot_timeframe(timeframe, caller="EdDB.compute_accuracy")
        results = {}
        from ml_horizon import PRIMARY_DECISION_HORIZONS

        scope = "rth_0930_1600_et" if rth_only else "all_hours"
        rth_clause = ""
        if rth_only:
            rth_clause = (
                f" AND (et_hour * 60 + COALESCE(et_minute, 0)) >= {self.ACCURACY_RTH_START_MIN}"
                f" AND (et_hour * 60 + COALESCE(et_minute, 0)) < {self.ACCURACY_RTH_END_MIN} "
            )

        for horizon in PRIMARY_DECISION_HORIZONS:
            pred_col    = f"pred_{horizon}_up_prob"
            outcome_col = f"outcome_{horizon}"

            with self._connect() as conn:
                rows = conn.execute(f"""
                    SELECT {pred_col}, pred_{horizon}_down_prob,
                           pred_{horizon}_flat_prob, {outcome_col}
                    FROM snapshots
                    WHERE ticker = ?
                      AND timeframe = ?
                      AND pred_model_version = ?
                      AND {pred_col} IS NOT NULL
                      AND {outcome_col} IS NOT NULL
                      {rth_clause}
                """, (ticker, timeframe, model_version)).fetchall()

            if not rows:
                # Fail closed: no rows in scope -> accuracy None (consumers drop the
                # horizon); NEVER silently widen the scope to all-hours.
                results[horizon] = {"total": 0, "accuracy": None, "scope": scope}
                continue

            correct = 0
            scored = 0
            from numeric_contract import direction_from_normalized_triplet, float_finite_or_none
            outcome_counts: dict[str, int] = {}
            for row in rows:
                # RC-345 / F22: predicted direction = the ONE argmax authority
                # numeric_contract.direction_from_normalized_triplet (same up>down>flat
                # tie-break), not a local max(probs, key=...). A row whose pred triplet is
                # MISSING is SKIPPED — never scored as a fabricated 'up' via `or 0`.
                _pu = float_finite_or_none(row[f"pred_{horizon}_up_prob"])
                _pd = float_finite_or_none(row[f"pred_{horizon}_down_prob"])
                _pf = float_finite_or_none(row[f"pred_{horizon}_flat_prob"])
                if _pu is None or _pd is None or _pf is None:
                    continue
                predicted = direction_from_normalized_triplet(_pu, _pd, _pf)
                actual    = row[outcome_col]
                outcome_counts[actual] = outcome_counts.get(actual, 0) + 1
                scored += 1
                if predicted == actual:
                    correct += 1

            total    = scored  # only rows with a real predicted triplet are scored (F22)
            accuracy = round(correct / total * 100, 1) if total > 0 else None
            baseline_label = max(outcome_counts, key=outcome_counts.get) if outcome_counts else None
            baseline_pct = (round(outcome_counts[baseline_label] / total * 100, 1)
                            if (total > 0 and baseline_label is not None) else None)
            results[horizon] = {
                "total": total,
                "correct": correct,
                "accuracy": accuracy,
                "scope": scope,
                "baseline_pct": baseline_pct,
                "baseline_label": baseline_label,
                # accuracy and baseline_pct are both gated on the same total>0 check above
                # (baseline_pct also requires baseline_label, non-None whenever total>0 since
                # outcome_counts fills alongside scored) -- accuracy not-None implies
                # baseline_pct not-None, so this never silently substitutes for a real gap.
                "edge_vs_baseline_pp": (
                    round(accuracy - baseline_pct, 1) if accuracy is not None else None  # caps-ok: accuracy not-None implies baseline_pct not-None (both gated on total>0 above)
                ),
            }

        return results

    # Pass 5a: minimum delta between two persisted accuracy rows for the same
    # (ticker, timeframe, model_version, horizon). The accuracy_pct value
    # itself only changes when new outcomes land, so equality of the value
    # is the natural dedup signal — but small floating noise should not skip.
    MODEL_ACCURACY_DEDUP_EPSILON: float = 0.05  # percentage points

    def log_model_accuracy(
        self,
        *,
        ticker: str,
        timeframe: str,
        model_version: str,
        horizon: str,
        total_predictions: int,
        correct_direction: Optional[int],
        accuracy_pct: Optional[float],
        avg_confidence: Optional[float] = None,
        ts_utc: Optional[float] = None,
    ) -> int:
        """Pass 5a writer for model_accuracy.

        Schema (see db_schema.py): one row per accuracy snapshot per
        (ticker, timeframe, model_version, horizon, ts_utc). Caller is
        expected to dedup via get_latest_model_accuracy before INSERT
        (the accuracy value only changes when new outcomes land — natural
        throttle).
        """
        import db  # module-attribute access only -- see this file's own docstring

        ts = float(ts_utc) if ts_utc is not None else db.utc_ts()
        cd = int(correct_direction) if correct_direction is not None else None
        ap = float(accuracy_pct) if accuracy_pct is not None else None
        ac = float(avg_confidence) if avg_confidence is not None else None

        def _do() -> int:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO model_accuracy "
                    "(ts_utc, ticker, timeframe, model_version, horizon, "
                    " total_predictions, correct_direction, accuracy_pct, avg_confidence) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        ts, ticker, timeframe, model_version, horizon,
                        int(total_predictions), cd, ap, ac,
                    ),
                )
                return int(cur.lastrowid)

        return _do()

    def get_latest_model_accuracy(
        self,
        *,
        ticker: str,
        timeframe: str,
        model_version: str,
        horizon: str,
    ) -> Optional[dict]:
        """Pass 5a reader: latest row for (ticker, timeframe, model_version, horizon)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM model_accuracy "
                "WHERE ticker = ? AND timeframe = ? "
                "  AND model_version = ? AND horizon = ? "
                "ORDER BY ts_utc DESC LIMIT 1",
                (ticker, timeframe, model_version, horizon),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_model_accuracy_history(
        self,
        *,
        ticker: str,
        timeframe: str,
        model_version: str,
        horizon: str,
        limit: int = 50,
    ) -> list[dict]:
        """Pass 5a/5b reader: history of accuracy snapshots for chart / panel."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM model_accuracy "
                "WHERE ticker = ? AND timeframe = ? "
                "  AND model_version = ? AND horizon = ? "
                "ORDER BY ts_utc DESC LIMIT ?",
                (ticker, timeframe, model_version, horizon, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    def maybe_log_model_accuracy(
        self,
        *,
        ticker: str,
        timeframe: str,
        model_version: str,
        horizon: str,
        total_predictions: int,
        correct_direction: Optional[int],
        accuracy_pct: Optional[float],
        avg_confidence: Optional[float] = None,
        ts_utc: Optional[float] = None,
    ) -> Optional[int]:
        """Pass 5a throttled writer: log only when accuracy_pct meaningfully changed
        vs the latest persisted row for this (ticker, timeframe, model_version, horizon).

        Returns the new row id when logged, or None when skipped (dedup or input None).
        """
        if accuracy_pct is None:
            return None
        latest = self.get_latest_model_accuracy(
            ticker=ticker, timeframe=timeframe,
            model_version=model_version, horizon=horizon,
        )
        if latest is not None:
            prev = latest.get("accuracy_pct")   # external-key-ok: sqlite column from get_latest_model_accuracy()
            if prev is not None and abs(float(prev) - float(accuracy_pct)) < self.MODEL_ACCURACY_DEDUP_EPSILON:
                return None
        return self.log_model_accuracy(
            ticker=ticker, timeframe=timeframe, model_version=model_version,
            horizon=horizon, total_predictions=total_predictions,
            correct_direction=correct_direction, accuracy_pct=accuracy_pct,
            avg_confidence=avg_confidence, ts_utc=ts_utc,
        )
