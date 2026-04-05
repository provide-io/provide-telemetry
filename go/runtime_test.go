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

func TestGetRuntimeConfigReturnsDefensiveCopy(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected non-nil config after setup")
	}
	cfg.ServiceName = "mutated-locally"

	again := GetRuntimeConfig()
	if again == nil {
		t.Fatal("expected non-nil config after second read")
	}
	if again.ServiceName == "mutated-locally" {
		t.Fatal("mutating GetRuntimeConfig result should not mutate runtime state")
	}
}

func TestCloneTelemetryConfigNilAndDeepCopy(t *testing.T) {
	if cloneTelemetryConfig(nil) != nil {
		t.Fatal("expected nil clone for nil input")
	}

	cfg := DefaultTelemetryConfig()
	cfg.Logging.OTLPHeaders["Authorization"] = "Bearer token"
	cfg.Logging.PrettyFields = []string{"event"}
	cfg.Logging.ModuleLevels["pkg"] = "DEBUG"
	cfg.EventSchema.RequiredKeys = []string{"request_id"}

	clone := cloneTelemetryConfig(cfg)
	if clone == nil {
		t.Fatal("expected non-nil clone")
	}

	clone.Logging.OTLPHeaders["Authorization"] = "changed"
	clone.Logging.PrettyFields[0] = "msg"
	clone.Logging.ModuleLevels["pkg"] = "INFO"
	clone.EventSchema.RequiredKeys[0] = "session_id"

	if cfg.Logging.OTLPHeaders["Authorization"] != "Bearer token" {
		t.Fatal("logging headers should be deep copied")
	}
	if cfg.Logging.PrettyFields[0] != "event" {
		t.Fatal("pretty fields should be deep copied")
	}
	if cfg.Logging.ModuleLevels["pkg"] != "DEBUG" {
		t.Fatal("module levels should be deep copied")
	}
	if cfg.EventSchema.RequiredKeys[0] != "request_id" {
		t.Fatal("required keys should be deep copied")
	}
}

func TestUpdateRuntimeConfigUpdatesField(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	err := UpdateRuntimeConfig(func(cfg *TelemetryConfig) {
		cfg.ServiceName = "updated-service"
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}
	if cfg.ServiceName != "updated-service" {
		t.Errorf("expected ServiceName=%q, got %q", "updated-service", cfg.ServiceName)
	}
}

func TestUpdateRuntimeConfigReappliesRuntimePolicies(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	err := UpdateRuntimeConfig(func(cfg *TelemetryConfig) {
		cfg.Sampling.LogsRate = 0.25
		cfg.Backpressure.LogsMaxSize = 17
		cfg.Exporter.LogsRetries = 2
		cfg.Exporter.LogsBackoffSeconds = 1.5
		cfg.Exporter.LogsTimeoutSeconds = 22
		cfg.Exporter.LogsFailOpen = false
		cfg.StrictSchema = true
		cfg.Logging.Level = "DEBUG"
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if got := GetSamplingPolicy(signalLogs).DefaultRate; got != 0.25 {
		t.Fatalf("sampling policy not updated, got %v", got)
	}
	if got := GetQueuePolicy().LogsMaxSize; got != 17 {
		t.Fatalf("queue policy not updated, got %d", got)
	}
	exporter := GetExporterPolicy(signalLogs)
	if exporter.Retries != 2 || exporter.BackoffSeconds != 1.5 || exporter.TimeoutSeconds != 22 || exporter.FailOpen {
		t.Fatalf("exporter policy not updated, got %+v", exporter)
	}
	if !_strictSchema {
		t.Fatal("strict schema flag not updated")
	}
}

func TestUpdateRuntimeConfigErrorWhenNotSetUp(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	err := UpdateRuntimeConfig(func(cfg *TelemetryConfig) {
		cfg.ServiceName = "should-not-apply"
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

	if got := GetSamplingPolicy(signalLogs).DefaultRate; got != 0.4 {
		t.Fatalf("sampling policy not reloaded, got %v", got)
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
