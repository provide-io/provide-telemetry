// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"testing"
)

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

func TestConfigFromEnv_PIIMaxDepth(t *testing.T) {
	t.Setenv("PROVIDE_LOG_PII_MAX_DEPTH", "16")
	cfg, err := ConfigFromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Logging.PIIMaxDepth != 16 {
		t.Errorf("PIIMaxDepth: got %d, want 16", cfg.Logging.PIIMaxDepth)
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

// ---- apply*Env unit tests ----

func TestConfigFromEnv_PIIMaxDepth_InvalidInt(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	err := applyLoggingEnv(cfg, func(key string) string {
		if key == "PROVIDE_LOG_PII_MAX_DEPTH" {
			return "notanint"
		}
		return ""
	})
	if err == nil {
		t.Fatal("expected invalid integer to fail")
	}
}

func TestConfigFromEnv_PIIMaxDepth_Negative(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	err := applyLoggingEnv(cfg, func(key string) string {
		if key == "PROVIDE_LOG_PII_MAX_DEPTH" {
			return "-1"
		}
		return ""
	})
	if err == nil {
		t.Fatal("expected negative value to fail")
	}
}
