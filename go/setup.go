// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"maps"
	"sync"
)

// SetupOption configures optional setup-time state (e.g. injected OTel providers).
type SetupOption func(*_setupState)

// _setupState holds optional OTel provider references injected at setup time.
// Providers are typed as any until the OTel wiring task (Task 14) adds real types.
type _setupState struct {
	tracerProvider any
	meterProvider  any
}

// WithTracerProvider injects a tracer provider at setup time.
func WithTracerProvider(tp any) SetupOption {
	return func(s *_setupState) { s.tracerProvider = tp }
}

// WithMeterProvider injects a meter provider at setup time.
func WithMeterProvider(mp any) SetupOption {
	return func(s *_setupState) { s.meterProvider = mp }
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
	SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: cfg.Sampling.LogsRate})
	SetSamplingPolicy(signalTraces, SamplingPolicy{DefaultRate: cfg.Sampling.TracesRate})
	SetSamplingPolicy(signalMetrics, SamplingPolicy{DefaultRate: cfg.Sampling.MetricsRate})

	SetQueuePolicy(QueuePolicy{
		LogsMaxSize:    cfg.Backpressure.LogsMaxSize,
		TracesMaxSize:  cfg.Backpressure.TracesMaxSize,
		MetricsMaxSize: cfg.Backpressure.MetricsMaxSize,
	})

	SetExporterPolicy(signalLogs, ExporterPolicy{
		Retries:        cfg.Exporter.LogsRetries,
		BackoffSeconds: cfg.Exporter.LogsBackoffSeconds,
		TimeoutSeconds: cfg.Exporter.LogsTimeoutSeconds,
		FailOpen:       cfg.Exporter.LogsFailOpen,
	})
	SetExporterPolicy(signalTraces, ExporterPolicy{
		Retries:        cfg.Exporter.TracesRetries,
		BackoffSeconds: cfg.Exporter.TracesBackoffSeconds,
		TimeoutSeconds: cfg.Exporter.TracesTimeoutSeconds,
		FailOpen:       cfg.Exporter.TracesFailOpen,
	})
	SetExporterPolicy(signalMetrics, ExporterPolicy{
		Retries:        cfg.Exporter.MetricsRetries,
		BackoffSeconds: cfg.Exporter.MetricsBackoffSeconds,
		TimeoutSeconds: cfg.Exporter.MetricsTimeoutSeconds,
		FailOpen:       cfg.Exporter.MetricsFailOpen,
	})

	_configureLogger(cfg)
	_strictSchema = cfg.StrictSchema
}

// SetupTelemetry initialises all telemetry subsystems from environment variables.
// It is idempotent: a second call with the system already set up returns the existing
// config without re-initialising anything.
func SetupTelemetry(opts ...SetupOption) (*TelemetryConfig, error) {
	_setupMu.Lock()
	defer _setupMu.Unlock()

	if _setupDone {
		return _runtimeCfg, nil
	}

	cfg, err := ConfigFromEnv()
	if err != nil {
		return nil, err
	}

	// Apply functional options to setup state (providers will be wired in Task 14).
	state := &_setupState{}
	for _, fn := range opts {
		fn(state)
	}

	// Wire per-signal sampling from config.
	_applyRuntimePolicies(cfg)

	// Wire OTel providers if any were supplied.
	_applyOTelProviders(state, cfg)

	// Record setup in health counters.
	_incSetupCount()

	_runtimeCfg = cfg
	_setupDone = true

	return cfg, nil
}

// ShutdownTelemetry tears down all telemetry subsystems and resets the setup sentinel.
// It is safe to call on an already-shutdown system (no-op).
func ShutdownTelemetry(ctx context.Context) error {
	_setupMu.Lock()
	defer _setupMu.Unlock()

	if !_setupDone {
		return nil
	}

	_setupDone = false
	_runtimeCfg = nil
	_incShutdownCount()

	return _shutdownOTelProviders(ctx)
}

// _resetSetup clears setup state unconditionally. For use in tests only.
func _resetSetup() {
	_setupMu.Lock()
	defer _setupMu.Unlock()
	_setupDone = false
	_runtimeCfg = nil
	_resetOTelProviders()
	DefaultTracer = &_noopTracer{}
}
