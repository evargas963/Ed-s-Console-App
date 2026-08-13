> **EVIDENCE / CONTRACT — not a second "now."** Outstanding work from this file, if material, lives on `OPEN_ITEMS.md` PA-48. Pointer: `ACTIVE_PROGRAM.md` → PA-46. Do not open a parallel program from this file.

> **Classification:** Evidence Artifact | **Scope:** VOLATILITY_SEMANTICS_AND_INPUT_CONTRACT_V1 session-evidence packet (read-only mission report)

# VOLATILITY_SEMANTICS_AND_INPUT_CONTRACT_V1

**Mission:** VOLATILITY_SEMANTICS_AND_INPUT_CONTRACT_V1
**Mode:** READ_ONLY
**HEAD at mission start and end:** `86466aeec5c18ae4b0d5ff30f3f5d77fa66c421b`
**Machine-readable counterpart:** `reports/VOLATILITY_SEMANTICS_AND_INPUT_CONTRACT_V1.json` (contains the full Phase 0 baseline snapshots including per-file SHA-256 hashes of every modified/untracked file, captured before investigation and after report generation).

Proof-label: `REPORTED_PROVEN_NOT_INDEPENDENTLY_VERIFIED` for design content; code-evidence rows carry `file:line` citations Read/verified this mission at the HEAD SHA above.

---

## Phase 0 — Worktree mechanical baseline

Captured at mission start (full command outputs and SHA-256 hash table embedded in the JSON under `phase0_baseline_start`):

