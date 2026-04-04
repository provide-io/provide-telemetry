// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 09_error_handling_and_degradation — error hierarchy and graceful degradation.
//
// Demonstrates:
//   - TelemetryError hierarchy for structured exception handling
//   - ConfigurationError wraps TelemetryError
//   - EventSchemaError for invalid event names
//   - Catching all telemetry errors with errors.As
//   - Graceful degradation when OTel is not configured
//   - Valid and invalid event names
package main

import (
	"context"
	"errors"
	"fmt"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func main() {
	fmt.Println("Error Handling & Graceful Degradation Demo")
fmt.Println()

	// Normal setup — works with or without OTel
	fmt.Println("Setting up telemetry (works with or without OTel)...")
	cfg, err := telemetry.SetupTelemetry()
	if err != nil {
		telemetry.Logger.Error("setup failed", "err", err)
		return
	}
	defer func() { _ = telemetry.ShutdownTelemetry(context.Background()) }()
	fmt.Printf("  Setup complete: service=%s\n\n", cfg.ServiceName)

	ctx := context.Background()
	log := telemetry.GetLogger(ctx, "examples.errors")

	// Exception hierarchy demo
	fmt.Println("Exception Hierarchy Demo")
fmt.Println()

	// ConfigurationError
	fmt.Println("  1. ConfigurationError (invalid config):")
	cfgErr := telemetry.NewConfigurationError("sample_rate must be in [0.0, 1.0]; got 2.0")
	fmt.Printf("     Caught ConfigurationError: %v\n", cfgErr)
	var telErr *telemetry.TelemetryError
	isTelErr := errors.As(cfgErr, &telErr)
	fmt.Printf("     Is TelemetryError? %v\n", isTelErr)

	// EventSchemaError — bad event names
	fmt.Println("\n  2. EventSchemaError (invalid event names):")
	_, err = telemetry.Event("only_one")
	if err != nil {
		var schemaErr *telemetry.EventSchemaError
		if errors.As(err, &schemaErr) {
			fmt.Printf("     Caught EventSchemaError: %v\n", err)
			isTel := errors.As(err, &telErr)
			fmt.Printf("     Is TelemetryError? %v\n", isTel)
		}
	}
	_, err = telemetry.Event("too", "few")
	if err != nil {
		fmt.Printf("     Caught EventSchemaError: %v\n", err)
	}

	// Catch-all with TelemetryError
	fmt.Println("\n  3. Catch-all with TelemetryError:")
	badInputs := [][]string{
		{"x"},
		{"a", "b"},
		{"a", "b", "c", "d", "e", "f"},
	}
	errorsCaught := 0
	for _, segments := range badInputs {
		_, e := telemetry.Event(segments...)
		if e != nil {
			var tErr *telemetry.TelemetryError
			if errors.As(e, &tErr) {
				errorsCaught++
			}
		}
	}
	fmt.Printf("     Caught %d errors with errors.As(err, &TelemetryError)\n", errorsCaught)

	// Valid event names
	fmt.Println("\n  4. Valid event names:")
	evt3, _ := telemetry.Event("auth", "login", "success")
	evt4, _ := telemetry.Event("payment", "subscription", "renewal", "success")
	fmt.Printf("     3-seg DAS:  %s\n", evt3.Event)
	fmt.Printf("     4-seg DARS: %s  (resource=%s)\n", evt4.Event, evt4.Resource)

	// Graceful degradation
	fmt.Println("\nGraceful Degradation Demo")
fmt.Println()

	// Metrics work even without OTel
	c := telemetry.NewCounter("example.errors.requests",
		telemetry.WithDescription("Demo counter"))
	c.Add(ctx, 5)
	fmt.Println("  Counter works without OTel (fallback in-memory)")

	// Tracing works with noop span when OTel isn't configured
	traceEvt, _ := telemetry.Event("example", "errors", "traced_work")
	traceErr := telemetry.Trace(ctx, traceEvt.Event, func(innerCtx context.Context) error {
		return nil
	})
	fmt.Printf("  Trace works without OTel: err=%v\n", traceErr)

	// Logging always works
	degradEvt, _ := telemetry.Event("example", "errors", "degradation_test")
	log.InfoContext(ctx, degradEvt.Event, append(degradEvt.Attrs(), "status", "ok")...)
	fmt.Println("  Structured logging always works")

	// Health snapshot shows the state
	health := telemetry.GetHealthSnapshot()
	fmt.Printf("  Health: logs_dropped=%d, spans_dropped=%d\n",
		health.LogsDropped, health.SpansDropped)

	// Validate event name helper
	fmt.Println("\nValidateEventName helper:")
	for _, name := range []string{"valid.event.name", "too_short", "INVALID.uppercase.name"} {
		e := telemetry.ValidateEventName(name)
		status := "valid"
		if e != nil {
			status = fmt.Sprintf("invalid: %v", e)
		}
		fmt.Printf("  %q -> %s\n", name, status)
	}

	fmt.Println("\nDone!")
}
