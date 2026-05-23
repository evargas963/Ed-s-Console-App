> **Classification:** Operational Ledger | **Scope:** Model restore/promotion event log.

# MODEL_RESTORE_LOG

**Pre-overwrite backup directory:** `models/active/.restore_backup_20260430T053742Z`

## Summary

- **Total files copied:** 86
- **Error count:** 0

## Verification (each copied file)

For each row below: destination exists under `models/active/`, source still exists under archive, size > 0, dst size == src size.

### $SPX

- **status:** MISSING_ARCHIVE
- **source:** ``
- **note:** MISSING_ARCHIVE: directory only; no archive in plan

### AAPL

- **status:** SUCCESS
- **source:** `models\_artifact_archive\parallel\AAPL\20260416T211940Z`
- **files_copied:** xgb_AAPL_1c.pkl, xgb_AAPL_1c_meta.json, lstm_AAPL_1c.pt, lstm_AAPL_1c_meta.json, transformer_AAPL_1c.pt, transformer_AAPL_1c_meta.json, meta_AAPL_1c.pkl
- **note:** run_id=20260416T211940Z
- **VERIFY xgb_AAPL_1c.pkl:** OK (archive_bytes=144130, active_bytes=144130)
- **VERIFY xgb_AAPL_1c_meta.json:** OK (archive_bytes=26319, active_bytes=26319)
- **VERIFY lstm_AAPL_1c.pt:** OK (archive_bytes=292269, active_bytes=292269)
- **VERIFY lstm_AAPL_1c_meta.json:** OK (archive_bytes=1386, active_bytes=1386)
- **VERIFY transformer_AAPL_1c.pt:** OK (archive_bytes=302466, active_bytes=302466)
- **VERIFY transformer_AAPL_1c_meta.json:** OK (archive_bytes=1071, active_bytes=1071)
- **VERIFY meta_AAPL_1c.pkl:** OK (archive_bytes=946, active_bytes=946)

### AMZN

- **status:** SUCCESS
- **source:** `models\_artifact_archive\parallel\AMZN\20260416T215758Z`
- **files_copied:** xgb_AMZN_1c.pkl, xgb_AMZN_1c_meta.json, lstm_AMZN_1c.pt, lstm_AMZN_1c_meta.json, transformer_AMZN_1c.pt, transformer_AMZN_1c_meta.json, meta_AMZN_1c.pkl
- **note:** run_id=20260416T215758Z
- **VERIFY xgb_AMZN_1c.pkl:** OK (archive_bytes=145763, active_bytes=145763)
- **VERIFY xgb_AMZN_1c_meta.json:** OK (archive_bytes=26316, active_bytes=26316)
- **VERIFY lstm_AMZN_1c.pt:** OK (archive_bytes=292269, active_bytes=292269)
- **VERIFY lstm_AMZN_1c_meta.json:** OK (archive_bytes=1386, active_bytes=1386)
- **VERIFY transformer_AMZN_1c.pt:** OK (archive_bytes=302466, active_bytes=302466)
- **VERIFY transformer_AMZN_1c_meta.json:** OK (archive_bytes=1071, active_bytes=1071)
- **VERIFY meta_AMZN_1c.pkl:** OK (archive_bytes=946, active_bytes=946)

### AVGO

- **status:** SUCCESS
- **source:** `models\_artifact_archive\parallel\AVGO\20260416T223129Z`
- **files_copied:** xgb_AVGO_1c.pkl, xgb_AVGO_1c_meta.json, lstm_AVGO_1c.pt, lstm_AVGO_1c_meta.json, transformer_AVGO_1c.pt, transformer_AVGO_1c_meta.json, meta_AVGO_1c.pkl
- **note:** run_id=20260416T223129Z
- **VERIFY xgb_AVGO_1c.pkl:** OK (archive_bytes=147808, active_bytes=147808)
- **VERIFY xgb_AVGO_1c_meta.json:** OK (archive_bytes=26228, active_bytes=26228)
- **VERIFY lstm_AVGO_1c.pt:** OK (archive_bytes=292269, active_bytes=292269)
- **VERIFY lstm_AVGO_1c_meta.json:** OK (archive_bytes=1386, active_bytes=1386)
- **VERIFY transformer_AVGO_1c.pt:** OK (archive_bytes=302466, active_bytes=302466)
- **VERIFY transformer_AVGO_1c_meta.json:** OK (archive_bytes=1071, active_bytes=1071)
- **VERIFY meta_AVGO_1c.pkl:** OK (archive_bytes=946, active_bytes=946)

