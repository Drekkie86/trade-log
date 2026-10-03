#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: run_server_release.sh <status-file> <receiver> <archive> <commit> <sha256> [--recovery-no-schema-change]" >&2
  exit 2
}

if [[ "${EUID}" -ne 0 ]]; then
  echo "Server release runner must run as root." >&2
  exit 1
fi

if [[ "$#" -lt 5 || "$#" -gt 6 ]]; then
  usage
fi

STATUS_FILE="$1"
RECEIVER="$2"
ARCHIVE="$3"
EXPECTED_COMMIT="${4,,}"
EXPECTED_SHA256="${5,,}"
RECOVERY_ARG="${6:-}"
LOCK_FILE="/run/lock/christiania-deploy.lock"

if [[ ! "${EXPECTED_COMMIT}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Invalid deployment commit." >&2
  exit 2
fi
if [[ ! "${EXPECTED_SHA256}" =~ ^[0-9a-f]{64}$ ]]; then
  echo "Invalid deployment archive SHA-256." >&2
  exit 2
fi
if [[ -n "${RECOVERY_ARG}" && "${RECOVERY_ARG}" != "--recovery-no-schema-change" ]]; then
  usage
fi

status_write() {
  local state="$1"
  local phase="$2"
  local detail="$3"
  local finished_at="${4:-}"
  local tmp="${STATUS_FILE}.tmp.$$"

  umask 027
  {
    printf 'state=%s\n' "${state}"
    printf 'phase=%s\n' "${phase}"
    printf 'target_commit=%s\n' "${EXPECTED_COMMIT}"
    printf 'activation_id=%s\n' "${CHRISTIANIA_DEPLOY_ACTIVATION_ID:-unknown}"
    printf 'unit=%s\n' "${CHRISTIANIA_DEPLOY_UNIT:-unknown}"
    printf 'started_at=%s\n' "${CHRISTIANIA_DEPLOY_STARTED_AT:-unknown}"
    printf 'updated_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'finished_at=%s\n' "${finished_at}"
    printf 'detail=%s\n' "${detail//$'\n'/ }"
  } > "${tmp}"
  chmod 0640 "${tmp}"
  mv -f "${tmp}" "${STATUS_FILE}"
}

install -d -m 0750 -o root -g christiania "$(dirname "${STATUS_FILE}")"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  status_write "FAILED" "LOCK" "Another Christiania deployment owns ${LOCK_FILE}." "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "Another Christiania deployment is already running." >&2
  exit 75
fi

export CHRISTIANIA_DEPLOY_LOCK_HELD=1
export CHRISTIANIA_DEPLOY_STATUS_FILE="${STATUS_FILE}"

status_write "RUNNING" "STARTING" "Server-owned deployment started."

set +e
if [[ -n "${RECOVERY_ARG}" ]]; then
  bash "${RECEIVER}" "${ARCHIVE}" "${EXPECTED_COMMIT}" "${EXPECTED_SHA256}" "${RECOVERY_ARG}"
  rc=$?
else
  bash "${RECEIVER}" "${ARCHIVE}" "${EXPECTED_COMMIT}" "${EXPECTED_SHA256}"
  rc=$?
fi
set -e

if [[ "${rc}" -eq 0 ]]; then
  status_write "SUCCEEDED" "COMPLETE" "Release activation completed successfully." "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
else
  status_write "FAILED" "COMPLETE" "Release receiver exited with code ${rc}; inspect the unit journal and rollback status." "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi

exit "${rc}"
