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
# Data is kept in a host bind mount under the repo, NOT a named Docker volume.
# Rationale: a named volume lives inside the VM's disk image (e.g. colima's
# ~/.colima/_lima/_disks/colima/datadisk). That image is sparse — it inflates as
# the volume grows but never shrinks when data is deleted, so reclaiming space
# needs a manual `fstrim` inside the VM. A host bind keeps the data on the host
# filesystem: visible, and freed the instant the directory is removed.
#
# The "mkdir <repo>: file exists" bind failure happens because `-v` makes the
# daemon RECURSIVELY create the source path, and virtiofs (colima/Docker Desktop)
# chokes trying to mkdir an already-existing parent. Fix: `mkdir -p` the dir here,
# then mount with `--mount type=bind` — which requires the source to exist and
# never tries to create it, so the buggy recursive mkdir is skipped entirely.
#
# The bind source is also canonicalized to its physical, symlink-free path: a
# VM-backed runtime (e.g. colima) mounts host paths by their real location, so a
# source still containing a symlink — common when a repo is symlinked onto another
# volume — won't resolve inside the VM. That volume must itself be shared into the
# VM (for colima, add it under `mounts:` in ~/.colima/<profile>/colima.yaml and
# `colima restart`). Override the location with OPENOBSERVE_DATA_DIR.
# Wipe it with: rm -rf "${OPENOBSERVE_DATA_DIR}"

# Resolve a directory to its physical, symlink-free absolute path.
_physical_dir() {
  CDPATH= cd -P -- "$1" && pwd -P
}

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OPENOBSERVE_DATA_DIR="${OPENOBSERVE_DATA_DIR:-${REPO_ROOT}/.openobserve-data}"
mkdir -p "${OPENOBSERVE_DATA_DIR}"
OPENOBSERVE_DATA_DIR=$(_physical_dir "${OPENOBSERVE_DATA_DIR}")

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
  --mount "type=bind,source=${OPENOBSERVE_DATA_DIR},target=/data" \
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
