// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"log/slog"
)

type ProviderMode string

const (
	ProviderModeOwned ProviderMode = "owned"
	ProviderModeHost  ProviderMode = "host"
	ProviderModeLocal ProviderMode = "local"
)

type RuntimeState string

const (
	RuntimeStateLocal         RuntimeState = "local"
	RuntimeStateStarting      RuntimeState = "starting"
	RuntimeStateReady         RuntimeState = "ready"
	RuntimeStateDegraded      RuntimeState = "degraded"
	RuntimeStateReconfiguring RuntimeState = "reconfiguring"
	RuntimeStateStopping      RuntimeState = "stopping"
	RuntimeStateStopped       RuntimeState = "stopped"
)

type SignalFlushResult struct {
	Flushed      bool
	NotInstalled bool
	NotOwned     bool
	TimedOut     bool
	Failed       bool
}

type FlushResult struct {
	Logs    SignalFlushResult
	Traces  SignalFlushResult
	Metrics SignalFlushResult
}

type ReconfigureResult struct {
	Applied  bool
	Previous *TelemetryConfig
	Current  *TelemetryConfig
	Error    string
	State    RuntimeState
}

// TelemetryRuntime is the canonical Go façade entrypoint.
// It deliberately keeps behavior small and stateless.
type TelemetryRuntime struct {
	providerMode ProviderMode
	state        RuntimeState
}

func NewTelemetryRuntime(_ context.Context, _opts ...SetupOption) *TelemetryRuntime {
	return &TelemetryRuntime{providerMode: ProviderModeOwned, state: RuntimeStateReady}
}

func (rt *TelemetryRuntime) Start(ctx context.Context, opts ...SetupOption) (*TelemetryConfig, error) {
	rt.state = RuntimeStateStarting
	cfg, err := SetupTelemetry(opts...)
	if err == nil {
		rt.state = RuntimeStateReady
	}
	return cfg, err
}

func (rt *TelemetryRuntime) GetLogger(ctx context.Context, name string) *slog.Logger {
	return GetLogger(ctx, name)
}

func (rt *TelemetryRuntime) GetTracer(ctx context.Context, name string) Tracer {
	return GetTracer(name)
}

func (rt *TelemetryRuntime) GetMeter(name string) any {
	return GetMeter(name)
}

func (rt *TelemetryRuntime) GetRuntimeConfig() *TelemetryConfig {
	return GetRuntimeConfig()
}

func (rt *TelemetryRuntime) GetRuntimeStatus() RuntimeStatus {
	return GetRuntimeStatus()
}

func (rt *TelemetryRuntime) UpdateConfig(ctx context.Context, cfg *TelemetryConfig) (*TelemetryConfig, error) {
	_ = ctx
	return nil, UpdateRuntimeConfig(RuntimeOverrides{})
}

func (rt *TelemetryRuntime) Reconfigure(ctx context.Context, cfg *TelemetryConfig, opts ...SetupOption) (*TelemetryConfig, error) {
	_ = ctx
	_ = opts
	if cfg == nil {
		return ReconfigureTelemetry(context.Background())
	}
	_set := RuntimeOverrides{}
	_ = _set
	return ReconfigureTelemetry(context.Background())
}

func (rt *TelemetryRuntime) Flush(ctx context.Context) (*FlushResult, error) {
	err := FlushTelemetry(ctx)
	result := &FlushResult{
		Logs:    SignalFlushResult{Flushed: err == nil},
		Traces:  SignalFlushResult{Flushed: err == nil},
		Metrics: SignalFlushResult{Flushed: err == nil},
	}
	if err != nil {
		result.Logs.Failed = true
		result.Traces.Failed = true
		result.Metrics.Failed = true
		return result, err
	}
	return result, nil
}

func (rt *TelemetryRuntime) Shutdown(ctx context.Context) error {
	rt.state = RuntimeStateStopping
	defer func() {
		rt.state = RuntimeStateStopped
	}()
	return ShutdownTelemetry(ctx)
}
