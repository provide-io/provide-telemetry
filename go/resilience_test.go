// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
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

func TestRunWithResilience_SucceedsFirstTry(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	SetExporterPolicy(signalLogs, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: true})

	called := 0
	err := RunWithResilience(context.Background(), signalLogs, func(_ context.Context) error {
		called++
		return nil
	})

	if err != nil {
		t.Fatalf("expected nil error, got %v", err)
	}
	if called != 1 {
		t.Errorf("fn called %d times, want 1", called)
	}

	snap := GetHealthSnapshot()
	if snap.LogsExportFailures != 0 {
		t.Errorf("LogsExportFailures: want 0 (success), got %d", snap.LogsExportFailures)
	}
}

func TestRunWithResilience_RetriesOnTransientError(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	SetExporterPolicy(signalTraces, ExporterPolicy{Retries: 2, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: true})

	attempt := 0
	err := RunWithResilience(context.Background(), signalTraces, func(_ context.Context) error {
		attempt++
		if attempt < 3 {
			return errors.New("transient")
		}
		return nil
	})

	if err != nil {
		t.Fatalf("expected nil error after retry, got %v", err)
	}
	if attempt != 3 {
		t.Errorf("expected 3 attempts, got %d", attempt)
	}

	snap := GetHealthSnapshot()
	// 2 failures before success.
	if snap.TracesExportFailures != 2 {
		t.Errorf("TracesExportFailures: want 2, got %d", snap.TracesExportFailures)
	}
	if snap.TracesRetries != 2 {
		t.Errorf("TracesRetries: want 2, got %d", snap.TracesRetries)
	}
}

func TestRunWithResilience_FailsAfterAllRetries(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	SetExporterPolicy(signalMetrics, ExporterPolicy{Retries: 2, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: false})

	sentinel := errors.New("permanent")
	err := RunWithResilience(context.Background(), signalMetrics, func(_ context.Context) error {
		return sentinel
	})

	if err == nil {
		t.Fatal("expected error after all retries, got nil")
	}

	snap := GetHealthSnapshot()
	// 3 attempts total (1 + 2 retries), each increments failure counter.
	if snap.MetricsExportFailures != 3 {
		t.Errorf("MetricsExportFailures: want 3, got %d", snap.MetricsExportFailures)
	}
}

func TestRunWithResilience_FailOpen_ReturnsNil(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	SetExporterPolicy(signalLogs, ExporterPolicy{Retries: 1, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: true})

	sentinel := errors.New("always fail")
	err := RunWithResilience(context.Background(), signalLogs, func(_ context.Context) error {
		return sentinel
	})

	if err != nil {
		t.Fatalf("FailOpen=true: expected nil, got %v", err)
	}
}

func TestRunWithResilience_ContextTimeoutPropagated(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	SetExporterPolicy(signalLogs, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: false})

	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Millisecond)
	defer cancel()
	<-ctx.Done()

	err := RunWithResilience(ctx, signalLogs, func(inner context.Context) error {
		return inner.Err()
	})

	if err == nil {
		t.Fatal("expected timeout error, got nil")
	}
}

func TestCB_TripsAfterThreeTimeouts(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	// 1ms timeout, fn sleeps 50ms → context.DeadlineExceeded
	SetExporterPolicy(signalLogs, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 0.001, FailOpen: false})

	for i := 0; i < 3; i++ {
		_ = RunWithResilience(context.Background(), signalLogs, func(ctx context.Context) error {
			select {
			case <-time.After(50 * time.Millisecond):
				return nil
			case <-ctx.Done():
				return ctx.Err()
			}
		})
	}

	// CB should now be open; next call should be rejected.
	_resetHealth()
	fnCalled := false
	err := RunWithResilience(context.Background(), signalLogs, func(_ context.Context) error {
		fnCalled = true
		return nil
	})

	if fnCalled {
		t.Error("fn should not be called when circuit breaker is open")
	}

	snap := GetHealthSnapshot()
	if snap.LogsCircuitState != "open" {
		t.Errorf("LogsCircuitState: want open, got %s", snap.LogsCircuitState)
	}

	// FailOpen=false, so we should get an error.
	if err == nil {
		t.Fatal("expected error when CB is open and FailOpen=false, got nil")
	}
}

