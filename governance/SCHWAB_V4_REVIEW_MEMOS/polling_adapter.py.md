> **Classification:** Policy Specification | **Scope:** Governance documentation `polling_adapter.py.md`.

# Review memo — polling_adapter.py

**Status:** pending gatekeeper review
**Date:** 2026-05-24
**Reviewer:** Claude (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)
**File language family:** python
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)**

**Closest-shape precedent** (per `AGENTS.md` Posture rules — sibling-pattern conformance, 2026-05-24): `market_data_adapter.py.md` S1 — `schwab_candles_to_bars` is the **immediate downstream consumer** that this file's two fetch functions hand the `payload["candles"]` array to. Mixed-disposition shape (NOT_MARKET_DATA for request-side / HTTP boilerplate, REPLACED for the `"candles"` subscript). The `enum→raw-kwargs` fallback at L109–120 matches `schwab_client.py.md` S3 (`schwab-py` API-version compatibility plumbing).

---

## Audit methodology (clause 4 — attribute / call / subscript)

Audited **this file** for:

| Channel | Method |
|---------|--------|
| String-literal dict access | `payload["candles"]` (L73, L130), `"candles" not in payload` (L69, L126) |
| Bracket dict access on Schwab payloads | The `payload["candles"]` reads above |
| Attribute access on market-bearing objects | `resp.status_code` (L65, L66, L122, L123), `resp.json()` (L68, L125) — HTTP envelope, not Schwab market wire |
| Method calls passing Schwab market objects | `schwab_candles_to_bars(candles)` (L74, L131) — delegation to `market_data_adapter` per-bar parsing |
| Schwab `schwab-py` client method calls | `client.get_price_history(...)` (L52–61, L101–108, L111–118) — three call sites across S2 / S3 |

**Review complete:** Every site **in this file** falls under **S1–S4** below; no other Schwab `example_raw_field` tokens or chain JSON subscripts occur in `polling_adapter.py`.

---

## Market-data sites identified

### S1 — `_prev_trading_day` (date arithmetic helper)

- **lines:** L25–30
- **surface:** `d - timedelta(days=1)`, `out.weekday() >= 5`, `out -= timedelta(days=1)`. Python `datetime.date` arithmetic only.
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — pure date arithmetic; no Schwab JSON keys, no API call.
- **evidence:** Function body reads only `date` / `timedelta` Python stdlib types. No tokens match any row in `schwab_field_inventory/schwab_field_dictionary.csv`.
- **code edit:** none.

### S2 — `fetch_bars_via_schwab_for_session` (REST session-window producer + `candles` subscript)

- **lines:** L33–74. Session window construction L45–47 (`prev_date = _prev_trading_day(session_date)`, `start_dt = datetime.combine(prev_date, time(0, 0), tzinfo=ET)`, `end_dt = datetime.combine(session_date, time(16, 0), tzinfo=ET)`). Schwab API call L49–61. HTTP envelope checks L65–66. JSON parse + `candles` subscript L68–74.
- **surface:**
  - **Request side (L50–61, L65–66, L68):** `client.get_price_history(symbol, period_type=None, period=None, frequency_type=PH.FrequencyType.MINUTE, frequency=PH.Frequency.EVERY_MINUTE, start_datetime=start_dt, end_datetime=end_dt, need_extended_hours_data=include_extended_hours)`; `resp.status_code`; `resp.json()`. **No Schwab market-field tokens read** at request side or HTTP envelope.
  - **Response subscript (L69–73):** `if "candles" not in payload: raise ValueError(...)`; `candles = payload["candles"]`. **This is a Schwab JSON key read** — the literal `"candles"` matches `schwab_field_inventory/schwab_field_dictionary.csv` row L2224 (`pricehistory.candles`, source_endpoints=`pricehistory`, example_raw_field=`candles`).
  - **Delegation (L74):** `return schwab_candles_to_bars(candles)` — per-bar field parsing (`c["open"]`, `c["close"]`, `c["high"]`, `c["low"]`, `c["volume"]`, `c.get("datetime")`) occurs in `market_data_adapter.schwab_candles_to_bars` (`market_data_adapter.py.md` S1 L118–147).
- **proposed disposition:**
  - **Request-side + HTTP envelope (L50–68):** **NOT_MARKET_DATA** at Schwab wire-token layer — `schwab-py` request parameters and HTTP response envelope; no Schwab market-field JSON keys read here.
  - **Response subscript `"candles"` (L69, L73):** **REPLACED** — canonical_field `pricehistory.candles`.
  - **Delegation to `schwab_candles_to_bars` (L74):** **NOT_MARKET_DATA** in this file — per-bar leaf disposition lives in `market_data_adapter.py.md` S1.
- **provenance trace (clause 4):** `fetch_bars_via_schwab_for_session` is called from `server.py` per `server.py.md` S27 ("Playbook session bars (`fetch_bars_via_schwab_for_session`)" L6701–6703). Caller passes the `client` produced by `schwab_client.build_client_from_token` (see `schwab_client.py.md` S1). Response → `payload["candles"]` (this file) → `schwab_candles_to_bars(candles)` → leaf reads `pricehistory.candles.*.open / .high / .low / .close / .volume / .datetime` (dict rows L2224–2231) in `market_data_adapter`.
- **canonical_field:** `pricehistory.candles` (top-level array key; per-bar leaf citations belong to `market_data_adapter.py.md` S1).
- **code edit:** none — `"candles"` is the documented Schwab pricehistory response key; the `if "candles" not in payload` guard is fail-closed (raises `ValueError` with status code) rather than fabricating an empty array.

