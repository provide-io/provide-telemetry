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

// ReconfigureResult is the outcome of an attempted runtime reconfiguration.
//
// Field names are the cross-language canonical set — Previous/Current name the
// configs on either side of the attempt, and State is the runtime state after it.
// The json tags matter: Rust serializes this type with serde's snake_case field
// names, so without them a Go-marshalled result would emit PascalCase keys and
// fail to deserialize on the other side.
type ReconfigureResult struct {
	Applied  bool             `json:"applied"`
	Previous *TelemetryConfig `json:"previous"`
	Current  *TelemetryConfig `json:"current"`
	Error    string           `json:"error"`
	State    RuntimeState     `json:"state"`
}

// TelemetryRuntime is the canonical Go façade entrypoint.
// It deliberately keeps behavior small and stateless.
type TelemetryRuntime struct {
	providerMode ProviderMode
	state        RuntimeState
	opts         []SetupOption
}

// NewTelemetryRuntime records opts for the eventual Start call. Construction does
// not install providers — setup can fail, and only Start can report that error.
func NewTelemetryRuntime(_ context.Context, opts ...SetupOption) *TelemetryRuntime {
	return &TelemetryRuntime{providerMode: ProviderModeOwned, state: RuntimeStateReady, opts: opts}
}

// Start installs providers using the constructor's options followed by opts, so a
// per-call option overrides the same option supplied at construction.
func (rt *TelemetryRuntime) Start(ctx context.Context, opts ...SetupOption) (*TelemetryConfig, error) {
	rt.state = RuntimeStateStarting
	cfg, err := SetupTelemetry(append(append([]SetupOption{}, rt.opts...), opts...)...)
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

// UpdateConfig applies the hot-reloadable fields of cfg and returns the resulting
// runtime config. Provider-changing fields (endpoints, headers) are rejected by
// UpdateRuntimeConfig — use Reconfigure for those.
func (rt *TelemetryRuntime) UpdateConfig(ctx context.Context, cfg *TelemetryConfig) (*TelemetryConfig, error) {
	_ = ctx
	if cfg == nil {
		return nil, NewConfigurationError("UpdateConfig requires a non-nil config")
	}
	if err := UpdateRuntimeConfig(runtimeOverridesFromConfig(cfg)); err != nil {
		return nil, err
	}
	return GetRuntimeConfig(), nil
}

// Reconfigure applies cfg as the reconfiguration target. A nil cfg falls back to
// the process environment. Explicit opts are applied after cfg, so a caller-supplied
// WithConfig takes precedence.
func (rt *TelemetryRuntime) Reconfigure(ctx context.Context, cfg *TelemetryConfig, opts ...SetupOption) (*TelemetryConfig, error) {
	if cfg != nil {
		opts = append([]SetupOption{WithConfig(cfg)}, opts...)
	}
	return ReconfigureTelemetry(ctx, opts...)
}

// Flush drains installed providers and reports per-signal outcomes. A signal with
// no provider installed reports NotInstalled rather than Flushed — matching the
// Rust facade, which reads the same per-signal provider status.
func (rt *TelemetryRuntime) Flush(ctx context.Context) (*FlushResult, error) {
	providers := GetRuntimeStatus().Providers
	err := FlushTelemetry(ctx)
	signal := func(installed bool) SignalFlushResult {
		return SignalFlushResult{
			Flushed:      installed && err == nil,
			NotInstalled: !installed,
			Failed:       installed && err != nil,
		}
	}
	return &FlushResult{
		Logs:    signal(providers.Logs),
		Traces:  signal(providers.Traces),
		Metrics: signal(providers.Metrics),
	}, err
}

func (rt *TelemetryRuntime) Shutdown(ctx context.Context) error {
	rt.state = RuntimeStateStopping
	defer func() {
		rt.state = RuntimeStateStopped
	}()
	return ShutdownTelemetry(ctx)
}
