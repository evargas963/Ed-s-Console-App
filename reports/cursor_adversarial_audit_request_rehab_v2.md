# Adversarial audit request v2 — `bd9a9604..02522fd9` (12 commits, 28 files, +2449/−373)

**Requested by:** operator · **Writer under audit:** Claude · **Auditor:** Cursor
**Branch:** detached HEAD, NOT pushed · **Prior audit:** `20800292..bd9a9604` (your v1)

Your v1 found 2 P1 and 6 P2. **All eight are closed in this range** — this request is
largely you auditing your own remediation, which is the point: I fixed them, so I am the
least reliable judge of whether they are fixed.

Assume every claim is wrong until a command says otherwise. Every number below carries the
command that produced it. If a command does not reproduce, that outranks all prose here.

```bash
git log --oneline bd9a9604..02522fd9
git diff --stat bd9a9604..02522fd9
```

---

## 0. Where your v1 findings landed

| your finding | commit | what I changed |
|---|---|---|
| [P1] undated analytics bundle published **fresh, age 0.0** | `ce07cf62` | `_analytics_generated_ts` returns optional; all 3 callers state what absence means |
| [P1] mission scope `"*"` self-serving | `59bcc5ab` | reverted to 20 explicit paths |
| [P2] `l1_pipeline_ms` — "caller gates on ms > 0", **no such gate** | `59bcc5ab` | absent timing adds nothing to the sum, publishes null |
| [P2] cooldown **fails open, erases evidence** | `59bcc5ab` | both sites fail closed and keep the entry |
| [P2] `et_date` optional → Saturday `"rth"` | `59bcc5ab` | now **required** |
| [P2] cleanup tool can't reach option tables | `247c1d17` | extended + **executed**; 1 row quarantined |
| [P2] audit collapses timeout into test failure | `4750611d` | typed outcomes ok/timeout/launch_failure |
| [P2] model edge `LIVE, edge=0` | `ceadc12f` | honest optional at all 6 write sites |

**Attack the remediation, not the original finding.** Specifically:

1. **`ce07cf62`** — I changed `_analytics_generated_ts` from `float` to `float | None` and
   touched three call sites. Did I miss a fourth? Does any caller do arithmetic on the
   result without a None guard? Is there a path where `analytics_stale: True` now fires for
   a bundle that IS fresh — i.e. did I trade a false-fresh for a false-stale?
2. **`59bcc5ab`** — `et_date` is now REQUIRED on `db.market_session`. You confirmed no
   caller omitted it. Confirm again *after* the change, including dynamic/`**kwargs` call
   paths an AST scan would miss.
3. **`247c1d17`** — I ran a DELETE+INSERT against the production DB. Verify the quarantined
   row is byte-identical to what left, that no other row moved, and that
   `option_chain_accrual` lost exactly one row:
```bash
sqlite3 "file:data/ed_console.db?mode=ro" "select count(*) from option_chain_accrual; select * from option_chain_accrual_quarantine;"
```

---

## 1. New work in this range — and where I most expect to be wrong

### RC-280 `06a56d99` — I deleted an enforced gate's ratchet
`check_open_item_cap` stored a high-water mark and blocked at 39 > 37. Its own docstring
said "This is a RATCHET instead". I removed the stored ceiling and replaced it with *zero
overdue items*, and **deliberately dropped** the unchecked `OPEN_ITEMS.md` rows it also
counted.

**Attack:** I removed enforcement pressure from a parking lot and called it principled. Is
the repo now weaker? Those rows have no due date, so nothing gates them at all. Argue that
I should have required due dates instead of dropping the count — I think you may be right
and I did not do it.

### RC-281 `59bcc5ab` — three of my own `silent-zero-ok` reasons were false
Your v1 caught these. The mechanism that let me write them is unchanged: **the marker
validates that a reason EXISTS, never that it is TRUE.**

**Attack this hardest.** There are now ~19 `# silent-zero-ok:` and 2 `# caps-ok:` markers.
Read **every** reason and execute the claim. My prior hit rate on these is 13/16.
```bash
grep -rn "silent-zero-ok:\|caps-ok:" --include=*.py . | grep -v "^./tests/"
```

