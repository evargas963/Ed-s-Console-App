> **Classification:** Policy Specification | **Scope:** Governance documentation `schwab_client.py.md`.

# Review memo — schwab_client.py

**Status:** pending gatekeeper review
**Date:** 2026-05-24
**Reviewer:** Claude (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)
**File language family:** python
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)**

---

---

## Gatekeeper CSV cross-check (retroactive @ 977e706, 2026-05-24)

**Tool:** \python tools/check_schwab_csv_first.py --gatekeeper-crosscheck schwab_client.py\n**lexical_csv_collision_count:** 0

Retroactive full-CSV AST cross-check. Prior memo dispositions unchanged; homonym collisions classified in original site sections. Zero new wire FIND from cross-check.

## Audit methodology (clause 4 — attribute / call / subscript)

Audited **this file** for:

| Channel | Method |
|---------|--------|
| String-literal dict access | All `.get("...")` / `obj["..."]` with string keys |
| Bracket dict access | None on Schwab payloads (this file does not subscript `q_json` / `c_json` / pricehistory) |
| Attribute access on market-bearing objects | None (only on `TokenInspectionResult` and OAuth token dicts) |
| Method calls passing Schwab market objects | `client.get_quote`, `client.get_price_history`, `client.get_option_chain` — **no** Schwab wire tokens are **read** at call boundary; the HTTP response object is returned to callers for downstream `.json()[...]` parsing |

This file is the **leaf adapter producer** for Schwab REST market-data fetches. It builds the `schwab-py` client and exposes three `safe_*` wrappers that return the **raw Schwab HTTP response** for downstream `.json()` consumption. **No Schwab market-field JSON key reads occur in this file** — all `q_json[...]` / `c_json[...]` / `resp.json()["candles"][i][...]` accesses occur in *consumer* files (`server.py`, `market_state.py`, `market_data_adapter.py`) and are dispositioned in those memos.

**Review complete:** Every site **in this file** falls under **S1–S4** below; no other Schwab `example_raw_field` tokens or chain JSON subscripts occur in `schwab_client.py`.

Same shape as `signals.py.md` (all S1–S12 there are NOT_MARKET_DATA at Schwab wire-token layer for the same reason — no in-file Schwab JSON subscripts).

---

## Market-data sites identified

### S1 — OAuth / token / login plumbing

- **lines:** L1–339 — imports L1–19; `InvalidTokenError` shim L23–26; `_DEFAULT_SCHWAB_OAUTH_SCOPE` L31; `_schwab_oauth_scope` L34–36; `_get_auth_context_with_scope` L39–50; `auth.get_auth_context` monkey-patch L53; `SchwabClientState` L56–60 and `TokenInspectionResult` L63–77; `_utc_ts` L80–81; `ensure_dir` L84–85; `save_diag` L88–94; `_resolve_token_path` L97–99; `inspect_token_file` L102–169; `auth_is_refreshable` L172–174; `build_client_from_token` L177–232; `_parse_callback_port` L234–239; `_wait_for_callback_port` L242–252; `run_login_flow` L255–302; `run_manual_flow` L305–326; `_is_token_error` L328–338.
- **surface:** Reads/writes the schwab-py token-file JSON keys `creation_timestamp`, `token`, `access_token`, `refresh_token`, `expires_at`, `scope`. Builds the Schwab `schwab-py` client via `auth.client_from_token_file` (L224–229), `auth.client_from_login_flow` (L264–271), `auth.client_from_manual_flow` (L311–317). Parses callback URL host/port. Classifies `InvalidTokenError` by class name and HTTP-401 / "token invalid|expired" substring (L328–338).
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer
- **evidence:** Token-file JSON is OAuth-2 credential material, not Schwab market-data wire payload. The literal keys (`access_token`, `refresh_token`, `expires_at`, `scope`, `creation_timestamp`, `token`) are **not** rows in `schwab_field_inventory/schwab_field_dictionary.csv` — that file catalogues `chains.*` (L2–158), `instruments.*` (L159–221), `market_hours.*` (L222–2212), `movers.*` (L2213–2223), `pricehistory.*` (L2224–2232), `quotes.*` (L2233–2307), `streaming.*` (L2308–2394), with no auth/token row family. REPLACED is **not** asserted on OAuth credential keys (same rule signals.py.md S3 applies to internal projection keys `"spot"` / `"price.spot"`).
- **code edit:** none.

