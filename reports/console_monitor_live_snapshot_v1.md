# Console monitor live snapshot v1

**Captured:** 2026-08-02 ~16:46 America/Chicago local (Sunday)  
**Mode:** read-only / passive — no process signals, no uvicorn restart, no product-code edits.

## 1. Which console is scrolling?

**Verdict: EXTERNAL Windows cmd/conhost — NOT mirrored into Cursor terminals.**

| Role | PID | Parent | Notes |
|------|-----|--------|-------|
| Live uvicorn :8000 | **31344** `python.exe` | **21172** `cmd.exe` | `python -m uvicorn server:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 10` |
| cmd launcher | **21172** | 14788 | `cmd.exe /c "...\start_ed_console.bat"` — **MainWindowTitle empty**; owns **conhost 28728** |
| Live uvicorn :8777 | **21748** `python.exe` | **16412** `claude.exe` | Claude-spawned; title on Claude app window, not a classic scrolling cmd |
| Historical Cursor capture | terminals/`151702.txt` | (dead) | Prior Cursor uvicorn on :8000; **status failed**; last write **2026-08-02 10:57:36**; size **1,582,282** bytes; **growth delta 0** when rechecked |

Operator “command window” scrolling with warnings/tracebacks almost certainly = **cmd 21172 + conhost 28728** hosting uvicorn **31344**. Stdout is not FileHandler-backed into Cursor; attaching/hijacking that console would interrupt Claude’s work → **not done**.

No currently growing Cursor terminal file was found that contains a live uvicorn stream for PID 31344.

## 2. Limitation (external console buffer)

Without interrupting the live servers, this monitor **cannot read the external console scrollback buffer**. Windows does not expose conhost text to other processes without debugger/attach or restart-with-tee.

**What we can see instead:**
- Process aliveness / command lines (above)
- Stale historical uvicorn stdout in `terminals/151702.txt` (ended ~10:57 AM, exit_code 4294967295)
- Light HTTP health (below)

## 3. Historical Cursor capture (`151702.txt`) — grepped

**File not updating** — useful only as prior-session symptomology that may still match what the operator sees live.

### Pattern counts (Select-String SimpleMatch)

| Pattern | Count |
|---------|------:|
| Traceback | 131 |
| ERROR | 136 |
| WARNING | 1138 |
| Exception | 0 |
| CRITICAL | 0 |

### Top clusters (normalized signatures)

1. **sklearn InconsistentVersionWarning** (LogisticRegression pickle version mismatch) — ~155
2. **sqlite3.DatabaseError: database disk image is malformed** — Traceback ×131 + related WARNINGs for SPY/QQQ/IWM/PLTR XGBoost / `build_xgb_pre_engineering_snapshot_for_tick`
3. **SnapshotRow field drift** dropping `charm_expiry`, `charm_scope` — ~135
4. **sqlite_bg_write_slow** `fill_outcomes` (5s+/10s+) — dozens
5. **morning wide capture skipped** `non_trading_day` — expected on Sunday
6. Minor: XGBoost serialized-model warning; STREAM_CLIENT_LOGOUT_FAIL; PLTR active-bundle label_config_version mismatch

### Traceback shape (repeated)

```
signals._compute_signals_impl
  -> ml_predict.build_xgb_pre_engineering_snapshot_for_tick
  -> ml_data_common.attach_net_gamma_prev_for_dgex
  -> fetch_prior_net_gamma
  -> sqlite3.DatabaseError: database disk image is malformed
```

Last ~400 lines of `151702.txt` are almost entirely `INFO` HTTP 200 access logs (spot/forces/terrain/bars1m for QQQ/PLTR) then process end footer — the malformed-DB/traceback storm appears earlier in that capture, not at the very end.

## 4. Light HTTP probes (no stress; one-shot)

| Endpoint | Result |
|----------|--------|
| `GET http://127.0.0.1:8000/api/health` | **200** `{"status":"ok",...,"logger_running":true,"logger_tickers":40}` |
| `GET http://127.0.0.1:8000/api/forces?ticker=SPY` | **200** body len=520 |
| `GET http://127.0.0.1:8777/api/health` | **200** |

API surface answers OK while console may still be printing ML/DB warnings (unobserved live).

## 5. Operator options WITHOUT stopping Claude now

**Scrollback (existing window):**
1. Click the cmd window title bar → Properties → Layout → **Screen Buffer Height** (e.g. 9999) → OK.  
   Note: may only apply to *new* lines / new windows depending on Windows version; if Properties is greyed or won’t stick, use next options at next restart.
2. Right-click title bar → **Find** can search visible buffer only (limited).

**Next start (tee — do not do while Claude owns the live process):**
```bat
python -m uvicorn server:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 10 2>&1 | tee reports\uvicorn_console_tee_%DATE%.log
```
Or PowerShell:
```powershell
python -m uvicorn server:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 10 *>&1 |
  Tee-Object -FilePath reports\uvicorn_console_tee.log
```
Prefer starting from a Cursor terminal next time so the terminals folder captures the stream automatically.

**Do not now:** kill/restart 31344/21748, edit `server.py`/`static`, bind ports, or attach debugger to conhost.

## 6. Background watcher

Started: append-only `reports/console_monitor_tail.jsonl` every **60s** for up to **~15 minutes**.

- If any Cursor terminal file grows with Traceback|ERROR|WARNING|Exception lines → append those new matching lines (metadata + sample).
- Else → heartbeat: PIDs 31344/21748/21172 still alive + optional single `/api/health` ping.

Never restarts anything.

