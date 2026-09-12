#!/usr/bin/env bash
set -euo pipefail

APP_LINK="/opt/christiania"
RELEASE_ROOT="/opt/christiania-releases"
STATE_ROOT="/var/lib/christiania"
ENV_FILE="/etc/christiania/christiania.env"
SYSTEMD_ROOT="/etc/systemd/system"
LOCAL_BIN="/usr/local/bin"
SERVICE_USER="christiania"

CORE_SERVICES=(
  "christiania-theta.service"
  "christiania-daemon.service"
  "christiania-app.service"
)

usage() {
  echo "Usage: sudo bash receive_release.sh <archive.tar.gz> <40-char-commit> <sha256>" >&2
  exit 2
}

fail() {
  echo "RELEASE FAILED: $*" >&2
  exit 1
}

if [[ "${EUID}" -ne 0 ]]; then
  fail "receiver must run as root"
fi

if [[ "$#" -ne 3 ]]; then
  usage
fi

ARCHIVE="$1"
EXPECTED_COMMIT="${2,,}"
EXPECTED_SHA256="${3,,}"

if [[ ! -f "${ARCHIVE}" ]]; then
  fail "release archive does not exist: ${ARCHIVE}"
fi

if [[ ! "${EXPECTED_COMMIT}" =~ ^[0-9a-f]{40}$ ]]; then
  fail "expected commit must be a full 40-character hexadecimal Git SHA"
fi

if [[ ! "${EXPECTED_SHA256}" =~ ^[0-9a-f]{64}$ ]]; then
  fail "expected archive SHA-256 must be 64 hexadecimal characters"
fi

for required in \
  sha256sum \
  tar \
  python3 \
  systemctl \
  install \
  readlink \
  find \
  cp \
  mv \
  ln \
  sudo; do
  if ! command -v "${required}" >/dev/null 2>&1; then
    fail "required command not found: ${required}"
  fi
done

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  fail "service account does not exist: ${SERVICE_USER}"
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  fail "runtime environment file does not exist: ${ENV_FILE}"
fi

ACTUAL_SHA256="$(
  sha256sum "${ARCHIVE}" | awk '{print tolower($1)}'
)"

if [[ "${ACTUAL_SHA256}" != "${EXPECTED_SHA256}" ]]; then
  fail "archive SHA-256 mismatch"
fi

