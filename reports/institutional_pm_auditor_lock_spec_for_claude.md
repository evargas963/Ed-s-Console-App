# Institutional PM/Auditor lock spec for Claude (encode checklist)

**Author:** Cursor (PM/auditor) · **Writer of locks:** Claude · **Date:** 2026-08-03  
**Scope:** Mechanical locks that bind Cursor as PM/auditor only.  
**OUT-OF-SCOPE:** Product faucet kills (`chart.html` / `server.py` kill work). No git reset by Cursor. Prefer no commit during Claude rebuild.  
**Not legal advice** — control-design themes only.

---

## A) Research findings (principles + citations)

### Principles (map → Ed Console roles)

| Principle | Institutional meaning | Ed mapping |
|---|---|---|
| **Segregation of duties (SoD)** | No single person initiates + approves + deploys a high-risk change | Claude = maker/writer; Cursor = checker/auditor; operator = sign-off (GO) |
| **Maker-checker** | Author ≠ approver/deployer | Cursor must not edit `scope_paths` or kill product; Cursor falsifies after landing |
| **Change control / CAB-as-gates** | Request → approve → implement → independent test → close with evidence; automate gates | `pm_mission.json` + PreToolUse/Stop/commit `.py` BLOCKs (not meeting theater) |
| **Audit independence** | Auditor objective in fact and appearance; evidence stands alone | Cursor audits; must not also be sole writer on same mission |
| **RACI / RASCI-VS** | Separate Responsible / Accountable / Verify / Sign-off | R=Claude, A=operator, C=Cursor PM, V=Cursor auditor + quiet/LIVE gates, S=`operator_go.json` |
| **IC ≠ implementer** | Incident Commander coordinates; Ops Lead executes | Cursor PM = IC; Claude = Ops/implementer |
| **Trust but verify / professional skepticism** | Do not assume honesty; require persuasive evidence | MEASURE hashes; PROVEN vs `[UNVERIFIED]`; quiet PASS before COMPLETE when LIVE bar set |
| **Evidence before assertion** | Documentation of procedures, evidence, conclusions; oral alone insufficient | Stop/completion claims need resolvable artifacts (quiet JSON, index=WT, RC resolve) |
| **No conflicting access** | Developer must not sole-control production migration / audit log | Cursor cannot reset product tree mid-mission; cannot invent `.md` locks as substitute |

### Citations (URLs)

1. SOX / ITGC change + SoD (design themes): https://legalclarity.org/sox-change-management-controls-requirements-and-audits/
2. ITGC overview (SoD, maker-checker, change mgmt): https://eduyush.com/en-us/blogs/cima/itgc
3. SOX IT controls checklist (change, access, ops): https://hunto.ai/resources/sox-it-controls-checklist/
4. IT SoD conflicts (developer vs deployer / audit trail): https://www.zluri.com/blog/it-segregation-of-duties
5. Basel BCBS internal control — Principle 6 SoD: https://www.bis.org/publ/bcbs40.pdf
6. COSO Internal Control — Integrated Framework (control activities / SoD): https://www.coso.org/_files/ugd/3059fc_1df7d5dd38074006bce8fdf621a942cf.pdf
7. Brokerage maker-checker SoD (ops analogy): https://brokeret.com/blog/maker-checker-segregation-of-duties-brokerage-operations
8. Google SRE incident response (IC vs Ops Lead): https://sre.google/workbook/incident-response/
9. ICS: IC coordinates, does not fix: https://hld.handbook.academy/curriculum/reliability-and-operations/incident-management/
10. RASCI-VS Verify + Sign-off: https://umbrex.com/resources/frameworks/organization-frameworks/rasci-rasci-vs-variants/
11. PCAOB AS 1000 (independence, professional skepticism): https://pcaobus.org/oversight/standards/auditing-standards/details/as-1000--general-responsibilities-of-the-auditor-in-conducting-an-audit
12. PCAOB AS 1215 (audit documentation stands alone): https://pcaobus.org/oversight/standards/auditing-standards/details/AS1215
13. PCAOB AS 1105 (audit evidence appropriateness/reliability): https://pcaobus.org/oversight/standards/auditing-standards/details/AS1105
14. Change approval automation / author ≠ sole approver: https://www.securityscientist.net/blog/12-questions-and-answers-about-change-approval-automation-in-high-velocity-teams/
15. CAB in DevOps (risk-based gates, not rubber-stamp meetings): https://www.joetheitguy.com/how-to-run-a-change-advisory-board-in-a-devops-world/

---

## B) Claude encode checklist (mechanical — extend existing modules)

**Do not create a mandate novel.** Extend:

- `tools/writer_drift_lock.py`
- `tools/process_lock_guard.py` (+ `tools/operating_process_lock.py`)
- `tools/pretooluse_guard.py` / `tools/operator_law_guard.py` (Shell)
- `tools/check_institutional_correctness.py` (ENFORCED + negative-control tests)
- `tools/rc_resolve_lock.py` (already present — wire the missing checker)

