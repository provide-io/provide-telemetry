#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.

set -euo pipefail

repo_root="${1:?repository root required}"
workspace_dir="${2:?workspace output directory required}"

mkdir -p "${workspace_dir}"
rm -f "${workspace_dir}/go.work" "${workspace_dir}/go.work.sum"

temp_dir="$(mktemp -d)"
trap 'rm -rf "${temp_dir}"' EXIT

workspace_modules=()
for module_dir in \
  "${repo_root}/go" \
  "${repo_root}/go/internal" \
  "${repo_root}/go/logger" \
  "${repo_root}/go/tracer" \
  "${repo_root}/go/otel" \
  "${repo_root}/go/cmd/e2e_cross_language_client"
do
  if [ -f "${module_dir}/go.mod" ]; then
    workspace_modules+=("${module_dir}")
  fi
done

if [ "${#workspace_modules[@]}" -eq 0 ]; then
  echo "no Go modules found under ${repo_root}" >&2
  exit 1
fi

(
  cd "${temp_dir}"
  go work init "${workspace_modules[@]}"
  mv go.work "${workspace_dir}/go.work"
  if [ -f go.work.sum ]; then
    mv go.work.sum "${workspace_dir}/go.work.sum"
  fi
)

printf '%s\n' "${workspace_dir}/go.work"
