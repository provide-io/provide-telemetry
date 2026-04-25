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

// QueueTicket represents one acquired backpressure slot.
// Release the returned ticket to free the exact queue slot that was acquired.
type QueueTicket struct {
	signal string
	ch     chan struct{}
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
// Old channels are abandoned (not closed) to prevent a panic: closing a channel
// while a concurrent sender holds a stale pointer to it would panic. GC reclaims
// the old channel once all in-flight references drop.
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

// _queueForSignal returns the configured max size and current channel for a signal.
// Caller must hold at least a read lock.
func _queueForSignal(signal string) (int, chan struct{}, bool) {
	switch signal {
	case signalLogs:
		return _queuePolicy.LogsMaxSize, _logsQueue, true
	case signalTraces:
		return _queuePolicy.TracesMaxSize, _tracesQueue, true
	case signalMetrics:
		return _queuePolicy.MetricsMaxSize, _metricsQueue, true
	default:
		return 0, nil, false
	}
}

// TryAcquire attempts a non-blocking acquire on the signal's semaphore.
// Returns a ticket if a slot was acquired, or nil if the queue is at capacity
// or the signal is unknown. A maxSize of 0 (or negative) means unlimited:
// acquisition succeeds with a ticket that does not hold a channel slot.
// The RLock is held through the entire read + send to prevent a TOCTOU race where
// SetQueuePolicy swaps the channel pointer between the read and the send.
func TryAcquire(signal string) *QueueTicket {
	_queueMu.RLock()
	defer _queueMu.RUnlock()

	maxSize, ch, ok := _queueForSignal(signal)
	if !ok {
		return nil
	}
	if maxSize <= 0 {
		return &QueueTicket{signal: signal}
	}

	select {
	case ch <- struct{}{}:
		return &QueueTicket{signal: signal, ch: ch}
	default:
		_incDropped(signal)
		return nil
	}
}

// Release frees the exact queue slot represented by ticket.
// It is a no-op for nil tickets and unlimited queues.
func Release(ticket *QueueTicket) {
	if ticket == nil || ticket.ch == nil {
		return
	}

	select {
	case <-ticket.ch:
	default:
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
