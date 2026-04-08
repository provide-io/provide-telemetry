// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"fmt"
	"log/slog"
	"math"
	"strings"
)

// GetRuntimeConfig returns the active TelemetryConfig, or nil if SetupTelemetry has not
// been called (or the system has been shut down).
func GetRuntimeConfig() *TelemetryConfig {
	_setupMu.Lock()
	defer _setupMu.Unlock()
	return _runtimeCfg
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

	if err := validateRuntimeOverrides(overrides); err != nil {
		return err
	}
	next := cloneTelemetryConfig(_runtimeCfg)
	applyRuntimeOverrides(next, overrides)
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
	_warnColdFieldDrift(cfg)

	overrides := runtimeOverridesFromConfig(cfg)
	next := cloneTelemetryConfig(_runtimeCfg)
	applyRuntimeOverrides(next, overrides)
	_applyRuntimePolicies(next)
	_runtimeCfg = next
	return nil
}

func runtimeOverridesFromConfig(cfg *TelemetryConfig) RuntimeOverrides {
	return RuntimeOverrides{
		Sampling:     &cfg.Sampling,
		Backpressure: &cfg.Backpressure,
		Exporter:     &cfg.Exporter,
		Security:     &cfg.Security,
		SLO:          &cfg.SLO,
		PIIMaxDepth:  &cfg.Logging.PIIMaxDepth,
		StrictSchema: &cfg.StrictSchema,
	}
}

func applyRuntimeOverrides(cfg *TelemetryConfig, overrides RuntimeOverrides) {
	if overrides.Sampling != nil {
		cfg.Sampling = *overrides.Sampling
	}
	if overrides.Backpressure != nil {
		cfg.Backpressure = *overrides.Backpressure
	}
	if overrides.Exporter != nil {
		cfg.Exporter = *overrides.Exporter
	}
	if overrides.Security != nil {
		cfg.Security = *overrides.Security
	}
	if overrides.SLO != nil {
		cfg.SLO = *overrides.SLO
	}
	if overrides.PIIMaxDepth != nil {
		cfg.Logging.PIIMaxDepth = *overrides.PIIMaxDepth
	}
	if overrides.StrictSchema != nil {
		cfg.StrictSchema = *overrides.StrictSchema
	}
}

func validateRuntimeOverrides(overrides RuntimeOverrides) error {
	validators := []func() error{
		func() error {
			if overrides.Sampling != nil {
				return _validateSamplingOverride(*overrides.Sampling)
			}
			return nil
		},
		func() error {
			if overrides.Backpressure != nil {
				return _validateBackpressureOverride(*overrides.Backpressure)
			}
			return nil
		},
		func() error {
			if overrides.Exporter != nil {
				return validateExporterPolicyOverride(*overrides.Exporter)
			}
			return nil
		},
		func() error {
			if overrides.Security != nil {
				return _validateSecurityOverride(*overrides.Security)
			}
			return nil
		},
		func() error {
			if overrides.PIIMaxDepth != nil {
				return validateNonNegative(*overrides.PIIMaxDepth, "RuntimeOverrides.PIIMaxDepth")
			}
			return nil
		},
	}
	for _, v := range validators {
		if err := v(); err != nil {
			return err
		}
	}
	return nil
}

func _validateSamplingOverride(s SamplingConfig) error {
	if err := validateRateFinite(s.LogsRate, "RuntimeOverrides.Sampling.LogsRate"); err != nil {
		return err
	}
	if err := validateRateFinite(s.TracesRate, "RuntimeOverrides.Sampling.TracesRate"); err != nil {
		return err
	}
	return validateRateFinite(s.MetricsRate, "RuntimeOverrides.Sampling.MetricsRate")
}

func _validateBackpressureOverride(b BackpressureConfig) error {
	if err := validateNonNegative(b.LogsMaxSize, "RuntimeOverrides.Backpressure.LogsMaxSize"); err != nil {
		return err
	}
	if err := validateNonNegative(b.TracesMaxSize, "RuntimeOverrides.Backpressure.TracesMaxSize"); err != nil {
		return err
	}
	return validateNonNegative(b.MetricsMaxSize, "RuntimeOverrides.Backpressure.MetricsMaxSize")
}

func _validateSecurityOverride(s SecurityConfig) error {
	if err := validateNonNegative(s.MaxAttrValueLength, "RuntimeOverrides.Security.MaxAttrValueLength"); err != nil {
		return err
	}
	if err := validateNonNegative(s.MaxAttrCount, "RuntimeOverrides.Security.MaxAttrCount"); err != nil {
		return err
	}
	return validateNonNegative(s.MaxNestingDepth, "RuntimeOverrides.Security.MaxNestingDepth")
}

func validateExporterPolicyOverride(policy ExporterPolicyConfig) error {
	ints := map[string]int{
		"LogsRetries":    policy.LogsRetries,
		"TracesRetries":  policy.TracesRetries,
		"MetricsRetries": policy.MetricsRetries,
	}
	for field, value := range ints {
		if err := validateNonNegative(value, "RuntimeOverrides.Exporter."+field); err != nil {
			return err
		}
	}
	floats := map[string]float64{
		"LogsBackoffSeconds":    policy.LogsBackoffSeconds,
		"TracesBackoffSeconds":  policy.TracesBackoffSeconds,
		"MetricsBackoffSeconds": policy.MetricsBackoffSeconds,
		"LogsTimeoutSeconds":    policy.LogsTimeoutSeconds,
		"TracesTimeoutSeconds":  policy.TracesTimeoutSeconds,
		"MetricsTimeoutSeconds": policy.MetricsTimeoutSeconds,
	}
	for field, value := range floats {
		if err := validateNonNegativeFloatFinite(value, "RuntimeOverrides.Exporter."+field); err != nil {
			return err
		}
	}
	return nil
}

func validateRateFinite(v float64, field string) error {
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return NewConfigurationError(fmt.Sprintf("%s must be finite, got %g", field, v))
	}
	return validateRate(v, field)
}

func validateNonNegativeFloatFinite(v float64, field string) error {
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return NewConfigurationError(fmt.Sprintf("%s must be finite, got %g", field, v))
	}
	return validateNonNegativeFloat(v, field)
}

// _warnColdFieldDrift logs a warning if cold fields in next differ from the live config.
func _warnColdFieldDrift(next *TelemetryConfig) {
	if _runtimeCfg != nil {
		_checkColdDrift(next)
	}
}

func _checkColdDrift(next *TelemetryConfig) {
	var drifted []string
	if next.ServiceName != _runtimeCfg.ServiceName {
		drifted = append(drifted, "ServiceName")
	}
	if next.Environment != _runtimeCfg.Environment {
		drifted = append(drifted, "Environment")
	}
	if next.Version != _runtimeCfg.Version {
		drifted = append(drifted, "Version")
	}
	if next.Tracing.Enabled != _runtimeCfg.Tracing.Enabled {
		drifted = append(drifted, "Tracing.Enabled")
	}
	if next.Metrics.Enabled != _runtimeCfg.Metrics.Enabled {
		drifted = append(drifted, "Metrics.Enabled")
	}
	if len(drifted) > 0 && Logger != nil {
		Logger.Warn("runtime.cold_field_drift",
			slog.String("fields", strings.Join(drifted, ",")),
			slog.String("action", "restart required to apply"),
		)
	}
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
