// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import "testing"

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
