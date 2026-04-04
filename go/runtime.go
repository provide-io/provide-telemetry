// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"fmt"
)

// GetRuntimeConfig returns the active TelemetryConfig, or nil if SetupTelemetry has not
// been called (or the system has been shut down).
func GetRuntimeConfig() *TelemetryConfig {
	_setupMu.Lock()
	defer _setupMu.Unlock()
	if _runtimeCfg == nil {
		return nil
	}
	return cloneTelemetryConfig(_runtimeCfg)
}

// UpdateRuntimeConfig applies mutate to the current config atomically.
// Returns an error if the telemetry system is not set up.
func UpdateRuntimeConfig(mutate func(*TelemetryConfig)) error {
	_setupMu.Lock()
	defer _setupMu.Unlock()

	if !_setupDone || _runtimeCfg == nil {
		return fmt.Errorf("telemetry not set up: call SetupTelemetry first")
	}

	next := cloneTelemetryConfig(_runtimeCfg)
	mutate(next)
	_applyRuntimePolicies(next)
	_runtimeCfg = next
	return nil
}

// ReloadRuntimeFromEnv re-parses all environment variables and replaces the in-memory
// config snapshot. No subsystems are restarted; use ReconfigureTelemetry for a full
// restart.
func ReloadRuntimeFromEnv() error {
	_setupMu.Lock()
	defer _setupMu.Unlock()

	if !_setupDone {
		return fmt.Errorf("telemetry not set up: call SetupTelemetry first")
	}

	cfg, err := ConfigFromEnv()
	if err != nil {
		return err
	}

	_applyRuntimePolicies(cfg)
	_runtimeCfg = cfg
	return nil
}

// ReconfigureTelemetry performs a full shutdown followed by a fresh setup using current
// environment variables. It is equivalent to calling ShutdownTelemetry then SetupTelemetry.
func ReconfigureTelemetry(ctx context.Context, opts ...SetupOption) (*TelemetryConfig, error) {
	// TODO(Task-14): propagate this error once ShutdownTelemetry can fail
	// (OTel TracerProvider/MeterProvider.Shutdown returns errors on context
	// deadline or exporter flush failure).
	_ = ShutdownTelemetry(ctx)
	return SetupTelemetry(opts...)
}
