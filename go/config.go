// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"fmt"
	"net/url"
	"os"
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
	EventSchema  *SchemaConfig
	PIIMaxDepth  *int
	StrictSchema *bool
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

// maskHeaderValue masks a header value: shows first 4 chars + **** if >= 8 chars, else ****.
func maskHeaderValue(v string) string {
	if len(v) < 8 {
		return "****"
	}
	return v[:4] + "****"
}

// maskHeaders returns a copy of h with all values masked.
func maskHeaders(h map[string]string) map[string]string {
	masked := make(map[string]string, len(h))
	for k, v := range h {
		masked[k] = maskHeaderValue(v)
	}
	return masked
}

// maskEndpointURL masks the password component of a URL's userinfo, if present.
// We rebuild the string manually to avoid url.URL.String() percent-encoding the
// asterisks in "****".
func maskEndpointURL(raw string) string {
	u, err := url.Parse(raw)
	if err != nil || u.User == nil {
		return raw
	}
	pass, hasPass := u.User.Password()
	if !hasPass || pass == "" {
		return raw
	}
	// Reconstruct: scheme://user:****@host[:port]/path?query
	host := u.Hostname()
	if port := u.Port(); port != "" {
		host = host + ":" + port
	}
	masked := u.Scheme + "://" + u.User.Username() + ":****@" + host + u.RequestURI()
	return masked
}

// RedactedString returns a string representation of the config with secrets masked.
func (c *TelemetryConfig) RedactedString() string {
	return fmt.Sprintf(
		"TelemetryConfig{ServiceName:%q, Environment:%q, Logging.OTLPHeaders:%v, Tracing.OTLPHeaders:%v, Tracing.OTLPEndpoint:%q, Metrics.OTLPHeaders:%v, Metrics.OTLPEndpoint:%q}",
		c.ServiceName, c.Environment,
		maskHeaders(c.Logging.OTLPHeaders),
		maskHeaders(c.Tracing.OTLPHeaders),
		maskEndpointURL(c.Tracing.OTLPEndpoint),
		maskHeaders(c.Metrics.OTLPHeaders),
		maskEndpointURL(c.Metrics.OTLPEndpoint),
	)
}

// String implements fmt.Stringer and always returns a redacted representation.
func (c *TelemetryConfig) String() string { return c.RedactedString() }

// GoString implements fmt.GoStringer and always returns a redacted representation.
func (c *TelemetryConfig) GoString() string { return c.RedactedString() }

// RedactConfig returns the config fields as a map with OTLP headers and
// endpoint passwords masked. Safe to log or store — no secrets are exposed.
func RedactConfig(c *TelemetryConfig) map[string]interface{} {
	return map[string]interface{}{
		"service_name": c.ServiceName,
		"environment":  c.Environment,
		"version":      c.Version,
		"logging": map[string]interface{}{
			"otlp_endpoint": maskEndpointURL(c.Logging.OTLPEndpoint),
			"otlp_headers":  maskHeaders(c.Logging.OTLPHeaders),
		},
		"tracing": map[string]interface{}{
			"otlp_endpoint": maskEndpointURL(c.Tracing.OTLPEndpoint),
			"otlp_headers":  maskHeaders(c.Tracing.OTLPHeaders),
		},
		"metrics": map[string]interface{}{
			"otlp_endpoint": maskEndpointURL(c.Metrics.OTLPEndpoint),
			"otlp_headers":  maskHeaders(c.Metrics.OTLPHeaders),
		},
	}
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
		applyMetricsEnv,
		applySamplingEnv,
		applyBackpressureEnv,
		applySLOEnv,
		applySecurityEnv,
	}
	for _, fn := range helpers {
		if err := fn(cfg, env); err != nil {
			return nil, err
		}
	}
	return cfg, nil
}
