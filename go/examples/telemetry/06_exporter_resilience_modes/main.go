// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 06_exporter_resilience_modes — retries, timeouts, and failure policies.
//
// Demonstrates:
//   - ExporterPolicy with FailOpen=true vs FailOpen=false
//   - TimeoutSeconds for deadline enforcement
//   - GetExporterPolicy to inspect active policy
//   - RunWithResilience with a failing function showing retries
//   - GetHealthSnapshot for retry/failure counts
package main

import (
	"context"
	"errors"
	"fmt"
	"time"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func main() {
	fmt.Println("Exporter Resilience Demo")

	// No SetupTelemetry needed — resilience API is standalone.
	// We call it anyway to match the pattern of other examples.
	_, err := telemetry.SetupTelemetry()
	if err != nil {
		telemetry.Logger.Error("setup failed", "err", err)
		return
	}
	defer func() { _ = telemetry.ShutdownTelemetry(context.Background()) }()

	ctx := context.Background()

	// Fail-open: returns nil on failure
	fmt.Println("Fail-open mode (retries=1, backoff=0s)")
	telemetry.SetExporterPolicy("logs", telemetry.ExporterPolicy{
		Retries:        1,
		BackoffSeconds: 0.0,
		TimeoutSeconds: 5.0,
		FailOpen:       true,
	})

	attemptsOpen := 0
	result := telemetry.RunWithResilience(ctx, "logs", func(_ context.Context) error {
		attemptsOpen++
		return errors.New("simulated exporter failure")
	})
	policy := telemetry.GetExporterPolicy("logs")
	fmt.Printf("  Result: %v\n", result)
	fmt.Printf("  Attempts: %d\n", attemptsOpen)
	fmt.Printf("  Policy: retries=%d, fail_open=%v\n", policy.Retries, policy.FailOpen)

	// Fail-closed: raises on failure
	fmt.Println("\nFail-closed mode (retries=1, backoff=0s)")
	telemetry.SetExporterPolicy("logs", telemetry.ExporterPolicy{
		Retries:        1,
		BackoffSeconds: 0.0,
		TimeoutSeconds: 5.0,
		FailOpen:       false,
	})

	attemptsClosed := 0
	closedErr := telemetry.RunWithResilience(ctx, "logs", func(_ context.Context) error {
		attemptsClosed++
		return errors.New("simulated hard failure")
	})
	if closedErr != nil {
		fmt.Printf("  Caught: %v\n", closedErr)
		fmt.Printf("  Attempts: %d\n", attemptsClosed)
	}

	// Timeout enforcement
	fmt.Println("\nTimeout enforcement (timeout=0.05s)")
	telemetry.SetExporterPolicy("traces", telemetry.ExporterPolicy{
		Retries:        0,
		BackoffSeconds: 0.0,
		TimeoutSeconds: 0.05,
		FailOpen:       true,
	})

	timeoutResult := telemetry.RunWithResilience(ctx, "traces", func(ctx context.Context) error {
		select {
		case <-time.After(200 * time.Millisecond):
			return nil
		case <-ctx.Done():
			return ctx.Err()
		}
	})
	fmt.Printf("  Result: %v  (nil = timed out, fail-open)\n", timeoutResult)

	// Health snapshot
	fmt.Println("\nHealth snapshot after all operations:")
	snapshot := telemetry.GetHealthSnapshot()
	fmt.Printf("  retries_logs:           %d\n", snapshot.LogsRetries)
	fmt.Printf("  retries_traces:         %d\n", snapshot.TracesRetries)
	fmt.Printf("  export_failures_logs:   %d\n", snapshot.LogsExportFailures)
	fmt.Printf("  export_failures_traces: %d\n", snapshot.TracesExportFailures)
	fmt.Printf("  circuit_state_logs:     %s\n", snapshot.LogsCircuitState)
	fmt.Printf("  setup_error:            %s\n", snapshot.SetupError)

	fmt.Println("\nDone!")
}
