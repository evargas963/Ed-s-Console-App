-- Staging table for canonical 1m bars before merge into price_bars_1m.
-- Safe to run once per DB; does NOT modify price_bars_1m.

CREATE TABLE IF NOT EXISTS price_bars_1m_staging (
    batch_id           TEXT    NOT NULL,
    ticker             TEXT    NOT NULL,
    bar_start_ts_utc   REAL    NOT NULL,
    bar_end_ts_utc     REAL    NOT NULL,
    open               REAL,
    high               REAL,
    low                REAL,
    close              REAL    NOT NULL,
    volume             REAL,
    source             TEXT    NOT NULL,
    ingested_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (batch_id, ticker, bar_start_ts_utc)
);

CREATE INDEX IF NOT EXISTS idx_pb1m_staging_ticker_start
    ON price_bars_1m_staging (ticker, bar_start_ts_utc);

CREATE INDEX IF NOT EXISTS idx_pb1m_staging_batch
    ON price_bars_1m_staging (batch_id);
