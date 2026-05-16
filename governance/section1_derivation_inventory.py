"""
Section 1 Schwab-leaf derivation audit inventory (source of truth for tests).

One inventory row per module-level function (public and private).
Disposition: REPLACED | KEEP_DERIVED | PASS_THROUGH | NONE
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DerivationRecord:
    file: str
    line: str
    derivation: str
    schwab_leaf: str
    disposition: str
    justification: str


SECTION1_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (

    DerivationRecord("schwab_client.py", "30", "_schwab_oauth_scope", "—", "NONE", "OAuth scope string from env; no market field."),
    DerivationRecord("schwab_client.py", "35", "_get_auth_context_with_scope", "—", "NONE", "OAuth authorize URL helper; transport only."),
    DerivationRecord("schwab_client.py", "76", "_utc_ts", "—", "NONE", "Diagnostic filename timestamp."),
    DerivationRecord("schwab_client.py", "80", "ensure_dir", "—", "NONE", "Filesystem helper."),
    DerivationRecord("schwab_client.py", "84", "save_diag", "—", "NONE", "Writes diagnostic JSON; no market derivation."),
    DerivationRecord("schwab_client.py", "93", "_resolve_token_path", "—", "NONE", "Absolute token path normalization."),
    DerivationRecord("schwab_client.py", "98", "inspect_token_file", "—", "NONE", "Token metadata inspection; no quote fields."),
    DerivationRecord("schwab_client.py", "168", "auth_is_refreshable", "—", "NONE", "Token refresh capability check."),
    DerivationRecord("schwab_client.py", "173", "build_client_from_token", "—", "PASS_THROUGH", "Constructs schwab-py client from token file."),
    DerivationRecord("schwab_client.py", "230", "_parse_callback_port", "—", "NONE", "OAuth callback port parse."),
    DerivationRecord("schwab_client.py", "238", "_wait_for_callback_port", "—", "NONE", "OAuth callback wait loop."),
    DerivationRecord("schwab_client.py", "251", "run_login_flow", "—", "NONE", "Interactive OAuth login; no market data."),
    DerivationRecord("schwab_client.py", "301", "run_manual_flow", "—", "NONE", "Manual OAuth URL flow."),
    DerivationRecord("schwab_client.py", "324", "_is_token_error", "—", "NONE", "Classifies auth errors for retry."),
    DerivationRecord("schwab_client.py", "337", "safe_get_quote", "quotes.quote|extended|regular.*", "PASS_THROUGH", "Schwab get_quote wrapper; returns raw quote JSON."),
    DerivationRecord("schwab_client.py", "381", "safe_get_price_history", "pricehistory.candles.*", "PASS_THROUGH", "Schwab price history wrapper; candles passed downstream."),
    DerivationRecord("schwab_client.py", "421", "safe_get_chain", "chains.*", "PASS_THROUGH", "Schwab option chain wrapper."),
    DerivationRecord("reauth_schwab.py", "30", "reauth", "—", "NONE", "CLI OAuth reauth; no market-field reads."),
    DerivationRecord("websocket_adapter.py", "44", "websocket_bars_stub", "—", "NONE", "Unimplemented transport stub."),
    DerivationRecord("sse_adapter.py", "43", "sse_bars_stub", "—", "NONE", "Unimplemented transport stub."),
    DerivationRecord("polling_adapter.py", "22", "_prev_trading_day", "—", "KEEP_DERIVED", "Calendar helper for session window; no Schwab leaf."),
    DerivationRecord("polling_adapter.py", "30", "fetch_bars_via_schwab_for_session", "pricehistory.candles.*", "PASS_THROUGH", "Session-bounded pricehistory → schwab_candles_to_bars."),
    DerivationRecord("polling_adapter.py", "69", "fetch_bars_via_schwab", "pricehistory.candles.*", "PASS_THROUGH", "Day-period pricehistory → schwab_candles_to_bars."),
    DerivationRecord("polling_adapter.py", "121", "poll_and_callback", "pricehistory.candles.*", "PASS_THROUGH", "Poll loop delegates to fetch_bars_via_schwab."),
    DerivationRecord("market_data_adapter.py", "62", "normalize_bar", "pricehistory.candles.*", "REPLACED", "Schwab path requires datetime leaf; reject incomplete OHLC."),
    DerivationRecord("market_data_adapter.py", "139", "normalize_bars", "pricehistory.candles.*", "PASS_THROUGH", "Batch normalize_bar."),
    DerivationRecord("market_data_adapter.py", "154", "schwab_candles_to_bars", "pricehistory.candles.*", "PASS_THROUGH", "Schwab JSON candles → normalized bars + _ts."),
    DerivationRecord("snapshot_normalizer.py", "54", "_connect", "—", "NONE", "SQLite connection helper."),
    DerivationRecord("snapshot_normalizer.py", "66", "_minute_bucket", "—", "KEEP_DERIVED", "int(ts_utc//60) bucket key."),
    DerivationRecord("snapshot_normalizer.py", "71", "_safe_float", "—", "NONE", "Parse helper."),
    DerivationRecord("snapshot_normalizer.py", "80", "resample_to_1m", "snapshots.* / pricehistory.candles.*", "KEEP_DERIVED", "Synthetic 1m from sub-minute rows; spot proxies tagged in missing_fields."),
    DerivationRecord("snapshot_normalizer.py", "217", "fetch_raw_subminute_rows", "snapshots.*", "PASS_THROUGH", "Reads legacy 5m snapshot rows from DB."),
    DerivationRecord("snapshot_normalizer.py", "228", "resolve_source_timeframe", "snapshots.timeframe", "PASS_THROUGH", "Selects 1m vs 5m source timeframe."),
    DerivationRecord("snapshot_normalizer.py", "243", "fetch_rows_for_normalization", "snapshots.*", "PASS_THROUGH", "Loads rows for normalization pipeline."),
    DerivationRecord("snapshot_normalizer.py", "255", "normalize_ticker", "snapshots.*", "PASS_THROUGH", "Per-ticker normalize entrypoint."),
    DerivationRecord("snapshot_normalizer.py", "266", "_normalized_table_exists", "—", "NONE", "Schema guard."),
    DerivationRecord("snapshot_normalizer.py", "273", "_get_snapshots_columns", "—", "NONE", "PRAGMA column list."),
    DerivationRecord("snapshot_normalizer.py", "279", "_table_column_set", "—", "NONE", "PRAGMA table columns."),
    DerivationRecord("snapshot_normalizer.py", "284", "_normalized_insert_columns", "—", "NONE", "INSERT column alignment."),
    DerivationRecord("snapshot_normalizer.py", "299", "materialize_normalized_table", "snapshots.*", "KEEP_DERIVED", "Persists resampled rows; derived table not Schwab native 1m."),
    DerivationRecord("snapshot_normalizer.py", "386", "clear_normalized_table", "—", "NONE", "DELETE helper."),
    DerivationRecord("snapshot_normalizer.py", "397", "validate_normalization", "—", "NONE", "DB integrity checks on normalized table."),
    DerivationRecord("snapshot_normalizer.py", "492", "load_normalized_rows", "snapshots_1m_normalized.*", "PASS_THROUGH", "Read normalized rows for training."),
    DerivationRecord("snapshot_normalizer.py", "517", "run_full_materialization", "—", "NONE", "CLI orchestration materialize+validate."),
    DerivationRecord("snapshot_normalizer.py", "539", "_print_ingestion_context", "—", "NONE", "Diagnostic print helper."),
    DerivationRecord("snapshot_access.py", "31", "require_snapshot_timeframe", "snapshots.timeframe", "PASS_THROUGH", "Enforces explicit timeframe on snapshot SQL reads."),
    DerivationRecord("snapshot_access.py", "50", "is_canonical_timeframe", "snapshots.timeframe", "NONE", "Compares to CANONICAL_TIMEFRAME constant."),
)

SECTION1_FILES = frozenset({
    "market_data_adapter.py",
    "polling_adapter.py",
    "reauth_schwab.py",
    "schwab_client.py",
    "snapshot_access.py",
    "snapshot_normalizer.py",
    "sse_adapter.py",
    "websocket_adapter.py",
})

