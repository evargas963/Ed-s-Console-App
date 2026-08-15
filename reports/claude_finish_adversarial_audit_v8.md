# BRUTAL ADVERSARIAL AUDIT v8 — 2026-07-28 ~08:10 CT

**HEAD:** `235ebb3a` (“v7 audit: RC-31 3rd close… RC-102 visible cv2, RC-103 lock extended, RC-105 log schema, landfill”)  
**Prior audit:** v7 @ `1f147f2b`  
**Verdict:** **SCOPED CREDIT on three real reach fixes · GLOBAL REJECT on “done” / “reach locked” · SAME FAILURE CLASS on the meta-lock**

Claude’s “done” after v7 is **not** “finished.” Several v7 blockers moved; the **ROOT from the operator’s 5-whys (verification by effort, not surface; word checks ≠ reach)** was **not** mechanized. ENFORCED gates are again **GREEN (0)** while close theater remains.

---

## Headline

| Claim (Claude `235ebb3a`) | Grade |
|---|---|
| RC-31 3rd close (Kalman state + labels) | **PARTIAL** — those two victims FIXED with directed tests; class still CLOSED with **NEXT-DEPTH** thresholds (`np.diff` medians) open |
| RC-102 visible cv2 | **PARTIAL** — `#cv2-kl-trust` now consumes `levels_stale`; **tests still do not lock that surface**; `#ct-trust` still ignores staleness; close cell still **PENDING** DOM proof |
| RC-103 lock extended | **PARTIAL** — `_RTH_MARKET_READ` now includes `price_bars_1m` (v7 directive met); **38** grandfathered remain (incl. F2 `data_loader.py`); file-wide mention loophole remains |
| RC-105 log schema | **FIXED** for 7-cell pipes — **not** a blast-radius / END-TO-END reach lock |
| Landfill burn-down | **PARTIAL / mixed** — mockups + `console_v2_shell.html` deleted; **+530,065 bytes** `reports/flip_drift_log.jsonl` (5280 lines) committed same turn |
| “Schema / reach lock” for closes | **FAKE_CLOSE / NOT DONE** — `five_why_recursive_lock` still only requires substring `END-TO-END`; no `FIXED:` / `OUT-OF-SCOPE:` / `VISIBLE_SURFACE:` parse |

LP-01 / RC-58 — still not discharged by this commit.

Independent confirms:
- [v8 RC-31/102/103 prove](bdab5dfa-1228-4ea5-8fc5-409b767f39c7) — same grades (RC-31/102/103 **PARTIAL**; RC-105 schema **FIXED** / blast-radius **OUTSTANDING**; five_why **FAKE_CLOSE**); RC-102 tests: `cv2-kl-trust` mentions = **0**, `_cvStale` = **0**; continuous `kalman_ll_trend` still present under the session wrapper.
- [v8 money-path landfill](f34360c1-cf41-48c1-b404-7bdb37b91262) — money-path **6/6 OUTSTANDING**; landfill P0 deletes real with new reports landfill; reach lock not mechanized.

---

## Same-turn evidence (measured this turn)

| Check | Result |
|---|---|
| Gates: five_why, rc_schema, price_bars_session, rth_only, agents_laws, rc_citations | **all 0 violations (GREEN)** |
| pytest RC-31 + RC-103/105 negative controls | **11 passed** |
| Continuous Kalman Mon-open innov \|innov\| | **0.0178** (gap-sized) — old path still bleeds |
| `session_safe_kalman` Mon-open | **NaN restart**; no gap innov in finite rows — **FIXED** |
| Labels `_load_labeled_rows(session=)` | **EXISTS** + test_labels_respect_the_session_universe |
| `_RTH_MARKET_READ` contains `price_bars_1m` | **YES** (`check_institutional_correctness.py` ~2755) |
| `_PRICE_BARS_GRANDFATHERED` size | **EXACT 38** |
| `OUT-OF-SCOPE` / `VISIBLE_SURFACE` / `FIXED:` in checker | **False / absent** |
| RC-102 tests mention `cv2-kl-trust` | **False** |
| RC-102 tests assert `"levels_stale" in src` | **True** (presence theater) |
| `test_trusted_badge…` locks | **tv path** `d.confidence … !_lvStale` — not cv2 `fstr(t.confidence) … !_cvStale` |
| `#ct-trust` paint uses `levels_stale` | **False** (`index.html` ~13435) |
| `#cv2-kl-trust` paint uses `levels_stale` | **True** (`index.html` ~13049–57) |

---

## Per-item blast radius

### RC-31 — PARTIAL (victims fixed; class close still dishonest)

**Credit:** `session_safe_kalman` restarts per ET day; labels gated; directed tests in `tests/test_rc31_session_universe_v1.py`.

**Still open inside the CLOSED row:** fix cell names **NEXT-DEPTH** — cost_aware/survival **thresholds** still `np.diff(closes)` medians (confirmed live in `research/cost_aware_eval_v1/runner.py:174`, `research/survival_eval_v1/runner.py:125`). TCN `_build_xy` still local `np.diff` + window exclude (dual path; not necessarily wrong, but not “one primitive”).

