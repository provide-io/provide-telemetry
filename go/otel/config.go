// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"strconv"
	"strings"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel/attribute"
	otlploghttp "go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp"
	otlpmetrichttp "go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	otlptracehttp "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	otelmetric "go.opentelemetry.io/otel/metric"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdkresource "go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

func _signalEndpointURL(endpoint, signalPath string) string {
	trimmed := strings.TrimSpace(endpoint)
	if trimmed == "" {
		return ""
	}
	if parsed, err := url.Parse(trimmed); err == nil && parsed.Scheme != "" && parsed.Host != "" {
		currentPath := strings.TrimRight(parsed.Path, "/")
		switch {
		case currentPath == "":
			parsed.Path = signalPath
		case !strings.HasSuffix(currentPath, signalPath):
			parsed.Path = currentPath + signalPath
		default:
			parsed.Path = currentPath
		}
		return parsed.String()
	}
	if strings.HasSuffix(strings.TrimRight(trimmed, "/"), signalPath) {
		return trimmed
	}
	return strings.TrimRight(trimmed, "/") + signalPath
}

func _validateURLPort(portStr string, parsed *url.URL, signalURL string) error {
	if portStr != "" {
		port, err := strconv.Atoi(portStr)
		if err != nil || port < 1 || port > 65535 {
			return fmt.Errorf("invalid OTLP endpoint port in %q", signalURL)
		}
	}
	hostAfterBracket := parsed.Host
	if idx := strings.LastIndex(parsed.Host, "]"); idx >= 0 {
		hostAfterBracket = parsed.Host[idx+1:]
	}
	if portStr == "" && strings.Contains(hostAfterBracket, ":") {
		return fmt.Errorf("invalid OTLP endpoint port in %q", signalURL)
	}
	return nil
}

func _validatedSignalEndpointURL(endpoint, signalPath string) (string, error) {
	if strings.TrimSpace(endpoint) == "" {
		return "", fmt.Errorf("invalid OTLP endpoint URL %q", endpoint)
	}
	signalURL := _signalEndpointURL(endpoint, signalPath)
	parsed, err := url.Parse(signalURL)
	if err != nil {
		return "", err
	}
	if parsed.Scheme == "" || parsed.Host == "" {
		return "", fmt.Errorf("invalid OTLP endpoint URL %q", signalURL)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return "", fmt.Errorf("invalid OTLP endpoint scheme %q in %q", parsed.Scheme, signalURL)
	}
	if err := _validateURLPort(parsed.Port(), parsed, signalURL); err != nil {
		return "", err
	}
	return signalURL, nil
}

// _resourceSchemaURL is the OTel schema URL stamped on the floor and explicit
// resource layers. The env layer carries the empty schema URL, so no layer ever
// triggers a schema-conflict in resource.Merge.
const _resourceSchemaURL = "https://opentelemetry.io/schemas/1.26.0"

// _explicitResourceAttrs returns the identity attributes the caller explicitly
// set — those whose config value differs from the framework default. They form
// the top precedence layer (winning over env); keys left at the default are
// omitted so an OTEL_* env value can still fill them.
func _explicitResourceAttrs(cfg *telemetry.TelemetryConfig) []attribute.KeyValue {
	dflt := telemetry.DefaultTelemetryConfig()
	attrs := make([]attribute.KeyValue, 0, 3)
	if cfg.ServiceName != dflt.ServiceName {
		attrs = append(attrs, attribute.String("service.name", cfg.ServiceName))
	}
	if cfg.Environment != dflt.Environment {
		attrs = append(attrs, attribute.String("deployment.environment", cfg.Environment))
	}
	if cfg.Version != dflt.Version {
		attrs = append(attrs, attribute.String("service.version", cfg.Version))
	}
	return attrs
}

