// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"testing"
)

// TracingEnabled/MetricsEnabled are the gates the optional OTel backend reads
// to decide whether to use or report a provider. They must mean "set up and
// this signal is on" — not merely "configured on" — so a shut-down facade stops
// claiming a host's provider, and they must survive a shutdown/re-setup cycle.
func TestRuntimeGates_TrackSetupAndSignalEnablement(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if TracingEnabled() || MetricsEnabled() {
		t.Fatal("gates are open before setup")
	}

	t.Setenv("PROVIDE_TRACE_ENABLED", "true")
	t.Setenv("PROVIDE_METRICS_ENABLED", "true")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if !TracingEnabled() || !MetricsEnabled() {
		t.Fatal("gates closed after a setup that enabled both signals")
	}

	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}
	if TracingEnabled() || MetricsEnabled() {
		t.Fatal("gates still open after shutdown")
	}

	// Re-setup must reopen them: the flags this replaced latched off here.
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("re-setup failed: %v", err)
	}
	if !TracingEnabled() || !MetricsEnabled() {
		t.Fatal("gates did not reopen after re-setup")
	}
}

func TestRuntimeGates_FollowPerSignalDisablement(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_TRACE_ENABLED", "false")
	t.Setenv("PROVIDE_METRICS_ENABLED", "true")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if TracingEnabled() {
		t.Error("tracing gate open for a disabled signal")
	}
	if !MetricsEnabled() {
		t.Error("metrics gate closed for an enabled signal")
	}
}
