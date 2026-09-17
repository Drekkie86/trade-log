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

DB_TIMER_UNITS=(
  "christiania-audit.timer"
  "christiania-backup.timer"
  "christiania-burn-in.timer"
  "christiania-health.timer"
  "christiania-restore-drill.timer"
  "christiania-supervisor.timer"
  "christiania-v1-readiness.timer"
)

DB_ONESHOT_SERVICES=(
  "christiania-audit.service"
  "christiania-backup.service"
  "christiania-burn-in.service"
  "christiania-health.service"
  "christiania-restore-drill.service"
  "christiania-supervisor.service"
  "christiania-v1-readiness.service"
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
  awk \
  basename \
  cp \
  date \
  find \
  id \
  install \
  ln \
  mv \
  python3 \
  readlink \
  rm \
  sha256sum \
  sudo \
  systemctl \
  tar \
  tr; do
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

ACTUAL_SHA256="$(sha256sum "${ARCHIVE}" | awk '{print tolower($1)}')"
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

PREVIOUS_TARGET=""
LEGACY_SOURCE=0
if [[ -L "${APP_LINK}" ]]; then
  PREVIOUS_TARGET="$(readlink -f "${APP_LINK}" 2>/dev/null || true)"
  if [[ -z "${PREVIOUS_TARGET}" || ! -d "${PREVIOUS_TARGET}" ]]; then
    fail "current application symlink does not resolve to a release directory: ${APP_LINK}"
  fi
elif [[ -d "${APP_LINK}" ]]; then
  PREVIOUS_TARGET="${APP_LINK}"
  LEGACY_SOURCE=1
else
  fail "current application path is neither a directory nor a symlink: ${APP_LINK}"
fi

ROLLBACK_ROOT="${STATE_ROOT}/release-rollbacks"
FAILED_RELEASE_ROOT="${RELEASE_ROOT}/failed"
install -d -m 0750 -o root -g "${SERVICE_USER}" "${ROLLBACK_ROOT}"
install -d -m 0750 -o root -g "${SERVICE_USER}" "${FAILED_RELEASE_ROOT}"

ACTIVATION_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
RELEASE_DIR="${RELEASE_ROOT}/${EXPECTED_COMMIT}"
QUARANTINED_RELEASE=""
if [[ -e "${RELEASE_DIR}" || -L "${RELEASE_DIR}" ]]; then
  candidate_target="$(readlink -f "${RELEASE_DIR}" 2>/dev/null || true)"
  if [[ -n "${candidate_target}" && "${candidate_target}" == "${PREVIOUS_TARGET}" ]]; then
    fail "requested release is already the active release: ${RELEASE_DIR}"
  fi
  QUARANTINED_RELEASE="${FAILED_RELEASE_ROOT}/${EXPECTED_COMMIT}-${ACTIVATION_ID}"
  echo "Quarantining incomplete prior attempt for ${EXPECTED_COMMIT} at ${QUARANTINED_RELEASE}."
  mv -- "${RELEASE_DIR}" "${QUARANTINED_RELEASE}"
fi

UNIT_BACKUP="${ROLLBACK_ROOT}/${ACTIVATION_ID}-systemd"
STATUS_BACKUP="${ROLLBACK_ROOT}/${ACTIVATION_ID}-christiania-status"
DB_ROLLBACK_POINTER="${ROLLBACK_ROOT}/${ACTIVATION_ID}-database.txt"

install -d -m 0700 -o root -g root "${UNIT_BACKUP}"
install -m 0660 -o "${SERVICE_USER}" -g "${SERVICE_USER}" /dev/null "${DB_ROLLBACK_POINTER}"

LEGACY_MOVED=0
APP_LINK_MUTATED=0
ACTIVATED=0
UNITS_BACKED_UP=0
STATUS_WRAPPER_HAD_PREVIOUS=0
SECURE_EDGE_WAS_ACTIVE=0
SERVICES_QUIESCED=0
DATABASE_PREPARED=0
ROLLBACK_DB_VERSION=""
ROLLBACK_DB_BACKUP=""
TEMP_SYSTEMD_ROOT=""
ACTIVE_DB_TIMERS=()

rollback() {
  local original_exit="$1"
  local restart_failed=0
  trap - ERR INT TERM

  echo "Release failed; restoring previous Christiania release and database state." >&2

  if [[ "${SERVICES_QUIESCED}" -eq 1 || "${ACTIVATED}" -eq 1 ]]; then
    for timer in "${DB_TIMER_UNITS[@]}"; do
      systemctl stop "${timer}" >/dev/null 2>&1 || true
    done
    for service in "${DB_ONESHOT_SERVICES[@]}"; do
      systemctl stop "${service}" >/dev/null 2>&1 || true
    done
    for service in "${CORE_SERVICES[@]}"; do
      systemctl stop "${service}" >/dev/null 2>&1 || true
    done
  fi

  if [[ "${APP_LINK_MUTATED}" -eq 1 ]]; then
    rm -f "${APP_LINK}"
    if [[ -n "${PREVIOUS_TARGET}" ]]; then
      ln -s "${PREVIOUS_TARGET}" "${APP_LINK}"
    fi
  fi

  if [[ "${ACTIVATED}" -eq 1 ]]; then
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

    if [[ -n "${ROLLBACK_DB_BACKUP}" && -n "${ROLLBACK_DB_VERSION}" ]]; then
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
    else
      echo "Database preparation stopped before the rollback pointer was committed; no migration could have started." >&2
    fi
  fi

  if [[ -n "${TEMP_SYSTEMD_ROOT}" && -d "${TEMP_SYSTEMD_ROOT}" ]]; then
    rm -rf "${TEMP_SYSTEMD_ROOT}" || true
  fi

  systemctl daemon-reload || true

  if [[ "${SERVICES_QUIESCED}" -eq 1 || "${ACTIVATED}" -eq 1 ]]; then
    for service in "${CORE_SERVICES[@]}"; do
      systemctl start "${service}" >/dev/null 2>&1 || restart_failed=1
    done
    for service in "${CORE_SERVICES[@]}"; do
      if [[ "$(systemctl is-active "${service}" 2>/dev/null || true)" != "active" ]]; then
        echo "ROLLBACK WARNING: ${service} did not return to active state." >&2
        restart_failed=1
      fi
    done
  fi

  if [[ "${SECURE_EDGE_WAS_ACTIVE}" -eq 1 ]]; then
    systemctl start "${SECURE_EDGE_SERVICE}" >/dev/null 2>&1 || restart_failed=1
  fi

  for timer in "${ACTIVE_DB_TIMERS[@]}"; do
    systemctl start "${timer}" >/dev/null 2>&1 || restart_failed=1
  done

  if [[ "${restart_failed}" -ne 0 ]]; then
    echo "ROLLBACK WARNING: previous runtime did not fully recover; operator inspection required." >&2
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
echo "Note: the current-release SQLite integrity check can take several minutes on a large database; this is expected and must not be interrupted."

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
for timer in "${DB_TIMER_UNITS[@]}"; do
  if systemctl is-active --quiet "${timer}"; then
    ACTIVE_DB_TIMERS+=("${timer}")
  fi
  systemctl stop "${timer}" >/dev/null 2>&1 || true
done
for service in "${DB_ONESHOT_SERVICES[@]}"; do
  systemctl stop "${service}" >/dev/null 2>&1 || true
done
for service in "${QUIESCE_SERVICES[@]}"; do
  systemctl stop "${service}"
done
SERVICES_QUIESCED=1

echo "Creating verified rollback backup and applying pending release migrations."
# The helper commits the rollback pointer before any migration SQL can run.
# Until that pointer exists, an interruption is provably pre-mutation.
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
  APP_LINK_MUTATED=1
elif [[ -L "${APP_LINK}" ]]; then
  rm "${APP_LINK}"
  APP_LINK_MUTATED=1
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
TEMP_SYSTEMD_ROOT=""
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

INSTALLED_COMMIT="$(tr -d '[:space:]' < "${APP_LINK}/DEPLOYED_COMMIT")"
if [[ "${INSTALLED_COMMIT}" != "${EXPECTED_COMMIT}" ]]; then
  fail "installed DEPLOYED_COMMIT does not match requested release"
fi

echo "Refreshing authoritative supervisor evidence."
systemctl start christiania-supervisor.service
SUPERVISOR_STATE="$(systemctl is-failed christiania-supervisor.service || true)"
if [[ "${SUPERVISOR_STATE}" == "failed" ]]; then
  fail "christiania-supervisor.service failed after deployment"
fi

echo "Running Christiania control-plane status."
"${LOCAL_BIN}/christiania-status" --json

echo "Restoring database-observer timers."
for timer in "${ACTIVE_DB_TIMERS[@]}"; do
  systemctl start "${timer}"
done

APP_LINK_MUTATED=0
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
echo "quarantined_retry=${QUARANTINED_RELEASE}"
echo "database_rollback_backup=${ROLLBACK_DB_BACKUP}"
echo "status_command=${LOCAL_BIN}/christiania-status"
