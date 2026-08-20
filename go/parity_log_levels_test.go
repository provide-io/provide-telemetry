// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// parity_log_levels_test.go validates Go behavioral parity for the log_levels
// section of spec/behavioral_fixtures.yaml: the canonical ladder, the alias
// table, the unrecognised-token fallback, and the slog bridge.
//
// Go's drift was that _parseLevel folded CRITICAL onto slog.LevelError while
// consent's own table ranked CRITICAL above ERROR -- a record could be ranked
// one way for filtering and another for consent inside a single call. The
// logger package carried a third copy of the fold.

package telemetry

import (
	"log/slog"
	"testing"

	"github.com/provide-io/provide-telemetry/go/internal/levelcore"
)

func TestParity_LogLevels_CanonicalLadder(t *testing.T) {
	cases := []struct {
		severity levelcore.Severity
		order    uint8
		name     string
	}{
		{levelcore.Trace, 0, "TRACE"},
		{levelcore.Debug, 1, "DEBUG"},
		{levelcore.Info, 2, "INFO"},
		{levelcore.Warn, 3, "WARN"},
		{levelcore.Error, 4, "ERROR"},
		{levelcore.Critical, 5, "CRITICAL"},
	}
	for _, tc := range cases {
		if got := tc.severity.Order(); got != tc.order {
			t.Errorf("%s order: want %d, got %d", tc.name, tc.order, got)
		}
		if got := tc.severity.Name(); got != tc.name {
			t.Errorf("order %d name: want %q, got %q", tc.order, tc.name, got)
		}
	}
}

func TestParity_LogLevels_NameGuardsAnOutOfRangeSeverity(t *testing.T) {
	// Severity is only minted by this package, so this is unreachable in
	// practice; it exists so a bad value degrades to INFO instead of panicking.
	if got := levelcore.Severity(99).Name(); got != "INFO" {
		t.Errorf("out-of-range severity: want INFO, got %q", got)
	}
}

func TestParity_LogLevels_ParseVectors(t *testing.T) {
	recognised := []struct {
		input    string
		expected levelcore.Severity
	}{
		{"ERROR", levelcore.Error},
		{"error", levelcore.Error},
		{"CrItIcAl", levelcore.Critical},
		{"  warn  ", levelcore.Warn},
		{"warning", levelcore.Warn},
		{"WARNING", levelcore.Warn},
		{"FATAL", levelcore.Critical},
		{"CRITICAL", levelcore.Critical},
		{"TRACE", levelcore.Trace},
		{"DEBUG", levelcore.Debug},
		{"INFO", levelcore.Info},
	}
	for _, tc := range recognised {
		got, ok := levelcore.TryParse(tc.input)
		if !ok || got != tc.expected {
			t.Errorf("TryParse(%q) = %v, %v; want %v, true", tc.input, got, ok, tc.expected)
		}
		if got := levelcore.Parse(tc.input, levelcore.Info); got != tc.expected {
			t.Errorf("Parse(%q) = %v, want %v", tc.input, got, tc.expected)
		}
		if got := levelcore.Order(tc.input); got != tc.expected.Order() {
			t.Errorf("Order(%q) = %d, want %d", tc.input, got, tc.expected.Order())
		}
	}

	for _, input := range []string{"warnn", "warns", "", "   "} {
		got, ok := levelcore.TryParse(input)
		if ok {
			t.Errorf("TryParse(%q) reported recognised", input)
		}
		if got != levelcore.Info {
			t.Errorf("TryParse(%q) = %v, want Info on failure", input, got)
		}
		if got := levelcore.Parse(input, levelcore.Info); got != levelcore.Info {
			t.Errorf("Parse(%q) = %v, want Info", input, got)
		}
		if got := levelcore.Order(input); got != levelcore.Info.Order() {
			t.Errorf("Order(%q) = %d, want %d", input, got, levelcore.Info.Order())
		}
	}
}

func TestParity_LogLevels_FallbackAppliesOnlyToUnrecognisedInput(t *testing.T) {
	if got := levelcore.Parse("warnn", levelcore.Error); got != levelcore.Error {
		t.Errorf("unrecognised input ignored the fallback: got %v", got)
	}
	if got := levelcore.Parse("debug", levelcore.Error); got != levelcore.Debug {
		t.Errorf("recognised input used the fallback: got %v", got)
	}
}

