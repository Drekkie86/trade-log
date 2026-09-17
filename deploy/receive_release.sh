#!/usr/bin/env bash
set -euo pipefail

APP_LINK="/opt/christiania"
RELEASE_ROOT="/opt/christiania-releases"
STATE_ROOT="/var/lib/christiania"
ENV_FILE="/etc/christiania/christiania.env"
SYSTEMD_ROOT="/etc/systemd/system"
LOCAL_BIN="/usr/local/bin"
SERVICE_USER="christiania"
SECURE_EDGE_SERVICE="christiania-oauth2-proxy.service"

CORE_SERVICES=(
  "christiania-theta.service"
  "christiania-daemon.service"
  "christiania-app.service"
)

QUIESCE_SERVICES=(
  "christiania-daemon.service"
  "christiania-app.service"
)

usage() {
  echo "Usage: sudo bash receive_release.sh <archive.tar.gz> <40-char-commit> <sha256>" >&2
  exit 2
}

fail() {
  echo "RELEASE FAILED: $*" >&2
  return 1
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
DB_ROLLBACK_POINTER="${ROLLBACK_ROOT}/${ACTIVATION_ID}-database.txt"

install -d -m 0700 -o root -g root "${UNIT_BACKUP}"
install -m 0660 -o "${SERVICE_USER}" -g "${SERVICE_USER}" /dev/null "${DB_ROLLBACK_POINTER}"

PREVIOUS_TARGET=""
LEGACY_SOURCE=0
LEGACY_MOVED=0
ACTIVATED=0
UNITS_BACKED_UP=0
STATUS_WRAPPER_HAD_PREVIOUS=0
SECURE_EDGE_WAS_ACTIVE=0
SERVICES_QUIESCED=0
DATABASE_PREPARED=0
ROLLBACK_DB_VERSION=""
ROLLBACK_DB_BACKUP=""

if [[ -L "${APP_LINK}" ]]; then
  PREVIOUS_TARGET="$(readlink -f "${APP_LINK}")"
elif [[ -d "${APP_LINK}" ]]; then
  PREVIOUS_TARGET="${APP_LINK}"
  LEGACY_SOURCE=1
else
  fail "current application path is neither a directory nor a symlink: ${APP_LINK}"
fi

rollback() {
  local original_exit="$1"
  trap - ERR INT TERM

  echo "Release failed; restoring previous Christiania release and database state." >&2

  if [[ "${SERVICES_QUIESCED}" -eq 1 || "${ACTIVATED}" -eq 1 ]]; then
    for service in "${CORE_SERVICES[@]}"; do
      systemctl stop "${service}" >/dev/null 2>&1 || true
    done
  fi

  if [[ "${ACTIVATED}" -eq 1 ]]; then
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
  fi

  if [[ "${DATABASE_PREPARED}" -eq 1 ]]; then
    if [[ -z "${ROLLBACK_DB_BACKUP}" || -z "${ROLLBACK_DB_VERSION}" ]]; then
      if [[ -s "${DB_ROLLBACK_POINTER}" ]]; then
        IFS=$'\t' read -r ROLLBACK_DB_VERSION ROLLBACK_DB_BACKUP < "${DB_ROLLBACK_POINTER}"
      fi
    fi

    if [[ -z "${ROLLBACK_DB_BACKUP}" || -z "${ROLLBACK_DB_VERSION}" ]]; then
      echo "DATABASE ROLLBACK METADATA MISSING; core services remain stopped." >&2
      exit "${original_exit}"
    fi

    echo "Restoring pre-release database schema v${ROLLBACK_DB_VERSION}." >&2
    if ! sudo -u "${SERVICE_USER}" \
      "${RELEASE_DIR}/.venv/bin/python" \
      "${RELEASE_DIR}/christiania_release_database.py" \
      --env-file "${ENV_FILE}" \
      restore \
      --backup "${ROLLBACK_DB_BACKUP}" \
      --expected-version "${ROLLBACK_DB_VERSION}"; then
      echo "DATABASE ROLLBACK FAILED; core services remain stopped." >&2
      exit "${original_exit}"
    fi
  fi

  systemctl daemon-reload || true

  if [[ "${SERVICES_QUIESCED}" -eq 1 || "${ACTIVATED}" -eq 1 ]]; then
    for service in "${CORE_SERVICES[@]}"; do
      systemctl start "${service}" >/dev/null 2>&1 || true
    done
  fi

  if [[ "${SECURE_EDGE_WAS_ACTIVE}" -eq 1 ]]; then
    systemctl start "${SECURE_EDGE_SERVICE}" >/dev/null 2>&1 || true
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
echo "Validating current release health before database preparation."

sudo -u "${SERVICE_USER}" \
  "${PREVIOUS_TARGET}/.venv/bin/python" \
  "${PREVIOUS_TARGET}/christiania_deploy_preflight.py" \
  --env-file "${ENV_FILE}" \
  --require-theta-live

TEMP_SYSTEMD_ROOT="$(mktemp -d)"

"${RELEASE_DIR}/.venv/bin/python" \
  "${RELEASE_DIR}/christiania_resource_policy.py" \
  render \
  --systemd-root "${TEMP_SYSTEMD_ROOT}"

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

if systemctl is-active --quiet "${SECURE_EDGE_SERVICE}"; then
  SECURE_EDGE_WAS_ACTIVE=1
fi

echo "Quiescing Christiania database consumers for release migration."
for service in "${QUIESCE_SERVICES[@]}"; do
  systemctl stop "${service}"
done
SERVICES_QUIESCED=1

echo "Creating verified rollback backup and applying pending release migrations."
# From this point onward rollback must assume database mutation may have begun.
DATABASE_PREPARED=1
DB_PREP_OUTPUT="$(
  sudo -u "${SERVICE_USER}" \
    "${RELEASE_DIR}/.venv/bin/python" \
    "${RELEASE_DIR}/christiania_release_database.py" \
    --env-file "${ENV_FILE}" \
    prepare \
    --migrations-dir "${RELEASE_DIR}/migrations" \
    --rollback-pointer "${DB_ROLLBACK_POINTER}" \
    --json
)"

IFS=$'\t' read -r ROLLBACK_DB_VERSION ROLLBACK_DB_BACKUP < "${DB_ROLLBACK_POINTER}"
if [[ -z "${ROLLBACK_DB_VERSION}" || -z "${ROLLBACK_DB_BACKUP}" ]]; then
  fail "release database preparation did not record rollback metadata"
fi
printf '%s\n' "${DB_PREP_OUTPUT}"

echo "Running target-release preflight against the migrated database."
sudo -u "${SERVICE_USER}" \
  "${RELEASE_DIR}/.venv/bin/python" \
  "${RELEASE_DIR}/christiania_deploy_preflight.py" \
  --env-file "${ENV_FILE}" \
  --require-theta-live

echo "Target preflight passed. Preparing atomic activation."
systemctl stop christiania-theta.service

if [[ "${LEGACY_SOURCE}" -eq 1 ]]; then
  LEGACY_TARGET="${RELEASE_ROOT}/legacy-${ACTIVATION_ID}"
  mv "${APP_LINK}" "${LEGACY_TARGET}"
  PREVIOUS_TARGET="${LEGACY_TARGET}"
  LEGACY_MOVED=1
elif [[ -L "${APP_LINK}" ]]; then
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

if [[ "${SECURE_EDGE_WAS_ACTIVE}" -eq 1 ]]; then
  echo "Restoring secure edge after application restart."
  systemctl start "${SECURE_EDGE_SERVICE}"
  edge_state="$(systemctl is-active "${SECURE_EDGE_SERVICE}")"
  if [[ "${edge_state}" != "active" ]]; then
    fail "${SECURE_EDGE_SERVICE} did not become active after deployment"
  fi
fi

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
SERVICES_QUIESCED=0
DATABASE_PREPARED=0
trap - ERR INT TERM

echo
echo "CHRISTIANIA RELEASE ACTIVATED"
echo "commit=${EXPECTED_COMMIT}"
echo "archive_sha256=${EXPECTED_SHA256}"
echo "release=${RELEASE_DIR}"
echo "previous=${PREVIOUS_TARGET}"
echo "legacy_migration=${LEGACY_MOVED}"
echo "database_rollback_backup=${ROLLBACK_DB_BACKUP}"
echo "status_command=${LOCAL_BIN}/christiania-status"