### S2 — `safe_get_quote` (Schwab REST quotes endpoint producer)

- **lines:** L341–383 (primary call L355; refresh-retry call L373; `attempt_hook` invocations L349–353, L368–372; `api_pressure.record_schwab_http_response(resp, f"quote:{ticker}")` L357–361, L375–379).
- **surface:** `client.get_quote(ticker)` — returns the raw `schwab-py` HTTP response. **No Schwab JSON keys are subscripted in this file.**
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — payload **production / handoff**; Schwab wire parsing occurs in callers under `server.py` and `market_state.py` (separate file memos). Same pattern as `server.py.md` S16 (`fetch_price_levels(..., quote_raw=q_json)`): the site records payload handoff, not a wire-token subscript.
- **provenance trace (for audit only — clause 4):** Consumer chain — `server.py::_safe_get_quote_with_retry` → `safe_get_quote(client, tkr, …)` → `client.get_quote(ticker)` returns HTTP response → `q_resp.json()` in caller (`server.py:2957-2960` per `server.py.md` S3) → leaf reads under `quotes.quote.lastPrice` / `.bidPrice` / `.askPrice` / `.mark` / `.totalVolume` / `.quoteTime` / `.tradeTime`, `quotes.extended.*`, `quotes.regular.*`, `quotes.reference.*`, `quotes.fundamental.*` (dictionary rows L2233–2307). Per-leaf dispositions live in `server.py.md` S1/S2/S3/S5/S7/S10 and `market_state.py.md`.
- **canonical_field:** **N/A at this surface** — REPLACED is **not** asserted on payload-production sites that read zero Schwab JSON tokens in-file (consistent with `signals.py.md` S3 rule).
- **token-refresh retry note (L364–382):** The `if refresh_client_fn is not None and _is_token_error(e):` arm rebuilds the Schwab client and replays `new_client.get_quote(ticker)`. This is **OAuth-2 refresh-token resilience**, not a market-field substitution — the second call hits the same Schwab `/marketdata/v1/quotes` endpoint with refreshed credentials and returns the same response shape. Fail-closed: if refresh also raises, the original exception re-raises (`raise retry_e` L382, unconditional `raise` L383).
- **code edit:** none.

### S3 — `safe_get_price_history` (Schwab REST pricehistory endpoint producer)

- **lines:** L385–432 (enum-API call L404–411; raw-kwargs fallback L418–425; final fail-closed `None` L432).
- **surface:** Enum-API path — `client.get_price_history(ticker, period_type=PH.PeriodType.DAY, period=…, frequency_type=PH.FrequencyType.MINUTE, frequency=…, need_extended_hours_data=False)` with `frequency_minutes ∈ {1,5,10,15,30}` and `period_days ∈ {1,2,3,5,10}` enum maps at L390–403. Raw-kwargs fallback — `client.get_price_history(ticker, periodType="day", period=period_days, frequencyType="minute", frequency=frequency_minutes, needExtendedHoursData=False)` (L418–425). **No Schwab JSON keys are subscripted in this file.**
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — payload **production / handoff** (same pattern as S2).
- **provenance trace (for audit only — clause 4):** Consumer chain — `server.py::_fetch_state` price-history seed paths → `safe_get_price_history(...)` → `client.get_price_history(...)` returns HTTP response → `resp.json().get("candles", [])` in caller (`server.py.md` S8 L3092–3101 and S9 L3694–3714; `market_data_adapter.schwab_candles_to_bars` L118–147) → leaf reads under `pricehistory.candles.*.open` / `.high` / `.low` / `.close` / `.volume` / `.datetime` (dictionary rows L2224–2231). Per-leaf dispositions in `server.py.md` S8/S9 and `market_data_adapter.py.md` S1.
- **canonical_field:** **N/A at this surface** (same rule as S2).
- **enum→raw-kwargs fallback note (L412–432):** The `except Exception as e_enum: … try { raw_kwargs } except Exception as e_raw: log.warning(…); return None` shape is **`schwab-py` API-version compatibility plumbing** — older library versions accept camelCase string-kwargs, newer versions accept typed enums; both call the same Schwab `/marketdata/v1/pricehistory` endpoint with the same parameter semantics. This is **not** a market-field substitution. Fail-closed on both-branch failure: a `warning` log records `enum_err` and `raw_err` for operator visibility (per the `STACK-VERIFY-CAND-SILENT-FALLBACK-SWEEP` comment block at L413–415) and returns `None` so the caller sees an explicit empty result, not a fabricated bar shape.
- **code edit:** none.

