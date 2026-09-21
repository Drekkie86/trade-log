#!/usr/bin/env bash
set -euo pipefail

APP_LINK="/opt/christiania"
RELEASE_ROOT="/opt/christiania-releases"
STATE_ROOT="/var/lib/christiania"
ENV_FILE="/etc/christiania/christiania.env"
EDGE_ENV="/etc/christiania/secure-edge.env"
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

QUIESCE_TIMER_UNITS=(
  "christiania-audit.timer"
  "christiania-backup.timer"
  "christiania-backup-compress.timer"
  "christiania-burn-in.timer"
  "christiania-health.timer"
  "christiania-restore-drill.timer"
  "christiania-supervisor.timer"
  "christiania-theta-refresh.timer"
  "christiania-theta-watchdog.timer"
  "christiania-v1-readiness.timer"
)

QUIESCE_ONESHOT_SERVICES=(
  "christiania-audit.service"
  "christiania-backup.service"
  "christiania-backup-compress.service"
  "christiania-burn-in.service"
  "christiania-health.service"
  "christiania-restore-drill.service"
  "christiania-supervisor.service"
  "christiania-theta-refresh.service"
  "christiania-theta-watchdog.service"
  "christiania-theta-recover.service"
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

PHASE_STARTED_AT=0
PHASE_NAME=""

phase_start() {
  PHASE_NAME="$1"
  PHASE_STARTED_AT="$(date +%s)"
  echo
  echo "==> ${PHASE_NAME}"
}

phase_done() {
  local finished_at
  local elapsed
  finished_at="$(date +%s)"
  elapsed=$((finished_at - PHASE_STARTED_AT))
  echo "<== ${PHASE_NAME} completed in ${elapsed}s"
  PHASE_NAME=""
  PHASE_STARTED_AT=0
}

validate_current_database_metadata() {
  (
    cd "${PREVIOUS_TARGET}"
    sudo -u "${SERVICE_USER}" \
      "${PREVIOUS_TARGET}/.venv/bin/python" \
      - "${ENV_FILE}" <<'PY'
import sys

from src.config import load_runtime_env_file
from src.database.repository import EXPECTED_SCHEMA_VERSION
from src.operations.sqlite_runtime import inspect_database

if not load_runtime_env_file(sys.argv[1], overwrite=False):
    raise SystemExit(f"Environment file missing or empty: {sys.argv[1]}")

health = inspect_database(deep_integrity=False)
if not health.exists:
    raise SystemExit("Current Christiania database is missing.")
if health.schema_version != EXPECTED_SCHEMA_VERSION:
    raise SystemExit(
        f"Current database schema v{health.schema_version} does not match "
        f"active release schema v{EXPECTED_SCHEMA_VERSION}."
    )
if health.journal_mode != "wal":
    raise SystemExit(
        f"Current database is not in WAL mode: {health.journal_mode}."
    )

print(
    f"Current DB metadata: schema v{health.schema_version}; WAL; "
    "deep integrity is required only when a release migration mutates the database."
)
PY
  )
}

stop_unit_for_release() {
  local unit="$1"
  local state=""

  systemctl stop "${unit}"
  state="$(systemctl show --property=ActiveState --value "${unit}" 2>/dev/null || true)"
  case "${state}" in
    active|activating|reloading|deactivating)
      fail "${unit} did not become inactive during release quiescence"
      ;;
  esac
}

wait_for_http_2xx() {
  local label="$1"
  local url="$2"
  local attempts="${3:-45}"
  local code=""
  local attempt

  for attempt in $(seq 1 "${attempts}"); do
    code="$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "${url}" 2>/dev/null || true)"
    if [[ "${code}" =~ ^2[0-9][0-9]$ ]]; then
      echo "${label}: HTTP ${code}"
      return 0
    fi
    sleep 1
  done

  fail "${label} did not become healthy at ${url}; last HTTP status=${code:-000}"
}

