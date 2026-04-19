#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#
# Verify the OTLP collector log contains every required signal name.
# Polls with retry because the collector may still be flushing OTLP requests
# to its log file after the producing test has exited (race observed on
# GitHub Actions ubuntu-latest runners).
#
# Usage: ci/verify-collector-signals.sh <log_path> <signal1> [signal2 ...]
#        Optional: SIGNAL_WAIT_SECONDS env var (default 30) sets the deadline.

set -euo pipefail

LOG_PATH="${1:?usage: verify-collector-signals.sh <log_path> <signal>...}"
shift
SIGNALS=("$@")
DEADLINE_SECONDS="${SIGNAL_WAIT_SECONDS:-30}"

if [ ${#SIGNALS[@]} -eq 0 ]; then
  echo "verify-collector-signals: no signal names supplied" >&2
  exit 2
fi

# Refresh the log file from the running collector container, then check.
# Container name is conventional per the existing workflows: otelcol-<lang>.
# Allow override via OTELCOL_CONTAINER env var.
CONTAINER="${OTELCOL_CONTAINER:-}"

end=$(( $(date +%s) + DEADLINE_SECONDS ))
while [ "$(date +%s)" -lt "$end" ]; do
  if [ -n "$CONTAINER" ]; then
    docker logs "$CONTAINER" >"$LOG_PATH" 2>&1 || true
  fi
  missing=()
  for sig in "${SIGNALS[@]}"; do
    if ! grep -q "$sig" "$LOG_PATH"; then
      missing+=("$sig")
    fi
  done
  if [ ${#missing[@]} -eq 0 ]; then
    echo "verify-collector-signals: all ${#SIGNALS[@]} signal(s) found in $LOG_PATH"
    exit 0
  fi
  sleep 1
done

echo "verify-collector-signals: timeout after ${DEADLINE_SECONDS}s — missing signals:" >&2
for sig in "${missing[@]}"; do
  echo "  - $sig" >&2
done
echo "--- last 80 lines of $LOG_PATH ---" >&2
tail -80 "$LOG_PATH" >&2 || true
exit 1
