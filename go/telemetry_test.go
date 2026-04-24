// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"regexp"
	"testing"
)

// TestEvent_ValidSegments verifies that Event returns a correctly populated EventRecord.
func TestEvent_ValidSegments(t *testing.T) {
	evt, err := Event("db", "query", "ok")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if evt.Event != "db.query.ok" {
		t.Errorf("want Event=%q, got %q", "db.query.ok", evt.Event)
	}
}

func TestEvent_InvalidSegments(t *testing.T) {
	_, err := Event("too_short")
	if err == nil {
		t.Fatal("expected error for single segment")
	}
}

// TestRegisterCardinalityLimit is a thin wrapper around SetCardinalityLimit.
func TestRegisterCardinalityLimit(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	RegisterCardinalityLimit("env", CardinalityLimit{MaxValues: 5, TTLSeconds: 60})
	got := GetCardinalityLimit("env")
	if got.MaxValues != 5 {
		t.Errorf("want MaxValues=5, got %d", got.MaxValues)
	}
}

// TestGetCardinalityLimits verifies the snapshot returned by the new exported function.
func TestGetCardinalityLimits_Empty(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	limits := GetCardinalityLimits()
	if len(limits) != 0 {
		t.Errorf("expected empty map, got %d entries", len(limits))
	}
}

func TestGetCardinalityLimits_WithEntries(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("region", CardinalityLimit{MaxValues: 10, TTLSeconds: 30})
	SetCardinalityLimit("env", CardinalityLimit{MaxValues: 5, TTLSeconds: 60})

	limits := GetCardinalityLimits()
	if len(limits) != 2 {
		t.Fatalf("expected 2 entries, got %d", len(limits))
	}
	if limits["region"].MaxValues != 10 {
		t.Errorf("region: want MaxValues=10, got %d", limits["region"].MaxValues)
	}
	if limits["env"].MaxValues != 5 {
		t.Errorf("env: want MaxValues=5, got %d", limits["env"].MaxValues)
	}
}

// TestClearCardinalityLimits verifies the exported clear wrapper.
func TestClearCardinalityLimits(t *testing.T) {
	SetCardinalityLimit("zone", CardinalityLimit{MaxValues: 3, TTLSeconds: 10})
	ClearCardinalityLimits()

	limits := GetCardinalityLimits()
	if len(limits) != 0 {
		t.Errorf("expected empty map after clear, got %d entries", len(limits))
	}
}

// TestRegisterPIIRule appends a single rule.
func TestRegisterPIIRule(t *testing.T) {
	_resetPIIRules()
	t.Cleanup(_resetPIIRules)

	RegisterPIIRule(PIIRule{Path: []string{"user", "ssn"}, Mode: PIIModeRedact})
	rules := GetPIIRules()
	if len(rules) != 1 {
		t.Fatalf("expected 1 rule, got %d", len(rules))
	}
	if rules[0].Mode != PIIModeRedact {
		t.Errorf("want mode=%q, got %q", PIIModeRedact, rules[0].Mode)
	}
}

func TestRegisterPIIRule_Accumulates(t *testing.T) {
	_resetPIIRules()
	t.Cleanup(_resetPIIRules)

	RegisterPIIRule(PIIRule{Path: []string{"a"}, Mode: PIIModeRedact})
	RegisterPIIRule(PIIRule{Path: []string{"b"}, Mode: PIIModeDrop})

	rules := GetPIIRules()
	if len(rules) != 2 {
		t.Fatalf("expected 2 rules, got %d", len(rules))
	}
}

// TestReplacePIIRules is a thin alias for SetPIIRules.
func TestReplacePIIRules(t *testing.T) {
	_resetPIIRules()
	t.Cleanup(_resetPIIRules)

	RegisterPIIRule(PIIRule{Path: []string{"old"}, Mode: PIIModeRedact})

	ReplacePIIRules([]PIIRule{
		{Path: []string{"new1"}, Mode: PIIModeHash},
		{Path: []string{"new2"}, Mode: PIIModeDrop},
	})

	rules := GetPIIRules()
	if len(rules) != 2 {
		t.Fatalf("expected 2 rules after replace, got %d", len(rules))
	}
	if rules[0].Mode != PIIModeHash {
		t.Errorf("want mode=%q, got %q", PIIModeHash, rules[0].Mode)
	}
}

// TestResetForTests verifies the exported testing helper resets all subsystems.
func TestResetForTests(t *testing.T) {
	// Pollute state across multiple subsystems.
	basePatternCount := len(GetSecretPatterns())
	SetCardinalityLimit("x", CardinalityLimit{MaxValues: 99})
	RegisterPIIRule(PIIRule{Path: []string{"secret"}, Mode: PIIModeRedact})
	RegisterSecretPattern("test-reset", regexp.MustCompile(`RESETME`))
	if _, err := SetSamplingPolicy("logs", SamplingPolicy{DefaultRate: 0.1}); err != nil {
		t.Fatal(err)
	}
	SetExporterPolicy("traces", ExporterPolicy{Retries: 10})

	ResetForTests()

	// Cardinality cleared.
	if len(GetCardinalityLimits()) != 0 {
		t.Error("expected cardinality limits cleared")
	}
	// PII cleared.
	if len(GetPIIRules()) != 0 {
		t.Error("expected PII rules cleared")
	}
	// Sampling reset (default rate = 1.0 when nothing registered).
	if p, err := GetSamplingPolicy("logs"); err != nil {
		t.Fatal(err)
	} else if p.DefaultRate != 1.0 {
		t.Errorf("expected sampling DefaultRate=1.0, got %v", p.DefaultRate)
	}
	// Resilience reset (default retries).
	if p := GetExporterPolicy("traces"); p.Retries != _defaultRetries {
		t.Errorf("expected default retries=%d, got %d", _defaultRetries, p.Retries)
	}
	// Custom secret patterns cleared.
	if got := len(GetSecretPatterns()); got != basePatternCount {
		t.Errorf("expected custom secret patterns cleared, got %d patterns (want %d)", got, basePatternCount)
	}
	// Setup state cleared.
	if GetRuntimeConfig() != nil {
		t.Error("expected nil runtime config after ResetForTests")
	}
	if Logger != nil {
		t.Error("expected nil logger after ResetForTests")
	}
}
