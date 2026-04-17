#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#
# Wait for the OTLP collector health endpoint to respond.
# Usage: ci/wait-for-collector.sh [url] [timeout_seconds]

set -euo pipefail

URL="${1:-http://127.0.0.1:13133/}"
TIMEOUT="${2:-30}"

for _ in $(seq 1 "$TIMEOUT"); do
  if curl -fsS "$URL" >/dev/null 2>&1; then
    exit 0
  fi
  sleep 1
done

echo "collector failed health check after ${TIMEOUT}s at $URL"
exit 1
