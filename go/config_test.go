// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"errors"
	"testing"
)

const (
	testDefaultEndpoint = "http://generic:4317"
	testLogLevel        = "INFO"
	testDebugLevel      = "DEBUG"
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

// ---- ConfigFromEnv: happy paths ----

func TestConfigFromEnv_TopLevel(t *testing.T) {
	t.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "my-service")
	t.Setenv("PROVIDE_TELEMETRY_ENV", "production")
	t.Setenv("PROVIDE_TELEMETRY_VERSION", "1.2.3")
	t.Setenv("PROVIDE_TELEMETRY_STRICT_SCHEMA", "true")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.ServiceName != "my-service" {
		t.Errorf("ServiceName: got %q", cfg.ServiceName)
	}
	if cfg.Environment != "production" {
		t.Errorf("Environment: got %q", cfg.Environment)
	}
	if cfg.Version != "1.2.3" {
		t.Errorf("Version: got %q", cfg.Version)
	}
	if !cfg.StrictSchema {
		t.Error("StrictSchema should be true")
	}
}

func TestConfigFromEnv_EventSchema(t *testing.T) {
	t.Setenv("PROVIDE_TELEMETRY_STRICT_EVENT_NAME", "1")
	t.Setenv("PROVIDE_TELEMETRY_REQUIRED_KEYS", "event_name, user_id, timestamp")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !cfg.EventSchema.StrictEventName {
		t.Error("EventSchema.StrictEventName should be true")
	}
	want := []string{"event_name", "user_id", "timestamp"}
	if len(cfg.EventSchema.RequiredKeys) != len(want) {
		t.Fatalf("RequiredKeys length: got %d, want %d", len(cfg.EventSchema.RequiredKeys), len(want))
	}
	for i, k := range want {
		if cfg.EventSchema.RequiredKeys[i] != k {
			t.Errorf("RequiredKeys[%d]: got %q, want %q", i, cfg.EventSchema.RequiredKeys[i], k)
		}
	}
}

func TestConfigFromEnv_LoggingGroup(t *testing.T) {
	t.Setenv("PROVIDE_LOG_LEVEL", "debug")
	t.Setenv("PROVIDE_LOG_FORMAT", "json")
	t.Setenv("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false")
	t.Setenv("PROVIDE_LOG_INCLUDE_CALLER", "false")
	t.Setenv("PROVIDE_LOG_SANITIZE", "false")
	t.Setenv("PROVIDE_LOG_CODE_ATTRIBUTES", "true")
	t.Setenv("PROVIDE_LOG_PRETTY_KEY_COLOR", "bold")
	t.Setenv("PROVIDE_LOG_PRETTY_VALUE_COLOR", "red")
	t.Setenv("PROVIDE_LOG_PRETTY_FIELDS", "field1, field2")
	t.Setenv("PROVIDE_LOG_MODULE_LEVELS", "myapp=DEBUG,asyncio=WARNING")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	l := cfg.Logging
	if l.Level != testDebugLevel {
		t.Errorf("Level: got %q, want %q", l.Level, testDebugLevel)
	}
	if l.Format != "json" {
		t.Errorf("Format: got %q, want json", l.Format)
	}
	if l.IncludeTimestamp {
		t.Error("IncludeTimestamp should be false")
	}
	if l.IncludeCaller {
		t.Error("IncludeCaller should be false")
	}
	if l.Sanitize {
		t.Error("Sanitize should be false")
	}
	if !l.LogCodeAttributes {
		t.Error("LogCodeAttributes should be true")
	}
	if l.PrettyKeyColor != "bold" {
		t.Errorf("PrettyKeyColor: got %q", l.PrettyKeyColor)
	}
	if l.PrettyValueColor != "red" {
		t.Errorf("PrettyValueColor: got %q", l.PrettyValueColor)
	}
	if len(l.PrettyFields) != 2 || l.PrettyFields[0] != "field1" || l.PrettyFields[1] != "field2" {
		t.Errorf("PrettyFields: got %v", l.PrettyFields)
	}
	if l.ModuleLevels["myapp"] != testDebugLevel {
		t.Errorf("ModuleLevels[myapp]: got %q", l.ModuleLevels["myapp"])
	}
	if l.ModuleLevels["asyncio"] != "WARNING" {
		t.Errorf("ModuleLevels[asyncio]: got %q", l.ModuleLevels["asyncio"])
	}
}

func TestConfigFromEnv_TracingGroup(t *testing.T) {
	t.Setenv("PROVIDE_TRACE_ENABLED", "false")
	t.Setenv("PROVIDE_TRACE_SAMPLE_RATE", "0.5")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Tracing.Enabled {
		t.Error("Tracing.Enabled should be false")
	}
	if cfg.Tracing.SampleRate != 0.5 {
		t.Errorf("Tracing.SampleRate: got %f, want 0.5", cfg.Tracing.SampleRate)
	}
}

func TestConfigFromEnv_MetricsGroup(t *testing.T) {
	t.Setenv("PROVIDE_METRICS_ENABLED", "false")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Metrics.Enabled {
		t.Error("Metrics.Enabled should be false")
	}
}

