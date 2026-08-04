// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Exporter retries carry the same ceiling in every language: TypeScript's
// setupTelemetry rejects retries above MAX_EXPORT_ATTEMPTS-1 (100), so the
// same environment value must not boot a Go service and crash a TS one.

package telemetry

import (
	"context"
	"errors"
	"strings"
	"testing"
)

func TestConfigFromEnv_RejectsRetriesAboveCeiling(t *testing.T) {
	for _, envVar := range []string{
		"PROVIDE_EXPORTER_LOGS_RETRIES",
		"PROVIDE_EXPORTER_TRACES_RETRIES",
		"PROVIDE_EXPORTER_METRICS_RETRIES",
	} {
		t.Run(envVar, func(t *testing.T) {
			resetSetupState(t)
			t.Cleanup(func() { resetSetupState(t) })
			t.Setenv(envVar, "101")

			_, err := ConfigFromEnv()
			if err == nil {
				t.Fatal("expected retries above 100 to be rejected")
			}
			if !strings.Contains(err.Error(), envVar) ||
				!strings.Contains(err.Error(), "must be at most 100, got 101") {
				t.Fatalf("error must name the variable and the ceiling, got %q", err.Error())
			}
		})
	}
}

func TestConfigFromEnv_AcceptsRetriesAtCeiling(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	t.Setenv("PROVIDE_EXPORTER_LOGS_RETRIES", "100")
	t.Setenv("PROVIDE_EXPORTER_TRACES_RETRIES", "100")
	t.Setenv("PROVIDE_EXPORTER_METRICS_RETRIES", "100")

	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("100 is the ceiling and must be accepted: %v", err)
	}
	if cfg.Exporter.LogsRetries != 100 || cfg.Exporter.TracesRetries != 100 || cfg.Exporter.MetricsRetries != 100 {
		t.Fatalf("retries at ceiling not applied: %+v", cfg.Exporter)
	}
}

func TestUpdateRuntimeConfig_RejectsRetriesAboveCeiling(t *testing.T) {
	fields := map[string]func(e *ExporterPolicyConfig){
		_fieldLogsRetries:    func(e *ExporterPolicyConfig) { e.LogsRetries = 101 },
		_fieldTracesRetries:  func(e *ExporterPolicyConfig) { e.TracesRetries = 101 },
		_fieldMetricsRetries: func(e *ExporterPolicyConfig) { e.MetricsRetries = 101 },
	}
	for field, mutate := range fields {
		t.Run(field, func(t *testing.T) {
			resetSetupState(t)
			t.Cleanup(func() { resetSetupState(t) })
			if _, err := SetupTelemetry(); err != nil {
				t.Fatalf("setup: %v", err)
			}

			exporter := GetRuntimeConfig().Exporter
			mutate(&exporter)
			err := UpdateRuntimeConfig(RuntimeOverrides{Exporter: &exporter})
			if err == nil {
				t.Fatal("expected retries above 100 to be rejected")
			}
			if !strings.Contains(err.Error(), "RuntimeOverrides.Exporter."+field) ||
				!strings.Contains(err.Error(), "must be at most 100, got 101") {
				t.Fatalf("error must name the field and the ceiling, got %q", err.Error())
			}
		})
	}
}

func TestUpdateRuntimeConfig_AcceptsRetriesAtCeiling(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup: %v", err)
	}

	exporter := GetRuntimeConfig().Exporter
	exporter.LogsRetries = 100
	if err := UpdateRuntimeConfig(RuntimeOverrides{Exporter: &exporter}); err != nil {
		t.Fatalf("100 is the ceiling and must be accepted: %v", err)
	}
	if got := GetRuntimeConfig().Exporter.LogsRetries; got != 100 {
		t.Fatalf("retries at ceiling not applied, got %d", got)
	}
}

// SetExporterPolicy bypasses config validation, so the retry loop itself
// clamps: an unvalidated policy must not buy more than _maxExportAttempts
// tries.
func TestRunWithResilience_ClampsAttemptsAtCeiling(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	SetExporterPolicy(signalLogs, ExporterPolicy{Retries: 250})

	calls := 0
	err := RunWithResilience(context.Background(), signalLogs, func(context.Context) error {
		calls++
		return errors.New("always failing exporter")
	})
	if err == nil {
		t.Fatal("expected the exhausted retry loop to surface the failure")
	}
	if calls != _maxExportAttempts {
		t.Fatalf("expected exactly %d attempts (clamped), got %d", _maxExportAttempts, calls)
	}
}
