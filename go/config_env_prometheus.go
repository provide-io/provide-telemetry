// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"fmt"
	"strconv"
	"strings"
)

const (
	_metricsExporterOTLP       = "otlp"
	_metricsExporterPrometheus = "prometheus"
	_metricsExporterNone       = "none"
	_metricsExporterConsole    = "console"
	_metricsExporterLogging    = "logging"

	// _configWarningSeparator joins config warnings in setup_error and in the
	// strict-mode error, as the OTLP TLS problems are joined.
	_configWarningSeparator = "; "

	_prometheusListenFalse = "false"
	_prometheusListenTrue  = "true"
	_prometheusListenAuto  = "auto"

	_prometheusDefaultHost        = "127.0.0.1"
	_prometheusDefaultPort        = 9464
	_prometheusDefaultPath        = "/metrics"
	_prometheusDefaultTranslation = "UnderscoreEscapingWithSuffixes"
	_prometheusMaxPort            = 65535
)

// PrometheusTranslationStrategies lists the accepted values of
// PROVIDE_METRICS_PROMETHEUS_TRANSLATION, matching Prometheus 3's
// otlp.translation_strategy.
var PrometheusTranslationStrategies = []string{ //nolint:gochecknoglobals
	"UnderscoreEscapingWithSuffixes",
	"UnderscoreEscapingWithoutSuffixes",
	"NoUTF8EscapingWithSuffixes",
	"NoTranslation",
}

// applyPrometheusEnv reads OTEL_METRICS_EXPORTER, the Prometheus listener and
// translation settings, and PROVIDE_METRICS_HEALTH_OTLP into cfg.
func applyPrometheusEnv(cfg *TelemetryConfig, env func(string) string) error {
	exporters, warnings := parseMetricsExporters(env("OTEL_METRICS_EXPORTER"))
	if cfg.StrictConfig && len(warnings) > 0 {
		return NewConfigurationError("PROVIDE_TELEMETRY_STRICT_CONFIG: " + strings.Join(warnings, _configWarningSeparator))
	}
	cfg.Metrics.Exporters = exporters
	cfg.Metrics.ExporterWarnings = warnings
	if err := applyPrometheusListenerEnv(&cfg.Metrics.Prometheus, env); err != nil {
		return err
	}
	if err := applyPrometheusOutputEnv(&cfg.Metrics.Prometheus, env); err != nil {
		return err
	}
	healthOTLP, err := parseEnvBool(env("PROVIDE_METRICS_HEALTH_OTLP"), false, "PROVIDE_METRICS_HEALTH_OTLP")
	if err != nil {
		return err
	}
	cfg.Metrics.HealthOTLP = healthOTLP
	return nil
}

// parseMetricsExporters splits OTEL_METRICS_EXPORTER on commas, trimming and
// lowercasing entries and dropping empty ones, and returns the exporters with
// the warnings for what it ignored (nil when nothing was). Empty input means
// ["otlp"]; "none" alone means no exporters. Anything else this SDK cannot
// export to is dropped with a warning, as the OTel environment-variable spec
// asks of an unrecognised enum value; see
// prometheus_metrics.metrics_exporter_warnings in the spec.
func parseMetricsExporters(raw string) ([]string, []string) {
	exporters := []string{}
	var warnings []string
	seen := map[string]bool{}
	sawNone, sawAny := false, false
	for _, part := range strings.Split(raw, ",") {
		name := strings.ToLower(strings.TrimSpace(part))
		if name == "" {
			continue
		}
		sawAny = true
		// Early continues, not a tagless switch: gremlins reports a switch's
		// case expressions as not covered. See _levelName in logger_pretty.go.
		if name == _metricsExporterNone {
			sawNone = true
			continue
		}
		if name == _metricsExporterOTLP || name == _metricsExporterPrometheus {
			exporters = append(exporters, name)
			continue
		}
		if !seen[name] {
			seen[name] = true
			warnings = append(warnings, _ignoredExporterWarning(name))
		}
	}
	return _settleMetricsExporters(exporters, warnings, sawNone, sawAny)
}

