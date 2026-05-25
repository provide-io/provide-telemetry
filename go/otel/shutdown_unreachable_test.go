// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"fmt"
	"net"
	"testing"
	"time"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

// reserveClosedTCPPort binds a TCP socket on localhost, captures its
// allocated port, then closes the socket so subsequent connects refuse
// instantly. Mirrors the Python/TS regression helper.
func reserveClosedTCPPort(t *testing.T) int {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen failed: %v", err)
	}
	port := l.Addr().(*net.TCPAddr).Port
	if err := l.Close(); err != nil {
		t.Fatalf("close failed: %v", err)
	}
	return port
}

// TestShutdownTelemetry_BoundedWhenLogsEndpointUnreachable asserts that
// ShutdownTelemetry returns promptly even when the configured OTLP endpoint
// refuses connections. Unlike Python's OTel SDK (where BatchLogRecordProcessor.
// force_flush silently ignores its timeout argument and routinely blocks
// 7-10s), Go's SDK currently honours ctx-derived deadlines reasonably well
// on its own. The bounded deadline we apply in ShutdownTelemetry is
// defense-in-depth: an upstream SDK regression that makes Shutdown
// uncancellable would be caught here, and the explicit timeout also gives
// operators a single knob to tune (PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS)
// without depending on caller code passing a ctx with a deadline.
func TestShutdownTelemetry_BoundedWhenLogsEndpointUnreachable(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	port := reserveClosedTCPPort(t)
	endpoint := fmt.Sprintf("http://127.0.0.1:%d", port)
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
	// Aggressive deadline: pre-fix this would block on the OTel SDK's
	// internal retry chain for the full per-export timeout (10s default).
	t.Setenv("PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS", "1.0")
	// Disable trace/metrics so only the logs OTLP path is exercised — proves
	// disabling those alone is NOT sufficient (mirrors the Python regression).
	t.Setenv("PROVIDE_TRACE_ENABLED", "false")
	t.Setenv("PROVIDE_METRICS_ENABLED", "false")

	if _, err := telemetry.SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	// Emit a log via the global OTel logger so the BatchProcessor has a
	// record in its queue at shutdown time. Without this the queue is empty
	// and ForceFlush short-circuits — the bounding code we're testing never
	// fires.
	if telemetry.Logger != nil {
		telemetry.Logger.Info("shutdown_unreachable_probe")
	}

	start := time.Now()
	if err := telemetry.ShutdownTelemetry(context.Background()); err != nil {
		// Deadline-exceeded errors are acceptable here — the contract is
		// "return quickly", not "succeed silently". An err from a
		// canceled flush is the expected signal that bounding fired.
		t.Logf("shutdown returned error (expected under bounded deadline): %v", err)
	}
	elapsed := time.Since(start)
	// 1s deadline + scheduling noise. Pre-fix took ~10s on the same
	// hardware; the 3s threshold gives plenty of margin while still
	// catching any regression that lets shutdown hang.
	if elapsed > 3*time.Second {
		t.Errorf("ShutdownTelemetry took %v with unreachable endpoint, expected <3s", elapsed)
	}
}

// TestShutdownTelemetry_DisableLogOTLPSkipsProvider proves the per-signal
// kill switch — PROVIDE_LOG_OTLP_ENABLED=false — short-circuits the OTLP
// logger provider construction even when an endpoint is configured. With
// no provider attached the shutdown path has nothing to flush.
func TestShutdownTelemetry_DisableLogOTLPSkipsProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	port := reserveClosedTCPPort(t)
	endpoint := fmt.Sprintf("http://127.0.0.1:%d", port)
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
	t.Setenv("PROVIDE_LOG_OTLP_ENABLED", "false")
	t.Setenv("PROVIDE_TRACE_ENABLED", "false")
	t.Setenv("PROVIDE_METRICS_ENABLED", "false")

	if _, err := telemetry.SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if _otelLoggerProvider != nil {
		t.Fatal("expected OTLP logger provider to be nil when PROVIDE_LOG_OTLP_ENABLED=false")
	}

	start := time.Now()
	if err := telemetry.ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}
	elapsed := time.Since(start)
	if elapsed > time.Second {
		t.Errorf("ShutdownTelemetry took %v with OTLP logs disabled, expected <1s", elapsed)
	}
}
