// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// Package telemetry — consent-gate module.
package telemetry

import (
	"fmt"
	"os"
	"strings"
	"sync"
	"sync/atomic"

	"github.com/provide-io/provide-telemetry/go/internal/levelcore"
)

// signalContext is the signal name used for context/baggage telemetry.
const signalContext = "context"

// ConsentLevel controls how much telemetry data is collected.
type ConsentLevel int

const (
	ConsentFull       ConsentLevel = iota // All signals collected
	ConsentFunctional                     // Warnings+, traces, metrics; no context
	ConsentMinimal                        // Errors only; no traces/metrics/context
	ConsentNone                           // No telemetry collected
)

// _logLevelOrder ranks a level string for the consent gates, through the one
// shared table. An unrecognised level now ranks INFO rather than 0/TRACE; both
// sit below the WARN and ERROR gates, so no consent decision changes. FATAL
// does change: it used to be unrecognised and was dropped as if it were the
// least severe record in the ladder.
func _logLevelOrder(level string) int { return int(levelcore.Order(level)) }

// _consentEnvVar is the operator's opt-out control; LoadConsentFromEnv reads it.
const _consentEnvVar = "PROVIDE_CONSENT_LEVEL"

var (
	_consentMu    sync.RWMutex
	_consentLevel = ConsentFull
	// _consentEnvWarned is set the first time LoadConsentFromEnv sees an
	// unrecognised value, so the operator hears about it once per process
	// even though setup and the lazy logger both call the loader.
	_consentEnvWarned atomic.Bool
)

// SetConsentLevel sets the active consent level.
func SetConsentLevel(level ConsentLevel) {
	_consentMu.Lock()
	_consentLevel = level
	_consentMu.Unlock()
}

// GetConsentLevel returns the current consent level.
func GetConsentLevel() ConsentLevel {
	_consentMu.RLock()
	defer _consentMu.RUnlock()
	return _consentLevel
}

// ShouldAllow returns true if the given signal is permitted at the current consent level.
// signal is one of "logs", "traces", "metrics", "context".
// logLevel is only used when signal == "logs" (e.g., "DEBUG", "WARNING", "ERROR").
func ShouldAllow(signal string, logLevel string) bool {
	_consentMu.RLock()
	level := _consentLevel
	_consentMu.RUnlock()

	switch level {
	case ConsentFull:
		return true
	case ConsentNone:
		return false
	case ConsentFunctional:
		if signal == signalLogs {
			return _logLevelOrder(logLevel) >= int(levelcore.Warn)
		}
		if signal == signalContext {
			return false
		}
		return true
	case ConsentMinimal:
		if signal == signalLogs {
			return _logLevelOrder(logLevel) >= int(levelcore.Error)
		}
		return false
	}
	return false
}

// LoadConsentFromEnv reads PROVIDE_CONSENT_LEVEL and applies it.
//
// Called by SetupTelemetry and by the lazy pre-setup GetLogger path, so an
// operator opt-out takes effect without a code change. The value is trimmed
// and upper-cased. Unset or blank (empty or whitespace-only) is a no-op: a
// level chosen in code survives. A set, non-empty, unrecognised value fails
// closed: consent becomes ConsentNone on every call, and a warning naming the
// raw value is written to os.Stderr once per process. The variable is an
// opt-out control, and the one failure an opt-out must not have is a typo
// that silently leaves collection on.
func LoadConsentFromEnv() {
	raw := os.Getenv(_consentEnvVar)
	text := strings.ToUpper(strings.TrimSpace(raw))
	if text == "" {
		return
	}
	switch text {
	case "FULL":
		SetConsentLevel(ConsentFull)
	case "FUNCTIONAL":
		SetConsentLevel(ConsentFunctional)
	case "MINIMAL":
		SetConsentLevel(ConsentMinimal)
	case "NONE":
		SetConsentLevel(ConsentNone)
	default:
		_warnInvalidConsentEnvOnce(raw)
		SetConsentLevel(ConsentNone)
	}
}

// _warnInvalidConsentEnvOnce reports an unrecognised PROVIDE_CONSENT_LEVEL on
// os.Stderr, once per process. It deliberately bypasses Logger(): the NONE
// that fail-closed just applied would drop the record. os.Stderr is read at
// call time so tests can swap it for a pipe.
func _warnInvalidConsentEnvOnce(raw string) {
	if _consentEnvWarned.Swap(true) {
		return
	}
	message := fmt.Sprintf(
		"[provide-telemetry] %s=%q is not one of FULL, FUNCTIONAL, MINIMAL, NONE; consent set to NONE (fail-closed)",
		_consentEnvVar, raw)
	fmt.Fprintln(os.Stderr, message)
}

// ResetConsentForTests resets consent to FULL and re-arms the once-per-process
// invalid-environment warning.
func ResetConsentForTests() {
	_consentMu.Lock()
	_consentLevel = ConsentFull
	_consentMu.Unlock()
	_consentEnvWarned.Store(false)
}
