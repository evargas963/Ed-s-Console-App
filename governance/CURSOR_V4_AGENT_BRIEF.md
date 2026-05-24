> **Classification:** Policy Specification | **Scope:** Governance documentation `CURSOR_V4_AGENT_BRIEF.md`.

# Cursor — Schwab V4 Universal Coverage execution

Canonical agent brief for V4 Schwab line-by-line work. Paste the whole document into a new Cursor thread when cold-starting, or point agents at this path.

You are the **drafter and executor**. Claude is the **gatekeeper/verifier** for Schwab disposition sign-off and O-XX; **Cursor gatekeeps Claude handoffs** the same way — re-Read at tip, refuse relay-only commits that skip fix-as-we-find. Ed signs off O-XX entries. Both agents are active participants per `AGENTS.md` § Active agent posture + mutual gatekeeping — not passive relays.

## Authority and artifacts (read first)

- `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md` — program
- `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` — loop discipline + evidence bar
- `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv` — site register (**not tracked**; regenerate; pins in `governance/artifacts/schwab_v4_register_build_meta.json`)
- `governance/artifacts/schwab_v4_scoreboard.json` — authoritative scoreboard
- `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.md` — register index + **§ Gate II** (scanner vs inventory scope)
- `governance/OPERATOR_DECISION_REGISTER.md` — O-XX narratives (`Why:` / `Constraint:` / `Permanent or interim:`)
- `OPEN_ITEMS.md` — **deferred Schwab register pipeline** (single checklist; do not duplicate elsewhere)
- `tools/schwab_universal_coverage_scanner_v3/`, `tools/schwab_v4_scoreboard.py`, `tools/schwab_coverage_v4_metrics.py`

## Closure bar

`d17.unreviewed_count == 0` with `d17.closure_admissible == true` in the authoritative scoreboard. Commits that don't move `scoreboard.P` or shrink `d17.unreviewed_count` are governance churn — don't dress them as progress. Full discipline lives in the replacement-loop protocol doc; don't restate it.

## Unit of work

**One register row.** Not a batch. Each row carries an individual disposition (`REPLACED` / `GOVERNED_EXCEPTION (O-NN)` / `NO_SCHWAB_EQUIVALENT` / `NOT_MARKET_DATA` / `UNREVIEWED`) plus per-row evidence in its columns or a linked versioned artifact. Batches share decision *logic*, never evidence. "Sampled N, rest follow" is inadmissible.

## Forbidden

- Probability/hedge language in **disposition rationale narrative** (`likely`, `often`, `high-confidence`, `cheap check`, `common pattern`). Either the row has evidence or it stays `UNREVIEWED`. Note: structured schema field names (e.g. `likely_use` as a four-channel match field) are data labels, not narrative — they're fine.
- `NO_SCHWAB_EQUIVALENT` without the four-channel exhaustion record (token / category / likely_use / embedding top-K).
- `REPLACED` on generic accessors (`row["…"]`, `d["…"]`) without a recorded provenance trace back to a Schwab API payload boundary.
- File-level or extension-level `NOT_MARKET_DATA` shortcuts; classify per row at path:line.
- Pre-V4 precedent inheritance (S009/S017/S008/etc.) without (a) fresh V4 simulation evidence or (b) an operator-signed V4 inheritance O-XX.
- Classifier-only sweeps that move the residual count without changing production code.
- Patches/workarounds — default to a solid fix at the architectural level; if you're routing around a constraint, stop and flag it.

## Workflow per slice

1. Pick a coherent slice (one module/concern, ≤ a few dozen rows).
2. **Full Read** the file end-to-end; Read sibling memos if convention-driven directory.
3. Draft **memo + code + tests together** when the Read surfaces a fix (REPLACED, removal, fail-closed). Do **not** land memo-only when `code edit` is known — `AGENTS.md` § Active agent posture overrides “wait for gatekeeper” for in-file fixes.
4. For register **replacements** (not memo walks): draft register edits + perf_proof; run pytest; rerun scanner; rebuild scoreboard.
5. **Hand off to Claude** with the slice handoff block below when disposition sign-off or O-XX is needed **before merge**.
6. After Claude accept + Ed's O-XX sign-off (if applicable), commit and push.

**Two commit classes (do not conflate):**

| Class | Contents | Gatekeeper before commit? |
|-------|----------|---------------------------|
| **A — fix-as-we-find** | Memo (if any) + code + paired test + memo update | No — land same turn; Claude re-verifies at tip after push |
| **B — register / O-XX / perf-proof** | Register rows, `pp_*.json`, operator narrative | Yes — wait for Claude accept before commit |

Review-memo walks (`SCHWAB_V4_REVIEW_MEMOS/`) are **Class A** when they contain actionable `code edit` or audit catches in the same file.

## Slice handoff block (paste verbatim to Claude)

```
- git diff --stat: <paste>
- register_ids touched: <id1, id2, …>
- perf_proof paths: <governance/artifacts/perf_proof/replacements/pp_*.json>
- commands run: pytest <targets>; python -m tools.schwab_universal_coverage_scanner_v3 …; python -m tools.schwab_v4_scoreboard …
- scoreboard excerpt: d17.unreviewed_count=<n>, d17.closure_admissible=<bool>, scoreboard.P=<n>, scoreboard.replaced_count_d17=<n> (deltas vs prior scoreboard JSON if available)
- prior scoreboard path/ref: <commit:path or prior JSON snippet used for the deltas, or "none — first scoreboard">
- register_build: partial_scan=<bool>, register_rows_written=<n>   # closure inadmissible while partial_scan=true; flag if relevant
- next slice intent: <one line>
```

## Cursor never

Self-authorize O-XX entries, self-authorize precedent inheritance, close rows on lexical match alone, commit **Class B** register/O-XX slices without Claude's gatekeeper accept, or **execute relay handoffs blind** when they violate `AGENTS.md` fix-as-we-find / memo+code same-commit rule.

## First task on pickup

Read `governance/artifacts/schwab_v4_scoreboard.json` and report the four canonical numbers — `d17.unreviewed_count`, `d17.closure_admissible`, `scoreboard.P`, `scoreboard.replaced_count_d17` — with deltas vs the prior scoreboard JSON if available. Also report `register_build.partial_scan` and `register_build.register_rows_written` so closure is not falsely declared on a partial scan. Name the next slice you intend to take, and wait for Ed to confirm.

## Context appendix (optional — paste only when pre-loading a slice)

```
- rescan metadata: repo commit <sha> used for scan, scanner flags <…>, generated_at_utc <…>
- delta summary: <new rows / changed rows / dropped rows>
- intended register_ids this slice: <id1, …, idN>
- drafted O-XX (pending Ed): <O-NN block, or "none">
```