### CIFR

- **status:** SUCCESS
- **source:** `models\_artifact_archive\parallel\CIFR\20260416T230157Z`
- **files_copied:** xgb_CIFR_1c.pkl, xgb_CIFR_1c_meta.json, lstm_CIFR_1c.pt, lstm_CIFR_1c_meta.json, transformer_CIFR_1c.pt, transformer_CIFR_1c_meta.json, meta_CIFR_1c.pkl
- **note:** run_id=20260416T230157Z
- **VERIFY xgb_CIFR_1c.pkl:** OK (archive_bytes=141337, active_bytes=141337)
- **VERIFY xgb_CIFR_1c_meta.json:** OK (archive_bytes=26373, active_bytes=26373)
- **VERIFY lstm_CIFR_1c.pt:** OK (archive_bytes=295405, active_bytes=295405)
- **VERIFY lstm_CIFR_1c_meta.json:** OK (archive_bytes=1270, active_bytes=1270)
- **VERIFY transformer_CIFR_1c.pt:** OK (archive_bytes=302466, active_bytes=302466)
- **VERIFY transformer_CIFR_1c_meta.json:** OK (archive_bytes=1071, active_bytes=1071)
- **VERIFY meta_CIFR_1c.pkl:** OK (archive_bytes=946, active_bytes=946)

### CRWD

- **status:** PARTIAL
- **source:** `models\_artifact_archive\parallel\CRWD\20260416T233824Z`
- **files_copied:** xgb_CRWD_1c.pkl, xgb_CRWD_1c_meta.json
- **missing_components:** lstm_CRWD_1c.pt, lstm_CRWD_1c_meta.json, transformer_CRWD_1c.pt, transformer_CRWD_1c_meta.json, meta_CRWD_1c.pkl
- **note:** Partial: XGB 1c only per MODEL_RECONSTRUCTION_PLAN.md
- **VERIFY xgb_CRWD_1c.pkl:** OK (archive_bytes=107931, active_bytes=107931)
- **VERIFY xgb_CRWD_1c_meta.json:** OK (archive_bytes=15449, active_bytes=15449)

### GOOGL

- **status:** SUCCESS
- **source:** `models\_artifact_archive\parallel\GOOGL\20260417T002204Z`
- **files_copied:** xgb_GOOGL_1c.pkl, xgb_GOOGL_1c_meta.json, lstm_GOOGL_1c.pt, lstm_GOOGL_1c_meta.json, transformer_GOOGL_1c.pt, transformer_GOOGL_1c_meta.json, meta_GOOGL_1c.pkl
- **note:** run_id=20260417T002204Z
- **VERIFY xgb_GOOGL_1c.pkl:** OK (archive_bytes=142555, active_bytes=142555)
- **VERIFY xgb_GOOGL_1c_meta.json:** OK (archive_bytes=26633, active_bytes=26633)
- **VERIFY lstm_GOOGL_1c.pt:** OK (archive_bytes=292297, active_bytes=292297)
- **VERIFY lstm_GOOGL_1c_meta.json:** OK (archive_bytes=1387, active_bytes=1387)
- **VERIFY transformer_GOOGL_1c.pt:** OK (archive_bytes=302503, active_bytes=302503)
- **VERIFY transformer_GOOGL_1c_meta.json:** OK (archive_bytes=1071, active_bytes=1071)
- **VERIFY meta_GOOGL_1c.pkl:** OK (archive_bytes=946, active_bytes=946)

### IWM

