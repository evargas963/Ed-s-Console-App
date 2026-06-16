# Source-control hygiene

**Scope:** Keep local runtime, model, database, log, and scratch artifacts out of day-to-day git status unless explicitly governed.

**Status:** Active policy | **Mechanical lock:** `tools/check_source_control_hygiene.py`

## Goal

`git status` should show **intentional source changes only**. Generated data, model binaries, backups, logs, auth captures, Excel analysis exports, and repo-root timing probes are **local runtime artifacts** — not source control.

## Categories

| Category | Meaning | Default disposition |
|----------|---------|---------------------|
| `source_should_track` | Production source, tests, governed JSON artifacts | Track in git |
| `generated_runtime_artifact` | DBs, logs, calibration scratch DBs | `.gitignore` |
| `local_secret_or_auth` | OAuth URLs, tokens, keys | `.gitignore` + never commit |
| `database_backup` | Operator DB snapshots under `backups/db/` | `.gitignore` (keep `.gitkeep`) |
| `model_binary_output` | Scheduler/training outputs under `models/active*` | `.gitignore` |
| `analysis_output` | Root-level Excel / enforce audit text dumps | `.gitignore` |
| `scratch_probe` | Repo-root timing probes (`timing_probe*.py`) | `.gitignore` |
| `local_report` | `reports/daily_scoreboard/` operator exports | `.gitignore` |
| `manual_review_required` | Uncertain — classify before track/ignore | Review first |

## Model policy (2026-06-11)

**New local training outputs** under `models/active/`, `models/active_5c/`, `models/active_15c/`, and `models/active_60c/` are **runtime artifacts** and must not be committed.

**Legacy baseline tickers** (e.g. SPY, QQQ, IWM, AAPL) may remain **already tracked** in git history from prior policy. Adding them to `.gitignore` hides **untracked** new tickers only; it does not remove tracked files. Mass `git rm --cached` of baseline models requires an explicit operator decision — not part of this hygiene pass.

Promotion path for a model baseline that must be shared: governed promotion via `arch_competition.promotion_execution.execute_promotion_if_eligible` + explicit operator commit with artifact policy cite — not ad-hoc scheduler output commits.

## Static mockups

`static/redesign_mockup.html` is a **local design mockup** (comment: "Delete freely"; not wired to data). Ignored — not production source. Production UI remains `static/index.html`.

## Artifacts

| Artifact | Command |
|----------|---------|
| Audit snapshot | `governance/artifacts/SOURCE_CONTROL_HYGIENE_AUDIT.json` |
| Checker | `python tools/check_source_control_hygiene.py` |
| Refresh audit counters | `python tools/check_source_control_hygiene.py --write-audit` |

## Objective audit wiring

`check_source_control_hygiene()` runs in `run_repo_wide_static_audit()` (via `tools/enforce_all_rules.py --objective-audit`).

## What this does **not** do

- Delete local files on disk
- Remove historically tracked model baselines from git
- Ignore broad source trees (`tools/`, `tests/`, `governance/artifacts/*.json`)
- Block governed Schwab dictionary CSV or trading calendar JSON under `data/trading_calendar/`
