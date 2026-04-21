// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"github.com/provide-io/provide-telemetry/go/internal/fingerprintcore"
)

// ComputeErrorFingerprint generates a stable 12-char hex fingerprint from
// exception type + top 3 stack frames from the given program counters.
// Matches the Python/TypeScript algorithm exactly.
func ComputeErrorFingerprint(excType string, pcs []uintptr) string {
	return fingerprintcore.ComputeFromPCs(excType, pcs)
}

// ComputeErrorFingerprintFromParts generates a fingerprint from pre-extracted parts.
func ComputeErrorFingerprintFromParts(excType string, frameParts []string) string {
	return fingerprintcore.ComputeFromParts(excType, frameParts)
}
