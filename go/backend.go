// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
)

// InstrumentOptions is a backend-facing snapshot of optional instrument metadata.
type InstrumentOptions struct {
	Description string
	Unit        string
}

// BackendSetupState exposes setup-time provider hints to optional backends.
type BackendSetupState struct {
	tracerProvider any
	meterProvider  any
	loggerProvider any
}

// TracerProvider returns the caller-supplied tracer provider, if any.
func (s BackendSetupState) TracerProvider() any { return s.tracerProvider }

// MeterProvider returns the caller-supplied meter provider, if any.
func (s BackendSetupState) MeterProvider() any { return s.meterProvider }

// LoggerProvider returns the caller-supplied logger provider, if any.
func (s BackendSetupState) LoggerProvider() any { return s.loggerProvider }

// Backend provides an optional signal implementation such as OpenTelemetry.
type Backend interface {
	Setup(cfg *TelemetryConfig, state BackendSetupState) error
	Shutdown(ctx context.Context) error
	ResetForTests()
	Providers() SignalStatus
	Tracer(name string) Tracer
	TraceContext(ctx context.Context) (traceID, spanID string, ok bool)
	LoggerHandler(name string) slog.Handler
	Meter(name string) any
	NewCounter(name string, opts InstrumentOptions) (Counter, bool)
	NewGauge(name string, opts InstrumentOptions) (Gauge, bool)
	NewHistogram(name string, opts InstrumentOptions) (Histogram, bool)
}

var (
	_backendMu          sync.RWMutex           //nolint:gochecknoglobals
	_registeredBackends = map[string]Backend{} //nolint:gochecknoglobals
	_activeBackendName  string                 //nolint:gochecknoglobals
)

// RegisterBackend registers an optional backend and marks it active.
// It returns the previously registered backend for the same name, if any.
func RegisterBackend(name string, backend Backend) (previous Backend, replaced bool) {
	_backendMu.Lock()
	defer _backendMu.Unlock()

	previous, replaced = _registeredBackends[name]
	_registeredBackends[name] = backend
	_activeBackendName = name
	return previous, replaced
}

// UnregisterBackend removes a previously registered optional backend.
func UnregisterBackend(name string) (previous Backend, removed bool) {
	_backendMu.Lock()
	defer _backendMu.Unlock()

	previous, removed = _registeredBackends[name]
	if removed {
		delete(_registeredBackends, name)
		if _activeBackendName == name {
			_activeBackendName = ""
		}
	}
	return previous, removed
}

// _activeBackend returns the currently active Backend, or nil when none is registered.
// It self-locks _backendMu for reading; callers must NOT already hold the lock.
func _activeBackend() Backend {
	_backendMu.RLock()
	defer _backendMu.RUnlock()
	if _activeBackendName == "" {
		return nil
	}
	return _registeredBackends[_activeBackendName]
}

func _backendSetupState(state *_setupState) BackendSetupState {
	return BackendSetupState{
		tracerProvider: state.tracerProvider,
		meterProvider:  state.meterProvider,
		loggerProvider: state.loggerProvider,
	}
}

func _backendOptionsSupplied(state *_setupState) bool {
	return state.tracerProvider != nil || state.meterProvider != nil || state.loggerProvider != nil
}

func _backendConfigured(cfg *TelemetryConfig) bool {
	return cfg.Tracing.OTLPEndpoint != "" || cfg.Metrics.OTLPEndpoint != "" || cfg.Logging.OTLPEndpoint != ""
}

// _backendTracerName is the instrumentation name handed to the backend when the
// tracer is resolved late (see _effectiveTracer).
var _backendTracerName string //nolint:gochecknoglobals

// _effectiveTracer returns the tracer a facade span should start on.
//
// The DefaultTracer binding is taken once, during setup. That is too early to
// see a provider a host application registers afterwards — an auto-
// instrumentation agent, a lazily-initialised vendor distro, a framework hook —
// so when the binding is still our no-op we ask the backend again on each span.
// A non-no-op binding always wins, so an explicit override keeps control.
func _effectiveTracer() Tracer {
	if _, isNoop := DefaultTracer.(*_noopTracer); !isNoop {
		return DefaultTracer
	}
	if backend := _activeBackend(); backend != nil {
		if tracer := backend.Tracer(_backendTracerName); tracer != nil {
			return tracer
		}
	}
	return DefaultTracer
}

func _wireBackendBindingsLocked(cfg *TelemetryConfig) {
	DefaultTracer = &_noopTracer{}
	_backendTracerName = cfg.ServiceName
	if Logger == nil {
		return
	}

	backend := _activeBackend()
	if backend == nil {
		return
	}
	providers := backend.Providers()
	if providers.Traces {
		if tracer := backend.Tracer(cfg.ServiceName); tracer != nil {
			DefaultTracer = tracer
		}
	}
	if providers.Logs {
		bridgeName := cfg.ServiceName
		if bridge := backend.LoggerHandler(bridgeName); bridge != nil {
			Logger = slog.New(newMultiHandler(Logger.Handler(), bridge))
			slog.SetDefault(Logger)
		}
	}
}

func _setupBackendLocked(state *_setupState, cfg *TelemetryConfig) error {
	backend := _activeBackend()
	if backend == nil {
		if _backendOptionsSupplied(state) {
			return NewConfigurationError(
				"provider options require an optional backend; import a backend module such as github.com/provide-io/provide-telemetry/go/otel",
			)
		}
		_wireBackendBindingsLocked(cfg)
		return nil
	}
	if !_backendOptionsSupplied(state) && !_backendConfigured(cfg) {
		_wireBackendBindingsLocked(cfg)
		return nil
	}
	if err := backend.Setup(cfg, _backendSetupState(state)); err != nil {
		return err
	}
	_wireBackendBindingsLocked(cfg)
	return nil
}

// FlushableBackend is the optional drain half of Backend: a backend that can
// force-flush its providers without tearing them down implements it. It is a
// separate interface rather than a Backend method so adding it does not break
// third-party Backend implementations; FlushTelemetry is a no-op for a backend
// that does not implement it.
type FlushableBackend interface {
	ForceFlush(ctx context.Context) error
}

func _flushBackendLocked(ctx context.Context) error {
	backend := _activeBackend()
	if backend == nil {
		return nil
	}
	flushable, ok := backend.(FlushableBackend)
	if !ok {
		return nil
	}
	return flushable.ForceFlush(ctx)
}

func _shutdownBackendLocked(ctx context.Context) error {
	if backend := _activeBackend(); backend != nil {
		return backend.Shutdown(ctx)
	}
	return nil
}

func _resetBackendsLocked() {
	for _, backend := range _registeredBackends {
		backend.ResetForTests()
	}
}

func _providerStatusLocked() SignalStatus {
	if backend := _activeBackend(); backend != nil {
		return backend.Providers()
	}
	return SignalStatus{}
}

func _providerConfigError() error {
	return NewConfigurationError(
		"provider-changing reconfiguration is unsupported after optional providers are installed; restart the process and call SetupTelemetry() with the new config",
	)
}

func _providerImportHint(name string) string {
	return fmt.Sprintf(
		"optional provider support for %s is not available; import a backend module such as github.com/provide-io/provide-telemetry/go/otel",
		name,
	)
}
