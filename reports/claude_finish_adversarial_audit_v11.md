# BRUTAL ADVERSARIAL AUDIT v11 — 2026-07-28 ~13:02 CT

**HEAD:** `5d82adce` — `RC-112 recurrence 2 (v10): by-REFERENCE bypasses killed; lock counts names.`  
**Prior:** v10 @ `e995e665` · REJECT finished  
**Method:** reaudit of Claude’s post-v10 close + re-prove remaining v10 victims · **SYNTHESIZED 2/2**  
**Verdict:** **REJECT “finished”**

| Agent | Status |
|---|---|
| [Money-path v11](3b37de13-c2a3-461e-aaae-8585f6892a62) | **MERGED** |
| [UI/Decide/LP01/DB v11](eee460c2-0942-49be-b6c8-4f8b4fc84c13) | **MERGED** |

---

## Headline

| Claim | Grade | Evidence |
|---|---|---|
| W3-C8 v10 kill shots (pool + mkt_ctx) | **FIXED / ACCEPT** | `:6237`, `:4175-4176`; structural test 1 passed |
| RC-112 “class sealed / lock unbeatable” | **PARTIAL / OVERCLAIM** | `server.py` name lock only; beaten by `safe_get_quote` / `client.get_quote` / getattr / other files |
| RC-110 / RC-115 → PARTIAL | **GOOD honesty** | Named-victim / VA debt still owed |
| UI clocks / Decide / LP-01 / RC-6 | **OUTSTANDING** | Untouched by `5d82adce` (byte-identical to v10 reject surface) |
| Repo **finished** | **REJECT** | — |

---

## What Claude shipped since v10

Only `5d82adce` (+23/−10): `server.py` + spot test + RC-110/115→PARTIAL.  
**Not touched:** `static/index.html`, `liquidity_value_engine.py`, `db.py`, `ACTIVE_PROGRAM.md`, gate `CHECKS`.

---

## MONEY_PATH ([Money-path v11](3b37de13-c2a3-461e-aaae-8585f6892a62))

| Claim | Grade | path:line |
|---|---|---|
| `_cq_pool` / market_context → memo | **FIXED** | `:6237`, `:4175-4176` |
| Fast lane / resolve_spot / inline Tier C | **FIXED** | `:3106`, `:563`, `:6215` |
| Absolute every-vendor-quote | **PARTIAL** | Startup `get_quote` `:9383/:9391`; `print_price_levels.py:50` |
| Lock unbeatable | **REJECT** | file-scoped name substring |
| W3-C4 carry-forward / QSD merge | **OUTSTANDING** | `:3008-3079`; `live_market_plane.py:230-254` |
| W3-C1 dual wall books | **OUTSTANDING** | `kl_*` + terrain both painted |
| Math ≠ display | **PARTIAL** | shared memo; dual semantics remain |

Exact `server.py`: `_safe_get_quote_with_retry` hits **3**; lock-legal non-def non-`#` = **1**; `_memoized_quote_response` hits **10**.

---

## UI / DECIDE / LP01 / DB / LOCKS ([UI/Decide/LP01/DB v11](eee460c2-0942-49be-b6c8-4f8b4fc84c13))

| ID | Grade | Evidence |
|---|---|---|
| W3-C3 multi-writer `#cv2-hd-px` | **OUTSTANDING** | `:6470`, `:13057`, `:13222`, `:13265` |
| W3-U3 `live ·` footers | **OUTSTANDING** | `:13089`, `:13491` |
| W3-U4 `#ct-conf` | **OUTSTANDING** | `:13441-13442` vs `#ct-trust` |
| W1-H2 gamma raw spot | **OUTSTANDING** | `:13313` |
| Decide pills under WAIT | **OUTSTANDING** | `:5331-5348` |
| LP-01 (all core math/surface) | **OUTSTANDING** | VP `:463-475`; overnight `:322-336`; LM under `#main` `:2827` |
| LP-01 program | **NEXT** | `ACTIVE_PROGRAM` Operator NOW unchanged |
| RC-6 blobs | **LIVE** | exact **1,097** / **187,193,762** B |
| RC-6 schema lock | **ABSENT** | `db.py:2727-2746` |
| `verify_dead --check` | **THEATER** | ∉ ENFORCED `CHECKS` (39 enforced) |

---

## Bucket scorecard (final)

| Bucket | Δ vs v10 | Grade |
|---|---|---|
| MONEY_PATH (W3-C8 v10 sites) | **up** | **FIXED** |
| MONEY_PATH (class seal) | slight up | **PARTIAL** |
| COLLECT_AUTH / C1 / C2 | flat | **OUTSTANDING / PARTIAL** |
| UI_CONSOLE_CHART | flat | **REJECT finished** |
| LEVELS_TERRAIN | honesty ↑ (RC-110/115 PARTIAL) | **REJECT finished** |
| LP01_LIQUIDITY | flat | **OUTSTANDING** (still NEXT) |
| DB_STORAGE | flat | **DEFECT LIVE** |
| DECIDE_ADMISSION | flat | **OUTSTANDING** |
| LOCKS_GOVERNANCE | RC honesty ↑ | **PARTIAL / THEATER** |

---

## Top burn (unchanged fork)

1. **P0 UI clocks** — one `#cv2-hd-px` writer; honest footers; `#ct-conf`; gamma via `consoleSpot`  
2. **P0b plane** — W3-C4 `record_quote` + QSD; W3-C1 one wall book  
3. **LP-01** — VP `[L,H]` (program-legal default)  
4. **RC-6** — schema lock against normalized blob re-ADD  
5. **Decide** — blank direction under `!tradeable`

---

## Status line

`CLAIM: REJECT finished @ 5d82adce — SYNTHESIZED 2/2; ACCEPT W3-C8 kill-shot; REJECT class-sealed; UI/Decide/LP-01/RC-6 still v10-surface · DONE: v11 · NEXT: operator burn P0_CLOCKS | LP-01 | DECIDE · BLOCKER: none`
