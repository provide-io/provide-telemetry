// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"fmt"
	"log/slog"
	"strings"
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

// UpdateRuntimeConfig applies the given hot-reloadable overrides atomically.
// Nil pointer fields in RuntimeOverrides are left unchanged.
// Returns an error if the telemetry system is not set up.
func UpdateRuntimeConfig(overrides RuntimeOverrides) error {
	_setupMu.Lock()
	defer _setupMu.Unlock()

	if !_setupDone || _runtimeCfg == nil {
		return fmt.Errorf("telemetry not set up: call SetupTelemetry first")
	}

	next := cloneTelemetryConfig(_runtimeCfg)
	if overrides.Sampling != nil {
		next.Sampling = *overrides.Sampling
	}
	if overrides.Backpressure != nil {
		next.Backpressure = *overrides.Backpressure
	}
	if overrides.Exporter != nil {
		next.Exporter = *overrides.Exporter
	}
	if overrides.Security != nil {
		next.Security = *overrides.Security
	}
	if overrides.SLO != nil {
		next.SLO = *overrides.SLO
	}
	if overrides.PIIMaxDepth != nil {
		next.Logging.PIIMaxDepth = *overrides.PIIMaxDepth
	}
	_applyRuntimePolicies(next)
	_runtimeCfg = next
	return nil
}

// ReloadRuntimeFromEnv re-parses all environment variables and replaces the in-memory
// config snapshot. No subsystems are restarted; use ReconfigureTelemetry for a full
// restart. Cold fields (ServiceName, Environment, Version, Tracing.Enabled,
// Metrics.Enabled) that have drifted from the current config are logged as warnings.
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

	// Warn on cold-field drift.
	if _runtimeCfg != nil {
		var drifted []string
		if cfg.ServiceName != _runtimeCfg.ServiceName {
			drifted = append(drifted, "ServiceName")
		}
		if cfg.Environment != _runtimeCfg.Environment {
			drifted = append(drifted, "Environment")
		}
		if cfg.Version != _runtimeCfg.Version {
			drifted = append(drifted, "Version")
		}
		if cfg.Tracing.Enabled != _runtimeCfg.Tracing.Enabled {
			drifted = append(drifted, "Tracing.Enabled")
		}
		if cfg.Metrics.Enabled != _runtimeCfg.Metrics.Enabled {
			drifted = append(drifted, "Metrics.Enabled")
		}
		if len(drifted) > 0 {
			if Logger != nil {
				Logger.Warn("runtime.cold_field_drift",
					slog.String("fields", strings.Join(drifted, ",")),
					slog.String("action", "restart required to apply"),
				)
			}
		}
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
