// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"math"
	"sync/atomic"
)

// HealthSnapshot holds point-in-time counters for all telemetry signals.
// The canonical layout has 25 fields: 8 per signal (logs, traces, metrics)
// plus 1 global field (SetupError).
type HealthSnapshot struct {
	// Logs (8 fields)
	LogsEmitted           int64
	LogsDropped           int64
	LogsExportFailures    int64
	LogsRetries           int64
	LogsExportLatencyMs   float64
	LogsAsyncBlockingRisk int64
	LogsCircuitState      string
	LogsCircuitOpenCount  int64

	// Traces (8 fields)
	TracesEmitted           int64
	TracesDropped           int64
	TracesExportFailures    int64
	TracesRetries           int64
	TracesExportLatencyMs   float64
	TracesAsyncBlockingRisk int64
	TracesCircuitState      string
	TracesCircuitOpenCount  int64

	// Metrics (8 fields)
	MetricsEmitted           int64
	MetricsDropped           int64
	MetricsExportFailures    int64
	MetricsRetries           int64
	MetricsExportLatencyMs   float64
	MetricsAsyncBlockingRisk int64
	MetricsCircuitState      string
	MetricsCircuitOpenCount  int64

	// Global (1 field)
	SetupError string
}

// _signalHealthCounters holds lock-free per-signal counters.
// Each field is an atomic value; no mutex is needed for increments or reads.
// latencyMs stores the IEEE-754 bits of the latest float64 via math.Float64bits.
type _signalHealthCounters struct {
	emitted        atomic.Int64
	dropped        atomic.Int64
	exportFailures atomic.Int64
	retries        atomic.Int64
	asyncBlocking  atomic.Int64
	latencyMs      atomic.Uint64 // math.Float64bits of latest latency
}

func (c *_signalHealthCounters) reset() {
	c.emitted.Store(0)
	c.dropped.Store(0)
	c.exportFailures.Store(0)
	c.retries.Store(0)
	c.asyncBlocking.Store(0)
	c.latencyMs.Store(0)
}

func (c *_signalHealthCounters) loadLatencyMs() float64 {
	return math.Float64frombits(c.latencyMs.Load())
}

var (
	_healthLogs       _signalHealthCounters
	_healthTraces     _signalHealthCounters
	_healthMetrics    _signalHealthCounters
	_setupErrorHealth atomic.Value // always stores string
)

// _healthFor returns the counter set for the given signal.
func _healthFor(signal string) *_signalHealthCounters {
	switch signal {
	case signalTraces:
		return &_healthTraces
	case signalMetrics:
		return &_healthMetrics
	default:
		return &_healthLogs
	}
}

// GetHealthSnapshot returns a point-in-time copy of the health counters,
// integrating live circuit breaker state from the resilience module.
func GetHealthSnapshot() HealthSnapshot {
	logsCS := GetCircuitState(signalLogs)
	tracesCS := GetCircuitState(signalTraces)
	metricsCS := GetCircuitState(signalMetrics)

	setupErr, _ := _setupErrorHealth.Load().(string)
	return HealthSnapshot{
		LogsEmitted:           _healthLogs.emitted.Load(),
		LogsDropped:           _healthLogs.dropped.Load(),
		LogsExportFailures:    _healthLogs.exportFailures.Load(),
		LogsRetries:           _healthLogs.retries.Load(),
		LogsExportLatencyMs:   _healthLogs.loadLatencyMs(),
		LogsAsyncBlockingRisk: _healthLogs.asyncBlocking.Load(),
		LogsCircuitState:      logsCS.State,
		LogsCircuitOpenCount:  int64(logsCS.OpenCount),

		TracesEmitted:           _healthTraces.emitted.Load(),
		TracesDropped:           _healthTraces.dropped.Load(),
		TracesExportFailures:    _healthTraces.exportFailures.Load(),
		TracesRetries:           _healthTraces.retries.Load(),
		TracesExportLatencyMs:   _healthTraces.loadLatencyMs(),
		TracesAsyncBlockingRisk: _healthTraces.asyncBlocking.Load(),
		TracesCircuitState:      tracesCS.State,
		TracesCircuitOpenCount:  int64(tracesCS.OpenCount),

		MetricsEmitted:           _healthMetrics.emitted.Load(),
		MetricsDropped:           _healthMetrics.dropped.Load(),
		MetricsExportFailures:    _healthMetrics.exportFailures.Load(),
		MetricsRetries:           _healthMetrics.retries.Load(),
		MetricsExportLatencyMs:   _healthMetrics.loadLatencyMs(),
		MetricsAsyncBlockingRisk: _healthMetrics.asyncBlocking.Load(),
		MetricsCircuitState:      metricsCS.State,
		MetricsCircuitOpenCount:  int64(metricsCS.OpenCount),

		SetupError: setupErr,
	}
}

// _incEmitted increments the emitted counter for the given signal.
func _incEmitted(signal string) { _healthFor(signal).emitted.Add(1) }

// _incDroppedHealth increments the dropped counter for the given signal.
func _incDroppedHealth(signal string) { _healthFor(signal).dropped.Add(1) }

// _incExportFailures increments the export failure counter for the given signal.
func _incExportFailures(signal string) { _healthFor(signal).exportFailures.Add(1) }

// _incRetries increments the retry counter for the given signal.
func _incRetries(signal string) { _healthFor(signal).retries.Add(1) }

// _recordExportLatencyForSignal records the latest export latency for a signal.
func _recordExportLatencyForSignal(signal string, ms float64) {
	_healthFor(signal).latencyMs.Store(math.Float64bits(ms))
}

// _incAsyncBlockingRisk increments the async blocking risk counter for a signal.
func _incAsyncBlockingRisk(signal string) { _healthFor(signal).asyncBlocking.Add(1) }

// _setSetupError records a setup-time error message.
func _setSetupError(msg string) { _setupErrorHealth.Store(msg) }

// Backward-compatible wrappers — used by sampling, backpressure, and resilience.

func _incLogsEmitted()         { _healthLogs.emitted.Add(1) }
func _incLogsDropped()         { _healthLogs.dropped.Add(1) }
func _incSpansStarted()        { _healthTraces.emitted.Add(1) }
func _incSpansDropped()        { _healthTraces.dropped.Add(1) }
func _incMetricsRecorded()     { _healthMetrics.emitted.Add(1) }
func _incMetricsDropped()      { _healthMetrics.dropped.Add(1) }
func _incLogsExportErrors()    { _healthLogs.exportFailures.Add(1) }
func _incSpansExportErrors()   { _healthTraces.exportFailures.Add(1) }
func _incMetricsExportErrors() { _healthMetrics.exportFailures.Add(1) }

func _resetHealth() {
	_healthLogs.reset()
	_healthTraces.reset()
	_healthMetrics.reset()
	_setupErrorHealth.Store("")
}
