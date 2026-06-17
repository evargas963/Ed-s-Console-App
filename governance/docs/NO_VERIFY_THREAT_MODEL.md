# No-verify threat model (Phase 3D)

**Scope:** Institutional Audit Phase 3D — local pre-commit bypass threat and external CI/branch-protection mitigation model.

## Threat

`git commit --no-verify` bypasses all local pre-commit hooks with **no audit event**. Same-actor mutation of governance files, manual DB/filesystem edits, env toggles, and disabled jobs remain open bypass classes documented in `UNIVERSAL_BYPASS_REGISTER.json`.

## Local controls (mitigate, do not close)

- Pre-commit via `tools/check_fix_everything_we_touch.py`
- `python tools/enforce_all_rules.py --objective-audit`
- Agent preload contract checkers

**Honest status:** local pre-commit is **bypassable**.

## External mitigation (required for institutional claim)

1. CI workflow `.github/workflows/objective-audit.yml` runs objective audit + governance tests
2. GitHub branch protection requires the `objective-audit` status check
3. Required PR review + CODEOWNERS on governance paths

## Closure criteria for `--no-verify`

| Control | Required for "mitigated" |
|---------|--------------------------|
| CI workflow exists | Yes — provable in-repo |
| CI runs objective audit | Yes — provable in-repo |
| Branch protection verified on GitHub | Yes — **not provable locally** |
| Required checks enforced by GitHub | Yes — **not provable locally** |

**Current acceptable claim:** `--no-verify` status **open**; mitigation path documented.

Artifact: `governance/artifacts/NO_VERIFY_RESISTANCE.json`

Do not set `no_verify_status: closed` unless both CI and branch protection are proven on GitHub.