func TestCB_NonTimeoutFailureResetsCounter(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	signal := "cb-reset-test"

	// 1ms timeout for timeout-producing calls.
	SetExporterPolicy(signal, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 0.001, FailOpen: false})

	// 2 timeouts
	for i := 0; i < 2; i++ {
		_ = RunWithResilience(context.Background(), signal, func(ctx context.Context) error {
			select {
			case <-time.After(50 * time.Millisecond):
				return nil
			case <-ctx.Done():
				return ctx.Err()
			}
		})
	}

	// 1 plain (non-timeout) error — should reset the counter.
	SetExporterPolicy(signal, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: false})
	_ = RunWithResilience(context.Background(), signal, func(_ context.Context) error {
		return errors.New("plain error")
	})

	// CB should NOT be tripped.
	state := GetCircuitState(signal)
	if state.State != "closed" {
		t.Errorf("expected closed after non-timeout failure reset, got %s", state.State)
	}
}

func TestCB_FailOpen_CircuitOpen_ReturnsNil(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	signal := signalLogs
	SetExporterPolicy(signal, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: true})

	_tripCircuitBreaker(signal)

	err := RunWithResilience(context.Background(), signal, func(_ context.Context) error {
		t.Error("fn must not be called when circuit breaker is open")
		return nil
	})

	if err != nil {
		t.Fatalf("FailOpen=true: expected nil, got %v", err)
	}

	snap := GetHealthSnapshot()
	if snap.LogsCircuitState != "open" {
		t.Errorf("LogsCircuitState: want open, got %s", snap.LogsCircuitState)
	}
	if snap.LogsCircuitOpenCount < 1 {
		t.Errorf("LogsCircuitOpenCount: want >= 1, got %d", snap.LogsCircuitOpenCount)
	}
}

func TestCB_FailClosed_CircuitOpen_ReturnsError(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	signal := signalTraces
	SetExporterPolicy(signal, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: false})

	_tripCircuitBreaker(signal)

	err := RunWithResilience(context.Background(), signal, func(_ context.Context) error {
		t.Error("fn must not be called when circuit breaker is open")
		return nil
	})

	if err == nil {
		t.Fatal("FailOpen=false: expected error when circuit breaker is open, got nil")
	}
}

func TestCB_HalfOpenProbe_SuccessDecays(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	signal := "half-open-success"
	SetExporterPolicy(signal, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: false})

	_tripCircuitBreaker(signal)

	// Set tripped time far enough in the past to allow half-open probe.
	_setCircuitTrippedAt(signal, time.Now().Add(-2*_cbBaseCooldown))

	// Probe should succeed.
	err := RunWithResilience(context.Background(), signal, func(_ context.Context) error {
		return nil
	})
	if err != nil {
		t.Fatalf("expected nil on successful probe, got %v", err)
	}

	state := GetCircuitState(signal)
	// After successful probe, openCount should decay.
	if state.OpenCount != 0 {
		t.Errorf("OpenCount: want 0 (decayed from 1), got %d", state.OpenCount)
	}
}

func TestCB_HalfOpenProbe_FailureReopens(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	signal := "half-open-failure"
	SetExporterPolicy(signal, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 0.001, FailOpen: false})

	_tripCircuitBreaker(signal)
	initialOC := GetCircuitState(signal).OpenCount

	// Set tripped time far enough in the past to allow half-open probe.
	_setCircuitTrippedAt(signal, time.Now().Add(-2*_cbBaseCooldown))

	// Probe fails (timeout).
	_ = RunWithResilience(context.Background(), signal, func(ctx context.Context) error {
		select {
		case <-time.After(50 * time.Millisecond):
			return nil
		case <-ctx.Done():
			return ctx.Err()
		}
	})

	state := GetCircuitState(signal)
	if state.OpenCount <= initialOC {
		t.Errorf("OpenCount should increase after failed probe: was %d, now %d", initialOC, state.OpenCount)
	}
	if state.State != "open" {
		t.Errorf("expected open after failed probe, got %s", state.State)
	}
}

func TestCB_HalfOpenProbe_ConcurrentCallRejected(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	signal := "half-open-concurrent"
	SetExporterPolicy(signal, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: false})

	_tripCircuitBreaker(signal)
	_setCircuitTrippedAt(signal, time.Now().Add(-2*_cbBaseCooldown))

	// Simulate a probe already in progress.
	_setHalfOpenProbing(signal, true)

	// This call should be rejected (probe already in flight).
	fnCalled := false
	err := RunWithResilience(context.Background(), signal, func(_ context.Context) error {
		fnCalled = true
		return nil
	})

	if fnCalled {
		t.Error("fn should not be called when half-open probe is already in progress")
	}
	if err == nil {
		t.Error("expected error when half-open probe in progress and FailOpen=false")
	}
}

