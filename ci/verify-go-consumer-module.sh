#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.

set -euo pipefail

tag="${1:?Go module tag required (for example go/v0.4.0)}"

probe_dir="$(mktemp -d)"
trap 'rm -rf "${probe_dir}"' EXIT

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
probe_module="github.com/provide-io/provide-telemetry/go/releaseprobe"

assert_module_version() {
  local module_path="${1:?module path required}"
  local expected_version="${2:?expected version required}"
  local actual_version

  actual_version="$(go list -m -f '{{.Version}}' "${module_path}")"
  if [ "${actual_version}" != "${expected_version}" ]; then
    printf 'resolved %s as %s, expected %s\n' "${module_path}" "${actual_version}" "${expected_version}" >&2
    exit 1
  fi
}

case "${tag}" in
  go/v*)
    module="github.com/provide-io/provide-telemetry/go"
    version="${tag##*/}"
    cat >"${probe_dir}/probe_test.go" <<'EOF'
package probe

import (
	"context"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func TestTaggedModuleConsumerProbe(t *testing.T) {
	cfg := telemetry.DefaultTelemetryConfig()
	if cfg == nil || cfg.ServiceName == "" {
		t.Fatal("expected default telemetry config")
	}
	if logger.GetLogger(context.Background(), "release.probe") == nil {
		t.Fatal("expected logger package to be importable from the root module")
	}
	// The tracer lives in the root package: go/tracer was a standalone parallel
	// copy that nothing imported, and it was removed in 0.6.0. Reach it through
	// GetTracer / SetDefaultTracer, which is what a consumer now does.
	ctx, span := telemetry.GetTracer("release.probe").Start(context.Background(), "release.probe")
	if ctx == nil || span == nil || span.TraceID() == "" {
		t.Fatal("expected the root package tracer to be usable")
	}
	span.End()
}
EOF
    ;;
  go/otel/v*)
    module="github.com/provide-io/provide-telemetry/go/otel"
    version="${tag##*/}"
    cat >"${probe_dir}/probe_test.go" <<'EOF'
package probe

import (
	"context"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
	_ "github.com/provide-io/provide-telemetry/go/otel"
)

func TestTaggedModuleConsumerProbe(t *testing.T) {
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")

	cfg, err := telemetry.SetupTelemetry()
	if err != nil {
		t.Fatalf("expected setup to succeed with optional backend registered: %v", err)
	}
	if !cfg.Tracing.Enabled || !cfg.Metrics.Enabled {
		t.Fatal("expected telemetry config to remain enabled")
	}
	status := telemetry.GetRuntimeStatus()
	if !status.SetupDone || (!status.Providers.Logs && !status.Providers.Traces && !status.Providers.Metrics) {
		t.Fatalf("expected at least one provider to be active, got %+v", status.Providers)
	}
	if err := telemetry.ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("expected shutdown to succeed: %v", err)
	}
}
EOF
    ;;
  *)
    printf 'unsupported Go module tag: %s\n' "${tag}" >&2
    exit 1
    ;;
esac

(
  cd "${probe_dir}"
  go mod init "${probe_module}"
  go get "${module}@${version}"
  resolved_version="$(go list -m -f '{{.Version}}' "${module}")"
  if [ "${resolved_version}" != "${version}" ]; then
    printf 'resolved %s as %s, expected %s\n' "${module}" "${resolved_version}" "${version}" >&2
    exit 1
  fi
  case "${tag}" in
    go/otel/v*)
      assert_module_version \
        "github.com/provide-io/provide-telemetry/go" \
        "v$(cat "${repo_root}/go/VERSION")"
      ;;
  esac
  # Populate go.sum with hashes for transitive deps imported by the
  # tagged module's sub-packages (e.g. go/internal/piicore pulls in
  # golang.org/x/text). go get only adds direct deps,
  # so without this 'go test .' fails with "missing go.sum entry".
  #
  # The proxy is used from here on, deliberately. GOPROXY=direct is the point
  # of this job for the *tagged module* — the go get above proves a consumer
  # can resolve it straight from VCS. It is not the point for the rest of the
  # graph: go mod tidy resolves the test dependencies of every dependency, so
  # with direct it fetches each from its own origin host. That reached
  # gonum.org via grpc's internal test utils and timed out after sixteen
  # minutes, failing a release for a host that has nothing to do with us.
  GOPROXY="https://proxy.golang.org,direct" go mod tidy
  GOPROXY="https://proxy.golang.org,direct" go test .
)

printf 'OK: consumer probe succeeded for %s@%s\n' "${module}" "${version}"
