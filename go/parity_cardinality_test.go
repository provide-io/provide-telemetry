// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// parity_cardinality_test.go validates Go behavioral parity for cardinality
// clamping against spec/behavioral_fixtures.yaml: MaxValues zero/negative
// clamped to 1, TTLSeconds zero/negative clamped to 1.0, and valid values
// passed through unchanged.

package telemetry

import (
	"testing"
)

// ── Cardinality Clamping ────────────────────────────────────────────────────

func TestParity_Cardinality_ZeroMaxValuesClamped(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("k", CardinalityLimit{MaxValues: 0, TTLSeconds: 10.0})
	got := GetCardinalityLimit("k")
	if got.MaxValues != 1 {
		t.Fatalf("expected MaxValues clamped to 1, got %d", got.MaxValues)
	}
	if got.TTLSeconds != 10.0 {
		t.Fatalf("expected TTLSeconds 10.0, got %f", got.TTLSeconds)
	}
}

func TestParity_Cardinality_NegativeMaxValuesClamped(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("k", CardinalityLimit{MaxValues: -5, TTLSeconds: 10.0})
	got := GetCardinalityLimit("k")
	if got.MaxValues != 1 {
		t.Fatalf("expected MaxValues clamped to 1, got %d", got.MaxValues)
	}
}

func TestParity_Cardinality_ZeroTTLClamped(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("k", CardinalityLimit{MaxValues: 10, TTLSeconds: 0.0})
	got := GetCardinalityLimit("k")
	if got.TTLSeconds != 1.0 {
		t.Fatalf("expected TTLSeconds clamped to 1.0, got %f", got.TTLSeconds)
	}
}

func TestParity_Cardinality_NegativeTTLClamped(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("k", CardinalityLimit{MaxValues: 10, TTLSeconds: -3.0})
	got := GetCardinalityLimit("k")
	if got.TTLSeconds != 1.0 {
		t.Fatalf("expected TTLSeconds clamped to 1.0, got %f", got.TTLSeconds)
	}
}

func TestParity_Cardinality_ValidValuesUnchanged(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("k", CardinalityLimit{MaxValues: 50, TTLSeconds: 300.0})
	got := GetCardinalityLimit("k")
	if got.MaxValues != 50 {
		t.Fatalf("expected MaxValues 50, got %d", got.MaxValues)
	}
	if got.TTLSeconds != 300.0 {
		t.Fatalf("expected TTLSeconds 300.0, got %f", got.TTLSeconds)
	}
}

// ── Cardinality Saturation ──────────────────────────────────────────────────
// Parity category: cardinality_saturation — once a limit is registered for
// a key, the (N+1)-th distinct value is replaced by the "__overflow__"
// sentinel.

func TestParity_Cardinality_Saturation_FourthValueOverflows(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	RegisterCardinalityLimit("route", CardinalityLimit{MaxValues: 3, TTLSeconds: 300.0})

	values := []string{"/a", "/b", "/c", "/d"}
	want := []string{"/a", "/b", "/c", _overflowValue}
	got := make([]string, 0, len(values))
	for _, v := range values {
		out := GuardAttributes(map[string]string{"route": v})
		got = append(got, out["route"])
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("value %d: expected %q, got %q (full sequence: %v)", i, want[i], got[i], got)
		}
	}
	if _overflowValue != "__overflow__" {
		t.Fatalf("overflow sentinel must be \"__overflow__\", got %q", _overflowValue)
	}
}
