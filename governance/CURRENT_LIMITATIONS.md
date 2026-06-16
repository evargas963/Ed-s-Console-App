> **Classification:** Operational Ledger | **Scope:** Phase 3F honest limitations — open gaps only.

# Current limitations (honest gaps)

**Generated:** 2026-06-15  
This file lists what is **not** proven. Do not infer maturity from green local CI alone.

| ID | Title | Status | Next action |
|----|-------|--------|-------------|
| `live_schwab_proof` | Live Schwab traffic proof missing | `unproven` | Operator host with Schwab auth: capture production decision from live _fetch_state and blind-reconstruct. |
| `github_branch_protection` | GitHub branch protection not API-verified | `required_not_proven` | Configure GitHub protection on main OR run python tools/verify_remote_enforcement.py --fetch-github on authenticated machine. |
| `required_status_checks` | Required GitHub status check not enforced until protection configured | `required_not_proven` | Push workflow, run on main, add objective-audit as required check in GitHub Settings. |
| `no_verify_external` | git commit --no-verify bypass | `external_required` | GitHub branch protection with required check objective-audit. |
| `manual_mutation_detection_only` | Manual DB/filesystem mutation detected not prevented | `detected_not_prevented` | Phase beyond 3F if prevention required (external storage, append-only audit). |
| `r012_route_gap` | R-012 GET /api/live/state Tier A still gapped | `unproven` | Dedicated R-012 adversarial proof or non-production classification with evidence. |
| `l5_not_claimed` | L5 institutional enforcement not claimed | `explicitly_rejected` | Do not promote maturity without MATURITY_PROMOTION_RULES.json criteria met. |
| `universal_enforcement` | Universal route enforcement not claimed | `explicitly_rejected` | Evidence-backed bypass reduction only — no cosmetic count changes. |

## Required gaps (checker-enforced)

`github_branch_protection`, `l5_not_claimed`, `live_schwab_proof`, `manual_mutation_detection_only`, `no_verify_external`, `r012_route_gap`, `required_status_checks`

Regenerate: `python tools/_build_current_limitations.py`