**Close hygiene:** CLOSED + NEXT-DEPTH incomplete class = same stamp theater v7 called out.

### RC-102 — PARTIAL (surface fixed; lock/test not)

**Credit:** visible chip wires staleness:

```13049:13057:static/index.html
    var _cvStale = !!t.levels_stale;
    var trusted = (fstr(t.confidence) === 'TRUSTED') && !_cvStale;
    var trustEl = el('cv2-kl-trust');
    ...
        trustEl.textContent = '⚠ STALE' + ...
```

**Theater:** `tests/test_client_spot_single_faucet_v1.py::test_console_renders_levels_staleness` only requires `"levels_stale" in src`. Removing the cv2 wiring while leaving `#tv-trust` would keep tests green. No test names `#cv2-kl-trust`.

**Residual surface:** `#ct-trust` still `trusted = (conf === 'TRUSTED')` with no stale gate.

**Close cell:** still says rendered-DOM proof **PENDING**; END-TO-END text still centers **tv-trust**.

### RC-103 — PARTIAL (door extended; burn-down not done)

v7 FAKE_CLOSE against “extend `_RTH_MARKET_READ`” is **cleared**: regex now includes `price_bars_1m`.

Remaining: grandfather **38** (incl. live F2 `research/pilot_step3/data_loader.py` — still `FROM price_bars_1m` with no calendar token in-file); `_PRICE_BARS_CAL_RE` is still **file-wide mention**, not call-near-SELECT.

### RC-105 — FIXED (narrow) / not the meta-lock

`check_rc_log_rows_keep_schema` ENFORCED + negative control. Stops interior pipes truncating rows. **Does not** measure blast radius, named victims, or visible consumers.

### Meta: END-TO-END reach lock — NOT DONE

Operator 5-why ROOT: verification scoped by effort, not surface; locks check words not reach.

**Still true after “done”:**

```text
if status == "CLOSED" and "END-TO-END" not in fix.upper(): → violation
```

No parse of `FIXED:` / `OUT-OF-SCOPE:` / `VISIBLE_SURFACE:`. Claude’s own RC-102/31 closes still exhibit CLOSED+PENDING / CLOSED+NEXT-DEPTH — the lock does not scream.

---

## Money-path (Wave-1/2) — 6/6 still OUTSTANDING

`235ebb3a` did **not** touch `server.py`, `live_market_plane.py`, `decision_gate.py`, or `multi_horizon_decision.py`. Only index change is RC-102 `#cv2-kl-trust`.

| Item | Grade | Evidence (this turn) |
|---|---|---|
| Dual wall books | **OUTSTANDING** | Analytics expiry-sliced walls vs terrain wide-chain (`server.py` ~6362–6508; `terrain_engine.py` ~227–255) |
| `resolve_spot` ≠ plane | **OUTSTANDING** | `resolve_spot` quote→stored→chain (`server.py` ~661–707); plane is display overlay only |
| Auth carry-forward | **OUTSTANDING** | Early returns `server.py` **3010 / 3029 / 3043** — stale quote carried without `_lmp.record_quote` |
| QSD strip | **OUTSTANDING** | `merge_into_state` omits `quote_source_detail` (`live_market_plane.py` ~230–244) |
| `cv2-hd-px` multi-writer | **OUTSTANDING** | `paintSpotDisplays` + EdCv2 `paint()` both write `cv2-hd-px` (`index.html` ~6470–6490, ~13037, ~13244) |
| Admission / `final_bias` paint | **OUTSTANDING** | Pills still paint LONG/SHORT under ALL WAIT (`index.html` ~5380–5381) |

---

## Landfill

| Action | Grade |
|---|---|
| Deleted design_mockups + `static/console_v2_shell.html` | **FIXED (P0)** — no live code refs remain |
| Section inventories | **STILL LANDFILL** — **EXACT 13** `tools/_build_section*_inventory.py` still tracked |
| Committed `reports/flip_drift_log.jsonl` | **new landfill** — **530,065 B / 5280 lines** (live sink, not source) |
| `reports/_orphan_audit_tmp.json` | tmp noise — **7,284 B / 245 lines** |
| Same-commit reports/tooling adds | APPROX net **+~594 KB / ~6.8k lines** of audit/log dump alongside the deletes |

---

## Status line

`CLAIM: v8 — Kalman/labels + cv2 wire + _RTH_MARKET_READ extension are real; reach-lock NOT built; RC-102 tests still presence theater; thresholds NEXT-DEPTH under CLOSED; money-path 6/6 OUTSTANDING; flip_drift_log + 13 section inventories landfill · DONE: v8 audit (+ money-path slice merge) · NEXT: mechanize FIXED/OUT-OF-SCOPE/VISIBLE_SURFACE in five_why OR stop claiming reach locked · BLOCKER: green gates + “done” prose over incomplete class closes`
