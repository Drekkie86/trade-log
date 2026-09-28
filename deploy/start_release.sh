#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: start_release.sh <archive> <receiver> <runner> <commit> <sha256> [--recovery-no-schema-change]" >&2
  exit 2
}

fail() {
  echo "DEPLOY LAUNCH FAILED: $*" >&2
  exit 1
}

if [[ "${EUID}" -ne 0 ]]; then
  fail "launcher must run as root"
fi

if [[ "$#" -lt 5 || "$#" -gt 6 ]]; then
  usage
fi

ARCHIVE="$1"
RECEIVER="$2"
RUNNER="$3"
EXPECTED_COMMIT="${4,,}"
EXPECTED_SHA256="${5,,}"
RECOVERY_ARG="${6:-}"

if [[ ! "${EXPECTED_COMMIT}" =~ ^[0-9a-f]{40}$ ]]; then
  fail "expected commit must be a full 40-character SHA"
fi
if [[ ! "${EXPECTED_SHA256}" =~ ^[0-9a-f]{64}$ ]]; then
  fail "expected archive SHA-256 must contain 64 hex characters"
fi
if [[ -n "${RECOVERY_ARG}" && "${RECOVERY_ARG}" != "--recovery-no-schema-change" ]]; then
  usage
fi

for required in systemd-run sha256sum install cp date awk; do
  command -v "${required}" >/dev/null 2>&1 || fail "required command missing: ${required}"
done

[[ -f "${ARCHIVE}" ]] || fail "archive missing: ${ARCHIVE}"
[[ -f "${RECEIVER}" ]] || fail "receiver missing: ${RECEIVER}"
[[ -f "${RUNNER}" ]] || fail "runner missing: ${RUNNER}"

actual_sha="$(sha256sum "${ARCHIVE}" | awk '{print tolower($1)}')"
[[ "${actual_sha}" == "${EXPECTED_SHA256}" ]] || fail "archive SHA-256 mismatch"

STATE_ROOT="/var/lib/christiania/deployments"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
ACTIVATION_ID="$(date -u +%Y%m%dT%H%M%SZ)-${EXPECTED_COMMIT:0:12}"
DEPLOY_DIR="${STATE_ROOT}/${ACTIVATION_ID}"
STATUS_FILE="${DEPLOY_DIR}/status.env"
UNIT="christiania-deploy-${ACTIVATION_ID}.service"

install -d -m 0750 -o root -g christiania "${STATE_ROOT}"
install -d -m 0750 -o root -g christiania "${DEPLOY_DIR}"
cp -f "${ARCHIVE}" "${DEPLOY_DIR}/release.tar.gz"
cp -f "${RECEIVER}" "${DEPLOY_DIR}/receive_release.sh"
cp -f "${RUNNER}" "${DEPLOY_DIR}/run_server_release.sh"
chmod 0640 "${DEPLOY_DIR}/release.tar.gz"
chmod 0750 "${DEPLOY_DIR}/receive_release.sh" "${DEPLOY_DIR}/run_server_release.sh"

umask 027
cat > "${STATUS_FILE}" <<EOF
state=QUEUED
phase=LAUNCH
target_commit=${EXPECTED_COMMIT}
activation_id=${ACTIVATION_ID}
unit=${UNIT}
started_at=${STARTED_AT}
updated_at=${STARTED_AT}
finished_at=
detail=Accepted by server launcher; transient systemd deployment unit is starting.
EOF
chmod 0640 "${STATUS_FILE}"

RUN_ARGS=(
  "${STATUS_FILE}"
  "${DEPLOY_DIR}/receive_release.sh"
  "${DEPLOY_DIR}/release.tar.gz"
  "${EXPECTED_COMMIT}"
  "${EXPECTED_SHA256}"
)
if [[ -n "${RECOVERY_ARG}" ]]; then
  RUN_ARGS+=("${RECOVERY_ARG}")
fi

systemd-run \
  --unit="${UNIT}" \
  --description="Christiania release ${EXPECTED_COMMIT}" \
  --property=Type=exec \
  --property=Restart=no \
  --property=KillMode=mixed \
  --property=TimeoutStopSec=infinity \
  --setenv="CHRISTIANIA_DEPLOY_ACTIVATION_ID=${ACTIVATION_ID}" \
  --setenv="CHRISTIANIA_DEPLOY_UNIT=${UNIT}" \
  --setenv="CHRISTIANIA_DEPLOY_STARTED_AT=${STARTED_AT}" \
  --no-block \
  /bin/bash "${DEPLOY_DIR}/run_server_release.sh" "${RUN_ARGS[@]}"

echo "activation_id=${ACTIVATION_ID}"
echo "unit=${UNIT}"
echo "status_path=${STATUS_FILE}"
echo "journal_command=journalctl -u ${UNIT} -f"
