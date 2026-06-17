> **Classification:** Policy Specification | **Scope:** Governance documentation `market_data_adapter.py.md`.

# Review memo — market_data_adapter.py

**Status:** pending gatekeeper review
**Date:** 2026-05-24 (S2 disposition refreshed — code already at canonical-only state)
**Reviewer:** Claude (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)
**File language family:** python
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)**

**Refresh note (2026-05-24):** Original memo (2026-05-10) flagged S2 as UNREVIEWED because the historical `normalize_bar` accepted multi-provider aliases (`vol`, `o`/`h`/`l`/`c`, `t`/`time`, etc.) and named Schwab + Polygon + Alpaca + generic in its docstring; closure required typed per-provider entrypoints or operator GOVERNED_EXCEPTION (O-NN). **Current code (at HEAD) has already taken the per-provider-split path:** `normalize_bar` reads only canonical Schwab `pricehistory.candles.*` leaves plus the NormalizedBar internal `timestamp` projection; the non-Schwab aliases are gone; the docstring (L66–69) cites only Schwab. **Resolution: S2 disposition updated UNREVIEWED → REPLACED.** No code change, no O-NN required, no FIND.

**Closest-shape precedent** (per `AGENTS.md` Posture rules — sibling-pattern conformance, 2026-05-24): `polling_adapter.py.md` — same shape (small producer-chain adapter file, mixed-disposition with REPLACED for Schwab leaf reads and NOT_MARKET_DATA for internal projection keys). `realized_contract_eval.py.md` (just-landed) for the canonical-leaf citation discipline.

**Active-posture Class A check** (per `AGENTS.md` §Fix everything we touch, 2026-05-24): Read surfaced stale memo content (S2 disposition outdated relative to current code). Fix = memo update to match current code state. No actionable in-file code FIND, no non-canonical fallback, no Schwab-replaceable derivation. **Memo-only commit admissible** — fix is the memo itself; nothing to bundle.

---

---

## Gatekeeper CSV cross-check (retroactive @ 977e706, 2026-05-24)

**Tool:** \python tools/check_schwab_csv_first.py --gatekeeper-crosscheck market_data_adapter.py\n**lexical_csv_collision_count:** 42

Retroactive full-CSV AST cross-check. Prior memo dispositions unchanged; homonym collisions classified in original site sections. Zero new wire FIND from cross-check.

## Audit methodology (clause 4 — attribute / call / subscript)

Audited **this file** (177 lines at HEAD) for:

| Channel | Method |
|---------|--------|
| String-literal dict access on Schwab candle payloads | `c.get("datetime")`, `c.get("volume")` (L169, in `schwab_candles_to_bars`); `raw.get("open"\|"high"\|"low"\|"close"\|"volume"\|"datetime")` via `_f(key)` + `_volume()` helpers (L77–94, called L109–112, L123); `raw.get("datetime")` and `raw.get("timestamp")` (L100, L104) — `datetime` is canonical Schwab `pricehistory.candles.*.datetime`; `timestamp` is the **NormalizedBar dataclass internal field name** (L40, BAR_KEYS L22), not a non-canonical provider alias. |
| Bracket dict access on Schwab payloads | None (all access via `.get(...)`). |
| Attribute access on market-bearing objects | `getattr(raw, key, None)` for OHLC + volume + datetime + timestamp when `raw` is not a dict (L78, L87, L106, L107) — supports NormalizedBar object re-normalization (idempotent), not a non-canonical provider object accessor. |
| Method calls passing Schwab market objects | `normalize_bar(raw, source=...)` is called from `schwab_candles_to_bars(candles)` (L165) and from callers via `normalize_bars(raw_bars, source=...)` (L139–146). |
| Schwab field dictionary citations consumed | `pricehistory.candles.*.{open,high,low,close,volume,datetime}` (dict L2225–2231); enumerated explicitly in `SCHWAB_CANDLE_LEAF_MAP` at L27–34. |

**Non-canonical alias check (clean):** The historical bare-key aliases flagged by the 2026-05-10 memo — `vol`, `o`/`h`/`l`/`c`, `t`/`time` — are **not present** in the current code at any line. No `bidSize`-class REST-vs-streaming leak (file works with REST `pricehistory.candles.*` only).

**Review complete:** Every site **in this file** falls under **S1–S4** below; no Schwab `example_raw_field` tokens beyond the six canonical `pricehistory.candles.*` leaves enumerated above.

---

## Market-data sites identified

### S1 — `schwab_candles_to_bars` (Schwab-typed entrypoint)

