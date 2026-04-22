#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.

set -euo pipefail

max_attempts="${UV_SYNC_MAX_ATTEMPTS:-4}"
base_delay_seconds="${UV_SYNC_RETRY_DELAY_SECONDS:-5}"

attempt=1
while true; do
  if uv sync "$@"; then
    exit 0
  else
    status=$?
  fi

  if [ "${attempt}" -ge "${max_attempts}" ]; then
    echo "uv sync failed after ${attempt} attempts" >&2
    exit "${status}"
  fi

  delay_seconds=$((base_delay_seconds * attempt))
  echo "uv sync failed with exit ${status}; retrying in ${delay_seconds}s (${attempt}/${max_attempts})..." >&2
  sleep "${delay_seconds}"
  attempt=$((attempt + 1))
done