### S3 — `fetch_bars_via_schwab` (REST period-days producer + `candles` subscript + enum→raw-kwargs fallback)

- **lines:** L77–131. PH enum / period map L91–100. Enum-API call L101–108. Raw-kwargs fallback L109–120. HTTP envelope checks L122–123. JSON parse + `candles` subscript L125–131.
- **surface:**
  - **Request side, enum path (L91–108):** `period_map = {1: PH.Period.ONE_DAY, 2: PH.Period.TWO_DAYS, 3: PH.Period.THREE_DAYS, 5: PH.Period.FIVE_DAYS, 10: PH.Period.TEN_DAYS}.get(period_days, PH.Period.TWO_DAYS)`; `client.get_price_history(symbol, period_type=PH.PeriodType.DAY, period=period, frequency_type=PH.FrequencyType.MINUTE, frequency=PH.Frequency.EVERY_MINUTE, need_extended_hours_data=include_extended_hours)`. **No Schwab market-field tokens read.**
  - **Request side, raw-kwargs fallback (L109–120):** `client.get_price_history(symbol, periodType="day", period=period_days, frequencyType="minute", frequency=1, needExtendedHoursData=include_extended_hours)`. Same Schwab endpoint, camelCase parameter form for older `schwab-py` releases. **No Schwab market-field tokens read.**
  - **HTTP envelope (L122–125):** `resp.status_code`, `resp.json()`. **NOT_MARKET_DATA.**
  - **Response subscript (L126–130):** `if "candles" not in payload: raise ValueError(...)`; `candles = payload["candles"]`. **Schwab JSON key read** — same row as S2 (`pricehistory.candles`, dict L2224).
  - **Delegation (L131):** `return schwab_candles_to_bars(candles)` — same delegation as S2.
- **proposed disposition:**
  - **Request-side + HTTP envelope (L91–125):** **NOT_MARKET_DATA** at Schwab wire-token layer (same reasoning as S2 request side).
  - **Response subscript `"candles"` (L126, L130):** **REPLACED** — canonical_field `pricehistory.candles`.
  - **Delegation to `schwab_candles_to_bars` (L131):** **NOT_MARKET_DATA** in this file.
- **provenance trace (clause 4):** `fetch_bars_via_schwab` is called by `poll_and_callback` (S4 L147 of this file). The `client` argument is the same `schwab-py` client produced by `schwab_client.build_client_from_token`. Response → `payload["candles"]` → `schwab_candles_to_bars` → per-bar leaves in `pricehistory.candles.*`.
- **canonical_field:** `pricehistory.candles` (same as S2).
- **enum→raw-kwargs fallback note (L109–120):** Matches the `schwab_client.py.md` S3 pattern for `safe_get_price_history` — `schwab-py` API-version compatibility plumbing, not a market-field substitution. Both branches call the same Schwab `/marketdata/v1/pricehistory` endpoint with the same parameter semantics. Difference vs. `safe_get_price_history`: this file does **not** swallow the `e_raw` exception to `None`; instead it re-raises as `ValueError` (L119–120). Fail-closed behavior is **stricter** here than in `safe_get_price_history` (which logs warning + returns `None`).
- **code edit:** none.

### S4 — `poll_and_callback` (background polling loop)

- **lines:** L134–152.
- **surface:** `import time` (L144); `while True:` loop (L145); `bars = fetch_bars_via_schwab(client, symbol)` (L147); `on_bars(bars)` callback dispatch (L148–149); exception swallow with debug log (L150–151); `time.sleep(interval_seconds)` (L152). **No Schwab JSON keys read.**
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — scheduling / dispatch loop; Schwab wire access is delegated to S3 (`fetch_bars_via_schwab`).
- **provenance trace (clause 4):** Wrapper for S3; same chain.
- **code edit:** none.

---

## Appendix A — NOT_MARKET_DATA clusters (wire-token layer)

Bulk **NOT_MARKET_DATA** at Schwab `example_raw_field` token layer: date arithmetic helper (S1 `_prev_trading_day`), the `schwab-py` request-parameter assembly across both fetch functions (PH enum maps, `period_type` / `frequency_type` / `start_datetime` / `end_datetime` / `need_extended_hours_data` kwargs), HTTP envelope inspection (`resp.status_code`, `resp.json()`), enum→raw-kwargs API-version fallback (same shape as `schwab_client.py.md` S3), background polling loop (S4 `poll_and_callback`), exception swallow + debug-log wiring, `from time_et import ET` for tzinfo, `BarCallback = Callable[[list[dict]], None]` type alias.

The single **REPLACED** disposition in this file is the `"candles"` top-level key read shared between S2 (L69, L73) and S3 (L126, L130). Per-bar leaf citations (`pricehistory.candles.*.open / .high / .low / .close / .volume / .datetime`, dict rows L2225–2231) belong to `market_data_adapter.py.md` S1 because `schwab_candles_to_bars` is where the per-candle dict subscription occurs.

This file's contribution to V4 closure is **establishing the BRANCH layer** (per `CLAUDE.md` SCHWAB FULL REPO directive) between `schwab_client.py` (LEAF producer wrapping `client.get_price_history`) and `market_data_adapter.py` (LEAF consumer parsing per-bar fields). It is the **only** site in the producer chain that subscripts the `"candles"` top-level array key — a real REPLACED row for the V4 register.

---

## Aggregate disposition for inventory

- **status:** pending (awaiting gatekeeper)
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/polling_adapter.py.md