func TestConfigFromEnv_SamplingGroup(t *testing.T) {
	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "0.1")
	t.Setenv("PROVIDE_SAMPLING_TRACES_RATE", "0.2")
	t.Setenv("PROVIDE_SAMPLING_METRICS_RATE", "0.3")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Sampling.LogsRate != 0.1 {
		t.Errorf("LogsRate: got %f", cfg.Sampling.LogsRate)
	}
	if cfg.Sampling.TracesRate != 0.2 {
		t.Errorf("TracesRate: got %f", cfg.Sampling.TracesRate)
	}
	if cfg.Sampling.MetricsRate != 0.3 {
		t.Errorf("MetricsRate: got %f", cfg.Sampling.MetricsRate)
	}
}

func TestConfigFromEnv_BackpressureGroup(t *testing.T) {
	t.Setenv("PROVIDE_BACKPRESSURE_LOGS_MAXSIZE", "100")
	t.Setenv("PROVIDE_BACKPRESSURE_TRACES_MAXSIZE", "200")
	t.Setenv("PROVIDE_BACKPRESSURE_METRICS_MAXSIZE", "300")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Backpressure.LogsMaxSize != 100 {
		t.Errorf("LogsMaxSize: got %d", cfg.Backpressure.LogsMaxSize)
	}
	if cfg.Backpressure.TracesMaxSize != 200 {
		t.Errorf("TracesMaxSize: got %d", cfg.Backpressure.TracesMaxSize)
	}
	if cfg.Backpressure.MetricsMaxSize != 300 {
		t.Errorf("MetricsMaxSize: got %d", cfg.Backpressure.MetricsMaxSize)
	}
}

