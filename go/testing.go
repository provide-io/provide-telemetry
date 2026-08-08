// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

// ResetForTests resets all package-level state to a clean baseline. Call this
// at the start (and in t.Cleanup) of any test that touches telemetry globals.
//
// It is safe to call from external test packages (package telemetry_test).
func ResetForTests() {
	_resetHealth()
	_resetSamplingPolicies()
	_resetQueuePolicy()
	_resetResiliencePolicies()
	_resetPIIRules()
	_resetSecretPatterns()
	_resetCardinalityLimits()
	_resetSetup()
}

// ResetPIIRulesForTests clears every custom PII rule and every hook registered
// on the PII engine, leaving only the built-in sensitive keys and patterns.
//
// It is safe to call from external test packages (package telemetry_test).
func ResetPIIRulesForTests() {
	_resetPIIRules()
}
