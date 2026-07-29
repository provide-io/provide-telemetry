// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"context"
	"errors"
	"log/slog"
	"sync"

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

	// Whether *we* registered each global. Shutdown resets only what we set:
	// clobbering a host application's registration would silently stop its own
	// instrumentation, which is not ours to switch off.
	_weSetTracerGlobal bool //nolint:gochecknoglobals
	_weSetMeterGlobal  bool //nolint:gochecknoglobals
	_weSetLoggerGlobal bool //nolint:gochecknoglobals
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

// ForceFlush drains every provider we installed, leaving them installed. Every
// signal is attempted — one stalled exporter must not deny the others their
// drain. A lone failure is returned as-is so FlushTelemetry's documented
// context.DeadlineExceeded survives an `==` comparison; when more than one
// signal fails the errors are joined and only errors.Is can match. A provider
// adopted from the OTel globals is not ours to drain and is skipped.
func (b *_backend) ForceFlush(ctx context.Context) error {
	// Concurrently, so each signal gets the caller's full budget. Run in
	// sequence they share one deadline, and a stalled traces exporter consumes
	// it entirely: metrics and logs then return DeadlineExceeded without
	// exporting anything, which is the opposite of what this promises. Python,
	// Rust and TypeScript all give each signal its own budget.
	flushes := []func(context.Context) error{}
	if tp := _loadTracerProvider(); tp != nil {
		flushes = append(flushes, tp.ForceFlush)
	}
	if mp := _loadMeterProvider(); mp != nil {
		flushes = append(flushes, mp.ForceFlush)
	}
	if lp := _loadLoggerProvider(); lp != nil {
		flushes = append(flushes, lp.ForceFlush)
	}

	errs := make([]error, len(flushes))
	var wg sync.WaitGroup
	for i, flush := range flushes {
		wg.Add(1)
		go func(i int, flush func(context.Context) error) {
			defer wg.Done()
			errs[i] = flush(ctx)
		}(i, flush)
	}
	wg.Wait()

	return _joinFlushErrors(errs)
}

// _joinFlushErrors joins the per-signal drain errors, but hands a lone error
// back untouched.
//
// errors.Join wraps even a single error in a *joinError. FlushTelemetry's godoc
// promises that an expired deadline reaches the caller as
// context.DeadlineExceeded, which invites `err == context.DeadlineExceeded`;
// wrapping the one-failure case — by far the common one — would silently break
// every such caller the moment the OTel backend is the one flushing.
func _joinFlushErrors(errs []error) error {
	var lone error
	failed := 0
	for _, err := range errs {
		if err != nil {
			failed++
			lone = err
		}
	}
	if failed == 1 {
		return lone
	}
	return errors.Join(errs...)
}

func (b *_backend) Shutdown(ctx context.Context) error {
	// Detach the providers under the lock, then drain them outside it. Holding
	// the write lock across the drain would block every RLock reader — a
	// concurrent FlushTelemetry resolving providers, Providers(), LoggerHandler
	// — on a mutex no context deadline can bound, so an in-flight request would
	// hang for the full shutdown against an unreachable collector. Resetting
	// the globals here too means new spans land on the no-op immediately rather
	// than in a provider being torn down.
	// Bind the method values under the lock, run them outside it — the same
	// shape ForceFlush uses above, so first-error-wins is stated once instead of
	// per signal.
	_providersMu.Lock()
	shutdowns := []func(context.Context) error{}
	if _otelTracerProvider != nil {
		shutdowns = append(shutdowns, _otelTracerProvider.Shutdown)
	}
	if _otelMeterProvider != nil {
		shutdowns = append(shutdowns, _otelMeterProvider.Shutdown)
	}
	if _otelLoggerProvider != nil {
		shutdowns = append(shutdowns, _otelLoggerProvider.Shutdown)
	}
	_otelTracerProvider = nil
	_otelMeterProvider = nil
	_otelLoggerProvider = nil
	_resetGlobalsWeSet()
	_providersMu.Unlock()

	var first error
	for _, shutdown := range shutdowns {
		if err := shutdown(ctx); err != nil && first == nil {
			first = err
		}
	}
	return first
}

// _resetGlobalsWeSet returns to the API no-ops only for the globals this
// backend registered, leaving a host application's registration intact.
func _resetGlobalsWeSet() {
	if _weSetTracerGlobal {
		otel.SetTracerProvider(otelnooptrace.NewTracerProvider())
		_weSetTracerGlobal = false
	}
	if _weSetMeterGlobal {
		otel.SetMeterProvider(otelmetricnoop.NewMeterProvider())
		_weSetMeterGlobal = false
	}
	if _weSetLoggerGlobal {
		logglobal.SetLoggerProvider(otellognoop.NewLoggerProvider())
		_weSetLoggerGlobal = false
	}
}

func _shutdownOTelProviders(ctx context.Context) error {
	return (&_backend{}).Shutdown(ctx)
}

func (b *_backend) ResetForTests() {
	_providersMu.Lock()
	defer _providersMu.Unlock()

	_otelTracerProvider = nil
	_otelMeterProvider = nil
	_otelLoggerProvider = nil
	_weSetTracerGlobal = false
	_weSetMeterGlobal = false
	_weSetLoggerGlobal = false
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
		Logs:    _loadLoggerProvider() != nil,
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
	provider := _loadLoggerProvider()
	if provider == nil {
		return nil
	}
	return otelslog.NewHandler(name, otelslog.WithLoggerProvider(provider))
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
