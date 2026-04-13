// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"sync"
	"testing"
)

func TestGetQueuePolicy_Defaults(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)

	policy := GetQueuePolicy()
	if policy.LogsMaxSize != _defaultQueueSize {
		t.Errorf("LogsMaxSize: want %d, got %d", _defaultQueueSize, policy.LogsMaxSize)
	}
	if policy.TracesMaxSize != _defaultQueueSize {
		t.Errorf("TracesMaxSize: want %d, got %d", _defaultQueueSize, policy.TracesMaxSize)
	}
	if policy.MetricsMaxSize != _defaultQueueSize {
		t.Errorf("MetricsMaxSize: want %d, got %d", _defaultQueueSize, policy.MetricsMaxSize)
	}
}

func TestTryAcquire_UnderLimit_ReturnsTrue(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)

	for _, signal := range []string{signalLogs, signalTraces, signalMetrics} {
		if !TryAcquire(signal) {
			t.Errorf("TryAcquire(%q): expected true when under limit", signal)
		}
	}
}

func TestTryAcquire_AtCapacity_ReturnsFalse(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)

	SetQueuePolicy(QueuePolicy{LogsMaxSize: 2, TracesMaxSize: 2, MetricsMaxSize: 2})

	for _, signal := range []string{signalLogs, signalTraces, signalMetrics} {
		// Fill to capacity.
		if !TryAcquire(signal) {
			t.Fatalf("TryAcquire(%q) slot 1: expected true", signal)
		}
		if !TryAcquire(signal) {
			t.Fatalf("TryAcquire(%q) slot 2: expected true", signal)
		}
		// At capacity — must return false.
		if TryAcquire(signal) {
			t.Errorf("TryAcquire(%q) over capacity: expected false", signal)
		}
	}
}

func TestRelease_FreesSlot(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)

	SetQueuePolicy(QueuePolicy{LogsMaxSize: 1, TracesMaxSize: 1, MetricsMaxSize: 1})

	for _, signal := range []string{signalLogs, signalTraces, signalMetrics} {
		if !TryAcquire(signal) {
			t.Fatalf("TryAcquire(%q): expected true", signal)
		}
		// Channel full — acquire should fail.
		if TryAcquire(signal) {
			t.Fatalf("TryAcquire(%q) when full: expected false", signal)
		}
		// Release the slot.
		Release(signal)
		// Now acquire should succeed.
		if !TryAcquire(signal) {
			t.Errorf("TryAcquire(%q) after Release: expected true", signal)
		}
	}
}

func TestTryAcquire_HealthCounters_AcquireSuccess_NoEmittedIncrement(t *testing.T) {
	// TryAcquire no longer increments emitted — emitted is tracked by ShouldSample only.
	_resetQueuePolicy()
	_resetHealth()
	t.Cleanup(_resetQueuePolicy)
	t.Cleanup(_resetHealth)

	SetQueuePolicy(QueuePolicy{LogsMaxSize: 10, TracesMaxSize: 10, MetricsMaxSize: 10})

	TryAcquire(signalLogs)
	TryAcquire(signalTraces)
	TryAcquire(signalMetrics)

	snap := GetHealthSnapshot()
	if snap.LogsEmitted != 0 {
		t.Errorf("LogsEmitted: want 0, got %d", snap.LogsEmitted)
	}
	if snap.TracesEmitted != 0 {
		t.Errorf("TracesEmitted: want 0, got %d", snap.TracesEmitted)
	}
	if snap.MetricsEmitted != 0 {
		t.Errorf("MetricsEmitted: want 0, got %d", snap.MetricsEmitted)
	}
}