func TestParity_LogLevels_Ordering(t *testing.T) {
	if levelcore.Order("CRITICAL") <= levelcore.Order("ERROR") {
		t.Error("CRITICAL must outrank ERROR")
	}
	if levelcore.Order("WARNING") != levelcore.Order("WARN") {
		t.Error("WARNING and WARN must be the same severity")
	}
	if levelcore.Order("FATAL") != levelcore.Order("CRITICAL") {
		t.Error("FATAL and CRITICAL must be the same severity")
	}
	if levelcore.Order("TRACE") >= levelcore.Order("DEBUG") {
		t.Error("TRACE must be the floor")
	}
}

func TestParity_LogLevels_SlogBridge(t *testing.T) {
	cases := []struct {
		severity levelcore.Severity
		level    slog.Level
		name     string
	}{
		{levelcore.Trace, LevelTrace, "TRACE"},
		{levelcore.Debug, slog.LevelDebug, "DEBUG"},
		{levelcore.Info, slog.LevelInfo, "INFO"},
		{levelcore.Warn, slog.LevelWarn, "WARN"},
		{levelcore.Error, slog.LevelError, "ERROR"},
		{levelcore.Critical, LevelCritical, "CRITICAL"},
	}
	for _, tc := range cases {
		if got := levelcore.ToSlog(tc.severity); got != tc.level {
			t.Errorf("ToSlog(%s) = %v, want %v", tc.name, got, tc.level)
		}
		if got := levelcore.FromSlog(tc.level); got != tc.severity {
			t.Errorf("FromSlog(%v) = %v, want %s", tc.level, got, tc.name)
		}
		if got := LevelName(tc.level); got != tc.name {
			t.Errorf("LevelName(%v) = %q, want %q", tc.level, got, tc.name)
		}
		if got := ParseLevel(tc.name); got != tc.level {
			t.Errorf("ParseLevel(%q) = %v, want %v", tc.name, got, tc.level)
		}
	}
}

func TestParity_LogLevels_SlogNameNeverRendersArithmetic(t *testing.T) {
	// slog.Level.String() renders the two custom rungs as "DEBUG-4" and
	// "ERROR+4". Neither is in any level table, so a record routed through
	// String() was ranked as an unrecognised level by the consent gate.
	if LevelTrace.String() == "TRACE" || LevelCritical.String() == "CRITICAL" {
		t.Skip("slog gained custom level names; this guard is no longer needed")
	}
	if got := LevelName(LevelTrace); got != "TRACE" {
		t.Errorf("LevelName(LevelTrace) = %q, want TRACE", got)
	}
	if got := LevelName(LevelCritical); got != "CRITICAL" {
		t.Errorf("LevelName(LevelCritical) = %q, want CRITICAL", got)
	}
}

func TestParity_LogLevels_ParseSlogResolvesStringsStraightToSlog(t *testing.T) {
	if got := levelcore.ParseSlog("fatal", levelcore.Info); got != LevelCritical {
		t.Errorf("ParseSlog(fatal) = %v, want %v", got, LevelCritical)
	}
	if got := levelcore.ParseSlog("nonsense", levelcore.Info); got != slog.LevelInfo {
		t.Errorf("ParseSlog(nonsense) = %v, want %v", got, slog.LevelInfo)
	}
}

func TestParity_LogLevels_AdapterDispatchChainCollapses(t *testing.T) {
	// The motivating case: a component reports (level, message) so it need not
	// depend on a logger. slog already takes a typed level, so the whole chain
	// is Log(ctx, ParseLevel(level), message).
	ctx := t.Context()
	logger := GetLogger(ctx, "adapter")
	for _, tc := range []struct {
		level string
		want  slog.Level
	}{
		{"debug", slog.LevelDebug},
		{"warn", slog.LevelWarn},
		{"warning", slog.LevelWarn},
		{"error", slog.LevelError},
		{"fatal", LevelCritical},
		{"nonsense", slog.LevelInfo},
	} {
		if got := ParseLevel(tc.level); got != tc.want {
			t.Errorf("ParseLevel(%q) = %v, want %v", tc.level, got, tc.want)
		}
		logger.Log(ctx, ParseLevel(tc.level), "adapter.probe")
	}
}
