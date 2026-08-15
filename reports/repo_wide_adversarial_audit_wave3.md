# BRUTAL REPO-WIDE ADVERSARIAL AUDIT — WAVE 3

**When:** 2026-07-28 ~10:40 CT  
**HEAD:** `90048e5e` (+ dirty: `root_cause_log.md`, `chart.html`, `terrain_engine.py`)  
**Prior canopy:** wave1/wave2 (2026-07-27) · finish audits v1–v9 · `spot_faucet_full_audit_v1.md`  
**Machine JSON:** `reports/repo_wide_adversarial_audit_wave3.json`  
**Verdict:** **NOT PRISTINE · NOT FINISHED · SCOPED CREDIT since wave2 · GREEN LOCKS ≠ HONEST REACH**  
**Status:** **SYNTHESIZED** (5/5 canopy slices merged)

---

## Headline

The fortress of ENFORCED locks is greener and denser (39 ENFORCED). Several real defects closed (vendor quote memo, chart spot tick, close-contract schema, Kalman/labels, RTH regex reaches `price_bars_1m`). The **money-path dual books**, **display/math spot split**, **multi-writer header**, **auth/QSD plane holes**, **Decide admission blob**, and **Operator NOW LP-01** are still open. Parallel canopy slices are merging into this file (see agents below).

Independent slices:

| Slice | Status | Agent |
|---|---|---|
| Money path | **MERGED** | [W3 money-path canopy](8b492ede-5fa9-4c4e-8394-99f23166c1b1) |
| Locks / governance | **MERGED** | [W3 locks governance](5cf8567e-e372-4613-90f5-c319321a5a3d) |
| UI / client | **MERGED** | [W3 UI client canopy](524c3abb-ed8b-484e-84a2-277e166ebf29) |
| Collect / Decide / ML | **MERGED** | [W3 collect decide ML](9228b55e-b6c6-475b-aecb-d09c0da45939) |
| Landfill / dead code | **MERGED** | [W3 landfill deadcode](a27c62a3-64eb-4ab4-9814-940183f37ef4) |

---

## Same-turn mechanical census (proven this turn)

| Metric | Exact |
|---|---|
| ENFORCED / ADVISORY checks | **39** / **7** |
| Sampled gates (five_why, schema, price_bars, rth, citations, agents_laws, single_spot, root_cause_log) | **all 0 violations** |
| `data_faucet_audit` violations | **0** |
| `_PRICE_BARS_GRANDFATHERED` | **38** |
| OPEN RC | **RC-58**, **RC-107** |
| PARTIAL RC | **RC-102**, **RC-113**, **RC-115** |
| REMEDIATED | **RC-55** |
| `tools/_build_section*_inventory.py` | **13** |
| `tests/archive` test files | **16** |
| `design_mockups/` / `console_v2_shell.html` | **absent** (deleted) |

**Dirty tree note:** RC-113/115 wall-range work is PARTIAL in the log with uncommitted `terrain_engine.py` + `chart.html` (+92/−2). Do not treat wall ranges as committed-complete.

---

## Credit since wave2 (real)

| Item | Grade |
|---|---|
| RC-112 vendor quote memo (AUDIT-QUOTE-MEMO) | **FIXED** |
| RC-106 close-contract tags + stop_guard | **PARTIAL** (presence/cutover holes — v9) |
| RC-108 token countdown | **FIXED** (claimed; not re-blasted this seed) |
| RC-110/111 chart off-scale + gamma spot frame | **FIXED** |
| RC-31 Kalman session + labels | **FIXED** (thresholds → RC-107 OPEN) |
| RC-103 `_RTH_MARKET_READ` includes `price_bars_1m` | **FIXED** door; burn-down **PARTIAL** |
| RC-102 visible trust chips (code) | **PARTIAL** (DOM proof owed) |
| Landfill mockups/shell | **FIXED**; 13 section inventories remain |

---

## Critical canopy (merged grades)

| ID | Area | Title | Grade | Evidence |
|---|---|---|---|---|
| W3-C1 | money | Dual wall/flip books | **OUTSTANDING** | Analytics expiry-sliced `kl_*` vs terrain `wide_chain` ([money-path](8b492ede-5fa9-4c4e-8394-99f23166c1b1)) |
| W3-C8 | money | Tier C `_fetch_state` bypasses quote memo | **OUTSTANDING (NEW CRITICAL)** | `server.py:6210/6228` `_safe_get_quote_with_retry` while fast lane uses memo |
| W3-C2 | money | Math `resolve_spot` ≠ display plane | **PARTIAL** | RC-112 memo shared; stream/overlay/fallback can still diverge |
| W3-C3 | UI | `cv2-hd-px` multi-writer + gamma `t.spot` | **OUTSTANDING** | `T('cv2-hd-px'` ×3; `index.html:13313` raw `t.spot` |
| W3-C4 | Collect | Auth carry-forward + QSD strip | **OUTSTANDING** | No `record_quote` on carry-forward; `merge_into_state` omits QSD (+ L1 sibling) |
| W3-C5 | Decide | Admission blob + `final_bias` / pills under WAIT | **OUTSTANDING** | [collect/decide](9228b55e-b6c6-475b-aecb-d09c0da45939): `the_call` blob; MH keeps `final_bias`; pills keep LONG/SHORT when `!tradeable` |
| W3-C6 | Program | **LP-01 NEXT untouched** | **OUTSTANDING** | `ACTIVE_PROGRAM.md` Operator NOW |
| W3-C7 | Locks | Close contract / dead_code / Cursor hooks | **PARTIAL_THEATER** | [locks](5cf8567e-e372-4613-90f5-c319321a5a3d): FIXED presence-only; **66** pre-cutover CLOSED lack `FIXED:`; `--check` not in CHECKS; no `.cursor/hooks.json` |
| W3-C9 | Decide/ML | Unproven ML + 5c “winning stack” + RC-6 re-ADD | **OUTSTANDING** | W2-C5/C6/C7 still live (`db.py` ADD COLUMN; `ml_predict` hardcoded 5c stack) |

