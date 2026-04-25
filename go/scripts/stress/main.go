// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Stress test suite — runs all stress scenarios and reports results.
//
// Usage: go run ./scripts/stress
package main

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"runtime"
	"time"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func heapMB() float64 {
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	return float64(m.HeapAlloc) / 1024 / 1024
}

func stressLogging() {
	fmt.Println("── Stress: Logging ────────────────────────────────────────")
	const n = 1_000_000
	before := heapMB()
	start := time.Now()
	for i := range n {
		telemetry.Logger.Info("stress.log", "i", i)
	}
	elapsed := time.Since(start)
	after := heapMB()
	fmt.Printf("  Records:    %d\n", n)
	fmt.Printf("  Elapsed:    %dms\n", elapsed.Milliseconds())
	fmt.Printf("  Heap delta: %.1f MB\n\n", after-before)
}

func stressSampling() {
	fmt.Println("── Stress: Sampling ───────────────────────────────────────")
	const n = 500_000
	_, _ = telemetry.SetSamplingPolicy("logs", telemetry.SamplingPolicy{
		DefaultRate: 0.5,
		Overrides:   map[string]float64{"auth.login": 1.0},
	})
	defer func() { _, _ = telemetry.SetSamplingPolicy("logs", telemetry.SamplingPolicy{DefaultRate: 1.0}) }()

	before := heapMB()
	start := time.Now()
	sampled := 0
	for i := range n {
		key := ""
		if i%2 == 0 {
			key = "auth.login"
		}
		if ok, _ := telemetry.ShouldSample("logs", key); ok {
			sampled++
		}
	}
	elapsed := time.Since(start)
	after := heapMB()
	fmt.Printf("  Decisions:  %d\n", n)
	fmt.Printf("  Sampled:    %d (%.1f%%)\n", sampled, float64(sampled)/float64(n)*100)
	fmt.Printf("  Elapsed:    %dms\n", elapsed.Milliseconds())
	fmt.Printf("  Heap delta: %.1f MB\n\n", after-before)
}

func stressPII() {
	fmt.Println("── Stress: PII Sanitization ───────────────────────────────")
	const nFlat = 200_000
	const nNested = 100_000
	before := heapMB()
	start := time.Now()

	for range nFlat {
		telemetry.SanitizePayload(map[string]any{
			"user":       "alice",
			"password":   "secret",   //nolint:gosec // pragma: allowlist secret
			"token":      "abc123",   //nolint:gosec // stress data
			"request_id": "req-flat", //nolint:gosec // stress data
		}, true, 8)
	}
	for range nNested {
		telemetry.SanitizePayload(map[string]any{
			"user":    map[string]any{"name": "bob", "ssn": "123-45-6789"},
			"headers": map[string]any{"authorization": "Bearer xyz", "host": "example.com"},
		}, true, 8)
	}

	elapsed := time.Since(start)
	after := heapMB()
	fmt.Printf("  Flat:       %d\n", nFlat)
	fmt.Printf("  Nested:     %d\n", nNested)
	fmt.Printf("  Elapsed:    %dms\n", elapsed.Milliseconds())
	fmt.Printf("  Heap delta: %.1f MB\n\n", after-before)
}

func stressBackpressure() {
	fmt.Println("── Stress: Backpressure ───────────────────────────────────")
	const n = 100_000
	telemetry.SetQueuePolicy(telemetry.QueuePolicy{LogsMaxSize: 100})
	defer telemetry.SetQueuePolicy(telemetry.QueuePolicy{})

	before := heapMB()
	start := time.Now()
	acquired := 0
	for range n {
		if ticket := telemetry.TryAcquire("logs"); ticket != nil {
			acquired++
			telemetry.Release(ticket)
		}
	}
	elapsed := time.Since(start)
	after := heapMB()
	snap := telemetry.GetHealthSnapshot()
	fmt.Printf("  Attempts:   %d\n", n)
	fmt.Printf("  Acquired:   %d\n", acquired)
	fmt.Printf("  Dropped:    %d\n", snap.LogsDropped)
	fmt.Printf("  Elapsed:    %dms\n", elapsed.Milliseconds())
	fmt.Printf("  Heap delta: %.1f MB\n\n", after-before)
}

func stressMetrics() {
	fmt.Println("── Stress: Metrics ────────────────────────────────────────")
	const nCounters = 1000
	const nOps = 100
	before := heapMB()
	start := time.Now()

	ctx := context.Background()
	total := int64(0)
	for i := range nCounters {
		c := telemetry.NewCounter(fmt.Sprintf("stress.counter.%d", i))
		for range nOps {
			c.Add(ctx, 1)
			total++
		}
	}

	elapsed := time.Since(start)
	after := heapMB()
	fmt.Printf("  Counters:   %d\n", nCounters)
	fmt.Printf("  Ops/ctr:    %d\n", nOps)
	fmt.Printf("  Total:      %d\n", total)
	fmt.Printf("  Elapsed:    %dms\n", elapsed.Milliseconds())
	fmt.Printf("  Heap delta: %.1f MB\n\n", after-before)
}

func stressTracing() {
	fmt.Println("── Stress: Tracing ────────────────────────────────────────")
	const n = 100_000
	before := heapMB()
	start := time.Now()

	ctx := context.Background()
	for range n {
		_ = telemetry.Trace(ctx, "stress.span", func(_ context.Context) error {
			return nil
		})
	}

	elapsed := time.Since(start)
	after := heapMB()
	fmt.Printf("  Spans:      %d\n", n)
	fmt.Printf("  Elapsed:    %dms\n", elapsed.Milliseconds())
	fmt.Printf("  Heap delta: %.1f MB\n\n", after-before)
}

func main() {
	_, err := telemetry.SetupTelemetry()
	if err != nil {
		fmt.Println("setup failed:", err)
		return
	}
	// Silence logger output for stress tests — prevents I/O from dominating timing.
	telemetry.Logger = slog.New(slog.NewTextHandler(io.Discard, nil))

	fmt.Println()
	fmt.Println("═══════════════════════════════════════════════════════════")
	fmt.Println(" Go Stress Tests")
	fmt.Println("═══════════════════════════════════════════════════════════")
	fmt.Println()

	stressLogging()
	stressSampling()
	stressPII()
	stressBackpressure()
	stressMetrics()
	stressTracing()
}
