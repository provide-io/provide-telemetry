// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// config_exporter_warnings_test.go covers the warn-and-ignore handling of
// OTEL_METRICS_EXPORTER and PROVIDE_TELEMETRY_STRICT_CONFIG beyond the shared
// fixture cases: the exact strict-mode error, and what setup does with the
// warnings (spec prometheus_metrics.metrics_exporter_warnings).

package telemetry

import (
	"bytes"
	"encoding/json"
	"errors"
	"slices"
	"strings"
	"testing"
)

const (
	_warnUnknownStatsd = "OTEL_METRICS_EXPORTER: unknown exporter statsd, ignored"
	_warnConsole       = "OTEL_METRICS_EXPORTER: console is not supported by provide-telemetry, ignored"
	_warnNoneCombined  = "OTEL_METRICS_EXPORTER: none cannot be combined with other exporters, ignored"
	_warnFallback      = "OTEL_METRICS_EXPORTER: no supported exporter left, using otlp"
)

func TestParseMetricsExporters_Table(t *testing.T) {
	cases := []struct {
		raw       string
		exporters []string
		warnings  []string
	}{
		{"", []string{"otlp"}, nil},
		{" , ", []string{"otlp"}, nil},
		{"none", []string{}, nil},
		{"prometheus,otlp", []string{"prometheus", "otlp"}, nil},
		{"statsd", []string{"otlp"}, []string{_warnUnknownStatsd, _warnFallback}},
		{"logging,console,logging", []string{"otlp"}, []string{
			"OTEL_METRICS_EXPORTER: logging is not supported by provide-telemetry, ignored", _warnConsole, _warnFallback,
		}},
		{"none,otlp", []string{"otlp"}, []string{_warnNoneCombined}},
		{"none,console", []string{"otlp"}, []string{_warnConsole, _warnNoneCombined, _warnFallback}},
	}
	for _, c := range cases {
		exporters, warnings := parseMetricsExporters(c.raw)
		if !slices.Equal(exporters, c.exporters) || exporters == nil {
			t.Errorf("%q: exporters = %#v, want %v", c.raw, exporters, c.exporters)
		}
		if !slices.Equal(warnings, c.warnings) || (c.warnings == nil) != (warnings == nil) {
			t.Errorf("%q: warnings = %#v, want %#v", c.raw, warnings, c.warnings)
		}
	}
}

func TestStrictConfig_DefaultsOffAndIsRead(t *testing.T) {
	cfg, err := _promConfig(t, nil)
	if err != nil || cfg.StrictConfig {
		t.Fatalf("default StrictConfig = %v (err %v), want false", cfg, err)
	}
	cfg, err = _promConfig(t, map[string]string{"PROVIDE_TELEMETRY_STRICT_CONFIG": "true"})
	if err != nil || !cfg.StrictConfig {
		t.Fatalf("StrictConfig = %v (err %v), want true", cfg, err)
	}
	_, err = _promConfig(t, map[string]string{"PROVIDE_TELEMETRY_STRICT_CONFIG": "maybe"})
	_wantConfigError(t, "strict-bool", err)
	if !strings.Contains(err.Error(), "PROVIDE_TELEMETRY_STRICT_CONFIG") {
		t.Fatalf("error %q does not name the variable", err)
	}
}

func TestStrictConfig_ErrorNamesEveryWarning(t *testing.T) {
	_, err := _promConfig(t, map[string]string{
		"OTEL_METRICS_EXPORTER":           "none,console",
		"PROVIDE_TELEMETRY_STRICT_CONFIG": "1",
	})
	var cfgErr *ConfigurationError
	if !errors.As(err, &cfgErr) {
		t.Fatalf("want *ConfigurationError, got %v", err)
	}
	want := "PROVIDE_TELEMETRY_STRICT_CONFIG: " + _warnConsole + "; " + _warnNoneCombined + "; " + _warnFallback
	if cfgErr.Error() != want {
		t.Fatalf("message = %q, want %q", cfgErr.Error(), want)
	}
}

func TestStrictConfig_SetupFails(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	t.Setenv("OTEL_METRICS_EXPORTER", "otlp,statsd")
	t.Setenv("PROVIDE_TELEMETRY_STRICT_CONFIG", "true")
	if _, err := SetupTelemetry(); err == nil {
		t.Fatal("strict config must fail setup on an ignored exporter")
	}
}

func _ignoredReasons(t *testing.T, out []byte) []string {
	t.Helper()
	reasons := []string{}
	for _, line := range bytes.Split(bytes.TrimSpace(out), []byte("\n")) {
		var rec map[string]any
		if json.Unmarshal(line, &rec) != nil || rec["message"] != "config.metrics_exporter.value_ignored" {
			continue
		}
		if rec["level"] != "WARN" {
			t.Errorf("level = %v, want WARN", rec["level"])
		}
		reason, _ := rec["reason"].(string)
		reasons = append(reasons, reason)
	}
	return reasons
}

func TestSetup_IgnoredExporterWarnsOnceAndRecordsSetupError(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	t.Setenv("PROVIDE_LOG_FORMAT", LogFormatJSON)
	t.Setenv("OTEL_METRICS_EXPORTER", "console")

	var buf bytes.Buffer
	cfg, err := SetupTelemetry(WithLogOutput(&buf))
	if err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if !slices.Equal(cfg.Metrics.Exporters, []string{"otlp"}) {
		t.Fatalf("exporters = %v, want [otlp]", cfg.Metrics.Exporters)
	}
	if got := _ignoredReasons(t, buf.Bytes()); !slices.Equal(got, []string{_warnConsole, _warnFallback}) {
		t.Fatalf("logged reasons = %q (output %q)", got, buf.String())
	}
	if got := GetHealthSnapshot().SetupError; got != _warnConsole+"; "+_warnFallback {
		t.Fatalf("SetupError = %q", got)
	}
	// A repeated setup is a no-op: nothing is logged twice.
	if _, err := SetupTelemetry(); err != nil {
		t.Fatal(err)
	}
	if got := _ignoredReasons(t, buf.Bytes()); len(got) != 2 {
		t.Fatalf("logged %d times, want 2", len(got))
	}
}

func TestSetup_CleanExporterClearsAStaleSetupError(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	t.Setenv("PROVIDE_LOG_FORMAT", LogFormatJSON)
	t.Setenv("OTEL_METRICS_EXPORTER", "prometheus")
	_setSetupError("stale")

	var buf bytes.Buffer
	if _, err := SetupTelemetry(WithLogOutput(&buf)); err != nil {
		t.Fatal(err)
	}
	if got := GetHealthSnapshot().SetupError; got != "" {
		t.Fatalf("SetupError = %q, want empty", got)
	}
	if got := _ignoredReasons(t, buf.Bytes()); len(got) != 0 {
		t.Fatalf("logged %q, want nothing", got)
	}
}

func TestLogIgnoredConfig_NoLoggerIsSafe(t *testing.T) {
	prev := Logger()
	t.Cleanup(func() { SetLogger(prev) })
	SetLogger(nil)
	cfg := DefaultTelemetryConfig()
	cfg.Metrics.ExporterWarnings = []string{_warnConsole}
	_logIgnoredConfig(cfg)
}
