// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

package telemetry

import (
	"os"
	"strings"
	"sync"
)

// ConsentLevel controls how much telemetry data is collected.
type ConsentLevel int

const (
	ConsentFull       ConsentLevel = iota // All signals collected
	ConsentFunctional                     // Warnings+, traces, metrics; no context
	ConsentMinimal                        // Errors only; no traces/metrics/context
	ConsentNone                           // No telemetry collected
)

var _logLevelOrder = map[string]int{
	"TRACE": 0, "DEBUG": 1, "INFO": 2, "WARNING": 3, "WARN": 3, "ERROR": 4, "CRITICAL": 5,
}

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
		if signal == "logs" {
			order := _logLevelOrder[strings.ToUpper(logLevel)]
			return order >= _logLevelOrder["WARNING"]
		}
		if signal == "context" {
			return false
		}
		return true
	case ConsentMinimal:
		if signal == "logs" {
			order := _logLevelOrder[strings.ToUpper(logLevel)]
			return order >= _logLevelOrder["ERROR"]
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
