// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"log/slog"
	"maps"
)

// _processStateSnapshot is everything SetupTelemetry writes into process-wide
// state before it knows whether backend wiring will succeed.
//
// Setup cannot simply defer those writes: the backend asks for Providers() and
// wraps Logger() with its bridge, so policies, the logger and the sink must
// already be in place when it runs. What it can do is remember what was there.
// Without this, a setup that failed — provider options with no backend
// registered, an OTLP exporter that would not build — returned an error while
// leaving its consent level, sampling rates, queue sizes, exporter policies,
// strict-schema flag, slog default and log writer installed, and the host was
// left running a configuration it had been told was rejected.
type _processStateSnapshot struct {
	sampling        map[string]SamplingPolicy
	queuePolicy     QueuePolicy
	logsQueue       chan struct{}
	tracesQueue     chan struct{}
	metricsQueue    chan struct{}
	exporter        map[string]ExporterPolicy
	strictSchema    bool
	consent         ConsentLevel
	logger          *slog.Logger
	slogDefault     *slog.Logger
	preTelemetry    *slog.Logger
	logSink         *_logSink
	consolePrepared bool
}

// _captureProcessState records the state SetupTelemetry is about to overwrite.
//
// The queue channels are kept, not just their sizes: a ticket acquired before
// setup releases into the channel it came from, and rebuilding fresh channels
// on rollback would hand out a full new budget while those tickets were still
// held.
func _captureProcessState() *_processStateSnapshot {
	snap := &_processStateSnapshot{
		strictSchema: _readStrictSchema(),
		consent:      GetConsentLevel(),
		logger:       Logger(),
		slogDefault:  slog.Default(),
		preTelemetry: _preTelemetryLogger,
		logSink:      _activeLogSink.Load(),
	}

	_samplingMu.RLock()
	snap.sampling = maps.Clone(_samplingPolicies)
	_samplingMu.RUnlock()

	_queueMu.RLock()
	snap.queuePolicy = _queuePolicy
	snap.logsQueue, snap.tracesQueue, snap.metricsQueue = _logsQueue, _tracesQueue, _metricsQueue
	_queueMu.RUnlock()

	_resilienceMu.RLock()
	snap.exporter = maps.Clone(_exporterPolicies)
	_resilienceMu.RUnlock()

	_consoleGuard.mu.Lock()
	snap.consolePrepared = _consoleGuard.restore != nil
	_consoleGuard.mu.Unlock()
	return snap
}

// _restoreProcessState puts back exactly what _captureProcessState saw.
func (snap *_processStateSnapshot) _restoreProcessState() {
	_samplingMu.Lock()
	_samplingPolicies = snap.sampling
	_samplingMu.Unlock()

	_queueMu.Lock()
	_queuePolicy = snap.queuePolicy
	_logsQueue, _tracesQueue, _metricsQueue = snap.logsQueue, snap.tracesQueue, snap.metricsQueue
	_queueMu.Unlock()

	_resilienceMu.Lock()
	_exporterPolicies = snap.exporter
	_resilienceMu.Unlock()

	SetStrictSchema(snap.strictSchema)
	SetConsentLevel(snap.consent)

	SetLogger(snap.logger)
	slog.SetDefault(snap.slogDefault)
	_preTelemetryLogger = snap.preTelemetry
	_activeLogSink.Store(snap.logSink)

	// Only a preparation this setup made is undone: one already in place
	// belongs to an earlier owner, which still expects it.
	if !snap.consolePrepared {
		_restoreLogConsole()
	}
}
