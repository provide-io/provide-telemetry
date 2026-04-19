// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"testing"
	"time"
)

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
