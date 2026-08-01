// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package logger

import (
	"log/slog"
	"testing"
)

func TestSlogLevelToStringBoundaries(t *testing.T) {
	if LevelTrace != slog.Level(-8) {
		t.Fatalf("LevelTrace=%d want -8", LevelTrace)
	}
	cases := []struct {
		level slog.Level
		want  string
	}{
		{LevelTrace - 1, LogLevelTrace},
		{LevelTrace, LogLevelTrace},
		{LevelTrace + 1, LogLevelDebug},
		{slog.LevelDebug, LogLevelDebug},
		{slog.LevelDebug + 1, LogLevelInfo},
		{slog.LevelInfo, LogLevelInfo},
		{slog.LevelInfo + 1, LogLevelWarn},
		{slog.LevelWarn, LogLevelWarn},
		{slog.LevelWarn + 1, LogLevelError},
		{slog.LevelError, LogLevelError},
	}
	for _, tc := range cases {
		if got := _slogLevelToString(tc.level); got != tc.want {
			t.Errorf("_slogLevelToString(%d)=%q want %q", tc.level, got, tc.want)
		}
	}
}
