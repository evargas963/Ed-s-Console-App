# governance/ — what lives here

> Rewritten 2026-08-25 (independent-audit round 2). The previous README was a fossil of the
> pre-slimming governance system — a truth-source table, maturity ladder (L0–L5), phase plan,
> and regeneration commands whose files and tools were retired in the 2026-07 slimming and the
> 2026-08-24 Architecture A teardown. History: `git log --follow governance/README.md`.

**Operating authority is [`AGENTS.md`](../AGENTS.md)** (charter + operating model + laws and
their enforcement map). Nothing in this directory grants work authority; the operator directs
each session in chat.

## Live ledgers and registers

| File | Holds |
|---|---|
| `root_cause_log.md` | Defects in our code — five-why rows, OPEN/CLOSED, machine-validated by `check_root_cause_log` |
| `retired_checks.md` | Append-only manifest of retired enforced checks (base-side, two-step removal contract) |
| `unproven_register.md` | Claims about the world — UNPROVEN/PROVEN/DISPROVED with due dates |
| `OPERATOR_DECISION_REGISTER.md` | O-NN operator decision narratives |
| `agent_error_log.md` | July-2026 historical error record (E-01..E-39) |
| `host_scheduled_jobs.md` | The single visible inventory of Windows scheduled tasks |
| `decision_path_admissions.json` | Decision-path admission registry (starts empty; unadmitted → WAIT) |
| `guard_applicability.json` | Append-only applicability history (the RC-93 entry is retired; the UNIVERSAL-SAFETY declaration stands; read by tests, not by live guard code) |

## Live program / process docs

| File | Holds |
|---|---|
| `AGENT_OPERATING_PROCESS_V1.md` | Process integrity checklist (measure-before-claim, small landings, LIVE vs DISK) |
| `REHAB_PROGRAM.md` | Operator-invoked rehab program (RH-F1 multi-faucet spine + facets) |
| `CONSOLE_REBUILD_PLAN_CR_V1.md` | Console rebuild design record (execution status: `ACTIVE_PROGRAM.md` §CR) |
| `Framework-ED-Decision-Engine-v1.1.md` | Decision-engine framework reference |
| `STACK_WIRING_INTEGRITY_MAP.md` | Stack wiring map (content live; provenance header historical) |
| `TRADE_IMPACTING_ROUTE_INVENTORY.md` | Trade-impacting route inventory |
| `DERIVED_ANALYTICS_REGISTRY.md` | Derived-analytics registry |

## Contracts, crosswalks, and generated inventories

The `A1_*` / `A2_*` / `PILOT_*` contract docs, the Schwab CSV crosswalk CSVs/YAMLs, the
`mega*_traceable_inventory.py` census tools, and `computation_registry.json` /
`level_faucets.json` / `plus_player_attributes.json` are live references consumed by checks
and tests; superseded contract versions resolve under `archive/`.

`archive/` holds retired programs, the 2026-Q2 memory archive, and superseded artifacts —
history, never authority.