func TestGetCircuitState_Closed(t *testing.T) {
	_resetResiliencePolicies()
	t.Cleanup(_resetResiliencePolicies)

	state := GetCircuitState("fresh-signal")
	if state.State != "closed" {
		t.Errorf("expected closed for fresh signal, got %s", state.State)
	}
	if state.OpenCount != 0 {
		t.Errorf("OpenCount: want 0, got %d", state.OpenCount)
	}
	if state.CooldownRemainingMs != 0 {
		t.Errorf("CooldownRemainingMs: want 0, got %d", state.CooldownRemainingMs)
	}
}

func TestGetCircuitState_Open(t *testing.T) {
	_resetResiliencePolicies()
	t.Cleanup(_resetResiliencePolicies)

	signal := "open-state-test"
	_tripCircuitBreaker(signal)

	state := GetCircuitState(signal)
	if state.State != "open" {
		t.Errorf("expected open, got %s", state.State)
	}
	if state.CooldownRemainingMs <= 0 {
		t.Errorf("CooldownRemainingMs should be > 0, got %d", state.CooldownRemainingMs)
	}
}

func TestGetCircuitState_ExponentialCooldown(t *testing.T) {
	_resetResiliencePolicies()
	t.Cleanup(_resetResiliencePolicies)

	signal := "exp-cooldown-test"
	_tripCircuitBreaker(signal)
	_setOpenCount(signal, 2) // cooldown = 30s * 2^2 = 120s

	state := GetCircuitState(signal)
	if state.State != "open" {
		t.Errorf("expected open, got %s", state.State)
	}
	// Cooldown should be approximately 120s (120000ms), give or take a few ms for elapsed time.
	if state.CooldownRemainingMs < 119000 || state.CooldownRemainingMs > 120100 {
		t.Errorf("CooldownRemainingMs: want ~120000, got %d", state.CooldownRemainingMs)
	}
}

