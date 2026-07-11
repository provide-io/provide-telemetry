# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#
#!/usr/bin/env bash
# Local OSS-Fuzz helper wrapper (no Google cloud onboarding).
#
# Usage:
#   ./scripts/oss-fuzz-local.sh build
#   ./scripts/oss-fuzz-local.sh run FuzzValidateRate
#   ./scripts/oss-fuzz-local.sh run FuzzMaskEndpointURL -- -max_total_time=60
#   ./scripts/oss-fuzz-local.sh list
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OSS_FUZZ_DIR="${OSS_FUZZ_DIR:-}"
if [[ -z "$OSS_FUZZ_DIR" ]]; then
  if [[ -d /tmp/oss-fuzz/infra ]]; then
    OSS_FUZZ_DIR=/tmp/oss-fuzz
  else
    OSS_FUZZ_DIR="${HOME}/src/oss-fuzz"
  fi
fi
PROJECT=provide-telemetry
PROJ_DIR="${OSS_FUZZ_DIR}/projects/${PROJECT}"

usage() {
  sed -n '2,9p' "$0" | sed 's/^# \?//'
  exit 1
}

ensure_oss_fuzz() {
  if [[ ! -d "${OSS_FUZZ_DIR}/infra" ]]; then
    echo "cloning google/oss-fuzz → ${OSS_FUZZ_DIR}"
    mkdir -p "$(dirname "$OSS_FUZZ_DIR")"
    git clone --depth 1 https://github.com/google/oss-fuzz.git "$OSS_FUZZ_DIR"
  fi
}

install_project() {
  ensure_oss_fuzz
  mkdir -p "$PROJ_DIR"
  cp "$ROOT/infra/oss-fuzz/project.yaml" \
     "$ROOT/infra/oss-fuzz/Dockerfile" \
     "$ROOT/infra/oss-fuzz/build.sh" \
     "$PROJ_DIR/"
  chmod +x "$PROJ_DIR/build.sh"
  echo "installed recipe → $PROJ_DIR"
}

cmd="${1:-}"
shift || true

case "$cmd" in
  build)
    install_project
    cd "$OSS_FUZZ_DIR"
    python3 infra/helper.py build_image --no-pull "$PROJECT" 2>/dev/null \
      || python3 infra/helper.py build_image "$PROJECT"
    python3 infra/helper.py build_fuzzers --sanitizer address --engine libfuzzer \
      "$PROJECT" "$ROOT"
    echo "binaries:"
    ls -la "build/out/${PROJECT}/" || true
    ;;
  run)
    fuzzer="${1:?fuzzer name required, e.g. FuzzValidateRate}"
    shift || true
    # remaining args after optional --
    if [[ "${1:-}" == "--" ]]; then shift; fi
    ensure_oss_fuzz
    if [[ ! -x "${OSS_FUZZ_DIR}/build/out/${PROJECT}/${fuzzer}" ]]; then
      echo "missing ${fuzzer}; run: $0 build" >&2
      exit 1
    fi
    cd "$OSS_FUZZ_DIR"
    python3 infra/helper.py run_fuzzer "$PROJECT" "$fuzzer" -- \
      -max_total_time="${MAX_TOTAL_TIME:-30}" -print_final_stats=1 "$@"
    ;;
  list)
    ensure_oss_fuzz
    ls -la "${OSS_FUZZ_DIR}/build/out/${PROJECT}/" 2>/dev/null \
      || echo "no build yet; run: $0 build"
    ;;
  install)
    install_project
    ;;
  *)
    usage
    ;;
esac
