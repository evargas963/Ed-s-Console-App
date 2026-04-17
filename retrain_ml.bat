@echo off
echo ============================================================
echo   ED CONSOLE — ML RETRAIN
echo ============================================================
echo.
echo   1. Materialize normalized 1m data (if using historical 5m snapshots)
echo   2. Retrain XGBoost from snapshots_1m_normalized
echo   3. Model approved only if it beats baseline by 3+ pct
echo.
pause

echo [1/2] Materializing normalized 1m data...
python snapshot_normalizer.py
if errorlevel 1 (
    echo WARN: Normalization had issues. Check output.
) else (
    echo Normalization OK.
)

echo.
echo [2/2] Training XGBoost...
python ml_train.py --db data/ed_console.db

echo.
echo ============================================================
echo   DONE — check the summary above.
echo   If APPROVED, the model is live on next server restart.
echo   If NOT APPROVED, rules engine continues running.
echo ============================================================
echo.
pause
