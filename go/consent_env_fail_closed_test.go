// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

package telemetry

// PROVIDE_CONSENT_LEVEL fail-closed semantics.
//
// An unset or blank variable is a no-op. A recognised value is applied. A set,
// non-empty, unrecognised value is an opt-out the operator misspelled, so it
// fails closed to NONE and warns once per process, naming the raw value. The
// warning goes to os.Stderr directly, never through the SDK logger: the NONE
// it just applied would drop it.

import (
	"bytes"
	"context"
	"os"
	"strings"
	"testing"
)

const _invalidConsentWarningForNoen = `[provide-telemetry] PROVIDE_CONSENT_LEVEL="  noen " is not one of ` +
	`FULL, FUNCTIONAL, MINIMAL, NONE; consent set to NONE (fail-closed)`

// captureStderr runs fn with os.Stderr swapped for a pipe and returns what fn
// wrote. The consent warning reads os.Stderr at call time for exactly this.
func captureStderr(t *testing.T, fn func()) string {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("pipe: %v", err)
	}
	orig := os.Stderr
	os.Stderr = w
	func() {
		defer func() { os.Stderr = orig }()
		fn()
	}()
	_ = w.Close()
	var buf bytes.Buffer
	_, _ = buf.ReadFrom(r)
	_ = r.Close()
	return buf.String()
}

// stderrLines splits captured output into non-empty lines.
func stderrLines(out string) []string {
	var lines []string
	for _, line := range strings.Split(out, "\n") {
		if line != "" {
			lines = append(lines, line)
		}
	}
	return lines
}

func loadConsentCapturingStderr(t *testing.T) []string {
	t.Helper()
	return stderrLines(captureStderr(t, LoadConsentFromEnv))
}

func TestLoadConsentFromEnvInvalidValueFailsClosedToNone(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	t.Setenv("PROVIDE_CONSENT_LEVEL", "NOEN")
	_ = loadConsentCapturingStderr(t)
	if got := GetConsentLevel(); got != ConsentNone {
		t.Fatalf("expected ConsentNone after invalid value, got %v", got)
	}
	if ShouldAllow(signalLogs, "ERROR") {
		t.Fatal("expected fail-closed NONE to block logs")
	}
}

func TestLoadConsentFromEnvInvalidValueOverridesProgrammaticFull(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	t.Setenv("PROVIDE_CONSENT_LEVEL", "NOEN")
	SetConsentLevel(ConsentFull)
	_ = loadConsentCapturingStderr(t)
	if got := GetConsentLevel(); got != ConsentNone {
		t.Fatalf("expected invalid env to override programmatic FULL with NONE, got %v", got)
	}
}

func TestLoadConsentFromEnvInvalidValueWarnsExactlyOnceNamingRawValue(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	t.Setenv("PROVIDE_CONSENT_LEVEL", "  noen ")
	lines := loadConsentCapturingStderr(t)
	if len(lines) != 1 {
		t.Fatalf("expected exactly one stderr line, got %d: %q", len(lines), lines)
	}
	if lines[0] != _invalidConsentWarningForNoen {
		t.Fatalf("warning text mismatch:\n got: %q\nwant: %q", lines[0], _invalidConsentWarningForNoen)
	}
	if got := GetConsentLevel(); got != ConsentNone {
		t.Fatalf("expected ConsentNone, got %v", got)
	}
}

func TestLoadConsentFromEnvSecondInvalidLoadIsSilentButStillFailsClosed(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	t.Setenv("PROVIDE_CONSENT_LEVEL", "BOGUS")
	first := loadConsentCapturingStderr(t)
	if len(first) != 1 {
		t.Fatalf("expected one warning on the first invalid load, got %d: %q", len(first), first)
	}
	// Code choosing FULL between the two loads must not survive the second.
	SetConsentLevel(ConsentFull)
	second := loadConsentCapturingStderr(t)
	if len(second) != 0 {
		t.Fatalf("expected no warning on the second invalid load, got %d: %q", len(second), second)
	}
	if got := GetConsentLevel(); got != ConsentNone {
		t.Fatalf("expected second invalid load to set ConsentNone, got %v", got)
	}
}