while IFS= read -r member; do
  if [[ -z "${member}" ]]; then
    continue
  fi

  if [[ "${member}" == /* ]]; then
    fail "archive contains an absolute path: ${member}"
  fi

  if [[ "${member}" =~ (^|/)\.\.(/|$) ]]; then
    fail "archive contains path traversal: ${member}"
  fi
done < <(tar -tzf "${ARCHIVE}")

install -d -m 0750 -o root -g "${SERVICE_USER}" "${RELEASE_ROOT}"

RELEASE_DIR="${RELEASE_ROOT}/${EXPECTED_COMMIT}"

if [[ -e "${RELEASE_DIR}" ]]; then
  fail "release directory already exists: ${RELEASE_DIR}"
fi

ROLLBACK_ROOT="${STATE_ROOT}/release-rollbacks"
install -d -m 0750 -o root -g "${SERVICE_USER}" "${ROLLBACK_ROOT}"

ACTIVATION_ID="$(date -u +%Y%m%dT%H%M%SZ)"
UNIT_BACKUP="${ROLLBACK_ROOT}/${ACTIVATION_ID}-systemd"
STATUS_BACKUP="${ROLLBACK_ROOT}/${ACTIVATION_ID}-christiania-status"

install -d -m 0700 -o root -g root "${UNIT_BACKUP}"

PREVIOUS_TARGET=""
LEGACY_MOVED=0
ACTIVATED=0
UNITS_BACKED_UP=0
STATUS_WRAPPER_HAD_PREVIOUS=0

rollback() {
  local original_exit="$1"

  if [[ "${ACTIVATED}" -eq 1 ]]; then
    echo "Activation failed; restoring previous Christiania release." >&2

    for service in "${CORE_SERVICES[@]}"; do
      systemctl stop "${service}" >/dev/null 2>&1 || true
    done

    rm -f "${APP_LINK}"

    if [[ -n "${PREVIOUS_TARGET}" ]]; then
      ln -s "${PREVIOUS_TARGET}" "${APP_LINK}"
    fi

    if [[ "${UNITS_BACKED_UP}" -eq 1 ]]; then
      find "${SYSTEMD_ROOT}" \
        -maxdepth 1 \
        \( -name 'christiania-*.service' -o -name 'christiania-*.timer' \) \
        -delete

      find "${SYSTEMD_ROOT}" \
        -maxdepth 1 \
        -type d \
        -name 'christiania-*.service.d' \
        -exec rm -rf {} +

      if compgen -G "${UNIT_BACKUP}/christiania-*" >/dev/null; then
        cp -a "${UNIT_BACKUP}"/christiania-* "${SYSTEMD_ROOT}/"
      fi
    fi

    if [[ "${STATUS_WRAPPER_HAD_PREVIOUS}" -eq 1 ]]; then
      cp -a "${STATUS_BACKUP}" "${LOCAL_BIN}/christiania-status"
    else
      rm -f "${LOCAL_BIN}/christiania-status"
    fi

    systemctl daemon-reload || true

    for service in "${CORE_SERVICES[@]}"; do
      systemctl start "${service}" >/dev/null 2>&1 || true
    done
  fi

  exit "${original_exit}"
}

trap 'rollback $?' ERR INT TERM

echo "Preparing Christiania release ${EXPECTED_COMMIT}."

install -d -m 0750 -o root -g "${SERVICE_USER}" "${RELEASE_DIR}"

tar -xzf "${ARCHIVE}" -C "${RELEASE_DIR}"

printf '%s\n' "${EXPECTED_COMMIT}" > "${RELEASE_DIR}/DEPLOYED_COMMIT"

if [[ -d "${APP_LINK}/vendor" ]]; then
  cp -a "${APP_LINK}/vendor" "${RELEASE_DIR}/vendor"
else
  install -d -m 0750 -o root -g "${SERVICE_USER}" "${RELEASE_DIR}/vendor"
fi

python3 -m venv "${RELEASE_DIR}/.venv"
"${RELEASE_DIR}/.venv/bin/pip" install --upgrade pip
"${RELEASE_DIR}/.venv/bin/pip" install -r "${RELEASE_DIR}/requirements.txt"

chown -R root:"${SERVICE_USER}" "${RELEASE_DIR}"
chmod -R g+rX,o-rwx "${RELEASE_DIR}"

echo "Running release preflight before activation."

sudo -u "${SERVICE_USER}" \
  "${RELEASE_DIR}/.venv/bin/python" \
  "${RELEASE_DIR}/christiania_deploy_preflight.py" \
  --env-file "${ENV_FILE}" \
  --require-theta-live

TEMP_SYSTEMD_ROOT="$(mktemp -d)"

"${RELEASE_DIR}/.venv/bin/python" \
  "${RELEASE_DIR}/christiania_resource_policy.py" \
  render \
  --systemd-root "${TEMP_SYSTEMD_ROOT}"

echo "Preflight passed. Preparing atomic activation."

if [[ -L "${APP_LINK}" ]]; then
  PREVIOUS_TARGET="$(readlink -f "${APP_LINK}")"
elif [[ -d "${APP_LINK}" ]]; then
  LEGACY_TARGET="${RELEASE_ROOT}/legacy-${ACTIVATION_ID}"
  mv "${APP_LINK}" "${LEGACY_TARGET}"
  PREVIOUS_TARGET="${LEGACY_TARGET}"
  LEGACY_MOVED=1
else
  fail "current application path is neither a directory nor a symlink: ${APP_LINK}"
fi

for existing in \
  "${SYSTEMD_ROOT}"/christiania-*.service \
  "${SYSTEMD_ROOT}"/christiania-*.timer \
  "${SYSTEMD_ROOT}"/christiania-*.service.d; do
  if [[ -e "${existing}" ]]; then
    cp -a "${existing}" "${UNIT_BACKUP}/"
  fi
done

UNITS_BACKED_UP=1

if [[ -e "${LOCAL_BIN}/christiania-status" ]]; then
  cp -a "${LOCAL_BIN}/christiania-status" "${STATUS_BACKUP}"
  STATUS_WRAPPER_HAD_PREVIOUS=1
fi

for service in "${CORE_SERVICES[@]}"; do
  systemctl stop "${service}"
done

if [[ -L "${APP_LINK}" ]]; then
  rm "${APP_LINK}"
fi

ln -s "${RELEASE_DIR}" "${APP_LINK}"
ACTIVATED=1

for unit in \
  "${RELEASE_DIR}"/deploy/systemd/christiania-*.service \
  "${RELEASE_DIR}"/deploy/systemd/christiania-*.timer; do
  install -m 0644 "${unit}" "${SYSTEMD_ROOT}/$(basename "${unit}")"
done

for dropin_dir in "${TEMP_SYSTEMD_ROOT}"/christiania-*.service.d; do
  if [[ -d "${dropin_dir}" ]]; then
    destination="${SYSTEMD_ROOT}/$(basename "${dropin_dir}")"
    rm -rf "${destination}"
    cp -a "${dropin_dir}" "${destination}"
  fi
done

rm -rf "${TEMP_SYSTEMD_ROOT}"

systemctl daemon-reload

"${APP_LINK}/.venv/bin/python" \
  "${APP_LINK}/christiania_resource_policy.py" \
  check \
  --systemd-root "${SYSTEMD_ROOT}"

install -m 0755 \
  "${APP_LINK}/deploy/christiania-status" \
  "${LOCAL_BIN}/christiania-status"

systemctl start christiania-theta.service
systemctl start christiania-daemon.service
systemctl start christiania-app.service

for service in "${CORE_SERVICES[@]}"; do
  state="$(systemctl is-active "${service}")"
  if [[ "${state}" != "active" ]]; then
    fail "${service} did not become active after deployment"
  fi
done

echo "Running post-activation deployment preflight."

sudo -u "${SERVICE_USER}" \
  "${APP_LINK}/.venv/bin/python" \
  "${APP_LINK}/christiania_deploy_preflight.py" \
  --env-file "${ENV_FILE}" \
  --require-theta-live

INSTALLED_COMMIT="$(
  tr -d '[:space:]' < "${APP_LINK}/DEPLOYED_COMMIT"
)"

if [[ "${INSTALLED_COMMIT}" != "${EXPECTED_COMMIT}" ]]; then
  fail "installed DEPLOYED_COMMIT does not match requested release"
fi

echo "Refreshing authoritative supervisor evidence."

systemctl start christiania-supervisor.service

SUPERVISOR_STATE="$(
  systemctl is-failed christiania-supervisor.service || true
)"

if [[ "${SUPERVISOR_STATE}" == "failed" ]]; then
  fail "christiania-supervisor.service failed after deployment"
fi

echo "Running Christiania control-plane status."

"${LOCAL_BIN}/christiania-status" --json

ACTIVATED=0
trap - ERR INT TERM

echo
echo "CHRISTIANIA RELEASE ACTIVATED"
echo "commit=${EXPECTED_COMMIT}"
echo "archive_sha256=${EXPECTED_SHA256}"
echo "release=${RELEASE_DIR}"
echo "previous=${PREVIOUS_TARGET}"
echo "legacy_migration=${LEGACY_MOVED}"
echo "status_command=${LOCAL_BIN}/christiania-status"