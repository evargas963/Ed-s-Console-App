# BRUTAL ADVERSARIAL AUDIT v12 — 2026-07-28 ~13:27 CT

**HEAD:** `0c1da1af` — `RC-117 CLOSED: the four UI lying clocks (P0_CLOCKS burn, W3-C3/U3/U4/H2).`  
**Prior:** v11 @ `5d82adce` · REJECT finished  
**Method:** bucket reaudit · **SYNTHESIZED 2/2**  
**Verdict:** **REJECT “finished”** · **REJECT RC-117 CLOSED** → should be **PARTIAL** (W3-U3 as-of incomplete + weak lock)

| Agent | Status |
|---|---|
| [RC-117 UI audit](f3102b69-a206-4162-9424-f250c2f4b574) | **MERGED** |
| [Residual blockers](5c2db289-a058-4376-9dca-ffeea42ab816) | **MERGED** |

Authority = committed tree. Any dirty WT as-of patch is post-CLOSE confession, not the CLOSED stamp.

---

## Headline

| Claim | Grade | Evidence |
|---|---|---|
| W3-C3 one value-writer | **FIXED** (code) / **PARTIAL** (lock) | `paintSpotDisplays` `:6470-6489`; lock only bans `T('cv2-hd-px'` non-null |
| W3-U3 “live” earned | **FIXED** (word) | `levels_stale` gate `:13094-13097`, `:13522-13525` |
| W3-U3 as-of honesty | **OUTSTANDING** | Still wall-clock `new Date().toLocaleTimeString` — P0c unmet |
| W3-U4 `#ct-conf` | **FIXED** | `:13458-13471` paired with `#ct-trust` |
| W1-H2 gamma | **FIXED** | `consoleSpot(t)` `:13327` |
| RC-117 CLOSED stamp | **REJECT → PARTIAL** | END-TO-END overclaim while as-of lies; test bind theater |
| Repo **finished** | **REJECT** | Residuals below |

Client faucet tests same-turn: **14/14** (structural only).

---

## RC-117 UI ([RC-117 UI audit](f3102b69-a206-4162-9424-f250c2f4b574))

| ID | Grade | path:line |
|---|---|---|
| W3-C3 | **FIXED** (value-race) | `:6470-6489`, triggers `:13060/:13276`; clear `:13231` |
| W3-U3 | **PARTIAL** | live word FIXED; as-of lie `:13099`, `:13525`; fail-open `!levels_stale`→live; QSD untouched |
| W3-U4 | **FIXED** | `:13458-13471` vs `:13488-13501` |
| W1-H2 | **FIXED** | `:13327`, `:13394`; zero `fnum((t\|\|{}).spot)` |
| Test lock | **THEATER / WEAK** | `test_client_spot_single_faucet_v1.py:190-211` — T()-only, `"null" in ln` exemption, no as-of assert, gamma unguarded |

---

## Residuals ([Residual blockers](5c2db289-a058-4376-9dca-ffeea42ab816))

RC-117 commit scoped to four clocks only. Untouched plane/DB/LP-01/Decide/gate.

| Victim | Grade | Evidence |
|---|---|---|
| W3-C4 record_quote / QSD | **OUTSTANDING** | Carry-forward no plane stamp; merge omits QSD |
| W3-C1 dual wall books | **OUTSTANDING** | `kl_*` + terrain walls both painted |
| Decide pills under `!tradeable` | **OUTSTANDING** | Per-horizon LONG/SHORT + dim (`:5343-5348`); only ALL consolidated blanks |
| LP-01 | **OUTSTANDING / NEXT** | VP dump; calendar overnight; LM under `#main`; Operator NOW |
| RC-6 | **LIVE / lock ABSENT** | exact **1,097** / **187,193,762** B |
| `verify_dead` ∉ CHECKS | **THEATER** | 39 ENFORCED |
| RC-107 | **OPEN** | due 2026-08-07 |

---

## Bucket scorecard (final)

| Bucket | Δ vs v11 | Grade |
|---|---|---|
| UI four clocks (named) | **up** | C3/U4/H2 **FIXED**; U3 **PARTIAL** |
| RC-117 CLOSED honesty | — | **REJECT → PARTIAL** |
| COLLECT_AUTH / C1 / Decide / LP01 / DB / locks | flat | **OUTSTANDING / THEATER** |

---

## Top burn after v12

1. Reopen RC-117 to **PARTIAL** (or finish as-of + seal writer lock) then re-close.  
2. **LP-01** (Operator NOW) or **P0b** plane (C4 + C1).  
3. Decide per-horizon sieve under `!tradeable`.  
4. RC-6 schema lock.

---

## Status line

`CLAIM: REJECT finished @ 0c1da1af — SYNTHESIZED 2/2; REJECT RC-117 CLOSED (→PARTIAL: wall-clock as-of + weak lock); C3/U4/H2 FIXED; residuals intact · DONE: v12 · NEXT: operator burn · BLOCKER: none`
