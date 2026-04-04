// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/sony/gobreaker"
)

func TestGetExporterPolicy_Defaults(t *testing.T) {
	_resetResiliencePolicies()
	t.Cleanup(_resetResiliencePolicies)

	for _, signal := range []string{signalLogs, signalTraces, signalMetrics, "unknown"} {
		policy := GetExporterPolicy(signal)
		if policy.Retries != _defaultRetries {
			t.Errorf("%s: Retries want %d, got %d", signal, _defaultRetries, policy.Retries)
		}
		if policy.BackoffSeconds != _defaultBackoffSeconds {
			t.Errorf("%s: BackoffSeconds want %f, got %f", signal, _defaultBackoffSeconds, policy.BackoffSeconds)
		}
		if policy.TimeoutSeconds != _defaultTimeoutSeconds {
			t.Errorf("%s: TimeoutSeconds want %f, got %f", signal, _defaultTimeoutSeconds, policy.TimeoutSeconds)
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

	fastPolicy := ExporterPolicy{Retries: 1, BackoffSeconds: 0.001, TimeoutSeconds: 5.0, FailOpen: true}
	SetExporterPolicy(signalLogs, fastPolicy)

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
	if snap.LogsExportedOK != 1 {
		t.Errorf("LogsExportedOK: want 1, got %d", snap.LogsExportedOK)
	}
}

func TestRunWithResilience_RetriesOnTransientError(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	fastPolicy := ExporterPolicy{Retries: 3, BackoffSeconds: 0.001, TimeoutSeconds: 5.0, FailOpen: true}
	SetExporterPolicy(signalTraces, fastPolicy)

	attempt := 0
	err := RunWithResilience(context.Background(), signalTraces, func(_ context.Context) error {
		attempt++
		if attempt < 2 {
			return errors.New("transient")
		}
		return nil
	})

	if err != nil {
		t.Fatalf("expected nil error after retry, got %v", err)
	}
	if attempt != 2 {
		t.Errorf("expected 2 attempts, got %d", attempt)
	}

	snap := GetHealthSnapshot()
	if snap.SpansExportedOK != 1 {
		t.Errorf("SpansExportedOK: want 1, got %d", snap.SpansExportedOK)
	}
	if snap.RetryAttempts < 1 {
		t.Errorf("RetryAttempts: want >= 1, got %d", snap.RetryAttempts)
	}
}

func TestRunWithResilience_FailsAfterAllRetries(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	fastPolicy := ExporterPolicy{Retries: 2, BackoffSeconds: 0.001, TimeoutSeconds: 5.0, FailOpen: false}
	SetExporterPolicy(signalMetrics, fastPolicy)

	sentinel := errors.New("permanent")
	err := RunWithResilience(context.Background(), signalMetrics, func(_ context.Context) error {
		return sentinel
	})

	if err == nil {
		t.Fatal("expected error after all retries, got nil")
	}

	snap := GetHealthSnapshot()
	if snap.MetricsExportErrors != 1 {
		t.Errorf("MetricsExportErrors: want 1, got %d", snap.MetricsExportErrors)
	}
}

func TestRunWithResilience_FailOpen_CircuitBreakerOpen_ReturnsNil(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	// Use a policy with very tight CB settings by directly injecting a pre-opened CB.
	failPolicy := ExporterPolicy{Retries: 1, BackoffSeconds: 0.001, TimeoutSeconds: 5.0, FailOpen: true}
	SetExporterPolicy(signalLogs, failPolicy)

	// Trip the circuit breaker by forcing 5 consecutive failures.
	sentinel := errors.New("force open")
	for i := 0; i < 5; i++ {
		_ = RunWithResilience(context.Background(), signalLogs, func(_ context.Context) error {
			return sentinel
		})
	}

	// Reset health so we can observe the next call cleanly.
	_resetHealth()

	// Now the CB should be open; with FailOpen=true, RunWithResilience returns nil.
	err := RunWithResilience(context.Background(), signalLogs, func(_ context.Context) error {
		t.Error("fn must not be called when circuit breaker is open")
		return nil
	})

	if err != nil {
		t.Fatalf("FailOpen=true: expected nil, got %v", err)
	}

	snap := GetHealthSnapshot()
	if snap.CircuitBreakerTrips != 1 {
		t.Errorf("CircuitBreakerTrips: want 1, got %d", snap.CircuitBreakerTrips)
	}
}

func TestRunWithResilience_FailClosed_CircuitBreakerOpen_ReturnsError(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	failPolicy := ExporterPolicy{Retries: 1, BackoffSeconds: 0.001, TimeoutSeconds: 5.0, FailOpen: false}
	SetExporterPolicy(signalTraces, failPolicy)

	sentinel := errors.New("force open")
	for i := 0; i < 5; i++ {
		_ = RunWithResilience(context.Background(), signalTraces, func(_ context.Context) error {
			return sentinel
		})
	}

	// CB should be open now.
	err := RunWithResilience(context.Background(), signalTraces, func(_ context.Context) error {
		t.Error("fn must not be called when circuit breaker is open")
		return nil
	})

	if err == nil {
		t.Fatal("FailOpen=false: expected error when circuit breaker is open, got nil")
	}

	if !errors.Is(err, gobreaker.ErrOpenState) && !errors.Is(err, gobreaker.ErrTooManyRequests) {
		t.Errorf("expected gobreaker open/too-many-requests error, got: %v", err)
	}
}

func TestRunWithResilience_ContextTimeoutPropagated(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	fastPolicy := ExporterPolicy{Retries: 1, BackoffSeconds: 0.001, TimeoutSeconds: 5.0, FailOpen: false}
	SetExporterPolicy(signalLogs, fastPolicy)

	// Create a context that is already cancelled.
	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Millisecond)
	defer cancel()
	time.Sleep(5 * time.Millisecond) // ensure it has expired

	err := RunWithResilience(ctx, signalLogs, func(inner context.Context) error {
		return inner.Err()
	})

	if err == nil {
		t.Fatal("expected timeout error, got nil")
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

func TestGetExporterPolicy_UnknownSignal_UsesDefault(t *testing.T) {
	_resetResiliencePolicies()
	t.Cleanup(_resetResiliencePolicies)

	policy := GetExporterPolicy("bogus-signal")
	if policy.Retries != _defaultRetries {
		t.Errorf("Retries: want %d, got %d", _defaultRetries, policy.Retries)
	}
	if policy.BackoffSeconds != _defaultBackoffSeconds {
		t.Errorf("BackoffSeconds: want %f, got %f", _defaultBackoffSeconds, policy.BackoffSeconds)
	}
	if policy.TimeoutSeconds != _defaultTimeoutSeconds {
		t.Errorf("TimeoutSeconds: want %f, got %f", _defaultTimeoutSeconds, policy.TimeoutSeconds)
	}
	if !policy.FailOpen {
		t.Error("FailOpen: want true, got false")
	}
}

func TestRunWithResilience_AllSignals_SuccessCounters(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	fastPolicy := ExporterPolicy{Retries: 1, BackoffSeconds: 0.001, TimeoutSeconds: 5.0, FailOpen: true}
	for _, signal := range []string{signalLogs, signalTraces, signalMetrics} {
		SetExporterPolicy(signal, fastPolicy)
	}

	for _, signal := range []string{signalLogs, signalTraces, signalMetrics} {
		if err := RunWithResilience(context.Background(), signal, func(_ context.Context) error {
			return nil
		}); err != nil {
			t.Errorf("signal %s: unexpected error %v", signal, err)
		}
	}

	snap := GetHealthSnapshot()
	if snap.LogsExportedOK != 1 {
		t.Errorf("LogsExportedOK: want 1, got %d", snap.LogsExportedOK)
	}
	if snap.SpansExportedOK != 1 {
		t.Errorf("SpansExportedOK: want 1, got %d", snap.SpansExportedOK)
	}
	if snap.MetricsExportedOK != 1 {
		t.Errorf("MetricsExportedOK: want 1, got %d", snap.MetricsExportedOK)
	}
}

func TestRunWithResilience_AllSignals_FailureCounters(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	fastPolicy := ExporterPolicy{Retries: 1, BackoffSeconds: 0.001, TimeoutSeconds: 5.0, FailOpen: false}
	for _, signal := range []string{signalLogs, signalTraces, signalMetrics} {
		SetExporterPolicy(signal, fastPolicy)
	}

	sentinel := errors.New("export error")
	for _, signal := range []string{signalLogs, signalTraces, signalMetrics} {
		_ = RunWithResilience(context.Background(), signal, func(_ context.Context) error {
			return sentinel
		})
	}

	snap := GetHealthSnapshot()
	if snap.LogsExportErrors != 1 {
		t.Errorf("LogsExportErrors: want 1, got %d", snap.LogsExportErrors)
	}
	if snap.SpansExportErrors != 1 {
		t.Errorf("SpansExportErrors: want 1, got %d", snap.SpansExportErrors)
	}
	if snap.MetricsExportErrors != 1 {
		t.Errorf("MetricsExportErrors: want 1, got %d", snap.MetricsExportErrors)
	}
}

func TestRunWithResilience_UnknownSignal_UsesDefault(t *testing.T) {
	_resetResiliencePolicies()
	_resetHealth()
	t.Cleanup(_resetResiliencePolicies)
	t.Cleanup(_resetHealth)

	// Unknown signal should use default policy (FailOpen=true) and succeed.
	err := RunWithResilience(context.Background(), "unknown", func(_ context.Context) error {
		return nil
	})
	if err != nil {
		t.Fatalf("unknown signal: expected nil error, got %v", err)
	}
}

func TestGetCircuitBreaker_ConcurrentLazyInit(t *testing.T) {
	_resetResiliencePolicies()
	t.Cleanup(_resetResiliencePolicies)

	// Race many goroutines through _getCircuitBreaker for a fresh signal to trigger
	// the double-check path inside the write lock.
	const goroutines = 20
	const freshSignal = "concurrent-lazy-signal"

	start := make(chan struct{})
	done := make(chan struct{}, goroutines)

	for i := 0; i < goroutines; i++ {
		go func() {
			<-start
			cb := _getCircuitBreaker(freshSignal)
			if cb == nil {
				t.Errorf("_getCircuitBreaker returned nil")
			}
			done <- struct{}{}
		}()
	}

	close(start)
	for i := 0; i < goroutines; i++ {
		<-done
	}
}
