// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"math"
	"sync"
	"testing"
)

func TestSamplingPolicy_DefaultWhenNotSet(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)

	policy, err := GetSamplingPolicy(signalLogs)
	if err != nil {
		t.Fatal(err)
	}
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
	if _, err := SetSamplingPolicy(signalTraces, policy); err != nil {
		t.Fatal(err)
	}
	got, err := GetSamplingPolicy(signalTraces)
	if err != nil {
		t.Fatal(err)
	}

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

	if _, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 1.0}); err != nil {
		t.Fatal(err)
	}

	for i := 0; i < 100; i++ {
		sampled, err := ShouldSample(signalLogs, "event")
		if err != nil {
			t.Fatal(err)
		}
		if !sampled {
			t.Errorf("expected true at iteration %d", i)
		}
	}
}

func TestShouldSample_RateZero_AlwaysFalse(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)

	if _, err := SetSamplingPolicy(signalTraces, SamplingPolicy{DefaultRate: 0.0}); err != nil {
		t.Fatal(err)
	}

	for i := 0; i < 100; i++ {
		sampled, err := ShouldSample(signalTraces, "span")
		if err != nil {
			t.Fatal(err)
		}
		if sampled {
			t.Errorf("expected false at iteration %d", i)
		}
	}
}

func TestShouldSample_Override_UseOverrideRate(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)

	if _, err := SetSamplingPolicy(signalMetrics, SamplingPolicy{
		DefaultRate: 1.0,
		Overrides:   map[string]float64{"foo": 0.0},
	}); err != nil {
		t.Fatal(err)
	}

	// key "foo" should always be false (override rate 0.0)
	for i := 0; i < 100; i++ {
		sampled, err := ShouldSample(signalMetrics, "foo")
		if err != nil {
			t.Fatal(err)
		}
		if sampled {
			t.Errorf("expected false for key 'foo' at iteration %d", i)
		}
	}

	// other keys should always be true (default rate 1.0)
	for i := 0; i < 100; i++ {
		sampled, err := ShouldSample(signalMetrics, "bar")
		if err != nil {
			t.Fatal(err)
		}
		if !sampled {
			t.Errorf("expected true for key 'bar' at iteration %d", i)
		}
	}
}

func TestShouldSample_DefaultRate(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)

	if _, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0.5}); err != nil {
		t.Fatal(err)
	}

	count := 0
	for i := 0; i < 1000; i++ {
		sampled, err := ShouldSample(signalLogs, "event")
		if err != nil {
			t.Fatal(err)
		}
		if sampled {
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
	if _, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 1.0}); err != nil {
		t.Fatal(err)
	}
	if _, err := ShouldSample(signalLogs, "e"); err != nil {
		t.Fatal(err)
	}
	if _, err := ShouldSample(signalLogs, "e"); err != nil {
		t.Fatal(err)
	}

	// logs: rate 0.0 -> dropped -> _incLogsDropped
	if _, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0.0}); err != nil {
		t.Fatal(err)
	}
	if _, err := ShouldSample(signalLogs, "e"); err != nil {
		t.Fatal(err)
	}

	// traces: rate 1.0 -> _incEmitted(signalTraces)
	if _, err := SetSamplingPolicy(signalTraces, SamplingPolicy{DefaultRate: 1.0}); err != nil {
		t.Fatal(err)
	}
	if _, err := ShouldSample(signalTraces, "span"); err != nil {
		t.Fatal(err)
	}

	// traces: rate 0.0 -> _incSpansDropped
	if _, err := SetSamplingPolicy(signalTraces, SamplingPolicy{DefaultRate: 0.0}); err != nil {
		t.Fatal(err)
	}
	if _, err := ShouldSample(signalTraces, "span"); err != nil {
		t.Fatal(err)
	}

	// metrics: rate 1.0 -> _incEmitted(signalMetrics)
	if _, err := SetSamplingPolicy(signalMetrics, SamplingPolicy{DefaultRate: 1.0}); err != nil {
		t.Fatal(err)
	}
	if _, err := ShouldSample(signalMetrics, "m"); err != nil {
		t.Fatal(err)
	}

	// metrics: rate 0.0 -> _incMetricsDropped
	if _, err := SetSamplingPolicy(signalMetrics, SamplingPolicy{DefaultRate: 0.0}); err != nil {
		t.Fatal(err)
	}
	if _, err := ShouldSample(signalMetrics, "m"); err != nil {
		t.Fatal(err)
	}

	snap := GetHealthSnapshot()

	if snap.LogsEmitted != 2 {
		t.Errorf("LogsEmitted: want 2, got %d", snap.LogsEmitted)
	}
	if snap.LogsDropped != 1 {
		t.Errorf("LogsDropped: want 1, got %d", snap.LogsDropped)
	}
	if snap.TracesEmitted != 1 {
		t.Errorf("TracesEmitted: want 1, got %d", snap.TracesEmitted)
	}
	if snap.TracesDropped != 1 {
		t.Errorf("TracesDropped: want 1, got %d", snap.TracesDropped)
	}
	if snap.MetricsEmitted != 1 {
		t.Errorf("MetricsEmitted: want 1, got %d", snap.MetricsEmitted)
	}
	if snap.MetricsDropped != 1 {
		t.Errorf("MetricsDropped: want 1, got %d", snap.MetricsDropped)
	}
}

