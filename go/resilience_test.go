// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"testing"
	"time"
)

// _setCircuitTrippedAt is a test helper that sets the tripped-at time for a signal.
func _setCircuitTrippedAt(signal string, t time.Time) {
	_resilienceMu.Lock()
	defer _resilienceMu.Unlock()
	_circuitTrippedAt[signal] = t
}

// _tripCircuitBreaker is a test helper that forces the CB into open state for a signal.
func _tripCircuitBreaker(signal string) {
	_resilienceMu.Lock()
	defer _resilienceMu.Unlock()
	_consecutiveTimeouts[signal] = _cbThreshold
	_openCount[signal]++
	_circuitTrippedAt[signal] = time.Now()
}

// _setOpenCount is a test helper that sets the open count for a signal.
func _setOpenCount(signal string, count int) {
	_resilienceMu.Lock()
	defer _resilienceMu.Unlock()
	_openCount[signal] = count
}

// _setHalfOpenProbing is a test helper that sets the half-open probing flag for a signal.
func _setHalfOpenProbing(signal string, v bool) {
	_resilienceMu.Lock()
	defer _resilienceMu.Unlock()
	_halfOpenProbing[signal] = v
}

func TestGetExporterPolicy_Defaults(t *testing.T) {
	_resetResiliencePolicies()
	t.Cleanup(_resetResiliencePolicies)

	for _, signal := range []string{signalLogs, signalTraces, signalMetrics, "unknown"} {
		policy := GetExporterPolicy(signal)
		if policy.Retries != 0 {
			t.Errorf("%s: Retries want 0, got %d", signal, policy.Retries)
		}
		if policy.BackoffSeconds != 0.0 {
			t.Errorf("%s: BackoffSeconds want 0.0, got %f", signal, policy.BackoffSeconds)
		}
		if policy.TimeoutSeconds != 10.0 {
			t.Errorf("%s: TimeoutSeconds want 10.0, got %f", signal, policy.TimeoutSeconds)
		}
		if !policy.FailOpen {
			t.Errorf("%s: FailOpen want true, got false", signal)
		}
	}
}

func TestSetExporterPolicy_ReplacesPolicy(t *testing.T) {
	_resetResiliencePolicies()
	t.Cleanup(_resetResiliencePolicies)

	initial := ExporterPolicy{Retries: 1, BackoffSeconds: 0.5, TimeoutSeconds: 10.0, FailOpen: false}
	SetExporterPolicy(signalLogs, initial)

	got := GetExporterPolicy(signalLogs)
	if got.Retries != 1 {
		t.Errorf("Retries: want 1, got %d", got.Retries)
	}
	if got.FailOpen {
		t.Error("FailOpen: want false, got true")
	}

	updated := ExporterPolicy{Retries: 5, BackoffSeconds: 2.0, TimeoutSeconds: 60.0, FailOpen: true}
	SetExporterPolicy(signalLogs, updated)

	got = GetExporterPolicy(signalLogs)
	if got.Retries != 5 {
		t.Errorf("Retries after update: want 5, got %d", got.Retries)
	}
	if got.BackoffSeconds != 2.0 {
		t.Errorf("BackoffSeconds after update: want 2.0, got %f", got.BackoffSeconds)
	}
	if !got.FailOpen {
		t.Error("FailOpen after update: want true, got false")
	}
}

func TestIncExportSuccessIsNoOp(t *testing.T) {
	// _incExportSuccess is a no-op — ensure it does not panic and can be called.
	_incExportSuccess("logs")
	_incExportSuccess("traces")
	_incExportSuccess("metrics")
}
