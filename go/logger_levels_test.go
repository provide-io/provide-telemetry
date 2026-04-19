// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"log/slog"
	"strings"
	"testing"
	"time"
)

// ── _effectiveLevel tests ─────────────────────────────────────────────────────

func TestEffectiveLevel_PrefixMatch(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Level = "INFO"
	cfg.Logging.ModuleLevels = map[string]string{
		"provide":           "WARN",
		"provide.telemetry": "DEBUG",
	}

	level := _effectiveLevel("provide.telemetry.auth", cfg)
	if level != slog.LevelDebug {
		t.Errorf("expected DEBUG from longest prefix match, got %v", level)
	}
}

func TestEffectiveLevel_NilConfig(t *testing.T) {
	level := _effectiveLevel("anything", nil)
	if level != slog.LevelInfo {
		t.Errorf("expected INFO for nil config, got %v", level)
	}
}

// ── _effectiveLevel: modules differing by 1 char ─────────────────────────────
// logger.go:188 `len(module) >= bestLen+1` BOUNDARY: `> bestLen+1` would skip
// module "ab" (len=2) when bestLen=1 because 2 > 2 is false.
func TestEffectiveLevel_ConsecutiveLengthModules(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Level = "INFO"
	cfg.Logging.ModuleLevels = map[string]string{
		"a":  "WARN",
		"ab": "DEBUG",
	}
	// "ab.c" matches both "a" (prefix) and "ab" (prefix).
	// "ab" is longer → should win with DEBUG.
	level := _effectiveLevel("ab.c", cfg)
	if level != slog.LevelDebug {
		t.Errorf("expected DEBUG from longest prefix 'ab', got %v", level)
	}
}

// ── _effectiveLevel: empty module key ────────────────────────────────────────

func TestEffectiveLevel_EmptyModuleKey_MatchesAll(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Level = "INFO"
	cfg.Logging.ModuleLevels = map[string]string{"": "DEBUG"}

	level := _effectiveLevel("any.module.name", cfg)
	if level != slog.LevelDebug {
		t.Errorf("empty module key should match all names; want DEBUG, got %v", level)
	}
}

// ── _parseLevel tests ─────────────────────────────────────────────────────────

func TestParseLevel_AllVariants(t *testing.T) {
	cases := []struct {
		input    string
		expected slog.Level
	}{
		{"TRACE", LevelTrace},
		{"DEBUG", slog.LevelDebug},
		{"INFO", slog.LevelInfo},
		{"WARN", slog.LevelWarn},
		{"WARNING", slog.LevelWarn},
		{"ERROR", slog.LevelError},
		{"CRITICAL", slog.LevelError},
		{"unknown", slog.LevelInfo},
		{"", slog.LevelInfo},
	}
	for _, tc := range cases {
		got := _parseLevel(tc.input)
		if got != tc.expected {
			t.Errorf("_parseLevel(%q) = %v, want %v", tc.input, got, tc.expected)
		}
	}
}

// ── _isPrefixMatch tests ──────────────────────────────────────────────────────

func TestIsPrefixMatch(t *testing.T) {
	cases := []struct {
		name, module string
		want         bool
	}{
		{"a.b.c", "a.b", true},
		{"a.b", "a.b", true},
		{"anything", "", true},
		{"ab.c", "a", false},
		{"other", "mymodule", false},
	}
	for _, tc := range cases {
		got := _isPrefixMatch(tc.name, tc.module)
		if got != tc.want {
			t.Errorf("_isPrefixMatch(%q, %q) = %v, want %v", tc.name, tc.module, got, tc.want)
		}
	}
}

// ── _attrsToMap / _mapToAttrs round-trip ─────────────────────────────────────

func TestAttrsToMap_AndMapToAttrs(t *testing.T) {
	rec := slog.NewRecord(time.Now(), slog.LevelInfo, "msg", 0)
	rec.AddAttrs(slog.String("foo", "bar"), slog.Int("n", 42))

	m := _attrsToMap(rec)
	if m["foo"] != "bar" {
		t.Errorf("expected foo=bar, got %v", m["foo"])
	}
	if m["n"] != int64(42) {
		t.Errorf("expected n=42, got %v (%T)", m["n"], m["n"])
	}

	attrs := _mapToAttrs(m)
	found := map[string]bool{}
	for _, a := range attrs {
		found[a.Key] = true
	}
	if !found["foo"] || !found["n"] {
		t.Errorf("round-trip lost keys: got %v", found)
	}
}

// ── applyStandardFields partial-set: kills CONDITIONALS_NEGATION mutations ───

func TestHandler_StandardField_OnlyServiceName(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = "only-svc"
	cfg.Environment = ""
	cfg.Version = ""
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("partial std fields")

	out := buf.String()
	if !strings.Contains(out, `"service.name":"only-svc"`) {
		t.Errorf("expected service.name in output, got: %s", out)
	}
	if strings.Contains(out, "service.env") {
		t.Errorf("unexpected service.env when Environment is empty: %s", out)
	}
}

// Mutation col 67: Version != "" — with Version set and others empty,
// mutant returns early. Test verifies service.version IS present.
func TestHandler_StandardField_OnlyVersion(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = ""
	cfg.Environment = ""
	cfg.Version = "1.0.0"
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("version only")

	out := buf.String()
	if !strings.Contains(out, `"service.version":"1.0.0"`) {
		t.Errorf("expected service.version in output, got: %s", out)
	}
}

// Mutation col 46: Environment != "" — with Environment set and others empty,
// mutant returns early. Test verifies service.env IS present.
func TestHandler_StandardField_OnlyEnvironment(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = ""
	cfg.Environment = "staging"
	cfg.Version = ""
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("env only")

	out := buf.String()
	if !strings.Contains(out, `"service.env":"staging"`) {
		t.Errorf("expected service.env in output, got: %s", out)
	}
}
