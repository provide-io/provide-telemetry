// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import "testing"

func TestSetupTelemetry_WithConfig_InvalidRate(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	mem := DefaultTelemetryConfig()
	mem.Tracing.SampleRate = 2.0
	cfg, err := SetupTelemetry(WithConfig(mem))
	if err == nil {
		t.Fatal("expected error for invalid SampleRate")
	}
	if cfg != nil {
		t.Error("expected nil config on validation error")
	}
}

func TestSetupTelemetry_WithConfig_InvalidSamplingAndFormat(t *testing.T) {
	cases := []struct {
		name string
		mut  func(*TelemetryConfig)
	}{
		{"logs_rate", func(c *TelemetryConfig) { c.Sampling.LogsRate = -0.1 }},
		{"traces_rate", func(c *TelemetryConfig) { c.Sampling.TracesRate = 1.5 }},
		{"metrics_rate", func(c *TelemetryConfig) { c.Sampling.MetricsRate = -1 }},
		{"format", func(c *TelemetryConfig) { c.Logging.Format = "xml" }},
		{"level", func(c *TelemetryConfig) { c.Logging.Level = "LOUD" }},
		{"logs_retries", func(c *TelemetryConfig) { c.Exporter.LogsRetries = 101 }},
		{"traces_retries", func(c *TelemetryConfig) { c.Exporter.TracesRetries = 101 }},
		{"metrics_retries", func(c *TelemetryConfig) { c.Exporter.MetricsRetries = 101 }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			resetSetupState(t)
			t.Cleanup(func() { resetSetupState(t) })
			mem := DefaultTelemetryConfig()
			tc.mut(mem)
			cfg, err := SetupTelemetry(WithConfig(mem))
			if err == nil {
				t.Fatalf("expected validation error for %s", tc.name)
			}
			if cfg != nil {
				t.Error("expected nil config on validation error")
			}
		})
	}
}

// The ceiling boundary: 100 is the largest accepted retries value at setup,
// and the rejection names the offending field so a polyglot operator can map
// it back to the shared PROVIDE_EXPORTER_*_RETRIES contract.
func TestSetupTelemetry_WithConfig_RetriesCeilingBoundary(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	mem := DefaultTelemetryConfig()
	mem.Exporter.LogsRetries = 100
	mem.Exporter.TracesRetries = 100
	mem.Exporter.MetricsRetries = 100
	if _, err := SetupTelemetry(WithConfig(mem)); err != nil {
		t.Fatalf("retries=100 must be accepted at setup: %v", err)
	}

	resetSetupState(t)
	over := DefaultTelemetryConfig()
	over.Exporter.LogsRetries = 101
	_, err := SetupTelemetry(WithConfig(over))
	if err == nil {
		t.Fatal("retries=101 must be rejected at setup")
	}
	want := "Exporter.LogsRetries must be at most 100, got 101"
	if err.Error() != want {
		t.Fatalf("error = %q, want %q", err.Error(), want)
	}
}
