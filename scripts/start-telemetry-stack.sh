#!/usr/bin/env sh
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
#
# Start the full provide-io local dev telemetry stack and wait for readiness.
#
# Usage:
#   sh scripts/start-telemetry-stack.sh
#
# Credentials (override via env):
#   OPENOBSERVE_USER     defaults to admin@provide.test
#   OPENOBSERVE_PASSWORD defaults to Complexpass#123

set -e
cd "$(dirname "$0")/.."

docker compose up -d

# Wait for Grafana
printf 'Waiting for Grafana'
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null http://localhost:3000/api/health 2>/dev/null; then
    printf ' ready\n'
    break
  fi
  printf '.'
  sleep 1
done

# Wait for OpenObserve
printf 'Waiting for OpenObserve'
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null http://localhost:5080/ 2>/dev/null; then
    printf ' ready\n'
    break
  fi
  printf '.'
  sleep 1
done

OO_USER="${OPENOBSERVE_USER:-admin@provide.test}"
OO_PASS="${OPENOBSERVE_PASSWORD:-Complexpass#123}"

printf '\n── Telemetry stack running ───────────────────────────────────────\n'
printf '  DIRECT (no DNS, no proxy)\n'
printf '    Grafana UI    http://localhost:3000\n'
printf '    OTLP HTTP     http://localhost:4318\n'
printf '    OTLP gRPC     localhost:4317\n'
printf '    OpenObserve   http://localhost:5080\n'
printf '    Traefik UI    http://localhost:8080\n'
printf '\n'
printf '  PROXIED (requires: sudo sh scripts/setup-provide-test-dns.sh)\n'
printf '    Grafana UI    http://telemetry.provide.test:5314\n'
printf '    OTLP HTTP     http://otlp.provide.test:5314\n'
printf '    OpenObserve   http://openobserve.provide.test:5314\n'
printf '\n'
printf '  OpenObserve credentials\n'
printf '    User          %s\n' "${OO_USER}"
printf '    Password      %s\n' "${OO_PASS}"
printf '─────────────────────────────────────────────────────────────────\n'