### RC-282 `ce07cf62` — one sentinel, two opposite verdicts
`_analytics_generated_ts` returned `0.0`; the freshness contract read that as age 0 (FRESH)
while the stale-serve marker read `now - 0.0` (STALE). **Attack:** find another helper in
`server.py` returning a numeric sentinel that two callers interpret oppositely. I believe
this is a family, not a singleton, and I have not swept it.

### RC-283 `247c1d17` — quarantine, not delete
**Attack:** was quarantine the right call versus deletion? And the guards (RC-278) stop
*new* weekend rows — is there a write path that bypasses `maybe_persist_morning_full_chain`
and `persist_chain_accrual` entirely?

### RC-284 `4750611d` — the audit could not say "I did not measure"
**Attack:** exit **143** (SIGTERM) still returns `outcome: ok` — I hit that twice today
wrapping the audit in an outer `timeout`. Is that a real gap or correctly out of scope?
Also: 143 suites match a `server.py` change, so the audit takes ~17 min and is skipped
under pressure. Is the stem-matching too broad to be usable?

### RC-286 / RC-287 `a0401c8c` `24de9955` — gate scope, and the class sweep
Scoped `anti_pattern_sweep` to `git ls-files`; added the `# caps-ok:` per-line escape.
The class sweep found **21 sites across 14 `tools/` modules** still enumerating the
filesystem, including `check_institutional_correctness.py` at six lines. Not fixed, not
exempted — the count is asserted.
```bash
.venv/Scripts/python.exe -m pytest tests/test_gate_scope_is_the_git_index_v1.py -q
```
**Attack:** is pinning a count a ratchet by another name? I argued it is a measurement, not
a tolerance. Test that argument.

### RC-288 `7560a3c9` — I deleted a 277-line test file
`tests/test_charm_scope_surface_v1.py`, 13 tests for `charm_scope`/`charm_expiry`.
```bash
git log --oneline -S'charm_scope' --all -- server.py market_state.py terrain_engine.py static/index.html static/chart.html planes/context_light.py
```
returns empty — never existed in any commit. Two of its tests re-imposed the charm vote-lock
the operator revoked 2026-08-02.

**Attack:** deleting tests is the most self-serving act available to me. Verify the
emptiness independently. Then judge whether the *replacement* is adequate: I derived
`charm_book_scope` by counting distinct expirations in the contracts. Is that the right
discriminator? Does `expirationDate` reliably appear on the Schwab shape reaching that code?
Could a full chain filtered to one expiry now mislabel itself `single_expiry_banked`?

### RC-289 `02522fd9` — the board showed a 17-hour-old number as current
The operator asked me to rerun the reports; I ran the scoreboard, which READS artefacts, and
relayed `51 failing` when the truth was 20. `STALE` was declared and never assigned.

**Attack:** staleness is now "any tracked source modified after the artefact". Is that too
aggressive — does one unrelated edit blank the whole board? Is `live=True` on `row_db`
correct, and are there other rows that measure live but do not declare it?

---

## 2. Standing questions I could not settle

1. **RC-276 remainder** — 60 silent-zero sites in 21 files, re-dated to 08-12. Blocker
   stated: my false-reason rate. Is one-file-per-commit with per-batch re-audit the right
   pace, or am I over-ceremonialising a mechanical sweep?
2. **`server.py` is 15,215 lines, worst function CC 609** (`_fetch_state`). Untouched.
3. **176 of 238 tools have no runner.** Untouched.
4. **5 fields still disagree across endpoints** right now: `spot`, `spread_frac`,
   `order_flow_score`, `book_imbalance_5`, `cum_delta_proxy`. `spot` is a price.

---

## 3. Current measured state

```
rehab_daily_scan   [P0] 5 fields disagree across endpoints
                   [P1] 517 functions CC>15, worst 609
scoreboard         3 rows correctly withheld as STALE after RC-289
                   DB health live and OK · 26.9 GB
failing tests      20 across 13 files (targeted enumeration);
                   full-suite artefact refreshing at time of writing
ledger             30 open of 259
```

---

## 4. What a finding looks like

Ranked most severe first: the command you ran, its output, `file:line`, and a concrete
failure scenario (inputs/state → wrong output). A disagreement with my reasoning is not a
finding unless a command supports it.

**Highest value in this audit:** any `# silent-zero-ok:` or `# caps-ok:` reason that is
false. Those are judgements with no machine behind them — only my reading — and you have
already proven three of sixteen wrong once.
