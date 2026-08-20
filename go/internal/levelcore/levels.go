// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Package levelcore holds the canonical severity ladder and the single place a
// level string becomes a level.
//
// It is shared because the module had three private converters that had
// drifted: the root package's _parseLevel folded CRITICAL onto ERROR, the
// logger package had its own copy of the same fold, and consent's
// _logLevelOrder ranked CRITICAL above ERROR — so a record could be ranked one
// way for filtering and another way for consent inside a single call.
//
// See the log_levels section of spec/behavioral_fixtures.yaml for the
// cross-language contract.
package levelcore

import (
	"log/slog"
	"strings"
)

// Severity is the canonical ladder. The value is the rank, so severities
// compare directly with < and >.
//
// WARNING and FATAL are deliberately absent: they are spellings resolved by
// TryParse, not members.
type Severity uint8

// The ladder, in order.
const (
	Trace Severity = iota
	Debug
	Info
	Warn
	Error
	Critical
)

// canonicalNames is indexed by rank.
var canonicalNames = [...]string{"TRACE", "DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"}

// table maps every accepted spelling, canonical and alias alike, to its rank.
var table = map[string]Severity{
	"TRACE":    Trace,
	"DEBUG":    Debug,
	"INFO":     Info,
	"WARN":     Warn,
	"ERROR":    Error,
	"CRITICAL": Critical,
	"WARNING":  Warn,
	"FATAL":    Critical,
}

// Name returns the canonical uppercase spelling, as it appears on the record.
func (s Severity) Name() string {
	if int(s) >= len(canonicalNames) {
		return canonicalNames[Info]
	}
	return canonicalNames[s]
}

// Order returns the numeric rank, for threshold comparisons.
func (s Severity) Order() uint8 { return uint8(s) }

// TryParse resolves a level string, reporting whether it was recognised.
// Surrounding whitespace is trimmed and comparison is case-insensitive.
func TryParse(text string) (Severity, bool) {
	s, ok := table[strings.ToUpper(strings.TrimSpace(text))]
	if !ok {
		return Info, false
	}
	return s, true
}

// Parse resolves a level string, substituting fallback when it is not
// recognised. The fallback is a parameter rather than a hidden constant so the
// substitution is visible at the call site.
func Parse(text string, fallback Severity) Severity {
	if s, ok := TryParse(text); ok {
		return s
	}
	return fallback
}

// Order returns the rank of a level string, with unrecognised values ranking
// INFO.
func Order(text string) uint8 { return Parse(text, Info).Order() }

// ToSlog converts a severity to the slog level that carries it.
func ToSlog(s Severity) slog.Level {
	// An if-chain rather than a switch: gremlins mutates a switch's case
	// expressions in a way that reports fully covered code as uncovered and
	// fails --threshold-mcover=100. See go/slo.go for the detail.
	if s <= Trace {
		return SlogTrace
	}
	if s <= Debug {
		return slog.LevelDebug
	}
	if s <= Info {
		return slog.LevelInfo
	}
	if s <= Warn {
		return slog.LevelWarn
	}
	if s <= Error {
		return slog.LevelError
	}
	return SlogCritical
}

// FromSlog converts an slog level to the nearest severity at or below it.
func FromSlog(l slog.Level) Severity {
	if l <= SlogTrace {
		return Trace
	}
	if l <= slog.LevelDebug {
		return Debug
	}
	if l <= slog.LevelInfo {
		return Info
	}
	if l <= slog.LevelWarn {
		return Warn
	}
	if l <= slog.LevelError {
		return Error
	}
	return Critical
}

// SlogName is the canonical spelling of an slog level.
//
// slog.Level.String() renders the two custom rungs as "DEBUG-4" and "ERROR+4",
// which no level table recognises. Anything that hands a level to consent, to
// a threshold check, or onto a record must come through here instead.
func SlogName(l slog.Level) string { return FromSlog(l).Name() }

// ParseSlog resolves a level string straight to an slog level.
func ParseSlog(text string, fallback Severity) slog.Level {
	return ToSlog(Parse(text, fallback))
}
