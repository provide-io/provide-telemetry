// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

package telemetry

import (
	"context"
	"os"
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

// ── Environment wiring ────────────────────────────────────────────────────────
//
// LoadConsentFromEnv existed from the start; nothing called it, so
// PROVIDE_CONSENT_LEVEL=NONE was read by every other SDK and ignored by Go.
// These pin the two entry points that now load it — setup and the lazy
// pre-setup logger — and the two things they must not do: overwrite a level
// when the variable is unset, and overwrite a programmatic level after setup.

func TestSetupTelemetryLoadsConsentFromEnv(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)

	t.Setenv("PROVIDE_CONSENT_LEVEL", "NONE")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if got := GetConsentLevel(); got != ConsentNone {
		t.Fatalf("expected setup to load ConsentNone from env, got %v", got)
	}
	if ShouldAllow(signalLogs, "ERROR") {
		t.Fatal("expected NONE loaded at setup to block logs")
	}
}

func TestSetupTelemetryLeavesConsentWhenEnvUnset(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)

	t.Setenv("PROVIDE_CONSENT_LEVEL", "")
	_ = os.Unsetenv("PROVIDE_CONSENT_LEVEL")
	SetConsentLevel(ConsentMinimal)
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if got := GetConsentLevel(); got != ConsentMinimal {
		t.Fatalf("expected unset env to leave ConsentMinimal in place, got %v", got)
	}
}

func TestGetLoggerBeforeSetupLoadsConsentFromEnv(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)

	t.Setenv("PROVIDE_CONSENT_LEVEL", "NONE")
	before := GetHealthSnapshot()
	GetLogger(context.Background(), "x").Info("lazy.logger.consent.none")
	if got := GetConsentLevel(); got != ConsentNone {
		t.Fatalf("expected lazy GetLogger to load ConsentNone from env, got %v", got)
	}
	if after := GetHealthSnapshot(); after.LogsEmitted != before.LogsEmitted {
		t.Fatalf("expected NONE to suppress the lazy record: before=%d after=%d", before.LogsEmitted, after.LogsEmitted)
	}
}

func TestGetLoggerAfterSetupDoesNotReloadConsentFromEnv(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)

	t.Setenv("PROVIDE_CONSENT_LEVEL", "NONE")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	// A programmatic decision made after setup is the authority; a later
	// GetLogger must not clobber it with the environment again.
	SetConsentLevel(ConsentFull)
	GetLogger(context.Background(), "x").Info("post.setup.consent.full")
	if got := GetConsentLevel(); got != ConsentFull {
		t.Fatalf("expected GetLogger after setup to leave ConsentFull, got %v", got)
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
