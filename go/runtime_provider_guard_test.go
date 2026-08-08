// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Liveness-gated provider-immutability: UpdateConfig and ReloadRuntimeFromEnv
// may only reject provider-baked field changes while a live provider actually
// has them baked in. In fallback mode nothing is installed, so nothing is
// immutable — matching ReconfigureTelemetry and the Python facade.

package telemetry

import (
	"bytes"
	"context"
	"errors"
	"log/slog"
	"strings"
	"testing"
)

// installFakeProviders registers a fake backend reporting the given signals as
// live. Call after SetupTelemetry: registering marks the backend active without
// re-running setup.
func installFakeProviders(t *testing.T, providers SignalStatus) *_fakeBackend {
	t.Helper()
	backend := &_fakeBackend{}
	RegisterBackend("fake-guard", backend)
	t.Cleanup(func() { UnregisterBackend("fake-guard") })
	_setupMu.Lock()
	backend.providers = providers
	_setupMu.Unlock()
	return backend
}

// With no live provider, a provider-field difference is not an error:
// ReconfigureTelemetry accepts the same target, and the two facade methods on
// one runtime must not disagree on one input.
func TestUpdateConfig_AcceptsProviderFieldsInFallbackMode(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	base := DefaultTelemetryConfig()
	base.ServiceName = "fallback-mode"
	if _, err := SetupTelemetry(WithConfig(base)); err != nil {
		t.Fatalf("setup: %v", err)
	}

	target := cloneTelemetryConfig(base)
	target.ServiceName = "renamed-in-fallback"
	target.Tracing.Enabled = !base.Tracing.Enabled
	target.Sampling.LogsRate = 0.25

	rt := NewTelemetryRuntime(context.Background())
	updated, err := rt.UpdateConfig(context.Background(), target)
	if err != nil {
		t.Fatalf("UpdateConfig must accept provider fields with no live provider: %v", err)
	}
	if updated.Sampling.LogsRate != 0.25 {
		t.Fatalf("hot field not applied alongside: %v", updated.Sampling.LogsRate)
	}

	// The agreement itself: Reconfigure accepts the identical target.
	if _, err := rt.Reconfigure(context.Background(), target); err != nil {
		t.Fatalf("Reconfigure disagreed with UpdateConfig on the same input: %v", err)
	}
}

// The gate is per signal, exactly as in ReconfigureTelemetry: a live tracer
// does not freeze the logging exporter's fields.
func TestUpdateConfig_ProviderRejectionIsPerSignal(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	base := DefaultTelemetryConfig()
	base.ServiceName = "per-signal"
	if _, err := SetupTelemetry(WithConfig(base)); err != nil {
		t.Fatalf("setup: %v", err)
	}
	installFakeProviders(t, SignalStatus{Traces: true})

	rt := NewTelemetryRuntime(context.Background())

	logsTarget := cloneTelemetryConfig(base)
	logsTarget.Logging.OTLPEndpoint = "http://elsewhere:4318"
	if _, err := rt.UpdateConfig(context.Background(), logsTarget); err != nil {
		t.Fatalf("logging endpoint must be mutable while only a tracer is live: %v", err)
	}

	identityTarget := cloneTelemetryConfig(base)
	identityTarget.ServiceName = "renamed"
	_, err := rt.UpdateConfig(context.Background(), identityTarget)
	var immutable *ProviderImmutableError
	if !errors.As(err, &immutable) {
		t.Fatalf("identity is baked into every live provider's Resource; got %T: %v", err, err)
	}
}

// A live log provider freezes the fields baked into its exporter against env
// drift: reload must fail loudly instead of retargeting the config while
// records keep exporting to the old collector.
func TestReloadRuntimeFromEnv_RejectsLoggerProviderDrift(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup: %v", err)
	}
	installFakeProviders(t, SignalStatus{Logs: true})

	t.Setenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "http://drifted:4318")
	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "0.5")

	err := ReloadRuntimeFromEnv()
	var immutable *ProviderImmutableError
	if !errors.As(err, &immutable) {
		t.Fatalf("expected ProviderImmutableError, got %T: %v", err, err)
	}
	live := GetRuntimeConfig()
	if live.Logging.OTLPEndpoint == "http://drifted:4318" {
		t.Fatal("rejected reload still retargeted the logging endpoint")
	}
	if live.Sampling.LogsRate == 0.5 {
		t.Fatal("rejected reload must not half-apply hot fields either")
	}
}

// The OTLP enable flag is baked in with the endpoint: flipping it via env
// while the provider is live is the same lie about what is installed.
func TestReloadRuntimeFromEnv_RejectsOTLPEnabledFlipWithLiveProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup: %v", err)
	}
	installFakeProviders(t, SignalStatus{Logs: true})

	t.Setenv("PROVIDE_LOG_OTLP_ENABLED", "false")

	err := ReloadRuntimeFromEnv()
	var immutable *ProviderImmutableError
	if !errors.As(err, &immutable) {
		t.Fatalf("expected ProviderImmutableError, got %T: %v", err, err)
	}
}

// A live log provider only freezes its own baked fields: a hot-only env change
// must still reload cleanly.
func TestReloadRuntimeFromEnv_AllowsHotChangesWithLiveProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup: %v", err)
	}
	installFakeProviders(t, SignalStatus{Logs: true})

	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "0.5")

	if err := ReloadRuntimeFromEnv(); err != nil {
		t.Fatalf("hot-only drift must not trip the provider guard: %v", err)
	}
	if got := GetRuntimeConfig().Sampling.LogsRate; got != 0.5 {
		t.Fatalf("hot field not applied, got %v", got)
	}
}

// Without a live log provider nothing is baked in, and reload applies the new
// logging fields exactly as before.
func TestReloadRuntimeFromEnv_AppliesLoggerFieldsWithoutLiveProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup: %v", err)
	}

	t.Setenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "http://drifted:4318")

	if err := ReloadRuntimeFromEnv(); err != nil {
		t.Fatalf("reload must apply logging fields in fallback mode: %v", err)
	}
	if got := GetRuntimeConfig().Logging.OTLPEndpoint; got != "http://drifted:4318" {
		t.Fatalf("logging endpoint not applied, got %q", got)
	}
}

// Cold drift stays a warning — those fields are never applied by reload, so the
// operator hears about the restart instead of the reload failing.
func TestReloadRuntimeFromEnv_WarnsOnColdFieldDrift(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup: %v", err)
	}

	var buf bytes.Buffer
	prev := Logger()
	SetLogger(slog.New(slog.NewJSONHandler(&buf, nil)))
	t.Cleanup(func() { SetLogger(prev) })

	t.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "drifted-service")

	if err := ReloadRuntimeFromEnv(); err != nil {
		t.Fatalf("cold drift must not fail the reload: %v", err)
	}
	out := buf.String()
	if !strings.Contains(out, "runtime.cold_field_drift") ||
		!strings.Contains(out, "ServiceName") ||
		!strings.Contains(out, "restart required to apply") {
		t.Fatalf("expected cold-drift warning naming the field, got %q", out)
	}
}
