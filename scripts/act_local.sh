#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

set -euo pipefail

if [[ $# -eq 0 ]]; then
  cat >&2 <<'USAGE'
usage: scripts/act_local.sh <act event/options...>

Runs act with local clones for SHA-pinned third-party actions. This avoids
act versions that incorrectly fetch SHA pins as branch refs while preserving
SHA-pinned GitHub Actions in CI.
USAGE
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cache_root="${PROVIDE_ACT_ACTION_CACHE:-"${repo_root}/.provide/act-actions"}"
act_bin="${ACT_BIN:-act}"

actions=(
  "actions/setup-node|53b83947a5a98c8d113130e565377fae1a50d02f|setup-node"
  "actions/setup-go|40f1582b2485089dde7abd97c1529aa768e1baff|setup-go"
  "actions/setup-python|a309ff8b426b58ec0e2a45f0f869d46889d02405|setup-python"
  "actions/upload-artifact|bbbca2ddaa5d8feaa63e36b76fdaad77386f024f|upload-artifact"
  "actions/download-artifact|3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c|download-artifact"
  "astral-sh/setup-uv|cec208311dfd045dd5311c1add060b2062131d57|setup-uv"
  "dtolnay/rust-toolchain|29eef336d9b2848a0b548edc03f92a220660cdb8|rust-toolchain"
  "Swatinem/rust-cache|23869a5bd66c73db3c0ac40331f3206eb23791dc|rust-cache"
  "github/codeql-action|5c8a8a642e79153f5d047b10ec1cba1d1cc65699|codeql-action"
  "pypa/gh-action-pypi-publish|ed0c53931b1dc9bd32cbe73a98c7f6766f8a527e|gh-action-pypi-publish"
  "sigstore/gh-action-sigstore-python|f514d46b907ebcd5bedc05145c03b69c1edd8b46|gh-action-sigstore-python"
)

mkdir -p "${cache_root}"

workflow_args=()
expect_workflow_arg=false
for arg in "$@"; do
  if [[ "${expect_workflow_arg}" == "true" ]]; then
    workflow_args+=("${arg}")
    expect_workflow_arg=false
    continue
  fi

  case "${arg}" in
    -W|--workflows)
      expect_workflow_arg=true
      ;;
    --workflows=*)
      workflow_args+=("${arg#--workflows=}")
      ;;
  esac
done

if [[ ${#workflow_args[@]} -eq 0 ]]; then
  workflow_args=(".github/workflows")
fi

workflow_files=()
for workflow_arg in "${workflow_args[@]}"; do
  workflow_path="${workflow_arg}"
  if [[ "${workflow_path}" != /* ]]; then
    workflow_path="${repo_root}/${workflow_path}"
  fi

  if [[ -d "${workflow_path}" ]]; then
    while IFS= read -r -d '' workflow_file; do
      workflow_files+=("${workflow_file}")
    done < <(find "${workflow_path}" -maxdepth 1 -type f \( -name '*.yml' -o -name '*.yaml' \) -print0)
  elif [[ -f "${workflow_path}" ]]; then
    workflow_files+=("${workflow_path}")
  fi
done

workflow_text=""
for workflow_file in "${workflow_files[@]}"; do
  workflow_text+="$(<"${workflow_file}")"$'\n'
done

ensure_action() {
  local repo="$1"
  local sha="$2"
  local name="$3"
  local path="${cache_root}/${name}"

  if [[ -e "${path}" && ! -d "${path}/.git" ]]; then
    echo "refusing to use non-git action cache path: ${path}" >&2
    return 1
  fi

  if [[ ! -d "${path}/.git" ]]; then
    git clone --quiet "https://github.com/${repo}.git" "${path}"
  fi

  git -C "${path}" fetch --quiet origin
  git -C "${path}" checkout --quiet "${sha}"
}

workflow_uses_action() {
  local repo="$1"
  local sha="$2"
  grep -Eq "uses:[[:space:]]+${repo}(/[^@[:space:]]+)?@${sha}([[:space:]]|$)" <<< "${workflow_text}"
}

act_args=()
has_socket=false

for arg in "$@"; do
  if [[ "${arg}" == "--container-daemon-socket" || "${arg}" == --container-daemon-socket=* ]]; then
    has_socket=true
  fi
done

if [[ "${has_socket}" == "false" ]]; then
  # Colima exposes the Docker socket at /var/run/docker.sock inside the VM.
  # Passing the macOS ~/.colima path makes Docker try to mkdir a socket path
  # in the job container and fails before workflow steps start.
  act_args+=(--container-daemon-socket unix:///var/run/docker.sock)
fi

for entry in "${actions[@]}"; do
  IFS="|" read -r repo sha name <<< "${entry}"
  if ! workflow_uses_action "${repo}" "${sha}"; then
    continue
  fi
  ensure_action "${repo}" "${sha}" "${name}"
  act_args+=(--local-repository "${repo}@${sha}=${cache_root}/${name}")
done

cd "${repo_root}"
exec "${act_bin}" "${act_args[@]}" "$@"
