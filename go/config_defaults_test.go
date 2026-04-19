// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"testing"
)

// ---- DefaultTelemetryConfig ----

func TestDefaultTelemetryConfig_TopLevel(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	if cfg.ServiceName != "provide-service" {
		t.Errorf("ServiceName: got %q, want %q", cfg.ServiceName, "provide-service")
	}
	if cfg.Environment != "dev" {
		t.Errorf("Environment: got %q, want %q", cfg.Environment, "dev")
	}
	if cfg.Version != "0.0.0" {
		t.Errorf("Version: got %q, want %q", cfg.Version, "0.0.0")
	}
	if cfg.StrictSchema {
		t.Error("StrictSchema should default to false")
	}
}

func TestDefaultTelemetryConfig_Logging(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	l := cfg.Logging
	if l.Level != testLogLevel {
		t.Errorf("Level: got %q, want %q", l.Level, testLogLevel)
	}
	if l.Format != "console" {
		t.Errorf("Format: got %q, want %q", l.Format, "console")
	}
	if !l.IncludeTimestamp {
		t.Error("IncludeTimestamp should default to true")
	}
	if !l.IncludeCaller {
		t.Error("IncludeCaller should default to true")
	}
	if !l.Sanitize {
		t.Error("Sanitize should default to true")
	}
	if l.LogCodeAttributes {
		t.Error("LogCodeAttributes should default to false")
	}
	if l.PrettyKeyColor != "dim" {
		t.Errorf("PrettyKeyColor: got %q, want %q", l.PrettyKeyColor, "dim")
	}
	if l.PrettyValueColor != "" {
		t.Errorf("PrettyValueColor: got %q, want %q", l.PrettyValueColor, "")
	}
	if len(l.PrettyFields) != 0 {
		t.Errorf("PrettyFields: got %v, want []", l.PrettyFields)
	}
	if len(l.ModuleLevels) != 0 {
		t.Errorf("ModuleLevels: got %v, want {}", l.ModuleLevels)
	}
	if l.OTLPHeaders == nil {
		t.Error("OTLPHeaders should be initialized (not nil)")
	}
}

func TestDefaultTelemetryConfig_Tracing(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	tr := cfg.Tracing
	if !tr.Enabled {
		t.Error("Tracing.Enabled should default to true")
	}
	if tr.SampleRate != 1.0 {
		t.Errorf("Tracing.SampleRate: got %f, want 1.0", tr.SampleRate)
	}
	if tr.OTLPHeaders == nil {
		t.Error("Tracing.OTLPHeaders should be initialized")
	}
}

func TestDefaultTelemetryConfig_Metrics(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	m := cfg.Metrics
	if !m.Enabled {
		t.Error("Metrics.Enabled should default to true")
	}
	if m.OTLPHeaders == nil {
		t.Error("Metrics.OTLPHeaders should be initialized")
	}
}

func TestDefaultTelemetryConfig_Sampling(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	s := cfg.Sampling
	if s.LogsRate != 1.0 {
		t.Errorf("Sampling.LogsRate: got %f, want 1.0", s.LogsRate)
	}
	if s.TracesRate != 1.0 {
		t.Errorf("Sampling.TracesRate: got %f, want 1.0", s.TracesRate)
	}
	if s.MetricsRate != 1.0 {
		t.Errorf("Sampling.MetricsRate: got %f, want 1.0", s.MetricsRate)
	}
}

func TestDefaultTelemetryConfig_Exporter(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	e := cfg.Exporter
	if e.LogsTimeoutSeconds != 10.0 {
		t.Errorf("LogsTimeoutSeconds: got %f, want 10.0", e.LogsTimeoutSeconds)
	}
	if e.TracesTimeoutSeconds != 10.0 {
		t.Errorf("TracesTimeoutSeconds: got %f, want 10.0", e.TracesTimeoutSeconds)
	}
	if e.MetricsTimeoutSeconds != 10.0 {
		t.Errorf("MetricsTimeoutSeconds: got %f, want 10.0", e.MetricsTimeoutSeconds)
	}
	if !e.LogsFailOpen {
		t.Error("LogsFailOpen should default to true")
	}
	if !e.TracesFailOpen {
		t.Error("TracesFailOpen should default to true")
	}
	if !e.MetricsFailOpen {
		t.Error("MetricsFailOpen should default to true")
	}
	if e.LogsAllowBlockingInEventLoop {
		t.Error("LogsAllowBlockingInEventLoop should default to false")
	}
}

func TestDefaultTelemetryConfig_SLO(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	if !cfg.SLO.IncludeErrorTaxonomy {
		t.Error("SLO.IncludeErrorTaxonomy should default to true")
	}
	if cfg.SLO.EnableREDMetrics {
		t.Error("SLO.EnableREDMetrics should default to false")
	}
	if cfg.SLO.EnableUSEMetrics {
		t.Error("SLO.EnableUSEMetrics should default to false")
	}
}

func TestDefaultTelemetryConfig_Security(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	s := cfg.Security
	if s.MaxAttrValueLength != 1024 {
		t.Errorf("MaxAttrValueLength: got %d, want 1024", s.MaxAttrValueLength)
	}
	if s.MaxAttrCount != 64 {
		t.Errorf("MaxAttrCount: got %d, want 64", s.MaxAttrCount)
	}
	if s.MaxNestingDepth != 8 {
		t.Errorf("MaxNestingDepth: got %d, want 8", s.MaxNestingDepth)
	}
}
