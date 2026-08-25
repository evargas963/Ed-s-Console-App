# Zero-Debt Work Law v1 — HISTORICAL RECORD (2026-08-02)

> **Not a standing binding MD (stamped 2026-08-25).** The live law is AGENTS.md
> "Find something broken → fix it"; the `tools/log_law.py` mechanism this file once cited is
> retired (`governance/retired_checks.md`). Kept as the dated record of the law's original
> wording — do NOT cite this file as authority; cite AGENTS.md.

| | |
|---|---|
| **STATUS** | **OPERATOR LAW — effective now** (spoken 2026-08-02) |
| **Binding agents** | Claude and Cursor — standing MD; follow on every fix/update/build |
| **Enforcement this turn** | **MD + operator review** (no new gate script shipped here — see §9 NEXT) |
| **Decide** | No decision-path admissions from this document |

---

## 1. Operator law (verbatim intent)

> Claude has a huge root cause log. We cannot have logs of things that are wrong or broken — these items need to be brought to the surface and fixed. Whether it is a root cause log or some other list or log, we should not have any debt anywhere in the repo during any fixes, or updates.

Also prior (still binding): **do not lock-harden; make things work.**

---

## 2. Meaning

During any fix, update, or build, **do not accumulate or leave wrong/broken items as permanent parked debt** in:

- `governance/root_cause_log.md` (OPEN / PARTIAL used as a museum)
- `governance/unproven_register.md` (claims past due, or DISPROVED never remediated)
- `OPEN_ITEMS.md` / operator open-item lists
- TODO / FIXME / "known issues" prose treated as the finish line
- handoffs that declare Done while named victims stay broken

**Debt** here means a known wrong or broken thing that nobody is actively repairing and that is not honestly clock-blocked with a measurable unblock.

Epistemic rows that are honestly waiting for accrued data (UNPROVEN with a due + measurement plan) are **not** the same as product defects parked forever — but they still owe a clock and a NEXT action (see register law).

---

## 3. Required behavior (same authority window)

When a wrong/broken item is found or touched:

1. **Surface it** — name the victim (RC row, register row, OPEN_ITEMS bullet, DOM id, table, etc.).
2. **Fix it in the same authority window**, OR
3. **Only with explicit operator park:** write `OUT-OF-SCOPE:` with:
   - dated tracker (RC id and/or register row and/or OPEN_ITEMS pointer),
   - **NEXT** action (who/what),
   - **clock** (due ISO date or measurable unblock condition).

**Honest PARTIAL** is allowed for clock-blocked live proof (e.g. `NEXT_RTH_PROOF` + computed next RTH ISO date) **only** with a measurable unblock condition — not as a dumping ground for leftovers.

Closing language for a slice must not claim Done while broken victims remain in any log without that park contract.

---

## 4. Forbidden

- Closing a slice **Done** while leaving broken victims in the RC log, register, OPEN_ITEMS, or "known issues" prose.
- Growing `root_cause_log.md` with **OPEN** rows that nobody is fixing.
- Using the RC log as a **museum of failures** instead of a **repair ledger**.
- Quietly converting product incompleteness into process debt (new gate scripts, new lists, new "we should someday" files) instead of fixing the product.
- Mass-closing RC rows without reach proof (close contract still binds).

---

## 5. Relationship to the RC log

| Status | Meaning under this law |
|---|---|
| **CLOSED** | Reach proven (FIXED victims enumerated; close contract for post-2026-07-28 rows). |
| **OPEN** | Actively worked **or** operator-parked with date + NEXT + clock. |
| **PARTIAL** | Same — active work or honest clock-block with measurable unblock; not a shelf. |

Prefer **fix the product** over new process files. Prefer finishing OPEN/PARTIAL victims over opening sibling museum rows.

This law does **not** authorize mass-close. It forbids parking without a park contract.

---

## 6. Relationship to lock-harden — explicitly OUT

**Product fix > agent-lock arms race.**

This law is **not** a licence to invent more PreToolUse / commit gates as the primary response to debt. Prior operator direction stands: make things work.

Mandate-to-mechanism (RC-66 / AGENTS.md) still applies when the operator says **law** / **mandate** / **non-negotiable** — but for *this* law the chosen surface **for now** is this standing MD plus operator review, not a new gate farm. See §9 for the smallest optional NEXT check if detection is later required.

---

## 7. How other docs cite this file

Use one of:

```text
Zero-debt work law → reports/zero_debt_work_law_v1.md
```

```text
OUT-OF-SCOPE: <victim> — operator-parked under zero-debt law;
tracker: RC-NNN / OPEN_ITEMS / unproven_register; NEXT: …; clock: YYYY-MM-DD or UNBLOCKED-BY: …
POINTER: reports/zero_debt_work_law_v1.md
```

Handoffs / ACTIVE_PROGRAM / closeouts that leave debt must cite this file in the same breath as the park contract. Do not invent a parallel "debt backlog" document.

Governance pointer: one-liner in `governance/root_cause_log.md` (header) cites this file.

---

## 8. Product debt vs process debt (examples)

These illustrate the distinction — **not** an order to implement Chart this turn.

