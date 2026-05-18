# SCHWAB FULL REPO DIRECTIVE (binding on all agents, no exceptions)

Operator-controlled instruction surface. Governs disposition, closure claims, and all market-field work in this repository.
Normative program law remains in `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md` and `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md`.

──────────────────────────────────────────────────────────────────────────────
SCOPE — THE ENTIRE CODEBASE (REPO ROOT)
──────────────────────────────────────────────────────────────────────────────
The repo root is the file tree of this repository. Every file in the repo
is in scope: every directory, every extension (Python, HTML, JavaScript, CSS,
SQL, YAML, JSON, TOML, configs, templates, tools, tests, docs, static,
governance, planes, research, calibration, arch_competition, v2_decision,
features, legacy, mocks — everything). Exclusions are by gitignore-class list
(vendored dependencies, build artifacts, the register itself), not by inclusion
list. No file is out of scope by path, section, phase, mega, scanner
capability, or "collateral."

──────────────────────────────────────────────────────────────────────────────
READ — NOT SCAN-ONLY
──────────────────────────────────────────────────────────────────────────────
Every in-scope file is Read end-to-end when doing disposition or closure work
— not grepped, not scanned-only, not spot-checked, not sampled. Per change
set: Read every file in the producer/consumer cone end-to-end. Program
closure: the full repo file tree.

──────────────────────────────────────────────────────────────────────────────
CANOPY → TRUNK → BRANCH → LEAF (mandatory trace, every market field)
──────────────────────────────────────────────────────────────────────────────
For every market-data field, value, derivation, or display element, trace the
full chain backward to Schwab wire. No stopping at an intermediate layer.

  CANOPY  — what the operator or API consumer sees: UI element id,
            API JSON key, snapshot/DB column, log line, tool output, or test
            assertion value.

  TRUNK   — named carrier inside the response: ms_dict key, state_cache entry,
            /api/* JSON field, snapshot column, register row's surface_form,
            DOM data binding (e.g. d.mhap_rows[h].confidence).

  BRANCH  — ordered file:fn chain that transforms inputs into the trunk
            value. No anonymous "the server sets it"; every hop is a named
            function in a named file with a line number.

  LEAF    — Schwab wire primitive per
            schwab_field_inventory/schwab_field_dictionary.csv
            (e.g. quotes.SPY.lastPrice, chains.callExpDateMap.*.gamma,
            pricehistory.candles[].close), OR NO_SCHWAB_EQUIVALENT.

Stopping at ms_dict, cache, fusion, "Key Levels," "inventory done," or any
intermediate layer without completing the chain to LEAF (or documented
NO_SCHWAB_EQUIVALENT) is rejection-grade (half-done) work.

──────────────────────────────────────────────────────────────────────────────
CSV CHECK + DISPOSITION
──────────────────────────────────────────────────────────────────────────────
Every canopy field must be checked against
schwab_field_inventory/schwab_field_dictionary.csv. Where Schwab provides a
leaf for that meaning, code MUST read that Schwab leaf via the existing
adapter (schwab_client / market_data_adapter / live_market_plane), removing
any substitute derivation, silent default, or cache-of-cache shortcut that
hides the leaf. Where Schwab does not, exactly one canonical fail-closed
derivation is allowed, documented in the V4 register as
GOVERNED_EXCEPTION (O-NN) with Why / Constraint / Permanent-or-interim in
governance/OPERATOR_DECISION_REGISTER.md. No silent 0, 0.33, "neutral",
"flat", 500.0, or fabricated defaults.

──────────────────────────────────────────────────────────────────────────────
PROGRAM ANCHOR — V4 IS THE PROGRAM
──────────────────────────────────────────────────────────────────────────────
governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md and
governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md govern disposition and
closure. governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv is the source
of truth for unreviewed_count and bare_governed_exception_count. The V4-B
loop ("Triage → Edit → Rescan → Re-disposition → Perf-proof bundle ↔
register → Exit") is the only workflow. No parallel program may be proposed.

──────────────────────────────────────────────────────────────────────────────
NO NEW MDs AS DELIVERABLES
──────────────────────────────────────────────────────────────────────────────
Documentation changes are in-place amendments to existing V4 program files
(or via the INSTITUTIONAL_STANDARD_V3.md § 20 amendment path for V3 changes).
The following are explicitly FORBIDDEN as new artifacts:
  • Any "Mandatory Leaf Program" / "SMLP" charter
  • Any "Rule SMLP-N" / "Rule N" naming
  • Any "Closure Certificate" parallel to V4-B § Exit
  • Any "Trace Table" MD-per-PR artifact in governance/traces/
    (the per-PR trace is the V4 register slice for that PR's register_id set,
     already required by V4-B §51)
  • Any new commit-trailer schema (register_id cite + pp_*.json perf-proof
    bundle per V4-B is the only trailer)

──────────────────────────────────────────────────────────────────────────────
UI RENDER PATHS, TESTS, COLLATERAL — EXPLICIT
──────────────────────────────────────────────────────────────────────────────
static/**/* and templates/**/* are normative canopy/branch surfaces. Every
id="..." element, every domIf('id', ...) call, every render-side data
binding is a canopy that must trace to leaf.

