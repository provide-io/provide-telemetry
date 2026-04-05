// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"fmt"
	"net/url"
	"os"
	"strconv"
	"strings"
)

// Log format constants.
const (
	LogFormatConsole = "console"
	LogFormatJSON    = "json"
	LogFormatPretty  = "pretty"
)

// Log level constants.
const (
	LogLevelTrace    = "TRACE"
	LogLevelDebug    = "DEBUG"
	LogLevelInfo     = "INFO"
	LogLevelWarn     = "WARN"
	LogLevelWarning  = "WARNING"
	LogLevelError    = "ERROR"
	LogLevelCritical = "CRITICAL"
)

// LoggingConfig holds all logging-related configuration.
type LoggingConfig struct {
	Level             string            // default "INFO"
	Format            string            // default "console" (console|json|pretty)
	IncludeTimestamp  bool              // default true
	IncludeCaller     bool              // default true
	Sanitize          bool              // default true
	PIIMaxDepth       int               // default 0 (use SanitizePayload default of 8)
	OTLPEndpoint      string            // optional
	OTLPHeaders       map[string]string // optional
	LogCodeAttributes bool              // default false
	PrettyKeyColor    string            // default "dim"
	PrettyValueColor  string            // default ""
	PrettyFields      []string          // default []
	ModuleLevels      map[string]string // default {}
}

// TracingConfig holds all tracing-related configuration.
type TracingConfig struct {
	Enabled      bool    // default true
	SampleRate   float64 // default 1.0
	OTLPEndpoint string
	OTLPHeaders  map[string]string
}

// MetricsConfig holds all metrics-related configuration.
type MetricsConfig struct {
	Enabled      bool // default true
	OTLPEndpoint string
	OTLPHeaders  map[string]string
}

// SchemaConfig holds event schema validation configuration.
type SchemaConfig struct {
	StrictEventName bool
	RequiredKeys    []string
}

// SamplingConfig holds per-signal sampling rates.
type SamplingConfig struct {
	LogsRate    float64 // default 1.0
	TracesRate  float64 // default 1.0
	MetricsRate float64 // default 1.0
}

// BackpressureConfig holds bounded queue configuration.
type BackpressureConfig struct {
	LogsMaxSize    int // default 0
	TracesMaxSize  int
	MetricsMaxSize int
}

// ExporterPolicyConfig holds retry/timeout/fail-open policy for exporters.
type ExporterPolicyConfig struct {
	LogsRetries    int
	TracesRetries  int
	MetricsRetries int

	LogsBackoffSeconds    float64
	TracesBackoffSeconds  float64
	MetricsBackoffSeconds float64

	LogsTimeoutSeconds    float64 // default 10.0
	TracesTimeoutSeconds  float64 // default 10.0
	MetricsTimeoutSeconds float64 // default 10.0

	LogsFailOpen    bool // default true
	TracesFailOpen  bool // default true
	MetricsFailOpen bool // default true

	LogsAllowBlockingInEventLoop    bool
	TracesAllowBlockingInEventLoop  bool
	MetricsAllowBlockingInEventLoop bool
}

// SLOConfig holds SLO metric configuration.
type SLOConfig struct {
	EnableREDMetrics     bool
	EnableUSEMetrics     bool
	IncludeErrorTaxonomy bool // default true
}

// SecurityConfig holds attribute security limits.
type SecurityConfig struct {
	MaxAttrValueLength int // default 1024
	MaxAttrCount       int // default 64
	MaxNestingDepth    int // default 8
}

// RuntimeOverrides contains only hot-reloadable fields.
// Nil pointer fields mean "keep current value".
type RuntimeOverrides struct {
	Sampling     *SamplingConfig
	Backpressure *BackpressureConfig
	Exporter     *ExporterPolicyConfig
	Security     *SecurityConfig
	SLO          *SLOConfig
	PIIMaxDepth  *int
}

