// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Reconfigure must apply the hot logging fields it validates. Before this,
// _applyHotFields copied only PIIMaxDepth and ModuleLevels, so a Reconfigure
// with Logging.Level = DEBUG validated the level, returned success, and left
// emission at INFO — while UpdateConfig on the same runtime applied it.

package telemetry

import (
	"context"
	"log/slog"
	"testing"
)

func TestReconfigure_AppliesHotLoggingFields(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	base := DefaultTelemetryConfig()
	if _, err := SetupTelemetry(WithConfig(base)); err != nil {
		t.Fatalf("setup: %v", err)
	}

	target := cloneTelemetryConfig(base)
	target.Logging.Level = LogLevelDebug
	target.Logging.Format = LogFormatJSON
	target.Logging.IncludeTimestamp = !base.Logging.IncludeTimestamp
	target.Logging.IncludeCaller = !base.Logging.IncludeCaller
	target.Logging.Sanitize = !base.Logging.Sanitize
	target.Logging.LogCodeAttributes = !base.Logging.LogCodeAttributes
	target.Logging.PrettyKeyColor = "cyan"
	target.Logging.PrettyValueColor = "magenta"
	target.Logging.PrettyFields = []string{"event"}
	target.Logging.ModuleLevels = map[string]string{"chatty": LogLevelDebug}
	target.Logging.PIIMaxDepth = 3

	rt := NewTelemetryRuntime(context.Background())
	got, err := rt.Reconfigure(context.Background(), target)
	if err != nil {
		t.Fatalf("reconfigure: %v", err)
	}

	assertLogging := func(name string, cfg *TelemetryConfig) {
		t.Helper()
		l := cfg.Logging
		if l.Level != LogLevelDebug || l.Format != LogFormatJSON {
			t.Fatalf("%s: level/format not applied: %q/%q", name, l.Level, l.Format)
		}
		if l.IncludeTimestamp != target.Logging.IncludeTimestamp ||
			l.IncludeCaller != target.Logging.IncludeCaller ||
			l.Sanitize != target.Logging.Sanitize ||
			l.LogCodeAttributes != target.Logging.LogCodeAttributes {
			t.Fatalf("%s: boolean logging fields not applied: %+v", name, l)
		}
		if l.PrettyKeyColor != "cyan" || l.PrettyValueColor != "magenta" {
			t.Fatalf("%s: pretty colors not applied: %q/%q", name, l.PrettyKeyColor, l.PrettyValueColor)
		}
		if len(l.PrettyFields) != 1 || l.PrettyFields[0] != "event" {
			t.Fatalf("%s: pretty fields not applied: %v", name, l.PrettyFields)
		}
		if l.ModuleLevels["chatty"] != LogLevelDebug {
			t.Fatalf("%s: module levels not applied: %v", name, l.ModuleLevels)
		}
		if l.PIIMaxDepth != 3 {
			t.Fatalf("%s: PIIMaxDepth not applied: %d", name, l.PIIMaxDepth)
		}
	}
	assertLogging("returned config", got)
	assertLogging("live config", GetRuntimeConfig())

	// The point of the fix: emission honors the new level, not just the report.
	l := GetLogger(context.Background(), "app")
	if !l.Enabled(context.Background(), slog.LevelDebug) {
		t.Fatal("DEBUG must be enabled after Reconfigure to DEBUG level")
	}

	// Cloned, not aliased: the caller mutating its own config must not reach
	// the live runtime (see applyRuntimeOverrides for why this is fatal).
	target.Logging.ModuleLevels["chatty"] = LogLevelError
	target.Logging.PrettyFields[0] = "mutated"
	live := GetRuntimeConfig()
	if live.Logging.ModuleLevels["chatty"] != LogLevelDebug || live.Logging.PrettyFields[0] != "event" {
		t.Fatal("Reconfigure aliased the caller's logging maps/slices into the live config")
	}
}

func TestReconfigure_PreservesProviderBakedLoggingFields(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	base := DefaultTelemetryConfig()
	base.Logging.OTLPEndpoint = "http://live:4318"
	base.Logging.OTLPHeaders = map[string]string{"a": "1"}
	if _, err := SetupTelemetry(WithConfig(base)); err != nil {
		t.Fatalf("setup: %v", err)
	}

	target := cloneTelemetryConfig(base)
	target.Logging.OTLPEndpoint = "http://elsewhere:4318"
	target.Logging.OTLPEnabled = !base.Logging.OTLPEnabled
	target.Logging.OTLPHeaders = map[string]string{"b": "2"}
	target.Logging.Level = LogLevelDebug

	// No live provider, so the target passes the immutability gate — but
	// Reconfigure only ever applies hot fields, and these are not hot.
	got, err := ReconfigureTelemetry(context.Background(), WithConfig(target))
	if err != nil {
		t.Fatalf("reconfigure: %v", err)
	}
	if got.Logging.OTLPEndpoint != "http://live:4318" {
		t.Fatalf("OTLP endpoint must keep its live value, got %q", got.Logging.OTLPEndpoint)
	}
	if got.Logging.OTLPEnabled != base.Logging.OTLPEnabled {
		t.Fatal("OTLP enable flag must keep its live value")
	}
	if got.Logging.OTLPHeaders["a"] != "1" || len(got.Logging.OTLPHeaders) != 1 {
		t.Fatalf("OTLP headers must keep their live value, got %v", got.Logging.OTLPHeaders)
	}
	if got.Logging.Level != LogLevelDebug {
		t.Fatal("hot level must still apply alongside the preserved baked fields")
	}
}