func TestGetCircuitState_CooldownCapped(t *testing.T) {
	_resetResiliencePolicies()
	t.Cleanup(_resetResiliencePolicies)

	signal := "capped-cooldown-test"
	_tripCircuitBreaker(signal)
	_setOpenCount(signal, 10) // 30s * 2^10 = 30720s, capped at 1024s

	state := GetCircuitState(signal)
	if state.State != "open" {
		t.Errorf("expected open, got %s", state.State)
	}
	// Cooldown should be capped at 1024s = 1024000ms.
	if state.CooldownRemainingMs < 1023000 || state.CooldownRemainingMs > 1024100 {
		t.Errorf("CooldownRemainingMs: want ~1024000, got %d", state.CooldownRemainingMs)
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

func TestRunWithResilience_AllSignals_SuccessCounters(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	for _, signal := range []string{signalLogs, signalTraces, signalMetrics} {
		SetExporterPolicy(signal, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: true})
	}

	for _, signal := range []string{signalLogs, signalTraces, signalMetrics} {
		if err := RunWithResilience(context.Background(), signal, func(_ context.Context) error {
			return nil
		}); err != nil {
			t.Errorf("signal %s: unexpected error %v", signal, err)
		}
	}

	snap := GetHealthSnapshot()
	// Success counters were removed; verify no failures occurred.
	if snap.LogsExportFailures != 0 {
		t.Errorf("LogsExportFailures: want 0, got %d", snap.LogsExportFailures)
	}
	if snap.TracesExportFailures != 0 {
		t.Errorf("TracesExportFailures: want 0, got %d", snap.TracesExportFailures)
	}
	if snap.MetricsExportFailures != 0 {
		t.Errorf("MetricsExportFailures: want 0, got %d", snap.MetricsExportFailures)
	}
}

func TestRunWithResilience_AllSignals_FailureCounters(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	for _, signal := range []string{signalLogs, signalTraces, signalMetrics} {
		SetExporterPolicy(signal, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: false})
	}

	sentinel := errors.New("export error")
	for _, signal := range []string{signalLogs, signalTraces, signalMetrics} {
		_ = RunWithResilience(context.Background(), signal, func(_ context.Context) error {
			return sentinel
		})
	}

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

func TestRunWithResilience_RetryAttempts_ExactCount(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	SetExporterPolicy(signalLogs, ExporterPolicy{Retries: 2, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: true})

	attempt := 0
	err := RunWithResilience(context.Background(), signalLogs, func(_ context.Context) error {
		attempt++
		if attempt < 3 {
			return errors.New("transient")
		}
		return nil
	})

	if err != nil {
		t.Fatalf("expected nil error after 3 attempts, got %v", err)
	}
	if attempt != 3 {
		t.Errorf("expected 3 attempts, got %d", attempt)
	}

	snap := GetHealthSnapshot()
	if snap.LogsRetries != 2 {
		t.Errorf("LogsRetries: want exactly 2, got %d", snap.LogsRetries)
	}
}

func TestRunWithResilience_NoRetries_RetryCounterIsZero(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	SetExporterPolicy(signalLogs, ExporterPolicy{Retries: 3, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: true})

	err := RunWithResilience(context.Background(), signalLogs, func(_ context.Context) error {
		return nil
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	snap := GetHealthSnapshot()
	if snap.LogsRetries != 0 {
		t.Errorf("LogsRetries: want 0 (no retries needed), got %d", snap.LogsRetries)
	}
}

func TestCB_CooldownCapInCheckCircuitBreaker(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	signal := "cap-check-cb"
	SetExporterPolicy(signal, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: false})

	// Trip the CB with a very high openCount so cooldown exceeds _cbMaxCooldown.
	_tripCircuitBreaker(signal)
	_setOpenCount(signal, 10) // 30s * 2^10 = 30720s, capped at 1024s

	// CB should still be open (rejects).
	fnCalled := false
	_ = RunWithResilience(context.Background(), signal, func(_ context.Context) error {
		fnCalled = true
		return nil
	})
	if fnCalled {
		t.Error("fn should not be called when CB is open with capped cooldown")
	}
}

// TestCB_CooldownUsesMultiplication verifies _checkCircuitBreaker computes cooldown
// as base * 2^openCount (not base / 2^openCount). With openCount=2: correct=120s,
// mutant=7.5s. Set tripped 10s ago → mutant thinks cooldown expired (allows probe),
// correct knows it hasn't (rejects).
func TestCB_CooldownUsesMultiplication(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	signal := "cooldown-mult-test"
	SetExporterPolicy(signal, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: false})

	_tripCircuitBreaker(signal)
	_setOpenCount(signal, 2)                                      // cooldown = 30s * 4 = 120s (correct) vs 30s / 4 = 7.5s (mutant)
	_setCircuitTrippedAt(signal, time.Now().Add(-10*time.Second)) // 10s ago

	// With correct cooldown (120s): elapsed=10s < 120s → CB rejects → fn NOT called.
	// With mutant cooldown (7.5s): elapsed=10s > 7.5s → half-open → fn IS called.
	fnCalled := false
	_ = RunWithResilience(context.Background(), signal, func(_ context.Context) error {
		fnCalled = true
		return nil
	})
	if fnCalled {
		t.Error("fn should not be called — CB cooldown (120s) has not elapsed (only 10s)")
	}
}

func TestCB_SuccessDecaysFromZeroOpenCount(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	signal := "decay-from-zero"
	SetExporterPolicy(signal, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: false})

	// Trip CB, then set openCount to 0 so decay path hits max(0, 0-1) = 0.
	_tripCircuitBreaker(signal)
	_setOpenCount(signal, 0)

	// Advance past cooldown.
	_setCircuitTrippedAt(signal, time.Now().Add(-2*_cbBaseCooldown))

	// This will be a half-open probe; success should decay openCount but it's already 0.
	err := RunWithResilience(context.Background(), signal, func(_ context.Context) error {
		return nil
	})
	if err != nil {
		t.Fatalf("expected nil, got %v", err)
	}

	state := GetCircuitState(signal)
	if state.OpenCount != 0 {
		t.Errorf("OpenCount: want 0, got %d", state.OpenCount)
	}
}