// TelemetryConfig is the top-level configuration for provide-telemetry.
type TelemetryConfig struct {
	ServiceName  string // default "provide-service"
	Environment  string // default "dev"
	Version      string // default "0.0.0"
	StrictSchema bool
	Logging      LoggingConfig
	Tracing      TracingConfig
	Metrics      MetricsConfig
	EventSchema  SchemaConfig
	Sampling     SamplingConfig
	Backpressure BackpressureConfig
	Exporter     ExporterPolicyConfig
	SLO          SLOConfig
	Security     SecurityConfig
}

// DefaultTelemetryConfig returns a *TelemetryConfig with all defaults applied.
func DefaultTelemetryConfig() *TelemetryConfig {
	return &TelemetryConfig{
		ServiceName: "provide-service",
		Environment: "dev",
		Version:     "0.0.0",
		Logging: LoggingConfig{
			Level:            LogLevelInfo,
			Format:           LogFormatConsole,
			IncludeTimestamp: true,
			IncludeCaller:    true,
			Sanitize:         true,
			OTLPHeaders:      map[string]string{},
			PrettyKeyColor:   "dim",
			PrettyValueColor: "",
			PrettyFields:     []string{},
			ModuleLevels:     map[string]string{},
		},
		Tracing: TracingConfig{
			Enabled:     true,
			SampleRate:  1.0,
			OTLPHeaders: map[string]string{},
		},
		Metrics: MetricsConfig{
			Enabled:     true,
			OTLPHeaders: map[string]string{},
		},
		EventSchema: SchemaConfig{
			RequiredKeys: []string{},
		},
		Sampling: SamplingConfig{
			LogsRate:    1.0,
			TracesRate:  1.0,
			MetricsRate: 1.0,
		},
		Exporter: ExporterPolicyConfig{
			LogsTimeoutSeconds:    10.0,
			TracesTimeoutSeconds:  10.0,
			MetricsTimeoutSeconds: 10.0,
			LogsFailOpen:          true,
			TracesFailOpen:        true,
			MetricsFailOpen:       true,
		},
		SLO: SLOConfig{
			IncludeErrorTaxonomy: true,
		},
		Security: SecurityConfig{
			MaxAttrValueLength: 1024,
			MaxAttrCount:       64,
			MaxNestingDepth:    8,
		},
	}
}

// ConfigFromEnv reads environment variables and returns a fully populated *TelemetryConfig.
// Returns *ConfigurationError for invalid values.
func ConfigFromEnv() (*TelemetryConfig, error) {
	cfg := DefaultTelemetryConfig()
	env := os.Getenv
	helpers := []func(*TelemetryConfig, func(string) string) error{
		applyTopLevelEnv,
		applyLoggingEnv,
		applyExporterEnv,
		applyTracingEnv,
		func(c *TelemetryConfig, e func(string) string) error { applyMetricsEnv(c, e); return nil },
		applySamplingEnv,
		applyBackpressureEnv,
		func(c *TelemetryConfig, e func(string) string) error { applySLOEnv(c, e); return nil },
		applySecurityEnv,
	}
	for _, fn := range helpers {
		if err := fn(cfg, env); err != nil {
			return nil, err
		}
	}
	return cfg, nil
}

// applyTopLevelEnv reads top-level and event-schema env vars into cfg.
func applyTopLevelEnv(cfg *TelemetryConfig, env func(string) string) error {
	if v := env("PROVIDE_TELEMETRY_SERVICE_NAME"); v != "" {
		cfg.ServiceName = v
	}
	if v := env("PROVIDE_TELEMETRY_ENV"); v != "" {
		cfg.Environment = v
	}
	if v := env("PROVIDE_TELEMETRY_VERSION"); v != "" {
		cfg.Version = v
	}
	cfg.StrictSchema = parseBool(env("PROVIDE_TELEMETRY_STRICT_SCHEMA"), false)
	cfg.EventSchema.StrictEventName = parseBool(env("PROVIDE_TELEMETRY_STRICT_EVENT_NAME"), false)
	if v := env("PROVIDE_TELEMETRY_REQUIRED_KEYS"); v != "" {
		cfg.EventSchema.RequiredKeys = splitTrimmed(v, ",")
	}
	return nil
}

