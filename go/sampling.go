// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"fmt"
	"sync"
)

const (
	signalLogs    = "logs"
	signalTraces  = "traces"
	signalMetrics = "metrics"
)

// _validSignals is the set of allowed signal names.
var _validSignals = map[string]struct{}{
	signalLogs:    {},
	signalTraces:  {},
	signalMetrics: {},
}

// _validateSignal returns a ConfigurationError if signal is not in the valid set.
func _validateSignal(signal string) error {
	if _, ok := _validSignals[signal]; !ok {
		return NewConfigurationError(
			fmt.Sprintf("unknown signal %q, expected one of [logs, metrics, traces]", signal),
		)
	}
	return nil
}

// SamplingPolicy defines per-signal sampling configuration.
type SamplingPolicy struct {
	DefaultRate float64            // probability [0.0, 1.0]; default 1.0 = sample all
	Overrides   map[string]float64 // key-specific rate overrides
}

// Package-level state: one policy per signal, protected by RWMutex.
var (
	_samplingMu       sync.RWMutex
	_samplingPolicies = make(map[string]SamplingPolicy) // keyed by signal: "logs", "traces", "metrics"
)

// SetSamplingPolicy registers a sampling policy for a signal.
// signal must be "logs", "traces", or "metrics"; other values return a ConfigurationError.
// DefaultRate is clamped to [0.0, 1.0].
func SetSamplingPolicy(signal string, policy SamplingPolicy) (SamplingPolicy, error) {
	if err := _validateSignal(signal); err != nil {
		return SamplingPolicy{}, err
	}
	if policy.DefaultRate < 0.0 {
		policy.DefaultRate = 0.0
	} else if policy.DefaultRate > 1.0 {
		policy.DefaultRate = 1.0
	}
	if len(policy.Overrides) > 0 {
		clamped := make(map[string]float64, len(policy.Overrides))
		for k, v := range policy.Overrides {
			clamped[k] = max(0.0, min(1.0, v))
		}
		policy.Overrides = clamped
	}
	_samplingMu.Lock()
	defer _samplingMu.Unlock()
	_samplingPolicies[signal] = policy
	return policy, nil
}

// GetSamplingPolicy returns the current policy for a signal.
// Returns SamplingPolicy{DefaultRate: 1.0} if no policy is set.
// signal must be "logs", "traces", or "metrics"; other values return a ConfigurationError.
func GetSamplingPolicy(signal string) (SamplingPolicy, error) {
	if err := _validateSignal(signal); err != nil {
		return SamplingPolicy{}, err
	}
	_samplingMu.RLock()
	defer _samplingMu.RUnlock()
	if policy, ok := _samplingPolicies[signal]; ok {
		return policy, nil
	}
	return SamplingPolicy{DefaultRate: 1.0}, nil
}

// ShouldSample returns true if the given key (usually event name or span name)
// should be sampled for the given signal, based on the registered policy.
//
// Fast paths:
//   - rate == 0.0: always return false (drop all)
//   - rate == 1.0: always return true (keep all)
//   - otherwise: rand.Float64() < rate
//
// Key lookup: if policy.Overrides[key] exists, use that rate; otherwise use DefaultRate.
func ShouldSample(signal, key string) (bool, error) {
	policy, err := GetSamplingPolicy(signal)
	if err != nil {
		return false, err
	}

	rate := policy.DefaultRate
	if policy.Overrides != nil {
		if override, ok := policy.Overrides[key]; ok {
			rate = override
		}
	}

	var sampled bool
	switch rate {
	case 0.0:
		sampled = false
	case 1.0:
		sampled = true
	default:
		sampled = _rollBelowRate(rate)
	}

	_recordSampleDecision(signal, sampled)

	return sampled, nil
}

// _recordSampleDecision increments the appropriate counter based on the signal and sampling outcome.
func _recordSampleDecision(signal string, sampled bool) {
	if sampled {
		switch signal {
		case signalLogs:
			_incLogsEmitted()
		case signalTraces:
			_incSpansStarted()
		case signalMetrics:
			_incMetricsRecorded()
		}
	} else {
		switch signal {
		case signalLogs:
			_incLogsDropped()
		case signalTraces:
			_incSpansDropped()
		case signalMetrics:
			_incMetricsDropped()
		}
	}
}

// _resetSamplingPolicies clears all registered sampling policies (for test cleanup).
func _resetSamplingPolicies() {
	_samplingMu.Lock()
	defer _samplingMu.Unlock()
	_samplingPolicies = make(map[string]SamplingPolicy)
}
