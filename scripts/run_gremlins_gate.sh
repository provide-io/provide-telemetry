#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#
# Run gremlins and actually fail on a surviving or uncovered mutant.
#
# gremlins' own --threshold-efficacy / --threshold-mcover flags do not gate:
# v0.6.0 exits 0 even when asked for an impossible 101%, verified by running
# ./logger at --threshold-efficacy=101 --threshold-mcover=101. Every CI step
# that relied on those flags for "100% kill rate required" would therefore have
# passed with live mutants. This wrapper reads the summary gremlins prints and
# enforces the threshold itself.
#
# Usage: run_gremlins_gate.sh <gremlins args...>
# The caller passes the same arguments it would pass to `gremlins unleash`.

set -uo pipefail

log="$(mktemp)"
trap 'rm -f "${log}"' EXIT

gremlins unleash "$@" 2>&1 | tee "${log}"
status="${PIPESTATUS[0]}"

if [ "${status}" -ne 0 ]; then
  echo "FAIL: gremlins exited ${status}"
  exit "${status}"
fi

# "Killed: 498, Lived: 0, Not covered: 2"
summary="$(grep -E '^Killed: [0-9]+, Lived: [0-9]+, Not covered: [0-9]+' "${log}" | tail -1)"
if [ -z "${summary}" ]; then
  echo "FAIL: gremlins printed no result summary; refusing to report a pass."
  exit 1
fi

read -r lived not_covered <<<"$(sed -E 's/.*Lived: ([0-9]+), Not covered: ([0-9]+).*/\1 \2/' <<<"${summary}")"

# Timed out and not-viable mutants are reported on the following line. A timeout
# is an untested mutant, so it fails the gate for the same reason a survivor
# does; not-viable mutants do not compile and are legitimately untestable.
timed_out="$(grep -oE '^Timed out: [0-9]+' "${log}" | tail -1 | grep -oE '[0-9]+' || echo 0)"

echo "gremlins gate: lived=${lived} not_covered=${not_covered} timed_out=${timed_out}"

rc=0
if [ "${lived}" -ne 0 ]; then
  echo "FAIL: ${lived} mutant(s) survived."
  grep -E '^\s*LIVED' "${log}" || true
  rc=1
fi
if [ "${not_covered}" -ne 0 ]; then
  echo "FAIL: ${not_covered} mutant(s) not covered by any test."
  grep -E '^\s*NOT COVERED' "${log}" || true
  rc=1
fi
if [ "${timed_out}" -ne 0 ]; then
  echo "FAIL: ${timed_out} mutant(s) timed out and were never decided."
  rc=1
fi

exit "${rc}"
