# Architecture A — external PM authority: clean landing + host acceptance proof

**Status: OPERATOR_ACTION_REQUIRED.** All repository-side work is complete and
mechanically proven off-host. Exactly one privileged host action remains (below).
This is NOT "implementation ready" theater: the five defects that made PR #179/#180
un-mergeable are closed at the class level and the landing is a clean single diff
against `main`, not stacked on #179.

## The invariant
The operator selects which AI runs. Any selected AI does ordinary product work but
cannot: become the operator; grant itself authority; rewrite/weaken control-authority
enforcement; modify executable PM authority; or bypass via shell/python/subprocess/
path/import/sudo. Executable PM authority keeps `pm="operator"` behind a REAL OS
capability boundary the AI does not hold — not a shell-regex blacklist.

## Design (three planes)
1. **Authority resource (state)** — `/var/lib/ed-console-authority/pm_mission.json`,
   `root:root`, dir `0755`, file `0644`. The AI user can READ, never write/delete/
   rename/chmod/chown.
2. **Reader (in-repo, runs as AI)** — `tools/pm_authority.py`: reads ONLY the canonical
   off-repo path; no repo fallback; fail-closed on missing/malformed/wrong-pm/symlink;
   no env override. The single canonical computation of executable PM state.
3. **Write seam (privileged, runs as root)** — `tools/pm_authority_helper.py` is the
   SOURCE; the installed copy at `/usr/local/sbin/ed_pm_authority_write` (`root:root`,
   `0755`) is the boundary. Self-contained (stdlib only, zero repo imports), validates
   `pm=="operator"` inline, writes the fixed canonical path atomically, refuses
   symlinks/argv/path-injection, and REFUSES to run outside an isolated interpreter.

