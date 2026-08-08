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
		logger: _loadActiveLogger(),
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

// DefaultLogger returns the currently configured logger, or nil before any
// setup.
//
// Prefer this to reading the exported Logger variable from concurrent code: a
// package variable that reconfiguration reassigns cannot be read safely while
// it is being written, and the race detector says so. Logger remains for
// existing callers and single-threaded use.
func DefaultLogger() *slog.Logger {
	return _activeLogger.Load()
}

// _activeLogger mirrors the exported Logger variable as an atomic pointer.
//
// Logger has always been a plain package variable that _configureLogger
// reassigns on every setup and reconfiguration. Reading it from GetLogger while
// that write was in flight is a data race, and the detector reported it as one.
// Every internal read now goes through this pointer instead; Logger is still
// assigned in lockstep so existing callers see no change.
var _activeLogger atomic.Pointer[slog.Logger] //nolint:gochecknoglobals

// _setActiveLogger installs l as both the exported variable and the atomic
// internal reads use. Called with _setupMu held.
func _setActiveLogger(l *slog.Logger) {
	Logger = l
	_activeLogger.Store(l)
}

// _loadActiveLogger returns the configured logger without reading the exported
// variable, or nil when none has been configured.
func _loadActiveLogger() *slog.Logger {
	return _activeLogger.Load()
}
