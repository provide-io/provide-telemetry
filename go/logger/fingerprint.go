// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package logger

import (
	"github.com/provide-io/provide-telemetry/go/internal/fingerprintcore"
)

// ComputeErrorFingerprint generates a stable 12-char hex fingerprint from
// exception type + top 3 stack frames from the given program counters.
func ComputeErrorFingerprint(excType string, pcs []uintptr) string {
	return fingerprintcore.ComputeFromPCs(excType, pcs)
}

// ComputeErrorFingerprintFromParts generates a stable 12-char hex fingerprint from
// an exception type and optional pre-extracted frame strings.
func ComputeErrorFingerprintFromParts(excType string, frameParts []string) string {
	return fingerprintcore.ComputeFromParts(excType, frameParts)
}

// _computeErrorFingerprint is the internal alias used by logger.go's applyErrorFingerprint.
func _computeErrorFingerprint(excType string, pcs []uintptr) string {
	return fingerprintcore.ComputeFromPCs(excType, pcs)
}

// _computeErrorFingerprintFromParts is the internal alias used in tests.
func _computeErrorFingerprintFromParts(excType string, frameParts []string) string {
	return fingerprintcore.ComputeFromParts(excType, frameParts)
}
