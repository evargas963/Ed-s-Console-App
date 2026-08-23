# PM-authority external wiring — IMPLEMENTATION_READY_FOR_HOST_BOUNDARY

# next-rth-ok: 2026-08-24 Monday
# universal-scope-ok: enforcement-architecture wiring, not a ticker-complete Collect/Chart verdict
# chart-intent-ok: process control; Chart yellow/GEX bars are not claimed Done

**Verdict:** `IMPLEMENTATION_READY_FOR_HOST_BOUNDARY`

Not `PASS`. Host acceptance proof has not been run. Committing `tools/install_pm_authority_host.sh` does not create the capability boundary.

**Reproduce:** `python -m pytest tests/test_pm_authority_external_v1.py tests/test_architecture_a_operator_writer_authority_v1.py tests/test_control_authority_surfaces_v1.py tests/test_writer_drift_lock_v1.py tests/test_operating_process_lock_v1.py -q`

## Inventory (production readers, pre-change)

| Reader | Role after RC-454 | Disposition |
|---|---|---|
| `operating_process_lock.pm_mission_record` | idle-mission + scope | now `pm_authority.executable_mission()` only |
| `operating_process_lock.reset_guard_violations` | adds mission scope to wipe reach | same |
| `process_lock_guard` LOCK-7 | mission_in_progress | same + fail-closed if authority missing |
| `writer_drift_lock.record_sod_drift` | mission_id | same |
| `completion_claim_violations` | OPEN RC vs mission_id | same |
| `rehab_daily_scan` | recommend-only `sole_writer.pm` | now `load_pm_authority()`; tombstone retired |
| `rc_resolve_lock` / commit checker | staged **template** becoming terminal | still inspects Git-tracked report text, not live authority |
| `sole_writer_record` | leftover | tombstone dict; not authorization |

`sole_writer.json` had no remaining executable-authority purpose. Retired. Not copied to `/var/lib/ed-console-authority/`.

## Canonical path

`/var/lib/ed-console-authority/pm_mission.json`

Git-tracked `governance/pm_mission.json` is marked `NON-AUTHORITATIVE`. The reader refuses any canonical path that resolves inside the repository.

## Helper

`tools/pm_authority_helper.py` is **SOURCE**, not the security boundary.

Installed target (host): `/usr/local/sbin/ed_pm_authority_write` (root-owned).

stdin JSON only. No output path. Atomic write. Symlink refuse. Nonzero on refusal.

## Host install (does not prove the boundary)

`tools/install_pm_authority_host.sh` with `CONFIRM=ed-console-authority-host` as root.

Operator must still remove general `NOPASSWD:ALL` and prove every AI channel runs as the restricted user.

## Host acceptance proof — not done

Items 1–16 in the operator brief remain unmeasured on a privileged host. Do not merge until they are.

PR #179 remains diagnosis-only and must not be merged as this fix.
