// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"math"
	"strings"
	"testing"
)

var _exporterDurationEnvVars = []string{
	"PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS",
	"PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS",
	"PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS",
	"PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS",
	"PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS",
	"PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS",
	"PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS",
}

// strconv.ParseFloat accepts every one of these spellings, so the env parser
// must refuse them itself; a bare `< 0` check let NaN and +Inf through.
func TestConfigFromEnv_RejectsNonFiniteExporterDurations(t *testing.T) {
	for _, name := range _exporterDurationEnvVars {
		for _, raw := range []string{"NaN", "nan", "Inf", "+Inf", "-Inf", "infinity"} {
			t.Run(name+"="+raw, func(t *testing.T) {
				t.Setenv(name, raw)
				_, err := ConfigFromEnv()
				if err == nil {
					t.Fatalf("expected %s=%s to be rejected", name, raw)
				}
				if !strings.Contains(err.Error(), name) {
					t.Fatalf("error does not name the variable: %v", err)
				}
			})
		}
	}
}

// The finite boundary is not over-tightened: zero and an ordinary value parse.
func TestConfigFromEnv_AcceptsFiniteExporterDurations(t *testing.T) {
	for _, name := range _exporterDurationEnvVars {
		for _, raw := range []string{"0", "0.25"} {
			t.Run(name+"="+raw, func(t *testing.T) {
				t.Setenv(name, raw)
				if _, err := ConfigFromEnv(); err != nil {
					t.Fatalf("expected %s=%s to parse: %v", name, raw, err)
				}
			})
		}
	}
}

func _exporterDurationFields() map[string]func(*TelemetryConfig, float64) {
	return map[string]func(*TelemetryConfig, float64){
		"LogsBackoffSeconds":    func(c *TelemetryConfig, v float64) { c.Exporter.LogsBackoffSeconds = v },
		"TracesBackoffSeconds":  func(c *TelemetryConfig, v float64) { c.Exporter.TracesBackoffSeconds = v },
		"MetricsBackoffSeconds": func(c *TelemetryConfig, v float64) { c.Exporter.MetricsBackoffSeconds = v },
		"LogsTimeoutSeconds":    func(c *TelemetryConfig, v float64) { c.Exporter.LogsTimeoutSeconds = v },
		"TracesTimeoutSeconds":  func(c *TelemetryConfig, v float64) { c.Exporter.TracesTimeoutSeconds = v },
		"MetricsTimeoutSeconds": func(c *TelemetryConfig, v float64) { c.Exporter.MetricsTimeoutSeconds = v },
	}
}

// WithConfig at setup now runs the same check ReconfigureTelemetry does, so
// every backoff and timeout refuses NaN, both infinities and negatives.
func TestSetupTelemetry_WithConfig_RejectsInvalidExporterDurations(t *testing.T) {
	for field, set := range _exporterDurationFields() {
		for _, v := range []float64{math.NaN(), math.Inf(1), math.Inf(-1), -0.5} {
			t.Run(field, func(t *testing.T) {
				resetSetupState(t)
				t.Cleanup(func() { resetSetupState(t) })
				mem := DefaultTelemetryConfig()
				set(mem, v)
				cfg, err := SetupTelemetry(WithConfig(mem))
				if err == nil || cfg != nil {
					t.Fatalf("expected %s=%g to be rejected, got cfg=%v err=%v", field, v, cfg, err)
				}
				if !strings.Contains(err.Error(), field) {
					t.Fatalf("error does not name the field: %v", err)
				}
				if _runtimeSetupDone() {
					t.Fatal("rejected config left the runtime set up")
				}
			})
		}
	}
}

// The shutdown deadline refuses only the non-finite values: the spec makes
// zero or negative the switch that turns library-side bounding off.
func TestSetupTelemetry_WithConfig_ShutdownTimeoutFiniteOnly(t *testing.T) {
	for _, v := range []float64{math.NaN(), math.Inf(1), math.Inf(-1)} {
		resetSetupState(t)
		mem := DefaultTelemetryConfig()
		mem.Exporter.LogsShutdownTimeoutSeconds = v
		if _, err := SetupTelemetry(WithConfig(mem)); err == nil ||
			!strings.Contains(err.Error(), "LogsShutdownTimeoutSeconds") {
			t.Fatalf("expected LogsShutdownTimeoutSeconds=%g to be rejected, got %v", v, err)
		}
	}
	for _, v := range []float64{-1, 0, 2.5} {
		resetSetupState(t)
		mem := DefaultTelemetryConfig()
		mem.Exporter.LogsShutdownTimeoutSeconds = v
		if _, err := SetupTelemetry(WithConfig(mem)); err != nil {
			t.Fatalf("expected LogsShutdownTimeoutSeconds=%g to be accepted: %v", v, err)
		}
	}
	resetSetupState(t)
}

// The rest of the hot-reloadable blocks are covered by the same check.
func TestSetupTelemetry_WithConfig_RejectsNegativeLimits(t *testing.T) {
	cases := map[string]func(*TelemetryConfig){
		"Backpressure.LogsMaxSize": func(c *TelemetryConfig) { c.Backpressure.LogsMaxSize = -1 },
		"Security.MaxAttrCount":    func(c *TelemetryConfig) { c.Security.MaxAttrCount = -1 },
		"Logging.PIIMaxDepth":      func(c *TelemetryConfig) { c.Logging.PIIMaxDepth = -1 },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			resetSetupState(t)
			t.Cleanup(func() { resetSetupState(t) })
			mem := DefaultTelemetryConfig()
			mutate(mem)
			if _, err := SetupTelemetry(WithConfig(mem)); err == nil {
				t.Fatalf("expected %s=-1 to be rejected", name)
			}
		})
	}
}

func TestUpdateRuntimeConfig_RejectsNonFiniteShutdownTimeout(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	if _, err := SetupTelemetry(WithConfig(DefaultTelemetryConfig())); err != nil {
		t.Fatal(err)
	}
	exporter := DefaultTelemetryConfig().Exporter
	exporter.LogsShutdownTimeoutSeconds = math.Inf(1)
	if err := UpdateRuntimeConfig(RuntimeOverrides{Exporter: &exporter}); err == nil {
		t.Fatal("expected +Inf shutdown timeout to be rejected")
	}
	if got := GetRuntimeConfig().Exporter.LogsShutdownTimeoutSeconds; got != 5.0 {
		t.Fatalf("rejected override was applied: %g", got)
	}
}