- **status:** SUCCESS
- **source:** `models\_artifact_archive\parallel\IWM\20260417T005614Z`
- **files_copied:** xgb_IWM_1c.pkl, xgb_IWM_1c_meta.json, lstm_IWM_1c.pt, lstm_IWM_1c_meta.json, transformer_IWM_1c.pt, transformer_IWM_1c_meta.json, meta_IWM_1c.pkl
- **note:** run_id=20260417T005614Z
- **VERIFY xgb_IWM_1c.pkl:** OK (archive_bytes=141748, active_bytes=141748)
- **VERIFY xgb_IWM_1c_meta.json:** OK (archive_bytes=26026, active_bytes=26026)
- **VERIFY lstm_IWM_1c.pt:** OK (archive_bytes=293329, active_bytes=293329)
- **VERIFY lstm_IWM_1c_meta.json:** OK (archive_bytes=1358, active_bytes=1358)
- **VERIFY transformer_IWM_1c.pt:** OK (archive_bytes=302429, active_bytes=302429)
- **VERIFY transformer_IWM_1c_meta.json:** OK (archive_bytes=1070, active_bytes=1070)
- **VERIFY meta_IWM_1c.pkl:** OK (archive_bytes=946, active_bytes=946)

### META

- **status:** SUCCESS
- **source:** `models\_artifact_archive\parallel\META\20260417T014739Z`
- **files_copied:** xgb_META_1c.pkl, xgb_META_1c_meta.json, lstm_META_1c.pt, lstm_META_1c_meta.json, transformer_META_1c.pt, transformer_META_1c_meta.json, meta_META_1c.pkl
- **note:** run_id=20260417T014739Z
- **VERIFY xgb_META_1c.pkl:** OK (archive_bytes=148973, active_bytes=148973)
- **VERIFY xgb_META_1c_meta.json:** OK (archive_bytes=26235, active_bytes=26235)
- **VERIFY lstm_META_1c.pt:** OK (archive_bytes=292269, active_bytes=292269)
- **VERIFY lstm_META_1c_meta.json:** OK (archive_bytes=1386, active_bytes=1386)
- **VERIFY transformer_META_1c.pt:** OK (archive_bytes=302466, active_bytes=302466)
- **VERIFY transformer_META_1c_meta.json:** OK (archive_bytes=1070, active_bytes=1070)
- **VERIFY meta_META_1c.pkl:** OK (archive_bytes=946, active_bytes=946)

### MSFT

- **status:** SUCCESS
- **source:** `models\_artifact_archive\parallel\MSFT\20260417T025209Z`
- **files_copied:** xgb_MSFT_1c.pkl, xgb_MSFT_1c_meta.json, lstm_MSFT_1c.pt, lstm_MSFT_1c_meta.json, transformer_MSFT_1c.pt, transformer_MSFT_1c_meta.json, meta_MSFT_1c.pkl
- **note:** run_id=20260417T025209Z
- **VERIFY xgb_MSFT_1c.pkl:** OK (archive_bytes=143304, active_bytes=143304)
- **VERIFY xgb_MSFT_1c_meta.json:** OK (archive_bytes=26339, active_bytes=26339)
- **VERIFY lstm_MSFT_1c.pt:** OK (archive_bytes=292269, active_bytes=292269)
- **VERIFY lstm_MSFT_1c_meta.json:** OK (archive_bytes=1384, active_bytes=1384)
- **VERIFY transformer_MSFT_1c.pt:** OK (archive_bytes=302466, active_bytes=302466)
- **VERIFY transformer_MSFT_1c_meta.json:** OK (archive_bytes=1071, active_bytes=1071)
- **VERIFY meta_MSFT_1c.pkl:** OK (archive_bytes=946, active_bytes=946)

### NVDA

- **status:** SUCCESS
- **source:** `models\_artifact_archive\parallel\NVDA\20260417T034659Z`
- **files_copied:** xgb_NVDA_1c.pkl, xgb_NVDA_1c_meta.json, lstm_NVDA_1c.pt, lstm_NVDA_1c_meta.json, transformer_NVDA_1c.pt, transformer_NVDA_1c_meta.json, meta_NVDA_1c.pkl
- **note:** run_id=20260417T034659Z
- **VERIFY xgb_NVDA_1c.pkl:** OK (archive_bytes=146243, active_bytes=146243)
- **VERIFY xgb_NVDA_1c_meta.json:** OK (archive_bytes=26665, active_bytes=26665)
- **VERIFY lstm_NVDA_1c.pt:** OK (archive_bytes=292269, active_bytes=292269)
- **VERIFY lstm_NVDA_1c_meta.json:** OK (archive_bytes=1386, active_bytes=1386)
- **VERIFY transformer_NVDA_1c.pt:** OK (archive_bytes=302466, active_bytes=302466)
- **VERIFY transformer_NVDA_1c_meta.json:** OK (archive_bytes=1070, active_bytes=1070)
- **VERIFY meta_NVDA_1c.pkl:** OK (archive_bytes=946, active_bytes=946)

