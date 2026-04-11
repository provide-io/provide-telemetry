// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"crypto/sha256"
	"fmt"
	"runtime"
	"strings"
)

// ComputeErrorFingerprint generates a stable 12-char hex fingerprint from
// exception type + top 3 stack frames from the given program counters.
// Matches the Python/TypeScript algorithm exactly.
func ComputeErrorFingerprint(excType string, pcs []uintptr) string {
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
				base := _extractBasename(frame.File)
				fn := strings.ToLower(_extractFuncName(frame.Function))
				parts = append(parts, base+":"+fn)
				count++
			}
			if !more {
				break
			}
		}
	}
	return _shortHash12(strings.Join(parts, ":"))
}

// ComputeErrorFingerprintFromParts generates a fingerprint from pre-extracted parts.
func ComputeErrorFingerprintFromParts(excType string, frameParts []string) string {
	parts := []string{strings.ToLower(excType)}
	parts = append(parts, frameParts...)
	return _shortHash12(strings.Join(parts, ":"))
}

// _shortHash12 returns the first 12 hex characters of the SHA-256 hash.
func _shortHash12(input string) string {
	sum := sha256.Sum256([]byte(input))
	return fmt.Sprintf("%x", sum)[:12]
}

// _extractBasename extracts the filename without path or extension, lowercased.
func _extractBasename(file string) string {
	file = strings.ReplaceAll(file, "\\", "/")
	if idx := strings.LastIndex(file, "/"); idx >= 0 {
		file = file[idx+1:]
	}
	if idx := strings.LastIndex(file, "."); idx >= 0 {
		file = file[:idx]
	}
	return strings.ToLower(file)
}

// _extractFuncName extracts just the function name from a fully qualified Go function path.
func _extractFuncName(fn string) string {
	if idx := strings.LastIndex(fn, "."); idx >= 0 {
		return fn[idx+1:]
	}
	return fn
}
