// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"sync"
	"time"
)

const (
	_defaultRetries        = 0
	_defaultBackoffSeconds = 0.0
	_defaultTimeoutSeconds = 10.0
	_defaultFailOpen       = true

	_cbThreshold   = 3
	_cbBaseCooldown = 30 * time.Second
	_cbMaxCooldown  = 1024 * time.Second
)

// ExporterPolicy defines resilience parameters for a signal's exporter.
type ExporterPolicy struct {
	Retries        int
	BackoffSeconds float64
	TimeoutSeconds float64
	FailOpen       bool
}

// CircuitState reports the current state of a signal's circuit breaker.
type CircuitState struct {
	State               string
	OpenCount           int
	CooldownRemainingMs int64
}

var (
	_resilienceMu        sync.RWMutex
	_exporterPolicies    = make(map[string]ExporterPolicy)
	_consecutiveTimeouts = make(map[string]int)
	_circuitTrippedAt    = make(map[string]time.Time)
	_openCount           = make(map[string]int)
	_halfOpenProbing     = make(map[string]bool)
)

// _defaultExporterPolicy returns the default ExporterPolicy.
func _defaultExporterPolicy() ExporterPolicy {
	return ExporterPolicy{
		Retries:        _defaultRetries,
		BackoffSeconds: _defaultBackoffSeconds,
		TimeoutSeconds: _defaultTimeoutSeconds,
		FailOpen:       _defaultFailOpen,
	}
}

// SetExporterPolicy replaces the per-signal policy.
func SetExporterPolicy(signal string, policy ExporterPolicy) {
	_resilienceMu.Lock()
	defer _resilienceMu.Unlock()
	_exporterPolicies[signal] = policy
}

// GetExporterPolicy returns the current policy for a signal.
// Returns the default policy if none is set.
func GetExporterPolicy(signal string) ExporterPolicy {
	_resilienceMu.RLock()
	defer _resilienceMu.RUnlock()
	if policy, ok := _exporterPolicies[signal]; ok {
		return policy
	}
	return _defaultExporterPolicy()
}

// _checkCircuitBreaker returns true if the circuit is OPEN (should reject).
func _checkCircuitBreaker(signal string) bool {
	_resilienceMu.Lock()
	defer _resilienceMu.Unlock()

	if !_reachedThreshold(_consecutiveTimeouts[signal], _cbThreshold) {
		return false
	}

	if _halfOpenProbing[signal] {
		return true
	}

	cooldown := min(_cbBaseCooldown*(1<<_openCount[signal]), _cbMaxCooldown)

	elapsed := time.Since(_circuitTrippedAt[signal])
	if _elapsedLessThan(elapsed, cooldown) {
		return true
	}

	_halfOpenProbing[signal] = true
	return false
}

// _recordAttemptSuccess records a successful attempt for the circuit breaker.
func _recordAttemptSuccess(signal string) {
	_resilienceMu.Lock()
	defer _resilienceMu.Unlock()

	if _halfOpenProbing[signal] {
		_halfOpenProbing[signal] = false
		_consecutiveTimeouts[signal] = 0
		_openCount[signal] = max(0, _openCount[signal]-1)
	} else {
		_consecutiveTimeouts[signal] = 0
	}
}

// _recordAttemptFailure records a failed attempt for the circuit breaker.
func _recordAttemptFailure(signal string, isTimeout bool) {
	_resilienceMu.Lock()
	defer _resilienceMu.Unlock()

	switch {
	case _halfOpenProbing[signal]:
		_halfOpenProbing[signal] = false
		_openCount[signal]++
		_circuitTrippedAt[signal] = time.Now()
	case isTimeout:
		_consecutiveTimeouts[signal]++
		if _reachedThreshold(_consecutiveTimeouts[signal], _cbThreshold) {
			_openCount[signal]++
			_circuitTrippedAt[signal] = time.Now()
		}
	default:
		_consecutiveTimeouts[signal] = 0
	}
}

// GetCircuitState returns the current circuit breaker state for a signal.
func GetCircuitState(signal string) CircuitState {
	_resilienceMu.RLock()
	defer _resilienceMu.RUnlock()

	oc := _openCount[signal]

	if _halfOpenProbing[signal] {
		return CircuitState{State: "half-open", OpenCount: oc, CooldownRemainingMs: 0}
	}

	if _reachedThreshold(_consecutiveTimeouts[signal], _cbThreshold) {
		cooldown := min(_cbBaseCooldown*(1<<oc), _cbMaxCooldown)
		elapsed := time.Since(_circuitTrippedAt[signal])
		remaining := cooldown - elapsed
		if _durationPositive(remaining) {
			return CircuitState{State: "open", OpenCount: oc, CooldownRemainingMs: remaining.Milliseconds()}
		}
		return CircuitState{State: "half-open", OpenCount: oc, CooldownRemainingMs: 0}
	}

	return CircuitState{State: "closed", OpenCount: oc, CooldownRemainingMs: 0}
}

// RunWithResilience executes fn wrapped in a circuit breaker, retry loop, and timeout.
func RunWithResilience(ctx context.Context, signal string, fn func(context.Context) error) error {
	policy := GetExporterPolicy(signal)

	attempts := max(1, policy.Retries+1)

	if _timeoutEnabled(policy.TimeoutSeconds) {
		if _checkCircuitBreaker(signal) {
			if policy.FailOpen {
				return nil
			}
			return errors.New("circuit breaker open for signal: " + signal)
		}
	}

	var lastErr error
	for attempt := 0; attempt < attempts; attempt++ {
		if attempt > 0 {
			_incRetries(signal)
			time.Sleep(_secondsToDuration(policy.BackoffSeconds))
		}

		var tctx context.Context
		var cancel context.CancelFunc
		if _timeoutEnabled(policy.TimeoutSeconds) {
			timeout := _secondsToDuration(policy.TimeoutSeconds)
			tctx, cancel = context.WithTimeout(ctx, timeout)
		} else {
			tctx = ctx
			cancel = func() {}
		}

		err := fn(tctx)
		cancel()

		if err == nil {
			_incExportSuccess(signal)
			_recordAttemptSuccess(signal)
			return nil
		}

		isTimeout := errors.Is(err, context.DeadlineExceeded)
		_incExportFailure(signal)
		_recordAttemptFailure(signal, isTimeout)
		lastErr = err
	}

	if policy.FailOpen {
		return nil
	}
	return lastErr
}

// _incExportSuccess is a no-op — success counters were removed from the canonical layout.
func _incExportSuccess(_ string) {}

// _incExportFailure increments the per-signal export-failure counter.
func _incExportFailure(signal string) {
	_incExportFailures(signal)
}

// _resetResiliencePolicies clears all registered policies and circuit breaker state (for test cleanup).
func _resetResiliencePolicies() {
	_resilienceMu.Lock()
	defer _resilienceMu.Unlock()
	_exporterPolicies = make(map[string]ExporterPolicy)
	_consecutiveTimeouts = make(map[string]int)
	_circuitTrippedAt = make(map[string]time.Time)
	_openCount = make(map[string]int)
	_halfOpenProbing = make(map[string]bool)
}
