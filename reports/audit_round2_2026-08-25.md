# Independent-audit round 2 — investigation and resolution record (2026-08-25)

Second audit round on main `2a8a9712` + the round-1 commit `a565ef8d`, run as three parallel
multi-agent sweeps (control plane 7 agents / guard machinery 6 / collection paths 5) plus
inline verification. Ledger rows: RC-480 (CLOSED — fixes landed) and RC-481..RC-484 (OPEN —
operator/runtime actions, due-dated). Every number below carries its reproduce command or
names the deterministic script that produced it.

## 1. Control plane (findings: contradictions, self-start, auto-governance, duplication)

87 raw findings across 35 surfaces, 64 after dedup — all implemented. Highlights:

- Self-start/standing authority removed: `.cursor/rules/01` (round 1), REHAB_PROGRAM law 5
  ("without waiting to be asked" deleted; queue sources are records for the operator's
  triage), ACTIVE_PROGRAM FP-09 "Not permission to idle" clause, OPEN_ITEMS "work this
  before" line, PA-46 "TOP ACTIVE EXECUTION QUEUE" retitle, rules-auditor "proactively"
  trigger, drift-audit "set a rule + mechanize" self-correction (now: propose to operator).
- The Monday-debt wake channel — a weekly host task issuing dead 2026-08-03 work orders —
  is retired repo-side (`tools/monday_debt_wake.py`, `tools/run_monday_debt_wake.ps1`,
  `reports/_wake/` deleted; prompts stamped HISTORICAL). **Operator action owed:**
  `schtasks /Delete /TN "EdMondayDebtWake" /F` (recorded in `governance/host_scheduled_jobs.md`).
- Duplicate truths consolidated: defect state = `governance/root_cause_log.md` (OPEN_ITEMS
  rows now point there); work selection = the operator in chat (every queue demoted to
  record); CR program status = ACTIVE_PROGRAM §CR (design doc header fixed); zero-debt "law"
  and standing prompts stamped HISTORICAL; `governance/README.md` rewritten from fossil.
- Branch protection re-measured: `gh api repos/evargas963/Ed-s-Console-App/branches/main/protection`
  → `enforce_admins=true`, required checks pytest-full + hardening, reviews required.
  GOV-REMOTE-ENFORCEMENT closed on that measurement; the RC-475 note in retired_checks.md
  is annotated (measurement disagrees with its "review requirement removed" claim).

## 2. Proof/honesty machinery (finding: shape-over-truth)

Six lanes executed real bypass probes against the guards; 35 gaps (with PoCs) and 39
verified-sound behaviors. Fixes landed (each with pinning tests):

