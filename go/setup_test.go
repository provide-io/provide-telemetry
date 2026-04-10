// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"sync"
	"testing"
)

// resetSetupState clears all setup state and related subsystems between tests.
func resetSetupState(t *testing.T) {
	t.Helper()
	_resetSetup()
	_resetSamplingPolicies()
	_resetQueuePolicy()
	_resetResiliencePolicies()
	_resetHealth()
}

func TestSetupTelemetryReturnsConfig(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}
	if cfg.ServiceName == "" {
		t.Error("expected non-empty ServiceName")
	}
}

func TestSetupTelemetryIdempotent(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg1, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("first setup failed: %v", err)
	}

	cfg2, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("second setup failed: %v", err)
	}

	if cfg1.ServiceName != cfg2.ServiceName {
		t.Error("expected equivalent config values on second call (idempotent)")
	}
}

func TestShutdownTelemetryResetsState(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}

	// After shutdown the config should be nil.
	cfg := GetRuntimeConfig()
	if cfg != nil {
		t.Error("expected nil config after shutdown")
	}
}

func TestShutdownThenSetupReinitialises(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("first setup failed: %v", err)
	}
	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}

	cfg, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("second setup failed: %v", err)
	}
	if cfg == nil {
		t.Fatal("expected non-nil config after re-setup")
	}
}

func TestSetupAppliesSamplingFromEnv(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "0.5")

	cfg, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if cfg.Sampling.LogsRate != 0.5 {
		t.Errorf("expected LogsRate=0.5, got %v", cfg.Sampling.LogsRate)
	}

	policy, err := GetSamplingPolicy(signalLogs)
	if err != nil {
		t.Fatal(err)
	}
	if policy.DefaultRate != 0.5 {
		t.Errorf("expected sampling policy DefaultRate=0.5, got %v", policy.DefaultRate)
	}
}

func TestSetupAppliesBackpressureFromEnv(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_BACKPRESSURE_LOGS_MAXSIZE", "42")

	cfg, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if cfg.Backpressure.LogsMaxSize != 42 {
		t.Errorf("expected LogsMaxSize=42, got %v", cfg.Backpressure.LogsMaxSize)
	}

	qp := GetQueuePolicy()
	if qp.LogsMaxSize != 42 {
		t.Errorf("expected queue policy LogsMaxSize=42, got %v", qp.LogsMaxSize)
	}
}

func TestSetupAppliesExporterPolicyFromEnv(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_EXPORTER_LOGS_RETRIES", "3")
	t.Setenv("PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS", "0.5")
	t.Setenv("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "9")
	t.Setenv("PROVIDE_EXPORTER_LOGS_FAIL_OPEN", "false")

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	policy := GetExporterPolicy(signalLogs)
	if policy.Retries != 3 || policy.BackoffSeconds != 0.5 || policy.TimeoutSeconds != 9 || policy.FailOpen {
		t.Fatalf("expected exporter policy from env, got %+v", policy)
	}
}

func TestSetupConcurrentOnlyOneInitialises(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	const goroutines = 10
	var wg sync.WaitGroup
	wg.Add(goroutines)

	for i := 0; i < goroutines; i++ {
		go func() {
			defer wg.Done()
			cfg, err := SetupTelemetry()
			if err != nil {
				t.Errorf("unexpected error in goroutine: %v", err)
			}
			if cfg == nil {
				t.Error("expected non-nil config from goroutine")
			}
		}()
	}
	wg.Wait()

	// Verify setup completed by checking we have a config.
	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Error("expected non-nil config after concurrent setup")
	}
}

func TestResetSetupClearsState(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	_resetSetup()

	if GetRuntimeConfig() != nil {
		t.Error("expected nil config after _resetSetup")
	}
}

func TestShutdownNoOpWhenNotSetUp(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// Calling shutdown when nothing is set up should be a no-op without error.
	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("expected nil error, got %v", err)
	}
}

func TestSetupTelemetryConfigFromEnvError(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// An invalid sampling rate causes ConfigFromEnv to return an error.
	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "invalid")

	cfg, err := SetupTelemetry()
	if err == nil {
		t.Fatal("expected error from SetupTelemetry with invalid env var")
	}
	if cfg != nil {
		t.Error("expected nil config on error")
	}
}

func TestSetupWithProviderOptions(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	sentinel := struct{ name string }{name: "test-tp"}
	cfg, err := SetupTelemetry(
		WithTracerProvider(sentinel),
		WithMeterProvider(sentinel),
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}
}

func TestSetupTelemetryIdempotentReturnsCopy(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg1, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("first setup failed: %v", err)
	}

	cfg2, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("second setup failed: %v", err)
	}

	// The idempotent path should return a clone, not the live pointer.
	if cfg1 == cfg2 {
		t.Error("expected different pointers from idempotent SetupTelemetry calls")
	}

	// Mutating the returned config should not affect internal state.
	cfg2.ServiceName = "mutated-via-setup-return"

	cfg3 := GetRuntimeConfig()
	if cfg3 == nil {
		t.Fatal("expected non-nil config")
	}
	if cfg3.ServiceName == "mutated-via-setup-return" {
		t.Fatal("mutating SetupTelemetry return value should not affect internal state")
	}
}

func TestSetupTelemetry_AllowBlockingInEventLoopRoundTrip(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_EXPORTER_LOGS_ALLOW_BLOCKING_EVENT_LOOP", "true")
	t.Setenv("PROVIDE_EXPORTER_TRACES_ALLOW_BLOCKING_EVENT_LOOP", "false")
	t.Setenv("PROVIDE_EXPORTER_METRICS_ALLOW_BLOCKING_EVENT_LOOP", "true")

	_, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	logs := GetExporterPolicy(signalLogs)
	if !logs.AllowBlockingInEventLoop {
		t.Error("expected logs AllowBlockingInEventLoop=true")
	}

	traces := GetExporterPolicy(signalTraces)
	if traces.AllowBlockingInEventLoop {
		t.Error("expected traces AllowBlockingInEventLoop=false")
	}

	metrics := GetExporterPolicy(signalMetrics)
	if !metrics.AllowBlockingInEventLoop {
		t.Error("expected metrics AllowBlockingInEventLoop=true")
	}
}
