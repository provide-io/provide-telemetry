// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// parity_health_test.go validates that the Go HealthSnapshot struct has
// exactly the 25 canonical fields with correct types and zero-value defaults,
// matching the cross-language parity specification.

package telemetry

import (
	"reflect"
	"testing"
)

func TestParity_Health_CanonicalFieldCount(t *testing.T) {
	rt := reflect.TypeOf(HealthSnapshot{})
	if rt.NumField() != 25 {
		t.Errorf("HealthSnapshot: want 25 canonical fields, got %d", rt.NumField())
	}
}

func TestParity_Health_CanonicalFieldNames(t *testing.T) {
	expected := []string{
		// Logs (8)
		"LogsEmitted", "LogsDropped", "LogsExportFailures",
		"LogsRetries", "LogsExportLatencyMs", "LogsAsyncBlockingRisk",
		"LogsCircuitState", "LogsCircuitOpenCount",
		// Traces (8)
		"TracesEmitted", "TracesDropped", "TracesExportFailures",
		"TracesRetries", "TracesExportLatencyMs", "TracesAsyncBlockingRisk",
		"TracesCircuitState", "TracesCircuitOpenCount",
		// Metrics (8)
		"MetricsEmitted", "MetricsDropped", "MetricsExportFailures",
		"MetricsRetries", "MetricsExportLatencyMs", "MetricsAsyncBlockingRisk",
		"MetricsCircuitState", "MetricsCircuitOpenCount",
		// Global (1)
		"SetupError",
	}

	rt := reflect.TypeOf(HealthSnapshot{})
	for i, name := range expected {
		if i >= rt.NumField() {
			t.Errorf("missing field %s (index %d)", name, i)
			continue
		}
		got := rt.Field(i).Name
		if got != name {
			t.Errorf("field %d: want %s, got %s", i, name, got)
		}
	}
}

func TestParity_Health_DefaultCircuitStates(t *testing.T) {
	_resetHealth()
	_resetResiliencePolicies()
	t.Cleanup(_resetHealth)
	t.Cleanup(_resetResiliencePolicies)

	snap := GetHealthSnapshot()

	if snap.LogsCircuitState != "closed" {
		t.Errorf("LogsCircuitState: want closed, got %s", snap.LogsCircuitState)
	}
	if snap.TracesCircuitState != "closed" {
		t.Errorf("TracesCircuitState: want closed, got %s", snap.TracesCircuitState)
	}
	if snap.MetricsCircuitState != "closed" {
		t.Errorf("MetricsCircuitState: want closed, got %s", snap.MetricsCircuitState)
	}
}

func TestParity_Health_DefaultCountersZero(t *testing.T) {
	_resetHealth()
	_resetResiliencePolicies()
	t.Cleanup(_resetHealth)
	t.Cleanup(_resetResiliencePolicies)

	snap := GetHealthSnapshot()

	// All int64 counters must be zero.
	int64Fields := map[string]int64{
		"LogsEmitted":              snap.LogsEmitted,
		"LogsDropped":              snap.LogsDropped,
		"LogsExportFailures":       snap.LogsExportFailures,
		"LogsRetries":              snap.LogsRetries,
		"LogsAsyncBlockingRisk":    snap.LogsAsyncBlockingRisk,
		"LogsCircuitOpenCount":     snap.LogsCircuitOpenCount,
		"TracesEmitted":            snap.TracesEmitted,
		"TracesDropped":            snap.TracesDropped,
		"TracesExportFailures":     snap.TracesExportFailures,
		"TracesRetries":            snap.TracesRetries,
		"TracesAsyncBlockingRisk":  snap.TracesAsyncBlockingRisk,
		"TracesCircuitOpenCount":   snap.TracesCircuitOpenCount,
		"MetricsEmitted":           snap.MetricsEmitted,
		"MetricsDropped":           snap.MetricsDropped,
		"MetricsExportFailures":    snap.MetricsExportFailures,
		"MetricsRetries":           snap.MetricsRetries,
		"MetricsAsyncBlockingRisk": snap.MetricsAsyncBlockingRisk,
		"MetricsCircuitOpenCount":  snap.MetricsCircuitOpenCount,
	}
	for name, val := range int64Fields {
		if val != 0 {
			t.Errorf("%s: want 0, got %d", name, val)
		}
	}

	// All float64 latencies must be zero.
	float64Fields := map[string]float64{
		"LogsExportLatencyMs":    snap.LogsExportLatencyMs,
		"TracesExportLatencyMs":  snap.TracesExportLatencyMs,
		"MetricsExportLatencyMs": snap.MetricsExportLatencyMs,
	}
	for name, val := range float64Fields {
		if val != 0.0 {
			t.Errorf("%s: want 0.0, got %f", name, val)
		}
	}

	// SetupError must be empty.
	if snap.SetupError != "" {
		t.Errorf("SetupError: want empty, got %q", snap.SetupError)
	}
}

func TestParity_Health_PerSignalSymmetry(t *testing.T) {
	_resetHealth()
	_resetResiliencePolicies()
	t.Cleanup(_resetHealth)
	t.Cleanup(_resetResiliencePolicies)

	// Each signal must have the same 8 fields with matching suffixes.
	rt := reflect.TypeOf(HealthSnapshot{})
	prefixes := []string{"Logs", "Traces", "Metrics"}
	suffixes := []string{"Emitted", "Dropped", "ExportFailures", "Retries",
		"ExportLatencyMs", "AsyncBlockingRisk", "CircuitState", "CircuitOpenCount"}

	for _, prefix := range prefixes {
		for _, suffix := range suffixes {
			name := prefix + suffix
			_, found := rt.FieldByName(name)
			if !found {
				t.Errorf("missing expected field: %s", name)
			}
		}
	}
}