**Hard product denylist (always when `writer≠cursor` and mission in-progress):**  
`static/chart.html`, `server.py`, `market_context.py`, `db.py`, kill/faucet tests under `tests/` matching faucet/prior_day/levels kill patterns, any path in `mission.scope_paths` that is not PM-allowlisted.

### LOCK-1 — Cursor cannot edit product / scope / kill paths (tighten RC-226)

| Item | Spec |
|---|---|
| **Trigger** | PreToolUse Edit/Write/StrReplace/Delete/MultiEdit when `ED_AGENT_ROLE` default cursor; mission in `MISSION_IN_PROGRESS_STATUSES`; `resolved_writer()≠cursor` |
| **BLOCK** | Any path in `scope_paths` OR hard denylist above OR `MISSION_GATED_PREFIXES` product surfaces — deny prefix `SOD_DRIFT:` |
| **Allowlist ONLY** | Keep/tighten `PM_ALLOWLIST_EXACT` + `reports/*audit*|*handoff*|rehab*|rc_open_drain*` |
| **Tighten** | (a) Cursor may edit `pm_mission.json` / `sole_writer.json` **status/blocker/note fields only** — BLOCK mutations that change `writer`, expand `scope_paths`, or delete `remaining` kill rows without `# pm-status-ok:` operator escape. (b) Remove or gate Cursor ability to Edit `tools/check_institutional_correctness.py` / lock `.py` **unless** mission `pm` explicitly sets `"cursor_lock_encode_ok": true` (default false). Prefer Claude encodes locks. (c) `tests/` in scope → Cursor BLOCK (today idle `tests/` is too open). |
| **Commit backstop** | Existing `check_writer_no_drift` / `live_writer_drift_violations(staged_only=True)` |
| **Tests** | Extend `tests/test_writer_drift_lock_v1.py`: chart.html / server.py / kill test path → BLOCK; audit report path → allow; pm_mission writer flip by cursor → BLOCK |

### LOCK-2 — Reset-guard (git reset/checkout/restore of product paths)

| Item | Spec |
|---|---|
| **Gap today** | `operator_law_guard._DESTRUCTIVE_GIT` only catches `reset --hard`, `checkout -- `, `clean -f`, force-push — **not** soft `git reset`, `git restore`, `git checkout -- <path>`, `git checkout HEAD -- <path>` |
| **Trigger** | PreToolUse Shell/Bash/PowerShell when mission in-progress OR dirty scope paths exist |
| **BLOCK** | Commands matching (case-insensitive): `git reset`, `git restore`, `git checkout --`, `git checkout HEAD --`, `git clean`, and path-targeted restore/checkout of denylist / `scope_paths` |
| **Escape** | Operator-only `ED_RESET_GUARD=off` (visible) OR explicit operator chat GO recorded in `operator_go.json` scope `git_reset_product` |
| **Wire** | Prefer new predicate in `operating_process_lock.reset_guard_violations(cmd)` called from `process_lock_guard.pretooluse_block` **and** widen `_DESTRUCTIVE_GIT` in `operator_law_guard.py` |
| **Tests** | Negative: `git reset -- static/chart.html` BLOCK; `git status` allow; `git diff` allow |

### LOCK-3 — Cursor PM allowlist (tight)

**ALLOWED when writer=claude / mission active:**

1. Chat (no file mutation)
2. Read / MEASURE / run read-only probes (`--measure`, quiet window **read**, pytest of lock tests only if allowlisted)
3. Write/Edit: `reports/*audit*`, `reports/*handoff*`, `reports/rehab_*`, `reports/rc_open_drain*`, `reports/institutional_pm_auditor_lock_spec_for_claude.md`
4. `governance/pm_mission.json` — **status / note / blocker / approved_* only** (LOCK-1)
5. `governance/sole_writer.json` — `updated_at` / `note` / `held_commit` only; **not** flipping `writer`/`pm`/`auditor` without operator `# sod-role-ok:`
6. `governance/root_cause_log.md` — OPEN rows with resolve path (RC-228 clause A) for audit findings
7. Cursor rules under `.cursor/rules/07*` / `08*` only if encoding PM process (prefer Claude for lock `.py`)

**DENIED:** product HTML/JS/CSS/py, kill tests, faucet census product edits, inventing new `governance/*MANDATE*.md` as substitute for a `.py` BLOCK, `git reset`/`restore` product, claiming COMPLETE without evidence.

### LOCK-4 — Self-heal on drift (tighten)

| Item | Spec |
|---|---|
| **On SOD_DRIFT deny** | Auto-deny already; add: require same-turn OPEN RC with `FIXED:`/`NEXT-DEPTH:`/`OUT-OF-SCOPE:` naming `mission_id` + `SOD_DRIFT` (Stop or next Edit of RC log). Optional ledger file `reports/sod_drift_events.jsonl` append-only from guard. |
| **Stop** | If last turn had SOD_DRIFT deny and no new RC row → Stop BLOCK `SELF_HEAL_OWED:` |
| **Do not** | Auto-edit product to “fix” drift; restore SoD via mission/sole_writer status fields only |