// _settleMetricsExporters applies the rules that need the whole list: "none"
// alone means no exporters, "none" beside anything is ignored, and nothing
// usable left falls back to otlp.
func _settleMetricsExporters(exporters, warnings []string, sawNone, sawAny bool) ([]string, []string) {
	if sawNone && len(exporters) == 0 && warnings == nil {
		return exporters, nil
	}
	if sawNone {
		warnings = append(warnings, "OTEL_METRICS_EXPORTER: none cannot be combined with other exporters, ignored")
	}
	if len(exporters) == 0 {
		if sawAny {
			warnings = append(warnings, "OTEL_METRICS_EXPORTER: no supported exporter left, using otlp")
		}
		exporters = append(exporters, _metricsExporterOTLP)
	}
	return exporters, warnings
}

// _ignoredExporterWarning is the warning for an OTEL_METRICS_EXPORTER entry
// this SDK drops: an OTel exporter it does not support, or an unknown name.
func _ignoredExporterWarning(name string) string {
	if name == _metricsExporterConsole || name == _metricsExporterLogging {
		return "OTEL_METRICS_EXPORTER: " + name + " is not supported by provide-telemetry, ignored"
	}
	return "OTEL_METRICS_EXPORTER: unknown exporter " + name + ", ignored"
}

func applyPrometheusListenerEnv(p *PrometheusConfig, env func(string) string) error {
	if err := _applyPrometheusListen(p, env("PROVIDE_METRICS_PROMETHEUS_LISTEN")); err != nil {
		return err
	}
	if v := strings.TrimSpace(env("OTEL_EXPORTER_PROMETHEUS_HOST")); v != "" {
		p.Host = v
	}
	if err := _applyPrometheusPort(p, env("OTEL_EXPORTER_PROMETHEUS_PORT")); err != nil {
		return err
	}
	if err := _applyPrometheusPath(p, env("PROVIDE_METRICS_PROMETHEUS_PATH")); err != nil {
		return err
	}
	p.WebConfig = strings.TrimSpace(env("PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG"))
	return nil
}

func _applyPrometheusListen(p *PrometheusConfig, raw string) error {
	v := strings.ToLower(strings.TrimSpace(raw))
	switch v {
	case "":
		return nil
	case _prometheusListenFalse, _prometheusListenTrue, _prometheusListenAuto:
		p.Listen = v
		return nil
	default:
		return NewConfigurationError(fmt.Sprintf("PROVIDE_METRICS_PROMETHEUS_LISTEN: want false, true or auto, got %q", v))
	}
}

func _applyPrometheusPort(p *PrometheusConfig, raw string) error {
	v := strings.TrimSpace(raw)
	if v == "" {
		return nil
	}
	port, err := strconv.Atoi(v)
	if err != nil || port < 0 || port > _prometheusMaxPort {
		return NewConfigurationError(fmt.Sprintf("OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got %q", v))
	}
	p.Port = port
	return nil
}

func _applyPrometheusPath(p *PrometheusConfig, raw string) error {
	v := strings.TrimSpace(raw)
	if v == "" {
		return nil
	}
	if !strings.HasPrefix(v, "/") || strings.ContainsAny(v, "?#") {
		return NewConfigurationError(fmt.Sprintf("PROVIDE_METRICS_PROMETHEUS_PATH: want a path starting with / and no query or fragment, got %q", v))
	}
	p.Path = v
	return nil
}

func applyPrometheusOutputEnv(p *PrometheusConfig, env func(string) string) error {
	if v := strings.TrimSpace(env("PROVIDE_METRICS_PROMETHEUS_TRANSLATION")); v != "" {
		if !_isTranslationStrategy(v) {
			return NewConfigurationError(fmt.Sprintf("PROVIDE_METRICS_PROMETHEUS_TRANSLATION: unknown strategy %q", v))
		}
		p.Translation = v
	}
	scope, err := parseEnvBool(env("PROVIDE_METRICS_PROMETHEUS_SCOPE_LABELS"), false, "PROVIDE_METRICS_PROMETHEUS_SCOPE_LABELS")
	if err != nil {
		return err
	}
	p.ScopeLabels = scope
	targetInfo, err := parseEnvBool(env("PROVIDE_METRICS_PROMETHEUS_TARGET_INFO"), true, "PROVIDE_METRICS_PROMETHEUS_TARGET_INFO")
	if err != nil {
		return err
	}
	p.TargetInfo = targetInfo
	return nil
}

func _isTranslationStrategy(v string) bool {
	for _, s := range PrometheusTranslationStrategies {
		if s == v {
			return true
		}
	}
	return false
}
