// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

//go:build !nogovernance

package telemetry

import (
	"context"
	"log/slog"
	"testing"
)

// TestLogger_BackpressureFull_DropsRecord verifies that Handle drops the record
// when the log queue is full (covers the TryAcquire=false branch in Handle).
func TestLogger_BackpressureFull_DropsRecord(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)
	_resetHealth()
	t.Cleanup(_resetHealth)

	// Fill the log queue with one slot and acquire it.
	SetQueuePolicy(QueuePolicy{LogsMaxSize: 1, TracesMaxSize: 64, MetricsMaxSize: 64})
	t.Cleanup(func() {
		SetQueuePolicy(QueuePolicy{LogsMaxSize: 64, TracesMaxSize: 64, MetricsMaxSize: 64})
	})

	ticket := TryAcquire(signalLogs)
	if !ticket {
		t.Fatal("expected to acquire the only log slot")
	}
	t.Cleanup(func() { Release(signalLogs) })

	before := GetHealthSnapshot()
	logger := GetLogger(context.Background(), "test.backpressure.logger")
	logger.Info("should.be.dropped.by.backpressure")

	after := GetHealthSnapshot()
	if after.LogsEmitted != before.LogsEmitted {
		t.Errorf("LogsEmitted should not increase when queue is full: before=%d after=%d",
			before.LogsEmitted, after.LogsEmitted)
	}
	if after.LogsDropped != before.LogsDropped+1 {
		t.Errorf("LogsDropped should increase by 1 when queue is full: before=%d after=%d",
			before.LogsDropped, after.LogsDropped)
	}
}

// TestLogger_ConsentNone_DropsRecord verifies that the slog handler drops
// records when consent is set to None (covers the ShouldAllow=false branch).
func TestLogger_ConsentNone_DropsRecord(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	_resetHealth()
	t.Cleanup(_resetHealth)

	SetConsentLevel(ConsentNone)

	before := GetHealthSnapshot()
	logger := GetLogger(context.Background(), "test.consent.logger")
	logger.Info("should.be.dropped", slog.String("key", "val"))

	after := GetHealthSnapshot()
	if after.LogsEmitted != before.LogsEmitted {
		t.Errorf("LogsEmitted should not increase under ConsentNone: before=%d after=%d",
			before.LogsEmitted, after.LogsEmitted)
	}
}

// TestTrace_ConsentNone_FnStillRuns verifies that Trace calls fn even when
// consent is None (covers the ShouldAllow=false branch in Trace).
func TestTrace_ConsentNone_FnStillRuns(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	_resetHealth()
	t.Cleanup(_resetHealth)

	SetConsentLevel(ConsentNone)

	called := false
	err := Trace(context.Background(), "test.consent.trace", func(ctx context.Context) error {
		called = true
		return nil
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !called {
		t.Error("fn must still be called when consent gate rejects")
	}

	snap := GetHealthSnapshot()
	if snap.TracesEmitted != 0 {
		t.Errorf("TracesEmitted should be 0 under ConsentNone, got %d", snap.TracesEmitted)
	}
}

// TestCounter_ConsentNone_DropsAdd verifies Counter.Add drops under ConsentNone.
func TestCounter_ConsentNone_DropsAdd(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	_resetHealth()
	t.Cleanup(_resetHealth)

	SetConsentLevel(ConsentNone)

	before := GetHealthSnapshot()
	c := NewCounter("test.consent.counter")
	c.Add(context.Background(), 1)

	after := GetHealthSnapshot()
	if after.MetricsEmitted != before.MetricsEmitted {
		t.Errorf("MetricsEmitted should not increase under ConsentNone: before=%d after=%d",
			before.MetricsEmitted, after.MetricsEmitted)
	}
}

// TestGauge_ConsentNone_DropsSet verifies Gauge.Set drops under ConsentNone.
func TestGauge_ConsentNone_DropsSet(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	_resetHealth()
	t.Cleanup(_resetHealth)

	SetConsentLevel(ConsentNone)

	before := GetHealthSnapshot()
	g := NewGauge("test.consent.gauge")
	g.Set(context.Background(), 3.14)

	after := GetHealthSnapshot()
	if after.MetricsEmitted != before.MetricsEmitted {
		t.Errorf("MetricsEmitted should not increase under ConsentNone: before=%d after=%d",
			before.MetricsEmitted, after.MetricsEmitted)
	}
}

// TestHistogram_ConsentNone_DropsRecord verifies Histogram.Record drops under ConsentNone.
func TestHistogram_ConsentNone_DropsRecord(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	_resetHealth()
	t.Cleanup(_resetHealth)

	SetConsentLevel(ConsentNone)

	before := GetHealthSnapshot()
	h := NewHistogram("test.consent.histogram")
	h.Record(context.Background(), 42.0)

	after := GetHealthSnapshot()
	if after.MetricsEmitted != before.MetricsEmitted {
		t.Errorf("MetricsEmitted should not increase under ConsentNone: before=%d after=%d",
			before.MetricsEmitted, after.MetricsEmitted)
	}
}