read_public_host() {
  (
    cd "${APP_LINK}"
    sudo -u "${SERVICE_USER}" \
      "${APP_LINK}/.venv/bin/python" \
      - "${EDGE_ENV}" <<'PY'
import sys
from src.config import read_env_file

values = read_env_file(sys.argv[1])
host = str(values.get("CHRISTIANIA_PUBLIC_HOST") or "").strip().lower()
if not host or "://" in host or "/" in host or "@" in host:
    raise SystemExit("CHRISTIANIA_PUBLIC_HOST is missing or invalid.")
print(host)
PY
  )
}

verify_public_edge() {
  local host="$1"
  local code=""
  code="$(
    curl -sS \
      --max-time 10 \
      --resolve "${host}:443:127.0.0.1" \
      -o /dev/null \
      -w '%{http_code}' \
      "https://${host}/" \
      2>/dev/null || true
  )"
  if [[ ! "${code}" =~ ^[23][0-9][0-9]$ ]]; then
    fail "public Christiania edge is unhealthy for https://${host}/; HTTP ${code:-000}"
  fi
  echo "Public Christiania edge: HTTP ${code}"
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
  chmod \
  chown \
  cp \
  curl \
  date \
  find \
  id \
  install \
  ln \
  mktemp \
  mv \
  python3 \
  readlink \
  rm \
  seq \
  sha256sum \
  sleep \
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
DB_ROLLBACK_DIR="${ROLLBACK_ROOT}/${ACTIVATION_ID}-database"
DB_ROLLBACK_POINTER="${DB_ROLLBACK_DIR}/rollback.txt"

install -d -m 0700 -o root -g root "${UNIT_BACKUP}"
# The release DB helper runs as the service account and atomically replaces a
# sibling temp file into the pointer path. Give it a dedicated per-activation
# directory rather than making the shared rollback root service-writable.
install -d -m 0700 -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${DB_ROLLBACK_DIR}"
install -m 0600 -o "${SERVICE_USER}" -g "${SERVICE_USER}" /dev/null "${DB_ROLLBACK_POINTER}"

LEGACY_MOVED=0
APP_LINK_MUTATED=0
ACTIVATED=0
UNITS_BACKED_UP=0
STATUS_WRAPPER_HAD_PREVIOUS=0
SECURE_EDGE_WAS_ACTIVE=0
SECURE_EDGE_EXPECTED=0
SERVICES_QUIESCED=0
DATABASE_PREPARED=0
ROLLBACK_DB_VERSION=""
ROLLBACK_DB_BACKUP=""
TEMP_SYSTEMD_ROOT=""
ACTIVE_QUIESCE_TIMERS=()

rollback() {
  local original_exit="$1"
  local restart_failed=0
  trap - ERR INT TERM HUP

  echo "Release failed; restoring previous Christiania release and database state." >&2

  if [[ "${SERVICES_QUIESCED}" -eq 1 || "${ACTIVATED}" -eq 1 ]]; then
    for timer in "${QUIESCE_TIMER_UNITS[@]}"; do
      systemctl stop "${timer}" >/dev/null 2>&1 || true
    done
    for service in "${QUIESCE_ONESHOT_SERVICES[@]}"; do
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

  for timer in "${ACTIVE_QUIESCE_TIMERS[@]}"; do
    systemctl start "${timer}" >/dev/null 2>&1 || restart_failed=1
  done

  if [[ "${restart_failed}" -ne 0 ]]; then
    echo "ROLLBACK WARNING: previous runtime did not fully recover; operator inspection required." >&2
  fi

  exit "${original_exit}"
}

trap 'rollback $?' ERR INT TERM HUP

echo "Preparing Christiania release ${EXPECTED_COMMIT}."

