// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"testing"
)

func TestGetRuntimeConfigNilBeforeSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if cfg := GetRuntimeConfig(); cfg != nil {
		t.Errorf("expected nil before setup, got %+v", cfg)
	}
}

func TestGetRuntimeConfigNonNilAfterSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if cfg := GetRuntimeConfig(); cfg == nil {
		t.Error("expected non-nil config after setup")
	}
}

func TestUpdateRuntimeConfigUpdatesField(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	err := UpdateRuntimeConfig(RuntimeOverrides{
		Sampling: &SamplingConfig{LogsRate: 0.5, TracesRate: 1.0, MetricsRate: 1.0},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}
	if cfg.Sampling.LogsRate != 0.5 {
		t.Errorf("expected Sampling.LogsRate=0.5, got %v", cfg.Sampling.LogsRate)
	}
}

func TestUpdateRuntimeConfigReappliesRuntimePolicies(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	err := UpdateRuntimeConfig(RuntimeOverrides{
		Sampling:     &SamplingConfig{LogsRate: 0.25, TracesRate: 1.0, MetricsRate: 1.0},
		Backpressure: &BackpressureConfig{LogsMaxSize: 17},
		Exporter: &ExporterPolicyConfig{
			LogsRetries:        2,
			LogsBackoffSeconds: 1.5,
			LogsTimeoutSeconds: 22,
			LogsFailOpen:       false,
		},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if p, err := GetSamplingPolicy(signalLogs); err != nil {
		t.Fatal(err)
	} else if p.DefaultRate != 0.25 {
		t.Fatalf("sampling policy not updated, got %v", p.DefaultRate)
	}
	if got := GetQueuePolicy().LogsMaxSize; got != 17 {
		t.Fatalf("queue policy not updated, got %d", got)
	}
	exporter := GetExporterPolicy(signalLogs)
	if exporter.Retries != 2 || exporter.BackoffSeconds != 1.5 || exporter.TimeoutSeconds != 22 || exporter.FailOpen {
		t.Fatalf("exporter policy not updated, got %+v", exporter)
	}
}

func TestUpdateRuntimeConfigErrorWhenNotSetUp(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	err := UpdateRuntimeConfig(RuntimeOverrides{
		Sampling: &SamplingConfig{LogsRate: 0.5, TracesRate: 1.0, MetricsRate: 1.0},
	})
	if err == nil {
		t.Error("expected error when calling UpdateRuntimeConfig without setup")
	}
}

func TestReloadRuntimeFromEnvUpdatesConfig(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	t.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "reloaded-service")

	if err := ReloadRuntimeFromEnv(); err != nil {
		t.Fatalf("reload failed: %v", err)
	}

	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected non-nil config after reload")
	}
	if cfg.ServiceName != "reloaded-service" {
		t.Errorf("expected ServiceName=%q after reload, got %q", "reloaded-service", cfg.ServiceName)
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

func TestReconfigureTelemetryRerunsSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg1, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("first setup failed: %v", err)
	}

	t.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "reconfigured-service")

	cfg2, err := ReconfigureTelemetry(context.Background())
	if err != nil {
		t.Fatalf("reconfigure failed: %v", err)
	}
	if cfg2 == nil {
		t.Fatal("expected non-nil config after reconfigure")
	}
	if cfg2 == cfg1 {
		t.Error("expected a fresh config pointer after reconfigure")
	}
	if cfg2.ServiceName != "reconfigured-service" {
		t.Errorf("expected ServiceName=%q after reconfigure, got %q", "reconfigured-service", cfg2.ServiceName)
	}
}

func TestRuntimeOverridesAppliesHotFields(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	depth := 12
	err := UpdateRuntimeConfig(RuntimeOverrides{
		Sampling:     &SamplingConfig{LogsRate: 0.1, TracesRate: 0.2, MetricsRate: 0.3},
		Backpressure: &BackpressureConfig{LogsMaxSize: 100, TracesMaxSize: 200, MetricsMaxSize: 300},
		Security:     &SecurityConfig{MaxAttrValueLength: 512, MaxAttrCount: 32, MaxNestingDepth: 4},
		SLO:          &SLOConfig{EnableREDMetrics: true, EnableUSEMetrics: true, IncludeErrorTaxonomy: false},
		PIIMaxDepth:  &depth,
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}
	if cfg.Sampling.LogsRate != 0.1 || cfg.Sampling.TracesRate != 0.2 || cfg.Sampling.MetricsRate != 0.3 {
		t.Fatalf("sampling not applied: %+v", cfg.Sampling)
	}
	if cfg.Backpressure.LogsMaxSize != 100 || cfg.Backpressure.TracesMaxSize != 200 || cfg.Backpressure.MetricsMaxSize != 300 {
		t.Fatalf("backpressure not applied: %+v", cfg.Backpressure)
	}
	if cfg.Security.MaxAttrValueLength != 512 || cfg.Security.MaxAttrCount != 32 || cfg.Security.MaxNestingDepth != 4 {
		t.Fatalf("security not applied: %+v", cfg.Security)
	}
	if !cfg.SLO.EnableREDMetrics || !cfg.SLO.EnableUSEMetrics || cfg.SLO.IncludeErrorTaxonomy {
		t.Fatalf("SLO not applied: %+v", cfg.SLO)
	}
	if cfg.Logging.PIIMaxDepth != 12 {
		t.Fatalf("PIIMaxDepth not applied: got %d", cfg.Logging.PIIMaxDepth)
	}
}

func TestRuntimeOverridesPreservesUnsetFields(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	before := GetRuntimeConfig()
	if before == nil {
		t.Fatal("expected non-nil config")
	}

	// Apply an empty overrides — nothing should change.
	err := UpdateRuntimeConfig(RuntimeOverrides{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	after := GetRuntimeConfig()
	if after == nil {
		t.Fatal("expected non-nil config")
	}

	// All fields should be preserved.
	if after.Sampling != before.Sampling {
		t.Errorf("Sampling changed: before=%+v after=%+v", before.Sampling, after.Sampling)
	}
	if after.Backpressure != before.Backpressure {
		t.Errorf("Backpressure changed: before=%+v after=%+v", before.Backpressure, after.Backpressure)
	}
	if after.Security != before.Security {
		t.Errorf("Security changed: before=%+v after=%+v", before.Security, after.Security)
	}
	if after.SLO != before.SLO {
		t.Errorf("SLO changed: before=%+v after=%+v", before.SLO, after.SLO)
	}
	if after.ServiceName != before.ServiceName {
		t.Errorf("ServiceName changed: before=%q after=%q", before.ServiceName, after.ServiceName)
	}
	if after.Logging.PIIMaxDepth != before.Logging.PIIMaxDepth {
		t.Errorf("PIIMaxDepth changed: before=%d after=%d", before.Logging.PIIMaxDepth, after.Logging.PIIMaxDepth)
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

	// Reload should succeed (cold fields are still applied, just warned).
	if err := ReloadRuntimeFromEnv(); err != nil {
		t.Fatalf("reload failed: %v", err)
	}

	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}
	// The cold field value IS applied to the in-memory config (reload replaces everything).
	if cfg.ServiceName != "drifted-service" {
		t.Errorf("expected ServiceName=%q after reload, got %q", "drifted-service", cfg.ServiceName)
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
	if cfg.Environment != "drifted-env" {
		t.Errorf("expected Environment=%q, got %q", "drifted-env", cfg.Environment)
	}
}
