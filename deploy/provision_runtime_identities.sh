#!/usr/bin/env bash
set -euo pipefail

SERVICE_USER="${CHRISTIANIA_SERVICE_USER:-christiania}"
RUNTIME_GROUP="${CHRISTIANIA_RUNTIME_GROUP:-christiania-runtime}"
UI_USER="${CHRISTIANIA_UI_USER:-christiania-ui}"
STATE_ROOT="${CHRISTIANIA_STATE_ROOT:-/var/lib/christiania}"
UI_ENV_ROOT="${CHRISTIANIA_UI_ENV_ROOT:-/etc/christiania-ui}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Christiania runtime identity provisioning must run as root." >&2
  exit 2
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  echo "Christiania backend service user does not exist: ${SERVICE_USER}" >&2
  exit 3
fi

if ! getent group "${RUNTIME_GROUP}" >/dev/null 2>&1; then
  groupadd --system "${RUNTIME_GROUP}"
fi

usermod -a -G "${RUNTIME_GROUP}" "${SERVICE_USER}"

if ! id "${UI_USER}" >/dev/null 2>&1; then
  useradd \
    --system \
    --home-dir /nonexistent \
    --shell /usr/sbin/nologin \
    --gid "${RUNTIME_GROUP}" \
    "${UI_USER}"
else
  usermod \
    --gid "${RUNTIME_GROUP}" \
    --groups "" \
    "${UI_USER}"
fi

install \
  -d \
  -m 0750 \
  -o root \
  -g "${RUNTIME_GROUP}" \
  "${UI_ENV_ROOT}"

for directory in \
  "${STATE_ROOT}/data" \
  "${STATE_ROOT}/backups" \
  "${STATE_ROOT}/audit"
do
  install \
    -d \
    -m 2750 \
    -o "${SERVICE_USER}" \
    -g "${RUNTIME_GROUP}" \
    "${directory}"

  chgrp -R \
    "${RUNTIME_GROUP}" \
    "${directory}"

  find "${directory}" \
    -type d \
    -exec chmod u=rwx,g=rx,o= {} + \
    -exec chmod g+s {} +

  find "${directory}" \
    -type f \
    -exec chmod u=rw,g=r,o= {} +
done

echo "Christiania runtime identities provisioned."
echo "backend_user=${SERVICE_USER}"
echo "ui_user=${UI_USER}"
echo "runtime_group=${RUNTIME_GROUP}"
