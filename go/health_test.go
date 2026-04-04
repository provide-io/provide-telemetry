// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"sync"
	"testing"
)

func TestGetHealthSnapshot_InitiallyZero(t *testing.T) {
	_resetHealth()
	snap := GetHealthSnapshot()
	if snap != (HealthSnapshot{}) {
		t.Errorf("expected zeroed snapshot, got %+v", snap)
	}
}

func TestIncLogsEmitted(t *testing.T) {
	_resetHealth()
	_incLogsEmitted()
	_incLogsEmitted()
	snap := GetHealthSnapshot()
	if snap.LogsEmitted != 2 {
		t.Errorf("LogsEmitted: want 2, got %d", snap.LogsEmitted)
	}
}

func TestIncLogsDropped(t *testing.T) {
	_resetHealth()
	_incLogsDropped()
	snap := GetHealthSnapshot()
	if snap.LogsDropped != 1 {
		t.Errorf("LogsDropped: want 1, got %d", snap.LogsDropped)
	}
}

func TestIncLogsExportErrors(t *testing.T) {
	_resetHealth()
	_incLogsExportErrors()
	snap := GetHealthSnapshot()
	if snap.LogsExportErrors != 1 {
		t.Errorf("LogsExportErrors: want 1, got %d", snap.LogsExportErrors)
	}
}

func TestIncLogsExportedOK(t *testing.T) {
	_resetHealth()
	_incLogsExportedOK()
	snap := GetHealthSnapshot()
	if snap.LogsExportedOK != 1 {
		t.Errorf("LogsExportedOK: want 1, got %d", snap.LogsExportedOK)
	}
}

func TestIncSpansStarted(t *testing.T) {
	_resetHealth()
	_incSpansStarted()
	snap := GetHealthSnapshot()
	if snap.SpansStarted != 1 {
		t.Errorf("SpansStarted: want 1, got %d", snap.SpansStarted)
	}
}

func TestIncSpansDropped(t *testing.T) {
	_resetHealth()
	_incSpansDropped()
	snap := GetHealthSnapshot()
	if snap.SpansDropped != 1 {
		t.Errorf("SpansDropped: want 1, got %d", snap.SpansDropped)
	}
}

func TestIncSpansExportErrors(t *testing.T) {
	_resetHealth()
	_incSpansExportErrors()
	snap := GetHealthSnapshot()
	if snap.SpansExportErrors != 1 {
		t.Errorf("SpansExportErrors: want 1, got %d", snap.SpansExportErrors)
	}
}

func TestIncSpansExportedOK(t *testing.T) {
	_resetHealth()
	_incSpansExportedOK()
	snap := GetHealthSnapshot()
	if snap.SpansExportedOK != 1 {
		t.Errorf("SpansExportedOK: want 1, got %d", snap.SpansExportedOK)
	}
}

func TestIncMetricsRecorded(t *testing.T) {
	_resetHealth()
	_incMetricsRecorded()
	snap := GetHealthSnapshot()
	if snap.MetricsRecorded != 1 {
		t.Errorf("MetricsRecorded: want 1, got %d", snap.MetricsRecorded)
	}
}

func TestIncMetricsDropped(t *testing.T) {
	_resetHealth()
	_incMetricsDropped()
	snap := GetHealthSnapshot()
	if snap.MetricsDropped != 1 {
		t.Errorf("MetricsDropped: want 1, got %d", snap.MetricsDropped)
	}
}

func TestIncMetricsExportErrors(t *testing.T) {
	_resetHealth()
	_incMetricsExportErrors()
	snap := GetHealthSnapshot()
	if snap.MetricsExportErrors != 1 {
		t.Errorf("MetricsExportErrors: want 1, got %d", snap.MetricsExportErrors)
	}
}

func TestIncMetricsExportedOK(t *testing.T) {
	_resetHealth()
	_incMetricsExportedOK()
	snap := GetHealthSnapshot()
	if snap.MetricsExportedOK != 1 {
		t.Errorf("MetricsExportedOK: want 1, got %d", snap.MetricsExportedOK)
	}
}

func TestIncCircuitBreakerTrips(t *testing.T) {
	_resetHealth()
	_incCircuitBreakerTrips()
	snap := GetHealthSnapshot()
	if snap.CircuitBreakerTrips != 1 {
		t.Errorf("CircuitBreakerTrips: want 1, got %d", snap.CircuitBreakerTrips)
	}
}

func TestIncRetryAttempts(t *testing.T) {
	_resetHealth()
	_incRetryAttempts()
	snap := GetHealthSnapshot()
	if snap.RetryAttempts != 1 {
		t.Errorf("RetryAttempts: want 1, got %d", snap.RetryAttempts)
	}
}

func TestAddExportLatency(t *testing.T) {
	_resetHealth()
	_addExportLatency(10)
	_addExportLatency(25)
	snap := GetHealthSnapshot()
	if snap.ExportLatencyMs != 35 {
		t.Errorf("ExportLatencyMs: want 35, got %d", snap.ExportLatencyMs)
	}
}

func TestIncSetupCount(t *testing.T) {
	_resetHealth()
	_incSetupCount()
	snap := GetHealthSnapshot()
	if snap.SetupCount != 1 {
		t.Errorf("SetupCount: want 1, got %d", snap.SetupCount)
	}
}

func TestIncShutdownCount(t *testing.T) {
	_resetHealth()
	_incShutdownCount()
	snap := GetHealthSnapshot()
	if snap.ShutdownCount != 1 {
		t.Errorf("ShutdownCount: want 1, got %d", snap.ShutdownCount)
	}
}

func TestSetLastError(t *testing.T) {
	_resetHealth()
	_setLastError("something went wrong")
	snap := GetHealthSnapshot()
	if snap.LastError != "something went wrong" {
		t.Errorf("LastError: want %q, got %q", "something went wrong", snap.LastError)
	}
}

func TestSetLastError_EmptyString(t *testing.T) {
	_resetHealth()
	_setLastError("initial error")
	_setLastError("")
	snap := GetHealthSnapshot()
	if snap.LastError != "" {
		t.Errorf("LastError: want empty, got %q", snap.LastError)
	}
}

func TestResetHealth(t *testing.T) {
	_incLogsEmitted()
	_incSpansStarted()
	_setLastError("err")
	_resetHealth()
	snap := GetHealthSnapshot()
	if snap != (HealthSnapshot{}) {
		t.Errorf("after reset expected zeroed snapshot, got %+v", snap)
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
				_incLogsEmitted()
				_incLogsDropped()
				_incSpansStarted()
				_incMetricsRecorded()
				_addExportLatency(1)
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
	if snap.SpansStarted != expected {
		t.Errorf("SpansStarted: want %d, got %d", expected, snap.SpansStarted)
	}
	if snap.MetricsRecorded != expected {
		t.Errorf("MetricsRecorded: want %d, got %d", expected, snap.MetricsRecorded)
	}
	if snap.ExportLatencyMs != expected {
		t.Errorf("ExportLatencyMs: want %d, got %d", expected, snap.ExportLatencyMs)
	}
}
