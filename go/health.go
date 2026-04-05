// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import "sync"

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

var (
	_healthMu          sync.Mutex
	_emitted           = map[string]int64{signalLogs: 0, signalTraces: 0, signalMetrics: 0}
	_dropped           = map[string]int64{signalLogs: 0, signalTraces: 0, signalMetrics: 0}
	_exportFailures    = map[string]int64{signalLogs: 0, signalTraces: 0, signalMetrics: 0}
	_retries           = map[string]int64{signalLogs: 0, signalTraces: 0, signalMetrics: 0}
	_exportLatencyMs   = map[string]float64{signalLogs: 0, signalTraces: 0, signalMetrics: 0}
	_asyncBlockingRisk = map[string]int64{signalLogs: 0, signalTraces: 0, signalMetrics: 0}
	_setupErrorHealth  string
)

// GetHealthSnapshot returns a point-in-time copy of the health counters,
// integrating live circuit breaker state from the resilience module.
func GetHealthSnapshot() HealthSnapshot {
	logsCS := GetCircuitState(signalLogs)
	tracesCS := GetCircuitState(signalTraces)
	metricsCS := GetCircuitState(signalMetrics)

	_healthMu.Lock()
	defer _healthMu.Unlock()
	return HealthSnapshot{
		LogsEmitted:           _emitted[signalLogs],
		LogsDropped:           _dropped[signalLogs],
		LogsExportFailures:    _exportFailures[signalLogs],
		LogsRetries:           _retries[signalLogs],
		LogsExportLatencyMs:   _exportLatencyMs[signalLogs],
		LogsAsyncBlockingRisk: _asyncBlockingRisk[signalLogs],
		LogsCircuitState:      logsCS.State,
		LogsCircuitOpenCount:  int64(logsCS.OpenCount),

		TracesEmitted:           _emitted[signalTraces],
		TracesDropped:           _dropped[signalTraces],
		TracesExportFailures:    _exportFailures[signalTraces],
		TracesRetries:           _retries[signalTraces],
		TracesExportLatencyMs:   _exportLatencyMs[signalTraces],
		TracesAsyncBlockingRisk: _asyncBlockingRisk[signalTraces],
		TracesCircuitState:      tracesCS.State,
		TracesCircuitOpenCount:  int64(tracesCS.OpenCount),

		MetricsEmitted:           _emitted[signalMetrics],
		MetricsDropped:           _dropped[signalMetrics],
		MetricsExportFailures:    _exportFailures[signalMetrics],
		MetricsRetries:           _retries[signalMetrics],
		MetricsExportLatencyMs:   _exportLatencyMs[signalMetrics],
		MetricsAsyncBlockingRisk: _asyncBlockingRisk[signalMetrics],
		MetricsCircuitState:      metricsCS.State,
		MetricsCircuitOpenCount:  int64(metricsCS.OpenCount),

		SetupError: _setupErrorHealth,
	}
}

// _incEmitted increments the emitted counter for the given signal.
func _incEmitted(signal string) {
	_healthMu.Lock()
	_emitted[signal]++
	_healthMu.Unlock()
}

// _incDroppedHealth increments the dropped counter for the given signal.
func _incDroppedHealth(signal string) {
	_healthMu.Lock()
	_dropped[signal]++
	_healthMu.Unlock()
}

// _incExportFailures increments the export failure counter for the given signal.
func _incExportFailures(signal string) {
	_healthMu.Lock()
	_exportFailures[signal]++
	_healthMu.Unlock()
}

// _incRetries increments the retry counter for the given signal.
func _incRetries(signal string) {
	_healthMu.Lock()
	_retries[signal]++
	_healthMu.Unlock()
}

// _recordExportLatencyForSignal records the latest export latency for a signal.
func _recordExportLatencyForSignal(signal string, ms float64) {
	_healthMu.Lock()
	_exportLatencyMs[signal] = ms
	_healthMu.Unlock()
}

// _incAsyncBlockingRisk increments the async blocking risk counter for a signal.
func _incAsyncBlockingRisk(signal string) {
	_healthMu.Lock()
	_asyncBlockingRisk[signal]++
	_healthMu.Unlock()
}

// _setSetupError records a setup-time error message.
func _setSetupError(msg string) {
	_healthMu.Lock()
	_setupErrorHealth = msg
	_healthMu.Unlock()
}

// Backward-compatible wrappers — used by sampling, backpressure, and resilience.

func _incLogsEmitted()      { _incEmitted(signalLogs) }
func _incLogsDropped()       { _incDroppedHealth(signalLogs) }
func _incSpansStarted()      { _incEmitted(signalTraces) }
func _incSpansDropped()      { _incDroppedHealth(signalTraces) }
func _incMetricsRecorded()   { _incEmitted(signalMetrics) }
func _incMetricsDropped()    { _incDroppedHealth(signalMetrics) }
func _incLogsExportErrors()  { _incExportFailures(signalLogs) }
func _incSpansExportErrors() { _incExportFailures(signalTraces) }
func _incMetricsExportErrors() { _incExportFailures(signalMetrics) }

func _resetHealth() {
	_healthMu.Lock()
	_emitted = map[string]int64{signalLogs: 0, signalTraces: 0, signalMetrics: 0}
	_dropped = map[string]int64{signalLogs: 0, signalTraces: 0, signalMetrics: 0}
	_exportFailures = map[string]int64{signalLogs: 0, signalTraces: 0, signalMetrics: 0}
	_retries = map[string]int64{signalLogs: 0, signalTraces: 0, signalMetrics: 0}
	_exportLatencyMs = map[string]float64{signalLogs: 0, signalTraces: 0, signalMetrics: 0}
	_asyncBlockingRisk = map[string]int64{signalLogs: 0, signalTraces: 0, signalMetrics: 0}
	_setupErrorHealth = ""
	_healthMu.Unlock()
}
