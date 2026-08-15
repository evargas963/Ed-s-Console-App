# BRUTAL ADVERSARIAL AUDIT v13 — 2026-07-28 ~13:35 CT

**HEAD:** `c7c65431` — `v12 residuals: as-of stamps the DATA clock; writer lock bans the ACTION.`  
**Prior:** v12 @ `0c1da1af` · REJECT finished; REJECT RC-117 CLOSED → PARTIAL  
**Method:** reaudit of claimed v12 residual close + residual surface · **SYNTHESIZED 2/2**  
**Verdict:** **REJECT “finished”** (repo) · **REJECT RC-117 CLOSED** → **PARTIAL** · as-of **FIXED** in code (unbound by test)

| Agent | Status |
|---|---|
| [RC-117 close reaudit](0449af9d-a291-4b6d-8aef-9a151f6aeb0e) | **MERGED** |
| [Residual surface](fb7ab31e-37f2-4c6c-8f76-6135e2f2aa75) | **MERGED** |

Claude’s commit scopes **v12 residuals only** (as-of + writer lock) — not repo finish. Touches: `static/index.html`, faucet test, RC-117 row.

---

## Headline

| Claim | Grade | Evidence |
|---|---|---|
| Footer as-of ≠ paint wall-clock | **FIXED** | `:13101-13105`, `:13533-13535` |
| As-of = “chain fetch” (commit prose) | **OVERCLAIM** | `_time.time()` compute (`terrain_engine.py:416`) + cache overwrite (`server.py:10712`) |
| Writer lock “bans ACTION” | **PARTIAL / THEATER** | Same-line co-occurrence; real writer `:6489` has no `cv2-hd-px` on that line |
| As-of test-bound | **ABSENT** | Still only `levels_stale` in footer window |
| `#tv-stamp` wall-clock | **OUTSTANDING** | `:12131` |
| Four clocks runtime | **FIXED** | C3/U3/U4/H2 paint paths |
| RC-117 CLOSED | **REJECT → PARTIAL** | Never demoted; lock/as-of bind fail |
| Repo **finished** | **REJECT** | Residuals below |

Client faucet **14/14** (structural).

---

## RC-117 close ([RC-117 close reaudit](0449af9d-a291-4b6d-8aef-9a151f6aeb0e))

| Claim | Grade |
|---|---|
| Runtime one `#cv2-hd-px` writer | **FIXED** |
| Lock bans any assignment | **REJECT / THEATER** |
| As-of data clock (named footers) | **FIXED** / **UNBOUNDED** by test |
| Fail-open `live` when `levels_stale` falsy | **PARTIAL residual** |
| Honest CLOSED stamp | **REJECT → PARTIAL** |

---

## Residuals ([Residual surface](fb7ab31e-37f2-4c6c-8f76-6135e2f2aa75))

| Victim | Grade | Proof |
|---|---|---|
| W3-C4 record_quote / QSD | **OUTSTANDING** | Carry-forward no `record_quote`; merge omits QSD |
| W3-C1 dual wall books | **OUTSTANDING** | `kl_*` + terrain walls both painted |
| Decide per-horizon under `!tradeable` | **OUTSTANDING** | LONG/SHORT + dim (`:5343-5348`) |
| LP-01 | **OUTSTANDING / NEXT** | VP dump; calendar overnight; LM under `#main`; Operator NOW |
| RC-6 | **LIVE / lock ABSENT** | exact **1,097** / **187,193,762** B; `db.py` re-ADD |
| `verify_dead` ∉ CHECKS | **THEATER** | 39 ENFORCED |
| RC-107 | **OPEN** | due 2026-08-07 |

---

## Bucket scorecard (final)

| Bucket | Δ vs v12 | Grade |
|---|---|---|
| UI four clocks + as-of | **up** | runtime **FIXED**; stamp **PARTIAL**; locks **THEATER** |
| COLLECT_AUTH / C1 / Decide / LP01 / DB / science | flat | **OUTSTANDING / THEATER** |

---

## Top burn

1. Demote RC-117 → **PARTIAL** or seal as-of bind + real writer lock, then re-close.  
2. **LP-01** (Operator NOW) or **P0b** plane (C4 + C1).  
3. Decide per-horizon sieve under `!tradeable`.  
4. RC-6 schema lock.

---

## Status line

`CLAIM: REJECT finished @ c7c65431 — SYNTHESIZED 2/2; REJECT RC-117 CLOSED→PARTIAL; as-of FIXED unbound; lock theater; residuals intact · DONE: v13 · NEXT: operator burn · BLOCKER: none`
