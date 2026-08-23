#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#
# Run the go/ coverage-guided fuzz targets, one at a time.
#
# `go test -fuzz` occasionally reports "context deadline exceeded" as a FAIL
# when -fuzztime expires while a worker is still mid-exchange with the
# coordinator. It is an end-of-run race, not a finding: no input is minimised,
# nothing is written to testdata/fuzz, and the same target passes on a rerun.
# The 0.8.1 release hit it on FuzzValidatedSignalEndpointURL at 900.10s of a
# 15m budget, after three targets had each run 900.09s green.
#
# Retrying blindly would hide a real crash, so this looks at what the run left
# behind: a corpus entry under testdata/fuzz means a genuine failing input and
# is fatal immediately. Only a deadline-shaped failure that wrote nothing is
# retried, once. A second one is fatal too — a target that cannot finish twice
# running is a problem, not a flake.
set -euo pipefail

readonly FUZZTIME="${FUZZTIME:-30s}"
readonly GO_DIR="${GO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../go" && pwd)}"
readonly CORPUS_DIR="${GO_DIR}/testdata/fuzz"

# The gate's targets live in fuzz_test.go. property_test.go carries its own
# Fuzz functions that run as seed-corpus tests elsewhere and are deliberately
# not fuzzed here; tests/tooling/test_go_fuzz_budget.py pins this list against
# that file so the two cannot drift apart silently.
readonly TARGETS=(
  FuzzParseOTLPHeaders
  FuzzMaskEndpointURL
  FuzzValidateRate
  FuzzValidatedSignalEndpointURL
  FuzzParseEnvFloatThenValidateRate
)

run_target() {
  local target="$1" output status=0
  output="$(cd "${GO_DIR}" && go test . -run='^$' -fuzz="^${target}\$" -fuzztime="${FUZZTIME}" 2>&1)" || status=$?
  printf '%s\n' "${output}"
  if [[ ${status} -eq 0 ]]; then
    return 0
  fi
  if [[ -d "${CORPUS_DIR}/${target}" ]] || grep -q "Failing input written to" <<<"${output}"; then
    echo "run-go-fuzz: ${target} found a failing input — see testdata/fuzz/${target}" >&2
    return 1
  fi
  if grep -q "context deadline exceeded" <<<"${output}"; then
    return 2
  fi
  echo "run-go-fuzz: ${target} failed for a reason that is not the deadline race" >&2
  return 1
}

for target in "${TARGETS[@]}"; do
  echo "run-go-fuzz: ${target} (fuzztime=${FUZZTIME})"
  status=0
  run_target "${target}" || status=$?
  case ${status} in
    0) ;;
    2)
      echo "run-go-fuzz: ${target} hit the end-of-run deadline race and wrote no input; retrying once" >&2
      retry=0
      run_target "${target}" || retry=$?
      if [[ ${retry} -ne 0 ]]; then
        echo "run-go-fuzz: ${target} failed again — treating as a real failure" >&2
        exit 1
      fi
      ;;
    *) exit 1 ;;
  esac
done

echo "run-go-fuzz: all ${#TARGETS[@]} targets completed at fuzztime=${FUZZTIME}"
