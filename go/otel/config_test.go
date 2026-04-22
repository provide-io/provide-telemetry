// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"errors"
	"log/slog"
	"math"
	"testing"
	"time"

	telemetry "github.com/provide-io/provide-telemetry/go"
	otlploghttp "go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp"
	otlpmetrichttp "go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	otlptracehttp "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

type _erroringLogExporter struct {
	shutdownErr error
}

func (e *_erroringLogExporter) Export(context.Context, []sdklog.Record) error { return nil }
func (e *_erroringLogExporter) Shutdown(context.Context) error                { return e.shutdownErr }
func (e *_erroringLogExporter) ForceFlush(context.Context) error              { return nil }

func TestBuildDefaultProviders_ExporterInitErrors(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg := telemetry.DefaultTelemetryConfig()
	cfg.Tracing.OTLPEndpoint = "http://collector:4318"
	cfg.Metrics.OTLPEndpoint = "http://collector:4318"
	cfg.Logging.OTLPEndpoint = "http://collector:4318"

	traceErr := errors.New("trace exporter init failed")
	_newOTLPTraceExporter = func(context.Context, ...otlptracehttp.Option) (sdktrace.SpanExporter, error) {
		return nil, traceErr
	}
	if tp, err := _buildDefaultTracerProvider(cfg); !errors.Is(err, traceErr) || tp != nil {
		t.Fatalf("expected tracer exporter error %v, got tp=%v err=%v", traceErr, tp, err)
	}

	metricErr := errors.New("metric exporter init failed")
	_newOTLPTraceExporter = _defaultOTLPTraceExporterFactory
	_newOTLPMetricsExporter = func(context.Context, ...otlpmetrichttp.Option) (sdkmetric.Exporter, error) {
		return nil, metricErr
	}
	if mp, err := _buildDefaultMeterProvider(cfg); !errors.Is(err, metricErr) || mp != nil {
		t.Fatalf("expected meter exporter error %v, got mp=%v err=%v", metricErr, mp, err)
	}

	logErr := errors.New("log exporter init failed")
	_newOTLPMetricsExporter = _defaultOTLPMetricsExporterFactory
	_newOTLPLogExporter = func(context.Context, ...otlploghttp.Option) (sdklog.Exporter, error) {
		return nil, logErr
	}
	if lp, err := _buildDefaultLoggerProvider(cfg); !errors.Is(err, logErr) || lp != nil {
		t.Fatalf("expected logger exporter error %v, got lp=%v err=%v", logErr, lp, err)
	}
}

func TestOTel_ShutdownOTelProviders_OnlyLoggerProviderError(t *testing.T) {
	_resetOTelProviders()
	t.Cleanup(func() { _resetOTelProviders() })

	wantErr := errors.New("logger shutdown failed")
	lp := sdklog.NewLoggerProvider(
		sdklog.WithProcessor(sdklog.NewSimpleProcessor(&_erroringLogExporter{shutdownErr: wantErr})),
	)
	_otelLoggerProvider = lp

	err := _shutdownOTelProviders(context.Background())
	if !errors.Is(err, wantErr) {
		t.Fatalf("expected logger shutdown error %v, got %v", wantErr, err)
	}
	if _otelLoggerProvider != nil {
		t.Fatal("expected logger provider pointer to be cleared after shutdown error")
	}
}

func TestValidatedSignalEndpointURL_PortValidation(t *testing.T) {
	tests := []struct {
		name    string
		input   string
		wantErr bool
	}{
		{"valid port", "http://host:4318", false},
		{"no port", "http://host", false},
		{"non-numeric port", "http://host:bad", true},
		{"empty port", "http://host:", true},
		{"port zero", "http://host:0", true},
		{"port out of range", "http://host:99999", true},
		{"negative port", "http://host:-1", true},
		{"ipv6 with valid port", "http://[::1]:4318", false},
		{"ipv6 no port", "http://[::1]", false},
		{"ipv6 empty port", "http://[::1]:", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := _validatedSignalEndpointURL(tt.input, "/v1/traces")
			if tt.wantErr && err == nil {
				t.Fatalf("expected error for %q", tt.input)
			}
			if !tt.wantErr && err != nil {
				t.Fatalf("unexpected error for %q: %v", tt.input, err)
			}
		})
	}
}

func TestSignalEndpointURL_Variants(t *testing.T) {
	tests := []struct {
		name       string
		endpoint   string
		signalPath string
		want       string
	}{
		{name: "blank endpoint", endpoint: "   ", signalPath: "/v1/logs", want: ""},
		{name: "root endpoint appends path", endpoint: "http://collector:4318", signalPath: "/v1/traces", want: "http://collector:4318/v1/traces"},
		{name: "existing path appends signal path", endpoint: "http://collector:4318/base", signalPath: "/v1/metrics", want: "http://collector:4318/base/v1/metrics"},
		{name: "existing suffix preserved", endpoint: "http://collector:4318/v1/logs", signalPath: "/v1/logs", want: "http://collector:4318/v1/logs"},
		{name: "unparsed string suffix preserved", endpoint: "collector:4318/v1/logs", signalPath: "/v1/logs", want: "collector:4318/v1/logs"},
		{name: "unparsed string appends path", endpoint: "collector:4318", signalPath: "/v1/logs", want: "collector:4318/v1/logs"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := _signalEndpointURL(tt.endpoint, tt.signalPath); got != tt.want {
				t.Fatalf("expected %q, got %q", tt.want, got)
			}
		})
	}
}

func TestAttributeFromSlogAttr_ConvertsSupportedKinds(t *testing.T) {
	now := time.Date(2026, time.April, 17, 12, 0, 0, 0, time.UTC)

	tests := []struct {
		name string
		attr slog.Attr
		want any
	}{
		{name: "bool", attr: slog.Bool("ok", true), want: true},
		{name: "duration", attr: slog.Duration("latency", 3*time.Second), want: "3s"},
		{name: "float", attr: slog.Float64("ratio", 1.5), want: 1.5},
		{name: "int64", attr: slog.Int64("count", 7), want: int64(7)},
		{name: "string", attr: slog.String("service", "api"), want: "api"},
		{name: "time", attr: slog.Time("at", now), want: now.Format("2006-01-02T15:04:05.999999999Z07:00")},
		{name: "uint64", attr: slog.Uint64("bytes", 9), want: int64(9)},
		{name: "uint64 overflow", attr: slog.Uint64("bytes", uint64(math.MaxInt64)+1), want: "9223372036854775808"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			kv := _attributeFromSlogAttr(tt.attr)
			if got := kv.Value.AsInterface(); got != tt.want {
				t.Fatalf("expected %v, got %v", tt.want, got)
			}
		})
	}
}