### LOCK-5 — No COMPLETE without quiet PASS when LIVE bar set

| Item | Spec |
|---|---|
| **Trigger** | Stop / completion_claim_violations when text matches COMPLETE/mission complete/LIVE_ENFORCED **and** mission `done_criteria` or note sets live bar (`"live_bar": "quiet_window"` or done_criteria contains quiet-window language) **or** last landing touched `server.py`/`db.py` |
| **Evidence** | `reports/ed_server_warn_quiet_window_latest.json` with `pass`/`status` PASS (schema as produced by `tools/ed_server_warn_quiet_window.py`) and `generated_at` within mission window |
| **BLOCK** | COMPLETE/LIVE claim without that PASS → `QUIET_PASS_REQUIRED:` |
| **Honest escape** | Explicit `DISK_ONLY_UNTIL_RESTART` in same claim text (existing) OR `# quiet-bar-ok:` operator waiver in mission |
| **Wire** | Extend `completion_claim_violations` in `operating_process_lock.py` |

### LOCK-6 — RC document-without-resolve (land the checker)

| Item | Spec |
|---|---|
| **Module exists** | `tools/rc_resolve_lock.py` + `tests/test_rc_document_without_resolve_v1.py` |
| **GAP (MEASURED this turn)** | `check_rc_document_without_resolve` is **absent** from `tools/check_institutional_correctness.py` (rg: no matches). AGENTS.md / RC-228 claim it ENFORCED — encode for real. |
| **Implement** | `def check_rc_document_without_resolve()` calling `staged_rc_resolve_violations` on staged RC + mission diffs; register `("rc_document_without_resolve", check_rc_document_without_resolve, True)` in ENFORCED list; ensure negative-control test entry |
| **Keep** | Stop path already uses `open_rcs_owned_by_mission` inside `completion_claim_violations` |

### LOCK-7 — No process-md theater as action substitute

| Item | Spec |
|---|---|
| **Existing** | `honesty_guard.py` BLOCKs claiming mechanical lock via `.md/.mdc` |
| **Tighten** | PreToolUse: when writer≠cursor and mission active, BLOCK Cursor creating **new** `governance/*` mandate/process novels outside allowlist (`PM_MANDATE`/`REHAB`/`AGENT_OPERATING` updates only with `# process-doc-ok:`). Prefer extending `.py` locks. |
| **Stop** | Pattern: “encoded in mandate/rule” without citing a CHECK id / guard `.py` → honesty BLOCK (extend regex carefully) |

### Acceptance tests Claude must ship

1. `tests/test_writer_drift_lock_v1.py` — denylist + status-only mission
2. `tests/test_reset_guard_v1.py` — new
3. `tests/test_rc_document_without_resolve_v1.py` — green with real checker registered
4. `tests/test_operating_process_lock_v1.py` — quiet PASS COMPLETE clause
5. Prove BLOCK with injected fixtures (not live chat theater)

### Non-goals for this encode mission

- Do not kill chart faucets / strip / PDH in this lock mission
- Do not `git reset` Claude’s tree
- Do not mass-fake CLOSE OPEN RCs
- Fix merge conflict markers in `governance/pm_mission.json` + `sole_writer.json` **first** (MEASURED: conflict markers present) before arming status=active cleanly

---

## C) Already exists vs gaps

| Control | Status | Gap |
|---|---|---|
| Writer drift PreToolUse (`pm_mission_edit_violation` + `SOD_DRIFT:`) | EXISTS | Allowlist too wide (`check_institutional_correctness.py`, full `pm_mission` mutate); `tests/` idle hole |
| `check_writer_no_drift` commit | EXISTS | Same scope looseness |
| Sole writer dual-edit | EXISTS | OK for protected paths |
| Destructive git hard reset | PARTIAL | Soft reset/restore/path checkout not covered; not mission-scoped product reset-guard |
| Completion claims index≠WT / DISK_ONLY | EXISTS | No quiet-window PASS binding |
| RC-228 module + Stop OPEN-RC COMPLETE | PARTIAL | **Checker not registered** in `check_institutional_correctness.py` |
| Honesty MD-as-lock | EXISTS | Does not stop Cursor writing new process-md instead of encoding |
| Self-heal RC on drift | DOCUMENTED in rules | Not mechanically required after SOD_DRIFT deny |
| Cursor hooks continuum | EXISTS (`.cursor/hooks.json` → process_lock + operator_law) | Reset-guard + quiet PASS + status-only mission still missing |

---

## Operator / Claude note (MEASURED)

`governance/pm_mission.json` and `governance/sole_writer.json` currently contain Git conflict markers (`<<<<<<< ours` / `=======` / `>>>>>>> theirs`). Claude must resolve to one coherent mission (writer=claude, pm=cursor) before relying on SoD gates — conflicted JSON loaders may return `{}` and **silently weaken** locks.