| Gap (PoC executed) | Fix |
|---|---|
| Verdict passed on a backticked command that never ran | `proof_only_guard.turn_slice` cross-checks citations against the transcript's Bash/PowerShell `tool_use` records, whole turn, fail-closed on missing transcript |
| One hedged aside disabled the whole guard | correcting exemption is ±200-char neighbourhood-scoped; affirmative verdicts (CONFIRMED/PROVEN/KILLED/RETIRED/SETTLED) never ride a correction |
| Only the final assistant record judged | whole-turn text slice (a bland "Done." tail no longer hides a verdict) |
| Memory-citation paraphrases escaped | +6 lexicon families (MEMORY.md-cites, earlier-audit-showed, as-established, you'll-recall, known-dead, file-notes) — documented as a deterrent lexicon, not semantic detection |
| pm_verify accepted mentioned-not-issued git reads | evidence requires a git READ actually issued this turn + value co-occurrence for sha claims; hedges scope per paragraph |
| `echo pytest all green` minted proof | `_verification_ran`: command-position issuance only; emitters/messages are data |
| Completion-claim battery dead since RC-471 | rewired at Stop via honesty_guard (claim-gated); quiet-window PASS must postdate the claimed change (STALE_PASS) |
| Re-dating overdue rows was free (67 historical due moves, 61 on already-overdue rows — measured from git history) | REDATE_LOCK in the operating-process pre-commit: a due move requires `RE-DATED <old>-><new>: <reason>` in the row; 8 staged-diff controls |
| no-grep law blocked/passed inconsistently | rebuilt as an action predicate (file-operand/recursive/xargs/git-grep/bare-rg = block; stdout filtering = legal) — 15-block/3-pass pinned matrix |
| `-c` classifier blocked `grep -c` and commit messages | binds to interpreter heads only; `-m` messages stripped as data |
| `AppData/` matched the protected `data/` tree | `_PROTECTED_TREE` path-segment anchored |
| `git push -n` (--dry-run) read as --no-verify | narrowed to `git commit -n` |
| Yes/no dodge tokens ("there is no simple way…") passed; "Correct —" blocked | answer-position tokens incl. operator dialect |
| The honest "no longer enforced; see foo.md" sentence blocked | MD-as-lock requires affirmative linkage |

Documented-not-mechanized (ACCEPT list, wording now in the guards' own docs): stats
adequacy, lowercase verdicts, memory paraphrase remainder, issuance≠execution (a
PostToolUse exit-code lane would be a new surface — operator's call), general option-menu
detection, marker-vocabulary limits. Reproduce: `pytest tests/test_proof_only_guard_v1.py
tests/test_operator_law_guard_verification_v1.py tests/test_honesty_guard_v1.py
tests/test_pm_verify_repo_lock_v1.py tests/test_operating_process_lock_v1.py -q`.

Session-friction note: the PM_COVERAGE and RC-125 live-probe blocks experienced in chat
fire from the PRODUCTION checkout's 105-commit-old guards; both are already retired on
current main — the pull itself removes them.

## 3. Collection and enrollment (measured; DB opened read-only)

Universe: 61 enrolled (11 core / 15 pinned / 17 panel_auto / 18 user_persisted) —
`EdDB.logging_universe_authoritative_tickers`, `db.py:2080`. Coverage window law: bars
exactly (555,975] with 0 violations in ~23k bars/day over 5 days.

| Class | Bars 9:15–16:15 | Snapshots/day | Ready by 9:30 (healthy days) |
|---|---|---|---|
| Sentinels (3) | 420/420 all days | ~656 | yes |
| Rotation tier (41) | avg ~374–420 (shortfall = liquidity) | ~19.8 (~18 min/ticker) | chains 42/44 by 09:16:30; snapshots 36–39/44 |
| panel_auto (17) | avg ~410–420 | 0 by design | bars/quotes only |
| Dead rows ($TNX/RTY/XXT; SATS stale) | 0 | 0 | never |

Day verdicts: 08-18 = 0/44 ready (console down 08:24–10:21); 08-19 41/44; 08-20 39/44
then a 12:31 halt + operator-mode starvation (52 background rows all day; XLE/XOM zero);
08-21 41/44; 08-24 41/44; 08-17 and 08-25 zero-collection down days. Caveat: ~98% of bar
"coverage" is `schwab_pricehistory` backfill — bar presence never proves liveness;
snapshot `ts_utc` is the honest live clock (08-17: 22,661 bars, 0 snapshots).

Defects D1–D13 triaged: **landed now** — D2 (the pytest healer that UPSERTED enrollments
into the LIVE production DB is assert-only; `enrollment_source` is write-once in `db.py`),
D9 (banked prior-session coverage stamp in `server.py::_canonical_price_level_bars` —
truncated tapes like MTA's 188/390 no longer serve PDH/PDL silently), D13 (FP-63 DONE,
FP-66 strike-count history, FP-64 dependency). **Tracked with due dates** — RC-481 (no
supervisor: 3 of 6 mornings dark; watchdog + pre-pull extended-hours decision), RC-482
(three-tier snapshots vs the universal standard: panel_auto ratify-or-remove + throttled
operator-mode rotation — product decisions), RC-483 ($SPX snapshots dead since 07-26,
SATS since 05-27, RTY/XXT never, 5 non-enrolled writers — de-enroll/re-key/enroll-or-stop
+ liveness-reconciliation candidate), RC-484 (enrollment blindness: day-1 seed,
`/api/bars1m` fallback, ATR daily fallback — specs ready, acceptance needs a live session).

GEX architecture (finding 4 blast): morning full-chain capture is alive and extended —
`option_chain_morning_full` 951 rows 2026-07-20→08-24 (20/20 sentinel capture days,
strike_count=100 since 07-20) + `option_chain_accrual` 50,802 rows since 07-31 at 38–45
tickers/day, window 09:15–16:15. The deleted July-20 rule lost nothing.

Deterministic evidence scripts — the four load-bearing ones are COMMITTED at
`reports/audit_round2_scripts/` (`readiness_matrix.py`, `coverage_verdicts.py`,
`snap_only.py`, `gex_capture_audit.py`; DB path via `ED_CONSOLE_DB_RO`, default
`file:data/ed_console.db?mode=ro`), so RC-481's next-RTH rerun is reproducible from the
tree. The remaining one-shot probes (`coverage_audit.py, followup_probe.py,
aug17_probe.py, q1.py, q4.py, q5.py`) were session scratch whose findings the committed
four supersede.

## 4. The 48 closes — complete-set answer (finding 9)

Evidence-class scan over all 48 fix cells — reproduce:
`python -c "import pathlib,re; ids='RC-257 RC-286 RC-287 RC-290 RC-295 RC-297 RC-307 RC-310 RC-316 RC-317 RC-322 RC-326 RC-328 RC-329 RC-345 RC-352 RC-353 RC-356 RC-357 RC-358 RC-361 RC-362 RC-363 RC-364 RC-365 RC-366 RC-369 RC-371 RC-372 RC-373 RC-374 RC-375 RC-382 RC-391 RC-392 RC-396 RC-401 RC-402 RC-403 RC-442 RC-450 RC-453 RC-454 RC-455 RC-456 RC-472 RC-473 RC-474'.split(); rows={m.group(1):m.group(0) for m in re.finditer(r'^\| (RC-\d+) \|.*$',pathlib.Path('governance/root_cause_log.md').read_text(encoding='utf-8'),re.M)}; ex=re.compile(r'pytest|test_[a-z0-9_]+\.py|RAN|--measure|python -m|\.venv',re.I); mech=re.compile(r'check_[a-z_]+|_guard\b|guard\.py|pm_verify|honesty|stop_hook|delta gate|negative control',re.I); import collections; c=collections.Counter(('exec' if ex.search(rows[i].rsplit('|',2)[-2]) else 'mech-only' if mech.search(rows[i].rsplit('|',2)[-2]) else 'neither') for i in ids); print(c)"`
→ 46 cite direct execution evidence; the only 2 mechanism-only closes (RC-326, RC-329) were already
reopened in round 1. Under the taint-fixed claims analyser the tracked test corpus holds
ZERO prose-only files, so no close rests on a prose-shaped test. Round 1's four batches
re-executed the cited suites independently. Remaining epistemic residue: none identified.

## 5. mc_sigma (finding 13)

Resolved leave-and-gate in code: `monte_carlo.mc_sigma_unit_for_row` era classifier +
reader-census pin (`pytest tests/test_mc_sigma_unit_quarantine_v1.py -q` = 6 passed).
The operator's optional data-side decision (partial ×313.5 backfill / unit-flag column)
stays open in RC-478; blast-area detail: `reports/mc_sigma_blast_area_2026-08-25.md`.

## 6. Five-why and anti-sprawl (findings 14–15)

Depth ≥5 + measured-evidence-on-CLOSED stay enforced (`check_root_cause_log`); no
surviving regex claims bedrock judgment (`five_why_reaches_bedrock` retired; tombstones
only). Every auto-governance recipe found (drift-audit phase 6, error-to-lock program,
ledger rule 5 "then add it", REHAB mandate-to-mechanism residue) now routes through the
operator. Net new mechanical surface this round: ONE rule inside an existing pre-commit
hook (REDATE_LOCK — mechanizing the operator's explicit finding 8) and one restored rail
(RC-442); deletions: 5 files + 3 GO markers + dead guard machinery.
