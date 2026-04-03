// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"sync"
	"testing"
)

func TestSamplingPolicy_DefaultWhenNotSet(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)

	policy := GetSamplingPolicy("logs")
	if policy.DefaultRate != 1.0 {
		t.Errorf("expected DefaultRate 1.0, got %f", policy.DefaultRate)
	}
	if policy.Overrides != nil {
		t.Errorf("expected nil Overrides, got %v", policy.Overrides)
	}
}

func TestSetSamplingPolicy_RoundTrip(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)

	policy := SamplingPolicy{
		DefaultRate: 0.75,
		Overrides:   map[string]float64{"foo": 0.25, "bar": 0.9},
	}
	SetSamplingPolicy("traces", policy)
	got := GetSamplingPolicy("traces")

	if got.DefaultRate != policy.DefaultRate {
		t.Errorf("DefaultRate: want %f, got %f", policy.DefaultRate, got.DefaultRate)
	}
	if len(got.Overrides) != len(policy.Overrides) {
		t.Errorf("Overrides length: want %d, got %d", len(policy.Overrides), len(got.Overrides))
	}
	if got.Overrides["foo"] != 0.25 {
		t.Errorf("Overrides[foo]: want 0.25, got %f", got.Overrides["foo"])
	}
	if got.Overrides["bar"] != 0.9 {
		t.Errorf("Overrides[bar]: want 0.9, got %f", got.Overrides["bar"])
	}
}

func TestShouldSample_RateOne_AlwaysTrue(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)

	SetSamplingPolicy("logs", SamplingPolicy{DefaultRate: 1.0})

	for i := 0; i < 100; i++ {
		if !ShouldSample("logs", "event") {
			t.Errorf("expected true at iteration %d", i)
		}
	}
}

func TestShouldSample_RateZero_AlwaysFalse(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)

	SetSamplingPolicy("traces", SamplingPolicy{DefaultRate: 0.0})

	for i := 0; i < 100; i++ {
		if ShouldSample("traces", "span") {
			t.Errorf("expected false at iteration %d", i)
		}
	}
}

func TestShouldSample_Override_UseOverrideRate(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)

	SetSamplingPolicy("metrics", SamplingPolicy{
		DefaultRate: 1.0,
		Overrides:   map[string]float64{"foo": 0.0},
	})

	// key "foo" should always be false (override rate 0.0)
	for i := 0; i < 100; i++ {
		if ShouldSample("metrics", "foo") {
			t.Errorf("expected false for key 'foo' at iteration %d", i)
		}
	}

	// other keys should always be true (default rate 1.0)
	for i := 0; i < 100; i++ {
		if !ShouldSample("metrics", "bar") {
			t.Errorf("expected true for key 'bar' at iteration %d", i)
		}
	}
}

func TestShouldSample_DefaultRate(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)

	SetSamplingPolicy("logs", SamplingPolicy{DefaultRate: 0.5})

	count := 0
	for i := 0; i < 1000; i++ {
		if ShouldSample("logs", "event") {
			count++
		}
	}

	if count < 300 || count > 700 {
		t.Errorf("expected roughly 500 trues out of 1000, got %d", count)
	}
}

func TestShouldSample_HealthCounters(t *testing.T) {
	_resetSamplingPolicies()
	_resetHealth()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetHealth)

	// logs: rate 1.0 -> sampled -> _incLogsEmitted
	SetSamplingPolicy("logs", SamplingPolicy{DefaultRate: 1.0})
	ShouldSample("logs", "e")
	ShouldSample("logs", "e")

	// logs: rate 0.0 -> dropped -> _incLogsDropped
	SetSamplingPolicy("logs", SamplingPolicy{DefaultRate: 0.0})
	ShouldSample("logs", "e")

	// traces: rate 1.0 -> _incSpansStarted
	SetSamplingPolicy("traces", SamplingPolicy{DefaultRate: 1.0})
	ShouldSample("traces", "span")

	// traces: rate 0.0 -> _incSpansDropped
	SetSamplingPolicy("traces", SamplingPolicy{DefaultRate: 0.0})
	ShouldSample("traces", "span")

	// metrics: rate 1.0 -> _incMetricsRecorded
	SetSamplingPolicy("metrics", SamplingPolicy{DefaultRate: 1.0})
	ShouldSample("metrics", "m")

	// metrics: rate 0.0 -> _incMetricsDropped
	SetSamplingPolicy("metrics", SamplingPolicy{DefaultRate: 0.0})
	ShouldSample("metrics", "m")

	snap := GetHealthSnapshot()

	if snap.LogsEmitted != 2 {
		t.Errorf("LogsEmitted: want 2, got %d", snap.LogsEmitted)
	}
	if snap.LogsDropped != 1 {
		t.Errorf("LogsDropped: want 1, got %d", snap.LogsDropped)
	}
	if snap.SpansStarted != 1 {
		t.Errorf("SpansStarted: want 1, got %d", snap.SpansStarted)
	}
	if snap.SpansDropped != 1 {
		t.Errorf("SpansDropped: want 1, got %d", snap.SpansDropped)
	}
	if snap.MetricsRecorded != 1 {
		t.Errorf("MetricsRecorded: want 1, got %d", snap.MetricsRecorded)
	}
	if snap.MetricsDropped != 1 {
		t.Errorf("MetricsDropped: want 1, got %d", snap.MetricsDropped)
	}
}

func TestShouldSample_UnknownSignal_NoHealthCounters(t *testing.T) {
	_resetSamplingPolicies()
	_resetHealth()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetHealth)

	// Unknown signal with default rate 1.0 (no policy set) — should return true
	// but no health counter incremented (unknown signal)
	result := ShouldSample("unknown", "key")
	if !result {
		t.Error("expected true for unknown signal with default rate 1.0")
	}

	snap := GetHealthSnapshot()
	if snap.LogsEmitted != 0 || snap.SpansStarted != 0 || snap.MetricsRecorded != 0 {
		t.Errorf("unexpected health counter increments for unknown signal: %+v", snap)
	}
}

func TestSamplingConcurrency(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)

	const goroutines = 50
	const iterations = 100

	var wg sync.WaitGroup
	wg.Add(goroutines)
	for i := 0; i < goroutines; i++ {
		go func(id int) {
			defer wg.Done()
			for j := 0; j < iterations; j++ {
				SetSamplingPolicy("logs", SamplingPolicy{DefaultRate: 0.5})
				SetSamplingPolicy("traces", SamplingPolicy{DefaultRate: 1.0, Overrides: map[string]float64{"k": 0.0}})
				_ = GetSamplingPolicy("logs")
				_ = ShouldSample("logs", "event")
				_ = ShouldSample("traces", "k")
				_ = ShouldSample("metrics", "m")
			}
		}(i)
	}
	wg.Wait()
}
