// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"testing"
)

func TestReloadRuntimeFromEnvUpdatesConfig(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	t.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "reloaded-service")
	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "0.5")

	if err := ReloadRuntimeFromEnv(); err != nil {
		t.Fatalf("reload failed: %v", err)
	}

	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected non-nil config after reload")
	}
	if cfg.ServiceName == "reloaded-service" {
		t.Errorf("cold ServiceName should not change on hot reload, got %q", cfg.ServiceName)
	}
	if cfg.Sampling.LogsRate != 0.5 {
		t.Errorf("expected hot Sampling.LogsRate=0.5 after reload, got %v", cfg.Sampling.LogsRate)
	}
}

func TestReloadRuntimeFromEnvStrictEventNameWithoutStrictSchema(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	t.Setenv("PROVIDE_TELEMETRY_STRICT_SCHEMA", "false")
	t.Setenv("PROVIDE_TELEMETRY_STRICT_EVENT_NAME", "true")

	if err := ReloadRuntimeFromEnv(); err != nil {
		t.Fatalf("reload failed: %v", err)
	}
	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected runtime config after reload")
	}
	if cfg.StrictSchema {
		t.Fatal("strict schema should remain false when only strict event name is enabled")
	}
	if !cfg.EventSchema.StrictEventName {
		t.Fatal("strict event name should be enabled in runtime config after reload")
	}
	if !GetStrictSchema() {
		t.Fatal("effective strict schema should be enabled when strict event name is true")
	}

	if _, err := EventName("User", "Login", "Ok"); err == nil {
		t.Fatal("expected strict event-name validation to reject uppercase segments after reload")
	}
}

func TestReloadRuntimeFromEnvReappliesRuntimePolicies(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "0.4")
	t.Setenv("PROVIDE_BACKPRESSURE_LOGS_MAXSIZE", "9")
	t.Setenv("PROVIDE_EXPORTER_LOGS_RETRIES", "4")
	t.Setenv("PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS", "0.5")
	t.Setenv("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "7.5")
	t.Setenv("PROVIDE_EXPORTER_LOGS_FAIL_OPEN", "false")
	t.Setenv("PROVIDE_TELEMETRY_STRICT_SCHEMA", "true")

	if err := ReloadRuntimeFromEnv(); err != nil {
		t.Fatalf("reload failed: %v", err)
	}

	if p, err := GetSamplingPolicy(signalLogs); err != nil {
		t.Fatal(err)
	} else if p.DefaultRate != 0.4 {
		t.Fatalf("sampling policy not reloaded, got %v", p.DefaultRate)
	}
	if got := GetQueuePolicy().LogsMaxSize; got != 9 {
		t.Fatalf("queue policy not reloaded, got %d", got)
	}
	exporter := GetExporterPolicy(signalLogs)
	if exporter.Retries != 4 || exporter.BackoffSeconds != 0.5 || exporter.TimeoutSeconds != 7.5 || exporter.FailOpen {
		t.Fatalf("exporter policy not reloaded, got %+v", exporter)
	}
	if !_strictSchema {
		t.Fatal("strict schema flag not reloaded")
	}
}

func TestReloadRuntimeFromEnvErrorWhenNotSetUp(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if err := ReloadRuntimeFromEnv(); err == nil {
		t.Error("expected error when reloading without setup")
	}
}

func TestReloadRuntimeFromEnvConfigFromEnvError(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	// Inject an invalid env var so that ConfigFromEnv fails on reload.
	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "not-a-float")

	if err := ReloadRuntimeFromEnv(); err == nil {
		t.Error("expected error from ReloadRuntimeFromEnv with invalid env var")
	}
}

func TestReloadRuntimeFromEnvColdFieldDrift(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	// Change a cold field in the environment.
	t.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "drifted-service")

	// Reload should succeed, warn, and preserve the live cold field.
	if err := ReloadRuntimeFromEnv(); err != nil {
		t.Fatalf("reload failed: %v", err)
	}

	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}
	if cfg.ServiceName == "drifted-service" {
		t.Errorf("cold ServiceName should not change on hot reload, got %q", cfg.ServiceName)
	}
}

func TestReloadRuntimeFromEnvAllColdFieldsDrift(t *testing.T) {
	// Covers the Environment/Version/Tracing.Enabled/Metrics.Enabled drift branches.
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	t.Setenv("PROVIDE_TELEMETRY_ENV", "drifted-env")
	t.Setenv("PROVIDE_TELEMETRY_VERSION", "9.9.9")
	t.Setenv("PROVIDE_TRACE_ENABLED", "false")
	t.Setenv("PROVIDE_METRICS_ENABLED", "false")

	if err := ReloadRuntimeFromEnv(); err != nil {
		t.Fatalf("reload failed: %v", err)
	}

	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}
	if cfg.Environment == "drifted-env" {
		t.Errorf("cold Environment should not change on hot reload, got %q", cfg.Environment)
	}
	if !cfg.Tracing.Enabled {
		t.Error("cold Tracing.Enabled should not change on hot reload")
	}
	if !cfg.Metrics.Enabled {
		t.Error("cold Metrics.Enabled should not change on hot reload")
	}
}
