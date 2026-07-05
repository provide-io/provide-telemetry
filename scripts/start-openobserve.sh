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
# Data is kept in a named Docker volume (not a host bind mount). A host bind mount
# of "${PWD}/.openobserve-data" fails on Docker Desktop for macOS with
# "error while creating mount source path ... mkdir <repo>: file exists" — a
# virtiofs/gRPC-FUSE quirk that leaves the container stuck in "Created". A named
# volume sidesteps host file-sharing entirely and persists across restarts.
# Wipe it with: docker volume rm "${OPENOBSERVE_VOLUME:-openobserve-dev-data}"
OPENOBSERVE_VOLUME="${OPENOBSERVE_VOLUME:-openobserve-dev-data}"

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
  -v "${OPENOBSERVE_VOLUME}:/data" \
  -e ZO_DATA_DIR="/data" \
  -p 5080:5080 \
  -e ZO_ROOT_USER_EMAIL="${OPENOBSERVE_USER}" \
  -e ZO_ROOT_USER_PASSWORD="${OPENOBSERVE_PASSWORD}" \
  openobserve/openobserve:v0.91.1 || exit 1

# Wait until the HTTP server actually answers, so callers know it's ready (not
# just "Created"). OpenObserve boots in ~2-5s; give it up to ~30s.
printf '\nWaiting for OpenObserve to become ready'
i=0
while [ "${i}" -lt 30 ]; do
  if curl -fsS -o /dev/null "http://localhost:5080/healthz" 2>/dev/null; then
    printf ' ready\n'
    break
  fi
  printf '.'
  sleep 1
  i=$((i + 1))
done
if [ "${i}" -ge 30 ]; then
  printf '\nOpenObserve did not answer /healthz within 30s; check: docker logs openobserve-dev\n'
  exit 1
fi

printf '\nOpenObserve running → http://localhost:5080\n'
printf '  User:     %s\n' "${OPENOBSERVE_USER}"
printf '  Password: %s\n' "${OPENOBSERVE_PASSWORD}"
printf '  API URL:  %s\n\n' "${OPENOBSERVE_URL}"
printf 'Set env vars before running examples:\n'
printf '  export OPENOBSERVE_URL=%s\n' "${OPENOBSERVE_URL}"
printf '  export OPENOBSERVE_USER=%s\n' "${OPENOBSERVE_USER}"
printf '  export OPENOBSERVE_PASSWORD=%s\n' "${OPENOBSERVE_PASSWORD}"
