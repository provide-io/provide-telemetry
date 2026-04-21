// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

//go:build !nogovernance

package telemetry

import (
	"testing"
)

func TestConsentDefaultIsFull(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	if got := GetConsentLevel(); got != ConsentFull {
		t.Errorf("expected ConsentFull, got %v", got)
	}
}

func TestConsentFullAllowsAllSignals(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	SetConsentLevel(ConsentFull)
	signals := []struct {
		signal   string
		logLevel string
	}{
		{"logs", "DEBUG"},
		{"traces", ""},
		{"metrics", ""},
		{"context", ""},
	}
	for _, s := range signals {
		if !ShouldAllow(s.signal, s.logLevel) {
			t.Errorf("expected FULL to allow %s", s.signal)
		}
	}
}

func TestConsentNoneBlocksAllSignals(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	SetConsentLevel(ConsentNone)
	signals := []struct {
		signal   string
		logLevel string
	}{
		{"logs", "ERROR"},
		{"traces", ""},
		{"metrics", ""},
		{"context", ""},
	}
	for _, s := range signals {
		if ShouldAllow(s.signal, s.logLevel) {
			t.Errorf("expected NONE to block %s", s.signal)
		}
	}
}

func TestConsentFunctionalLogThresholds(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	SetConsentLevel(ConsentFunctional)

	tests := []struct {
		logLevel string
		want     bool
	}{
		{"DEBUG", false},
		{"INFO", false},
		{"WARNING", true},
		{"WARN", true},
		{"ERROR", true},
		{"CRITICAL", true},
		{"", false},
	}
	for _, tt := range tests {
		got := ShouldAllow("logs", tt.logLevel)
		if got != tt.want {
			t.Errorf("FUNCTIONAL logs %q: got %v, want %v", tt.logLevel, got, tt.want)
		}
	}
}

func TestConsentFunctionalTracesAndMetricsAllowed(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	SetConsentLevel(ConsentFunctional)
	if !ShouldAllow("traces", "") {
		t.Error("expected FUNCTIONAL to allow traces")
	}
	if !ShouldAllow("metrics", "") {
		t.Error("expected FUNCTIONAL to allow metrics")
	}
}

func TestConsentFunctionalContextBlocked(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	SetConsentLevel(ConsentFunctional)
	if ShouldAllow("context", "") {
		t.Error("expected FUNCTIONAL to block context")
	}
}

func TestConsentMinimalLogThresholds(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	SetConsentLevel(ConsentMinimal)

	tests := []struct {
		logLevel string
		want     bool
	}{
		{"DEBUG", false},
		{"INFO", false},
		{"WARNING", false},
		{"ERROR", true},
		{"CRITICAL", true},
		{"", false},
	}
	for _, tt := range tests {
		got := ShouldAllow("logs", tt.logLevel)
		if got != tt.want {
			t.Errorf("MINIMAL logs %q: got %v, want %v", tt.logLevel, got, tt.want)
		}
	}
}

func TestConsentMinimalBlocksTracesMetricsContext(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	SetConsentLevel(ConsentMinimal)
	for _, sig := range []string{"traces", "metrics", "context"} {
		if ShouldAllow(sig, "") {
			t.Errorf("expected MINIMAL to block %s", sig)
		}
	}
}

func TestLoadConsentFromEnvFull(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	t.Setenv("PROVIDE_CONSENT_LEVEL", "FULL")
	LoadConsentFromEnv()
	if got := GetConsentLevel(); got != ConsentFull {
		t.Errorf("expected ConsentFull, got %v", got)
	}
}

func TestLoadConsentFromEnvFunctional(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	t.Setenv("PROVIDE_CONSENT_LEVEL", "FUNCTIONAL")
	LoadConsentFromEnv()
	if got := GetConsentLevel(); got != ConsentFunctional {
		t.Errorf("expected ConsentFunctional, got %v", got)
	}
}

func TestLoadConsentFromEnvMinimal(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	t.Setenv("PROVIDE_CONSENT_LEVEL", "MINIMAL")
	LoadConsentFromEnv()
	if got := GetConsentLevel(); got != ConsentMinimal {
		t.Errorf("expected ConsentMinimal, got %v", got)
	}
}

func TestLoadConsentFromEnvNone(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	t.Setenv("PROVIDE_CONSENT_LEVEL", "NONE")
	LoadConsentFromEnv()
	if got := GetConsentLevel(); got != ConsentNone {
		t.Errorf("expected ConsentNone, got %v", got)
	}
}

func TestLoadConsentFromEnvInvalidIgnored(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	t.Setenv("PROVIDE_CONSENT_LEVEL", "BOGUS")
	LoadConsentFromEnv()
	// invalid value leaves level unchanged (FULL)
	if got := GetConsentLevel(); got != ConsentFull {
		t.Errorf("expected ConsentFull after bogus value, got %v", got)
	}
}

func TestLoadConsentFromEnvEmpty(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	t.Setenv("PROVIDE_CONSENT_LEVEL", "")
	LoadConsentFromEnv()
	// empty env var leaves level unchanged
	if got := GetConsentLevel(); got != ConsentFull {
		t.Errorf("expected ConsentFull after empty env, got %v", got)
	}
}

func TestConsentFunctionalUnknownSignalAllowed(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	SetConsentLevel(ConsentFunctional)
	if !ShouldAllow("custom_signal", "") {
		t.Error("expected FUNCTIONAL to allow unknown signals")
	}
}

func TestConsentMinimalUnknownSignalBlocked(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	SetConsentLevel(ConsentMinimal)
	if ShouldAllow("custom_signal", "") {
		t.Error("expected MINIMAL to block unknown signals")
	}
}

func TestSetGetConsentLevel(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	SetConsentLevel(ConsentFunctional)
	if got := GetConsentLevel(); got != ConsentFunctional {
		t.Errorf("expected ConsentFunctional, got %v", got)
	}
}

func TestShouldAllowUnknownConsentLevelReturnsFalse(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	SetConsentLevel(ConsentLevel(99))
	if ShouldAllow("logs", "INFO") {
		t.Error("expected unknown ConsentLevel to deny all signals")
	}
}
