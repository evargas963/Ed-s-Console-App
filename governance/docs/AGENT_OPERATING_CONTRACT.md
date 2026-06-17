> **Classification:** Active Rule Source | **Scope:** Universal agent preload — Cursor, Claude Code, and compatible agents.

# Agent Operating Contract

**Canonical preload surface.** `AGENTS.md` and `CLAUDE.md` extend this file; they must not drift from it. Mechanical verification: `python tools/check_agent_preload_contract.py`.

---

## Session opening (mandatory)

Before editing code, read and obey governance/docs/AGENT_OPERATING_CONTRACT.md. If you cannot verify that this contract is loaded, stop and report the preload failure. Do not proceed as if normal coding rules apply.

**Read order after this contract:** `ACTIVE_PROGRAM.md` → `AGENTS.md` → `CLAUDE.md` (Schwab market-field work only).

---

## Operating posture

You are **not a patch generator**. You own the fix loop until:

1. The **exact** failing test or command passes (rerun by name).
2. The **related test group** passes.
3. The **broader governance suite** passes when the cone touches governance.
4. **Affected artifacts** are regenerated with commands shown.
5. **Remaining gaps** are explicitly recorded (path, test, reason) — or closed in the same turn.

You may **not** stop at “fix incomplete because X.” That triggers another loop iteration unless X is explicitly out of scope in **Remaining Known Gaps**.

---

## Definition of Done for Fixes

A code edit is **not** a fix. A fix is complete only when the exact failing test has been rerun and passes.

Closed loop: **IDENTIFY → ROOT-CAUSE → PATCH → RERUN EXACT → RERUN GROUP → RERUN BROADER → REGEN ARTIFACTS → REPORT**.

---

## Maturity truth (no inflation)

**Maturity truth source:** `governance/artifacts/SEVERITY_1_CONTROL_VALIDATION_REGISTER.json` — supersedes matrix labels and chat claims.

- **No maturity upgrade from implementation alone** — not from preload files, not from adding `AGENTS.md` / `CLAUDE.md` / Cursor rules, not from checkers that only assert repo presence.
- **L5 requires adversarial proof** — workflow approval, immutable audit, bypass-detection tests, and validation-register evidence. Do not claim L5 institutional enforcement without that proof.
- **Promotion rules:** `governance/artifacts/MATURITY_PROMOTION_RULES.json`.

---

## Repo neatness

- **One maturity truth source** — do not treat `governance_coverage_matrix.json` as enforcement proof.
- **No orphaned governance** — new governance artifacts need an owner, regen command, and consumer or explicit REAL-GATE.
- **Generated artifacts** must document regeneration commands (see `governance/README.md`).

---

## Testing and artifacts before sign-off

| Step | Command pattern |
|------|-----------------|
| Exact failure | `python -m pytest path::test_name -q` |
| Related group | `python -m pytest tests/<cone>/ -q` |
| Broader governance | `python -m pytest tests/decision_reconstruction/ tests/release_object/ tests/test_governance_consolidation.py -q` |
| Objective audit | `python tools/enforce_all_rules.py --objective-audit` |

Regenerate when wiring changes:

```bash
python tools/_build_institutional_audit_phase2.py
python tools/_build_institutional_audit_phase3.py
```

---

## Preload vs enforcement (honest limit)

| Layer | Role |
|-------|------|
| **Preload** (`AGENTS.md`, `CLAUDE.md`, `.cursor/rules/`, this file) | Preload improves compliance — guides agents at session start |
| **Mechanical checks** (`tools/check_*.py`, pre-commit, `--objective-audit`) | Detect missing/weak preload and rule drift |
| **Hooks / CI / branch protection** | True prevention — still required; not replaced by preload |

Preload improves compliance; it is not institutional enforcement by itself.

---

## Required final report format

Every fix or implementation sign-off must include:

```
Files changed:
Commands run:
Exact failing test status:
Related test group status:
Broader suite status:
Artifacts regenerated:
Objective audit status:
Remaining Known Gaps:
Known bypasses still open:
Maturity changes proposed:
Maturity changes rejected:
```

---

## Mechanical lock

`tools/check_agent_preload_contract.py` — wired into `python tools/enforce_all_rules.py --objective-audit`. Paired: `tests/test_agent_preload_contract.py`.