| Example | Class | What zero-debt requires |
|---|---|---|
| **Chart v6 build** (`ui_mockup_approvals` v6: candles + LINE + levels pulldown on existing Chart) | **Product debt** if approved redesign stays unfinished while OPEN Chart RC victims (e.g. off-scale walls, put/call framing, lying clocks) remain | Finish or operator-park with tracker + NEXT + clock; do not declare Chart Done |
| **Exposure overlay** (`reports/exposure_overlay_chart_direction_v1.md` — Heatseeker-class map; **not** v6) | **Future product direction** when marked NOT NOW — legal park only if pointer + status stay honest | Cite the direction doc; do not grow silent RC museum rows for it |
| **Collect window** (session completeness, non-trading writes, RTH labeling — e.g. RC-177/178/181 class) | **Product / Collect debt** | Surface → fix in-window or park with clock; banking ≠ Chart render Done (RC-163 chart-intent still binds) |
| New gate / PreToolUse / check script invented to "manage" the above without repairing victims | **Process debt** — usually the wrong response under this law | Prefer product repair; smallest detection only if operator later demands it (§9) |

Chart-intent reminder: Collect/accrual finish language cannot soft-out Chart render without an open P0/`CHART_CONSUMER` residual or proven consumer (`reports` / RC-163 family).

---

## 9. Mandate-to-mechanism — deferred smallest NEXT (not implemented this turn)

AGENTS.md mandate-to-mechanism would normally demand a mechanical lock the same turn a **law** is declared. Operator also hates lock bloat and ordered **documentation + inventory only** this turn, with **prefer the MD as the law surface for now**.

**NEXT (optional, smallest — implement only if operator later asks):**

- Soft warn (or commit WARN, not a sprawling PreToolUse) when a new `| RC-… | OPEN |` row is added without `UNBLOCKED-BY:` / `NEXT:` / due already in schema, **or**
- Inventory snippet in closeout: print OPEN+PARTIAL count; fail only if count rose with zero FIXED victims in the same diff.

Do **not** implement that gate in this turn unless the operator explicitly asks. Detection absence is not a licence to park debt — the law still binds.

---

## 10. Same-turn inventory (2026-08-02) — exact parse

**Method:** parse `governance/root_cause_log.md` table rows matching  
`| RC-<n> | OPEN|PARTIAL|CLOSED | YYYY-MM-DD | …`  
Unique RC ids; no duplicates.

| Status | COUNT |
|---|---|
| OPEN | **7** |
| PARTIAL | **8** |
| CLOSED | **172** |
| **Total rows** | **187** |

**Active (OPEN + PARTIAL):** **15** — do not mass-close.

### `governance/unproven_register.md` (same turn)

| Status | COUNT |
|---|---|
| UNPROVEN | **6** (openish) |
| DISPROVED | **0** |
| PROVEN | 13 |
| REMEDIATED | 5 |
| **Total claim rows** | **24** |

### Top 10 oldest OPEN / PARTIAL (by `opened`, then RC id) — operator visibility

| id | status | opened | due | one-liner |
|---|---|---|---|---|
| RC-58 | OPEN | 2026-07-26 | 2026-08-09 | Market-closed contamination in measurement tools (weekday/holiday gate missing; terrain scorecard harm measured) |
| RC-102 | PARTIAL | 2026-07-27 | 2026-08-03 | Console half of P0 lying clocks — `index.html` never reads terrain staleness fields; dual spot accessors |
| RC-107 | OPEN | 2026-07-28 | 2026-08-07 | Session-blind thresholds survive RC-31 (`np.diff` medians inflate on weekend gaps) |
| RC-110 | PARTIAL | 2026-07-28 | 2026-07-28 | Chart: levels outside day price window invisible (off-canvas / skipped) |
| RC-115 | PARTIAL | 2026-07-28 | 2026-07-28 | Chart: put/call wall framing lost after coincident-wall merge; value-area ranges not shipped |
| RC-117 | PARTIAL | 2026-07-28 | 2026-07-28 | P0_CLOCKS UI burn — multi-writer spot, hardcoded "live", trust chip, raw payload spot |
| RC-124 | PARTIAL | 2026-07-28 | 2026-07-28 | Gamma pin definition / readability (abs-net vs total-gamma; near-ties hidden) |
| RC-165 | PARTIAL | 2026-07-31 | 2026-08-07 | Healthy terrain cadence mislabeled STALE (sleep floor vs delivered spacing) |
| RC-166 | PARTIAL | 2026-07-31 | 2026-08-07 | Live console freeze / DB_DEGRADED — SQLite write-lock contention |
| RC-168 | OPEN | 2026-07-31 | 2026-08-07 | Impossible `price_bars_1m.volume` spikes (accumulator suspect; no root yet) |

**Remaining active (not in top-10 age list):** RC-177 OPEN, RC-178 OPEN, RC-180 PARTIAL, RC-181 OPEN, RC-190 OPEN.

---

## 11. Admission block (this artifact)

| Field | |
|---|---|
| MISSION_CLASS | Governance / Collect-Find-Decide hygiene — standing work law |
| GAP | No single citeable law forbidding parked wrong/broken log debt during fixes |
| SMALLEST_COMPLETE_CHANGE | This MD + RC-log one-liner pointer + same-turn inventory |
| MINIMUM_SUFFICIENT_EVIDENCE | Exact RC status counts + oldest OPEN/PARTIAL one-liners (above) |
| DECISION_PATH_EFFECT | None — no TRADE influence |
| WHY_NOW | Operator law spoken; RC log already large with active debt |
| TASK_ADMISSION | Docs + inventory only; no product code; no commit; no mass-close; no Chart build |