## The five defects and their class-level close
| # | Defect (in #179/#180) | Close |
|---|---|---|
| 1 | privileged helper `import`s `tools.pm_authority` from the AI-writable checkout | helper is now **self-contained**: stdlib only, no `sys.path`, no `import tools`, no `importlib`. Root loads zero AI-writable code. (`test_helper_is_self_contained_stdlib_only`) |
| 2 | install copies/trusts the live checkout; helper not repo-independent | install **hash-verifies** the source against operator-supplied `EXPECTED_HELPER_SHA256` and **smoke-tests** self-containment (repo absent, hostile `PYTHONPATH`, `cd /`, `-I`) before installing. (`test_install_script_refuses_untrusted_checkout_and_smoke_tests`) |
| 3 | PR #180 stacked on rejected #179 history | this branch is a **single clean commit off `main`** (`db6ca607`); no #179/#180 ancestry. |
| 4 | guard bricked every mission-gated path when the external file was absent (every unprovisioned host incl. Windows/`C:\var\lib\…`) | **degraded mode**: absence of the external boundary is non-enforcing for the PM-workflow product gate (the AI can't induce it on a provisioned host); rails still hard. `measure_report()['pm_authority_mode']` signposts `enforcing`/`degraded`. (`test_c_…product_degraded_not_bricked`) |
| 5 | repo `pm_mission.json` field-flip left unguarded while it was still read | repo files are **non-authoritative**; `pm_mission_record()`/`sole_writer_record()` never read them as authority (`test_i`, `test_j`); the flip gains the AI nothing. |
| 6 | **bootstrap trust chain was circular** — the pin was derived from `sha256sum` of the same live checkout, and root ran the installer directly from that AI-writable checkout, so root executed unverified AI code *before* any freeze/hash could protect it | the bootstrap is now **anchored to an immutable operator-reviewed commit**: the operator materializes the reviewed commit from the REMOTE into ROOT-OWNED staging; the installer **refuses to run unless its tree is root-owned + not AI-writable AND its git HEAD == `ED_PM_REVIEW_COMMIT`**, and the pin is derived from the reviewed commit, never the live checkout. Root never executes the AI-writable installer. (`test_install_script_refuses_untrusted_checkout_and_smoke_tests`) |

## Self-falsification — bypasses FOUND by adversarial agents and FIXED in this pass
A five-agent adversarial sweep attacked each class against the actual code. It found
two real defects (both now fixed and re-verified), which is the process working:
- **install-time TOCTOU** — the first draft hashed `HELPER_SRC`, smoke-tested a throwaway
  copy, and installed `HELPER_SRC` again (three decoupled reads of an AI-writable path),
  so the AI could swap the file between check and install. **Fix:** the installer now
  FREEZES the source once to a root-owned `0400` scratch copy and hashes + smoke-tests +
  installs THAT copy, then RE-HASHES the installed file and aborts on mismatch; it also
  fixes `PATH`, requires a root-owned `/usr/bin/python3` (ignores `ED_PM_PYTHON`), seeds
  the authority file minimally (never from the AI template's scope/remaining), and the
  operator command drops `sudo -E`.
- **`tools/__init__.py` poison** — it executes on every `import tools.*` inside the guard
  process but was not a control-authority surface, so an assigned AI could plant a
  monkeypatch there to neuter `control_authority_violation` and forge `pm=operator`.
  **Fix:** added to `CONTROL_AUTHORITY_EXACT` + CODEOWNERS + a CI test pinning it to
  no-executable-code (`test_tools_package_init_*`). (This gap was latent on `main` too.)

- **hook/enforcement code-injection class** — the guards and pre-commit wrappers import
  ~28 AI-writable `tools/` modules that execute inside the enforcement process; a planted
  module-top statement runs with the enforcer's privileges. **Fix:** the entire
  enforcement-execution closure (PreToolUse/Stop hook closure + pre-commit closure +
  every `tests/**/conftest.py`) is CODEOWNERS-covered, with a **self-maintaining test**
  (`test_enforcement_execution_closure_is_codeowned_and_hooks_railed`) that recomputes
  the closure and fails if a new import escapes coverage. (Latent on `main` too.)

## Security model the adversarial sweep established (the key finding)
The sweep proved a foundational point that **vindicates the mission's instruction to use a
real capability boundary, not shell blacklists**: an assigned AI with a shell can rewrite
any file in its own checkout (`cp`/`mv`/`sed -i`/`tee`/`install`/a python script), and the
in-process PreToolUse guards cannot exhaustively intercept every write channel. Therefore:
- **In-process guards (`control_authority_violation`, PreToolUse/Stop) are DEFENSE-IN-DEPTH,
  not the boundary.** They raise the local bar and catch honest mistakes; they cannot stop
  a determined assigned AI in its own session.
- **The actual capability boundary is three OS/platform facts the AI does not hold:**
  1. **OS ownership** — executable PM authority is a `root:root` file the non-root AI cannot
     write; the write seam is a `root:root` helper. This is what makes `pm=operator`
     unforgeable, and it is *independent of every in-process guard*.
  2. **Non-root AI** — the AI runs as a constrained uid with no general sudo, so it cannot
     escalate to touch the root-owned boundary even after poisoning its own session hooks.
  3. **Merge review** — poisoned enforcement code cannot reach production without operator
     review; the full enforcement-execution closure is CODEOWNERS-gated on protected `main`.
This is why the mission is closeable only with an OS boundary + branch protection, and why
those are the irreducible operator actions below.

## Self-falsification — attack CLASS → why it fails
- **stale writer/auditor/vendor metadata** → never authorization; retired to tombstone; no reader consumes them (`test_i` AST scan). 
- **direct write/delete/rename of the authority file** → AI uid ≠ owner, dir not AI-writable → OS `EPERM` (any tool). *[host-proven]*
- **python & shell mutation** → identical uid boundary, language-independent. *[host-proven]*
- **path construction / alt cwd** → reader refuses in-repo paths, canonical is absolute+fixed, no fallback; helper ignores caller paths (`test_o`, `test_b`).
- **chmod/chown** → only owner/root; AI is neither. *[host-proven]*
- **symlink / redirection** → root-owned dir (no AI symlink plant) + `O_NOFOLLOW`/lstat refusal (`test_p`).
- **import / PYTHONPATH / cwd shadowing** → self-contained helper + `-I` + sudoers `env_reset`; a hostile `json.py` on `PYTHONPATH` is proven NOT executed (`test_helper_ignores_hostile_pythonpath_stdlib_shadow`).
- **general sudo/root escape** → AI has NO general sudo; the ONLY grant is one fixed helper command. *[host: remove `NOPASSWD:ALL`]*
- **mutation/disablement of the enforcement mechanism** → authority file, installed helper, sudoers, parent dirs all root-owned (`EPERM`); in-repo control-authority surfaces (reader, helper SOURCE, install, guards, CI, CODEOWNERS) are operator-review-gated (CODEOWNERS + branch protection) and in-process control-authority-blocked (`test_control_authority_surfaces_v1`).

*[host-proven]* items are the OS-permission facts that require the boundary to exist;
they are asserted by the HOST ACCEPTANCE PROOF below, not by the in-process tests.

## Repository proof already run (this SHA, off-host)
`pytest tests/test_pm_authority_external_v1.py tests/test_architecture_a_operator_writer_authority_v1.py tests/test_control_authority_surfaces_v1.py tests/test_architecture_a_bypass_class_v1.py tests/test_writer_drift_lock_v1.py tests/test_operating_process_lock_v1.py tests/test_pm_full_coverage_lock_v1.py tests/test_pm_verify_repo_lock_v1.py`
→ **193 passed, 1 skipped** (symlink case skips on Windows).

Helper SOURCE SHA-256 (recompute on the merged SHA before install):
`e7ced32cd01d13b082b0047915a8a6f540a0da1c56195f69ce36a0f1ccf02f79`

## THE ONE REMAINING ACTION — operator/root, on the Linux runtime
A capability boundary is by definition a principal the AI does not hold; the AI
cannot create it without holding it, so this step is irreducibly the operator's.

```sh
# 0) TRUST ANCHOR — materialize the OPERATOR-REVIEWED, MERGED commit from the REMOTE
#    into a ROOT-OWNED staging tree. Root never runs the AI-writable checkout, and the
#    pin is derived from the reviewed commit (not the live checkout). C is the commit
#    the operator reviewed on PR #181 (immutable, content-addressed).
C=<operator-reviewed merged commit SHA of PR #181>
sudo rm -rf /srv/ed-console-staging
sudo git clone --no-local <remote-url> /srv/ed-console-staging   # from the remote, not the AI checkout
sudo git -C /srv/ed-console-staging checkout --detach "$C"
[ "$(sudo git -C /srv/ed-console-staging rev-parse HEAD)" = "$C" ] || { echo "staging != reviewed commit"; exit 1; }
# derive the pin from the REVIEWED commit in root-owned staging (never the live checkout):
PIN="$(sudo sha256sum /srv/ed-console-staging/tools/pm_authority_helper.py | awk '{print $1}')"

# 1) Provision the boundary by running the installer FROM ROOT-OWNED STAGING (it refuses
#    to run from any AI-writable tree or a tree whose HEAD != C):
sudo env \
  EXPECTED_HELPER_SHA256="$PIN" \
  ED_PM_REVIEW_COMMIT="$C" \
  CONFIRM=ed-console-authority-host \
  ED_AI_USER=<the-uid-the-AI-runs-as> \
  sh /srv/ed-console-staging/tools/install_pm_authority_host.sh   # NOT sudo -E

# 2) Remove the AI user's general sudo / NOPASSWD:ALL (host config, not this repo).

# 3) HOST ACCEPTANCE PROOF (run as the AI uid unless noted); each must behave as stated:
sudo -n -l                                  # lists ONLY ed_pm_authority_write; no ALL
python3 -c "open('/var/lib/ed-console-authority/pm_mission.json','w')"   # -> PermissionError
echo '{"pm":"operator","status":"idle"}' | sudo /usr/local/sbin/ed_pm_authority_write   # -> exit 0
echo '{"pm":"cursor"}'   | sudo /usr/local/sbin/ed_pm_authority_write   # -> exit 2, no write
printf 'nope'            | sudo /usr/local/sbin/ed_pm_authority_write   # -> exit 2, no write
# with the repo checkout deleted, the installed helper still runs (self-contained):
sudo rm -rf /path/to/checkout && echo '{"pm":"operator"}' | sudo /usr/local/sbin/ed_pm_authority_write  # -> exit 0
# 4) then, on the exact SHA: full pytest + hardening + required CI green.
```

## THE OTHER IRREDUCIBLE OPERATOR STEPS (platform, not repo)
- **Land this control-authority PR.** An assigned AI is denied control-authority rewrites
  by design (invariant #5 — the pre-commit rail blocks even this authoring agent's commit),
  so landing requires the operator: grant a scoped `governance/operator_go.json`
  `staged_lock_surface` GO and commit, OR the operator commits/merges, then restore
  fail-closed. The AI must NOT self-grant that GO (it is itself a control-authority rail).
- **Enable branch protection on `main`**: require CODEOWNERS review + required CI status
  checks for the protected paths. This is what makes the merge-review boundary real — the
  repo defines the owned set; GitHub enforces it. The AI cannot set this.

Until (1)–(4), the landing, and branch protection are in place, the boundary is **not
proven** and the parent mission stays NOT_PROVEN. The repository side owes nothing further:
the code, tests (193 pass), self-falsification (2 bypasses found+fixed, class-closure
completed), and the exact host/platform steps are all delivered.
