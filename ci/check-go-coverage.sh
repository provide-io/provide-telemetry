#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#
# Enforce a Go coverage profile's total against an exact expected percentage.
# Usage: ci/check-go-coverage.sh <profile> [expected-total]
#
# Lifted out of ci-go.yml when the test job gained a Windows leg: the gate now
# runs on two operating systems and in two jobs, and a `run:` block longer than
# three lines belongs in a script (CLAUDE.md). The workflow selects `shell:
# bash` so the Windows runner executes this through Git Bash, exactly as Linux
# does.
#
# The total is matched on the "total:" field rather than grepped for the
# substring, so a function whose name contains "total" cannot supply the
# number. An empty total — a profile `go tool cover` could not summarise —
# fails rather than comparing empty against the expectation and passing.

set -euo pipefail

profile="${1:?coverage profile required}"
expected="${2:-100.0%}"

total="$(go tool cover -func="${profile}" | awk '$1 == "total:" { print $3 }')"

echo "Total coverage: ${total}"
if [ "${total}" != "${expected}" ]; then
  echo "FAIL: coverage is ${total:-<none reported>}, expected ${expected}"
  exit 1
fi
