// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 08_full_hardening_profile — all guardrails active simultaneously.
//
// Demonstrates:
//   - PII masking: hash emails, drop credit cards
//   - Cardinality limits: max 3 unique player_ids
//   - Sampling policies: 50% default, 100% for critical events
//   - Backpressure queue: TracesMaxSize=2
//   - Exporter resilience: fail-open, 2 retries, 0.01s backoff
//   - SLO RED/USE metrics
//   - Runtime reconfiguration mid-flight
//   - Full HealthSnapshot inspection
package main

import (
	"context"
	"fmt"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func main() {
	fmt.Println("Full Production Hardening Profile\n")

	cfg, err := telemetry.SetupTelemetry()
	if err != nil {
		telemetry.Logger.Error("setup failed", "err", err)
		return
	}
	defer func() { _ = telemetry.ShutdownTelemetry(context.Background()) }()

	ctx := context.Background()
	log := telemetry.GetLogger(ctx, "examples.hardening")

	// PII masking
	fmt.Println("PII masking: hash emails, drop credit cards")
	telemetry.RegisterPIIRule(telemetry.PIIRule{
		Path: []string{"user", "email"},
		Mode: telemetry.PIIModeHash,
	})
	telemetry.RegisterPIIRule(telemetry.PIIRule{
		Path: []string{"credit_card"},
		Mode: telemetry.PIIModeDrop,
	})
	payload := map[string]any{
		"user":        map[string]any{"email": "player@game.io", "name": "Hero"},
		"credit_card": "4111111111111111",
	}
	sanitized := telemetry.SanitizePayload(payload, true, 0)
	evtName, _ := telemetry.Event("example", "hardening", "user_event")
	log.InfoContext(ctx, evtName, "payload", fmt.Sprintf("%v", sanitized))
	fmt.Println("  PII rules active")

	// Cardinality limits
	fmt.Println("\nCardinality limit: max 3 unique player_ids")
	telemetry.RegisterCardinalityLimit("player_id", telemetry.CardinalityLimit{
		MaxValues:  3,
		TTLSeconds: 300,
	})
	metric := telemetry.NewCounter("example.hardening.actions",
		telemetry.WithDescription("Player actions"))
	for _, pid := range []string{"p1", "p2", "p3", "p4", "p5"} {
		attrs := telemetry.GuardAttributes(map[string]string{"player_id": pid})
		metric.Add(ctx, 1)
		guarded := attrs["player_id"]
		icon := "OK"
		if guarded != pid {
			icon = "OVERFLOW"
		}
		fmt.Printf("  %s player_id=%s -> guarded=%s\n", icon, pid, guarded)
	}

	// Sampling policies
	fmt.Println("\nSampling: logs=50%, traces=100%, critical overrides=100%")
	telemetry.SetSamplingPolicy("logs", telemetry.SamplingPolicy{
		DefaultRate: 0.5,
		Overrides:   map[string]float64{"example.critical": 1.0},
	})
	telemetry.SetSamplingPolicy("traces", telemetry.SamplingPolicy{DefaultRate: 1.0})

	// Backpressure
	fmt.Println("\nBackpressure: traces queue max=2")
	telemetry.SetQueuePolicy(telemetry.QueuePolicy{
		LogsMaxSize:    0,
		MetricsMaxSize: 0,
		TracesMaxSize:  2,
	})

	// Exporter resilience
	fmt.Println("\nExporter resilience: fail-open with 2 retries")
	telemetry.SetExporterPolicy("logs", telemetry.ExporterPolicy{
		Retries:        2,
		BackoffSeconds: 0.01,
		FailOpen:       true,
		TimeoutSeconds: 1.0,
	})

	// SLO RED/USE metrics
	fmt.Println("\nRecording SLO metrics...")
	telemetry.RecordREDMetrics("/game/start", "POST", 200, 22.0)
	telemetry.RecordREDMetrics("/game/start", "POST", 500, 150.0)
	telemetry.RecordUSEMetrics("cpu", 55)
	latency := telemetry.NewHistogram("example.hardening.latency",
		telemetry.WithDescription("Request latency"),
		telemetry.WithUnit("ms"))
	latency.Record(ctx, 22.0)
	fmt.Println("  RED: 2 requests (1 success, 1 error)")
	fmt.Println("  USE: cpu=55%")

	// Runtime reconfiguration
	fmt.Println("\nHot-swapping sampling rate to 100%...")
	before := telemetry.GetSamplingPolicy("logs")
	fmt.Printf("  Before: logs_rate=%.1f\n", before.DefaultRate)
	err = telemetry.UpdateRuntimeConfig(func(c *telemetry.TelemetryConfig) {
		c.Sampling.LogsRate = 1.0
	})
	if err != nil {
		fmt.Printf("  UpdateRuntimeConfig error: %v\n", err)
	} else {
		// re-apply sampling policy to reflect the new rate
		telemetry.SetSamplingPolicy("logs", telemetry.SamplingPolicy{DefaultRate: 1.0})
		after := telemetry.GetSamplingPolicy("logs")
		fmt.Printf("  After:  logs_rate=%.1f\n", after.DefaultRate)
	}

	// Health snapshot
	fmt.Printf("\nHealth snapshot (service=%s):\n", cfg.ServiceName)
	s := telemetry.GetHealthSnapshot()
	fmt.Printf("  Dropped:         logs=%d  traces=%d  metrics=%d\n",
		s.LogsDropped, s.SpansDropped, s.MetricsDropped)
	fmt.Printf("  Retries:         %d\n", s.RetryAttempts)
	fmt.Printf("  Export failures: logs=%d  traces=%d\n",
		s.LogsExportErrors, s.SpansExportErrors)
	fmt.Printf("  Circuit trips:   %d\n", s.CircuitBreakerTrips)
	fmt.Printf("  Last error:      %q\n", s.LastError)

	fmt.Println("\nAll guardrails active — production-ready!")
}
