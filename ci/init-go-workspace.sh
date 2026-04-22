#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.

set -euo pipefail

repo_root="${1:?repository root required}"
workspace_dir="${2:?workspace output directory required}"

canonicalize_dir() {
  (
    cd "${1}"
    pwd -P
  )
}

repo_root="$(canonicalize_dir "${repo_root}")"
mkdir -p "${workspace_dir}"
workspace_dir="$(canonicalize_dir "${workspace_dir}")"
rm -f "${workspace_dir}/go.work" "${workspace_dir}/go.work.sum"

workspace_modules=()
workspace_go_version=""

go_version_gt() {
  awk -v candidate="${1}" -v current="${2}" '
    function part(version, position,    values, count) {
      count = split(version, values, ".")
      return position <= count ? values[position] + 0 : 0
    }

    BEGIN {
      for (i = 1; i <= 3; i++) {
        candidate_part = part(candidate, i)
        current_part = part(current, i)
        if (candidate_part > current_part) {
          exit 0
        }
        if (candidate_part < current_part) {
          exit 1
        }
      }
      exit 1
    }
  ' </dev/null
}

for module_dir in \
  "${repo_root}/go" \
  "${repo_root}/go/internal" \
  "${repo_root}/go/logger" \
  "${repo_root}/go/tracer" \
  "${repo_root}/go/otel" \
  "${repo_root}/go/cmd/e2e_cross_language_client"
do
  if [ -f "${module_dir}/go.mod" ]; then
    module_dir="$(canonicalize_dir "${module_dir}")"
    workspace_modules+=("${module_dir}")
    module_go_version="$(
      awk '/^go[[:space:]]+/ { print $2; exit }' "${module_dir}/go.mod"
    )"
    if [ -z "${workspace_go_version}" ] || go_version_gt "${module_go_version}" "${workspace_go_version}"; then
      workspace_go_version="${module_go_version}"
    fi
  fi
done

if [ "${#workspace_modules[@]}" -eq 0 ]; then
  echo "no Go modules found under ${repo_root}" >&2
  exit 1
fi

if [ -z "${workspace_go_version}" ]; then
  echo "unable to determine Go version from workspace modules under ${repo_root}" >&2
  exit 1
fi

{
  printf 'go %s\n\n' "${workspace_go_version}"
  if [ "${#workspace_modules[@]}" -eq 1 ]; then
    printf 'use %s\n' "${workspace_modules[0]}"
  else
    printf 'use (\n'
    for module_dir in "${workspace_modules[@]}"; do
      printf '\t%s\n' "${module_dir}"
    done
    printf ')\n'
  fi
} > "${workspace_dir}/go.work"

printf '%s\n' "${workspace_dir}/go.work"