// _buildResource layers the resource as: framework floor < OTEL_* env < explicit
// config. This honors OTEL_RESOURCE_ATTRIBUTES / OTEL_SERVICE_NAME (callers can
// attach host.name, service.instance.id, k8s.*, etc. without a custom provider)
// while an explicitly named service is never hijacked by ambient env, and an
// unset service name is still filled by OTEL_SERVICE_NAME.
//
// A malformed OTEL_RESOURCE_ATTRIBUTES yields a partial resource plus an error;
// the error is intentionally ignored so the well-formed entries are still
// applied (best-effort). resource.New never returns a nil resource, and
// _mergeResources preserves the earlier layer on any merge failure.
func _buildResource(cfg *telemetry.TelemetryConfig) *sdkresource.Resource {
	dflt := telemetry.DefaultTelemetryConfig()
	floor := sdkresource.NewWithAttributes(
		_resourceSchemaURL,
		attribute.String("service.name", dflt.ServiceName),
		attribute.String("deployment.environment", dflt.Environment),
		attribute.String("service.version", dflt.Version),
	)
	envRes, _ := sdkresource.New(context.Background(), sdkresource.WithFromEnv())
	explicit := sdkresource.NewWithAttributes(_resourceSchemaURL, _explicitResourceAttrs(cfg)...)
	// Each _mergeResources call lets the second (argument) resource win, so the
	// order floor → env → explicit yields ascending precedence.
	return _mergeResources(_mergeResources(floor, envRes), explicit)
}

// _mergeResources merges the env-detected resource onto base, with env winning
// on key conflict. If the two carry conflicting non-empty schema URLs (the only
// case resource.Merge reports an error for), base is returned unchanged rather
// than a schemaless blend, keeping the pinned schema URL and service identity.
func _mergeResources(base, envRes *sdkresource.Resource) *sdkresource.Resource {
	merged, err := sdkresource.Merge(base, envRes)
	if err != nil {
		return base
	}
	return merged
}

func _buildDefaultTracerProvider(cfg *telemetry.TelemetryConfig) (*sdktrace.TracerProvider, error) {
	traceURL, err := _validatedSignalEndpointURL(cfg.Tracing.OTLPEndpoint, "/v1/traces")
	if err != nil {
		return nil, err
	}
	exporter, err := _newOTLPTraceExporter(context.Background(),
		otlptracehttp.WithEndpointURL(traceURL),
		otlptracehttp.WithHeaders(cfg.Tracing.OTLPHeaders),
	)
	if err != nil {
		return nil, err
	}
	return sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(_wrapSpanExporter(exporter)),
		sdktrace.WithResource(_buildResource(cfg)),
	), nil
}

func _buildDefaultMeterProvider(cfg *telemetry.TelemetryConfig) (*sdkmetric.MeterProvider, error) {
	metricsURL, err := _validatedSignalEndpointURL(cfg.Metrics.OTLPEndpoint, "/v1/metrics")
	if err != nil {
		return nil, err
	}
	exporter, err := _newOTLPMetricsExporter(context.Background(),
		otlpmetrichttp.WithEndpointURL(metricsURL),
		otlpmetrichttp.WithHeaders(cfg.Metrics.OTLPHeaders),
	)
	if err != nil {
		return nil, err
	}
	return sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(_wrapMetricsExporter(exporter))),
		sdkmetric.WithResource(_buildResource(cfg)),
	), nil
}

func _buildDefaultLoggerProvider(cfg *telemetry.TelemetryConfig) (*sdklog.LoggerProvider, error) {
	logsURL, err := _validatedSignalEndpointURL(cfg.Logging.OTLPEndpoint, "/v1/logs")
	if err != nil {
		return nil, err
	}
	exporter, err := _newOTLPLogExporter(context.Background(),
		otlploghttp.WithEndpointURL(logsURL),
		otlploghttp.WithHeaders(cfg.Logging.OTLPHeaders),
	)
	if err != nil {
		return nil, err
	}
	return sdklog.NewLoggerProvider(
		sdklog.WithProcessor(sdklog.NewBatchProcessor(_wrapLogExporter(exporter))),
		sdklog.WithResource(_buildResource(cfg)),
	), nil
}