Spot detail: `reports/spot_faucet_full_audit_v1.md` (same HEAD).

### UI slice extras ([UI](524c3abb-ed8b-484e-84a2-277e166ebf29))

| ID | Grade | Note |
|---|---|---|
| RC-110/111 chart | **FIXED** (code) | Off-scale pins + gamma spot re-tick |
| RC-102 / RC-113 | **PARTIAL** | DOM/screenshot proof owed |
| W1-C5 hidden `#terrain-view` | **OUTSTANDING** | Still polled while `display:none` |
| W3-U3 footer lying clock | **OUTSTANDING** | `cv2-f-status` / `ct-foot-status` hardcode `live ·` |
| W3-U4 `#ct-conf` vs `#ct-trust` | **OUTSTANDING** | Raw TRUSTED beside demoted stale chip |
| W3-U1 nested `fnum((t\|\|{}).spot)` | **OUTSTANDING** | Faucet audit regex blind |

`audit_client()==0` is **non-exonerating** for multi-writer / nested-fnum.

### Collect/Decide extras ([collect/decide](9228b55e-b6c6-475b-aecb-d09c0da45939))

- **FIXED:** RC-108 token countdown; scorecard **producer** cadence (schtask Last Result 0)  
- **PARTIAL:** RC-58 producer gates (re-validate owed); W2-C8 door + 38 grandfather  
- **OUTSTANDING HIGH:** MH `max(confluence,4)` forge; meta in-sample OOF fallback  

### Locks slice extras (merged)

- RC census: **113** rows → CLOSED 107 / OPEN 2 / PARTIAL 3 / REMEDIATED 1  
- OPEN_ITEMS zombies: FULLCHAIN `[ ]` vs FP-66 DONE; GREEK `[~]` vs FP-65 DONE  
- Negative-control grandfather: **22**

### Money-path pristine blockers (merged)

1. One wall/flip book (W3-C1)  
2. One display clock (W3-C3) + footers/conf honesty (W3-U3/U4)  
3. Plane honesty under auth + QSD (W3-C4)  
4. Memo continuum incl. Tier C (W3-C8)  
5. Declared dual-leg or true single faucet in audit (W3-C2 / W3-U1)

---

## Pristine program (updated)

1. **P0** — Lying clocks: multi-writer spot, footers, QSD/auth plane, Tier C memo, RC-102 DOM  
2. **P1** — One wall book + one spot semantic  
3. **P2** — Decide sieve + kill exposure/pill paint under WAIT + no 5c hardcoded stack  
4. **P3** — **LP-01** (Operator NOW — binding)  
5. **P4** — Close-contract reach + wire `verify_dead --check` + Cursor hooks  
6. **P5** — RC-58 revalidate · RC-107 thresholds · 38 grandfather · RC-6 re-ADD  
7. **P6** — Landfill: **PARTIAL** — `deletable_now=0`; 20 provenance-blocked (13 section inventories); reports recurse **467**; archive **99** test fns; mockups/shell **gone**

### Landfill slice ([landfill](a27c62a3-64eb-4ab4-9814-940183f37ef4))

| Surface | Exact |
|---|---|
| Section inventories | **13** tracked (still) |
| `deletable_now` | **0** (orphan gate empty) |
| Provenance-blocked | **20** |
| RC-100/104 | CLOSED rows; burn-down **PARTIAL** residual |
| `reports/` recurse | **467** files |
| `flip_drift_log.jsonl` | gitignored; on-disk sink remains |

Blind delete of section inventories / mega / research eval packs = **blocked** (ledger co-retirement required).

---

## Status line

`CLAIM: wave3 SYNTHESIZED 5/5 — NOT pristine; P0 lying clocks + Tier C memo + dual wall books; P2 Decide sieve; P3 LP-01; locks tag theater; landfill PARTIAL with deletable_now=0 · DONE: full canopy merge · NEXT: operator picks P0 vs LP-01 · BLOCKER: green gates ≠ finished repo`
