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
	_resetCardinalityLimits()
	_resetSetup()
}
