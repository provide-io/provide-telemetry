// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Package fingerprintcore contains the stateless error-fingerprint logic
// shared by the top-level telemetry package and the logger sub-package.
package fingerprintcore

import (
	"crypto/sha256"
	"fmt"
	"runtime"
	"strings"
)

// ShortHash12 returns the first 12 hex characters of the SHA-256 hash.
func ShortHash12(input string) string {
	sum := sha256.Sum256([]byte(input))
	return fmt.Sprintf("%x", sum)[:12]
}

// ExtractBasename extracts the filename without path or extension, lowercased.
func ExtractBasename(file string) string {
	file = strings.ReplaceAll(file, "\\", "/")
	if idx := strings.LastIndex(file, "/"); idx >= 0 {
		file = file[idx+1:]
	}
	if idx := strings.LastIndex(file, "."); idx >= 0 {
		file = file[:idx]
	}
	return strings.ToLower(file)
}

// ExtractFuncName extracts just the function name from a fully qualified Go function path.
func ExtractFuncName(fn string) string {
	if idx := strings.LastIndex(fn, "."); idx >= 0 {
		return fn[idx+1:]
	}
	return fn
}

// ComputeFromPCs generates a stable 12-char hex fingerprint from exception type
// + top 3 stack frames from the given program counters.
func ComputeFromPCs(excType string, pcs []uintptr) string {
	parts := []string{strings.ToLower(excType)}
	if len(pcs) > 0 {
		frames := runtime.CallersFrames(pcs)
		count := 0
		for count < 3 {
			frame, more := frames.Next()
			if frame.Function == "" && !more {
				break
			}
			if frame.File != "" {
				base := ExtractBasename(frame.File)
				fn := strings.ToLower(ExtractFuncName(frame.Function))
				parts = append(parts, base+":"+fn)
				count++
			}
			if !more {
				break
			}
		}
	}
	return ShortHash12(strings.Join(parts, ":"))
}

// ComputeFromParts generates a fingerprint from pre-extracted parts.
func ComputeFromParts(excType string, frameParts []string) string {
	parts := []string{strings.ToLower(excType)}
	parts = append(parts, frameParts...)
	return ShortHash12(strings.Join(parts, ":"))
}
