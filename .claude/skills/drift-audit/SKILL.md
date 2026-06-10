---
name: drift-audit
description: Self-administered MIT-professor audit protocol. Run BEFORE signing off ANY audit, stage acceptance, or "MET/clean/verified" claim — especially when auditing Cursor's work. Forces drift-check, AST scan, the known failure-class checklist, and a completeness critic, then self-corrects (direct Cursor + set a rule + mechanize). Invoke whenever about to claim work is correct/complete.
---

> **Classification:** Operator Runbook | **Scope:** Drift-audit skill protocol for agent sign-off gates.

# Drift-Audit Protocol (run on MYSELF before any sign-off)

A sign-off ("MET", "clean", "verified", "no callers break", "100%", "stage passes") is INVALID unless every phase below was executed this turn with cited command output. Lazy = regex/eyeballing/trusting the report. Rigorous = this protocol.

## Phase 1 — Intent & drift
- Restate what the OPERATOR actually wanted here (not what Cursor reported). Which north-star principle does this touch (zero-bias / data-driven / per model×horizon / fail-closed)?
- Open the written plan. Does this change still serve it? Did scope or goal slip? Did a stage get marked done that isn't? Is the acceptance GATE actually equal to the principle, or weaker (e.g., presence-only)?

## Phase 2 — Mechanical scans (MANDATORY — never skip)
- **AST scan every changed signature/arity/return:** `python tools/enforce_all_rules.py --ast-callsites <FUNC>`. Confirm every call site's binding. (Catches multi-line + two-step unpacks regex misses.)
- Run the relevant gate(s) + tests **myself** (`--ablation-bias`, pytest) — never cite Cursor's pass count.

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
- [ ] **Patch / gate-relax (no-patches rule)** — does the change make something pass by BYPASSING or WEAKENING a production gate rather than fixing the cause? Env flag that skips a contract (`ED_*_EVAL`), an `if X: skip`/relax branch, a silent slice/prefix/fallback forcing incompatible data through (e.g. legacy-width tensor sliced to load). **Trace the artifact/bundle LOAD lineage** — how each model/bundle is actually loaded for scoring — not just the output. A green gate over a relaxed load is a patch, and "preflight passed" then means "it booted," not "it's correct." Solid fix or fail-closed; never a money-path bypass. (Missed 2026-06-05: the `ED_ABLATION_SCORED_EVAL` + prefix-slice contamination — I audited grid shape/output, never the bundle load path.)

## Phase 4 — Completeness critic
- "What failure class did I NOT check? What would an MIT professor still ask? Where is the gate smaller than the goal?" If a new class surfaces, check it AND add it to Phase 3 (this protocol compounds).

## Phase 5 — Verdict (every claim cites same-turn command/Read output)
- State CLEAN or list FINDINGS with file:line + evidence. No impression-verdicts.

## Phase 6 — Self-correct loop (if any finding)
1. Write the precise **Cursor fix directive** (file:line, exact change, acceptance).
2. Set a **self-directed rule** (AGENTS.md + memory) so this class is caught next time.
3. **Mechanize** the check if possible (extend `check_zero_bias_ablation_contract` / a detector) so the build catches it, not just me.

## Phase 7 — Sign-off
- Only after 1–6. State explicitly: "drift-audit run; findings: <…>; corrections: <…>; gate hardened: <y/n>." Then sign off.

**Honest limit:** this guarantees coverage of KNOWN failure classes + forces the completeness critic; it cannot guarantee a novel class. Every novel class found gets added to Phase 3.
