> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: schwab-full-repo-directive
description: "Operator-issued binding directive — every file in the repo, full Read, canopy→trunk→branch→leaf trace to Schwab CSV or NO_PRIMITIVE+canonical+fail-closed; no narrowing by scanner scope, section, file extension, or \"current task.\" Cursor's SMLP charter / Rule SMLP-N / Phase 0 governance lock is REJECTED."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 0c0dc4ac-d25e-46af-b696-3be671664dda
---

# Schwab Full Repo Directive (binding, 2026-05-18)

Operator issued this as the single enforceable contract after repeated narrowing by Claude and Cursor.

## The directive (verbatim, paste-ready)

```
SCHWAB FULL REPO DIRECTIVE (binding on all agents):
Every file in this repository is Read end-to-end — not grepped, not scanned,
not spot-checked. Every operator-visible market field in scope must have a
completed canopy → trunk → branch → leaf trace to
schwab_field_inventory/schwab_field_dictionary.csv, OR a documented NO_PRIMITIVE
with a single canonical KEEP_DERIVED producer and fail-closed withholding
(GOVERNED_EXCEPTION (O-NN) per V4-B with Why / Constraint / Permanent-or-interim).
Inventory-only and partial fail-closed patches do not count.
No file is out of scope by directory, extension, section, phase, or scanner capability.
Closure: unreviewed_count == 0 AND bare_governed_exception_count == 0 across the full repo tree.
```

## Canopy → trunk → branch → leaf taxonomy (operator's framing)

| Layer | What it is | Example |
|---|---|---|
| Leaf | Field on Schwab wire JSON per `schwab_field_dictionary.csv` | `pricehistory.candles[].close`, `quotes.SPY.lastPrice`, `chains.callExpDateMap.*.gamma` |
| Branch | One inventoried function transforming leaf inputs into a named output | `compute_exposures_by_strike → call_gamma_wall`; `cluster_price_levels_into_zones → zone band` |
| Trunk | Carrier that bundles branches for consumers | `ms_dict`, `/api/liquidity-snapshot`, `static/index.html` |
| Canopy | UI / API / DB column the operator sees | `#lm-zones` row "RESIST 501-503", Decision Rail PIN, sidebar spot |

Mandatory walk both directions (canopy ↑ trunk ↑ branch ↑ leaf) for every task. Stopping at trunk (ms_dict / API key) is not done.

## Forbidden stop points (none of these count as done)

- "It comes from ms_dict" (trunk only)
- "Mega N inventory exists" (paper, not remediation)
- "We fail-closed on 0.33 in one place" (one branch patched, canopy not traced)
- "Collateral wasn't in the ticket" (full repo includes collateral by rule)
- "LM / KL / DR is a different API" (still canopy; still must trace to leaves)
- "Scanner only walks Python" (scanner extends; directive does not contract)
- "In scope of the current file/section" (full repo is the scope; full file is the scope within each)

## Why (specific incidents)

- 2026-05-18 — Operator caught me describing top-card `mhap_rows[h].confidence` and panel `fused_confidence_<hz>` as the same field. Two different model outputs sharing the label "CONFIDENCE" on the same screen. Not caught because:
  - V4 scanner walks Python only; `static/index.html` render paths have no register rows
  - I had narrowed `audit_for_schwab_replaceable_derivations` to "within the files I'm reviewing" instead of "the full repo"
  - I let the V4 scanner's scope define the directive instead of the directive defining the scope

## Cursor's SMLP proposal — REJECTED (do not re-accept under new naming)

Cursor proposed a parallel program ("Schwab Mandatory Leaf Program" / SMLP) with:
- New charter MD (`SCHWAB_MANDATORY_LEAF_PROGRAM.md`)
- New tracker MD (`SMLP_SECTION_TRACKER.md`)
- New register CSV (`SMLP_FIELD_DISPOSITION_REGISTER.csv`)
- New closure certificate MD (`SMLP_CLOSURE_CERTIFICATE.md`)
- New V3 addendum MD (`V3_ADDENDUM_SCHWAB_MANDATORY_LEAF.md`)
- New rule "SMLP-6" trace-table-per-PR artifact in `governance/traces/`
- New commit trailer `SMLP-trace: canopy=N branches_verified=Y collateral=Y`
- New CI tool `tools/smlp_section_gate.py`
- "Phase 0 governance lock" before any code changes