func _counterOptions(opts telemetry.InstrumentOptions) []otelmetric.Int64CounterOption {
	options := make([]otelmetric.Int64CounterOption, 0, 2)
	if opts.Description != "" {
		options = append(options, otelmetric.WithDescription(opts.Description))
	}
	if opts.Unit != "" {
		options = append(options, otelmetric.WithUnit(opts.Unit))
	}
	return options
}

func _gaugeOptions(opts telemetry.InstrumentOptions) []otelmetric.Float64GaugeOption {
	options := make([]otelmetric.Float64GaugeOption, 0, 2)
	if opts.Description != "" {
		options = append(options, otelmetric.WithDescription(opts.Description))
	}
	if opts.Unit != "" {
		options = append(options, otelmetric.WithUnit(opts.Unit))
	}
	return options
}

func _histogramOptions(opts telemetry.InstrumentOptions) []otelmetric.Float64HistogramOption {
	options := make([]otelmetric.Float64HistogramOption, 0, 2)
	if opts.Description != "" {
		options = append(options, otelmetric.WithDescription(opts.Description))
	}
	if opts.Unit != "" {
		options = append(options, otelmetric.WithUnit(opts.Unit))
	}
	return options
}

func _addOptions(attrs []slog.Attr) []otelmetric.AddOption {
	if len(attrs) == 0 {
		return nil
	}
	keyValues := make([]attribute.KeyValue, 0, len(attrs))
	for _, attr := range attrs {
		keyValues = append(keyValues, _attributeFromSlogAttr(attr))
	}
	return []otelmetric.AddOption{otelmetric.WithAttributes(keyValues...)}
}

func _recordOptions(attrs []slog.Attr) []otelmetric.RecordOption {
	if len(attrs) == 0 {
		return nil
	}
	keyValues := make([]attribute.KeyValue, 0, len(attrs))
	for _, attr := range attrs {
		keyValues = append(keyValues, _attributeFromSlogAttr(attr))
	}
	return []otelmetric.RecordOption{otelmetric.WithAttributes(keyValues...)}
}

func _attributeFromSlogAttr(attr slog.Attr) attribute.KeyValue {
	value := attr.Value.Resolve()
	switch value.Kind() {
	case slog.KindBool:
		return attribute.Bool(attr.Key, value.Bool())
	case slog.KindDuration:
		return attribute.String(attr.Key, value.Duration().String())
	case slog.KindFloat64:
		return attribute.Float64(attr.Key, value.Float64())
	case slog.KindInt64:
		return attribute.Int64(attr.Key, value.Int64())
	case slog.KindString:
		return attribute.String(attr.Key, value.String())
	case slog.KindTime:
		return attribute.String(attr.Key, value.Time().Format("2006-01-02T15:04:05.999999999Z07:00"))
	case slog.KindUint64:
		u := value.Uint64()
		if u > uint64(^uint64(0)>>1) {
			return attribute.String(attr.Key, fmt.Sprint(u))
		}
		return attribute.Int64(attr.Key, int64(u))
	default:
		return attribute.String(attr.Key, fmt.Sprint(value.Any()))
	}
}

func _defaultOTLPTraceExporterFactory(ctx context.Context, opts ...otlptracehttp.Option) (sdktrace.SpanExporter, error) {
	return otlptracehttp.New(ctx, opts...)
}

func _defaultOTLPMetricsExporterFactory(ctx context.Context, opts ...otlpmetrichttp.Option) (sdkmetric.Exporter, error) {
	return otlpmetrichttp.New(ctx, opts...)
}

func _defaultOTLPLogExporterFactory(ctx context.Context, opts ...otlploghttp.Option) (sdklog.Exporter, error) {
	return otlploghttp.New(ctx, opts...)
}

var _newOTLPTraceExporter = _defaultOTLPTraceExporterFactory     //nolint:gochecknoglobals
var _newOTLPMetricsExporter = _defaultOTLPMetricsExporterFactory //nolint:gochecknoglobals
var _newOTLPLogExporter = _defaultOTLPLogExporterFactory         //nolint:gochecknoglobals

var errOTelShutdown = errors.New("otel shutdown error")
