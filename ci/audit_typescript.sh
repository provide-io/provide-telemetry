#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#
# Audit the complete npm dependency graph — production and development.
#
# A graph with implausibly few packages means the audit examined nothing, which
# is a broken scan rather than a clean one, so we assert a floor before
# trusting a zero-finding result.
set -euo pipefail

readonly REPO_ROOT="${PROVIDE_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
readonly MIN_PACKAGES=100

if [[ ! -d "${REPO_ROOT}/typescript" ]]; then
  echo "typescript: no typescript/ directory under ${REPO_ROOT}" >&2
  exit 2
fi
cd "${REPO_ROOT}/typescript"

# `npm audit` exits non-zero when it finds something, so the failure is handled
# below rather than by set -e swallowing the report.
report="$(npm audit --json 2>/dev/null || true)"
if [[ -z "${report}" ]]; then
  echo "typescript: npm audit produced no output" >&2
  exit 2
fi

total="$(printf '%s' "${report}" | node -e '
  let raw = ""
  process.stdin.on("data", (d) => { raw += d })
  process.stdin.on("end", () => {
    const meta = JSON.parse(raw).metadata ?? {}
    const deps = meta.dependencies ?? {}
    const n = typeof deps === "number" ? deps : Object.values(deps).reduce((a, b) => a + b, 0)
    process.stdout.write(String(n))
  })
')"

if [[ -z "${total}" ]] || (( total < MIN_PACKAGES )); then
  echo "typescript: audit inventoried ${total:-0} packages, expected at least ${MIN_PACKAGES}" >&2
  exit 2
fi
echo "typescript: audited ${total} packages"

# --audit-level=low so a low-severity advisory cannot slip through as clean.
npm audit --audit-level=low
