// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import "sync"

const _defaultQueueSize = 1000

// QueuePolicy defines per-signal maximum in-flight queue sizes.
type QueuePolicy struct {
	LogsMaxSize    int
	TracesMaxSize  int
	MetricsMaxSize int
}

var (
	_queueMu      sync.RWMutex
	_queuePolicy  QueuePolicy
	_logsQueue    chan struct{}
	_tracesQueue  chan struct{}
	_metricsQueue chan struct{}
)

func init() {
	_resetQueuePolicy()
}

// _buildQueue returns a buffered channel of the given size (minimum 1).
func _buildQueue(size int) chan struct{} {
	if size < 1 {
		size = 1
	}
	return make(chan struct{}, size)
}

// _resetQueuePolicy closes existing channels and rebuilds with default sizes.
// Must be called with no lock held.
func _resetQueuePolicy() {
	_queueMu.Lock()
	defer _queueMu.Unlock()
	_drainAndRebuild(
		QueuePolicy{
			LogsMaxSize:    _defaultQueueSize,
			TracesMaxSize:  _defaultQueueSize,
			MetricsMaxSize: _defaultQueueSize,
		},
	)
}

// _drainAndRebuild replaces all queues with new channels based on policy.
// Caller must hold _queueMu write lock.
func _drainAndRebuild(policy QueuePolicy) {
	if _logsQueue != nil {
		close(_logsQueue)
	}
	if _tracesQueue != nil {
		close(_tracesQueue)
	}
	if _metricsQueue != nil {
		close(_metricsQueue)
	}
	_queuePolicy = policy
	_logsQueue = _buildQueue(policy.LogsMaxSize)
	_tracesQueue = _buildQueue(policy.TracesMaxSize)
	_metricsQueue = _buildQueue(policy.MetricsMaxSize)
}

// SetQueuePolicy replaces the semaphore channels with new sizes.
func SetQueuePolicy(policy QueuePolicy) {
	_queueMu.Lock()
	defer _queueMu.Unlock()
	_drainAndRebuild(policy)
}

// GetQueuePolicy returns the current policy under read lock.
func GetQueuePolicy() QueuePolicy {
	_queueMu.RLock()
	defer _queueMu.RUnlock()
	return _queuePolicy
}

// _channelForSignal returns the channel for the given signal, or nil for unknown signals.
// Caller must hold at least a read lock.
func _channelForSignal(signal string) chan struct{} {
	switch signal {
	case signalLogs:
		return _logsQueue
	case signalTraces:
		return _tracesQueue
	case signalMetrics:
		return _metricsQueue
	default:
		return nil
	}
}

// TryAcquire attempts a non-blocking acquire on the signal's semaphore.
// Returns true if a slot was acquired; false if the queue is at capacity or the signal is unknown.
func TryAcquire(signal string) bool {
	_queueMu.RLock()
	ch := _channelForSignal(signal)
	_queueMu.RUnlock()

	if ch == nil {
		return false
	}

	select {
	case ch <- struct{}{}:
		_incAcquired(signal)
		return true
	default:
		_incDropped(signal)
		return false
	}
}

// Release frees one slot on the signal's semaphore. No-op for unknown signals.
func Release(signal string) {
	_queueMu.RLock()
	ch := _channelForSignal(signal)
	_queueMu.RUnlock()

	if ch == nil {
		return
	}

	select {
	case <-ch:
	default:
	}
}

// _incAcquired increments the appropriate "emitted/started/recorded" counter.
func _incAcquired(signal string) {
	switch signal {
	case signalLogs:
		_incLogsEmitted()
	case signalTraces:
		_incSpansStarted()
	case signalMetrics:
		_incMetricsRecorded()
	}
}

// _incDropped increments the appropriate "dropped" counter.
func _incDropped(signal string) {
	switch signal {
	case signalLogs:
		_incLogsDropped()
	case signalTraces:
		_incSpansDropped()
	case signalMetrics:
		_incMetricsDropped()
	}
}
