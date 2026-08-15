# BRUTAL ADVERSARIAL AUDIT v10 — 2026-07-28 ~12:36 CT

**HEAD:** `e995e665` — `RC-6 REOPENED` (+ “W3-C8 memo class closed” / RC-110–115 CLOSED stamps)  
**Prior:** v9 @ `5418054f` · Wave-3 · `reports/repo_attack_plan_and_ratings_v1.md`  
**Method:** bucket audit (not blind full-repo) · **SYNTHESIZED 3/3**  
**Verdict:** **REJECT “finished”**

| Agent | Status |
|---|---|
| [Money-path v10](f3a3b901-271c-4032-9f5d-db30da95d03f) | **MERGED** |
| [UI/walls v10](67755ca0-f396-496d-8587-6b4470f92099) | **MERGED** |
| [Locks/Decide/LP01/DB v10](f572af15-23d3-4029-9278-8694d93414dc) | **MERGED** |

---

## Headline

| Claim | Grade | Smoking gun |
|---|---|---|
| “W3-C8 memo class closed” (`f2c08c1d`) | **FAKE_CLOSE** | Inline memo `server.py:6210`; hot `_cq_pool` still `_safe_get_quote_with_retry` `:6228`. Structural test greps `"_safe_get_quote_with_retry("` only → **green while bypass lives** |
| RC-112 (fast lane + resolve_spot) | **FIXED** (those two legs) | `:3106`, `:563` |
| RC-112 class / Tier C continuum | **FAKE_CLOSE** | `:6228` + `market_context` inject `:4171` |
| RC-6 reopen | **GOOD honesty / DEFECT LIVE** | Exact **1,097** / **187,193,762** B; schema lock **ABSENT** (`db.py:2727-2746`) |
| RC-110 / RC-115 CLOSED | **FAKE_CLOSE** | Wrong-victim / deferred-VA proof |
| RC-111 / RC-113 CLOSED | **PARTIAL** | Code real; surface/proof debt |
| Wave-3 UI lies (C3/U3/U4/H2) | **OUTSTANDING** | multi-writer, `live ·`, `#ct-conf`, gamma raw spot |
| LP-01 Operator NOW | **OUTSTANDING** | All 5 sub-items open |
| Decide under WAIT | **OUTSTANDING** | Horizon LONG/SHORT when `!tradeable` |
| Repo **finished** | **REJECT** | — |

---

## Bucket scorecard (final)

| Bucket | Grade | One line |
|---|---|---|
| MONEY_PATH | **REJECT finished** | W3-C8 FAKE_CLOSE; C1 dual books OUTSTANDING; C2 PARTIAL |
| COLLECT_AUTH | **OUTSTANDING** | No `record_quote` on carry-forward; QSD stripped in merge |
| UI_CONSOLE_CHART | **REJECT finished** | W3-C3/U3/U4 + W1-H2 live; RC-110 FAKE_CLOSE |
| LEVELS_TERRAIN | **REJECT finished** | Dual-book paint; RC-115 FAKE_CLOSE; LM under `#main` |
| LP01_LIQUIDITY | **OUTSTANDING** | VP dump + calendar overnight + hidden map; still NEXT |
| DB_STORAGE | **HONEST REOPEN / DEFECT LIVE** | 1,097 blobs; migrate re-ADDs |
| LOCKS_GOVERNANCE | **PARTIAL / THEATER** | RC-106 tag theater; `verify_dead --check` ∉ `CHECKS` |
| DECIDE_ADMISSION | **OUTSTANDING** | Pills under WAIT (W3-C5) |
| FIND_PROVE_SCIENCE | **OPEN remainder** | RC-107 / RC-58 OPEN |

---

## MONEY_PATH + COLLECT_AUTH ([Money-path v10](f3a3b901-271c-4032-9f5d-db30da95d03f))

| Claim | Grade | path:line |
|---|---|---|
| W3-C8 every `_fetch_state` quote → memo | **FAKE_CLOSE** | `:6210` vs `:6228` |
| Structural “one legal site” test | **FAKE_CLOSE** | `tests/test_spot_authority_v1.py:401-407` (paren-form only) |
| RC-112 fast lane / resolve_spot | **FIXED** | `:3106` / `:563` |
| Market-context vendor faucet | **OUTSTANDING** | `:4171` → `market_context.py:657` |
| W3-C4 carry-forward `record_quote` | **OUTSTANDING** | `:3009-3079` never stamps plane |
| W3-C4 QSD in plane merge | **OUTSTANDING** | `live_market_plane.py:230-254` omits `quote_source_detail` |
| W3-C1 dual wall books | **OUTSTANDING** | analytics `kl_*` + terrain wide both painted |
| Math ≠ display | **PARTIAL** | `resolve_spot` vs `consoleSpot`/`_fastLaneSpot` |

Exact `server.py` counts this turn: legal paren `_safe_get_quote_with_retry(` outside def = **1** (inside memo); bare REF bypasses live = **2** (`:6228`, `:4171`); `_memoized_quote_response(` sites = **7**.

---

## UI / LEVELS ([UI/walls v10](67755ca0-f396-496d-8587-6b4470f92099))

| CLOSED RC | Grade |
|---|---|
| RC-110 | **FAKE_CLOSE** (KDS/LVP pins ≠ call-wall/flip victims) |
| RC-111 | **PARTIAL** |
| RC-113 | **PARTIAL** |
| RC-115 | **FAKE_CLOSE** (“next restart” under CLOSED; nearest-strike box) |

Wave-3 UI still live: `#cv2-hd-px` writers `:6470/:13057/:13222/:13265`; footers `:13089/:13491`; `#ct-conf` `:13441` vs `#ct-trust` `:13458`; gamma `:13313`.

---

## LOCKS / DECIDE / LP01 / DB ([Locks/Decide/LP01/DB v10](f572af15-23d3-4029-9278-8694d93414dc))

| Claim | Grade |
|---|---|
| RC-6 reopen honesty | **GOOD** |
| Schema lock vs re-ADD | **ABSENT** |
| LP-01 all 5 | **OUTSTANDING** |
| Decide pills under WAIT | **OUTSTANDING** (`index.html:5331-5348`) |
| Close-contract / verify_dead | **THEATER** |
| RC-107 / RC-58 | **OPEN** |

---

## Top burn after audit (operator pick still required)

1. **P0a money:** wire `_cq_pool.submit` → `_memoized_quote_response`; fix paren-only test to catch refs (`:6228`).  
2. **P0 UI clocks:** one `#cv2-hd-px` writer; honest footers; `#ct-conf` demotion; gamma via `consoleSpot`.  
3. **Or program-legal:** LP-01 VP `[L,H]` first.  
4. **DB:** forbid normalized blob re-ADD (schema lock).  
5. **Decide:** blank direction under `!tradeable`.

---

## Status line

`CLAIM: REJECT finished @ e995e665 — SYNTHESIZED 3/3; W3-C8 FAKE_CLOSE (6228 + green theater test); RC-110/115 FAKE_CLOSE; RC-6 1097/187193762 lock ABSENT; LP-01 NEXT · DONE: v10 · NEXT: operator burn pick P0_CLOCKS | LP-01 | DECIDE · BLOCKER: none for audit`
