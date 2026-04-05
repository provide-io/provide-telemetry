// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"sync"
	"testing"
)

func TestGetHealthSnapshot_InitiallyZero(t *testing.T) {
	_resetHealth()
	_resetResiliencePolicies()
	t.Cleanup(_resetHealth)
	t.Cleanup(_resetResiliencePolicies)

	snap := GetHealthSnapshot()
	// Circuit states default to "closed" (not zero-value ""), so we cannot
	// compare against a bare HealthSnapshot{}. Check key counters instead.
	if snap.LogsEmitted != 0 || snap.TracesEmitted != 0 || snap.MetricsEmitted != 0 {
		t.Errorf("expected zeroed emitted counters, got %+v", snap)
	}
	if snap.LogsCircuitState != "closed" || snap.TracesCircuitState != "closed" || snap.MetricsCircuitState != "closed" {
		t.Errorf("expected all circuit states closed, got logs=%s traces=%s metrics=%s",
			snap.LogsCircuitState, snap.TracesCircuitState, snap.MetricsCircuitState)
	}
	if snap.SetupError != "" {
		t.Errorf("expected empty SetupError, got %q", snap.SetupError)
	}
}

func TestIncEmitted(t *testing.T) {
	_resetHealth()
	t.Cleanup(_resetHealth)

	_incEmitted(signalLogs)
	_incEmitted(signalLogs)
	_incEmitted(signalTraces)
	_incEmitted(signalMetrics)
	snap := GetHealthSnapshot()
	if snap.LogsEmitted != 2 {
		t.Errorf("LogsEmitted: want 2, got %d", snap.LogsEmitted)
	}
	if snap.TracesEmitted != 1 {
		t.Errorf("TracesEmitted: want 1, got %d", snap.TracesEmitted)
	}
	if snap.MetricsEmitted != 1 {
		t.Errorf("MetricsEmitted: want 1, got %d", snap.MetricsEmitted)
	}
}

func TestIncDropped(t *testing.T) {
	_resetHealth()
	t.Cleanup(_resetHealth)

	_incDroppedHealth(signalLogs)
	_incDroppedHealth(signalTraces)
	_incDroppedHealth(signalMetrics)
	snap := GetHealthSnapshot()
	if snap.LogsDropped != 1 {
		t.Errorf("LogsDropped: want 1, got %d", snap.LogsDropped)
	}
	if snap.TracesDropped != 1 {
		t.Errorf("TracesDropped: want 1, got %d", snap.TracesDropped)
	}
	if snap.MetricsDropped != 1 {
		t.Errorf("MetricsDropped: want 1, got %d", snap.MetricsDropped)
	}
}

func TestIncExportFailures(t *testing.T) {
	_resetHealth()
	t.Cleanup(_resetHealth)

	_incExportFailures(signalLogs)
	_incExportFailures(signalTraces)
	_incExportFailures(signalMetrics)
	snap := GetHealthSnapshot()
	if snap.LogsExportFailures != 1 {
		t.Errorf("LogsExportFailures: want 1, got %d", snap.LogsExportFailures)
	}
	if snap.TracesExportFailures != 1 {
		t.Errorf("TracesExportFailures: want 1, got %d", snap.TracesExportFailures)
	}
	if snap.MetricsExportFailures != 1 {
		t.Errorf("MetricsExportFailures: want 1, got %d", snap.MetricsExportFailures)
	}
}

func TestIncRetries(t *testing.T) {
	_resetHealth()
	t.Cleanup(_resetHealth)

	_incRetries(signalLogs)
	_incRetries(signalTraces)
	_incRetries(signalMetrics)
	snap := GetHealthSnapshot()
	if snap.LogsRetries != 1 {
		t.Errorf("LogsRetries: want 1, got %d", snap.LogsRetries)
	}
	if snap.TracesRetries != 1 {
		t.Errorf("TracesRetries: want 1, got %d", snap.TracesRetries)
	}
	if snap.MetricsRetries != 1 {
		t.Errorf("MetricsRetries: want 1, got %d", snap.MetricsRetries)
	}
}

func TestRecordExportLatency(t *testing.T) {
	_resetHealth()
	t.Cleanup(_resetHealth)

	_recordExportLatencyForSignal(signalLogs, 10.5)
	_recordExportLatencyForSignal(signalLogs, 25.0)
	snap := GetHealthSnapshot()
	// Latest, not cumulative.
	if snap.LogsExportLatencyMs != 25.0 {
		t.Errorf("LogsExportLatencyMs: want 25.0, got %f", snap.LogsExportLatencyMs)
	}
}

func TestIncAsyncBlockingRisk(t *testing.T) {
	_resetHealth()
	t.Cleanup(_resetHealth)

	_incAsyncBlockingRisk(signalLogs)
	_incAsyncBlockingRisk(signalTraces)
	_incAsyncBlockingRisk(signalMetrics)
	snap := GetHealthSnapshot()
	if snap.LogsAsyncBlockingRisk != 1 {
		t.Errorf("LogsAsyncBlockingRisk: want 1, got %d", snap.LogsAsyncBlockingRisk)
	}
	if snap.TracesAsyncBlockingRisk != 1 {
		t.Errorf("TracesAsyncBlockingRisk: want 1, got %d", snap.TracesAsyncBlockingRisk)
	}
	if snap.MetricsAsyncBlockingRisk != 1 {
		t.Errorf("MetricsAsyncBlockingRisk: want 1, got %d", snap.MetricsAsyncBlockingRisk)
	}
}

