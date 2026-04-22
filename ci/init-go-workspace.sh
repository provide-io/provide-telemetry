#!/usr/bin/env bash
set -euo pipefail

repo_root="${1:?repository root required}"
workspace_dir="${2:?workspace output directory required}"

required_version() {
  local go_mod_path="${1:?go.mod path required}"
  local module_path="${2:?module path required}"

  awk -v module_path="${module_path}" '
    $1 == "require" && $2 == module_path {
      print $3
      exit
    }
    $1 == "require" && $2 == "(" {
      in_require = 1
      next
    }
    in_require && $1 == ")" {
      in_require = 0
      next
    }
    in_require && $1 == module_path {
      print $2
      exit
    }
  ' "${go_mod_path}"
}

mkdir -p "${workspace_dir}"
rm -f "${workspace_dir}/go.work" "${workspace_dir}/go.work.sum"

temp_dir="$(mktemp -d)"
trap 'rm -rf "${temp_dir}"' EXIT

root_internal_version="$(required_version "${repo_root}/go/go.mod" "github.com/provide-io/provide-telemetry/go/internal")"
logger_internal_version="$(required_version "${repo_root}/go/logger/go.mod" "github.com/provide-io/provide-telemetry/go/internal")"
tracer_logger_version="$(required_version "${repo_root}/go/tracer/go.mod" "github.com/provide-io/provide-telemetry/go/logger")"

(
  cd "${temp_dir}"
  go work init \
    "${repo_root}/go" \
    "${repo_root}/go/internal" \
    "${repo_root}/go/logger" \
    "${repo_root}/go/tracer"
  # Nested modules still consult versioned requirements while constructing the
  # module graph, so pin unreleased local edges back to disk explicitly.
  replace_args=(
    "-replace=github.com/provide-io/provide-telemetry/go/internal@${root_internal_version}=${repo_root}/go/internal"
    "-replace=github.com/provide-io/provide-telemetry/go/logger@${tracer_logger_version}=${repo_root}/go/logger"
  )
  if [ "${logger_internal_version}" != "${root_internal_version}" ]; then
    replace_args+=("-replace=github.com/provide-io/provide-telemetry/go/internal@${logger_internal_version}=${repo_root}/go/internal")
  fi
  env GOWORK="${temp_dir}/go.work" go work edit "${replace_args[@]}"
  mv go.work "${workspace_dir}/go.work"
  if [ -f go.work.sum ]; then
    mv go.work.sum "${workspace_dir}/go.work.sum"
  fi
)

printf '%s\n' "${workspace_dir}/go.work"
