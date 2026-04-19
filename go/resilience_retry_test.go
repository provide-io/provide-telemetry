// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"testing"
	"time"
)

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
