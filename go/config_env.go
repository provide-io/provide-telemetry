// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

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
	var err error
	cfg.StrictSchema, err = parseEnvBool(env("PROVIDE_TELEMETRY_STRICT_SCHEMA"), false, "PROVIDE_TELEMETRY_STRICT_SCHEMA")
	if err != nil {
		return err
	}
	cfg.EventSchema.StrictEventName, err = parseEnvBool(
		env("PROVIDE_TELEMETRY_STRICT_EVENT_NAME"),
		false,
		"PROVIDE_TELEMETRY_STRICT_EVENT_NAME",
	)
	if err != nil {
		return err
	}
	if v := env("PROVIDE_TELEMETRY_REQUIRED_KEYS"); v != "" {
		cfg.EventSchema.RequiredKeys = splitTrimmed(v, ",")
	}
	return nil
}

// applyLoggingEnv reads logging-related env vars into cfg.
func applyLoggingEnv(cfg *TelemetryConfig, env func(string) string) error {
	if err := applyLoggingLevelFormat(cfg, env); err != nil {
		return err
	}
	if err := applyLoggingBoolFlags(cfg, env); err != nil {
		return err
	}
	return applyLoggingPrettyAndModules(cfg, env)
}

// applyLoggingLevelFormat handles PROVIDE_LOG_LEVEL and PROVIDE_LOG_FORMAT.
func applyLoggingLevelFormat(cfg *TelemetryConfig, env func(string) string) error {
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
	return nil
}

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
	enabled, err := parseEnvBool(env("PROVIDE_TRACE_ENABLED"), true, "PROVIDE_TRACE_ENABLED")
	if err != nil {
		return err
	}
	cfg.Tracing.Enabled = enabled
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
func applyMetricsEnv(cfg *TelemetryConfig, env func(string) string) error {
	enabled, err := parseEnvBool(env("PROVIDE_METRICS_ENABLED"), true, "PROVIDE_METRICS_ENABLED")
	if err != nil {
		return err
	}
	cfg.Metrics.Enabled = enabled
	return nil
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

// applySLOEnv reads SLO env vars into cfg.
func applySLOEnv(cfg *TelemetryConfig, env func(string) string) error {
	var err error
	cfg.SLO.EnableREDMetrics, err = parseEnvBool(
		env("PROVIDE_SLO_ENABLE_RED_METRICS"),
		false,
		"PROVIDE_SLO_ENABLE_RED_METRICS",
	)
	if err != nil {
		return err
	}
	cfg.SLO.EnableUSEMetrics, err = parseEnvBool(
		env("PROVIDE_SLO_ENABLE_USE_METRICS"),
		false,
		"PROVIDE_SLO_ENABLE_USE_METRICS",
	)
	if err != nil {
		return err
	}
	cfg.SLO.IncludeErrorTaxonomy, err = parseEnvBool(
		env("PROVIDE_SLO_INCLUDE_ERROR_TAXONOMY"),
		true,
		"PROVIDE_SLO_INCLUDE_ERROR_TAXONOMY",
	)
	return err
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
