// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"log/slog"
	"sync/atomic"
)

// A runtimeGeneration is one complete, frozen answer to "how is telemetry
// configured right now": the config and the logger built from it, published
// together under one atomic store.
//
// It exists because the emit path and the reconfiguration path met on a shared
// *TelemetryConfig. SetupTelemetry handed the very pointer it stored in
// _runtimeCfg to _configureLogger, so every live slog handler retained it, and
// ReconfigureTelemetry then wrote each hot block straight through that pointer
// with _applyHotFields. `go test -race` reported it exactly as it looks:
// _applyHotFields writing Logging/Sampling while _effectiveLevel ranged over
// Logging.ModuleLevels and applySchema read EventSchema, all with no
// synchronisation.
//
// Locking could not have fixed that without putting a mutex on every log call.
// Immutability does: a published generation is never written again, so a
// handler that captured one keeps reading a consistent snapshot for as long as
// it lives, and a reconfiguration builds an entirely new one and swaps the
// pointer. Readers see the old world or the new one, never a half-applied mix
// of endpoint-from-one and level-from-the-other.
//
// The generation number is what makes publication observable. Without it a test
// can see that values changed but not that a *new* generation was published,
// which is the property the atomicity argument actually rests on.
type runtimeGeneration struct {
	number uint64
	config *TelemetryConfig
	logger *slog.Logger
}

var (
	_activeGeneration  atomic.Pointer[runtimeGeneration] //nolint:gochecknoglobals
	_generationCounter atomic.Uint64                     //nolint:gochecknoglobals
)

// _loadGeneration returns the published generation, or nil before the first
// SetupTelemetry and after ShutdownTelemetry.
//
// The returned config and logger must be treated as read-only: they are shared
// with every other reader of this generation. Internal hot-path callers use
// this; anything handing a config outward uses loadRuntimeGeneration.
func _loadGeneration() *runtimeGeneration {
	return _activeGeneration.Load()
}

// loadRuntimeGeneration returns a snapshot whose config is safe to keep and to
// modify — the caller gets their own deep copy, so vandalising it cannot reach
// the live runtime. The logger is shared: an *slog.Logger is already immutable.
func loadRuntimeGeneration() runtimeGeneration {
	current := _activeGeneration.Load()
	if current == nil {
		return runtimeGeneration{}
	}
	return runtimeGeneration{
		number: current.number,
		config: cloneTelemetryConfig(current.config),
		logger: current.logger,
	}
}

// _publishGenerationLocked freezes cfg and the current logger into a new
// generation and swaps it in.
//
// Must be called with _setupMu held, and only after every piece of derived
// state has been built successfully: publication is the commit point, so a
// generation must never become visible while its logger or policies are still
// being assembled. cfg is stored by reference and must not be written again
// afterwards — every caller reaches here holding a clone it alone can see.
func _publishGenerationLocked(cfg *TelemetryConfig) {
	_runtimeCfg = cfg
	_publishRuntimeGatesLocked()
	_activeGeneration.Store(&runtimeGeneration{
		number: _generationCounter.Add(1),
		config: cfg,
		logger: _activeLogger.Load(),
	})
}

// _clearGenerationLocked retires the active generation. Handlers already built
// from it keep working against their own frozen copy; only new lookups see the
// absence.
func _clearGenerationLocked() {
	_runtimeCfg = nil
	_publishRuntimeGatesLocked()
	_activeGeneration.Store(nil)
}

// Logger returns the currently configured logger, or nil before any setup and
// after shutdown.
//
// This was an assignable `var Logger *slog.Logger` until it proved impossible
// to make race-free: reconfiguration rewrote it while readers read it, and the
// go/otel module assigned it from another package entirely. Keeping the
// canonical spec name and moving one pair of parentheses costs callers a
// character and buys a value that cannot be torn.
func Logger() *slog.Logger {
	return _activeLogger.Load()
}

// _activeLogger holds the configured logger.
//
// This used to be an exported `var Logger *slog.Logger` that _configureLogger
// reassigned on every setup and reconfiguration, which the race detector
// reported exactly as it looks: GetLogger read it while that write was in
// flight. A package variable cannot be both publicly assignable and race-free,
// so it is gone — Logger() is the only way to reach the logger, and the
// pointer below is the only place it lives.
var _activeLogger atomic.Pointer[slog.Logger] //nolint:gochecknoglobals

// SetLogger installs l as the logger Logger returns.
//
// The write half of the pair. Callers wanting a custom sink — test harnesses,
// probes — use this; callers wanting a named logger over the configured
// pipeline use GetLogger.
//
// The next setup or reconfiguration rebuilds the logger and overwrites this.
func SetLogger(l *slog.Logger) {
	_activeLogger.Store(l)
}
