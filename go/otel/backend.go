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
	// Last, so our own providers always take precedence over a host's.
	_adoptForeignProviders(cfg)
	return nil
}

// ForceFlush drains every provider we installed, leaving them installed. Returns
// the first error encountered, after attempting all three signals — one stalled
// exporter must not deny the others their drain. A provider adopted from the
// OTel globals is not ours to drain and is skipped.
func (b *_backend) ForceFlush(ctx context.Context) error {
	var first error

	if _otelTracerProvider != nil {
		if err := _otelTracerProvider.ForceFlush(ctx); err != nil {
			first = err
		}
	}

	if _otelMeterProvider != nil {
		if err := _otelMeterProvider.ForceFlush(ctx); err != nil && first == nil {
			first = err
		}
	}

	if _otelLoggerProvider != nil {
		if err := _otelLoggerProvider.ForceFlush(ctx); err != nil && first == nil {
			first = err
		}
	}

	return first
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
	// Adopted providers belong to the host: drop the reference, do not shut down.
	_releaseAdoptedProviders()
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
	_releaseAdoptedProviders()
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
		Traces:  _effectiveTracerProvider() != nil,
		Metrics: _effectiveMeterProvider() != nil,
	}
}

func (b *_backend) Tracer(name string) telemetry.Tracer {
	provider := _effectiveTracerProvider()
	if provider == nil {
		return nil
	}
	return _otelTracerAdapter{inner: provider.Tracer(name)}
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
	provider := _effectiveMeterProvider()
	if provider == nil {
		return nil
	}
	return provider.Meter(name)
}

func (b *_backend) NewCounter(name string, opts telemetry.InstrumentOptions) (telemetry.Counter, bool) {
	provider := _effectiveMeterProvider()
	if provider == nil {
		return nil, false
	}
	meter := provider.Meter("provide.telemetry")
	counter, err := meter.Int64Counter(name, _counterOptions(opts)...)
	if err != nil {
		return nil, false
	}
	return &_otelCounter{inner: counter}, true
}

func (b *_backend) NewGauge(name string, opts telemetry.InstrumentOptions) (telemetry.Gauge, bool) {
	provider := _effectiveMeterProvider()
	if provider == nil {
		return nil, false
	}
	meter := provider.Meter("provide.telemetry")
	gauge, err := meter.Float64Gauge(name, _gaugeOptions(opts)...)
	if err != nil {
		return nil, false
	}
	return &_otelGauge{inner: gauge}, true
}

func (b *_backend) NewHistogram(name string, opts telemetry.InstrumentOptions) (telemetry.Histogram, bool) {
	provider := _effectiveMeterProvider()
	if provider == nil {
		return nil, false
	}
	meter := provider.Meter("provide.telemetry")
	histogram, err := meter.Float64Histogram(name, _histogramOptions(opts)...)
	if err != nil {
		return nil, false
	}
	return &_otelHistogram{inner: histogram}, true
}
