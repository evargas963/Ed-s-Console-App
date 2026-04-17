# Schwab Auth Hardening — Root Cause & Fix

## Root Cause

**Link vs manual launch**: When launching via shortcut, `Start in` (cwd) can differ from the app directory. The token path was built as `os.path.join(app_dir, "schwab_token.json")` where `app_dir = Path(__file__).parent.resolve()`. While `__file__` is typically absolute, `os.path.join` with a relative segment could produce inconsistent resolution in edge cases. Additionally:

1. **No absolute-path guarantee** — config did not force `os.path.abspath()` on the token path
2. **No env override** — no way to pin token location for launch-method debugging
3. **Stale client on token expiry** — global `_client` was never cleared; token errors produced raw 500s
4. **No retry** — `safe_get_quote` did not catch `InvalidTokenError` or retry after rebuild
5. **No startup validation** — auth issues discovered only on first `/api/state` call
6. **Opaque 500** — token errors returned generic 500 instead of structured auth payload

## Files Changed

| File | Change |
|------|--------|
| `config.py` | `build_config`: env `SCHWAB_TOKEN_PATH` override; token_path always `os.path.abspath()` |
| `schwab_client.py` | `_resolve_token_path`, `_is_token_error`, `safe_get_quote` with `refresh_client_fn` retry |
| `server.py` | `reset_schwab_client`, `get_client(force_refresh)`, `_safe_get_quote_with_retry`, startup diagnostics, startup auth validation, structured 401 on token error |
| `static/index.html` | Frontend shows `detail`/`remediation` for auth errors |
| `start_ed_console.bat` | Note about CWD and token resolution |

## Exact Diffs

### config.py
- Added `SCHWAB_TOKEN_PATH` env override; token_path always `os.path.abspath()`

### schwab_client.py
- `_resolve_token_path(token_path)` — normalizes to absolute
- `_is_token_error(exc)` — detects token-related exceptions
- `safe_get_quote(client, ticker, refresh_client_fn=None)` — on token error, calls `refresh_client_fn()`, retries once with new client
- `build_client_from_token` — uses `_resolve_token_path` before `os.path.exists`

### server.py
- `_log_schwab_startup_diagnostics()` — logs cwd, token_path, token_exists, python exe
- `reset_schwab_client()` — clears `_client`
- `get_client(force_refresh=False)` — when `force_refresh`, clears cache and rebuilds
- `_safe_get_quote_with_retry(client, ticker)` — wraps `safe_get_quote` with `refresh_client_fn=lambda: get_client(force_refresh=True)`
- Lifespan: calls `_log_schwab_startup_diagnostics()`, then lightweight auth validation (build client, SPY quote)
- `/api/state`: catches token errors, returns 401 with `{error, detail, message, remediation}`

## Resolved Token Path Behavior

- **Config**: `build_config(app_dir)` sets `token_path`:
  - If `SCHWAB_TOKEN_PATH` env set → `os.path.abspath(env_value)`
  - Else → `os.path.abspath(os.path.join(app_dir, "schwab_token.json"))`
- **Client**: `build_client_from_token` uses `_resolve_token_path(token_path)` before `os.path.exists` and `auth.client_from_token_file`
- **Result**: Same absolute path used regardless of cwd or launch method

## Retry / Rebuild Logic

1. `safe_get_quote(client, ticker, refresh_client_fn=...)` catches exception
2. If `_is_token_error(exc)` and `refresh_client_fn` provided:
   - Call `new_client = refresh_client_fn()` (server passes `lambda: get_client(force_refresh=True)`)
   - Retry `new_client.get_quote(ticker)`
3. If retry fails, raise (caller handles)
4. Server `/api/state` catches token errors, returns structured 401

## Startup Diagnostics

At app startup (lifespan):
1. `_log_schwab_startup_diagnostics()` — logs: `cwd`, `token_path`, `token_exists`, `python` exe
2. Lightweight auth check: build client, call `client.get_quote("SPY")`; on token error log remediation
3. If token file missing: log error with `SCHWAB_TOKEN_PATH` and `reauth_schwab.py` guidance

## Closure Audit

| Check | Result |
|-------|--------|
| Token path absolute | ✓ `config.build_config` + `schwab_client._resolve_token_path` |
| Env override | ✓ `SCHWAB_TOKEN_PATH` |
| Centralized client creation | ✓ `build_client_from_token` in schwab_client |
| Retry on token error | ✓ `safe_get_quote` + `refresh_client_fn` |
| Client refreshable | ✓ `get_client(force_refresh=True)` |
| Startup verification | ✓ Diagnostics + auth validation in lifespan |
| Structured auth error | ✓ 401 with `{error, detail, message, remediation}` |
| Frontend surfaces auth | ✓ Uses `detail`/`remediation` in error display |
| Launch diagnostics | ✓ cwd, token_path, token_exists logged |
