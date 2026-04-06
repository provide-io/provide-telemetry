// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// parity_backpressure_test.go validates Go behavioral parity for backpressure
// queue policies against spec/behavioral_fixtures.yaml: default policy is
// unlimited (size=0), unlimited queues always acquire, zero-size is unlimited,
// and bounded queues reject after capacity is reached.

package telemetry

import (
	"testing"
)

// ── Backpressure Parity ───────────────────────────────────────────────────────

func TestParity_Backpressure_DefaultUnlimited(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)

	policy := GetQueuePolicy()
	if policy.LogsMaxSize != 0 {
		t.Errorf("expected default LogsMaxSize=0 (unlimited), got %d", policy.LogsMaxSize)
	}
	if policy.TracesMaxSize != 0 {
		t.Errorf("expected default TracesMaxSize=0 (unlimited), got %d", policy.TracesMaxSize)
	}
	if policy.MetricsMaxSize != 0 {
		t.Errorf("expected default MetricsMaxSize=0 (unlimited), got %d", policy.MetricsMaxSize)
	}
}

func TestParity_Backpressure_UnlimitedAlwaysAcquires(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)

	for i := 0; i < 5000; i++ {
		if !TryAcquire(signalLogs) {
			t.Fatalf("TryAcquire failed at iteration %d with unlimited queue", i)
		}
	}
}

// ── Backpressure Unlimited ──────────────────────────────────────────────────

func TestParity_Backpressure_ZeroIsUnlimited(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)
	t.Cleanup(_resetHealth)

	SetQueuePolicy(QueuePolicy{LogsMaxSize: 0, TracesMaxSize: 0, MetricsMaxSize: 0})
	// 100 concurrent acquires must all succeed without release.
	for i := 0; i < 100; i++ {
		if !TryAcquire(signalLogs) {
			t.Fatalf("acquire %d failed with unlimited (0) queue", i)
		}
	}
}

func TestParity_Backpressure_BoundedRejects(t *testing.T) {
	_resetQueuePolicy()
	_resetHealth()
	t.Cleanup(_resetQueuePolicy)
	t.Cleanup(_resetHealth)

	SetQueuePolicy(QueuePolicy{LogsMaxSize: 1, TracesMaxSize: 1, MetricsMaxSize: 1})
	if !TryAcquire(signalLogs) {
		t.Fatal("first acquire must succeed")
	}
	if TryAcquire(signalLogs) {
		t.Fatal("second acquire must fail with queue size 1")
	}
}