func TestConfigFromEnv_ExporterGroup(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_LOGS_RETRIES", "3")
	t.Setenv("PROVIDE_EXPORTER_TRACES_RETRIES", "4")
	t.Setenv("PROVIDE_EXPORTER_METRICS_RETRIES", "5")
	t.Setenv("PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS", "1.5")
	t.Setenv("PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS", "2.5")
	t.Setenv("PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS", "3.5")
	t.Setenv("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "30.0")
	t.Setenv("PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS", "31.0")
	t.Setenv("PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS", "32.0")
	t.Setenv("PROVIDE_EXPORTER_LOGS_FAIL_OPEN", "false")
	t.Setenv("PROVIDE_EXPORTER_TRACES_FAIL_OPEN", "false")
	t.Setenv("PROVIDE_EXPORTER_METRICS_FAIL_OPEN", "false")
	t.Setenv("PROVIDE_EXPORTER_LOGS_ALLOW_BLOCKING_EVENT_LOOP", "true")
	t.Setenv("PROVIDE_EXPORTER_TRACES_ALLOW_BLOCKING_EVENT_LOOP", "true")
	t.Setenv("PROVIDE_EXPORTER_METRICS_ALLOW_BLOCKING_EVENT_LOOP", "true")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	e := cfg.Exporter
	if e.LogsRetries != 3 {
		t.Errorf("LogsRetries: got %d", e.LogsRetries)
	}
	if e.TracesRetries != 4 {
		t.Errorf("TracesRetries: got %d", e.TracesRetries)
	}
	if e.MetricsRetries != 5 {
		t.Errorf("MetricsRetries: got %d", e.MetricsRetries)
	}
	if e.LogsBackoffSeconds != 1.5 {
		t.Errorf("LogsBackoffSeconds: got %f", e.LogsBackoffSeconds)
	}
	if e.TracesBackoffSeconds != 2.5 {
		t.Errorf("TracesBackoffSeconds: got %f", e.TracesBackoffSeconds)
	}
	if e.MetricsBackoffSeconds != 3.5 {
		t.Errorf("MetricsBackoffSeconds: got %f", e.MetricsBackoffSeconds)
	}
	if e.LogsTimeoutSeconds != 30.0 {
		t.Errorf("LogsTimeoutSeconds: got %f", e.LogsTimeoutSeconds)
	}
	if e.TracesTimeoutSeconds != 31.0 {
		t.Errorf("TracesTimeoutSeconds: got %f", e.TracesTimeoutSeconds)
	}
	if e.MetricsTimeoutSeconds != 32.0 {
		t.Errorf("MetricsTimeoutSeconds: got %f", e.MetricsTimeoutSeconds)
	}
	if e.LogsFailOpen {
		t.Error("LogsFailOpen should be false")
	}
	if e.TracesFailOpen {
		t.Error("TracesFailOpen should be false")
	}
	if e.MetricsFailOpen {
		t.Error("MetricsFailOpen should be false")
	}
	if !e.LogsAllowBlockingInEventLoop {
		t.Error("LogsAllowBlockingInEventLoop should be true")
	}
	if !e.TracesAllowBlockingInEventLoop {
		t.Error("TracesAllowBlockingInEventLoop should be true")
	}
	if !e.MetricsAllowBlockingInEventLoop {
		t.Error("MetricsAllowBlockingInEventLoop should be true")
	}
}

func TestConfigFromEnv_SLOGroup(t *testing.T) {
	t.Setenv("PROVIDE_SLO_ENABLE_RED_METRICS", "true")
	t.Setenv("PROVIDE_SLO_ENABLE_USE_METRICS", "true")
	t.Setenv("PROVIDE_SLO_INCLUDE_ERROR_TAXONOMY", "false")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !cfg.SLO.EnableREDMetrics {
		t.Error("EnableREDMetrics should be true")
	}
	if !cfg.SLO.EnableUSEMetrics {
		t.Error("EnableUSEMetrics should be true")
	}
	if cfg.SLO.IncludeErrorTaxonomy {
		t.Error("IncludeErrorTaxonomy should be false")
	}
}

func TestConfigFromEnv_SecurityGroup(t *testing.T) {
	t.Setenv("PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH", "512")
	t.Setenv("PROVIDE_SECURITY_MAX_ATTR_COUNT", "32")
	t.Setenv("PROVIDE_SECURITY_MAX_NESTING_DEPTH", "4")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Security.MaxAttrValueLength != 512 {
		t.Errorf("MaxAttrValueLength: got %d", cfg.Security.MaxAttrValueLength)
	}
	if cfg.Security.MaxAttrCount != 32 {
		t.Errorf("MaxAttrCount: got %d", cfg.Security.MaxAttrCount)
	}
	if cfg.Security.MaxNestingDepth != 4 {
		t.Errorf("MaxNestingDepth: got %d", cfg.Security.MaxNestingDepth)
	}
}

// ---- Bool parsing ----

func TestParseBool_TrueValues(t *testing.T) {
	trueInputs := []string{"1", "true", "TRUE", "True", "yes", "YES", "on", "ON"}
	for _, v := range trueInputs {
		got := parseBool(v, false)
		if !got {
			t.Errorf("parseBool(%q, false) = false, want true", v)
		}
	}
}

func TestParseBool_FalseValues(t *testing.T) {
	falseInputs := []string{"false", "FALSE", "0", "no", "off", "garbage"}
	for _, v := range falseInputs {
		got := parseBool(v, true)
		if got {
			t.Errorf("parseBool(%q, true) = true, want false", v)
		}
	}
}

func TestParseBool_EmptyUsesDefault(t *testing.T) {
	if parseBool("", true) != true {
		t.Error("empty string should return default=true")
	}
	if parseBool("", false) != false {
		t.Error("empty string should return default=false")
	}
}

func TestParseEnvBool_InvalidValueErrors(t *testing.T) {
	got, err := parseEnvBool("invalid-boolean", true, "PROVIDE_TRACE_ENABLED")
	if err == nil {
		t.Fatal("expected error for invalid boolean env value")
	}
	if got {
		t.Fatal("invalid boolean should not silently coerce to true")
	}
}

func TestConfigFromEnv_InvalidBooleanErrors(t *testing.T) {
	t.Setenv("PROVIDE_TRACE_ENABLED", "invalid-boolean")

	_, err := ConfigFromEnv()
	if err == nil {
		t.Fatal("expected invalid boolean env to fail config load")
	}
}

func TestApplyTopLevelEnv_InvalidStrictSchemaBool(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	err := applyTopLevelEnv(cfg, func(key string) string {
		if key == "PROVIDE_TELEMETRY_STRICT_SCHEMA" {
			return "invalid-boolean"
		}
		return ""
	})
	if err == nil {
		t.Fatal("expected invalid strict schema boolean to fail")
	}
}

func TestApplyTopLevelEnv_InvalidStrictEventNameBool(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	err := applyTopLevelEnv(cfg, func(key string) string {
		if key == "PROVIDE_TELEMETRY_STRICT_EVENT_NAME" {
			return "invalid-boolean"
		}
		return ""
	})
	if err == nil {
		t.Fatal("expected invalid strict event name boolean to fail")
	}
}

func TestApplyTopLevelEnv_PopulatesFields(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	err := applyTopLevelEnv(cfg, func(key string) string {
		values := map[string]string{
			"PROVIDE_TELEMETRY_SERVICE_NAME":      "svc",
			"PROVIDE_TELEMETRY_ENV":               "prod",
			"PROVIDE_TELEMETRY_VERSION":           "1.2.3",
			"PROVIDE_TELEMETRY_STRICT_SCHEMA":     "true",
			"PROVIDE_TELEMETRY_STRICT_EVENT_NAME": "true",
			"PROVIDE_TELEMETRY_REQUIRED_KEYS":     "request_id, session_id",
		}
		return values[key]
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.ServiceName != "svc" || cfg.Environment != "prod" || cfg.Version != "1.2.3" {
		t.Fatalf("unexpected top-level values: %+v", cfg)
	}
	if !cfg.StrictSchema || !cfg.EventSchema.StrictEventName {
		t.Fatal("expected strict schema flags to be applied")
	}
	if got := len(cfg.EventSchema.RequiredKeys); got != 2 {
		t.Fatalf("expected required keys to be parsed, got %d", got)
	}
}

func TestApplyLoggingEnv_InvalidBoolErrors(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	err := applyLoggingEnv(cfg, func(key string) string {
		if key == "PROVIDE_LOG_INCLUDE_TIMESTAMP" {
			return "invalid-boolean"
		}
		return ""
	})
	if err == nil {
		t.Fatal("expected invalid logging boolean to fail")
	}
}

func TestApplyLoggingEnv_InvalidOtherBoolErrors(t *testing.T) {
	for _, key := range []string{
		"PROVIDE_LOG_INCLUDE_CALLER",
		"PROVIDE_LOG_SANITIZE",
		"PROVIDE_LOG_CODE_ATTRIBUTES",
	} {
		t.Run(key, func(t *testing.T) {
			cfg := DefaultTelemetryConfig()
			err := applyLoggingEnv(cfg, func(k string) string {
				if k == key {
					return "invalid-boolean"
				}
				return ""
			})
			if err == nil {
				t.Fatalf("expected %s to fail", key)
			}
		})
	}
}

func TestApplyLoggingEnv_PopulatesFields(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	err := applyLoggingEnv(cfg, func(key string) string {
		values := map[string]string{
			"PROVIDE_LOG_LEVEL":              "debug",
			"PROVIDE_LOG_FORMAT":             "json",
			"PROVIDE_LOG_INCLUDE_TIMESTAMP":  "false",
			"PROVIDE_LOG_INCLUDE_CALLER":     "false",
			"PROVIDE_LOG_SANITIZE":           "false",
			"PROVIDE_LOG_CODE_ATTRIBUTES":    "true",
			"PROVIDE_LOG_PRETTY_KEY_COLOR":   "blue",
			"PROVIDE_LOG_PRETTY_VALUE_COLOR": "green",
			"PROVIDE_LOG_PRETTY_FIELDS":      "event,request_id",
			"PROVIDE_LOG_MODULE_LEVELS":      "pkg=DEBUG",
		}
		return values[key]
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Logging.Level != "DEBUG" || cfg.Logging.Format != "json" {
		t.Fatalf("unexpected logging config: %+v", cfg.Logging)
	}
	if cfg.Logging.IncludeTimestamp || cfg.Logging.IncludeCaller || cfg.Logging.Sanitize {
		t.Fatal("expected boolean logging fields to be false")
	}
	if !cfg.Logging.LogCodeAttributes {
		t.Fatal("expected log code attributes to be enabled")
	}
	if cfg.Logging.PrettyKeyColor != "blue" || cfg.Logging.PrettyValueColor != "green" {
		t.Fatal("expected pretty colors to be applied")
	}
	if len(cfg.Logging.PrettyFields) != 2 || cfg.Logging.ModuleLevels["pkg"] != "DEBUG" {
		t.Fatal("expected pretty fields and module levels to be parsed")
	}
}

func TestApplyMetricsEnv_InvalidBoolErrors(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	err := applyMetricsEnv(cfg, func(key string) string {
		if key == "PROVIDE_METRICS_ENABLED" {
			return "invalid-boolean"
		}
		return ""
	})
	if err == nil {
		t.Fatal("expected invalid metrics boolean to fail")
	}
}

func TestApplyExporterEnv_PopulatesFields(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	err := applyExporterEnv(cfg, func(key string) string {
		values := map[string]string{
			"OTEL_EXPORTER_OTLP_ENDPOINT":                        "http://collector:4318",
			"OTEL_EXPORTER_OTLP_HEADERS":                         "Authorization=Bearer%20token",
			"PROVIDE_EXPORTER_LOGS_FAIL_OPEN":                    "false",
			"PROVIDE_EXPORTER_TRACES_FAIL_OPEN":                  "false",
			"PROVIDE_EXPORTER_METRICS_FAIL_OPEN":                 "false",
			"PROVIDE_EXPORTER_LOGS_ALLOW_BLOCKING_EVENT_LOOP":    "true",
			"PROVIDE_EXPORTER_TRACES_ALLOW_BLOCKING_EVENT_LOOP":  "true",
			"PROVIDE_EXPORTER_METRICS_ALLOW_BLOCKING_EVENT_LOOP": "true",
		}
		return values[key]
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Logging.OTLPEndpoint != "http://collector:4318" || cfg.Tracing.OTLPEndpoint != "http://collector:4318" || cfg.Metrics.OTLPEndpoint != "http://collector:4318" {
		t.Fatal("expected generic OTLP endpoint fallback to apply")
	}
	if cfg.Logging.OTLPHeaders["Authorization"] != "Bearer token" {
		t.Fatal("expected generic OTLP headers to be parsed")
	}
	if cfg.Exporter.LogsFailOpen || cfg.Exporter.TracesFailOpen || cfg.Exporter.MetricsFailOpen {
		t.Fatal("expected fail-open flags to be false")
	}
	if !cfg.Exporter.LogsAllowBlockingInEventLoop || !cfg.Exporter.TracesAllowBlockingInEventLoop || !cfg.Exporter.MetricsAllowBlockingInEventLoop {
		t.Fatal("expected allow-blocking flags to be true")
	}
}

func TestApplyExporterEnv_InvalidBoolErrors(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	err := applyExporterEnv(cfg, func(key string) string {
		if key == "PROVIDE_EXPORTER_LOGS_FAIL_OPEN" {
			return "invalid-boolean"
		}
		return ""
	})
	if err == nil {
		t.Fatal("expected invalid exporter boolean to fail")
	}
}

func TestApplyExporterEnv_InvalidOtherBoolErrors(t *testing.T) {
	for _, key := range []string{
		"PROVIDE_EXPORTER_TRACES_FAIL_OPEN",
		"PROVIDE_EXPORTER_METRICS_FAIL_OPEN",
		"PROVIDE_EXPORTER_LOGS_ALLOW_BLOCKING_EVENT_LOOP",
		"PROVIDE_EXPORTER_TRACES_ALLOW_BLOCKING_EVENT_LOOP",
		"PROVIDE_EXPORTER_METRICS_ALLOW_BLOCKING_EVENT_LOOP",
	} {
		t.Run(key, func(t *testing.T) {
			cfg := DefaultTelemetryConfig()
			err := applyExporterEnv(cfg, func(k string) string {
				if k == key {
					return "invalid-boolean"
				}
				return ""
			})
			if err == nil {
				t.Fatalf("expected %s to fail", key)
			}
		})
	}
}

func TestApplySLOEnv_InvalidBoolErrors(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	err := applySLOEnv(cfg, func(key string) string {
		if key == "PROVIDE_SLO_ENABLE_RED_METRICS" {
			return "invalid-boolean"
		}
		return ""
	})
	if err == nil {
		t.Fatal("expected invalid SLO boolean to fail")
	}
}

func TestApplySLOEnv_InvalidEnableUseBoolErrors(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	err := applySLOEnv(cfg, func(key string) string {
		if key == "PROVIDE_SLO_ENABLE_USE_METRICS" {
			return "invalid-boolean"
		}
		return ""
	})
	if err == nil {
		t.Fatal("expected invalid SLO enable-use boolean to fail")
	}
}

func TestApplySLOEnv_PopulatesFields(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	err := applySLOEnv(cfg, func(key string) string {
		values := map[string]string{
			"PROVIDE_SLO_ENABLE_RED_METRICS":     "true",
			"PROVIDE_SLO_ENABLE_USE_METRICS":     "true",
			"PROVIDE_SLO_INCLUDE_ERROR_TAXONOMY": "false",
		}
		return values[key]
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !cfg.SLO.EnableREDMetrics || !cfg.SLO.EnableUSEMetrics || cfg.SLO.IncludeErrorTaxonomy {
		t.Fatalf("unexpected SLO config: %+v", cfg.SLO)
	}
}

// ---- OTLP header parsing ----

func TestParseOTLPHeaders_Normal(t *testing.T) {
	// '+' is preserved as a literal character; use %20 for spaces.
	got := parseOTLPHeaders("Authorization=Bearer%20token,X-Tenant=abc")
	if got["Authorization"] != "Bearer token" {
		t.Errorf("Authorization: got %q", got["Authorization"])
	}
	if got["X-Tenant"] != "abc" {
		t.Errorf("X-Tenant: got %q", got["X-Tenant"])
	}
}

func TestParseOTLPHeaders_URLEncoded(t *testing.T) {
	got := parseOTLPHeaders("my%20key=my%20value")
	if got["my key"] != "my value" {
		t.Errorf("URL-decoded: got %v", got)
	}
}

func TestParseOTLPHeaders_Malformed_Skipped(t *testing.T) {
	// pair without '=' should be skipped
	got := parseOTLPHeaders("no-equals,key=val")
	if _, ok := got["no-equals"]; ok {
		t.Error("malformed pair should be skipped")
	}
	if got["key"] != "val" {
		t.Errorf("valid pair: got %q", got["key"])
	}
}

func TestParseOTLPHeaders_EmptyKey_Skipped(t *testing.T) {
	got := parseOTLPHeaders("=value,key=val")
	if _, ok := got[""]; ok {
		t.Error("empty key should be skipped")
	}
	if got["key"] != "val" {
		t.Errorf("valid pair: got %q", got["key"])
	}
}

func TestParseOTLPHeaders_InvalidURLEncodedValue_Skipped(t *testing.T) {
	// A percent sign followed by invalid hex causes url.QueryUnescape to fail on the value.
	got := parseOTLPHeaders("key=%ZZ,other=ok")
	if _, ok := got["key"]; ok {
		t.Error("pair with invalid URL-encoded value should be skipped")
	}
	if got["other"] != "ok" {
		t.Errorf("valid pair: got %q", got["other"])
	}
}

func TestParseOTLPHeaders_InvalidURLEncodedKey_Skipped(t *testing.T) {
	// A percent sign followed by invalid hex in the key should also be skipped.
	got := parseOTLPHeaders("%ZZ=value,other=ok")
	if _, ok := got["%ZZ"]; ok {
		t.Error("pair with invalid URL-encoded key should be skipped")
	}
	if got["other"] != "ok" {
		t.Errorf("valid pair: got %q", got["other"])
	}
}

func TestParseOTLPHeaders_SingleCharKey_Accepted(t *testing.T) {
	got := parseOTLPHeaders("k=v")
	if got["k"] != "v" {
		t.Errorf("single-char key: want k=v, got %v", got)
	}
}

func TestParseOTLPHeaders_Empty(t *testing.T) {
	got := parseOTLPHeaders("")
	if len(got) != 0 {
		t.Errorf("empty input: got %v", got)
	}
}

// ---- Module levels parsing ----

func TestParseModuleLevels_Valid(t *testing.T) {
	got, err := parseModuleLevels("myapp=DEBUG,asyncio=WARNING")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got["myapp"] != testDebugLevel {
		t.Errorf("myapp: got %q", got["myapp"])
	}
	if got["asyncio"] != "WARNING" {
		t.Errorf("asyncio: got %q", got["asyncio"])
	}
}

func TestParseModuleLevels_MixedCase(t *testing.T) {
	got, err := parseModuleLevels("pkg=info")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got["pkg"] != "INFO" {
		t.Errorf("level should be normalised to INFO, got %q", got["pkg"])
	}
}

func TestParseModuleLevels_SingleCharModule_Accepted(t *testing.T) {
	got, err := parseModuleLevels("a=DEBUG")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got["a"] != testDebugLevel {
		t.Errorf("single-char module: got %q, want %q", got["a"], testDebugLevel)
	}
}

func TestParseModuleLevels_MalformedPair_Skipped(t *testing.T) {
	got, err := parseModuleLevels("no-equals,pkg=DEBUG")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if _, ok := got["no-equals"]; ok {
		t.Error("malformed pair should be skipped")
	}
	if got["pkg"] != testDebugLevel {
		t.Errorf("valid pair: got %q", got["pkg"])
	}
}

func TestParseModuleLevels_EmptyModuleName_Skipped(t *testing.T) {
	// "=DEBUG" has an '=' but empty module name — should be skipped.
	got, err := parseModuleLevels("=DEBUG,pkg=INFO")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if _, ok := got[""]; ok {
		t.Error("empty module name should be skipped")
	}
	if got["pkg"] != "INFO" {
		t.Errorf("valid pair: got %q", got["pkg"])
	}
}

func TestParseModuleLevels_Empty(t *testing.T) {
	got, err := parseModuleLevels("")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got) != 0 {
		t.Errorf("expected empty map, got %v", got)
	}
}

func TestParseModuleLevels_InvalidLevel_Error(t *testing.T) {
	_, err := parseModuleLevels("pkg=BADLEVEL")
	if err == nil {
		t.Fatal("expected error for invalid level")
	}
	var cfgErr *ConfigurationError
	if !errors.As(err, &cfgErr) {
		t.Errorf("expected *ConfigurationError, got %T", err)
	}
}

// ---- OTLP endpoint fallback ----

func TestConfigFromEnv_OTLPEndpointFallback(t *testing.T) {
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", testDefaultEndpoint)
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Logging.OTLPEndpoint != testDefaultEndpoint {
		t.Errorf("Logging.OTLPEndpoint: got %q", cfg.Logging.OTLPEndpoint)
	}
	if cfg.Tracing.OTLPEndpoint != testDefaultEndpoint {
		t.Errorf("Tracing.OTLPEndpoint: got %q", cfg.Tracing.OTLPEndpoint)
	}
	if cfg.Metrics.OTLPEndpoint != testDefaultEndpoint {
		t.Errorf("Metrics.OTLPEndpoint: got %q", cfg.Metrics.OTLPEndpoint)
	}
}

func TestConfigFromEnv_OTLPEndpointSignalSpecificTakesPriority(t *testing.T) {
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", testDefaultEndpoint)
	t.Setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://traces:4318")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Tracing.OTLPEndpoint != "http://traces:4318" {
		t.Errorf("Tracing.OTLPEndpoint: got %q, want http://traces:4318", cfg.Tracing.OTLPEndpoint)
	}
	// Other signals still fall back to generic
	if cfg.Logging.OTLPEndpoint != testDefaultEndpoint {
		t.Errorf("Logging.OTLPEndpoint: got %q", cfg.Logging.OTLPEndpoint)
	}
}

func TestConfigFromEnv_OTLPHeadersFallback(t *testing.T) {
	t.Setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Bearer%20generic")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Logging.OTLPHeaders["Authorization"] != "Bearer generic" {
		t.Errorf("Logging.OTLPHeaders: got %v", cfg.Logging.OTLPHeaders)
	}
	if cfg.Tracing.OTLPHeaders["Authorization"] != "Bearer generic" {
		t.Errorf("Tracing.OTLPHeaders: got %v", cfg.Tracing.OTLPHeaders)
	}
}

func TestConfigFromEnv_OTLPHeadersSignalSpecific(t *testing.T) {
	t.Setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Bearer%20generic")
	t.Setenv("OTEL_EXPORTER_OTLP_LOGS_HEADERS", "X-Token=logs-token")
	t.Setenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "X-Token=traces-token")
	t.Setenv("OTEL_EXPORTER_OTLP_METRICS_HEADERS", "X-Token=metrics-token")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Logging.OTLPHeaders["X-Token"] != "logs-token" {
		t.Errorf("logs signal-specific header: got %v", cfg.Logging.OTLPHeaders)
	}
	if cfg.Tracing.OTLPHeaders["X-Token"] != "traces-token" {
		t.Errorf("traces signal-specific header: got %v", cfg.Tracing.OTLPHeaders)
	}
	if cfg.Metrics.OTLPHeaders["X-Token"] != "metrics-token" {
		t.Errorf("metrics signal-specific header: got %v", cfg.Metrics.OTLPHeaders)
	}
}

// ---- Error cases ----

func TestConfigFromEnv_InvalidFloat_SampleRate(t *testing.T) {
	t.Setenv("PROVIDE_TRACE_SAMPLE_RATE", "not-a-float")
	_, err := ConfigFromEnv()
	if err == nil {
		t.Fatal("expected error for invalid float")
	}
	var cfgErr *ConfigurationError
	if !errors.As(err, &cfgErr) {
		t.Errorf("expected *ConfigurationError, got %T", err)
	}
}

func TestConfigFromEnv_InvalidFloat_SamplingLogs(t *testing.T) {
	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "bad")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidFloat_SamplingTraces(t *testing.T) {
	t.Setenv("PROVIDE_SAMPLING_TRACES_RATE", "bad")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidFloat_SamplingMetrics(t *testing.T) {
	t.Setenv("PROVIDE_SAMPLING_METRICS_RATE", "bad")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidFloat_ExporterLogsBackoff(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS", "bad")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidFloat_ExporterTracesBackoff(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS", "bad")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidFloat_ExporterMetricsBackoff(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS", "bad")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidFloat_ExporterLogsTimeout(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "bad")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidFloat_ExporterTracesTimeout(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS", "bad")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidFloat_ExporterMetricsTimeout(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS", "bad")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidInt_BackpressureLogs(t *testing.T) {
	t.Setenv("PROVIDE_BACKPRESSURE_LOGS_MAXSIZE", "not-int")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidInt_BackpressureTraces(t *testing.T) {
	t.Setenv("PROVIDE_BACKPRESSURE_TRACES_MAXSIZE", "not-int")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidInt_BackpressureMetrics(t *testing.T) {
	t.Setenv("PROVIDE_BACKPRESSURE_METRICS_MAXSIZE", "not-int")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidInt_ExporterLogsRetries(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_LOGS_RETRIES", "not-int")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidInt_ExporterTracesRetries(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_TRACES_RETRIES", "not-int")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidInt_ExporterMetricsRetries(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_METRICS_RETRIES", "not-int")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidInt_SecurityAttrValueLength(t *testing.T) {
	t.Setenv("PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH", "not-int")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidInt_SecurityAttrCount(t *testing.T) {
	t.Setenv("PROVIDE_SECURITY_MAX_ATTR_COUNT", "not-int")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidInt_SecurityNestingDepth(t *testing.T) {
	t.Setenv("PROVIDE_SECURITY_MAX_NESTING_DEPTH", "not-int")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidLogLevel(t *testing.T) {
	t.Setenv("PROVIDE_LOG_LEVEL", "BADLEVEL")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidLogFormat(t *testing.T) {
	t.Setenv("PROVIDE_LOG_FORMAT", "xml")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestConfigFromEnv_InvalidModuleLevel(t *testing.T) {
	t.Setenv("PROVIDE_LOG_MODULE_LEVELS", "mypkg=NOTLEVEL")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

// ---- Log level normalisation coverage ----

func TestNormalizeLevel_AllValid(t *testing.T) {
	cases := []struct{ in, want string }{
		{"TRACE", "TRACE"}, {"trace", "TRACE"},
		{"DEBUG", "DEBUG"}, {"debug", "DEBUG"},
		{"INFO", "INFO"}, {"info", "INFO"},
		{"WARNING", "WARNING"}, {"warning", "WARNING"},
		{"ERROR", "ERROR"}, {"error", "ERROR"},
		{"CRITICAL", "CRITICAL"}, {"critical", "CRITICAL"},
	}
	for _, tc := range cases {
		got, err := normalizeLevel(tc.in)
		if err != nil {
			t.Errorf("normalizeLevel(%q): unexpected error %v", tc.in, err)
		}
		if got != tc.want {
			t.Errorf("normalizeLevel(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}

func TestNormalizeLevel_Invalid(t *testing.T) {
	_, err := normalizeLevel("VERBOSE")
	if err == nil {
		t.Fatal("expected error")
	}
	var cfgErr *ConfigurationError
	if !errors.As(err, &cfgErr) {
		t.Errorf("expected *ConfigurationError, got %T", err)
	}
}

// ---- firstNonEmpty ----

func TestFirstNonEmpty(t *testing.T) {
	if firstNonEmpty("", "b", "c") != "b" {
		t.Error("should return first non-empty")
	}
	if firstNonEmpty("", "") != "" {
		t.Error("all empty should return empty")
	}
	if firstNonEmpty("a", "b") != "a" {
		t.Error("should return first when first non-empty")
	}
}

// ---- splitTrimmed ----

func TestSplitTrimmed_Normal(t *testing.T) {
	got := splitTrimmed(" a , b , c ", ",")
	want := []string{"a", "b", "c"}
	if len(got) != len(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("[%d]: got %q, want %q", i, got[i], want[i])
		}
	}
}

func TestSplitTrimmed_EmptyElements_Skipped(t *testing.T) {
	got := splitTrimmed(",a,,b,", ",")
	if len(got) != 2 || got[0] != "a" || got[1] != "b" {
		t.Errorf("got %v", got)
	}
}

// ---- Range validation (Fix 2) ----

func TestValidateRate_BelowZero(t *testing.T) {
	t.Setenv("PROVIDE_TRACE_SAMPLE_RATE", "-0.1")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateRate_AboveOne(t *testing.T) {
	t.Setenv("PROVIDE_TRACE_SAMPLE_RATE", "1.1")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateRate_SamplingLogsBelow(t *testing.T) {
	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "-0.5")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateRate_SamplingTracesAbove(t *testing.T) {
	t.Setenv("PROVIDE_SAMPLING_TRACES_RATE", "2.0")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateRate_SamplingMetricsBelow(t *testing.T) {
	t.Setenv("PROVIDE_SAMPLING_METRICS_RATE", "-1.0")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateNonNegative_BackpressureLogs(t *testing.T) {
	t.Setenv("PROVIDE_BACKPRESSURE_LOGS_MAXSIZE", "-1")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateNonNegative_BackpressureTraces(t *testing.T) {
	t.Setenv("PROVIDE_BACKPRESSURE_TRACES_MAXSIZE", "-5")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateNonNegative_BackpressureMetrics(t *testing.T) {
	t.Setenv("PROVIDE_BACKPRESSURE_METRICS_MAXSIZE", "-10")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateNonNegative_SecurityAttrValueLength(t *testing.T) {
	t.Setenv("PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH", "-1")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateNonNegative_SecurityAttrCount(t *testing.T) {
	t.Setenv("PROVIDE_SECURITY_MAX_ATTR_COUNT", "-1")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateNonNegative_SecurityNestingDepth(t *testing.T) {
	t.Setenv("PROVIDE_SECURITY_MAX_NESTING_DEPTH", "-1")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateRate_ZeroAndOneAreValid(t *testing.T) {
	t.Setenv("PROVIDE_TRACE_SAMPLE_RATE", "0.0")
	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "1.0")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("0.0 and 1.0 should be valid rates, got error: %v", err)
	}
	if cfg.Tracing.SampleRate != 0.0 {
		t.Errorf("SampleRate: got %f, want 0.0", cfg.Tracing.SampleRate)
	}
	if cfg.Sampling.LogsRate != 1.0 {
		t.Errorf("LogsRate: got %f, want 1.0", cfg.Sampling.LogsRate)
	}
}

func TestValidateNonNegative_ZeroIsValid(t *testing.T) {
	t.Setenv("PROVIDE_BACKPRESSURE_LOGS_MAXSIZE", "0")
	t.Setenv("PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH", "0")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("0 should be a valid non-negative value, got error: %v", err)
	}
	if cfg.Backpressure.LogsMaxSize != 0 {
		t.Errorf("LogsMaxSize: got %d, want 0", cfg.Backpressure.LogsMaxSize)
	}
	if cfg.Security.MaxAttrValueLength != 0 {
		t.Errorf("MaxAttrValueLength: got %d, want 0", cfg.Security.MaxAttrValueLength)
	}
}

// ---- Exporter range validation (Fix 3) ----

func TestValidateNonNegative_ExporterLogsRetries(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_LOGS_RETRIES", "-1")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateNonNegative_ExporterTracesRetries(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_TRACES_RETRIES", "-2")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateNonNegative_ExporterMetricsRetries(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_METRICS_RETRIES", "-3")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateNonNegativeFloat_ExporterLogsBackoff(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS", "-0.5")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateNonNegativeFloat_ExporterTracesBackoff(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS", "-1.0")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateNonNegativeFloat_ExporterMetricsBackoff(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS", "-2.5")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateNonNegativeFloat_ExporterLogsTimeout(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "-1.0")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateNonNegativeFloat_ExporterTracesTimeout(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS", "-5.0")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateNonNegativeFloat_ExporterMetricsTimeout(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS", "-0.1")
	_, err := ConfigFromEnv()
	assertConfigError(t, err)
}

func TestValidateNonNegativeFloat_ZeroIsValid(t *testing.T) {
	t.Setenv("PROVIDE_EXPORTER_LOGS_RETRIES", "0")
	t.Setenv("PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS", "0.0")
	t.Setenv("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "0.0")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("0 should be valid for retries/backoff/timeout, got error: %v", err)
	}
	if cfg.Exporter.LogsRetries != 0 {
		t.Errorf("LogsRetries: got %d, want 0", cfg.Exporter.LogsRetries)
	}
	if cfg.Exporter.LogsBackoffSeconds != 0.0 {
		t.Errorf("LogsBackoffSeconds: got %f, want 0.0", cfg.Exporter.LogsBackoffSeconds)
	}
	if cfg.Exporter.LogsTimeoutSeconds != 0.0 {
		t.Errorf("LogsTimeoutSeconds: got %f, want 0.0", cfg.Exporter.LogsTimeoutSeconds)
	}
}

// ---- Helper ----

func assertConfigError(t *testing.T, err error) {
	t.Helper()
	if err == nil {
		t.Fatal("expected *ConfigurationError, got nil")
	}
	var cfgErr *ConfigurationError
	if !errors.As(err, &cfgErr) {
		t.Errorf("expected *ConfigurationError, got %T: %v", err, err)
	}
}
