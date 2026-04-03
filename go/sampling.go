// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"math/rand"
	"sync"
)

const (
	signalLogs    = "logs"
	signalTraces  = "traces"
	signalMetrics = "metrics"
)

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
// signal should be "logs", "traces", or "metrics".
func SetSamplingPolicy(signal string, policy SamplingPolicy) {
	_samplingMu.Lock()
	defer _samplingMu.Unlock()
	_samplingPolicies[signal] = policy
}

// GetSamplingPolicy returns the current policy for a signal.
// Returns SamplingPolicy{DefaultRate: 1.0} if no policy is set.
func GetSamplingPolicy(signal string) SamplingPolicy {
	_samplingMu.RLock()
	defer _samplingMu.RUnlock()
	if policy, ok := _samplingPolicies[signal]; ok {
		return policy
	}
	return SamplingPolicy{DefaultRate: 1.0}
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
func ShouldSample(signal, key string) bool {
	policy := GetSamplingPolicy(signal)

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
		sampled = rand.Float64() < rate // #nosec G404 -- probabilistic sampling; crypto/rand not required
	}

	_recordSampleDecision(signal, sampled)

	return sampled
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
