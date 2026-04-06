// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 07_slo_and_health_snapshot — SLO metrics and full health snapshot inspection.
//
// Demonstrates:
//   - RecordREDMetrics for HTTP request/error/duration (RED)
//   - RecordUSEMetrics for resource utilization (USE)
//   - ClassifyError for error taxonomy
//   - GetHealthSnapshot with all counters
package main

import (
	"context"
	"fmt"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func main() {
	fmt.Println("SLO Metrics & Health Snapshot Demo")

	_, err := telemetry.SetupTelemetry()
	if err != nil {
		telemetry.Logger.Error("setup failed", "err", err)
		return
	}
	defer func() { _ = telemetry.ShutdownTelemetry(context.Background()) }()

	ctx := context.Background()
	log := telemetry.GetLogger(ctx, "examples.slo")

	// Successful requests
	fmt.Println("Recording successful HTTP requests...")
	telemetry.RecordREDMetrics("/matchmaking", "POST", 200, 18.2)
	telemetry.RecordREDMetrics("/matchmaking", "GET", 200, 5.1)
	telemetry.RecordREDMetrics("/leaderboard", "GET", 200, 12.7)
	fmt.Println("  3 requests recorded (POST + 2x GET)")

	// Server errors
	fmt.Println("\nRecording server errors...")
	telemetry.RecordREDMetrics("/matchmaking", "POST", 503, 210.5)
	telemetry.RecordREDMetrics("/inventory", "PUT", 500, 45.0)
	fmt.Println("  2 errors recorded (503 + 500)")

	// Resource utilization (USE)
	fmt.Println("\nRecording resource utilization...")
	telemetry.RecordUSEMetrics("cpu", 61)
	telemetry.RecordUSEMetrics("memory", 78)
	telemetry.RecordUSEMetrics("disk_io", 23)
	fmt.Println("  cpu=61%  |  memory=78%  |  disk_io=23%")

	// Error taxonomy
	fmt.Println("\nError taxonomy classification:")
	type errorCase struct {
		name string
		code int
	}
	cases := []errorCase{
		{"UpstreamTimeout", 503},
		{"InvalidPayload", 400},
		{"NullPointerError", 0},
	}
	for _, c := range cases {
		taxonomy := telemetry.ClassifyError(c.name, c.code)
		fmt.Printf("  %s(status=%d) -> category=%s, severity=%s\n",
			c.name, c.code,
			taxonomy["error.category"],
			taxonomy["error.severity"],
		)
		if c.code == 503 {
			errEvt, _ := telemetry.Event("example", "slo", "error")
			log.ErrorContext(ctx, errEvt.Event, append(errEvt.Attrs(),
				"exc_name", c.name,
				"status_code", fmt.Sprint(c.code),
				"error_category", taxonomy["error.category"],
				"error_severity", taxonomy["error.severity"],
			)...)
		}
	}

	// Full health snapshot
	fmt.Println("\nFull HealthSnapshot:")
	s := telemetry.GetHealthSnapshot()
	fmt.Printf("  LogsEmitted:         %d\n", s.LogsEmitted)
	fmt.Printf("  LogsDropped:         %d\n", s.LogsDropped)
	fmt.Printf("  LogsExportFailures:  %d\n", s.LogsExportFailures)
	fmt.Printf("  LogsRetries:         %d\n", s.LogsRetries)
	fmt.Printf("  LogsCircuitState:    %s\n", s.LogsCircuitState)
	fmt.Printf("  TracesEmitted:       %d\n", s.TracesEmitted)
	fmt.Printf("  TracesDropped:       %d\n", s.TracesDropped)
	fmt.Printf("  TracesExportFailures:%d\n", s.TracesExportFailures)
	fmt.Printf("  TracesRetries:       %d\n", s.TracesRetries)
	fmt.Printf("  TracesCircuitState:  %s\n", s.TracesCircuitState)
	fmt.Printf("  MetricsEmitted:      %d\n", s.MetricsEmitted)
	fmt.Printf("  MetricsDropped:      %d\n", s.MetricsDropped)
	fmt.Printf("  MetricsExportFailures:%d\n", s.MetricsExportFailures)
	fmt.Printf("  MetricsRetries:      %d\n", s.MetricsRetries)
	fmt.Printf("  MetricsCircuitState: %s\n", s.MetricsCircuitState)
	fmt.Printf("  SetupError:          %q\n", s.SetupError)

	fmt.Println("\nDone!")
}
