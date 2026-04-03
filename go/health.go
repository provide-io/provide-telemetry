// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import "sync"

// HealthSnapshot holds point-in-time counters for all telemetry signals.
type HealthSnapshot struct {
	// Logging counters
	LogsEmitted      int64
	LogsDropped      int64
	LogsExportErrors int64
	LogsExportedOK   int64

	// Tracing counters
	SpansStarted      int64
	SpansDropped      int64
	SpansExportErrors int64
	SpansExportedOK   int64

	// Metrics counters
	MetricsRecorded     int64
	MetricsDropped      int64
	MetricsExportErrors int64
	MetricsExportedOK   int64

	// Resilience counters
	CircuitBreakerTrips int64
	RetryAttempts       int64
	ExportLatencyMs     int64 // cumulative; divide by exported count for avg

	// Setup state
	SetupCount    int64
	ShutdownCount int64
	LastError     string // last error message, "" if none
}

var (
	_healthMu sync.Mutex
	_health   HealthSnapshot
)

// GetHealthSnapshot returns a point-in-time copy of the health counters.
func GetHealthSnapshot() HealthSnapshot {
	_healthMu.Lock()
	defer _healthMu.Unlock()
	return _health
}

func _incLogsEmitted() {
	_healthMu.Lock()
	_health.LogsEmitted++
	_healthMu.Unlock()
}

func _incLogsDropped() {
	_healthMu.Lock()
	_health.LogsDropped++
	_healthMu.Unlock()
}

func _incLogsExportErrors() {
	_healthMu.Lock()
	_health.LogsExportErrors++
	_healthMu.Unlock()
}

func _incLogsExportedOK() {
	_healthMu.Lock()
	_health.LogsExportedOK++
	_healthMu.Unlock()
}

func _incSpansStarted() {
	_healthMu.Lock()
	_health.SpansStarted++
	_healthMu.Unlock()
}

func _incSpansDropped() {
	_healthMu.Lock()
	_health.SpansDropped++
	_healthMu.Unlock()
}

func _incSpansExportErrors() {
	_healthMu.Lock()
	_health.SpansExportErrors++
	_healthMu.Unlock()
}

func _incSpansExportedOK() {
	_healthMu.Lock()
	_health.SpansExportedOK++
	_healthMu.Unlock()
}

func _incMetricsRecorded() {
	_healthMu.Lock()
	_health.MetricsRecorded++
	_healthMu.Unlock()
}

func _incMetricsDropped() {
	_healthMu.Lock()
	_health.MetricsDropped++
	_healthMu.Unlock()
}

func _incMetricsExportErrors() {
	_healthMu.Lock()
	_health.MetricsExportErrors++
	_healthMu.Unlock()
}

func _incMetricsExportedOK() {
	_healthMu.Lock()
	_health.MetricsExportedOK++
	_healthMu.Unlock()
}

func _incCircuitBreakerTrips() {
	_healthMu.Lock()
	_health.CircuitBreakerTrips++
	_healthMu.Unlock()
}

func _incRetryAttempts() {
	_healthMu.Lock()
	_health.RetryAttempts++
	_healthMu.Unlock()
}

func _addExportLatency(ms int64) {
	_healthMu.Lock()
	_health.ExportLatencyMs += ms
	_healthMu.Unlock()
}

func _incSetupCount() {
	_healthMu.Lock()
	_health.SetupCount++
	_healthMu.Unlock()
}

func _incShutdownCount() {
	_healthMu.Lock()
	_health.ShutdownCount++
	_healthMu.Unlock()
}

func _setLastError(msg string) {
	_healthMu.Lock()
	_health.LastError = msg
	_healthMu.Unlock()
}

func _resetHealth() {
	_healthMu.Lock()
	_health = HealthSnapshot{}
	_healthMu.Unlock()
}
