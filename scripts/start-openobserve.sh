#!/usr/bin/env sh
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
#
# Start a local OpenObserve instance for development and example runs.
# Credentials use the .test TLD (IANA-reserved per RFC 2606 — never a real mail server).
#
# Usage:
#   sh scripts/start-openobserve.sh
#
# Override defaults via env:
#   OPENOBSERVE_USER=other@provide.test \
#   OPENOBSERVE_PASSWORD=mypass \
#   sh scripts/start-openobserve.sh

OPENOBSERVE_USER="${OPENOBSERVE_USER:-admin@provide.test}"
OPENOBSERVE_PASSWORD="${OPENOBSERVE_PASSWORD:-Complexpass#123}"
OPENOBSERVE_URL="${OPENOBSERVE_URL:-http://localhost:5080/api/default}"

# Stop any container currently bound to port 5080.
EXISTING=$(docker ps -q --filter "publish=5080")
if [ -n "${EXISTING}" ]; then
  printf 'Stopping container(s) on port 5080...\n'
  docker rm -f ${EXISTING} >/dev/null
fi
# Remove any stopped openobserve-dev container.
if docker inspect openobserve-dev >/dev/null 2>&1; then
  docker rm -f openobserve-dev >/dev/null
fi

docker run --detach \
  --name openobserve-dev \
  -v "${PWD}/.openobserve-data:/data" \
  -e ZO_DATA_DIR="/data" \
  -p 5080:5080 \
  -e ZO_ROOT_USER_EMAIL="${OPENOBSERVE_USER}" \
  -e ZO_ROOT_USER_PASSWORD="${OPENOBSERVE_PASSWORD}" \
  openobserve/openobserve:v0.14.5

printf '\nOpenObserve starting → http://localhost:5080\n'
printf '  User:     %s\n' "${OPENOBSERVE_USER}"
printf '  Password: %s\n' "${OPENOBSERVE_PASSWORD}"
printf '  API URL:  %s\n\n' "${OPENOBSERVE_URL}"
printf 'Set env vars before running examples:\n'
printf '  export OPENOBSERVE_URL=%s\n' "${OPENOBSERVE_URL}"
printf '  export OPENOBSERVE_USER=%s\n' "${OPENOBSERVE_USER}"
printf '  export OPENOBSERVE_PASSWORD=%s\n' "${OPENOBSERVE_PASSWORD}"
