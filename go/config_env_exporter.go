// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

// applyExporterEnv reads exporter policy env vars and OTLP endpoints/headers into cfg.
func applyExporterEnv(cfg *TelemetryConfig, env func(string) string) error {
	// OTLP endpoints/headers — signal-specific fallback to generic
	genericEndpoint := env("OTEL_EXPORTER_OTLP_ENDPOINT")
	genericHeaders := env("OTEL_EXPORTER_OTLP_HEADERS")
	var err error

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
	cfg.Exporter.LogsFailOpen, err = parseEnvBool(env("PROVIDE_EXPORTER_LOGS_FAIL_OPEN"), true, "PROVIDE_EXPORTER_LOGS_FAIL_OPEN")
	if err != nil {
		return err
	}
	cfg.Exporter.TracesFailOpen, err = parseEnvBool(
		env("PROVIDE_EXPORTER_TRACES_FAIL_OPEN"),
		true,
		"PROVIDE_EXPORTER_TRACES_FAIL_OPEN",
	)
	if err != nil {
		return err
	}
	cfg.Exporter.MetricsFailOpen, err = parseEnvBool(
		env("PROVIDE_EXPORTER_METRICS_FAIL_OPEN"),
		true,
		"PROVIDE_EXPORTER_METRICS_FAIL_OPEN",
	)
	if err != nil {
		return err
	}

	// Allow-blocking
	cfg.Exporter.LogsAllowBlockingInEventLoop, err = parseEnvBool(
		env("PROVIDE_EXPORTER_LOGS_ALLOW_BLOCKING_EVENT_LOOP"),
		false,
		"PROVIDE_EXPORTER_LOGS_ALLOW_BLOCKING_EVENT_LOOP",
	)
	if err != nil {
		return err
	}
	cfg.Exporter.TracesAllowBlockingInEventLoop, err = parseEnvBool(
		env("PROVIDE_EXPORTER_TRACES_ALLOW_BLOCKING_EVENT_LOOP"),
		false,
		"PROVIDE_EXPORTER_TRACES_ALLOW_BLOCKING_EVENT_LOOP",
	)
	if err != nil {
		return err
	}
	cfg.Exporter.MetricsAllowBlockingInEventLoop, err = parseEnvBool(
		env("PROVIDE_EXPORTER_METRICS_ALLOW_BLOCKING_EVENT_LOOP"),
		false,
		"PROVIDE_EXPORTER_METRICS_ALLOW_BLOCKING_EVENT_LOOP",
	)
	if err != nil {
		return err
	}

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