### QQQ

- **status:** SUCCESS
- **source:** `models\_artifact_archive\parallel\QQQ\20260417T054357Z`
- **files_copied:** xgb_QQQ_1c.pkl, xgb_QQQ_1c_meta.json, lstm_QQQ_1c.pt, lstm_QQQ_1c_meta.json, transformer_QQQ_1c.pt, transformer_QQQ_1c_meta.json, meta_QQQ_1c.pkl
- **note:** run_id=20260417T054357Z
- **VERIFY xgb_QQQ_1c.pkl:** OK (archive_bytes=139969, active_bytes=139969)
- **VERIFY xgb_QQQ_1c_meta.json:** OK (archive_bytes=26262, active_bytes=26262)
- **VERIFY lstm_QQQ_1c.pt:** OK (archive_bytes=294865, active_bytes=294865)
- **VERIFY lstm_QQQ_1c_meta.json:** OK (archive_bytes=1300, active_bytes=1300)
- **VERIFY transformer_QQQ_1c.pt:** OK (archive_bytes=302429, active_bytes=302429)
- **VERIFY transformer_QQQ_1c_meta.json:** OK (archive_bytes=1070, active_bytes=1070)
- **VERIFY meta_QQQ_1c.pkl:** OK (archive_bytes=946, active_bytes=946)

### SPY

- **status:** SUCCESS
- **source:** `models\_artifact_archive\parallel\SPY\20260416T144038Z`
- **files_copied:** xgb_SPY_1c.pkl, xgb_SPY_1c_meta.json, lstm_SPY_1c.pt, lstm_SPY_1c_meta.json, transformer_SPY_1c.pt, transformer_SPY_1c_meta.json, meta_SPY_1c.pkl
- **note:** run_id=20260416T144038Z
- **VERIFY xgb_SPY_1c.pkl:** OK (archive_bytes=151501, active_bytes=151501)
- **VERIFY xgb_SPY_1c_meta.json:** OK (archive_bytes=26469, active_bytes=26469)
- **VERIFY lstm_SPY_1c.pt:** OK (archive_bytes=295377, active_bytes=295377)
- **VERIFY lstm_SPY_1c_meta.json:** OK (archive_bytes=1270, active_bytes=1270)
- **VERIFY transformer_SPY_1c.pt:** OK (archive_bytes=302429, active_bytes=302429)
- **VERIFY transformer_SPY_1c_meta.json:** OK (archive_bytes=1070, active_bytes=1070)
- **VERIFY meta_SPY_1c.pkl:** OK (archive_bytes=946, active_bytes=946)

### TSLA

- **status:** SUCCESS
- **source:** `models\_artifact_archive\parallel\TSLA\20260416T104002Z`
- **files_copied:** xgb_TSLA_1c.pkl, xgb_TSLA_1c_meta.json, lstm_TSLA_1c.pt, lstm_TSLA_1c_meta.json, transformer_TSLA_1c.pt, transformer_TSLA_1c_meta.json, meta_TSLA_1c.pkl
- **note:** run_id=20260416T104002Z
- **VERIFY xgb_TSLA_1c.pkl:** OK (archive_bytes=147330, active_bytes=147330)
- **VERIFY xgb_TSLA_1c_meta.json:** OK (archive_bytes=26288, active_bytes=26288)
- **VERIFY lstm_TSLA_1c.pt:** OK (archive_bytes=293357, active_bytes=293357)
- **VERIFY lstm_TSLA_1c_meta.json:** OK (archive_bytes=1360, active_bytes=1360)
- **VERIFY transformer_TSLA_1c.pt:** OK (archive_bytes=302466, active_bytes=302466)
- **VERIFY transformer_TSLA_1c_meta.json:** OK (archive_bytes=1071, active_bytes=1071)
- **VERIFY meta_TSLA_1c.pkl:** OK (archive_bytes=946, active_bytes=946)