- **lines:** L154–177.
- **surface:** Iterates Schwab pricehistory candle dicts; calls `normalize_bar(raw, source="schwab_pricehistory")` (L165); extracts `c.get("datetime")` separately (L169) and stamps `bar["_ts"]` (epoch seconds; ms→s conversion when `ts > 1e12`).
- **proposed disposition:** **REPLACED** — canonical Schwab pricehistory candle keys.
- **canonical_field:** `pricehistory.candles.*.datetime` (dict L2227) at the `_ts` stamp; full OHLCV leaf set delegated to S2 via `normalize_bar(..., source="schwab_pricehistory")`.
- **provenance trace (clause 4):** Caller passes the array from `safe_get_price_history(client, ...) → resp.json()["candles"]` (per `schwab_client.py.md` S3 and `polling_adapter.py.md` S2/S3); each `c` element matches the Schwab `pricehistory.candles.*` shape (dict L2224–2231).
- **observation:** Iteration safety — `if not isinstance(c, dict): continue` (L162–163) skips malformed entries without crashing; `raw = dict(c)` defensive copy before mutation (L164); `bar["_ts"]` only stamped when `ts is not None` and `float()` succeeds (L170–175) — fail-disclosed, no fabricated timestamps.
- **code edit:** none.

### S2 — `normalize_bar` / `normalize_bars` (canonical-only at HEAD; UNREVIEWED → REPLACED)

- **lines:** L62–136 (`normalize_bar`), L139–146 (`normalize_bars`).
- **surface — canonical Schwab leaves only:**
  - **L109–112 OHLC:** `_f("open")`, `_f("high")`, `_f("low")`, `_f("close")` via the `_f(key)` helper (L77–84) which does `raw.get(key)` for dicts or `getattr(raw, key, None)` for objects, returning `float(v)` or `None`. **Maps to** `pricehistory.candles.*.open / .high / .low / .close` (dict L2226 / L2228 / L2229 / L2230).
  - **L123 volume:** `_volume()` helper (L86–94) reads `raw.get("volume")` (dict) or `getattr(raw, "volume", None)` (object); returns `float(v)` if `>= 0`, else `None` (rejects negative volumes — fail-disclosed). **Maps to** `pricehistory.candles.*.volume` (dict L2231).
  - **L98–108 timestamp:**
    - When `source == "schwab_pricehistory"`: reads `raw.get("datetime")` only (L100); adds `"datetime"` to `missing_fields` if absent (L101–102). **Maps to** `pricehistory.candles.*.datetime` (dict L2227).
    - When `source != "schwab_pricehistory"`: reads `raw.get("datetime")` first; falls back to `raw.get("timestamp")` if `datetime` is None (L104). The `timestamp` key here is the **NormalizedBar dataclass internal field name** (L40, `BAR_KEYS` L22) — supports idempotent re-normalization of already-normalized bars, not a non-canonical provider alias.
  - **L113–118 missing OHLC reject:** any of OHLC missing → `log.debug` + return `None` (fail-closed, no fabricated bar).
  - **L119–121 close==0 reject:** zero-close → `log.debug` + return `None` (fail-closed).
  - **L124–125 missing-volume disclosure:** when dict has no `volume` key, adds `"volume"` to `missing_fields` on the returned bar (disclosed; not silently zero).
- **proposed disposition:**
  - **OHLC + volume + datetime reads (Schwab path):** **REPLACED** — six canonical `pricehistory.candles.*` leaves.
  - **`timestamp` fallback (non-Schwab path):** **NOT_MARKET_DATA** at Schwab wire-token layer — reads the NormalizedBar dataclass's own internal field name (idempotent re-normalization), same rule as `signals.py.md` S3 (internal projection keys are not Schwab wire tokens).
  - **`getattr(raw, key, None)` object accessor path:** **NOT_MARKET_DATA** at Schwab wire-token layer — accepts pre-typed NormalizedBar (or any object exposing the canonical attribute names) for idempotent re-normalization; not a non-canonical provider-object accessor.