func TestTryAcquire_HealthCounters_AcquireFailure(t *testing.T) {
	_resetQueuePolicy()
	_resetHealth()
	t.Cleanup(_resetQueuePolicy)
	t.Cleanup(_resetHealth)

	SetQueuePolicy(QueuePolicy{LogsMaxSize: 1, TracesMaxSize: 1, MetricsMaxSize: 1})

	// Fill each channel then try again to trigger drop counters.
	for _, signal := range []string{signalLogs, signalTraces, signalMetrics} {
		TryAcquire(signal) // fills the slot
		TryAcquire(signal) // should drop
	}

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

func TestSetQueuePolicy_RebuildsChannels(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)

	newPolicy := QueuePolicy{LogsMaxSize: 5, TracesMaxSize: 10, MetricsMaxSize: 15}
	SetQueuePolicy(newPolicy)

	got := GetQueuePolicy()
	if got.LogsMaxSize != 5 {
		t.Errorf("LogsMaxSize: want 5, got %d", got.LogsMaxSize)
	}
	if got.TracesMaxSize != 10 {
		t.Errorf("TracesMaxSize: want 10, got %d", got.TracesMaxSize)
	}
	if got.MetricsMaxSize != 15 {
		t.Errorf("MetricsMaxSize: want 15, got %d", got.MetricsMaxSize)
	}

	// Verify new channel capacities are honoured.
	for i := 0; i < 5; i++ {
		if !TryAcquire(signalLogs) {
			t.Errorf("TryAcquire(logs) slot %d: expected true", i+1)
		}
	}
	if TryAcquire(signalLogs) {
		t.Errorf("TryAcquire(logs) slot 6: expected false (capacity 5)")
	}
}

func TestTryAcquire_UnknownSignal_ReturnsFalse(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)

	if TryAcquire("unknown") {
		t.Error("TryAcquire(unknown): expected false")
	}
}

func TestRelease_UnknownSignal_NoOp(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)

	// Should not panic or block.
	Release("unknown")
}

func TestRelease_EmptyChannel_NoOp(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)

	// Release on an empty channel should not block.
	Release(signalLogs)
	Release(signalTraces)
	Release(signalMetrics)
}

func TestSetQueuePolicy_ZeroSize_Unlimited(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)

	// A zero-sized policy means unlimited — TryAcquire always succeeds.
	SetQueuePolicy(QueuePolicy{LogsMaxSize: 0, TracesMaxSize: 0, MetricsMaxSize: 0})

	for _, signal := range []string{signalLogs, signalTraces, signalMetrics} {
		for i := 0; i < 10; i++ {
			if !TryAcquire(signal) {
				t.Errorf("TryAcquire(%q) iteration %d with unlimited size: expected true", signal, i)
			}
		}
	}
}

// TestTryAcquireRelease_ConcurrentSetQueuePolicy verifies that concurrent calls to
// TryAcquire/Release and SetQueuePolicy do not race. Before the TOCTOU fix,
// TryAcquire would release the RLock before sending on the channel, allowing
// SetQueuePolicy to swap the channel pointer mid-operation.
func TestTryAcquireRelease_ConcurrentSetQueuePolicy(t *testing.T) {
	_resetQueuePolicy()
	_resetHealth()
	t.Cleanup(_resetQueuePolicy)
	t.Cleanup(_resetHealth)

	SetQueuePolicy(QueuePolicy{LogsMaxSize: 10, TracesMaxSize: 10, MetricsMaxSize: 10})

	const goroutines = 20
	const iterations = 200

	var wg sync.WaitGroup
	// Goroutines that continuously swap the queue policy.
	for i := 0; i < 3; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			for j := 0; j < iterations; j++ {
				size := (i+j)%10 + 1
				SetQueuePolicy(QueuePolicy{
					LogsMaxSize:    size,
					TracesMaxSize:  size,
					MetricsMaxSize: size,
				})
			}
		}(i)
	}
	// Goroutines that continuously acquire and release.
	for i := 0; i < goroutines; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < iterations; j++ {
				for _, signal := range []string{signalLogs, signalTraces, signalMetrics} {
					if TryAcquire(signal) {
						Release(signal)
					}
				}
			}
		}()
	}
	wg.Wait()
}

func TestBackpressureConcurrency(t *testing.T) {
	_resetQueuePolicy()
	_resetHealth()
	t.Cleanup(_resetQueuePolicy)
	t.Cleanup(_resetHealth)

	SetQueuePolicy(QueuePolicy{LogsMaxSize: 50, TracesMaxSize: 50, MetricsMaxSize: 50})

	const goroutines = 50
	const iterations = 100

	var wg sync.WaitGroup
	wg.Add(goroutines)
	for i := 0; i < goroutines; i++ {
		go func() {
			defer wg.Done()
			for j := 0; j < iterations; j++ {
				acquired := TryAcquire(signalLogs)
				if acquired {
					Release(signalLogs)
				}
				acquired = TryAcquire(signalTraces)
				if acquired {
					Release(signalTraces)
				}
				acquired = TryAcquire(signalMetrics)
				if acquired {
					Release(signalMetrics)
				}
			}
		}()
	}
	wg.Wait()
}
