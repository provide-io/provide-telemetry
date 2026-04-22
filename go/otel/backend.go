// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"log/slog"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/contrib/bridges/otelslog"
	"go.opentelemetry.io/otel"
	logglobal "go.opentelemetry.io/otel/log/global"
	otellognoop "go.opentelemetry.io/otel/log/noop"
	otelmetricnoop "go.opentelemetry.io/otel/metric/noop"
	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	oteltrace "go.opentelemetry.io/otel/trace"
	otelnooptrace "go.opentelemetry.io/otel/trace/noop"
)

var (
	_otelTracerProvider *sdktrace.TracerProvider //nolint:gochecknoglobals
	_otelMeterProvider  *sdkmetric.MeterProvider //nolint:gochecknoglobals
	_otelLoggerProvider *sdklog.LoggerProvider   //nolint:gochecknoglobals
)

func init() {
	telemetry.RegisterBackend("otel", &_backend{})
}

type _backend struct{}

func (b *_backend) Setup(cfg *telemetry.TelemetryConfig, state telemetry.BackendSetupState) error {
	_setupTracerProvider(state, cfg)
	_setupMeterProvider(state, cfg)
	_setupLoggerProvider(state, cfg)
	return nil
}

func (b *_backend) Shutdown(ctx context.Context) error {
	var first error

	if _otelTracerProvider != nil {
		if err := _otelTracerProvider.Shutdown(ctx); err != nil {
			first = err
		}
		_otelTracerProvider = nil
	}

	if _otelMeterProvider != nil {
		if err := _otelMeterProvider.Shutdown(ctx); err != nil && first == nil {
			first = err
		}
		_otelMeterProvider = nil
	}

	if _otelLoggerProvider != nil {
		if err := _otelLoggerProvider.Shutdown(ctx); err != nil && first == nil {
			first = err
		}
		_otelLoggerProvider = nil
	}
	otel.SetTracerProvider(otelnooptrace.NewTracerProvider())
	otel.SetMeterProvider(otelmetricnoop.NewMeterProvider())
	logglobal.SetLoggerProvider(otellognoop.NewLoggerProvider())

	return first
}

func _shutdownOTelProviders(ctx context.Context) error {
	return (&_backend{}).Shutdown(ctx)
}

func (b *_backend) ResetForTests() {
	_otelTracerProvider = nil
	_otelMeterProvider = nil
	_otelLoggerProvider = nil
	_newOTLPTraceExporter = _defaultOTLPTraceExporterFactory
	_newOTLPMetricsExporter = _defaultOTLPMetricsExporterFactory
	_newOTLPLogExporter = _defaultOTLPLogExporterFactory
	otel.SetTracerProvider(otelnooptrace.NewTracerProvider())
	otel.SetMeterProvider(otelmetricnoop.NewMeterProvider())
	logglobal.SetLoggerProvider(otellognoop.NewLoggerProvider())
}

func _resetOTelProviders() {
	(&_backend{}).ResetForTests()
}

func (b *_backend) Providers() telemetry.SignalStatus {
	return telemetry.SignalStatus{
		Logs:    _otelLoggerProvider != nil,
		Traces:  _otelTracerProvider != nil,
		Metrics: _otelMeterProvider != nil,
	}
}

func (b *_backend) Tracer(name string) telemetry.Tracer {
	if _otelTracerProvider == nil {
		return nil
	}
	return _otelTracerAdapter{inner: _otelTracerProvider.Tracer(name)}
}

func (b *_backend) TraceContext(ctx context.Context) (traceID, spanID string, ok bool) {
	if span := oteltrace.SpanFromContext(ctx); span.SpanContext().IsValid() {
		sc := span.SpanContext()
		return sc.TraceID().String(), sc.SpanID().String(), true
	}
	return "", "", false
}

func (b *_backend) LoggerHandler(name string) slog.Handler {
	if _otelLoggerProvider == nil {
		return nil
	}
	return otelslog.NewHandler(name, otelslog.WithLoggerProvider(_otelLoggerProvider))
}

func (b *_backend) Meter(name string) any {
	if _otelMeterProvider == nil {
		return nil
	}
	return _otelMeterProvider.Meter(name)
}

func (b *_backend) NewCounter(name string, opts telemetry.InstrumentOptions) (telemetry.Counter, bool) {
	if _otelMeterProvider == nil {
		return nil, false
	}
	meter := _otelMeterProvider.Meter("provide.telemetry")
	counter, err := meter.Int64Counter(name, _counterOptions(opts)...)
	if err != nil {
		return nil, false
	}
	return &_otelCounter{inner: counter}, true
}

func (b *_backend) NewGauge(name string, opts telemetry.InstrumentOptions) (telemetry.Gauge, bool) {
	if _otelMeterProvider == nil {
		return nil, false
	}
	meter := _otelMeterProvider.Meter("provide.telemetry")
	gauge, err := meter.Float64Gauge(name, _gaugeOptions(opts)...)
	if err != nil {
		return nil, false
	}
	return &_otelGauge{inner: gauge}, true
}

func (b *_backend) NewHistogram(name string, opts telemetry.InstrumentOptions) (telemetry.Histogram, bool) {
	if _otelMeterProvider == nil {
		return nil, false
	}
	meter := _otelMeterProvider.Meter("provide.telemetry")
	histogram, err := meter.Float64Histogram(name, _histogramOptions(opts)...)
	if err != nil {
		return nil, false
	}
	return &_otelHistogram{inner: histogram}, true
}
