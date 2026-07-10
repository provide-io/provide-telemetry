// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"maps"
	"sync"
	"time"
)

// SetupOption configures optional setup-time state (e.g. injected OTel providers).
type SetupOption func(*_setupState)

// _setupState holds optional OTel provider references injected at setup time.
// Providers are typed as any until the OTel wiring task (Task 14) adds real types.
type _setupState struct {
	tracerProvider any
	meterProvider  any
	loggerProvider any
	config         *TelemetryConfig // when set via WithConfig, replaces ConfigFromEnv
}

// WithConfig supplies an in-memory TelemetryConfig instead of reading the process
// environment. Prefer this for hosts that re-exec or fork and must not mutate
// os.Environ to configure telemetry. When both WithConfig and env-derived defaults
// matter, construct the config yourself (e.g. start from ConfigFromEnv, override
// fields) and pass the result here.
//
// A nil cfg is ignored (env path used). The config is cloned so later mutations
// of the caller's pointer do not affect runtime state.
func WithConfig(cfg *TelemetryConfig) SetupOption {
	return func(s *_setupState) {
		if cfg != nil {
			s.config = cloneTelemetryConfig(cfg)
		}
	}
}

// WithTracerProvider injects a tracer provider at setup time.
func WithTracerProvider(tp any) SetupOption {
	return func(s *_setupState) { s.tracerProvider = tp }
}

// WithMeterProvider injects a meter provider at setup time.
func WithMeterProvider(mp any) SetupOption {
	return func(s *_setupState) { s.meterProvider = mp }
}

// WithLoggerProvider injects a logger provider at setup time.
func WithLoggerProvider(lp any) SetupOption {
	return func(s *_setupState) { s.loggerProvider = lp }
}

// Package-level setup state — protected by _setupMu.
var (
	_setupMu    sync.Mutex
	_setupDone  bool
	_runtimeCfg *TelemetryConfig
)

func cloneTelemetryConfig(cfg *TelemetryConfig) *TelemetryConfig {
	if cfg == nil {
		return nil
	}
	clone := *cfg
	clone.Logging = cfg.Logging
	clone.Logging.OTLPHeaders = maps.Clone(cfg.Logging.OTLPHeaders)
	clone.Logging.PrettyFields = append([]string(nil), cfg.Logging.PrettyFields...)
	clone.Logging.ModuleLevels = maps.Clone(cfg.Logging.ModuleLevels)
	clone.Tracing = cfg.Tracing
	clone.Tracing.OTLPHeaders = maps.Clone(cfg.Tracing.OTLPHeaders)
	clone.Metrics = cfg.Metrics
	clone.Metrics.OTLPHeaders = maps.Clone(cfg.Metrics.OTLPHeaders)
	clone.EventSchema = cfg.EventSchema
	clone.EventSchema.RequiredKeys = append([]string(nil), cfg.EventSchema.RequiredKeys...)
	return &clone
}

func _applyRuntimePolicies(cfg *TelemetryConfig) {
	_, _ = SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: cfg.Sampling.LogsRate})
	// Facade ShouldSample rate matches the SDK sampler rate. When a live OTel
	// tracer provider is installed, Trace() skips ShouldSample so the SDK is
	// the single sampling authority (no double-sampling).
	_, _ = SetSamplingPolicy(signalTraces, SamplingPolicy{DefaultRate: cfg.EffectiveTracesSampleRate()})
	_, _ = SetSamplingPolicy(signalMetrics, SamplingPolicy{DefaultRate: cfg.Sampling.MetricsRate})

	SetQueuePolicy(QueuePolicy{
		LogsMaxSize:    cfg.Backpressure.LogsMaxSize,
		TracesMaxSize:  cfg.Backpressure.TracesMaxSize,
		MetricsMaxSize: cfg.Backpressure.MetricsMaxSize,
	})

	SetExporterPolicy(signalLogs, ExporterPolicy{
		Retries:                  cfg.Exporter.LogsRetries,
		BackoffSeconds:           cfg.Exporter.LogsBackoffSeconds,
		TimeoutSeconds:           cfg.Exporter.LogsTimeoutSeconds,
		FailOpen:                 cfg.Exporter.LogsFailOpen,
		AllowBlockingInEventLoop: cfg.Exporter.LogsAllowBlockingInEventLoop,
	})
	SetExporterPolicy(signalTraces, ExporterPolicy{
		Retries:                  cfg.Exporter.TracesRetries,
		BackoffSeconds:           cfg.Exporter.TracesBackoffSeconds,
		TimeoutSeconds:           cfg.Exporter.TracesTimeoutSeconds,
		FailOpen:                 cfg.Exporter.TracesFailOpen,
		AllowBlockingInEventLoop: cfg.Exporter.TracesAllowBlockingInEventLoop,
	})
	SetExporterPolicy(signalMetrics, ExporterPolicy{
		Retries:                  cfg.Exporter.MetricsRetries,
		BackoffSeconds:           cfg.Exporter.MetricsBackoffSeconds,
		TimeoutSeconds:           cfg.Exporter.MetricsTimeoutSeconds,
		FailOpen:                 cfg.Exporter.MetricsFailOpen,
		AllowBlockingInEventLoop: cfg.Exporter.MetricsAllowBlockingInEventLoop,
	})

	_configureLogger(cfg)
	SetStrictSchema(cfg.StrictSchema || cfg.EventSchema.StrictEventName)
}