// applyLoggingEnv reads logging-related env vars into cfg.
func applyLoggingEnv(cfg *TelemetryConfig, env func(string) string) error {
	if v := env("PROVIDE_LOG_LEVEL"); v != "" {
		normalized, err := normalizeLevel(v)
		if err != nil {
			return err
		}
		cfg.Logging.Level = normalized
	}
	if v := env("PROVIDE_LOG_FORMAT"); v != "" {
		if err := validateFormat(v); err != nil {
			return err
		}
		cfg.Logging.Format = v
	}
	cfg.Logging.IncludeTimestamp = parseBool(env("PROVIDE_LOG_INCLUDE_TIMESTAMP"), true)
	cfg.Logging.IncludeCaller = parseBool(env("PROVIDE_LOG_INCLUDE_CALLER"), true)
	cfg.Logging.Sanitize = parseBool(env("PROVIDE_LOG_SANITIZE"), true)
	cfg.Logging.LogCodeAttributes = parseBool(env("PROVIDE_LOG_CODE_ATTRIBUTES"), false)

// applyLoggingBoolFlags handles the boolean PROVIDE_LOG_* env vars and PII depth.
func applyLoggingBoolFlags(cfg *TelemetryConfig, env func(string) string) error {
	var err error
	cfg.Logging.IncludeTimestamp, err = parseEnvBool(env("PROVIDE_LOG_INCLUDE_TIMESTAMP"), true, "PROVIDE_LOG_INCLUDE_TIMESTAMP")
	if err != nil {
		return err
	}
	cfg.Logging.IncludeCaller, err = parseEnvBool(env("PROVIDE_LOG_INCLUDE_CALLER"), true, "PROVIDE_LOG_INCLUDE_CALLER")
	if err != nil {
		return err
	}
	cfg.Logging.Sanitize, err = parseEnvBool(env("PROVIDE_LOG_SANITIZE"), true, "PROVIDE_LOG_SANITIZE")
	if err != nil {
		return err
	}
	cfg.Logging.LogCodeAttributes, err = parseEnvBool(
		env("PROVIDE_LOG_CODE_ATTRIBUTES"),
		false,
		"PROVIDE_LOG_CODE_ATTRIBUTES",
	)
	if err != nil {
		return err
	}
	if v := env("PROVIDE_LOG_PII_MAX_DEPTH"); v != "" {
		n, err := parseEnvInt(v, "PROVIDE_LOG_PII_MAX_DEPTH")
		if err != nil {
			return err
		}
		if err := validateNonNegative(n, "PROVIDE_LOG_PII_MAX_DEPTH"); err != nil {
			return err
		}
		cfg.Logging.PIIMaxDepth = n
	}
	return nil
}

// applyLoggingPrettyAndModules handles pretty-print and module-level env vars.
func applyLoggingPrettyAndModules(cfg *TelemetryConfig, env func(string) string) error {
	if v := env("PROVIDE_LOG_PRETTY_KEY_COLOR"); v != "" {
		cfg.Logging.PrettyKeyColor = v
	}
	if v := env("PROVIDE_LOG_PRETTY_VALUE_COLOR"); v != "" {
		cfg.Logging.PrettyValueColor = v
	}
	if v := env("PROVIDE_LOG_PRETTY_FIELDS"); v != "" {
		cfg.Logging.PrettyFields = splitTrimmed(v, ",")
	}
	if v := env("PROVIDE_LOG_MODULE_LEVELS"); v != "" {
		ml, err := parseModuleLevels(v)
		if err != nil {
			return err
		}
		cfg.Logging.ModuleLevels = ml
	}
	return nil
}

// applyTracingEnv reads tracing-related env vars into cfg.
func applyTracingEnv(cfg *TelemetryConfig, env func(string) string) error {
	cfg.Tracing.Enabled = parseBool(env("PROVIDE_TRACE_ENABLED"), true)
	if v := env("PROVIDE_TRACE_SAMPLE_RATE"); v != "" {
		f, err := parseEnvFloat(v, "PROVIDE_TRACE_SAMPLE_RATE")
		if err != nil {
			return err
		}
		if err := validateRate(f, "PROVIDE_TRACE_SAMPLE_RATE"); err != nil {
			return err
		}
		cfg.Tracing.SampleRate = f
	}
	return nil
}

// applyMetricsEnv reads metrics-related env vars into cfg.
func applyMetricsEnv(cfg *TelemetryConfig, env func(string) string) {
	cfg.Metrics.Enabled = parseBool(env("PROVIDE_METRICS_ENABLED"), true)
}

// applySamplingEnv reads per-signal sampling rate env vars into cfg.
func applySamplingEnv(cfg *TelemetryConfig, env func(string) string) error {
	if v := env("PROVIDE_SAMPLING_LOGS_RATE"); v != "" {
		f, err := parseEnvFloat(v, "PROVIDE_SAMPLING_LOGS_RATE")
		if err != nil {
			return err
		}
		if err := validateRate(f, "PROVIDE_SAMPLING_LOGS_RATE"); err != nil {
			return err
		}
		cfg.Sampling.LogsRate = f
	}
	if v := env("PROVIDE_SAMPLING_TRACES_RATE"); v != "" {
		f, err := parseEnvFloat(v, "PROVIDE_SAMPLING_TRACES_RATE")
		if err != nil {
			return err
		}
		if err := validateRate(f, "PROVIDE_SAMPLING_TRACES_RATE"); err != nil {
			return err
		}
		cfg.Sampling.TracesRate = f
	}
	if v := env("PROVIDE_SAMPLING_METRICS_RATE"); v != "" {
		f, err := parseEnvFloat(v, "PROVIDE_SAMPLING_METRICS_RATE")
		if err != nil {
			return err
		}
		if err := validateRate(f, "PROVIDE_SAMPLING_METRICS_RATE"); err != nil {
			return err
		}
		cfg.Sampling.MetricsRate = f
	}
	return nil
}

// applyBackpressureEnv reads backpressure maxsize env vars into cfg.
func applyBackpressureEnv(cfg *TelemetryConfig, env func(string) string) error {
	if v := env("PROVIDE_BACKPRESSURE_LOGS_MAXSIZE"); v != "" {
		n, err := parseEnvInt(v, "PROVIDE_BACKPRESSURE_LOGS_MAXSIZE")
		if err != nil {
			return err
		}
		if err := validateNonNegative(n, "PROVIDE_BACKPRESSURE_LOGS_MAXSIZE"); err != nil {
			return err
		}
		cfg.Backpressure.LogsMaxSize = n
	}
	if v := env("PROVIDE_BACKPRESSURE_TRACES_MAXSIZE"); v != "" {
		n, err := parseEnvInt(v, "PROVIDE_BACKPRESSURE_TRACES_MAXSIZE")
		if err != nil {
			return err
		}
		if err := validateNonNegative(n, "PROVIDE_BACKPRESSURE_TRACES_MAXSIZE"); err != nil {
			return err
		}
		cfg.Backpressure.TracesMaxSize = n
	}
	if v := env("PROVIDE_BACKPRESSURE_METRICS_MAXSIZE"); v != "" {
		n, err := parseEnvInt(v, "PROVIDE_BACKPRESSURE_METRICS_MAXSIZE")
		if err != nil {
			return err
		}
		if err := validateNonNegative(n, "PROVIDE_BACKPRESSURE_METRICS_MAXSIZE"); err != nil {
			return err
		}
		cfg.Backpressure.MetricsMaxSize = n
	}
	return nil
}

// applyExporterEnv reads exporter policy env vars and OTLP endpoints/headers into cfg.
func applyExporterEnv(cfg *TelemetryConfig, env func(string) string) error {
	// OTLP endpoints/headers — signal-specific fallback to generic
	genericEndpoint := env("OTEL_EXPORTER_OTLP_ENDPOINT")
	genericHeaders := env("OTEL_EXPORTER_OTLP_HEADERS")

	cfg.Logging.OTLPEndpoint = firstNonEmpty(env("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"), genericEndpoint)
	cfg.Logging.OTLPHeaders = parseOTLPHeaders(firstNonEmpty(env("OTEL_EXPORTER_OTLP_LOGS_HEADERS"), genericHeaders))

	cfg.Tracing.OTLPEndpoint = firstNonEmpty(env("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"), genericEndpoint)
	cfg.Tracing.OTLPHeaders = parseOTLPHeaders(firstNonEmpty(env("OTEL_EXPORTER_OTLP_TRACES_HEADERS"), genericHeaders))

	cfg.Metrics.OTLPEndpoint = firstNonEmpty(env("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"), genericEndpoint)
	cfg.Metrics.OTLPHeaders = parseOTLPHeaders(firstNonEmpty(env("OTEL_EXPORTER_OTLP_METRICS_HEADERS"), genericHeaders))

	if err := applyExporterRetries(cfg, env); err != nil {
		return err
	}
	if err := applyExporterBackoff(cfg, env); err != nil {
		return err
	}
	if err := applyExporterTimeout(cfg, env); err != nil {
		return err
	}

	// Fail-open
	cfg.Exporter.LogsFailOpen = parseBool(env("PROVIDE_EXPORTER_LOGS_FAIL_OPEN"), true)
	cfg.Exporter.TracesFailOpen = parseBool(env("PROVIDE_EXPORTER_TRACES_FAIL_OPEN"), true)
	cfg.Exporter.MetricsFailOpen = parseBool(env("PROVIDE_EXPORTER_METRICS_FAIL_OPEN"), true)

	// Allow-blocking
	cfg.Exporter.LogsAllowBlockingInEventLoop = parseBool(env("PROVIDE_EXPORTER_LOGS_ALLOW_BLOCKING_EVENT_LOOP"), false)
	cfg.Exporter.TracesAllowBlockingInEventLoop = parseBool(env("PROVIDE_EXPORTER_TRACES_ALLOW_BLOCKING_EVENT_LOOP"), false)
	cfg.Exporter.MetricsAllowBlockingInEventLoop = parseBool(env("PROVIDE_EXPORTER_METRICS_ALLOW_BLOCKING_EVENT_LOOP"), false)

	return nil
}

// applyExporterRetries reads exporter retry count env vars into cfg.
func applyExporterRetries(cfg *TelemetryConfig, env func(string) string) error {
	if v := env("PROVIDE_EXPORTER_LOGS_RETRIES"); v != "" {
		n, err := parseEnvInt(v, "PROVIDE_EXPORTER_LOGS_RETRIES")
		if err != nil {
			return err
		}
		if err := validateNonNegative(n, "PROVIDE_EXPORTER_LOGS_RETRIES"); err != nil {
			return err
		}
		cfg.Exporter.LogsRetries = n
	}
	if v := env("PROVIDE_EXPORTER_TRACES_RETRIES"); v != "" {
		n, err := parseEnvInt(v, "PROVIDE_EXPORTER_TRACES_RETRIES")
		if err != nil {
			return err
		}
		if err := validateNonNegative(n, "PROVIDE_EXPORTER_TRACES_RETRIES"); err != nil {
			return err
		}
		cfg.Exporter.TracesRetries = n
	}
	if v := env("PROVIDE_EXPORTER_METRICS_RETRIES"); v != "" {
		n, err := parseEnvInt(v, "PROVIDE_EXPORTER_METRICS_RETRIES")
		if err != nil {
			return err
		}
		if err := validateNonNegative(n, "PROVIDE_EXPORTER_METRICS_RETRIES"); err != nil {
			return err
		}
		cfg.Exporter.MetricsRetries = n
	}
	return nil
}

// applyExporterBackoff reads exporter backoff seconds env vars into cfg.
func applyExporterBackoff(cfg *TelemetryConfig, env func(string) string) error {
	if v := env("PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS"); v != "" {
		f, err := parseEnvFloat(v, "PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS")
		if err != nil {
			return err
		}
		if err := validateNonNegativeFloat(f, "PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS"); err != nil {
			return err
		}
		cfg.Exporter.LogsBackoffSeconds = f
	}
	if v := env("PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS"); v != "" {
		f, err := parseEnvFloat(v, "PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS")
		if err != nil {
			return err
		}
		if err := validateNonNegativeFloat(f, "PROVIDE_EXPORTER_TRACES_BACKOFF_SECONDS"); err != nil {
			return err
		}
		cfg.Exporter.TracesBackoffSeconds = f
	}
	if v := env("PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS"); v != "" {
		f, err := parseEnvFloat(v, "PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS")
		if err != nil {
			return err
		}
		if err := validateNonNegativeFloat(f, "PROVIDE_EXPORTER_METRICS_BACKOFF_SECONDS"); err != nil {
			return err
		}
		cfg.Exporter.MetricsBackoffSeconds = f
	}
	return nil
}

// applyExporterTimeout reads exporter timeout seconds env vars into cfg.
func applyExporterTimeout(cfg *TelemetryConfig, env func(string) string) error {
	if v := env("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS"); v != "" {
		f, err := parseEnvFloat(v, "PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS")
		if err != nil {
			return err
		}
		if err := validateNonNegativeFloat(f, "PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS"); err != nil {
			return err
		}
		cfg.Exporter.LogsTimeoutSeconds = f
	}
	if v := env("PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS"); v != "" {
		f, err := parseEnvFloat(v, "PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS")
		if err != nil {
			return err
		}
		if err := validateNonNegativeFloat(f, "PROVIDE_EXPORTER_TRACES_TIMEOUT_SECONDS"); err != nil {
			return err
		}
		cfg.Exporter.TracesTimeoutSeconds = f
	}
	if v := env("PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS"); v != "" {
		f, err := parseEnvFloat(v, "PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS")
		if err != nil {
			return err
		}
		if err := validateNonNegativeFloat(f, "PROVIDE_EXPORTER_METRICS_TIMEOUT_SECONDS"); err != nil {
			return err
		}
		cfg.Exporter.MetricsTimeoutSeconds = f
	}
	return nil
}

// applySLOEnv reads SLO env vars into cfg.
func applySLOEnv(cfg *TelemetryConfig, env func(string) string) {
	cfg.SLO.EnableREDMetrics = parseBool(env("PROVIDE_SLO_ENABLE_RED_METRICS"), false)
	cfg.SLO.EnableUSEMetrics = parseBool(env("PROVIDE_SLO_ENABLE_USE_METRICS"), false)
	cfg.SLO.IncludeErrorTaxonomy = parseBool(env("PROVIDE_SLO_INCLUDE_ERROR_TAXONOMY"), true)
}

// applySecurityEnv reads security limit env vars into cfg.
func applySecurityEnv(cfg *TelemetryConfig, env func(string) string) error {
	if v := env("PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH"); v != "" {
		n, err := parseEnvInt(v, "PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH")
		if err != nil {
			return err
		}
		if err := validateNonNegative(n, "PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH"); err != nil {
			return err
		}
		cfg.Security.MaxAttrValueLength = n
	}
	if v := env("PROVIDE_SECURITY_MAX_ATTR_COUNT"); v != "" {
		n, err := parseEnvInt(v, "PROVIDE_SECURITY_MAX_ATTR_COUNT")
		if err != nil {
			return err
		}
		if err := validateNonNegative(n, "PROVIDE_SECURITY_MAX_ATTR_COUNT"); err != nil {
			return err
		}
		cfg.Security.MaxAttrCount = n
	}
	if v := env("PROVIDE_SECURITY_MAX_NESTING_DEPTH"); v != "" {
		n, err := parseEnvInt(v, "PROVIDE_SECURITY_MAX_NESTING_DEPTH")
		if err != nil {
			return err
		}
		if err := validateNonNegative(n, "PROVIDE_SECURITY_MAX_NESTING_DEPTH"); err != nil {
			return err
		}
		cfg.Security.MaxNestingDepth = n
	}
	return nil
}

// validateRate returns a ConfigurationError if v is not in [0.0, 1.0].
func validateRate(v float64, field string) error {
	if v < 0.0 || v > 1.0 {
		return NewConfigurationError(fmt.Sprintf("%s must be in [0.0, 1.0], got %g", field, v))
	}
	return nil
}

// validateNonNegative returns a ConfigurationError if v is negative.
func validateNonNegative(v int, field string) error {
	if v < 0 {
		return NewConfigurationError(fmt.Sprintf("%s must be >= 0, got %d", field, v))
	}
	return nil
}

// validateNonNegativeFloat returns a ConfigurationError if v is negative.
func validateNonNegativeFloat(v float64, field string) error {
	if v < 0 {
		return NewConfigurationError(fmt.Sprintf("%s must be >= 0, got %g", field, v))
	}
	return nil
}

// parseBool interprets "1", "true", "yes", "on" (case-insensitive) as true;
// empty string returns the default; anything else returns false.
func parseBool(value string, defaultVal bool) bool {
	if value == "" {
		return defaultVal
	}
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "1", "true", "yes", "on":
		return true
	default:
		return false
	}
}

