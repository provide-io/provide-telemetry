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
	otellog "go.opentelemetry.io/otel/log"
	logglobal "go.opentelemetry.io/otel/log/global"
	otellognoop "go.opentelemetry.io/otel/log/noop"
	otelmetric "go.opentelemetry.io/otel/metric"
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
	_providersMu.RLock()
	providers := _installedProvidersLocked()
	_providersMu.RUnlock()

	return _drainConcurrently(ctx, providers, _drainable.ForceFlush)
}

// ForceFlushBySignal is ForceFlush with the outcomes kept apart.
//
// One entry per signal this backend installed; a signal we did not install — or
// one adopted from the OTel globals, which belongs to the host — is absent, so
// the facade can report it as NotOwned rather than claiming its records are out.
// Every signal is still attempted concurrently on the caller's full budget.
func (b *_backend) ForceFlushBySignal(ctx context.Context) map[string]error {
	_providersMu.RLock()
	names, providers := _installedSignalsLocked()
	_providersMu.RUnlock()

	errs := make([]error, len(providers))
	var wg sync.WaitGroup
	for i, provider := range providers {
		wg.Add(1)
		go func(i int, provider _drainable) {
			defer wg.Done()
			errs[i] = provider.ForceFlush(ctx)
		}(i, provider)
	}
	wg.Wait()

	results := make(map[string]error, len(names))
	for i, name := range names {
		results[name] = errs[i]
	}
	return results
}

// _installedSignalsLocked returns the signal names and providers this backend
// installed, in signal order. Must be called with _providersMu held.
func _installedSignalsLocked() ([]string, []_drainable) {
	names := []string{}
	providers := []_drainable{}
	// Each concrete pointer is nil-checked before it is boxed — a typed nil in
	// an interface would compare non-nil and panic on call.
	if _otelTracerProvider != nil {
		names = append(names, telemetry.SignalTraces)
		providers = append(providers, _otelTracerProvider)
	}
	if _otelMeterProvider != nil {
		names = append(names, telemetry.SignalMetrics)
		providers = append(providers, _otelMeterProvider)
	}
	if _otelLoggerProvider != nil {
		names = append(names, telemetry.SignalLogs)
		providers = append(providers, _otelLoggerProvider)
	}
	return names, providers
}

// _drainable is the lifecycle pair every SDK provider carries. Declared so the
// two drains can share one collection and one runner: they differ only in which
// method they bind.
type _drainable interface {
	ForceFlush(context.Context) error
	Shutdown(context.Context) error
}

// _installedProvidersLocked returns the providers this backend installed, in
// signal order. A provider adopted from the OTel globals is not ours to drain
// and is never in here. Must be called with _providersMu held.
func _installedProvidersLocked() []_drainable {
	providers := []_drainable{}
	// Each concrete pointer is nil-checked before it is boxed — a typed nil in
	// an interface would compare non-nil and panic on call.
	if _otelTracerProvider != nil {
		providers = append(providers, _otelTracerProvider)
	}
	if _otelMeterProvider != nil {
		providers = append(providers, _otelMeterProvider)
	}
	if _otelLoggerProvider != nil {
		providers = append(providers, _otelLoggerProvider)
	}
	return providers
}

// _drainConcurrently runs drain against every provider at once, so each signal
// gets the caller's full budget.
//
// Run in sequence they share one deadline, and a stalled traces exporter
// consumes it entirely: metrics and logs then return DeadlineExceeded without
// exporting anything. That is wrong for both drains — a flush that promises
// every signal an attempt, and a shutdown that is the last chance to get queued
// records out. Python, Rust and TypeScript all give each signal its own budget.
func _drainConcurrently(
	ctx context.Context,
	providers []_drainable,
	drain func(_drainable, context.Context) error,
) error {
	errs := make([]error, len(providers))
	var wg sync.WaitGroup
	for i, provider := range providers {
		wg.Add(1)
		go func(i int, provider _drainable) {
			defer wg.Done()
			errs[i] = drain(provider, ctx)
		}(i, provider)
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

// Shutdown tears down every provider we installed. Like ForceFlush, the signals
// drain concurrently on the caller's full budget rather than sharing it in
// sequence — shutdown is the last chance to get queued records out, so a
// stalled traces exporter must not cost metrics and logs their drain.
func (b *_backend) Shutdown(ctx context.Context) error {
	// Detach the providers under the lock, then drain them outside it. Holding
	// the write lock across the drain would block every RLock reader — a
	// concurrent FlushTelemetry resolving providers, Providers(), LoggerHandler
	// — on a mutex no context deadline can bound, so an in-flight request would
	// hang for the full shutdown against an unreachable collector. Resetting
	// the globals here too means new spans land on the no-op immediately rather
	// than in a provider being torn down.
	_providersMu.Lock()
	providers := _installedProvidersLocked()
	// Captured before the nil-out: _resetGlobalsWeSet compares these against the
	// live globals to decide whether the registration is still ours to undo.
	installedTP, installedMP, installedLP := _otelTracerProvider, _otelMeterProvider, _otelLoggerProvider
	_otelTracerProvider = nil
	_otelMeterProvider = nil
	_otelLoggerProvider = nil
	_resetGlobalsWeSet(installedTP, installedMP, installedLP)
	_providersMu.Unlock()

	return _drainConcurrently(ctx, providers, _drainable.Shutdown)
}

// _resetGlobalsWeSet returns to the API no-ops only for the globals this
// backend registered AND still owns.
//
// The ownership booleans alone are not enough. They record that we registered a
// provider once; they say nothing about whether that registration survived. A
// host that calls otel.SetTracerProvider after our Setup owns the global from
// that moment on — an auto-instrumentation agent, a vendor distro, a lazily
// initialised SDK — and handing the global back to a no-op would silently
// disable the host's telemetry. So identity decides: reset only while the
// global still holds the exact provider we installed.
//
// The flag is cleared either way. Once the host has taken the global there is
// no registration of ours left to undo, so continuing to claim ownership would
// only mean clobbering it on some later shutdown.
func _resetGlobalsWeSet(tp *sdktrace.TracerProvider, mp *sdkmetric.MeterProvider, lp *sdklog.LoggerProvider) {
	if _weSetTracerGlobal {
		if tp != nil && otel.GetTracerProvider() == oteltrace.TracerProvider(tp) {
			otel.SetTracerProvider(otelnooptrace.NewTracerProvider())
		}
		_weSetTracerGlobal = false
	}
	if _weSetMeterGlobal {
		if mp != nil && otel.GetMeterProvider() == otelmetric.MeterProvider(mp) {
			otel.SetMeterProvider(otelmetricnoop.NewMeterProvider())
		}
		_weSetMeterGlobal = false
	}
	if _weSetLoggerGlobal {
		if lp != nil && logglobal.GetLoggerProvider() == otellog.LoggerProvider(lp) {
			logglobal.SetLoggerProvider(otellognoop.NewLoggerProvider())
		}
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