func TestGetCircuitState_HalfOpenProbing(t *testing.T) {
	_resetResiliencePolicies()
	t.Cleanup(_resetResiliencePolicies)

	signal := "half-open-probing-state"

	// Manually set the half-open probing flag.
	_resilienceMu.Lock()
	_halfOpenProbing[signal] = true
	_openCount[signal] = 2
	_resilienceMu.Unlock()

	state := GetCircuitState(signal)
	if state.State != "half-open" {
		t.Errorf("expected half-open, got %s", state.State)
	}
	if state.OpenCount != 2 {
		t.Errorf("OpenCount: want 2, got %d", state.OpenCount)
	}
	if state.CooldownRemainingMs != 0 {
		t.Errorf("CooldownRemainingMs: want 0, got %d", state.CooldownRemainingMs)
	}
}

func TestGetCircuitState_HalfOpenWhenCooldownExpired(t *testing.T) {
	_resetResiliencePolicies()
	t.Cleanup(_resetResiliencePolicies)

	signal := "expired-cooldown-state"
	_tripCircuitBreaker(signal)

	// Move tripped time far into the past so cooldown has expired.
	_setCircuitTrippedAt(signal, time.Now().Add(-2*_cbBaseCooldown))

	state := GetCircuitState(signal)
	if state.State != "half-open" {
		t.Errorf("expected half-open when cooldown expired, got %s", state.State)
	}
	if state.CooldownRemainingMs != 0 {
		t.Errorf("CooldownRemainingMs: want 0, got %d", state.CooldownRemainingMs)
	}
}

func TestRunWithResilience_ZeroTimeout_NoContextWrapping(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	// TimeoutSeconds=0 means no per-request timeout wrapping; CB check is skipped.
	SetExporterPolicy(signalLogs, ExporterPolicy{Retries: 0, BackoffSeconds: 0, TimeoutSeconds: 0, FailOpen: false})

	called := false
	err := RunWithResilience(context.Background(), signalLogs, func(_ context.Context) error {
		called = true
		return nil
	})
	if err != nil {
		t.Fatalf("expected nil, got %v", err)
	}
	if !called {
		t.Error("fn should have been called")
	}

	snap := GetHealthSnapshot()
	if snap.LogsExportFailures != 0 {
		t.Errorf("LogsExportFailures: want 0 (success), got %d", snap.LogsExportFailures)
	}
}

func TestGetCircuitState_CooldownCapInGetCircuitState(t *testing.T) {
	_resetResiliencePolicies()
	t.Cleanup(_resetResiliencePolicies)

	signal := "cap-in-getstate"
	_tripCircuitBreaker(signal)
	_setOpenCount(signal, 10) // triggers cap

	state := GetCircuitState(signal)
	if state.State != "open" {
		t.Errorf("expected open, got %s", state.State)
	}
	// Should be capped at 1024s.
	if state.CooldownRemainingMs > 1024100 {
		t.Errorf("CooldownRemainingMs should be capped at ~1024000, got %d", state.CooldownRemainingMs)
	}
}

func TestRunWithResilience_NegativeRetries_ClampedToOne(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	// Negative retries should be clamped to 1 attempt.
	SetExporterPolicy(signalLogs, ExporterPolicy{Retries: -5, BackoffSeconds: 0, TimeoutSeconds: 5.0, FailOpen: false})

	called := 0
	err := RunWithResilience(context.Background(), signalLogs, func(_ context.Context) error {
		called++
		return nil
	})
	if err != nil {
		t.Fatalf("expected nil, got %v", err)
	}
	if called != 1 {
		t.Errorf("expected 1 call, got %d", called)
	}
}

func TestRunWithResilience_BackoffApplied(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	// With BackoffSeconds=0.05 and Retries=2, if backoff works correctly the total
	// time should be >= 100ms (2 retries * 50ms each).
	policy := ExporterPolicy{
		Retries:        2,
		BackoffSeconds: 0.05,
		TimeoutSeconds: 5.0,
		FailOpen:       false,
	}
	SetExporterPolicy("backoff-test", policy)

	start := time.Now()
	_ = RunWithResilience(context.Background(), "backoff-test", func(_ context.Context) error {
		return errors.New("always fail")
	})
	elapsed := time.Since(start)

	// With 2 retries at 50ms backoff each, should take at least 80ms (allowing some slack).
	if elapsed < 80*time.Millisecond {
		t.Errorf("expected backoff to add >= 80ms, but total elapsed was %v", elapsed)
	}
}

func TestIncExportSuccessIsNoOp(t *testing.T) {
	// _incExportSuccess is a no-op — ensure it does not panic and can be called.
	_incExportSuccess("logs")
	_incExportSuccess("traces")
	_incExportSuccess("metrics")
}