func TestResetConsentForTestsRearmsInvalidEnvWarning(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	t.Setenv("PROVIDE_CONSENT_LEVEL", "BOGUS")
	if n := len(loadConsentCapturingStderr(t)); n != 1 {
		t.Fatalf("expected one warning before reset, got %d", n)
	}
	ResetConsentForTests()
	if got := GetConsentLevel(); got != ConsentFull {
		t.Fatalf("expected reset to restore ConsentFull, got %v", got)
	}
	lines := loadConsentCapturingStderr(t)
	if len(lines) != 1 {
		t.Fatalf("expected reset to re-arm the warning, got %d lines: %q", len(lines), lines)
	}
	if !strings.Contains(lines[0], `PROVIDE_CONSENT_LEVEL="BOGUS"`) {
		t.Fatalf("re-armed warning does not name the raw value: %q", lines[0])
	}
}

func TestLoadConsentFromEnvBlankValueIsNoOp(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	t.Setenv("PROVIDE_CONSENT_LEVEL", "")
	SetConsentLevel(ConsentMinimal)
	lines := loadConsentCapturingStderr(t)
	if len(lines) != 0 {
		t.Fatalf("expected no warning for blank value, got %q", lines)
	}
	if got := GetConsentLevel(); got != ConsentMinimal {
		t.Fatalf("expected blank value to leave ConsentMinimal, got %v", got)
	}
}

func TestLoadConsentFromEnvWhitespaceOnlyValueIsNoOp(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	t.Setenv("PROVIDE_CONSENT_LEVEL", "  \t ")
	SetConsentLevel(ConsentMinimal)
	lines := loadConsentCapturingStderr(t)
	if len(lines) != 0 {
		t.Fatalf("expected no warning for whitespace-only value, got %q", lines)
	}
	if got := GetConsentLevel(); got != ConsentMinimal {
		t.Fatalf("expected whitespace-only value to leave ConsentMinimal, got %v", got)
	}
}

func TestLoadConsentFromEnvUnsetIsNoOp(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	t.Setenv("PROVIDE_CONSENT_LEVEL", "")
	_ = os.Unsetenv("PROVIDE_CONSENT_LEVEL")
	SetConsentLevel(ConsentMinimal)
	lines := loadConsentCapturingStderr(t)
	if len(lines) != 0 {
		t.Fatalf("expected no warning when unset, got %q", lines)
	}
	if got := GetConsentLevel(); got != ConsentMinimal {
		t.Fatalf("expected unset variable to leave ConsentMinimal, got %v", got)
	}
}

func TestLoadConsentFromEnvRecognisedValueIsTrimmedAndAppliedWithoutWarning(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)
	t.Setenv("PROVIDE_CONSENT_LEVEL", " functional ")
	lines := loadConsentCapturingStderr(t)
	if len(lines) != 0 {
		t.Fatalf("expected no warning for a recognised value, got %q", lines)
	}
	if got := GetConsentLevel(); got != ConsentFunctional {
		t.Fatalf("expected ConsentFunctional, got %v", got)
	}
}

func TestSetupTelemetryFailsClosedOnInvalidConsentEnv(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)

	t.Setenv("PROVIDE_CONSENT_LEVEL", "NOEN")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if got := GetConsentLevel(); got != ConsentNone {
		t.Fatalf("expected setup with invalid env to fail closed to ConsentNone, got %v", got)
	}
	if ShouldAllow(signalLogs, "ERROR") {
		t.Fatal("expected fail-closed NONE at setup to block logs")
	}
}

func TestGetLoggerBeforeSetupFailsClosedOnInvalidConsentEnv(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)

	t.Setenv("PROVIDE_CONSENT_LEVEL", "NOEN")
	before := GetHealthSnapshot()
	GetLogger(context.Background(), "x").Info("lazy.logger.consent.invalid")
	if got := GetConsentLevel(); got != ConsentNone {
		t.Fatalf("expected lazy GetLogger with invalid env to fail closed to ConsentNone, got %v", got)
	}
	if after := GetHealthSnapshot(); after.LogsEmitted != before.LogsEmitted {
		t.Fatalf("expected fail-closed NONE to suppress the lazy record: before=%d after=%d", before.LogsEmitted, after.LogsEmitted)
	}
}
