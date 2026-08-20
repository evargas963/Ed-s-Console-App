# Live Schwab inventory — operator-host auth path (RC-438)

**Verdict (this cloud agent turn):** `CLOUD_SECRET_UNAVAILABLE` — **not** `TOKEN_FAILURE`.  
Live authenticated inventory **cannot** be completed in this environment. Stop here; switch to operator host (or Claude on host) to run the commands below.

## Auth path the working console uses (measured)

Same chain for `server.py`, `tools/sync_schwab_field_dictionary.py --poll`, `tools/probe_schwab_of_capability_rth.py`, and (via env/`build_config`) `schwab_full_field_inventory.py`:

1. `config.build_config(app_dir)` loads repo-root `.env` via dotenv (`override=False`).
2. Requires env `SCHWAB_API_KEY` + `SCHWAB_APP_SECRET` (from `.env` or process env).
3. Token path:
   - if `SCHWAB_TOKEN_PATH` set → `os.path.abspath(that)`
   - else → `os.path.abspath(os.path.join(app_dir, "schwab_token.json"))`
4. Client: `schwab_client.build_client_from_token(api_key, app_secret, token_path)`.

`start_ed_console.bat` sets `cd /d "%~dp0"` so `app_dir` = the Ed Console install root; default token is therefore **`<console_root>/schwab_token.json`**.

### Cloud measurement (this turn)

| Check | Result |
|---|---|
| `cfg.token_path` | `/workspace/schwab_token.json` |
| Token file exists | **False** |
| `SCHWAB_TOKEN_PATH` | unset |
| Repo `.env` | absent |
| `inspect_token_file` | `Token file not found at '/workspace/schwab_token.json'` |
| One `--poll` attempt (`ED_CI_OFFLINE` cleared) | `RuntimeError: Schwab client unavailable: Token file not found: /workspace/schwab_token.json` |

Classification: **`CLOUD_SECRET_UNAVAILABLE`**. Do not reauth, copy, or recreate the token from cloud. Host already authenticates the running console.

## Tool roles (do not substitute schema-only refresh)

| Tool | Live? | Surface |
|---|---|---|
| `python tools/sync_schwab_field_dictionary.py --poll` | Yes | **REST-only** — quotes, chains, pricehistory, market_hours, instruments, movers. Union-merges into `schwab_field_inventory/schwab_field_dictionary.csv`. **No Level One / BOOK stream.** |
| `python schwab_full_field_inventory.py` | Yes | REST + streaming sample (`ENABLE_STREAMING=True`): LEVEL_ONE_EQUITY, NASDAQ_BOOK, CHART_EQUITY. Writes under `schwab_field_inventory/`. |
| `python tools/probe_schwab_of_capability_rth.py ...` | Yes | **Streaming OF probe** — NYSE_BOOK + NASDAQ_BOOK (+ OPTIONS_BOOK / TIMESALE / optional LEVELONE_OPTIONS). Raw numeric + schwab-py-decoded side-by-side. |
| `python tools/refresh_schwab_native_field_inventory.py` | No | schwab-py **schema/definition** only — **not** a live authenticated read. |

## Single-streamer-owner — must stop console streamer for live stream inventory

Schwab allows **one** active streamer session per account. Confirmed in-repo:

- Console owns the socket via `order_flow_streaming` (started from `server.py` lifespan).
- `tools/run_stream_capture.py` takes `data/stream_capture.lock`.
- Probe manifest note: do **not** run alongside `order_flow_streaming` or `run_stream_capture`.

**Required before streaming inventory/probe:**

1. Stop Ed Console (Ctrl+C on the uvicorn window / stop the process bound to port 8000), **or** otherwise ensure `order_flow_streaming` is not logged in.
2. Ensure no `run_stream_capture` / other StreamClient process is running.
3. Then run `schwab_full_field_inventory.py` and/or `probe_schwab_of_capability_rth.py`.

REST-only `--poll` does **not** need the streamer stopped (no websocket login).

## Exact host commands (reuse console auth — no token surgery)

Run from the **same directory** as the working console (the folder that already contains `schwab_token.json` and `.env`). Prefer the console venv/Python if that is what uvicorn uses.

```bat
cd /d <console_root>
REM Optional prove of auth path (should print absolute path to existing schwab_token.json):
python -c "from pathlib import Path; from config import build_config; from schwab_client import inspect_token_file; c=build_config(str(Path('.').resolve())); i=inspect_token_file(c.token_path); print(c.token_path, i.file_exists, i.message)"

REM === A) REST live dictionary sync (REST-ONLY) ===
python tools/sync_schwab_field_dictionary.py --poll

REM === B) Full REST + brief stream sample (stop console streamer first) ===
python schwab_full_field_inventory.py

REM === C) OF streaming capability probe — L1 books / OPTIONS_BOOK / TIMESALE (stop console streamer; prefer RTH) ===
python tools/probe_schwab_of_capability_rth.py --symbols SPY,QQQ,IWM --duration-sec 90 --with-levelone-options
```

Optional dry-run for REST only (no dictionary write):

```bat
python tools/sync_schwab_field_dictionary.py --poll --dry-run
```

After a successful host run, artifacts that prove the ask:

| Ask | Artifact |
|---|---|
| Live REST services / fields vs Aug-15 | `governance/artifacts/schwab_field_sync_state.json` + updated dictionary `last_seen` |
| Live stream services / native fields | `schwab_field_inventory/streaming/` + `reports/of_capability_probe/<stamp>/` |
| vs schwab-py schema | compare probe/inventory leaves to `schwab_field_inventory/schwab_native_schema_inventory_v1.json` |
| Console uses / discards / persists / ignores | `reports/of_schwab_capability_universe_map_v1.json` (code-map; refresh after live if needed) |

## What this turn does **not** claim

Any table of “which Schwab services are observed live from your authenticated account” in **this** cloud turn would be fabricated. Prior observed REST sync remains **2026-08-15**. Streaming live proof remains **host-owed**.

## Halt

No further cloud auth loops. Technical blocker = missing operator token file in the cloud workspace (`CLOUD_SECRET_UNAVAILABLE`).
