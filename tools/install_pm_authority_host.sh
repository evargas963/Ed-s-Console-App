#!/bin/sh
# Host installation for executable PM authority (Architecture A).
#
# COMMITTING THIS SCRIPT DOES NOT CREATE THE BOUNDARY. The boundary exists only
# after a privileged host principal (NOT the assigned AI) runs this as root AND
# the HOST ACCEPTANCE PROOF (reports/pm_authority_external_implementation.md) is
# measured on the exact SHA.
#
# Integrity model — the bootstrap is ANCHORED to an immutable operator-reviewed commit,
# NOT to the AI-writable checkout:
#   - This script REFUSES to run unless the tree it runs from is ROOT-OWNED and not
#     group/other-writable (the AI's own checkout is AI-owned, so running from it aborts),
#     AND that tree's git HEAD equals ED_PM_REVIEW_COMMIT (the exact commit the operator
#     reviewed). Root therefore never executes an unverified installer from the AI checkout.
#   - EXPECTED_HELPER_SHA256 is the operator's pin derived from the REVIEWED COMMIT (from the
#     remote, not the live checkout); it is re-checked here against the staged helper.
#   - It then FREEZES the helper to a root-owned scratch copy, re-hashes the INSTALLED file,
#     and pins PATH + a root-owned interpreter (defense-in-depth on top of the anchor).
#
# Usage — the operator MATERIALIZES THE REVIEWED COMMIT FROM THE REMOTE INTO ROOT-OWNED
# STAGING FIRST, then runs THIS script from there (never from the AI-writable checkout):
#   C=<operator-reviewed merged commit SHA of PR #181>
#   sudo git clone --no-local <remote-url> /srv/ed-console-staging
#   sudo git -C /srv/ed-console-staging checkout --detach "$C"
#   sudo env EXPECTED_HELPER_SHA256=<pin derived from the reviewed commit> \
#        ED_PM_REVIEW_COMMIT="$C" CONFIRM=ed-console-authority-host \
#        ED_AI_USER=<the-uid-the-AI-runs-as> \
#        sh /srv/ed-console-staging/tools/install_pm_authority_host.sh   # NOT sudo -E

set -eu

# Fixed, root-owned PATH — ignore whatever the caller's environment carried, so a
# shadowed sha256sum/install/cp/awk/grep/visudo cannot become root code execution.
PATH="/usr/sbin:/usr/bin:/sbin:/bin"
export PATH
# Neutralize temp-dir hijack: mktemp honors TMPDIR, so a caller-supplied TMPDIR could
# relocate the root-owned scratch under an AI-owned parent (deletable/renamable).
# Force the system default (/tmp, sticky) regardless of the environment.
unset TMPDIR TMP TEMPDIR

CONFIRM_REQUIRED="ed-console-authority-host"
AUTHORITY_DIR="/var/lib/ed-console-authority"
AUTHORITY_FILE="${AUTHORITY_DIR}/pm_mission.json"
HELPER_INSTALL="/usr/local/sbin/ed_pm_authority_write"
SUDOERS_DROP="/etc/sudoers.d/ed-pm-authority"
AI_USER="${ED_AI_USER:-ubuntu}"
# Interpreter is fixed and must be root-owned — NOT taken from the environment.
PYTHON_BIN="/usr/bin/python3"

