#!/usr/bin/env bash
set -euo pipefail

APP_LINK="/opt/christiania"
PROBE_ROOT="/opt/christiania-probes"
ENV_FILE="/etc/christiania/christiania.env"
STATE_ROOT="/var/lib/christiania"
SERVICE_USER="christiania"

fail() {
  echo "PERFORMANCE PROBE FAILED: $*" >&2
  exit 1
}

resolve_python_313() {
  local candidate=""
  local version=""

  for candidate in python3.13 python3; do
    if ! command -v "${candidate}" >/dev/null 2>&1; then
      continue
    fi
    version="$("${candidate}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if [[ "${version}" == "3.13" ]]; then
      command -v "${candidate}"
      return 0
    fi
  done

  fail "Python 3.13 interpreter not found."
}

if [[ "${EUID}" -ne 0 ]]; then
  fail "probe must run as root"
fi

if [[ "$#" -ne 3 ]]; then
  echo "Usage: sudo bash probe_release_performance.sh <archive.tar.gz> <40-char-commit> <sha256>" >&2
  exit 2
fi

ARCHIVE="$1"
EXPECTED_COMMIT="${2,,}"
EXPECTED_SHA256="${3,,}"

[[ -f "${ARCHIVE}" ]] || fail "release archive missing: ${ARCHIVE}"
[[ "${EXPECTED_COMMIT}" =~ ^[0-9a-f]{40}$ ]] || fail "invalid commit SHA"
[[ "${EXPECTED_SHA256}" =~ ^[0-9a-f]{64}$ ]] || fail "invalid archive SHA-256"
[[ -f "${ENV_FILE}" ]] || fail "runtime environment file missing: ${ENV_FILE}"
id "${SERVICE_USER}" >/dev/null 2>&1 || fail "service account missing: ${SERVICE_USER}"

for required in awk chmod chown date grep install mktemp rm sha256sum sort sudo tar; do
  command -v "${required}" >/dev/null 2>&1 || fail "required command missing: ${required}"
done

ACTUAL_SHA256="$(sha256sum "${ARCHIVE}" | awk '{print tolower($1)}')"
[[ "${ACTUAL_SHA256}" == "${EXPECTED_SHA256}" ]] || fail "archive SHA-256 mismatch"

while IFS= read -r member; do
  [[ -z "${member}" ]] && continue
  [[ "${member}" != /* ]] || fail "archive contains absolute path: ${member}"
  [[ ! "${member}" =~ (^|/)\.\.(/|$) ]] || fail "archive contains path traversal: ${member}"
done < <(tar -tzf "${ARCHIVE}")

PROBE_ID="${EXPECTED_COMMIT}-$(date -u +%Y%m%dT%H%M%SZ)-$$"
PROBE_DIR="${PROBE_ROOT}/${PROBE_ID}"
REPORT_DIR="${STATE_ROOT}/audit/performance-probes"
REPORT_PATH="${REPORT_DIR}/${EXPECTED_COMMIT}-$(date -u +%Y%m%dT%H%M%SZ).json"

cleanup() {
  rm -rf -- "${PROBE_DIR}"
}
trap cleanup EXIT

install -d -m 0750 -o root -g "${SERVICE_USER}" "${PROBE_ROOT}"
install -d -m 0750 -o root -g "${SERVICE_USER}" "${PROBE_DIR}"
install -d -m 0750 -o root -g "${SERVICE_USER}" "${REPORT_DIR}"
tar -xzf "${ARCHIVE}" -C "${PROBE_DIR}"
printf '%s\n' "${EXPECTED_COMMIT}" > "${PROBE_DIR}/DEPLOYED_COMMIT"

PYTHON_BIN="$(resolve_python_313)"
"${PYTHON_BIN}" -m venv "${PROBE_DIR}/.venv"
"${PROBE_DIR}/.venv/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-compile \
  --no-deps \
  -r "${PROBE_DIR}/requirements-lock-linux-py313.txt"
"${PROBE_DIR}/.venv/bin/python" -m pip check

LOCK_ACTUAL="$("${PROBE_DIR}/.venv/bin/python" -m pip freeze | LC_ALL=C sort -f)"
LOCK_EXPECTED="$(grep -vE '^[[:space:]]*(#|$)' "${PROBE_DIR}/requirements-lock-linux-py313.txt" | LC_ALL=C sort -f)"
[[ "${LOCK_ACTUAL}" == "${LOCK_EXPECTED}" ]] || fail "probe runtime does not match committed Linux lock"

chown -R root:"${SERVICE_USER}" "${PROBE_DIR}"
chmod -R g+rX,o-rwx "${PROBE_DIR}"

TMP_REPORT="$(mktemp "${REPORT_DIR}/.probe.XXXXXX")"
trap 'rm -f "${TMP_REPORT}"; cleanup' EXIT

(
  cd "${PROBE_DIR}"
  sudo -u "${SERVICE_USER}" \
    "${PROBE_DIR}/.venv/bin/python" \
    "${PROBE_DIR}/christiania_performance_probe.py" \
    --env-file "${ENV_FILE}" \
    --include-full \
    --warmups 1 \
    --runs 3
) > "${TMP_REPORT}"

chown root:"${SERVICE_USER}" "${TMP_REPORT}"
chmod 0640 "${TMP_REPORT}"
mv -f "${TMP_REPORT}" "${REPORT_PATH}"
trap cleanup EXIT

echo "PERFORMANCE PROBE COMPLETE"
echo "commit=${EXPECTED_COMMIT}"
echo "performance_report=${REPORT_PATH}"
cat "${REPORT_PATH}"