// normalizeLevel validates and normalises a log level string.
func normalizeLevel(value string) (string, error) {
	allowed := map[string]struct{}{
		LogLevelTrace: {}, LogLevelDebug: {}, LogLevelInfo: {},
		LogLevelWarning: {}, LogLevelError: {}, LogLevelCritical: {},
	}
	upper := strings.ToUpper(strings.TrimSpace(value))
	if _, ok := allowed[upper]; !ok {
		return "", NewConfigurationError(fmt.Sprintf("invalid log level: %s", value))
	}
	return upper, nil
}

// validateFormat checks that the log format is one of the allowed values.
func validateFormat(value string) error {
	switch value {
	case LogFormatConsole, LogFormatJSON, LogFormatPretty:
		return nil
	default:
		return NewConfigurationError(fmt.Sprintf("invalid log format: %s", value))
	}
}

// parseEnvFloat parses a float64 from a string, returning ConfigurationError on failure.
func parseEnvFloat(value, field string) (float64, error) {
	f, err := strconv.ParseFloat(strings.TrimSpace(value), 64)
	if err != nil {
		return 0, NewConfigurationError(fmt.Sprintf("invalid float for %s: %q", field, value))
	}
	return f, nil
}

// parseEnvInt parses an int from a string, returning ConfigurationError on failure.
func parseEnvInt(value, field string) (int, error) {
	n, err := strconv.Atoi(strings.TrimSpace(value))
	if err != nil {
		return 0, NewConfigurationError(fmt.Sprintf("invalid integer for %s: %q", field, value))
	}
	return n, nil
}

