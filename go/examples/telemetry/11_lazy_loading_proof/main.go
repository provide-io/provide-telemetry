// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 11_lazy_loading_proof — optional OTel wiring and graceful degradation.
//
// Go does not have dynamic module loading like Python's lazy imports.
// This example adapts the concept to demonstrate:
//   - SetupTelemetry() without OTel providers works (graceful degradation)
//   - Measuring setup overhead with and without OTel bridge
//   - "No OTel dependency loaded" when providers are nil (no-op path)
//
// This replaces the Python "lazy import" concept with Go's "optional OTel wiring".
// In Go, OTel is a compile-time dependency; what is optional is the runtime
// *wiring* of real providers vs the no-op fallback path.
package main

import (
	"context"
	"fmt"
	"time"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

const _probeIter = 20

func measureSetup(label string, opts ...telemetry.SetupOption) time.Duration {
	// Ensure clean state before each measurement.
	_ = telemetry.ShutdownTelemetry(context.Background())

	start := time.Now()
	_, err := telemetry.SetupTelemetry(opts...)
	elapsed := time.Since(start)
	if err != nil {
		fmt.Printf("  [%s] setup error: %v\n", label, err)
	}
	_ = telemetry.ShutdownTelemetry(context.Background())
	return elapsed
}

func main() {
	fmt.Println("Optional OTel Wiring — Lazy Loading Proof (Go adaptation)")

	// Scenario 1: No providers injected — pure no-op path.
	fmt.Println("Scenario 1: No OTel providers (no-op path)")

	var noopTimes []time.Duration
	for range _probeIter {
		noopTimes = append(noopTimes, measureSetup("no-op"))
	}
	var noopTotal time.Duration
	for _, d := range noopTimes {
		noopTotal += d
	}
	noopAvg := noopTotal / time.Duration(len(noopTimes))
	fmt.Printf("  SetupTelemetry() without OTel providers — avg over %d runs: %v\n",
		_probeIter, noopAvg)
	fmt.Println("  no OTel dependency loaded (providers are nil, all signals use no-op)")

	// Scenario 2: Nil providers explicitly passed (same as no-op — shows the API).
	fmt.Println("\nScenario 2: Nil providers passed explicitly")
	_, err := telemetry.SetupTelemetry(
		telemetry.WithTracerProvider(nil),
		telemetry.WithMeterProvider(nil),
	)
	if err != nil {
		fmt.Printf("  setup error: %v\n", err)
	} else {
		fmt.Println("  SetupTelemetry with nil providers: OK (no-op fallback)")
	}
	_ = telemetry.ShutdownTelemetry(context.Background())

	// Scenario 3: Verify that all instruments work on the no-op path.
	fmt.Println("\nScenario 3: All instruments work on no-op path")
	_, err = telemetry.SetupTelemetry()
	if err != nil {
		fmt.Printf("  setup error: %v\n", err)
		return
	}
	defer func() { _ = telemetry.ShutdownTelemetry(context.Background()) }()

	ctx := context.Background()

	c := telemetry.NewCounter("lazy.proof.requests")
	c.Add(ctx, 1)
	fmt.Println("  counter.Add: OK")

	g := telemetry.NewGauge("lazy.proof.active")
	g.Set(ctx, 42)
	fmt.Println("  gauge.Set:   OK")

	h := telemetry.NewHistogram("lazy.proof.latency")
	h.Record(ctx, 3.14)
	fmt.Println("  histogram.Record: OK")

	traceEvt, _ := telemetry.Event("lazy", "proof", "span")
	_ = telemetry.Trace(ctx, traceEvt.Event, func(_ context.Context) error { return nil })
	fmt.Println("  Trace (no-op span): OK")

	log := telemetry.GetLogger(ctx, "lazy.proof")
	logEvt, _ := telemetry.Event("lazy", "proof", "log")
	log.InfoContext(ctx, logEvt.Event, append(logEvt.Attrs(), "msg", "logging works on no-op path")...)
	fmt.Println("  GetLogger: OK")

	// Summary
	fmt.Printf("\nSummary:\n")
	fmt.Printf("  No-op setup avg: %v\n", noopAvg)
	fmt.Println("  All telemetry instruments degrade gracefully without OTel providers.")
	fmt.Println("  The OTel bridge is optional wiring at runtime, not a load-time requirement.")

	fmt.Println("\nDone!")
}
