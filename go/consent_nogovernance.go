// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

//go:build nogovernance

package telemetry

// ShouldAllow is the no-governance stub — all signals are always permitted.
// The full implementation lives in consent.go and is excluded from this build.
func ShouldAllow(_ string, _ string) bool { return true }