### S4 — `safe_get_chain` (Schwab REST option chain endpoint producer)

- **lines:** L434–448 — kwargs assembly L436–440 (`strike_count`, `include_underlying_quote=True`, optional `from_date` / `to_date`); call L441; `api_pressure.record_schwab_http_response(resp, f"option_chain:{ticker}")` L442–447.
- **surface:** `client.get_option_chain(ticker, **kwargs)` — returns the raw `schwab-py` HTTP response. **No Schwab JSON keys are subscripted in this file.**
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — payload **production / handoff** (same pattern as S2 / S3).
- **provenance trace (for audit only — clause 4):** Consumer chain — `server.py::_fetch_state` chain block (`server.py.md` S6 L2928–2934) and `server.py::/api/debug-charm` (`server.py.md` S17 L6755–6761, S18 L6745–6748) → `safe_get_chain(...)` → `client.get_option_chain(...)` returns HTTP response → `c_resp.json()` in caller → leaf reads under `chains.callExpDateMap.*.*` (L4–62), `chains.putExpDateMap.*.*` (L71–129), `chains.underlying.*` (L133–156), `chains.underlyingPrice` (L157). Per-leaf dispositions in `server.py.md` S6/S10/S12/S13/S14/S17/S18.
- **canonical_field:** **N/A at this surface** (same rule as S2 / S3).
- **`include_underlying_quote=True` note (L436):** Standard Schwab chain-request parameter that populates `chains.underlying.*` in the response (same arm `server.py.md` S6 reads). Not a derivation, not a substitution — the documented Schwab request flag controlling whether the underlying sub-tree is included.
- **code edit:** none.

---

## Appendix A — NOT_MARKET_DATA clusters (wire-token layer)

The entirety of this file is **NOT_MARKET_DATA at the Schwab wire-token layer** — no `example_raw_field` token is subscripted anywhere. S1 covers OAuth-2 credential plumbing (scope override, token inspection, client construction, login + manual flows, token-error classification, diagnostic file writer, UTC timestamp helper). S2 / S3 / S4 cover the three payload-producer wrappers — they invoke `schwab-py` client methods that hit Schwab REST endpoints and return the HTTP response **as opaque** to callers. The `api_pressure.record_schwab_http_response(resp, f"quote:{ticker}")` (S2) and `…(resp, f"option_chain:{ticker}")` (S4) telemetry calls consume the HTTP response for rate-limit accounting without subscripting Schwab market-data JSON keys. The `f"quote:{ticker}"` and `f"option_chain:{ticker}"` labels are operator-side telemetry tags, not Schwab wire tokens.

This file's contribution to V4 closure is **establishing the BRANCH layer** of the CANOPY→TRUNK→BRANCH→LEAF chain (per `CLAUDE.md` SCHWAB FULL REPO directive): the three `safe_get_*` functions are the named functions in the named file at which the producer→consumer payload handoff occurs. The LEAF citations live in each consumer memo at the per-key disposition.

---

## Aggregate disposition for inventory

- **status:** pending (awaiting gatekeeper)
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/schwab_client.py.md
