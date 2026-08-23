#!/bin/sh
# Host installation for executable PM authority (RC-456).
#
# COMMITTING THIS SCRIPT DOES NOT CREATE THE BOUNDARY.
# The boundary exists only after a privileged host principal (not the assigned
# AI) runs this script and the HOST ACCEPTANCE PROOF in
# reports/pm_authority_external_implementation.md is measured.
#
# This script must be run as root by the operator/host provisioner.
# It will refuse to run if CONFIRM is not set, so an assigned AI cannot
# casually lock the host.

set -eu

CONFIRM_REQUIRED="ed-console-authority-host"
AUTHORITY_DIR="/var/lib/ed-console-authority"
AUTHORITY_FILE="${AUTHORITY_DIR}/pm_mission.json"
HELPER_INSTALL="/usr/local/sbin/ed_pm_authority_write"
SUDOERS_DROP="/etc/sudoers.d/ed-pm-authority"
AI_USER="${ED_AI_USER:-ubuntu}"

if [ "$(id -u)" -ne 0 ]; then
  echo "install_pm_authority_host.sh: must run as root (host provisioner)" >&2
  exit 1
fi
if [ "${CONFIRM:-}" != "${CONFIRM_REQUIRED}" ]; then
  echo "install_pm_authority_host.sh: set CONFIRM=${CONFIRM_REQUIRED} to proceed." >&2
  echo "This script is not the boundary until the operator runs it on the host." >&2
  exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
HELPER_SRC="${REPO_ROOT}/tools/pm_authority_helper.py"
TEMPLATE="${REPO_ROOT}/governance/pm_mission.json"

if [ ! -f "${HELPER_SRC}" ]; then
  echo "missing helper source ${HELPER_SRC}" >&2
  exit 1
fi

install -d -o root -g root -m 0755 "${AUTHORITY_DIR}"
# Directory: root rwx, AI user rx only — cannot write/delete/rename contents,
# cannot chmod/chown (not owner).
chmod 0755 "${AUTHORITY_DIR}"
chown root:root "${AUTHORITY_DIR}"

if [ ! -f "${AUTHORITY_FILE}" ]; then
  if [ -f "${TEMPLATE}" ]; then
    python3 - "${TEMPLATE}" "${AUTHORITY_FILE}" <<'PY'
import json, sys
src, dest = sys.argv[1], sys.argv[2]
doc = json.loads(open(src, encoding="utf-8").read())
if not isinstance(doc, dict) or doc.get("pm") != "operator":
    raise SystemExit("template is not a valid pm=operator document")
# Do not copy non-authoritative marker into the live authority file.
doc.pop("_authority", None)
doc.pop("_authority_note", None)
open(dest, "w", encoding="utf-8").write(json.dumps(doc, indent=2) + "\n")
PY
  else
    echo '{"pm": "operator", "status": "idle"}' > "${AUTHORITY_FILE}"
  fi
fi
chown root:root "${AUTHORITY_FILE}"
chmod 0644 "${AUTHORITY_FILE}"

install -o root -g root -m 0755 "${HELPER_SRC}" "${HELPER_INSTALL}"
# Helper parent /usr/local/sbin is expected root-owned; reaffirm helper bits.
chown root:root "${HELPER_INSTALL}"
chmod 0755 "${HELPER_INSTALL}"

# Narrow sudoers: AI user may run ONLY the installed helper as root.
# This file does not grant ALL. Removing general sudo is a separate host
# step the operator must confirm (see acceptance proof).
cat > "${SUDOERS_DROP}" <<EOF
# Ed Console PM authority — ONLY the installed helper. Not ALL.
${AI_USER} ALL=(root) NOPASSWD: ${HELPER_INSTALL}
EOF
chmod 0440 "${SUDOERS_DROP}"
visudo -cf "${SUDOERS_DROP}"

echo "installed ${AUTHORITY_FILE} and ${HELPER_INSTALL}"
echo "BOUNDARY IS NOT PROVEN until HOST ACCEPTANCE PROOF is measured."
echo "Remaining operator step: remove ${AI_USER} from general sudo/NOPASSWD:ALL"
echo "and ensure every AI execution channel runs as ${AI_USER}."
exit 0