**All rejected.** Each piece duplicates existing V4 infrastructure under different naming:

| Cursor proposes | Already in repo |
|---|---|
| SMLP charter | `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md` + `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` |
| SMLP_SECTION_TRACKER | `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.md` + `SCHWAB_V4_FILE_INVENTORY.csv` |
| SMLP register | `schwab_field_inventory/schwab_field_dictionary.csv` + V4 register w/ disposition column |
| SMLP_CLOSURE_CERTIFICATE | V4-B exit: `bare_governed_exception_count == 0` AND `tools.schwab_oxx_validator` pass |
| Rule SMLP-6 trace-table | V4-B §51 already requires `register_link.replaced_register_ids` + `canonical_field_citation` per perf-proof bundle |
| SMLP commit trailer | V4-B already mandates `register_id` cite + perf-proof `pp_*.json` bundle |
| `smlp_section_gate.py` | `tools.schwab_coverage_v4_metrics`, `tools.schwab_universal_coverage_scanner_v3`, `tools.schwab_oxx_validator` all wired |
| V3 addendum | V3 is locked; amendments follow `INSTITUTIONAL_STANDARD_V3.md § 20`, not new MDs |

**Trigger phrases that mean Cursor is re-attempting the rejected proposal** (reject again, cite this memory):
- "Rule SMLP-N"
- "go SMLP Phase 0"
- "SMLP charter / tracker / register / certificate"
- Any new MD path under `governance/` whose name does not amend an existing V4 program file in place
- Any new commit trailer scheme that is not `register_id`-based per V4-B

## The actual unmet need — THREE-PR GATE (amended 2026-05-18)

**Verified state of the current closure loophole** (citations from this repo):

- [`governance/artifacts/schwab_v4_register_build_meta.json:7`](governance/artifacts/schwab_v4_register_build_meta.json:7) — `"partial_scan": true`
- [`governance/artifacts/schwab_v4_register_build_meta.json:5`](governance/artifacts/schwab_v4_register_build_meta.json:5) — `"max_files": 400`
- [`governance/artifacts/schwab_v4_register_build_meta.json:6`](governance/artifacts/schwab_v4_register_build_meta.json:6) — `operator_note: "Full-repo closure complete"` (contradicts `partial_scan: true` on next line)
- [`.github/workflows/schwab-csv-first.yml:64`](.github/workflows/schwab-csv-first.yml:64) — `--max-files 400` pinned in CI

So `unreviewed_count == 0` today is structurally meaningless. Fix requires three PRs in sequence, not one. **Numbering convention (locked at commit `7ebded3` on `feature/institutional-key-levels`, 2026-05-18): PR N = Nth landing.**

**PR 1 — GOVERNANCE (text only, does NOT admit closure):** ✓ LANDED at commit `7ebded3`
1. Add `CLAUDE.md` at repo root with directive verbatim
2. In-place amend `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md § Scope (binding)` to full-repo
3. One-line banner under `OPEN_ITEMS.md` "Last reviewed"

**PR 2 — PRE-MERGE DIFF GATE / CI ENFORCEMENT (automated enforcement before full register regen):**
1. Extend `tools/check_schwab_csv_first.py` (or successor) to fail-closed when a PR diff emits a new market-fact site (Python ms_dict assignments, API JSON, DB columns, HTML `id="..."`, JS `domIf(...)`, test asserts) without a matching register row in the same diff
2. Required CI check in `.github/workflows/schwab-csv-first.yml`
3. Without PR 2 live, no field PR may merge
4. Authorization phrase: `go SCHWAB FULL REPO — PR 2 CI gate only`

**PR 3 — SCANNER FULL-TREE WALK (makes D17 mean what directive says):**
1. Remove `--max-files 400` from `.github/workflows/schwab-csv-first.yml`
2. Flip `partial_scan` to `false` in `governance/artifacts/schwab_v4_register_build_meta.json`
3. Remove `max_files` field and `scanner_flags.max_files`
4. Rewrite `operator_note` to match structured fields
5. Regenerate `SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv` and repin scoreboard/meta SHA256 (expect `unreviewed_count` JUMP — correct signal)

