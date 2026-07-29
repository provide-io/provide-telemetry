// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"testing"
)

// TracingEnabled/MetricsEnabled are the gates the optional OTel backend reads
// to decide whether to use or report a provider. They mean "no loaded config
// has switched this signal off", and must track a config across a
// shutdown/re-setup cycle.
func TestRuntimeGates_TrackSignalEnablement(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

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

	// Re-setup must keep them open: the flags this replaced latched off here.
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("re-setup failed: %v", err)
	}
	if !TracingEnabled() || !MetricsEnabled() {
		t.Fatal("gates did not reopen after re-setup")
	}
}

// A signal switched off by config must stay off across a re-setup that turns it
// back on and a shutdown that unloads the config — the gate follows the config
// that is actually loaded, nothing latches.
func TestRuntimeGates_ReopenWhenADisabledConfigIsUnloaded(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_TRACE_ENABLED", "false")
	t.Setenv("PROVIDE_METRICS_ENABLED", "false")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if TracingEnabled() || MetricsEnabled() {
		t.Fatal("gates open for signals the config switched off")
	}

	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}
	if !TracingEnabled() || !MetricsEnabled() {
		t.Fatal("gates stayed shut after the disabling config was unloaded")
	}
}

// Before SetupTelemetry there is no config, and Trace() emits — a host that
// installs its own SDK on the OTel globals and never calls SetupTelemetry must
// have that provider adopted rather than losing every span to the no-op tracer.
// The gates must say so.
func TestRuntimeGates_DefaultOpenBeforeSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if !TracingEnabled() || !MetricsEnabled() {
		t.Fatal("gates shut before setup; a host-installed provider would be ignored")
	}
	// The emit path's own enablement check must agree, or status and behaviour
	// diverge for exactly this pre-setup window.
	if !_runtimeTracingEnabled() || !_runtimeMetricsEnabled() {
		t.Fatal("emit-path enablement disagrees with the published gates")
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
