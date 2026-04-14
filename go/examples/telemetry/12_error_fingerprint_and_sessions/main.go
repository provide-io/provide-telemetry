// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 12_error_fingerprint_and_sessions — error fingerprinting and session correlation.
//
// Demonstrates:
//   - Session correlation: BindSessionContext, GetSessionID, ClearSessionContext
//   - Error fingerprinting via SHA-256 of "ErrorType:callsite" — a stable hash
//     that is consistent across runs for the same error type.
//   - Structured error fields via slog (Go's equivalent of Python error processors).
//
// Note: Go uses structured error fields; fingerprinting is done via PIIRule hash
// mode or custom middleware. The SHA-256 demo here shows the same deterministic
// fingerprint concept as the Python _compute_error_fingerprint internal.
package main

import (
	"context"
	"crypto/sha256"
	"fmt"
	"runtime"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

// computeErrorFingerprint computes a deterministic short hex fingerprint for an
// error type at a given call site.  When callSite is empty, only the type is
// hashed — matching the Python "no traceback" behaviour.
func computeErrorFingerprint(errType, callSite string) string {
	key := errType
	if callSite != "" {
		key = errType + ":" + callSite
	}
	sum := sha256.Sum256([]byte(key))
	return fmt.Sprintf("%x", sum)[:16]
}

func demoErrorFingerprint(ctx context.Context) {
	fmt.Println("--- Error Fingerprinting ---")
fmt.Println()

	// Same error type without callsite produces the same fingerprint.
	fpA := computeErrorFingerprint("ValueError", "")
	fpB := computeErrorFingerprint("ValueError", "")
	fmt.Printf("  ValueError (no callsite) fingerprint 1: %s\n", fpA)
	fmt.Printf("  ValueError (no callsite) fingerprint 2: %s\n", fpB)
	fmt.Printf("  Same? %v\n\n", fpA == fpB)

	// Different types produce different fingerprints.
	fpC := computeErrorFingerprint("TypeError", "")
	fmt.Printf("  TypeError  (no callsite) fingerprint:   %s\n", fpC)
	fmt.Printf("  Differs from ValueError? %v\n\n", fpA != fpC)

	// Using runtime.Callers to capture a stable call site.
	_, file, line, _ := runtime.Caller(0)
	callSite := fmt.Sprintf("%s:%d", file, line)
	fpRuntime := computeErrorFingerprint("RuntimeError", callSite)
	fmt.Printf("  RuntimeError with callsite fingerprint: %s\n", fpRuntime)

	// Log the simulated error with the fingerprint as a structured field.
	log := telemetry.GetLogger(ctx, "examples.fingerprint")
	errEvt, _ := telemetry.Event("app", "error", "simulated")
	log.ErrorContext(ctx, errEvt.Event, append(errEvt.Attrs(),
		"error_fingerprint", fpRuntime,
		"exc_name", "RuntimeError",
		"message", "simulated failure",
	)...)

	// Normal events get no fingerprint (must be added explicitly).
	normalFp := computeErrorFingerprint("", "")
	fmt.Printf("  Normal event fingerprint (empty type): %s\n", normalFp)
	fmt.Printf("  Normal event has distinct fingerprint? %v\n\n", normalFp != fpA)
}

func demoSessionCorrelation(ctx context.Context) {
	fmt.Println("--- Session Correlation ---")
fmt.Println()

	log := telemetry.GetLogger(ctx, "examples.session")

	sessionBefore, _ := telemetry.GetSessionID(ctx)
	fmt.Printf("  Session before bind: %q\n", sessionBefore)

	ctx = telemetry.BindSessionContext(ctx, "sess-demo-42")
	sessionAfterBind, _ := telemetry.GetSessionID(ctx)
	fmt.Printf("  Session after bind:  %q\n", sessionAfterBind)

	boundEvt, _ := telemetry.Event("app", "session", "bound")
	log.InfoContext(ctx, boundEvt.Event, append(boundEvt.Attrs(), "detail", "session is active")...)

	actionEvt, _ := telemetry.Event("app", "session", "action")
	log.InfoContext(ctx, actionEvt.Event, append(actionEvt.Attrs(), "action", "page_view", "path", "/dashboard")...)

	ctx = telemetry.ClearSessionContext(ctx)
	sessionAfterClear, _ := telemetry.GetSessionID(ctx)
	fmt.Printf("  Session after clear: %q\n\n", sessionAfterClear)
}

func main() {
	fmt.Println("Error Fingerprinting and Session Correlation Demo")
fmt.Println()

	_, err := telemetry.SetupTelemetry()
	if err != nil {
		telemetry.Logger.Error("setup failed", "err", err)
		return
	}
	defer func() { _ = telemetry.ShutdownTelemetry(context.Background()) }()

	ctx := context.Background()

	demoErrorFingerprint(ctx)
	demoSessionCorrelation(ctx)

	fmt.Println("Done!")
}
