// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"testing"

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

func (e *_erroringLogExporter) Shutdown(context.Context) error { return e.shutdownErr }

func (e *_erroringLogExporter) ForceFlush(context.Context) error { return nil }

func TestBuildDefaultProviders_ExporterInitErrors(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg := DefaultTelemetryConfig()
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
