#!/usr/bin/env sh
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
#
# Optional: add *.provide.test hostnames to /etc/hosts for pretty URLs.
#
# The telemetry stack works WITHOUT this script via nip.io:
#   http://telemetry.127.0.0.1.nip.io:5314
#   http://openobserve.127.0.0.1.nip.io:5314
#   http://otlp.127.0.0.1.nip.io:5314
#
# Running this script adds /etc/hosts entries so you can also use:
#   http://telemetry.provide.test:5314
#   http://openobserve.provide.test:5314
#   http://otlp.provide.test:5314
#
# Usage:
#   sudo sh scripts/setup-provide-test-dns.sh
#
# Notes:
#   - Idempotent — safe to run multiple times.
#   - macOS 26 broke /etc/resolver/ for custom TLDs, so we use /etc/hosts
#     instead of dnsmasq. No wildcards, but three entries cover the stack.
#   - Add new entries when you add services to docker-compose.yml.

set -e

MARKER="# provide.test dev infrastructure"
HOSTS_FILE="/etc/hosts"

# The hostnames to register — add new services here.
ENTRIES="127.0.0.1  telemetry.provide.test openobserve.provide.test otlp.provide.test"

if grep -qF "${MARKER}" "${HOSTS_FILE}" 2>/dev/null; then
  printf 'provide.test entries already present in %s\n' "${HOSTS_FILE}"
else
  printf '\n%s\n%s\n' "${MARKER}" "${ENTRIES}" >> "${HOSTS_FILE}"
  printf 'Added provide.test entries to %s\n' "${HOSTS_FILE}"
fi

# Flush DNS cache (macOS)
if [ "$(uname -s)" = "Darwin" ]; then
  dscacheutil -flushcache 2>/dev/null || true
  killall -HUP mDNSResponder 2>/dev/null || true
  printf 'DNS cache flushed\n'
fi

printf '\nVerify:\n'
printf '  ping -c1 openobserve.provide.test\n'
printf '  ping -c1 telemetry.provide.test\n'
printf '  ping -c1 otlp.provide.test\n'
