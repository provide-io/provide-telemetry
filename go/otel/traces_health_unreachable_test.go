// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"fmt"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

// TestTracesHealthReportsAnUnreachableCollector pins what a host may rely on
// when it lets this module build the TracerProvider: a span batch the
// collector refuses is counted in TracesExportFailures, and the traces circuit
// is a real state rather than "unknown". A host that builds its own provider
// gets neither, because its exporter never runs through RunWithResilience.
func TestTracesHealthReportsAnUnreachableCollector(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", fmt.Sprintf("http://127.0.0.1:%d", reserveClosedTCPPort(t)))
	t.Setenv("PROVIDE_EXPORTER_TRACES_RETRIES", "0")
	t.Setenv("PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS", "1")
	t.Setenv("PROVIDE_LOG_LEVEL", "CRITICAL")
	t.Setenv("PROVIDE_METRICS_ENABLED", "false")

	if _, err := telemetry.SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	before := telemetry.GetHealthSnapshot()

	_ = telemetry.Trace(context.Background(), "unreachable.probe", func(context.Context) error { return nil })
	_ = telemetry.FlushTelemetry(context.Background())

	after := telemetry.GetHealthSnapshot()
	if got := after.TracesExportFailures - before.TracesExportFailures; got < 1 {
		t.Fatalf("TracesExportFailures rose by %d, want at least 1", got)
	}
	switch after.TracesCircuitState {
	case "closed", "open", "half-open":
	default:
		t.Fatalf("TracesCircuitState = %q, want a real circuit state", after.TracesCircuitState)
	}
	_ = telemetry.ShutdownTelemetry(context.Background())
}