install -d -m 0750 -o root -g "${SERVICE_USER}" "${RELEASE_DIR}"
tar -xzf "${ARCHIVE}" -C "${RELEASE_DIR}"
printf '%s\n' "${EXPECTED_COMMIT}" > "${RELEASE_DIR}/DEPLOYED_COMMIT"

if [[ -d "${APP_LINK}/vendor" ]]; then
  cp -a "${APP_LINK}/vendor" "${RELEASE_DIR}/vendor"
else
  install -d -m 0750 -o root -g "${SERVICE_USER}" "${RELEASE_DIR}/vendor"
fi

phase_start "Building isolated target runtime"
python3 -m venv "${RELEASE_DIR}/.venv"
"${RELEASE_DIR}/.venv/bin/pip" install --upgrade pip
"${RELEASE_DIR}/.venv/bin/pip" install -r "${RELEASE_DIR}/requirements.txt"
phase_done

chown -R root:"${SERVICE_USER}" "${RELEASE_DIR}"
chmod -R g+rX,o-rwx "${RELEASE_DIR}"

phase_start "Validating current production deployment safety"
sudo -u "${SERVICE_USER}" \
  "${RELEASE_DIR}/.venv/bin/python" \
  "${RELEASE_DIR}/christiania_status.py" \
  --json \
  --deployment-safe
phase_done

phase_start "Validating current database schema/WAL metadata"
validate_current_database_metadata
phase_done

echo "Deep database integrity is not repeated here. If the target release requires a schema migration, the release database safety step fully verifies a fresh rollback copy before migration SQL and then fully verifies the migrated database. If schema is unchanged, both O(database-size) scans are skipped."

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
if systemctl is-active --quiet "${SECURE_EDGE_SERVICE}" \
  || systemctl is-enabled --quiet "${SECURE_EDGE_SERVICE}" 2>/dev/null; then
  SECURE_EDGE_EXPECTED=1
fi

phase_start "Quiescing scheduled jobs and database consumers"
SERVICES_QUIESCED=1
for timer in "${QUIESCE_TIMER_UNITS[@]}"; do
  if systemctl is-active --quiet "${timer}"; then
    ACTIVE_QUIESCE_TIMERS+=("${timer}")
  fi
  stop_unit_for_release "${timer}"
done
for service in "${QUIESCE_ONESHOT_SERVICES[@]}"; do
  stop_unit_for_release "${service}"
done
for service in "${QUIESCE_SERVICES[@]}"; do
  stop_unit_for_release "${service}"
done

if [[ "$(systemctl is-active christiania-theta.service 2>/dev/null || true)" != "active" ]]; then
  fail "christiania-theta.service is not active after background-job quiescence"
fi
phase_done

phase_start "Preparing release database"
# The helper uses a zero-copy metadata-only fast path when the current schema
# already matches the target. When a migration is required it commits the
# rollback pointer before any migration SQL can run.
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
phase_done

DB_MIGRATED="$(
  printf '%s' "${DB_PREP_OUTPUT}" \
    | "${RELEASE_DIR}/.venv/bin/python" -c \
      'import json,sys; print("1" if json.load(sys.stdin)["migrated"] else "0")'
)"

if [[ "${DB_MIGRATED}" -eq 1 ]]; then
  IFS=$'\t' read -r ROLLBACK_DB_VERSION ROLLBACK_DB_BACKUP < "${DB_ROLLBACK_POINTER}"
  if [[ -z "${ROLLBACK_DB_VERSION}" || -z "${ROLLBACK_DB_BACKUP}" ]]; then
    fail "release database migration did not record rollback metadata"
  fi
else
  DATABASE_PREPARED=0
  echo "No schema migration required; rollback DB snapshot and deep DB scans were skipped."
fi

# The helper no longer needs to mutate the pointer once preparation returns.
# Harden its dedicated directory before any target-release checks run.
chown -R root:root "${DB_ROLLBACK_DIR}"
chmod 0700 "${DB_ROLLBACK_DIR}"
chmod 0600 "${DB_ROLLBACK_POINTER}"
printf '%s\n' "${DB_PREP_OUTPUT}"