fail() { echo "install_pm_authority_host.sh: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "must run as root (host provisioner)"
[ "${CONFIRM:-}" = "${CONFIRM_REQUIRED}" ] || fail "set CONFIRM=${CONFIRM_REQUIRED} to proceed (the AI cannot casually lock the host)"
# AI_USER is interpolated into the sudoers drop; a stray value could inject an
# over-grant that visudo would still accept. Require a plain unix username.
echo "${AI_USER}" | grep -qE '^[a-z_][a-z0-9_-]*$' || fail "ED_AI_USER=${AI_USER} is not a valid unix username"
[ -x "${PYTHON_BIN}" ] || fail "interpreter ${PYTHON_BIN} not executable"
# The interpreter root will run must itself be root-owned (not an AI-planted binary).
PYOWN=$(stat -c '%U' "${PYTHON_BIN}" 2>/dev/null || echo "?")
[ "${PYOWN}" = "root" ] || fail "interpreter ${PYTHON_BIN} is not root-owned (owner=${PYOWN})"

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
HELPER_SRC="${REPO_ROOT}/tools/pm_authority_helper.py"
TEMPLATE="${REPO_ROOT}/governance/pm_mission.json"

# ── BOOTSTRAP TRUST ANCHOR (operator review 2026-08-23) ──────────────────────────
# Root must NEVER execute this installer from the AI-writable checkout, and the pin
# must be anchored to an IMMUTABLE operator-reviewed commit, not derived from the same
# mutable source. The operator materializes the reviewed commit from the remote into a
# ROOT-OWNED staging tree and runs this script from THERE; the checks below refuse
# anything else. Freeze-once (below) hardens the install step; THESE checks establish
# trust in the installer/helper themselves before any privileged action.
[ -n "${ED_PM_REVIEW_COMMIT:-}" ] || fail "set ED_PM_REVIEW_COMMIT to the operator-reviewed commit SHA and run from a root-owned staging checkout of it (see reports/pm_authority_external_implementation.md); refusing to trust the live checkout"

# (1) The tree this script runs from must be root-owned and not group/other-writable.
# The AI's own checkout is owned by the AI uid, so running from it REFUSES here.
for _p in "${SCRIPT_DIR}" "${REPO_ROOT}" "$0" "${HELPER_SRC}"; do
  _own=$(stat -c '%U' "${_p}" 2>/dev/null || echo "?")
  _mode=$(stat -c '%a' "${_p}" 2>/dev/null || echo "777")
  [ "${_own}" = "root" ] || fail "refusing: ${_p} is owned by '${_own}', not root — run from a ROOT-OWNED staging checkout of the reviewed commit, never the AI-writable checkout"
  [ "$(( 0${_mode} & 022 ))" -eq 0 ] || fail "refusing: ${_p} is group/other-writable (mode ${_mode}) — staging must not be writable by the AI"
done

# (2) The staging content must be EXACTLY the operator-reviewed commit. A commit SHA is
# content-addressed, so the AI cannot change what ED_PM_REVIEW_COMMIT contains, and it
# cannot write the root-owned staging. This binds the installer AND the helper to the
# reviewed version.
command -v git >/dev/null 2>&1 || fail "git required to verify the reviewed commit"
_head=$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo "")
[ "${_head}" = "${ED_PM_REVIEW_COMMIT}" ] || fail "refusing: staging HEAD ('${_head:-none}') != operator-reviewed ED_PM_REVIEW_COMMIT ('${ED_PM_REVIEW_COMMIT}') — materialize the exact reviewed commit from the remote"
# HEAD names the commit; a clean working tree binds the FILES ON DISK to that commit's
# tree, so the installer/helper it actually reads are byte-for-byte the reviewed content
# (not a HEAD-matching-but-modified checkout).
git -C "${REPO_ROOT}" diff --quiet HEAD -- 2>/dev/null || fail "refusing: staging working tree is dirty vs ${ED_PM_REVIEW_COMMIT} — the on-disk files do not match the reviewed commit"

[ -f "${HELPER_SRC}" ] || fail "missing helper source ${HELPER_SRC}"
[ -n "${EXPECTED_HELPER_SHA256:-}" ] || fail "set EXPECTED_HELPER_SHA256 to the operator-reviewed pin of tools/pm_authority_helper.py"

# --- (0) FREEZE the source ONCE to a root-owned scratch copy --------------------
# Everything after this point (hash, smoke, install, re-hash) operates on FROZEN,
# never on the AI-writable HELPER_SRC. This is the TOCTOU close.
umask 077
SCRATCH=$(mktemp -d)
trap 'rm -rf "${SCRATCH}"' EXIT
FROZEN="${SCRATCH}/ed_pm_authority_write"
cp "${HELPER_SRC}" "${FROZEN}"
chown root:root "${FROZEN}"
chmod 0400 "${FROZEN}"

# --- (1) INTEGRITY GATE against the operator-reviewed pin (hash the FROZEN copy) -
ACTUAL_SHA=$(sha256sum "${FROZEN}" | awk '{print $1}')
if [ "${ACTUAL_SHA}" != "${EXPECTED_HELPER_SHA256}" ]; then
  fail "helper source hash mismatch — refusing.
  expected: ${EXPECTED_HELPER_SHA256}
  actual:   ${ACTUAL_SHA}
  The checkout does not match the operator-reviewed helper. Do NOT install."
fi

