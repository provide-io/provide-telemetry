// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 01_basic_telemetry — logging, tracing, and all three metric types.
//
// Demonstrates:
//   - SetupTelemetry / ShutdownTelemetry lifecycle
//   - GetLogger for structured logging
//   - Trace for automatic span creation
//   - NewCounter, NewGauge, NewHistogram creation and recording
//   - BindContext / UnbindContext / ClearContext for structured fields
package main

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func doWork(ctx context.Context, iteration int) error {
	workEvt, _ := telemetry.Event("example", "basic", "work")
	return telemetry.Trace(ctx, workEvt.Event, func(ctx context.Context) error {
		log := telemetry.GetLogger(ctx, "examples.basic")
		iterEvt, _ := telemetry.Event("example", "basic", "iteration")
		log.InfoContext(ctx, iterEvt.Event, append(iterEvt.Attrs(), "iteration", fmt.Sprint(iteration))...)

		requests := telemetry.NewCounter("example.basic.requests",
			telemetry.WithDescription("Total request count"))
		requests.Add(ctx, 1, slog.String("iteration", fmt.Sprint(iteration)))

		latency := telemetry.NewHistogram("example.basic.latency_ms",
			telemetry.WithDescription("Simulated latency"),
			telemetry.WithUnit("ms"))
		latency.Record(ctx, float64(iteration)*12.5, slog.String("iteration", fmt.Sprint(iteration)))

		activeTasks := telemetry.NewGauge("example.basic.active_tasks",
			telemetry.WithDescription("Active task gauge"),
			telemetry.WithUnit("1"))
		activeTasks.Set(ctx, 1)

		return nil
	})
}

func main() {
	fmt.Println("Basic Telemetry Demo")

	cfg, err := telemetry.SetupTelemetry()
	if err != nil {
		telemetry.Logger.Error("setup failed", "err", err)
		return
	}
	defer func() { _ = telemetry.ShutdownTelemetry(context.Background()) }()

	ctx := context.Background()
	log := telemetry.GetLogger(ctx, "examples.basic")

	fmt.Printf("Service: %s  |  Env: %s  |  SampleRate: %.2f\n",
		cfg.ServiceName, cfg.Logging.Level, cfg.Tracing.SampleRate)

	// Structured context binding
	fmt.Println("\nBinding structured context fields...")
	ctx = telemetry.BindContext(ctx, map[string]any{"region": "us-east-1", "tier": "premium"})
	startEvt, _ := telemetry.Event("example", "basic", "start")
	log.InfoContext(ctx, startEvt.Event, append(startEvt.Attrs(), "msg", "context is bound")...)
	fmt.Println("  Bound: region=us-east-1, tier=premium")

	// Traced work loop with all metric types
	fmt.Println("\nRunning traced iterations with counter + histogram + gauge:")
	for i := range 3 {
		if err := doWork(ctx, i); err != nil {
			log.ErrorContext(ctx, "work failed", "err", err)
		}
		time.Sleep(50 * time.Millisecond)
		fmt.Printf("  Iteration %d: counter +1, histogram %.1fms, gauge +1\n", i, float64(i)*12.5)
	}

	// Context cleanup
	fmt.Println("\nUnbinding 'region', then clearing all context...")
	ctx = telemetry.UnbindContext(ctx, "region")
	unbindEvt, _ := telemetry.Event("example", "basic", "after_unbind")
	log.InfoContext(ctx, unbindEvt.Event, append(unbindEvt.Attrs(), "msg", "region removed")...)
	fmt.Println("  Unbound: region")

	ctx = telemetry.ClearContext(ctx)
	clearEvt, _ := telemetry.Event("example", "basic", "after_clear")
	log.InfoContext(ctx, clearEvt.Event, append(clearEvt.Attrs(), "msg", "all context cleared")...)
	fmt.Println("  Cleared: all context fields")

	fmt.Println("\nDone!")
}
