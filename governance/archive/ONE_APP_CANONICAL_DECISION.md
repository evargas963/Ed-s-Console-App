# ONE-APP CANONICAL DECISION (RC-350)

**Decision (operator, 2026-08-14):** the **live app is canonical**. The lineage the
operator runs — anchored as branch `live-canonical` at `5609617d` plus its working-tree
state — is the product. `origin/main` (`d873d998`) is the impostor and is folded INTO
live, never the reverse.

**Direction of reconciliation:** base = `live-canonical`; bring `origin/main`'s 65
non-merge audited commits (five-zone, F31, RC-285/291/297/301/329, pin-fix, RC-350 lock)
onto it. Never merge live's month of product work into the thin `main` slice.

## Mechanical locks (not this doc — this doc only records them)
1. **`live-canonical` branch** anchors the live lineage so it cannot be lost.
2. **`tools/check_live_path_is_main.py` (RC-350)** — fail-closed launch guard: the desk
   may only run a non-detached, non-divergent, clean build of `origin/main`. Wired into
   `start_ed_console.bat` (preflight), pre-push, and CI. After reconciliation `main` ==
   the live app, so the guard passes only when the desk runs the one true trunk.
3. Post-reconciliation: `main` is the single trunk; branches are short-lived and deleted;
   releases are tags on `main`; nothing runs that is not an ancestor of `origin/main`.

## Why live, not main (recorded so it is not re-litigated)
- Live is the real product: 335 commits + a month of features `main` lacks entirely
  (Chart / Exposure / Desk pages do not exist on `main`).
- Folding `main`'s 65 surgical, audited commits into live is far smaller and safer than
  dragging 335 commits + 206 uncommitted files onto `main`.
- The fixes are portable (localized edits); the product is not.
