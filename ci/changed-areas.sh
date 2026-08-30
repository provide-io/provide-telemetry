#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
#
# Report which areas of the repository a change touches.
#
# Workflows that own a required status context cannot filter at the trigger,
# because a workflow that never runs reports nothing and a context that never
# reports blocks the merge forever -- unlike a job skipped by `if:`, which
# GitHub counts as satisfied. So those workflows always run and gate their jobs
# on this instead.
#
# Usage:  ci/changed-areas.sh <base-ref> [head-ref]
#
# Writes `<area>=true|false` for every area to $GITHUB_OUTPUT (and to stdout
# when run locally). When the diff cannot be computed -- a missing base, a
# shallow clone, the very first commit -- every area reports true, so an
# undetectable change runs everything rather than silently skipping it.

set -euo pipefail

base_ref="${1:-}"
head_ref="${2:-HEAD}"

# Area definitions. Each is a set of `git diff` pathspecs; keep these in step
# with the `paths:` list of any workflow that still filters at the trigger.
AREA_NAMES="go rust spec contracts"

# One pattern per line. `dir/**` matches anything under dir; anything else is an
# exact path.
area_paths() {
  case "$1" in
    go)
      printf '%s\n' "go/**" "ci/**" "VERSION" ".github/workflows/ci-go.yml" \
        "baselines/perf-go.json" "scripts/perf_check.py"
      ;;
    rust)
      printf '%s\n' "rust/**" "ci/**" "VERSION" ".github/workflows/ci-rust.yml"
      ;;
    spec)
      printf '%s\n' "spec/**" "ci/**" "src/provide/telemetry/**" "typescript/src/**" \
        "go/**" "rust/**" "csharp/**" "VERSION" "typescript/package.json" \
        "typescript/package-lock.json" "pyproject.toml" "scripts/check_version_sync.py" \
        ".github/workflows/ci-spec.yml"
      ;;
    contracts)
      printf '%s\n' "spec/**" "ci/**" "src/provide/telemetry/**" "typescript/src/**" \
        "go/**" "rust/src/**" "rust/examples/contract_probe.rs" "VERSION" \
        ".github/workflows/ci-contracts.yml"
      ;;
    *)
      echo "changed-areas: unknown area '$1'" >&2
      return 1
      ;;
  esac
}

emit() {
  printf '%s=%s\n' "$1" "$2"
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf '%s=%s\n' "$1" "$2" >>"$GITHUB_OUTPUT"
  fi
}

# No base to compare against, or a base this clone does not have: run everything.
if [[ -z "$base_ref" ]] || ! git rev-parse --verify --quiet "$base_ref" >/dev/null; then
  echo "changed-areas: no usable base ref (${base_ref:-unset}); reporting every area as changed" >&2
  for area in $AREA_NAMES; do
    emit "$area" true
  done
  exit 0
fi

changed="$(git diff --name-only "$base_ref" "$head_ref" -- || true)"

if [[ -z "$changed" ]]; then
  echo "changed-areas: no files differ from $base_ref; reporting every area as unchanged" >&2
fi

echo "changed-areas: comparing $base_ref..$head_ref" >&2
while IFS= read -r line; do
  [ -n "$line" ] && echo "  $line" >&2
done <<EOF
$changed
EOF

for area in $AREA_NAMES; do
  matched=false
  while IFS= read -r file; do
    [ -z "$file" ] && continue
    while IFS= read -r pattern; do
      case "$pattern" in
        */\*\*)
          case "$file" in
            "${pattern%/**}"/*) matched=true ;;
          esac
          ;;
        *)
          [ "$file" = "$pattern" ] && matched=true
          ;;
      esac
      [ "$matched" = true ] && break
    done <<EOF
$(area_paths "$area")
EOF
    [ "$matched" = true ] && break
  done <<EOF
$changed
EOF
  emit "$area" "$matched"
done
