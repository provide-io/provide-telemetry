// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"sync"
	"time"

	"github.com/cenkalti/backoff/v4"
	"github.com/sony/gobreaker"
)

const (
	_defaultRetries        = 3
	_defaultBackoffSeconds = 1.0
	_defaultTimeoutSeconds = 30.0
	_defaultFailOpen       = true
)

// ExporterPolicy defines resilience parameters for a signal's exporter.
type ExporterPolicy struct {
	Retries        int
	BackoffSeconds float64
	TimeoutSeconds float64
	FailOpen       bool
}

var (
	_resilienceMu      sync.RWMutex
	_exporterPolicies  = make(map[string]ExporterPolicy)
	_circuitBreakers   = make(map[string]*gobreaker.CircuitBreaker)
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

// _newCircuitBreaker creates a circuit breaker for the given signal and policy.
func _newCircuitBreaker(signal string, _ ExporterPolicy) *gobreaker.CircuitBreaker {
	settings := gobreaker.Settings{
		Name:        signal,
		MaxRequests: 1,
		Interval:    0,
		Timeout:     60 * time.Second,
		ReadyToTrip: func(counts gobreaker.Counts) bool {
			return counts.ConsecutiveFailures >= 5
		},
	}
	return gobreaker.NewCircuitBreaker(settings)
}

// SetExporterPolicy replaces the per-signal policy and circuit breaker.
func SetExporterPolicy(signal string, policy ExporterPolicy) {
	_resilienceMu.Lock()
	defer _resilienceMu.Unlock()
	_exporterPolicies[signal] = policy
	_circuitBreakers[signal] = _newCircuitBreaker(signal, policy)
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

// _getCircuitBreaker returns (or lazily creates) the circuit breaker for a signal.
// Caller must NOT hold any lock.
func _getCircuitBreaker(signal string) *gobreaker.CircuitBreaker {
	_resilienceMu.Lock()
	defer _resilienceMu.Unlock()
	if cb, ok := _circuitBreakers[signal]; ok {
		return cb
	}
	cb := _newCircuitBreaker(signal, _defaultExporterPolicy())
	_circuitBreakers[signal] = cb
	return cb
}

// RunWithResilience executes fn wrapped in a circuit breaker, retry loop, and timeout.
// On success, the appropriate success counter is incremented.
// On permanent failure, the failure counter is incremented.
// If the circuit breaker is open and FailOpen=true, the error is swallowed (returns nil).
func RunWithResilience(ctx context.Context, signal string, fn func(context.Context) error) error {
	cb := _getCircuitBreaker(signal)
	policy := GetExporterPolicy(signal)

	_, cbErr := cb.Execute(func() (interface{}, error) {
		return nil, _runWithBackoff(ctx, signal, policy, fn)
	})
	err := cbErr

	return _handleResilienceResult(signal, policy, err)
}

// _runWithBackoff runs fn under a timeout with exponential backoff retries.
func _runWithBackoff(ctx context.Context, signal string, policy ExporterPolicy, fn func(context.Context) error) error {
	timeout := time.Duration(policy.TimeoutSeconds * float64(time.Second))
	tctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	bo := backoff.NewExponentialBackOff()
	bo.InitialInterval = time.Duration(policy.BackoffSeconds * float64(time.Second))
	bor := backoff.WithMaxRetries(bo, uint64(policy.Retries)) //nolint:gosec

	var attempt int
	return backoff.Retry(func() error {
		if attempt > 0 {
			_incRetryAttempts()
		}
		attempt++
		return fn(tctx)
	}, backoff.WithContext(bor, tctx))
}

// _handleResilienceResult processes the result from cb.Execute and updates counters.
func _handleResilienceResult(signal string, policy ExporterPolicy, err error) error {
	if err == nil {
		_incExportSuccess(signal)
		return nil
	}

	if err == gobreaker.ErrOpenState || err == gobreaker.ErrTooManyRequests {
		_incCircuitBreakerTrips()
		if policy.FailOpen {
			return nil
		}
		return err
	}

	_incExportFailure(signal)
	return err
}

// _incExportSuccess increments the per-signal "exported OK" counter.
func _incExportSuccess(signal string) {
	switch signal {
	case signalLogs:
		_incLogsExportedOK()
	case signalTraces:
		_incSpansExportedOK()
	case signalMetrics:
		_incMetricsExportedOK()
	}
}

// _incExportFailure increments the per-signal export-error counter.
func _incExportFailure(signal string) {
	switch signal {
	case signalLogs:
		_incLogsExportErrors()
	case signalTraces:
		_incSpansExportErrors()
	case signalMetrics:
		_incMetricsExportErrors()
	}
}

// _resetResiliencePolicies clears all registered policies and circuit breakers (for test cleanup).
func _resetResiliencePolicies() {
	_resilienceMu.Lock()
	defer _resilienceMu.Unlock()
	_exporterPolicies = make(map[string]ExporterPolicy)
	_circuitBreakers = make(map[string]*gobreaker.CircuitBreaker)
}
