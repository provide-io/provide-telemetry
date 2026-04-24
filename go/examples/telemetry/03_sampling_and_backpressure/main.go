// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 03_sampling_and_backpressure — sampling policies and backpressure queue controls.
//
// Demonstrates:
//   - SamplingPolicy with DefaultRate and per-key Overrides
//   - SetSamplingPolicy / GetSamplingPolicy / ShouldSample
//   - QueuePolicy with per-signal max sizes
//   - SetQueuePolicy / GetQueuePolicy
//   - TryAcquire / Release for manual backpressure
//   - GetHealthSnapshot for dropped counts
package main

import (
	"context"
	"fmt"
	"sync"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func tracedWork(ctx context.Context, taskID int) error {
	concEvt, _ := telemetry.Event("example", "sampling", "concurrent")
	return telemetry.Trace(ctx, concEvt.Event, func(ctx context.Context) error {
		requests := telemetry.NewCounter("example.sampling.counter")
		requests.Add(ctx, 1)
		return nil
	})
}

func main() {
	fmt.Println("Sampling & Backpressure Demo")

	_, err := telemetry.SetupTelemetry()
	if err != nil {
		telemetry.Logger.Error("setup failed", "err", err)
		return
	}
	defer func() { _ = telemetry.ShutdownTelemetry(context.Background()) }()

	ctx := context.Background()
	log := telemetry.GetLogger(ctx, "examples.sampling")

	// Sampling policies with overrides
	fmt.Println("Setting sampling policies...")
	_, _ = telemetry.SetSamplingPolicy("logs", telemetry.SamplingPolicy{
		DefaultRate: 0.0,
		Overrides:   map[string]float64{"example.critical": 1.0},
	})
	_, _ = telemetry.SetSamplingPolicy("metrics", telemetry.SamplingPolicy{DefaultRate: 1.0})
	_, _ = telemetry.SetSamplingPolicy("traces", telemetry.SamplingPolicy{DefaultRate: 1.0})

	// Inspect active policies
	logsPolicy, _ := telemetry.GetSamplingPolicy("logs")
	fmt.Printf("  logs:    default_rate=%.1f, overrides=%v\n", logsPolicy.DefaultRate, logsPolicy.Overrides)
	metricsPolicy, _ := telemetry.GetSamplingPolicy("metrics")
	fmt.Printf("  metrics: default_rate=%.1f\n", metricsPolicy.DefaultRate)
	tracesPolicy, _ := telemetry.GetSamplingPolicy("traces")
	fmt.Printf("  traces:  default_rate=%.1f\n", tracesPolicy.DefaultRate)

	// should_sample with overrides
	fmt.Println("\nShouldSample() decisions:")
	for _, key := range []string{"example.routine", "example.critical"} {
		sampled, _ := telemetry.ShouldSample("logs", key)
		mark := "NO"
		if sampled {
			mark = "YES"
		}
		fmt.Printf("  logs/%s: sampled=%s\n", key, mark)
	}

	// Backpressure queue limits
	fmt.Println("\nSetting queue policy (TracesMaxSize=1)...")
	telemetry.SetQueuePolicy(telemetry.QueuePolicy{
		LogsMaxSize:    0,
		MetricsMaxSize: 0,
		TracesMaxSize:  1,
	})
	qp := telemetry.GetQueuePolicy()
	fmt.Printf("  Queue policy: logs=%d, traces=%d, metrics=%d\n",
		qp.LogsMaxSize, qp.TracesMaxSize, qp.MetricsMaxSize)

	// TryAcquire / Release
	fmt.Println("\nTryAcquire / Release for traces:")
	acquired := telemetry.TryAcquire("traces")
	fmt.Printf("  First acquire: %v\n", acquired != nil)
	if acquired != nil {
		second := telemetry.TryAcquire("traces")
		fmt.Printf("  Second acquire (expect false): %v\n", second != nil)
		telemetry.Release(acquired)
		after := telemetry.TryAcquire("traces")
		fmt.Printf("  After release (expect true): %v\n", after != nil)
		telemetry.Release(after)
	}

	// Concurrent traced work (will saturate queue)
	fmt.Println("\nLaunching 5 concurrent traced tasks...")
	var wg sync.WaitGroup
	for i := range 5 {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			_ = tracedWork(ctx, id)
		}(i)
	}
	wg.Wait()
	fmt.Println("  All tasks completed")

	// This event itself is sampled out (logs rate=0%).
	doneEvt, _ := telemetry.Event("example", "sampling", "done")
	log.InfoContext(ctx, doneEvt.Event, doneEvt.Attrs()...)

	// Health snapshot
	fmt.Println("\nHealth snapshot after saturation:")
	snapshot := telemetry.GetHealthSnapshot()
	fmt.Printf("  dropped_logs:       %d\n", snapshot.LogsDropped)
	fmt.Printf("  dropped_traces:     %d\n", snapshot.TracesDropped)
	fmt.Printf("  dropped_metrics:    %d\n", snapshot.MetricsDropped)
	fmt.Printf("  queue_depth_traces: (n/a in Go snapshot)\n")

	fmt.Println("\nDone!")
}
