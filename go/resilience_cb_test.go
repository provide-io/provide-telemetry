// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"testing"
	"time"
)

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
