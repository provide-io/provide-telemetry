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

(
  cd "${temp_dir}"
  go work init \
    "${repo_root}/go" \
    "${repo_root}/go/otel" \
    "${repo_root}/go/cmd/e2e_cross_language_client"
  mv go.work "${workspace_dir}/go.work"
  if [ -f go.work.sum ]; then
    mv go.work.sum "${workspace_dir}/go.work.sum"
  fi
)

printf '%s\n' "${workspace_dir}/go.work"