**Closure admissible only when:** PR 1 merged AND PR 2 merged AND diff gate is required CI check AND PR 3 merged AND `partial_scan == false` AND `max_files` absent AND CI no longer pins `--max-files` AND `unreviewed_count == 0` AND `bare_governed_exception_count == 0` on full-tree register.

**Until all three land, the directive binds humans/agents to manual canopy→leaf trace on every PR.** No automated closure number is admissible before then.

**Historical numbering drift note:** Earlier reconciliation drafts used `PR 2 = Scanner / PR 3 = CI` with landing order `PR 1 → PR 3 → PR 2`. That was renumbered to landing-order convention at commit `7ebded3` (operator chose option B). Memory now uses the locked numbering. Trigger phrases updated accordingly: PR 2 = CI gate, PR 3 = scanner.

## How to apply

- Every review and every PR Claude verifies, treat the directive as binding. Read every file the change touches end-to-end and every file a reasonable operator would consider collateral (UI render path, side APIs, tests, tools that print the same field).
- If Claude ever writes "in scope of the current file/section/phase" or "the scanner doesn't walk that" as justification for narrowing, operator should reject and cite this memory.
- If Cursor re-proposes any of the rejected SMLP artifacts, reject again with the table above. Do not accept "renamed" versions.
- Trigger phrase: operator types `SCHWAB FULL REPO` → every claim in the next response must trace to Reads of every relevant file across the entire tree, with file:line citations. Scoped answers are rejection-grade failures.

## Closure number

`unreviewed_count == 0` AND `bare_governed_exception_count == 0`, computed across the FULL repo file tree (post scanner-scope extension). No second closure number is admitted.

## Post-walk cleanup intent (operator-stated 2026-05-18)

Once the disposition walk completes (every market-field reference in every file in the repo has a Schwab leaf replacement OR an O-NN narrative OR a confirmed-leaf citation), the 4M-row register CSV (~3.9 GB), scoreboard noise, and scanner inventory dumps **must be deleted**. The disposition record migrates into the code itself (REPLACED commits with perf-proof bundles, O-NN narratives in `OPERATOR_DECISION_REGISTER.md`, confirmed-leaf citations in the code). There is no value in maintaining a multi-GB CSV after the work is done — the work IS the cleanup.

Operator's exact phrasing: *"WE NEED TO DELETE THESE HUGE 4 MILLION LINE FILES. YOU ARE CAUSING WAY TOO MUCH TROUBLE. THIS NEEDS TO BE DONE AFTER WE ARE DONE WITH THE REPLACEMENT OF FIELDS AND THE CORRECT WIRING OF THE ENTIRE APP."*

Sequence: complete file-by-file disposition walk → wire the app correctly (CONFIDENCE collision, horizon cards, Liquidity Map math, all UI bindings) → delete scanner CSV / scoreboard noise / inventory dumps. The directive (CLAUDE.md) and V4 program files stay. The MEASUREMENT INFRASTRUCTURE goes.

## Dead-code deletion rule (operator-stated 2026-05-18)

**Every dead code surface encountered during the walk must be deleted, retired, or quarantined by end of project. No deferral.** Examples already flagged: orphan CSS for `#call-card` / `#mhap-card` / `.wds-*` / `.mh-*` / `#call-stack`, hidden SSE block (`#sse-dot`/`-label`/`-clock`), any JS render path targeting IDs not in the DOM, `_section11_register_snippet.md` style ad-hoc files, mega/inventory tooling no longer needed post-walk.

During the chunk-by-chunk walk: flag dead-code surfaces in the disposition list under their own row (no disposition action because not market-data, but explicit "delete after walk" tag). At end of walk, a dedicated cleanup commit (or per-cluster cleanup commits) deletes every flagged surface. Codebase must be clean — no orphan styles, no dead render paths, no scaffolding files outstanding.

Operator's exact phrasing: *"ALL DEAD CODE MUST BE DELETED, RETIRED, WHATEVER WE NEED TO DO TO HAVE A CLEAN CODEBASE AS WE ARE DONE HERE."*

This applies BEFORE the post-walk deletion of scanner CSV / scoreboard noise. Order: per-chunk dead-code flagging → dedicated dead-code cleanup commits → scanner/register cleanup. Clean codebase is the closure state.