// parseOTLPHeaders parses "key=value,key2=value2" into a map.
// Keys and values are URL-decoded. Malformed pairs are skipped.
func parseOTLPHeaders(raw string) map[string]string {
	headers := map[string]string{}
	if raw == "" {
		return headers
	}
	for _, pair := range strings.Split(raw, ",") {
		idx := strings.Index(pair, "=")
		if idx < 1 {
			// malformed or empty key — skip
			continue
		}
		rawKey := strings.TrimSpace(pair[:idx])
		rawVal := strings.TrimSpace(pair[idx+1:])
		// Use PathUnescape so that '+' is preserved as a literal character
		// (QueryUnescape decodes '+' as space, which breaks header names like
		// "x-api+json").
		key, err := url.PathUnescape(rawKey)
		if err != nil || key == "" {
			continue
		}
		val, err := url.PathUnescape(rawVal)
		if err != nil {
			continue
		}
		headers[key] = val
	}
	return headers
}

// parseModuleLevels parses "module=LEVEL,module2=LEVEL2" into a map.
// Malformed pairs and invalid levels are skipped.
func parseModuleLevels(raw string) (map[string]string, error) {
	result := map[string]string{}
	if strings.TrimSpace(raw) == "" {
		return result, nil
	}
	for _, pair := range strings.Split(raw, ",") {
		pair = strings.TrimSpace(pair)
		idx := strings.Index(pair, "=")
		if idx < 1 {
			// malformed or empty module name — skip
			continue
		}
		module := strings.TrimSpace(pair[:idx])
		levelStr := strings.TrimSpace(pair[idx+1:])
		normalized, err := normalizeLevel(levelStr)
		if err != nil {
			return nil, err
		}
		result[module] = normalized
	}
	return result, nil
}

// splitTrimmed splits a string by sep and trims whitespace from each element,
// omitting empty strings.
func splitTrimmed(s, sep string) []string {
	parts := strings.Split(s, sep)
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}

// firstNonEmpty returns the first non-empty string among the provided values.
func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}
