// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// parity_sampling_test.go validates Go behavioral parity for sampling against
// spec/behavioral_fixtures.yaml: rate=0, rate=1, rate=0.5 statistical, and
// signal validation (invalid/valid signal names) for SetSamplingPolicy and
// ShouldSample.

package telemetry

import (
	"testing"
)

// ── Sampling ─────────────────────────────────────────────────────────────────

func TestParity_Sampling_RateZero_AlwaysDrops(t *testing.T) {
	_resetSamplingPolicies()
	_resetHealth()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetHealth)

	if _, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0.0}); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 100; i++ {
		sampled, err := ShouldSample(signalLogs, "evt")
		if err != nil {
			t.Fatal(err)
		}
		if sampled {
			t.Fatal("rate=0.0 must never sample")
		}
	}
}

func TestParity_Sampling_RateOne_AlwaysKeeps(t *testing.T) {
	_resetSamplingPolicies()
	_resetHealth()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetHealth)

	if _, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 1.0}); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 100; i++ {
		sampled, err := ShouldSample(signalLogs, "evt")
		if err != nil {
			t.Fatal(err)
		}
		if !sampled {
			t.Fatal("rate=1.0 must always sample")
		}
	}
}

func TestParity_Sampling_RateHalf_Statistical(t *testing.T) {
	_resetSamplingPolicies()
	_resetHealth()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetHealth)

	if _, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0.5}); err != nil {
		t.Fatal(err)
	}
	count := 0
	const n = 10000
	for i := 0; i < n; i++ {
		sampled, err := ShouldSample(signalLogs, "evt")
		if err != nil {
			t.Fatal(err)
		}
		if sampled {
			count++
		}
	}
	pct := float64(count) / float64(n) * 100
	if pct < 40 || pct > 60 {
		t.Errorf("rate=0.5: expected 40-60%%, got %.1f%%", pct)
	}
}

// ── Sampling Signal Validation ──────────────────────────────────────────────

func TestParity_Sampling_InvalidSignalErrors(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)

	invalidSignals := []string{"log", "trace", "metric", "events", ""}
	for _, sig := range invalidSignals {
		t.Run(sig, func(t *testing.T) {
			_, err := SetSamplingPolicy(sig, SamplingPolicy{DefaultRate: 1.0})
			if err == nil {
				t.Fatalf("SetSamplingPolicy(%q) should return error", sig)
			}
		})
	}
}

func TestParity_Sampling_ValidSignalsAccepted(t *testing.T) {
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)

	validSignals := []string{"logs", "traces", "metrics"}
	for _, sig := range validSignals {
		t.Run(sig, func(t *testing.T) {
			_, err := SetSamplingPolicy(sig, SamplingPolicy{DefaultRate: 1.0})
			if err != nil {
				t.Fatalf("SetSamplingPolicy(%q) unexpected error: %v", sig, err)
			}
		})
	}
}

func TestParity_ShouldSample_InvalidSignalErrors(t *testing.T) {
	_resetSamplingPolicies()
	_resetHealth()
	t.Cleanup(_resetSamplingPolicies)
	t.Cleanup(_resetHealth)

	_, err := ShouldSample("invalid", "key")
	if err == nil {
		t.Fatal("ShouldSample with invalid signal must return error")
	}
}