- `git rev-parse HEAD` → `86466aeec5c18ae4b0d5ff30f3f5d77fa66c421b`
- `git status --short` → 14 modified tracked files, 16 untracked paths (identical set to the prior recovery mission's end-of-mission baseline)
- `git diff --name-status` / `--stat` → 11 tracked files, 206 insertions / 7 deletions (unchanged from prior baseline)
- `git ls-files --others --exclude-standard` → 15 untracked files

End-of-mission proof (bottom of this report): the only additions attributable to this mission are the two authorized report files. No pre-existing file hash changed.

---

## Matrix 1 — Volatility concept registry (Phase 4 authoritative decisions)

Separate fields ARE required for each concept below. The legacy overloaded `vix_*` names are the root cause of MSD-001/MSD-002 ambiguity; the canonical registry disambiguates them.

| Canonical name | Meaning | Source | Units | Missing → fail closed |
|---|---|---|---|---|
| `market_iv_level` | Broad-market 30d implied vol (CBOE VIX) | Schwab quotes `$VIX` lastPrice | vol points | yes |
| `market_iv_change` | Delta vs previous published cycle | derived current−prev | signed vol points | yes (None when prev missing, never 0) |
| `market_iv_direction` | rising/falling/flat over tracker window | derived tracker | enum | yes |
| `native_iv_level` | Underlying-native index IV (VXN/RVX) or chain ATM for equities | Schwab `$VXN`/`$RVX` or chain | vol points | yes — status `UNAVAILABLE`, never a silent macro copy |
| `native_iv_change` | Delta native IV vs prev cycle | derived | signed vol points | yes |
| `native_iv_direction` | Categorical native IV trend | derived tracker | enum | yes |
| `ticker_atm_iv` | Ticker chain ATM IV (existing `iv_level` semantics) | chain totals / mc_iv_level | decimal at SignalInput; percent in DB | yes |
| `realized_vol` | Annualized RV from 1m closes (FORMULA_P1A) | `math_volatility` | decimal at SignalInput; percent DB | yes |
| `forecast_vol_bars` | GARCH+blend per-bar sigma | `math_volatility` garch (≥21 closes) | per-bar sigma | no — MC flat-blend fallback is documented and explicit |
| `native_vs_market_iv_spread` | native − market divergence | derived | signed vol points | yes |
| `vol_input_quality` | Provenance/staleness envelope | derived per cycle | struct | REQUIRED — cannot be missing |

Full per-concept detail (sign/direction conventions, normalization, timestamps, staleness thresholds, consumer allowlists, training/live permissions) is in JSON matrix `1_volatility_concept_registry`.

---

## Matrix 2 — Producer–consumer matrix (Phase 1 inventory)

All citations Read this mission at HEAD `86466ae`:

| Field | Producer(s) | Money-path consumers | Defect |
|---|---|---|---|
| `vix_level` (legacy, overloaded) | `market_context` `$VIX` → `market_state.py:1312` `vix_level=mkt_ctx.vix` | `volatility_regime` (extreme 28 / rapid branch), `call_engine` (25/35 thresholds), `prediction_engine.py:646` similar-setups, `ml_train.py:140` numeric feature, `math_volatility.vix_bucket` (15/20/30), `server.py:4824` materiality context, `server.py:6162` confluence | macro consumed as universal ticker vol context (MSD-002) |
| `vix_direction` | live: `market_state.py:1312` hardcoded `None`; DB/API: server `_vix_tracker` → `server.py:6876`, `7247` | confluence (`server.py:6163`), API `ms_dict`, replay builder (copies DB column) | route divergence (MSD-001) |
| `vix_vs_prev` | live: ABSENT (no assignment in `market_state.py`); DB: `server.py:6741-6743` pre-publish diff | `volatility_regime.py:194` rapid branch (dead on live route), `prediction_engine.py:646`, `ml_train` numeric feature, replay builder | train/replay populated vs live None (MSD-001) |
| `vix_bucket` | `math_volatility.vix_bucket` on both routes | `ml_train` CATEGORICALS, similar-setups | none (single shared function) |
| `ctx.vxn` / `ctx.rvx` | `market_context.py:660-668` — fetch-only, in-code comment: "no consumer routing in V1 lane" | none | FETCHED_UNCONSUMED, statusless |
| `iv_level` | market_state chain ATM → decimal | `monte_carlo._blend_sigma`, `volatility_regime`, `ml_train` | — |
| `realized_vol` | market_state (percent→decimal at stamp) | `monte_carlo`, `volatility_regime`, `ml_train` | — |
| `garch_sigma_bars` | server GARCH fit on 1m closes | `monte_carlo` per-bar sigma path, `volatility_regime._garch_trend` | — |
| `atr` | market_state | `monte_carlo` blend, vol_regime `atr_pct` | — |

**Field name does not prove semantics:** `vix_level` at SignalInput is macro VIX for every ticker; `iv_level` is ticker-native chain IV in decimal at SignalInput but percent in ms_dict/DB. Both facts are stamped in code comments (`signal_types.py:86-88`, `db.py:424-426`) and verified by Read.

---

## Matrix 3 — Ticker-class mapping (Phase 2)

**Rule:** governed instrument-class map (owner: `instrument_identity.py`, which already owns the `VIX/VXN/RVX` broker-root mapping at `instrument_identity.py:22`) — never per-ticker hardcodes inside consumers.

| Class | Examples | Native index | Required concepts |
|---|---|---|---|
| `spx_cone` | SPY, $SPX | VIX (`NATIVE_EQUALS_MARKET`) | market_iv_*, ticker_atm_iv, realized_vol, forecast_vol_bars |
| `ndx_cone` | QQQ | VXN | + native_iv_* (VXN), native_vs_market_iv_spread |
| `rut_cone` | IWM | RVX | + native_iv_* (RVX), native_vs_market_iv_spread |
| `single_equity_guest` | AAPL, NVDA, TSLA, MSFT, AMZN, META, GOOGL, AVGO, MRVL, NFLX, PLTR, SMCI, CRWD, MET, PCG, CIFR, … | none | market_iv_* (macro overlay), ticker_atm_iv as native with status `CHAIN_DERIVED`, realized_vol, forecast_vol_bars |

**Justification by consumer role (not assumption):** `volatility_regime` needs macro stress + rate-of-change → `market_iv_*` for all tickers. Monte Carlo needs ticker-level sigma → already native by construction (chain IV / RV / GARCH on the ticker's own bars). Native index IV adds regime confluence only where an index exists — so SPY→VIX, QQQ→VXN, IWM→RVX emerges from consumer needs, not prescription. **Guest policy is universal:** any current or future guest resolves through the classification rule; a ticker without a native index gets `CHAIN_DERIVED` provenance — no fabricated index value, no per-ticker exceptions.

---

## Matrix 4 — Training/backtest/replay/live parity (Phase 3)

| Field | Training (DB) | Backtest | Replay | Live SignalInput | API | Parity |
|---|---|---|---|---|---|---|
| `vix_level` | populated | populated | populated | populated | populated | PARTIAL (companions missing live) |
| `vix_direction` | populated (tracker) | populated | populated (column copy) | **None** (`market_state.py:1312`) | populated | **CONFIRMED_DEFECT** |
| `vix_vs_prev` | populated (`server.py:6741`) | populated | populated | **ABSENT** | populated | **CONFIRMED_DEFECT** |
| native vol (VXN/RVX) | absent | absent | absent | fetched-unconsumed | absent | **CONFIRMED_DEFECT** (semantics) |
| `iv_level`/`realized_vol`/garch/atr | percent in DB | DB | raw column copy | decimal at stamp | ms_dict | **NOT_PROVEN** row-level — see finding below |

**New finding surfaced this mission (design must cover it):** `features/replay_signal_input_v1.py` copies matching DB columns verbatim into SignalInput. DB stores `iv_level`/`realized_vol` in **percent**, live SignalInput carries **decimal** (`signal_types.py:86-88`). The replay route therefore has a potential unit-convention divergence for those fields in addition to MSD-001's presence divergence. The golden-route parity lock (Matrix 9) is specified to catch exactly this class; row-level confirmation requires executing a replay row, which is outside this read-only mission → `NOT_PROVEN`, not asserted as defect.

---

## Matrix 5 — Missing-data and fallback matrix

Per concept: see registry table (Matrix 1, last column) and JSON `5_missing_data_fallback_matrix`. Governing rules:

- Direction/change fields: `None` when inputs missing — never `flat`/`0` as default.
- `native_iv_*`: explicit `native_iv_status = UNAVAILABLE` — never silently copy `market_iv_level`.
- `forecast_vol_bars`: documented fallback to MC flat blend (the one intentional fail-open, already explicit in `monte_carlo.py:233-247`).
- `vol_input_quality`: the only field that can never be missing.

---

## Matrix 6 — MSD-001 / MSD-002 reproduction register (Phase 3)

### MSD_001 = CONFIRMED_DEFECT

- **Producer (live):** `market_state.py:1312` stamps `vix_direction=None`; Grep of `market_state.py` proves no `vix_vs_prev` assignment exists.
- **Producer (DB/API):** `server.py:6741-6743` computes `vix_vs_prev` pre-publish; `server.py:6876-6877` stamps snapshot row; `server.py:7247-7252` stamps `ms_dict`.
- **Consumers hit:** `volatility_regime.py:194` (`vix_chg = _f(inp.vix_vs_prev)`) — the rapid-VIX-change branch (`volatility_regime.py:216-231`) can **never fire on the live route**; `prediction_engine.py:646` similar-setups key always None live vs populated history rows.
- **Route divergence proof:** `features/replay_signal_input_v1.py` copies every matching DB column, so a **replay** SignalInput carries `vix_direction`/`vix_vs_prev` while a **live** SignalInput does not — same as-of information, different inputs. Deterministic; all tickers; all horizons.

### MSD_002 = CONFIRMED_DEFECT

- `market_state.py:1312` gives every ticker `vix_level=mkt_ctx.vix` (macro).
- `market_context.py:647-652` fetches `$VIX`; `market_context.py:654-668` fetches `$VXN`/`$RVX` with in-code comment "fetch-only; no consumer routing in V1 lane" — data exists at wire, no consumer, no status.
- `ml_train.py:140` (`vix_level`, `vix_vs_prev` numeric) and `ml_train.py:175` (`vix_bucket` categorical) train every ticker's model on macro VIX as if ticker-relevant.
- `call_engine` VIX thresholds (25/35) apply universally. `db.py` SnapshotRow has no native-vol columns.
- Deterministic; semantic scope QQQ/IWM/guests, overload scope ALL.

---

## Matrix 7 — Canonical volatility input contract (Phase 5, design only)

**`VOL_INPUT_CONTRACT` semver `1.0.0-draft`, ticker-agnostic.**

- **Required:** `market_iv_level`, `market_iv_change`, `market_iv_direction`, `ticker_atm_iv`, `realized_vol`, `vol_input_quality`.
- **Conditional (class-dependent):** `native_iv_level/change/direction`, `native_vs_market_iv_spread`, `forecast_vol_bars`.
- **Prohibited silent defaults:** `0`, `0.5`, `neutral`, flat-as-default, macro-copied-into-native without status.
- **Neutral states:** absence is `None` + quality status — absence is never a directional signal.
- **Fail-closed:** missing required field → consumer degrades explicitly (vol_regime returns unknown-with-reason; ML row excluded via governed pipeline).
- **Sessions covered:** premarket, RTH, after-hours, closed, historical replay, training.
- **Provenance:** `vol_input_quality` per field: `{status: LIVE|STALE|UNAVAILABLE|CHAIN_DERIVED|NATIVE_EQUALS_MARKET, source_symbol, ts}`.
- **Compatibility:** legacy `vix_*` frozen as `market_iv_*` aliases during migration; contract version stamped in training rows and by the live builder; version mismatch fails scheduler preflight.

Not implemented in this mission.

---

## Matrix 8 — Implementation dependency matrix (Phase 6 full-fix design)

### Lane V1 — MSD-001 route parity
One per-cycle vol context computed once in `server.py` (tracker direction + pre-publish change), passed into `market_state.build_market_state` as a parameter, stamped identically onto SignalInput, snapshot row, and `ms_dict`. No `signal_types.py` schema change needed (fields exist). Forbidden: `ml_predict.py`, `models/*`, `calibration/*`. Tests: route-parity unit (three surfaces equal per tick), vol_regime rapid-branch reachability, replay golden equality. Rollback: default-`None` parameter preserves current behavior; single revert. Acceptance: parity test green, zero training-column change, zero ticker literals.

### Lane V2 — MSD-002 semantics
Add `native_iv_*` + `vol_input_quality` to `signal_types.py`; class map in `instrument_identity.py`; stamp in `market_state.py`; additive DB columns (`native_iv_level/change/direction/status`) — historical rows NULL with status `BACKFILL_UNAVAILABLE`, no fabricated backfill. `market_context.py` already fetches VXN/RVX. **ML feature adoption is explicitly NOT in this lane** — survivors-only placement per the ablation contract governs any future feature add. Tests: class-map totality over supported tickers, QQQ→VXN / IWM→RVX / SPY→`NATIVE_EQUALS_MARKET`, guest→`CHAIN_DERIVED`, fetch-fail→`UNAVAILABLE` without macro contamination.

### Dependency order
1. **R1 — operator ratifies this contract** (blocking specification decision)
2. Lane V1 (MSD-001)
3. Lane V2 (MSD-002)
4. Prior-mission 5c lanes (MSD-003/004)
5. ML adoption only after purged-CV + ablation infrastructure

---

## Matrix 9 — Mechanical-lock matrix (Phase 7)

| Lock | Fails when | Mechanism |
|---|---|---|
| canonical-builder | production `SignalInput(` outside `build_market_state` / replay builder | AST scan in `tools/check_fix_everything_we_touch.py` + paired test |
| vol-field completeness | `vix_level` set but direction/change None while cycle had values | builder invariant + unit test |
| legacy-overload | new read of `ctx.vix` with native semantics | checker allowlist |
| class-map totality | supported ticker unmapped or duplicate-mapped | test vs `models/active*` inventory |
| contract-version parity | training rows vs live builder semver differ | version stamp + scheduler preflight |
| silent-fallback | native non-null without status, or macro copied to native | builder invariant + negative test |
| consumer-allowlist | consumer reads vol field outside allowlist | AST attribute scan (advisory tier) |
| golden-route parity | immutable golden input diverges across live/replay builders (catches the percent/decimal replay finding) | pytest golden fixture |

---

## Matrix 10 — Final binary status table

```
VOLATILITY_CONSUMER_INVENTORY               = PROVEN
CURRENT_VOLATILITY_SEMANTICS                = CONFIRMED_DEFECT
MSD_001                                     = CONFIRMED_DEFECT
MSD_002                                     = CONFIRMED_DEFECT
TICKER_VOLATILITY_MAPPING_SPECIFICATION     = PROVEN
GUEST_TICKER_MAPPING_SPECIFICATION          = PROVEN
TRAIN_BACKTEST_REPLAY_LIVE_VOLATILITY_PARITY = CONFIRMED_DEFECT
CANONICAL_VOLATILITY_INPUT_CONTRACT         = APPROVED
MSD_001_FULL_FIX_DESIGN                     = APPROVED
MSD_002_FULL_FIX_DESIGN                     = APPROVED
MECHANICAL_ENFORCEMENT_DESIGN               = APPROVED
IMPLEMENTATION_READY                        = NOT_APPROVED
REAL_MONEY_APPROVAL                         = NOT_APPROVED
```

`IMPLEMENTATION_READY = NOT_APPROVED` because this mission is read-only and the contract requires operator ratification (dependency R1) before any implementation lane may land. The designs themselves are APPROVED as designs.

---

## End-of-mission proof

See JSON `phase0_baseline_end` (captured after both report files were written): HEAD unchanged at `86466aeec5c18ae4b0d5ff30f3f5d77fa66c421b`; `git status --short` and `git diff --name-status/--stat` byte-identical to the start baseline for all pre-existing files; every start-baseline SHA-256 hash unchanged; the only new paths are:

```
reports/VOLATILITY_SEMANTICS_AND_INPUT_CONTRACT_V1.md
reports/VOLATILITY_SEMANTICS_AND_INPUT_CONTRACT_V1.json
```

RECOVERY_SCOPE_VIOLATION = NOT_DETECTED. Nothing was committed, pushed, merged, retrained, recalibrated, or altered at runtime.
