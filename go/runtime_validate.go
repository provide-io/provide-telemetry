// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Validation for runtime overrides and reconfiguration targets.
//
// Split out of runtime.go, which is at the repo's 500-line ceiling.

package telemetry

import (
	"fmt"
	"math"
)

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
		func() error {
			if overrides.Logging != nil {
				return _validateLoggingOverride(*overrides.Logging)
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

// _validateLoggingOverride validates level, format, module-level levels, and
// PIIMaxDepth on a runtime logging override. Mirrors the env-parse validation
// in config_env.go so runtime overrides cannot introduce invalid values.
func _validateLoggingOverride(l LoggingConfig) error {
	if l.Level != "" {
		if _, err := normalizeLevel(l.Level); err != nil {
			return err
		}
	}
	if l.Format != "" {
		if err := validateFormat(l.Format); err != nil {
			return err
		}
	}
	for module, levelStr := range l.ModuleLevels {
		if _, err := normalizeLevel(levelStr); err != nil {
			return NewConfigurationError(
				fmt.Sprintf("RuntimeOverrides.Logging.ModuleLevels[%q]: %s", module, err.Error()),
			)
		}
	}
	return validateNonNegative(l.PIIMaxDepth, "RuntimeOverrides.Logging.PIIMaxDepth")
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

// exporterPolicyFieldNames are the string keys used for exporter policy validation messages.
const (
	_fieldLogsRetries    = "LogsRetries"
	_fieldTracesRetries  = "TracesRetries"
	_fieldMetricsRetries = "MetricsRetries"
)

func validateExporterPolicyOverride(policy ExporterPolicyConfig) error {
	ints := map[string]int{
		_fieldLogsRetries:    policy.LogsRetries,
		_fieldTracesRetries:  policy.TracesRetries,
		_fieldMetricsRetries: policy.MetricsRetries,
	}
	for field, value := range ints {
		if err := validateRetries(value, "RuntimeOverrides.Exporter."+field); err != nil {
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
	// Zero or negative is the spec'd way to switch library-side shutdown
	// bounding off, so only the non-finite values are refused: +Inf converts
	// to a negative time.Duration — an already-expired deadline that abandons
	// every flush — and NaN to whatever the platform makes of it.
	return validateFinite(policy.LogsShutdownTimeoutSeconds, "RuntimeOverrides.Exporter.LogsShutdownTimeoutSeconds")
}

// validateFinite returns a ConfigurationError if v is NaN or infinite.
func validateFinite(v float64, field string) error {
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return NewConfigurationError(fmt.Sprintf("%s must be finite, got %g", field, v))
	}
	return nil
}

func validateRateFinite(v float64, field string) error {
	if err := validateFinite(v, field); err != nil {
		return err
	}
	return validateRate(v, field)
}

// validateNonNegativeFloatFinite rejects NaN, the infinities and negatives.
// NaN is the one a bare `v < 0` lets through — every comparison with it is
// false — and a NaN backoff or timeout then disables the very bound it set.
// Used by the env parser and the in-memory paths alike, so a value refused
// from PROVIDE_EXPORTER_* is refused from WithConfig too.
func validateNonNegativeFloatFinite(v float64, field string) error {
	if err := validateFinite(v, field); err != nil {
		return err
	}
	return validateNonNegativeFloat(v, field)
}
