// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"testing"
)

// ---- Bool parsing ----

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

// ---- Error cases ----

func TestConfigFromEnv_InvalidFloat_SampleRate(t *testing.T) {
	t.Setenv("PROVIDE_TRACE_SAMPLE_RATE", "not-a-float")
	_, err := ConfigFromEnv()
	if err == nil {
		t.Fatal("expected error for invalid float")
	}
	assertConfigError(t, err)
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

// ---- Range validation ----

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

// ---- Exporter range validation ----

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