- **canonical_field:** `pricehistory.candles.*.{open,high,low,close,volume,datetime}` (dict L2226–2231).
- **provenance trace (clause 4):** Two callers in this file (`schwab_candles_to_bars` at L165, `normalize_bars` at L143); external callers reach `normalize_bars` with `source="schwab_pricehistory"` to hit the Schwab-strict timestamp branch (L99–102). The `_f` and `_volume` helpers do not accept any non-canonical key — they only resolve the five literal canonical keys passed by the caller.
- **historical disposition (2026-05-10) — superseded:** UNREVIEWED with `code edit: deferred — add provider-specific wrappers or register O-NN before closure`. Resolved by intervening refactor: the multi-provider aliases (`vol`, `o`/`h`/`l`/`c`, `t`/`time`) were removed, the docstring narrowed to Schwab, and `SCHWAB_CANDLE_LEAF_MAP` was added to make the canonical mapping explicit. Per V4-B §When refactor is required: "If a Schwab equivalent fits the site and no operator-cited constraint in a valid O-XX blocks substitution, the row must not close as GOVERNED_EXCEPTION — edit code toward REPLACED or remove the emission." The code is already at REPLACED; no O-NN is needed.
- **`normalize_bars` (L139–146):** thin wrapper; iterates `raw_bars` list, calls `normalize_bar(b, source=source)`, returns `[nb.to_dict() for nb in ...]`. No additional key reads. **NOT_MARKET_DATA** in this file for subscript tokens — delegates to S2 main.
- **code edit:** none — code is already at the REPLACED endpoint the historical memo called for.

### S3 — `SCHWAB_CANDLE_LEAF_MAP` + module constants (explicit governance mapping)

- **lines:** L21–34. `BAR_KEYS` (L22 — canonical output dict key list). `_OHLC_KEYS` (L24 — the four OHLC literals). `SCHWAB_CANDLE_LEAF_MAP` (L27–34 — explicit `dict[str, str]` mapping internal field name → Schwab dictionary leaf path).
- **surface:** Module-level string constants. `SCHWAB_CANDLE_LEAF_MAP` enumerates the six Schwab leaves used by S1 / S2 with their canonical paths (`pricehistory.candles.*.open`, etc.) — a built-in compliance pointer for downstream auditors.
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — explicit governance documentation embedded in code (this IS the V4-compliance pointer, not a wire read).
- **code edit:** none.

### S4 — `NormalizedBar` dataclass

- **lines:** L37–59.
- **surface:** Dataclass with seven fields (`timestamp`, `open`, `high`, `low`, `close`, `volume`, `source`, `missing_fields`); `to_dict()` method (L49–59) projects to engine-consumable dict shape.
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — internal canonical bar shape; field names match Schwab canonical leaf names (`open`/`high`/`low`/`close`/`volume`) by design but the dataclass IS the canonical projection, not a wire read.
- **code edit:** none.

---

## Appendix A — NOT_MARKET_DATA clusters (wire-token layer)

Bulk **NOT_MARKET_DATA** at Schwab `example_raw_field` token layer:

- **Module imports + logger (L1–19).**
- **`BAR_KEYS` / `_OHLC_KEYS` / `SCHWAB_CANDLE_LEAF_MAP` (S3):** Internal canonical shape declarations; `SCHWAB_CANDLE_LEAF_MAP` is governance documentation (the file's own pointer to Schwab dictionary leaves).
- **`NormalizedBar` dataclass + `to_dict` (S4):** Internal canonical bar projection.
- **`normalize_bar` non-canonical fallback paths:** `timestamp` key fallback (when `source != "schwab_pricehistory"`) is the dataclass internal field name, not a provider alias. `getattr(raw, key, None)` object-accessor path supports idempotent re-normalization of already-typed NormalizedBar instances.
- **`normalize_bars` wrapper (S2 tail):** Delegates to S2 main, no additional key reads.

**REPLACED dispositions** concentrate in S1 (`schwab_candles_to_bars` — Schwab-strict entrypoint stamping `_ts`) and S2 Schwab path (`normalize_bar` with `source="schwab_pricehistory"` reading the six canonical pricehistory leaves). Six canonical `pricehistory.candles.*` leaves total: `open`, `high`, `low`, `close`, `volume`, `datetime`.

This file's contribution to V4 closure is **establishing the Schwab pricehistory normalization branch** as Schwab-wire-clean: the historical multi-provider aliases are gone; the canonical leaves are explicitly mapped via `SCHWAB_CANDLE_LEAF_MAP`; the `source="schwab_pricehistory"` typed-entrypoint pattern (S1) is the Schwab-strict path called by `polling_adapter.fetch_bars_via_schwab` and `polling_adapter.fetch_bars_via_schwab_for_session` (per `polling_adapter.py.md` S2 / S3 delegation notes).

---

## Aggregate disposition for inventory

- **status:** pending (awaiting gatekeeper)
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/market_data_adapter.py.md
- **S2 closure:** UNREVIEWED → **REPLACED** @ this SHA. Resolution path: per-provider split (code already at canonical-only state; multi-provider aliases removed by intervening refactor before 2026-05-24). No O-NN needed.
- **Class A determination:** memo-only commit admissible — the "fix" in cone (per AGENTS §Fix everything we touch) is the memo update itself; the code is already at the REPLACED endpoint the historical memo's S2 disposition called for. No code change, no paired test, no new FIND.