tests/**/* and fixture files are canopy. Hardcoded market values in tests
must trace to a justified fixture (O-NN with capture provenance) or be
replaced with Schwab-leaf-derived fixtures.

Collateral is automatic. A PR touching any file that emits or displays a
market field MUST Read every other file in the producer/consumer cone for
that field, end-to-end.

──────────────────────────────────────────────────────────────────────────────
CLOSURE (Deliverable 17 — admissibility conditions)
──────────────────────────────────────────────────────────────────────────────
Closure is unreviewed_count == 0 AND bare_governed_exception_count == 0
across the FULL repo file tree (V4 Deliverable 17 metrics). Inventories-only,
fail-closed spot fixes, single-file patches without full canopy→leaf trace
do NOT count as closure.

A closure claim is INADMISSIBLE unless ALL of the following hold:
  • register_build.partial_scan == false (full-repo scanner walk committed)
  • register_build has no max_files cap in meta or CI canonical build path
  • PR 2 CI diff-emission gate is live in .github/workflows/schwab-csv-first.yml
  • Every GOVERNED_EXCEPTION row satisfies V4-A (O-NN + operator narrative)

──────────────────────────────────────────────────────────────────────────────
PROGRAM CLOSURE — THREE-PR GATE (binding; PR N = Nth landing)
──────────────────────────────────────────────────────────────────────────────
Land in this order: PR 1 → PR 2 → PR 3 → field work under the gate.

PR 1 — Governance (text only)
  • This file (CLAUDE.md), in-place V4 Scope amendment, OPEN_ITEMS banner
  • Does NOT admit any closure claim or "closure per D17" language

PR 2 — CI diff-emission gate (before full register regen)
  • Extend tools/check_schwab_csv_first.py (or successor) so a PR that emits
    a new market-fact site without a matching register row in the diff FAILS
  • Required step in .github/workflows/schwab-csv-first.yml
  • Without PR 2 live, no field PR may merge

PR 3 — Scanner full-tree walk
  • Remove --max-files from canonical scanner build and CI regen step
  • governance/artifacts/schwab_v4_register_build_meta.json: partial_scan false;
    no max_files field; operator_note must not claim closure on a partial walk
  • Regenerate governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv and repin
    scoreboard/meta SHA256
  • A jump in unreviewed_count after PR 3 is the CORRECT signal

Only after PR 1 + PR 2 + PR 3 may agents claim closure_admissible per D17.
Walking register rows down to zero is separate multi-PR work (one row per
feedback_no_spot_check_demand_systematic).

──────────────────────────────────────────────────────────────────────────────
ENFORCEMENT PHRASE
──────────────────────────────────────────────────────────────────────────────
When the operator types `SCHWAB FULL REPO`, every claim in the next response
must trace to Read of relevant files with file:line citations. Scoped or
narrowed answers are rejection-grade failures.

When the operator types `go SCHWAB FULL REPO — governance PR only`, only PR 1
files may change (CLAUDE.md, V4 Scope amend, OPEN_ITEMS banner). No code,
register, scanner, or workflow changes.

When the operator types `go SCHWAB FULL REPO — PR 2 CI gate only`, only PR 2
files may change (tools/check_schwab_csv_first.py and
.github/workflows/schwab-csv-first.yml). No scanner regen, register, or
partial_scan changes.

FORBIDDEN PHRASES (any of these in a response is rejection-grade):
  • "scope of current section" / "for this section only"
  • "scanner capability" / "the scanner doesn't walk that"
  • "in scope of the file I'm editing" / "the file I was asked about"
  • "collateral only" / "not in the ticket" / "out of scope of this PR"
  • "ms_dict is the source" / "the API provides it" (without continuing to leaf)
  • "based on the files I've reviewed" / "for the change set in this PR"
  • "Mega N is done" / "the section is closed" / "we already inventoried that"
  • "fail-closed in [specific place]" as a substitute for canopy→leaf trace
  • "this is paper work, not code work"
  • "closure per D17" while partial_scan is true or PR 2 is not live
  • Any phrase whose effect narrows scope to less than the full repo