# --- (2) SELF-CONTAINMENT SMOKE TEST on the FROZEN copy -------------------------
# Run from '/' under isolated mode with a hostile PYTHONPATH shadow of a stdlib
# name. A self-contained helper prints its stdin-only refusal (rc 2, "PM_AUTHORITY");
# a helper that imports repo code or executes the shadow behaves differently -> abort.
HOSTILE="${SCRATCH}/hostile"; mkdir -p "${HOSTILE}"
printf 'raise SystemExit("PYTHONPATH shadow executed")\n' > "${HOSTILE}/json.py"
set +e
( cd / && PYTHONPATH="${HOSTILE}" "${PYTHON_BIN}" -I "${FROZEN}" </dev/null >/dev/null 2>"${SCRATCH}/err" )
SMOKE_RC=$?
set -e
if [ "${SMOKE_RC}" -ne 2 ] || ! grep -q "PM_AUTHORITY" "${SCRATCH}/err"; then
  echo "--- smoke stderr ---" >&2; cat "${SCRATCH}/err" >&2
  fail "self-containment smoke test failed (rc=${SMOKE_RC}) — helper is not repo-independent; refusing to install"
fi

# --- (3) authority dir + file (root-owned; AI user read-only) ------------------
# Seed MINIMALLY: pm=operator + idle. Do NOT import scope_paths/remaining/status
# from the AI-writable template — the operator sets real mission state later via the
# privileged helper (which validates). We only consult the template to confirm the
# operator intent pm=operator is present; nothing AI-controlled reaches the seed.
install -d -o root -g root -m 0755 "${AUTHORITY_DIR}"
chown root:root "${AUTHORITY_DIR}"; chmod 0755 "${AUTHORITY_DIR}"
if [ ! -f "${AUTHORITY_FILE}" ]; then
  if [ -f "${TEMPLATE}" ]; then
    "${PYTHON_BIN}" -I - "${TEMPLATE}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    doc = json.loads(fh.read())
if not isinstance(doc, dict) or doc.get("pm") != "operator":
    raise SystemExit("template is not a valid pm=operator document")
PY
  fi
  printf '{\n  "pm": "operator",\n  "status": "idle"\n}\n' > "${AUTHORITY_FILE}"
fi
chown root:root "${AUTHORITY_FILE}"; chmod 0644 "${AUTHORITY_FILE}"

# --- (4) install the FROZEN, hash-verified, smoke-tested helper (root-owned) ----
install -o root -g root -m 0755 "${FROZEN}" "${HELPER_INSTALL}"
chown root:root "${HELPER_INSTALL}"; chmod 0755 "${HELPER_INSTALL}"

# --- (4b) RE-HASH the installed file: it must equal the frozen/verified copy ----
INSTALLED_SHA=$(sha256sum "${HELPER_INSTALL}" | awk '{print $1}')
if [ "${INSTALLED_SHA}" != "${ACTUAL_SHA}" ]; then
  rm -f "${HELPER_INSTALL}"
  fail "post-install hash mismatch (installed=${INSTALLED_SHA} != verified=${ACTUAL_SHA}) — removed; refusing"
fi

# --- (5) narrow sudoers: AI user runs ONLY this one command, env reset ----------
# NOT ALL. Isolated interpreter is enforced by the helper shebang (#!/usr/bin/python3 -I)
# AND by the helper's own sys.flags.isolated guard; env_reset + secure_path strip
# PYTHONPATH/PYTHONHOME regardless.
cat > "${SUDOERS_DROP}" <<EOF
# Ed Console PM authority — ONLY the installed helper. Not ALL.
Defaults!${HELPER_INSTALL} env_reset
Defaults!${HELPER_INSTALL} secure_path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
${AI_USER} ALL=(root) NOPASSWD: ${HELPER_INSTALL}
EOF
chmod 0440 "${SUDOERS_DROP}"
visudo -cf "${SUDOERS_DROP}"

echo "installed ${AUTHORITY_FILE} (root:root 0644) and ${HELPER_INSTALL} (root:root 0755)"
echo "helper pin verified (frozen + installed): ${ACTUAL_SHA}"
echo "BOUNDARY IS NOT PROVEN until the HOST ACCEPTANCE PROOF is measured on this SHA."
echo "REMAINING UNAVOIDABLE OPERATOR STEP: ensure ${AI_USER} has NO general sudo /"
echo "NOPASSWD:ALL, and that every AI execution channel runs as ${AI_USER} (not root)."
exit 0
