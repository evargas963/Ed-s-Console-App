# DEEP ADVERSARIAL AUDIT v23 — One Levels Faucet (RC-128) — 2026-07-29 ~08:30 CT

**HEAD:** `84f66649` — `RC-128 CLOSED: One Levels Faucet — the second book is deleted, not overridden.`  
**Mandate:** operator prompt — one producer, one payload path, mechanical locks, no second book anywhere  
**Method:** commit census → AST/line writer scan → UI dual-bind census → suite → escape list  
**Verdict:** **ACCEPT** the core RC-128 claim for **`kl_*` SSOT carriage** (analytics second book deleted; overlay sole writer; delta+EM in terrain; E-34 closed; locks fire) · **REJECT** absolute “no more multiple faucets **anywhere**” · **PARTIAL** vs full mandate (dual terrain-native vs `kl_*` paint paths; unlocked HVP/LVP/charm/key_delta; radar fallback producer; analytics still recomputes flip/HVL/max-pain for internals)

---

## Charter

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — adversarial verify One Levels Faucet |
| GAP | Claude CLOSED RC-128 vs mandate absolute wording |
| SMALLEST_COMPLETE_CHANGE | This report |
| EVIDENCE | Same-turn AST/scan + 27 passed + file:line |
| DECISION_PATH | none |
| WHY_NOW | Operator ordered deep audit |
| TASK_ADMISSION | audit only |

---

## What shipped (`84f66649`, 7 files, +171/−59)

| Area | Change |
|---|---|
| `server.py` | Deleted analytics `kl_*` / strength / straddle-EM writes; expanded `_terrain_kl_overlay` sole writer |
| `terrain_engine.py` | `call_delta_wall` / `put_delta_wall` on SSOT producer |
| `static/index.html` | Removed `em_straddle \|\| kl_em` fallback chains |
| Tests | AST-adjacent sole-writer + negative control + full-concept overlay + Lock-4 client ban |
| Ledger | RC-128 CLOSED; E-34 CLOSED |

---

## Mandate checklist vs reality

| Mandate item | Grade | Proof |
|---|---|---|
| Analytics cannot publish SSOT `kl_*` | **FIXED** | Assignments deleted at Tier-C shell + `_fetch_state`; AST subscript assigns outside overlay = **[]**; line-scan offenders = **[]** |
| Overlay only writer for SSOT set | **FIXED** | Literals in `_terrain_kl_overlay` `:10496+`; called at `:2679` and `:8650` only (def at `:10466`) |
| Delta walls on terrain SSOT | **FIXED** | `terrain_engine.py` `pick_delta_wall_strikes`; overlay carries |
| OI/vanna/inflections/oi_center | **FIXED (blank)** | Overlay forces `None` — absence, not analytics stand-in |
| One EM (E-34) | **FIXED** | `kl_em_*` from terrain `implied_1d_move` + spot; straddle → `em_straddle_*_diag`; client `em_straddle` count **0**; Lock-4 test present |
| Fail-closed stale/absent | **FIXED** | Prior + widened carriage test; stale blanks SSOT keys |
| Mechanical locks invariant-shaped | **PARTIAL / GOOD** | Sole-writer + injection negative control + full-concept test + Lock-4 — **real**. Gaps below |
| One payload path all surfaces | **OUTSTANDING** | UI still paints terrain-native `call_wall`/`gamma_pin`/… **and** `kl_*` (index mentions e.g. call_wall **12** vs kl_call_gamma_wall **2**) |
| No second producer anywhere | **OUTSTANDING** | `_radar_fallback_recompute` still live; analytics still `compute_gamma_flip_v2` / `compute_hvl` / `compute_max_pain` on narrow `contracts_use` (`:6556-6559`) for MS/internals |
| Lock 3 UI single bind | **ABSENT** | No test forces one key family per concept across paint sites |
| Census of HVP/LVP/charm/key_delta | **PARTIAL** | Painted on cv2 map from terrain (`index.html:13457`) — one producer, **not** in `SSOT_KEYS` lock set |

---

## Same-turn proof

```
SSOT writes outside overlay: []
AST SSOT assigns outside overlay: []
pytest tests/test_levels_single_producer_v1.py + test_client_spot_single_faucet_v1.py → 27 passed
E-34: CLOSED in agent_error_log
```

---

## Escapes / residuals (why not absolute ACCEPT)

### 1. Dual bind (same producer, two key families) — mandate Lock 3 miss
Terrain cards / chart / cv2 read `t.call_wall`, `t.gamma_pin`, `t.hvl`, …  
Key Levels / some chips read `kl_call_gamma_wall`, … stamped from cache.  
If both always mirror the same terrain cache generation → numbers match.  
If `/api/terrain` and Tier-C overlay stamp at different times → **two call walls on one screen** without a second analytics book. Not locked.

### 2. Extra painted levels outside `SSOT_KEYS`
HVP, LVP, KEY DELTA, CALL/PUT CHARM on the cv2 level list — terrain-sourced, unlocked by RC-128 writer scan. Adding an analytics paint of the same names would not trip Lock 1.

### 3. Radar fallback producer
`_radar_fallback_recompute` remains (grandfathered in producer-set test). Mandate: route through terrain refresh or do not paint as live key levels.

### 4. Analytics still recomputes SSOT *concepts* for non-`kl_*` consumers
Narrow-chain `_gamma_flip` / `_hvl` / `_max_pain` still computed in `_fetch_state`. They no longer fill `kl_*`, but `kl_gamma_flip_confidence` is still published from that narrow flip while the strike comes from terrain — **confidence can describe a different book than the level**.

### 5. `kl_em_anchor` still analytics
`ms_dict["kl_em_anchor"] = resolve_kl_em_anchor(_em_straddle, _em_iv)` while `kl_em_upper/lower` are terrain sigma. Related vocabulary split (method label vs band).

### 6. Lock-4 narrowness
Bans `em_straddle_* ||` and `|| d.kl_em_*` only — not a general ban on level-key fallback chains.

---

## RC-128 CLOSED honesty

| Claim in commit | Cursor grade |
|---|---|
| Second **analytics `kl_*` book** deleted | **ACCEPT** |
| Overlay sole writer of SSOT_KEYS | **ACCEPT** |
| E-34 closed | **ACCEPT** |
| “One Levels Faucet” / no second book **anywhere** | **REJECT as absolute** — dual bind + radar + unlocked extras + flip confidence |
| Status cell CLOSED | **ACCEPT for scoped burn**; should note PARTIAL residuals in fix cell (placement class solved for `kl_*`; Lock 3 / extras open) |

---

## Score impact (seed)

Levels dual-book was a major trust drag. Core fix earns **+1** on Trust / Structure / Collect vs pre-RC-128. Absolute faucet purity still short of 10.

---

## What would earn full ACCEPT of the mandate

1. **One bind:** UI reads only `kl_*` (stamped) **or** only terrain fields — not both for the same concept; structural test.  
2. Extend `SSOT_KEYS` (or sibling lock) to every painted level name (HVP/LVP/charm/key_delta/ranges).  
3. Kill or quarantine radar fallback as a levels producer for operator paint.  
4. Stop publishing analytics `kl_gamma_flip_confidence` unless derived from the SSOT flip’s chain.  
5. Align or rename `kl_em_anchor` so it cannot imply a second EM method on the level strip.

---

## Status line

`CLAIM: ACCEPT RC-128 kl_* sole-writer + E-34 @84f66649; REJECT absolute one-faucet-anywhere; dual-bind UI + radar + extras open · DONE: v23 · NEXT: operator (seal residuals | Decide) · BLOCKER: none`
