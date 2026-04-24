// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

// SignalStatus describes whether a telemetry signal is enabled, provider-backed,
// or running on the local fallback path.
type SignalStatus struct {
	Logs    bool
	Traces  bool
	Metrics bool
}

// RuntimeStatus reports the active runtime/provider state using the shared
// cross-language shape.
type RuntimeStatus struct {
	SetupDone  bool
	Signals    SignalStatus
	Providers  SignalStatus
	Fallback   SignalStatus
	SetupError string
}

// GetRuntimeStatus returns current signal enablement, provider install state,
// fallback mode, and the last setup error if any.
func GetRuntimeStatus() RuntimeStatus {
	_setupMu.Lock()
	setupDone := _setupDone
	cfg := cloneTelemetryConfig(_runtimeCfg)
	providers := _providerStatusLocked()
	_setupMu.Unlock()

	if cfg == nil {
		var err error
		cfg, err = ConfigFromEnv()
		if err != nil || cfg == nil {
			cfg = DefaultTelemetryConfig()
		}
	}

	return RuntimeStatus{
		SetupDone: setupDone,
		Signals: SignalStatus{
			Logs:    true,
			Traces:  cfg.Tracing.Enabled,
			Metrics: cfg.Metrics.Enabled,
		},
		Providers: providers,
		Fallback: SignalStatus{
			Logs:    !providers.Logs,
			Traces:  !providers.Traces,
			Metrics: !providers.Metrics,
		},
		SetupError: GetHealthSnapshot().SetupError,
	}
}
