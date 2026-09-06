#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root on an Ubuntu 24.04 VM." >&2
  exit 2
fi

if [[ ! -r /etc/os-release ]]; then
  echo "Cannot identify operating system." >&2
  exit 3
fi

. /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
  echo "RC0 bootstrap is pinned to Ubuntu 24.04; found ${ID:-unknown} ${VERSION_ID:-unknown}." >&2
  exit 4
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  git \
  jq \
  openjdk-21-jre-headless \
  python3 \
  python3-pip \
  python3-venv \
  rsync \
  sqlite3 \
  sudo \
  ufw

java_major="$(
  java -version 2>&1 |
  awk -F'[\".]' '/version/ {print $2; exit}'
)"
if [[ -z "${java_major}" || "${java_major}" -lt 21 ]]; then
  echo "Java 21+ is required by current Theta Terminal v3." >&2
  exit 5
fi

echo "Core Ubuntu RC0 dependencies installed."
echo "Firewall was NOT enabled automatically; remote access is never changed implicitly."
echo "Caddy and oauth2-proxy are intentionally installed in the separate secure-edge step."
