# Monday debt alarm — setup / status

> **HISTORICAL RECORD (stamped 2026-08-25, audit round 2).** This one-shot 2026-08-03 alarm's
> work orders are dead (RC-166 CLOSED; RC-180/181 have no ledger rows; the cited playbook file
> no longer exists). The repo-side wake machinery (`tools/monday_debt_wake.py`,
> `tools/run_monday_debt_wake.ps1`, `reports/_wake/`) was deleted the same day. **Operator
> action still owed:** delete the host task — `schtasks /Delete /TN "EdMondayDebtWake" /F` —
> which only the operator can do; `governance/host_scheduled_jobs.md` carries the same note.

**Written:** 2026-08-02 (Sunday).  
**Target fire:** **2026-08-03 Monday 08:25 CT** (America/Chicago wall clock; ~5 min before 08:30 CT RTH open).  
**Prompt injected:** `reports/monday_debt_wake_prompt.md`.

---

## What was installed THIS turn (PROVEN)

| Mechanism | Status | Evidence |
|---|---|---|
| **Windows Task Scheduler `EdMondayDebtWake`** | **INSTALLED** | `schtasks /Create` SUCCESS; Next Run **8/3/2026 8:25:00 AM**; Weekly MON; TR → `tools/run_monday_debt_wake.ps1` |
| Wake tool | Landed | `tools/monday_debt_wake.py` + `tools/run_monday_debt_wake.ps1` |
| Wake prompt | Landed | `reports/monday_debt_wake_prompt.md` |
| Cursor Automation (Glass cron) | **DRAFT READY — not auto-saved** | Automations skill requires operator draft approval + "open the editor" confirmation before `open_automation`. Wall-clock CT is already covered by Task Scheduler below. |

Task Scheduler is the **operator-reliable** alarm. Cursor Automation is an optional second channel once the editor draft is approved.

---

## How it works

At 08:25 CT Mondays the task runs:

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File <REPO>\tools\run_monday_debt_wake.ps1
```

Which runs `.venv\Scripts\python.exe tools\monday_debt_wake.py` and:

1. Writes `reports/_wake/monday_debt_go_<YYYY-MM-DD>.json` + `monday_debt_go_LATEST.json` with `status=GO`.
2. Copies `reports/monday_debt_wake_prompt.md` to the clipboard (best effort).
3. Shows a Windows balloon notification.
4. Opens the prompt file in the default editor so you can paste into Cursor/Claude.

Non-Monday runs exit `SKIP` unless `--force` (smoke).

---

## Verify

```powershell
schtasks /Query /TN "EdMondayDebtWake" /FO LIST /V
# expect: Status Ready; Next Run Monday 8:25:00 AM; Days MON

# Smoke (Sunday/any day):
.venv\Scripts\python.exe tools\monday_debt_wake.py --force --no-open
Get-Content reports\_wake\monday_debt_go_LATEST.json
```

---

## Disable / remove

```powershell
schtasks /Change /TN "EdMondayDebtWake" /DISABLE
# or remove:
schtasks /Delete /TN "EdMondayDebtWake" /F
```

Re-enable: `schtasks /Change /TN "EdMondayDebtWake" /ENABLE`.

---

## Cursor Automation draft (optional second channel)

If you want a Cursor cloud/agent cron as well, approve this draft then say **yes, open the Automations editor**:

| Draft field | What will open in the editor |
|-------------|------------------------------|
| Name / description | **Monday debt wake** — Finish RC-166/180/181 live proofs at Monday open |
| Trigger | Every Monday at **08:25** (cron `25 8 * * 1` — confirm timezone in editor matches CT intent) |
| Tools | Default agent tools (no Slack/MCP required) |
| Instructions | Execute `reports/monday_debt_wake_prompt.md` end-to-end; no soft-stop; Decide WAIT |
| Resolved settings | Repo: this EdWebConsole checkout; schedule Monday 08:25 |
| To finish in editor | Confirm cron timezone displays as Central (or convert to UTC if the editor is UTC-only); attach cloud compute if desired |

**Does this look correct?** (Automations skill gate — reply yes + ask to open editor.)

Until then, rely on **EdMondayDebtWake**.

---

## Related host tasks

| Task | Role |
|---|---|
| `EdMondayDebtWake` | **NEW** — morning agent GO for Mon live proofs |
| `EdRthCompletenessCheck` | RC-181 — daily 15:35 CT post-close census (already registered; first meaningful Mon fire is the close) |
| Inventory file | `governance/host_scheduled_jobs.md` (updated same turn) |

**Note measured 2026-08-02:** `EdRthCompletenessCheck` Last Result was non-zero (`-2147020576`) on a Sunday early-morning run — treat as "task exists but last fire unhealthy"; Monday 15:35 CT is still the PASS gate for RC-181.

---

## If automation fails Monday morning — paste this

Open a new Cursor/Claude chat and paste the entire contents of `reports/monday_debt_wake_prompt.md`, or the short GO block in `reports/no_soft_stop_completion_playbook.md`.
