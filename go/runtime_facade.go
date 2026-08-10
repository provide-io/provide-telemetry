// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
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
// runtime config.
//
// Provider-changing fields (service identity, OTLP endpoints and headers, and
// the per-signal enable flags) are rejected when they differ from the live
// config — installing a new exporter needs a process restart, and quietly
// copying a new endpoint into the live config would leave records going to the
// old collector while GetRuntimeConfig reported the new one. Use Reconfigure
// for those, or restart with SetupTelemetry.
func (rt *TelemetryRuntime) UpdateConfig(ctx context.Context, cfg *TelemetryConfig) (*TelemetryConfig, error) {
	_ = ctx
	if cfg == nil {
		return nil, NewConfigurationError("UpdateConfig requires a non-nil config")
	}
	if err := rejectProviderChangingFields(cfg); err != nil {
		return nil, err
	}
	if err := UpdateRuntimeConfig(runtimeOverridesFromConfig(cfg)); err != nil {
		return nil, err
	}
	return GetRuntimeConfig(), nil
}

// Reconfigure applies cfg as the reconfiguration target. A nil cfg falls back to
// the runtime's constructor options, then to the process environment. Options
// are ordered constructor-first so an explicit cfg, and then explicit opts,
// each override what came before — matching Start.
func (rt *TelemetryRuntime) Reconfigure(ctx context.Context, cfg *TelemetryConfig, opts ...SetupOption) (*TelemetryConfig, error) {
	// rt.opts is forwarded for the same reason Start forwards it: a host that
	// built the runtime with WithConfig did so because it must not read the
	// process environment. Dropping them here made Reconfigure(ctx, nil) fall
	// through to ConfigFromEnv and silently replace the caller's settings with
	// environment defaults.
	resolved := append([]SetupOption{}, rt.opts...)
	if cfg != nil {
		resolved = append(resolved, WithConfig(cfg))
	}
	resolved = append(resolved, opts...)
	return ReconfigureTelemetry(ctx, resolved...)
}

// Flush drains installed providers and reports per-signal outcomes.
//
// A signal with no provider installed reports NotInstalled. A signal whose
// provider the host application put on the OTel globals reports NotOwned — we
// leave it alone, so calling it Flushed would tell a caller its records are out
// when they are still in the host's queue. The rest carry their own drain
// result: the three export to potentially different endpoints, and one
// unreachable collector says nothing about the other two.
//
// Backends that do not implement PerSignalFlushableBackend can only answer in
// aggregate, and every installed signal then carries the same outcome. A
// backend that implements neither flush interface cannot answer at all: every
// installed signal reports NotOwned, because Flushed would tell a caller its
// records are out while they sit undrained in the backend's queue.
func (rt *TelemetryRuntime) Flush(ctx context.Context) (*FlushResult, error) {
	status := GetRuntimeStatus()
	providers := status.Providers
	perSignal, granular := FlushTelemetryBySignal(ctx)
	err := _joinSignalErrors(perSignal)
	if !granular {
		err = FlushTelemetry(ctx)
	}
	// A type assertion on a nil interface is simply false, so an absent
	// backend needs no separate case.
	_, flushable := _activeBackend().(FlushableBackend)
	signal := func(name string, installed bool) SignalFlushResult {
		if !installed {
			return SignalFlushResult{NotInstalled: true}
		}
		// Before SetupTelemetry nothing installed is ours. A provider visible
		// here is one the host put on the OTel globals, and both flush entry
		// points short-circuit on !_setupDone without touching it — so the
		// aggregate nil they return is "nothing was drained", not "the drain
		// succeeded". Calling that Flushed would tell a caller its records are
		// out while they sit in the host's batch processor.
		if !status.SetupDone {
			return SignalFlushResult{NotOwned: true}
		}
		if !granular && !flushable {
			// The registered backend implements neither FlushableBackend nor
			// PerSignalFlushableBackend, so both flush entry points returned
			// nil without draining anything. installed + setupDone + nil error
			// must not map to Flushed here — the records are still queued, the
			// exact misreport NotOwned exists to prevent: installed, but not
			// drainable by us.
			return SignalFlushResult{NotOwned: true}
		}
		drainErr := err
		if granular {
			ours, owned := perSignal[name]
			if !owned {
				return SignalFlushResult{NotOwned: true}
			}
			drainErr = ours
		}
		if drainErr == nil {
			return SignalFlushResult{Flushed: true}
		}
		if errors.Is(drainErr, context.DeadlineExceeded) {
			return SignalFlushResult{TimedOut: true}
		}
		return SignalFlushResult{Failed: true}
	}
	return &FlushResult{
		Logs:    signal(SignalLogs, providers.Logs),
		Traces:  signal(SignalTraces, providers.Traces),
		Metrics: signal(SignalMetrics, providers.Metrics),
	}, err
}

// _joinSignalErrors collapses per-signal drain errors for Flush's error return,
// which stays aggregate for callers that only want "did everything get out".
func _joinSignalErrors(perSignal map[string]error) error {
	errs := make([]error, 0, len(perSignal))
	for _, name := range []string{SignalLogs, SignalTraces, SignalMetrics} {
		if err, ok := perSignal[name]; ok && err != nil {
			errs = append(errs, err)
		}
	}
	if len(errs) == 1 {
		// Handed back untouched so a caller's `== context.DeadlineExceeded`
		// still matches, as FlushTelemetry documents.
		return errs[0]
	}
	return errors.Join(errs...)
}

func (rt *TelemetryRuntime) Shutdown(ctx context.Context) error {
	rt.state = RuntimeStateStopping
	defer func() {
		rt.state = RuntimeStateStopped
	}()
	return ShutdownTelemetry(ctx)
}
