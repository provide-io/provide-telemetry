// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import "sync"

const _defaultQueueSize = 0

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

// _buildQueue returns a buffered channel of the given size, or nil for unlimited (size <= 0).
func _buildQueue(size int) chan struct{} {
	if size <= 0 {
		return nil
	}
	return make(chan struct{}, size)
}

// _resetQueuePolicy rebuilds all queues with default sizes.
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
// Old channels are abandoned (not closed) to prevent a TOCTOU panic: TryAcquire
// and Release read the channel pointer under RLock then release the lock before
// the channel operation, so closing the old channel here could race with a
// concurrent send/receive on the now-stale pointer.
// Caller must hold _queueMu write lock.
func _drainAndRebuild(policy QueuePolicy) {
	// Intentionally do not close old channels — let them be GC'd once all
	// in-flight references drop.
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
// A maxSize of 0 (or negative) means unlimited — always succeeds without a channel.
func TryAcquire(signal string) bool {
	_queueMu.RLock()
	policy := _queuePolicy
	ch := _channelForSignal(signal)
	_queueMu.RUnlock()

	maxSize := 0
	switch signal {
	case signalLogs:
		maxSize = policy.LogsMaxSize
	case signalTraces:
		maxSize = policy.TracesMaxSize
	case signalMetrics:
		maxSize = policy.MetricsMaxSize
	default:
		return false
	}
	if maxSize <= 0 {
		_incAcquired(signal)
		return true
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

// Release frees one slot on the signal's semaphore. No-op for unknown signals or unlimited queues.
func Release(signal string) {
	_queueMu.RLock()
	policy := _queuePolicy
	ch := _channelForSignal(signal)
	_queueMu.RUnlock()

	maxSize := 0
	switch signal {
	case signalLogs:
		maxSize = policy.LogsMaxSize
	case signalTraces:
		maxSize = policy.TracesMaxSize
	case signalMetrics:
		maxSize = policy.MetricsMaxSize
	}
	if maxSize <= 0 || ch == nil {
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