// SetupTelemetry initialises all telemetry subsystems.
//
// By default it reads configuration from environment variables via ConfigFromEnv.
// Pass WithConfig(cfg) to use an in-memory TelemetryConfig instead (preferred for
// hosts that re-exec/fork and must not mutate process environment).
//
// It is idempotent: a second call with the system already set up returns the
// existing config without re-initialising anything. Provider options
// (WithTracerProvider, etc.) are only applied on the first successful setup.
func SetupTelemetry(opts ...SetupOption) (*TelemetryConfig, error) {
	_setupMu.Lock()
	defer _setupMu.Unlock()

	if _setupDone {
		return cloneTelemetryConfig(_runtimeCfg), nil
	}

	// Apply functional options first so WithConfig can replace env loading.
	state := &_setupState{}
	for _, fn := range opts {
		fn(state)
	}

	var cfg *TelemetryConfig
	if state.config != nil {
		if err := validateTelemetryConfig(state.config); err != nil {
			return nil, err
		}
		cfg = state.config
	} else {
		var err error
		cfg, err = ConfigFromEnv()
		if err != nil {
			return nil, err
		}
	}

	// Wire per-signal sampling from config.
	_applyRuntimePolicies(cfg)

	// Wire any registered optional backend (for example go/otel).
	if err := _setupBackendLocked(state, cfg); err != nil {
		return nil, err
	}

	_runtimeCfg = cfg
	_setupDone = true

	return cloneTelemetryConfig(cfg), nil
}

// validateTelemetryConfig checks rates and log format/level on an in-memory
// config (the env path validates as it parses).
func validateTelemetryConfig(cfg *TelemetryConfig) error {
	if err := validateRate(cfg.Tracing.SampleRate, "Tracing.SampleRate"); err != nil {
		return err
	}
	if err := validateRate(cfg.Sampling.LogsRate, "Sampling.LogsRate"); err != nil {
		return err
	}
	if err := validateRate(cfg.Sampling.TracesRate, "Sampling.TracesRate"); err != nil {
		return err
	}
	if err := validateRate(cfg.Sampling.MetricsRate, "Sampling.MetricsRate"); err != nil {
		return err
	}
	if err := validateFormat(cfg.Logging.Format); err != nil {
		return err
	}
	if _, err := normalizeLevel(cfg.Logging.Level); err != nil {
		return err
	}
	return nil
}

// ShutdownTelemetry tears down all telemetry subsystems and resets the setup sentinel.
// It is safe to call on an already-shutdown system (no-op).
//
// When ctx has no deadline, ShutdownTelemetry applies one derived from
// cfg.Exporter.LogsShutdownTimeoutSeconds (default 5s) so the OTel SDK's
// LoggerProvider.Shutdown cannot block indefinitely against an unreachable
// OTLP endpoint. Callers that want to enforce their own deadline can pass a
// context.WithTimeout / context.WithDeadline themselves.
//
// When the library-applied deadline expires the bounded-shutdown contract is
// "abandon any pending flush and return cleanly" — matching the Python /
// TypeScript / Rust behaviour — so a resulting context.DeadlineExceeded from
// the backend is suppressed. Caller-supplied deadlines are still surfaced as
// errors because the caller explicitly asked for that bound.
func ShutdownTelemetry(ctx context.Context) error {
	_setupMu.Lock()
	defer _setupMu.Unlock()

	if !_setupDone {
		return nil
	}

	timeout := _shutdownDeadlineForLocked(ctx)
	libraryBounded := timeout > 0
	if libraryBounded {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, timeout)
		defer cancel()
	}

	_setupDone = false
	_runtimeCfg = nil

	err := _shutdownBackendLocked(ctx)
	DefaultTracer = &_noopTracer{}
	_resetLogger()
	if libraryBounded && errors.Is(err, context.DeadlineExceeded) {
		return nil
	}
	return err
}

// _shutdownDeadlineForLocked returns the bounded-shutdown timeout to apply
// when ctx has no deadline of its own. Returns 0 when the caller already
// supplied a deadline (we honour the caller's choice) or when the active
// config disables bounding (LogsShutdownTimeoutSeconds <= 0).
//
// Must be called with _setupMu held — it reads _runtimeCfg.
func _shutdownDeadlineForLocked(ctx context.Context) time.Duration {
	if _, ok := ctx.Deadline(); ok {
		return 0
	}
	if _runtimeCfg == nil {
		return 0
	}
	secs := _runtimeCfg.Exporter.LogsShutdownTimeoutSeconds
	if secs <= 0 {
		return 0
	}
	return time.Duration(secs * float64(time.Second))
}

// _resetSetup clears setup state unconditionally. For use in tests only.
func _resetSetup() {
	_setupMu.Lock()
	defer _setupMu.Unlock()
	_setupDone = false
	_runtimeCfg = nil
	_resetBackendsLocked()
	DefaultTracer = &_noopTracer{}
	_resetLogger()
}
