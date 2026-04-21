#!/usr/bin/env bash
set -euo pipefail

tag="${1:?Go module tag required (for example go/v0.4.0)}"

probe_dir="$(mktemp -d)"
trap 'rm -rf "${probe_dir}"' EXIT

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
probe_module="github.com/provide-io/provide-telemetry/go/releaseprobe"

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
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func TestTaggedModuleConsumerProbe(t *testing.T) {
	cfg := telemetry.DefaultTelemetryConfig()
	if cfg == nil || cfg.ServiceName == "" {
		t.Fatal("expected default telemetry config")
	}
}
EOF
    ;;
  go/internal/v*)
    module="github.com/provide-io/provide-telemetry/go/internal"
    version="${tag##*/}"
    cat >"${probe_dir}/probe_test.go" <<'EOF'
package probe

import (
	"testing"

	fingerprintcore "github.com/provide-io/provide-telemetry/go/internal/fingerprintcore"
	piicore "github.com/provide-io/provide-telemetry/go/internal/piicore"
	schemacore "github.com/provide-io/provide-telemetry/go/internal/schemacore"
)

func TestTaggedModuleConsumerProbe(t *testing.T) {
	if len(fingerprintcore.ShortHash12("release-probe")) != 12 {
		t.Fatal("expected 12-character fingerprint")
	}
	if !schemacore.ValidateSegmentFormat("release_probe") {
		t.Fatal("expected valid schema segment")
	}
	if !piicore.IsDefaultSensitiveKey("password") {
		t.Fatal("expected default sensitive key match")
	}
}
EOF
    ;;
  go/logger/v*)
    module="github.com/provide-io/provide-telemetry/go/logger"
    version="${tag##*/}"
    cat >"${probe_dir}/probe_test.go" <<'EOF'
package probe

import (
	"context"
	"testing"

	logger "github.com/provide-io/provide-telemetry/go/logger"
)

func TestTaggedModuleConsumerProbe(t *testing.T) {
	l := logger.GetLogger(context.Background(), "release.probe")
	if l == nil {
		t.Fatal("expected logger instance")
	}
}
EOF
    ;;
  go/tracer/v*)
    module="github.com/provide-io/provide-telemetry/go/tracer"
    version="${tag##*/}"
    cat >"${probe_dir}/probe_test.go" <<'EOF'
package probe

import (
	"context"
	"testing"

	tracer "github.com/provide-io/provide-telemetry/go/tracer"
)

func TestTaggedModuleConsumerProbe(t *testing.T) {
	ctx, span := tracer.GetTracer("release.probe").Start(context.Background(), "release.probe")
	if ctx == nil {
		t.Fatal("expected span context")
	}
	if span == nil || span.TraceID() == "" {
		t.Fatal("expected span with trace ID")
	}
	span.End()
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
    go/v*)
      assert_module_version \
        "github.com/provide-io/provide-telemetry/go/internal" \
        "$(required_version "${repo_root}/go/go.mod" "github.com/provide-io/provide-telemetry/go/internal")"
      ;;
    go/logger/v*)
      assert_module_version \
        "github.com/provide-io/provide-telemetry/go/internal" \
        "$(required_version "${repo_root}/go/logger/go.mod" "github.com/provide-io/provide-telemetry/go/internal")"
      ;;
    go/tracer/v*)
      assert_module_version \
        "github.com/provide-io/provide-telemetry/go/logger" \
        "$(required_version "${repo_root}/go/tracer/go.mod" "github.com/provide-io/provide-telemetry/go/logger")"
      ;;
  esac
  go test .
)

printf 'OK: consumer probe succeeded for %s@%s\n' "${module}" "${version}"
