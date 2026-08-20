// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// Package telemetry — consent-gate module.
package telemetry

import (
	"os"
	"strings"
	"sync"

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

var (
	_consentMu    sync.RWMutex
	_consentLevel = ConsentFull
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

// LoadConsentFromEnv reads PROVIDE_CONSENT_LEVEL and sets the consent level.
func LoadConsentFromEnv() {
	raw := strings.TrimSpace(strings.ToUpper(os.Getenv("PROVIDE_CONSENT_LEVEL")))
	switch raw {
	case "FULL":
		SetConsentLevel(ConsentFull)
	case "FUNCTIONAL":
		SetConsentLevel(ConsentFunctional)
	case "MINIMAL":
		SetConsentLevel(ConsentMinimal)
	case "NONE":
		SetConsentLevel(ConsentNone)
	}
}

// ResetConsentForTests resets consent to FULL.
func ResetConsentForTests() {
	_consentMu.Lock()
	_consentLevel = ConsentFull
	_consentMu.Unlock()
}
