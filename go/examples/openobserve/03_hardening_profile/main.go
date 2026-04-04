// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 03_hardening_profile — full hardening profile with emission to OpenObserve.
//
// Required environment variables:
//
//	OPENOBSERVE_URL      e.g. http://localhost:5080/api/default
//	OPENOBSERVE_USER     e.g. someuserexample@provide.test
//	OPENOBSERVE_PASSWORD e.g. password
//
// Optional:
//
//	PROVIDE_EXAMPLE_TOKEN  token value for demo (default: "example-token-from-env")
//
// Combines PII masking, cardinality guards, and SLO RED/USE metrics,
// all shipped to a live OpenObserve endpoint.
package main

import (
	"context"
	"encoding/base64"
	"fmt"
	"net/url"
	"os"
	"strconv"
	"time"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func requireEnv(name string) string {
	v := os.Getenv(name)
	if v == "" {
		fmt.Fprintf(os.Stderr, "missing required env var: %s\n", name)
		os.Exit(1)
	}
	return v
}

func authHeader(user, password string) string {
	token := base64.StdEncoding.EncodeToString([]byte(user + ":" + password))
	return "Basic " + token
}

func emit(ctx context.Context, iteration int) error {
	traceName, _ := telemetry.Event("example", "openobserve", "work")
	return telemetry.Trace(ctx, traceName, func(ctx context.Context) error {
		tokenValue := os.Getenv("PROVIDE_EXAMPLE_TOKEN")
		if tokenValue == "" {
			tokenValue = "example-token-from-env"
		}
		log := telemetry.GetLogger(ctx, "examples.openobserve.hardening")
		logEvt, _ := telemetry.Event("example", "openobserve", "log")

		// The PII rules will sanitize email and truncate full_name before logging.
		payload := map[string]any{
			"iteration": iteration,
			"user": map[string]any{
				"email":     "ops@example.com",
				"full_name": "Operator Example",
			},
			"token": tokenValue,
		}
		sanitized := telemetry.SanitizePayload(payload, true, 0)
		log.InfoContext(ctx, logEvt,
			"iteration", strconv.Itoa(iteration),
			"user", fmt.Sprintf("%v", sanitized["user"]),
			"token", fmt.Sprintf("%v", sanitized["token"]),
		)
		return nil
	})
}

func main() {
	baseURL := requireEnv("OPENOBSERVE_URL")
	for len(baseURL) > 0 && baseURL[len(baseURL)-1] == '/' {
		baseURL = baseURL[:len(baseURL)-1]
	}
	user := requireEnv("OPENOBSERVE_USER")
	password := requireEnv("OPENOBSERVE_PASSWORD")
	auth := authHeader(user, password)

	// Register PII rules before setup.
	telemetry.RegisterPIIRule(telemetry.PIIRule{
		Path: []string{"user", "email"},
		Mode: telemetry.PIIModeHash,
	})
	telemetry.RegisterPIIRule(telemetry.PIIRule{
		Path:       []string{"user", "full_name"},
		Mode:       telemetry.PIIModeTruncate,
		TruncateTo: 4,
	})
	telemetry.RegisterCardinalityLimit("player_id", telemetry.CardinalityLimit{
		MaxValues:  50,
		TTLSeconds: 300,
	})

	// Wire OTel endpoints.
	encodedAuth := url.QueryEscape(auth)
	os.Setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization="+encodedAuth)
	os.Setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", baseURL+"/v1/traces")
	os.Setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", baseURL+"/v1/metrics")
	os.Setenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", baseURL+"/v1/logs")
	os.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "provide-telemetry-hardening-example")
	os.Setenv("PROVIDE_TELEMETRY_VERSION", "hardening")
	os.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "1.0")
	os.Setenv("PROVIDE_SAMPLING_TRACES_RATE", "1.0")
	os.Setenv("PROVIDE_SAMPLING_METRICS_RATE", "1.0")
	os.Setenv("PROVIDE_BACKPRESSURE_TRACES_MAXSIZE", "64")
	os.Setenv("PROVIDE_EXPORTER_LOGS_RETRIES", "1")
	os.Setenv("PROVIDE_EXPORTER_TRACES_RETRIES", "1")
	os.Setenv("PROVIDE_EXPORTER_METRICS_RETRIES", "1")
	os.Setenv("PROVIDE_SLO_ENABLE_RED_METRICS", "true")
	os.Setenv("PROVIDE_SLO_ENABLE_USE_METRICS", "true")

	_, err := telemetry.SetupTelemetry()
	if err != nil {
		fmt.Fprintf(os.Stderr, "setup failed: %v\n", err)
		os.Exit(1)
	}

	ctx := context.Background()

	for i := range 5 {
		if err := emit(ctx, i); err != nil {
			telemetry.Logger.Error("emit failed", "err", err)
		}
		time.Sleep(50 * time.Millisecond)
	}

	if err := telemetry.ShutdownTelemetry(ctx); err != nil {
		fmt.Fprintf(os.Stderr, "shutdown error: %v\n", err)
	}

	health := telemetry.GetHealthSnapshot()
	fmt.Printf("health: logs_emitted=%d spans_started=%d metrics_recorded=%d "+
		"logs_dropped=%d spans_dropped=%d\n",
		health.LogsEmitted, health.SpansStarted, health.MetricsRecorded,
		health.LogsDropped, health.SpansDropped)
}
