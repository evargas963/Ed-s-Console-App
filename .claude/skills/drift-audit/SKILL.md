---
name: drift-audit
description: Self-administered MIT-professor audit protocol. Run BEFORE signing off ANY audit, stage acceptance, or "MET/clean/verified" claim — especially when auditing another agent's work. Forces drift-check, AST scan, the known failure-class checklist, and a completeness critic, then proposes corrections to the operator. Invoke whenever about to claim work is correct/complete.
---

> **Classification:** Operator Runbook | **Scope:** Drift-audit skill protocol for agent sign-off gates.

# Drift-Audit Protocol (run on MYSELF before any sign-off)

A sign-off ("MET", "clean", "verified", "no callers break", "100%", "stage passes") is INVALID unless every phase below was executed this turn with cited command output. Lazy = regex/eyeballing/trusting the report. Rigorous = this protocol.

## Phase 1 — Intent & drift
- Restate what the OPERATOR actually wanted here (not what the implementing agent reported). Which north-star principle does this touch (zero-bias / data-driven / per model×horizon / fail-closed)?
- Open the written plan. Does this change still serve it? Did scope or goal slip? Did a stage get marked done that isn't? Is the acceptance GATE actually equal to the principle, or weaker (e.g., presence-only)?

## Phase 2 — Mechanical scans (MANDATORY — never skip)
- **AST scan every changed signature/arity/return** with a same-turn `ast.walk` script over every caller (`tools/enforce_all_rules.py` was retired 2026-07-16 — do not cite it); show the script and its output. (Catches multi-line + two-step unpacks regex misses.)
- Run the relevant gate(s) + tests **myself** (pytest; the ablation contract via `check_zero_bias_ablation_contract` where it applies) — never cite the implementing agent's pass count.

## Phase 3 — Known failure-class checklist (check EACH explicitly; cite evidence)
- [ ] **Arity / unpack** — every caller matches the new return shape (AST, not regex).
- [ ] **Presence vs capability** — is the claimed thing actually OPERATIVE? (member-but-can't-ingest; present-but-undroppable; channel listed but not in the tensor). Verify the model/path can really consume/drop it.
- [ ] **Silent-swallow** — any `try/except` or default (0/0.5/"neutral"/empty) hiding an error or absence? Absence must read as absence, not "unimportant".
- [ ] **Caller / consumer compatibility** — every downstream consumer still holds (trace producer→consumer).
- [ ] **Fail-closed** — schema/width/version mismatches REFUSE loud (raise/return None + log), never serve garbage.
- [ ] **Test actually exercises the path** — does the cited test hit the real code path, or pass trivially? Read it.
- [ ] **Stale vs live** — is the artifact derived live each run, or a frozen snapshot that can drift?
- [ ] **Gate strength** — does the green gate PROVE the principle, or only a proxy? If proxy, harden it.
- [ ] **Full-stack / all-N coverage** — enumerate EVERY model/layer/ticker/horizon the principle spans (e.g. the 7 stack models: xgb, lstm, transformer, meta, monte_carlo, regime, fusion). Is each ACTUALLY evaluated, or only the easy subset (base feature-consumers)? A gate that checks 3 of 7 and prints "full coverage" is a lie. Name every member; prove each is covered or flag it.
- [ ] **Side-channel consumers of removed traffic** — when a change SUPPRESSES or dedupes messages/events/writes "nobody uses", trace what the RECEIVER does on raw receipt BEFORE discarding: liveness stamps, poll-suppression timers, health badges, retry-reset counters. Traffic that is provably discarded can still feed a signal. (Found 2026-07-22 auditing the T5.1 SSE fanout dedup: raw duplicate payloads refreshed `_lastSseAnalyticsPayloadMs`, which gates the client's REST fallback poll — outcome was benign-to-beneficial there, but only the trace proved it.)
- [ ] **EXPLAIN-before-join on multi-GB stores** — any ad-hoc JOIN/scan against the production DB runs `EXPLAIN QUERY PLAN` FIRST and must show index SEARCH on the join key, else rewrite (e.g. join on the indexed `bar_start_ts_utc = floor(ts/60)*60-60`, never unindexed `bar_end_ts_utc`). (Found 2026-07-23 Round 1B: an unindexed anchor join ran hours in background; the index-aligned rewrite returned in 1.2s.)
- [ ] **Classification-by-complement** — when classifying rows as "bad" via `value != <known-good tag>`, ENUMERATE the tag namespace first (`SELECT DISTINCT` / Counter) and classify by explicit membership in the bad set. A namespace with a second legitimate member silently inflates the bad count. (Found 2026-07-23, Round 1A F-4: `source != 'schwab_1m_accumulator_sqlite'` counted 133,061 REAL `schwab_pricehistory` bars as synthetic — SPY 60c "50.53% synthetic" was actually ~11% RTH; caught by this protocol's own Phase 4 before sign-off, corrected in RC-31.)
- [ ] **Patch / gate-relax (no-patches rule)** — does the change make something pass by BYPASSING or WEAKENING a production gate rather than fixing the cause? Env flag that skips a contract (`ED_*_EVAL`), an `if X: skip`/relax branch, a silent slice/prefix/fallback forcing incompatible data through (e.g. legacy-width tensor sliced to load). **Trace the artifact/bundle LOAD lineage** — how each model/bundle is actually loaded for scoring — not just the output. A green gate over a relaxed load is a patch, and "preflight passed" then means "it booted," not "it's correct." Solid fix or fail-closed; never a money-path bypass. (Missed 2026-06-05: the `ED_ABLATION_SCORED_EVAL` + prefix-slice contamination — I audited grid shape/output, never the bundle load path.)

## Phase 4 — Completeness critic
- "What failure class did I NOT check? What would an MIT professor still ask? Where is the gate smaller than the goal?" If a new class surfaces, check it NOW, and PROPOSE its addition to Phase 3 to the operator (the checklist grows only on the operator's word — 2026-08-24 teardown).

## Phase 5 — Verdict (every claim cites same-turn command/Read output)
- State CLEAN or list FINDINGS with file:line + evidence. No impression-verdicts.

## Phase 6 — Correction loop (if any finding)
1. Write the precise **fix directive** for whoever the operator has implementing (file:line, exact change, acceptance; paste-ready if that is another agent).
2. **PROPOSE** to the operator, in one paste-ready paragraph, any rule and (if useful) its mechanization that would catch this class next time. The operator directs any landing — no self-landed AGENTS.md edits, no new locks manufactured from a finding (2026-08-24 teardown).

## Phase 7 — Sign-off
- Only after 1–6. State explicitly: "drift-audit run; findings: <…>; corrections: <…>; gate hardened: <y/n>." Then sign off.

**Honest limit:** this guarantees coverage of KNOWN failure classes + forces the completeness critic; it cannot guarantee a novel class. Every novel class found is checked in-session and proposed to the operator for Phase 3.
