// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Validates the log_levels contract from spec/behavioral_fixtures.yaml for the
// standalone logger package, which carried its own copy of the CRITICAL fold.

package logger_test

import (
	"log/slog"
	"testing"

	"github.com/provide-io/provide-telemetry/go/logger"
)

func TestParseLevelResolvesEverySpellingIncludingAliases(t *testing.T) {
	cases := []struct {
		input string
		want  slog.Level
	}{
		{"TRACE", logger.LevelTrace},
		{"DEBUG", slog.LevelDebug},
		{"INFO", slog.LevelInfo},
		{"WARN", slog.LevelWarn},
		{"WARNING", slog.LevelWarn},
		{"ERROR", slog.LevelError},
		// CRITICAL used to fold onto slog.LevelError here too.
		{"CRITICAL", logger.LevelCritical},
		{"FATAL", logger.LevelCritical},
		{"  critical  ", logger.LevelCritical},
		{"nonsense", slog.LevelInfo},
		{"", slog.LevelInfo},
	}
	for _, tc := range cases {
		if got := logger.ParseLevel(tc.input); got != tc.want {
			t.Errorf("ParseLevel(%q) = %v, want %v", tc.input, got, tc.want)
		}
	}
}

func TestLevelNameRendersCanonicalSpellingsNotSlogArithmetic(t *testing.T) {
	// slog.Level.String() renders the custom rungs as "DEBUG-4" and "ERROR+4",
	// which no level table recognises.
	cases := []struct {
		level slog.Level
		want  string
	}{
		{logger.LevelTrace, "TRACE"},
		{slog.LevelDebug, "DEBUG"},
		{slog.LevelInfo, "INFO"},
		{slog.LevelWarn, "WARN"},
		{slog.LevelError, "ERROR"},
		{logger.LevelCritical, "CRITICAL"},
	}
	for _, tc := range cases {
		if got := logger.LevelName(tc.level); got != tc.want {
			t.Errorf("LevelName(%v) = %q, want %q", tc.level, got, tc.want)
		}
	}
}