func TestSetSetupError(t *testing.T) {
	_resetHealth()
	t.Cleanup(_resetHealth)

	_setSetupError("something went wrong")
	snap := GetHealthSnapshot()
	if snap.SetupError != "something went wrong" {
		t.Errorf("SetupError: want %q, got %q", "something went wrong", snap.SetupError)
	}
}

func TestSetSetupError_EmptyString(t *testing.T) {
	_resetHealth()
	t.Cleanup(_resetHealth)

	_setSetupError("initial error")
	_setSetupError("")
	snap := GetHealthSnapshot()
	if snap.SetupError != "" {
		t.Errorf("SetupError: want empty, got %q", snap.SetupError)
	}
}

func TestResetHealth(t *testing.T) {
	_incEmitted(signalLogs)
	_incEmitted(signalTraces)
	_setSetupError("err")
	_resetHealth()
	snap := GetHealthSnapshot()
	if snap.LogsEmitted != 0 || snap.TracesEmitted != 0 || snap.SetupError != "" {
		t.Errorf("after reset expected zeroed counters, got %+v", snap)
	}
}

func TestBackwardCompatWrappers(t *testing.T) {
	_resetHealth()
	t.Cleanup(_resetHealth)

	_incLogsEmitted()
	_incLogsDropped()
	_incSpansStarted()
	_incSpansDropped()
	_incMetricsRecorded()
	_incMetricsDropped()
	_incLogsExportErrors()
	_incSpansExportErrors()
	_incMetricsExportErrors()

	snap := GetHealthSnapshot()
	if snap.LogsEmitted != 1 {
		t.Errorf("LogsEmitted: want 1, got %d", snap.LogsEmitted)
	}
	if snap.LogsDropped != 1 {
		t.Errorf("LogsDropped: want 1, got %d", snap.LogsDropped)
	}
	if snap.TracesEmitted != 1 {
		t.Errorf("TracesEmitted: want 1, got %d", snap.TracesEmitted)
	}
	if snap.TracesDropped != 1 {
		t.Errorf("TracesDropped: want 1, got %d", snap.TracesDropped)
	}
	if snap.MetricsEmitted != 1 {
		t.Errorf("MetricsEmitted: want 1, got %d", snap.MetricsEmitted)
	}
	if snap.MetricsDropped != 1 {
		t.Errorf("MetricsDropped: want 1, got %d", snap.MetricsDropped)
	}
	if snap.LogsExportFailures != 1 {
		t.Errorf("LogsExportFailures: want 1, got %d", snap.LogsExportFailures)
	}
	if snap.TracesExportFailures != 1 {
		t.Errorf("TracesExportFailures: want 1, got %d", snap.TracesExportFailures)
	}
	if snap.MetricsExportFailures != 1 {
		t.Errorf("MetricsExportFailures: want 1, got %d", snap.MetricsExportFailures)
	}
}

func TestConcurrentIncrements(t *testing.T) {
	t.Parallel()
	_resetHealth()

	const goroutines = 50
	const iterations = 100

	var wg sync.WaitGroup
	wg.Add(goroutines)
	for i := 0; i < goroutines; i++ {
		go func() {
			defer wg.Done()
			for j := 0; j < iterations; j++ {
				_incEmitted(signalLogs)
				_incDroppedHealth(signalLogs)
				_incEmitted(signalTraces)
				_incEmitted(signalMetrics)
				_incRetries(signalLogs)
			}
		}()
	}
	wg.Wait()

	snap := GetHealthSnapshot()
	expected := int64(goroutines * iterations)
	if snap.LogsEmitted != expected {
		t.Errorf("LogsEmitted: want %d, got %d", expected, snap.LogsEmitted)
	}
	if snap.LogsDropped != expected {
		t.Errorf("LogsDropped: want %d, got %d", expected, snap.LogsDropped)
	}
	if snap.TracesEmitted != expected {
		t.Errorf("TracesEmitted: want %d, got %d", expected, snap.TracesEmitted)
	}
	if snap.MetricsEmitted != expected {
		t.Errorf("MetricsEmitted: want %d, got %d", expected, snap.MetricsEmitted)
	}
	if snap.LogsRetries != expected {
		t.Errorf("LogsRetries: want %d, got %d", expected, snap.LogsRetries)
	}
}

func TestCircuitStateIntegration(t *testing.T) {
	_resetHealth()
	_resetResiliencePolicies()
	t.Cleanup(_resetHealth)
	t.Cleanup(_resetResiliencePolicies)

	_tripCircuitBreaker(signalLogs)

	snap := GetHealthSnapshot()
	if snap.LogsCircuitState != "open" {
		t.Errorf("LogsCircuitState: want open, got %s", snap.LogsCircuitState)
	}
	if snap.LogsCircuitOpenCount != 1 {
		t.Errorf("LogsCircuitOpenCount: want 1, got %d", snap.LogsCircuitOpenCount)
	}
	if snap.TracesCircuitState != "closed" {
		t.Errorf("TracesCircuitState: want closed, got %s", snap.TracesCircuitState)
	}
}
