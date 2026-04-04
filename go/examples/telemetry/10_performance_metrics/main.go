// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 10_performance_metrics — benchmark key telemetry operations.
//
// Demonstrates:
//   - Timing for SetupTelemetry lifecycle
//   - Hot-path instrument ops: counter.Add, gauge.Set, histogram.Record
//   - Sampling decision throughput via ShouldSample
//   - Event construction via Event()
//   - Sub-microsecond hot-path performance
package main

import (
	"context"
	"fmt"
	"time"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

const (
	_defaultIterations  = 10_000
	_lifecycleIter      = 50
	_configureIter      = 100
)

func bench(fn func(), iterations int) float64 {
	start := time.Now()
	for range iterations {
		fn()
	}
	elapsed := time.Since(start)
	return float64(elapsed.Nanoseconds()) / float64(iterations)
}

func fmtNs(ns float64) string {
	switch {
	case ns >= 1_000_000:
		return fmt.Sprintf("%10.2f ms", ns/1_000_000)
	case ns >= 1_000:
		return fmt.Sprintf("%10.2f us", ns/1_000)
	default:
		return fmt.Sprintf("%10.0f ns", ns)
	}
}

type row struct {
	label string
	value string
}

func main() {
	fmt.Println("Performance Characteristics\n")

	var rows []row

	// Full setup/shutdown lifecycle
	fmt.Println("Setup / Shutdown Lifecycle\n")
	lifecycleNs := bench(func() {
		_, _ = telemetry.SetupTelemetry()
		_ = telemetry.ShutdownTelemetry(context.Background())
	}, _lifecycleIter)
	rows = append(rows, row{"setup + shutdown cycle", fmtNs(lifecycleNs)})

	// Ensure setup for hot-path benchmarks
	_, err := telemetry.SetupTelemetry()
	if err != nil {
		telemetry.Logger.Error("setup failed", "err", err)
		return
	}
	defer func() { _ = telemetry.ShutdownTelemetry(context.Background()) }()

	ctx := context.Background()

	// SetupTelemetry idempotent path (already set up)
	idempotentNs := bench(func() {
		_, _ = telemetry.SetupTelemetry()
	}, _configureIter)
	rows = append(rows, row{"SetupTelemetry (idempotent)", fmtNs(idempotentNs)})

	// Hot-path instrument operations
	fmt.Println("Hot-Path Instrument Operations\n")

	c := telemetry.NewCounter("perf.example.requests",
		telemetry.WithDescription("bench counter"))
	g := telemetry.NewGauge("perf.example.active",
		telemetry.WithDescription("bench gauge"))
	h := telemetry.NewHistogram("perf.example.latency",
		telemetry.WithDescription("bench histogram"),
		telemetry.WithUnit("ms"))

	rows = append(rows, row{"NewCounter(name)", fmtNs(bench(func() {
		_ = telemetry.NewCounter("perf.bench.requests")
	}, _defaultIterations))})

	rows = append(rows, row{"counter.Add(1)", fmtNs(bench(func() {
		c.Add(ctx, 1)
	}, _defaultIterations))})

	rows = append(rows, row{"NewGauge(name)", fmtNs(bench(func() {
		_ = telemetry.NewGauge("perf.bench.active")
	}, _defaultIterations))})

	rows = append(rows, row{"gauge.Set(42)", fmtNs(bench(func() {
		g.Set(ctx, 42)
	}, _defaultIterations))})

	rows = append(rows, row{"NewHistogram(name)", fmtNs(bench(func() {
		_ = telemetry.NewHistogram("perf.bench.latency")
	}, _defaultIterations))})

	rows = append(rows, row{"histogram.Record(3.14)", fmtNs(bench(func() {
		h.Record(ctx, 3.14)
	}, _defaultIterations))})

	rows = append(rows, row{`ShouldSample("logs","x")`, fmtNs(bench(func() {
		_ = telemetry.ShouldSample("logs", "perf.test")
	}, _defaultIterations))})

	rows = append(rows, row{`Event("a","b","c")`, fmtNs(bench(func() {
		_, _ = telemetry.Event("perf", "bench", "op")
	}, _defaultIterations))})

	// Results table
	fmt.Println("Results\n")
	maxLabel := 0
	for _, r := range rows {
		if len(r.label) > maxLabel {
			maxLabel = len(r.label)
		}
	}
	for _, r := range rows {
		fmt.Printf("    %-*s  %s\n", maxLabel, r.label, r.value)
	}

	fmt.Println("\nDone!")
}