func TestShouldSample_UnknownSignal_ReturnsError(t *testing.T) {
	_resetSamplingPolicies()
	_resetHealth()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetHealth)

	// Unknown signal must return an error.
	_, err := ShouldSample("unknown", "key")
	if err == nil {
		t.Fatal("expected error for unknown signal")
	}

	snap := GetHealthSnapshot()
	if snap.LogsEmitted != 0 || snap.TracesEmitted != 0 || snap.MetricsEmitted != 0 {
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
				_, _ = SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0.5})
				_, _ = SetSamplingPolicy(signalTraces, SamplingPolicy{DefaultRate: 1.0, Overrides: map[string]float64{"k": 0.0}})
				_, _ = GetSamplingPolicy(signalLogs)
				_, _ = ShouldSample(signalLogs, "event")
				_, _ = ShouldSample(signalTraces, "k")
				_, _ = ShouldSample(signalMetrics, "m")
			}
		}(i)
	}
	wg.Wait()
}

// ── Kill CONDITIONALS_NEGATION at sampling.go:74 ─────────────────────────────
// Negation inverts `rand.Float64() < rate` to `>= rate`, flipping which half
// passes. With rate=0.99, correct code samples ~99%; negation samples ~1%.

func TestShouldSample_HighRate_AlmostAlwaysTrue(t *testing.T) {
	_resetSamplingPolicies()
	_resetHealth()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetHealth)

	if _, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0.99}); err != nil {
		t.Fatal(err)
	}

	count := 0
	const n = 1000
	for i := 0; i < n; i++ {
		sampled, err := ShouldSample(signalLogs, "event")
		if err != nil {
			t.Fatal(err)
		}
		if sampled {
			count++
		}
	}
	if count < 900 {
		t.Errorf("at rate=0.99, expected >900 sampled out of %d, got %d", n, count)
	}
}

func TestShouldSample_LowRate_AlmostAlwaysFalse(t *testing.T) {
	_resetSamplingPolicies()
	_resetHealth()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetHealth)

	if _, err := SetSamplingPolicy(signalTraces, SamplingPolicy{DefaultRate: 0.01}); err != nil {
		t.Fatal(err)
	}

	count := 0
	const n = 1000
	for i := 0; i < n; i++ {
		sampled, err := ShouldSample(signalTraces, "span")
		if err != nil {
			t.Fatal(err)
		}
		if sampled {
			count++
		}
	}
	if count > 100 {
		t.Errorf("at rate=0.01, expected <100 sampled out of %d, got %d", n, count)
	}
}

func TestSetSamplingPolicy_ClampsAboveOne(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)
	p, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 1.5})
	if err != nil {
		t.Fatal(err)
	}
	if p.DefaultRate != 1.0 {
		t.Errorf("expected rate clamped to 1.0, got %f", p.DefaultRate)
	}
}

func TestSetSamplingPolicy_ClampsBelowZero(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)
	p, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: -0.5})
	if err != nil {
		t.Fatal(err)
	}
	if p.DefaultRate != 0.0 {
		t.Errorf("expected rate clamped to 0.0, got %f", p.DefaultRate)
	}
}