phase_start "Validating target release prerequisites"
sudo -u "${SERVICE_USER}" \
  "${RELEASE_DIR}/.venv/bin/python" \
  "${RELEASE_DIR}/christiania_deploy_preflight.py" \
  --env-file "${ENV_FILE}" \
  --require-theta-live \
  --metadata-db-check
phase_done

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

phase_start "Verifying live application and secure edge"
wait_for_http_2xx "Christiania Streamlit app" "http://127.0.0.1:8501/_stcore/health" 45

if [[ "${SECURE_EDGE_EXPECTED}" -eq 1 ]]; then
  if ! command -v caddy >/dev/null 2>&1; then
    fail "secure edge is expected but caddy is unavailable"
  fi
  if [[ ! -f "${EDGE_ENV}" ]]; then
    fail "secure edge is expected but ${EDGE_ENV} is missing"
  fi

  echo "Restarting OAuth edge after application activation."
  systemctl restart "${SECURE_EDGE_SERVICE}"
  wait_for_http_2xx "Christiania OAuth proxy" "http://127.0.0.1:4180/ping" 30

  caddy validate --config /etc/caddy/Caddyfile
  if [[ "$(systemctl is-active caddy.service 2>/dev/null || true)" != "active" ]]; then
    fail "caddy.service is not active after deployment"
  fi

  PUBLIC_HOST="$(read_public_host)"
  verify_public_edge "${PUBLIC_HOST}"
fi
phase_done

phase_start "Running post-activation readiness checks"
sudo -u "${SERVICE_USER}" \
  "${APP_LINK}/.venv/bin/python" \
  "${APP_LINK}/christiania_deploy_preflight.py" \
  --env-file "${ENV_FILE}" \
  --require-theta-live \
  --metadata-db-check
phase_done

INSTALLED_COMMIT="$(tr -d '[:space:]' < "${APP_LINK}/DEPLOYED_COMMIT")"
if [[ "${INSTALLED_COMMIT}" != "${EXPECTED_COMMIT}" ]]; then
  fail "installed DEPLOYED_COMMIT does not match requested release"
fi

echo "Refreshing authoritative supervisor evidence."
systemctl start christiania-supervisor.service || true

echo "Running deployment-safety control-plane status."
"${LOCAL_BIN}/christiania-status" --json --deployment-safe

echo "Operational status (informational after deployment safety has passed)."
"${LOCAL_BIN}/christiania-status" --json || true

echo "Restoring scheduled Christiania timers."
for timer in "${ACTIVE_QUIESCE_TIMERS[@]}"; do
  systemctl start "${timer}"
done

APP_LINK_MUTATED=0
ACTIVATED=0
SERVICES_QUIESCED=0
DATABASE_PREPARED=0
trap - ERR INT TERM HUP

echo "Pruning old immutable release directories after successful activation."
if ! "${APP_LINK}/.venv/bin/python" \
  "${APP_LINK}/prune_christiania_releases.py" \
  --release-root "${RELEASE_ROOT}" \
  --active-release "${RELEASE_DIR}" \
  --retention 4 \
  --json; then
  echo "WARNING: release-directory pruning failed; activation remains valid." >&2
fi

echo
echo "CHRISTIANIA RELEASE ACTIVATED"
echo "commit=${EXPECTED_COMMIT}"
echo "archive_sha256=${EXPECTED_SHA256}"
echo "release=${RELEASE_DIR}"
echo "previous=${PREVIOUS_TARGET}"
echo "legacy_migration=${LEGACY_MOVED}"
echo "quarantined_retry=${QUARANTINED_RELEASE}"
echo "database_migrated=${DB_MIGRATED}"
echo "database_rollback_backup=${ROLLBACK_DB_BACKUP}"
echo "status_command=${LOCAL_BIN}/christiania-status"