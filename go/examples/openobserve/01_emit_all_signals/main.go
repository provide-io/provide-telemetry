// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 01_emit_all_signals — emit logs, traces, and metrics to OpenObserve.
//
// Required environment variables:
//
//	OPENOBSERVE_URL      e.g. http://localhost:5080/api/default
//	OPENOBSERVE_USER     e.g. tim@provide.io
//	OPENOBSERVE_PASSWORD e.g. password
//
// The program sets OTEL_EXPORTER_OTLP_* from OPENOBSERVE_URL and emits
// 5 traced iterations, then sends a direct JSON log to the HTTP API.
// Prints: signals emitted run_id=<id>
package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
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

func sendJSONLog(baseURL, auth, runID string) error {
	payload := []map[string]any{
		{
			"_timestamp": time.Now().UnixMicro(),
			"event":      "example.openobserve.jsonlog",
			"run_id":     runID,
			"message":    "openobserve json log ingestion",
		},
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal payload: %w", err)
	}

	// Construct the ingestion endpoint: <baseURL>/default/_json
	// baseURL is already stripped of trailing slash.
	endpoint := baseURL + "/default/_json"
	parsed, err := url.Parse(endpoint)
	if err != nil {
		return fmt.Errorf("parse url: %w", err)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return fmt.Errorf("unsupported URL scheme: %s", parsed.Scheme)
	}

	req, err := http.NewRequestWithContext(context.Background(), http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Authorization", auth)
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("http post: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	_, _ = io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		return fmt.Errorf("OpenObserve API returned status %d", resp.StatusCode)
	}
	return nil
}

func doWork(ctx context.Context, runID string, iteration int) error {
	traceName := "example.openobserve.work." + runID
	return telemetry.Trace(ctx, traceName, func(ctx context.Context) error {
		log := telemetry.GetLogger(ctx, "examples.openobserve")
		evtName, _ := telemetry.Event("example", "openobserve", "log")
		log.InfoContext(ctx, evtName.Event, append(evtName.Attrs(), "iteration", strconv.Itoa(iteration))...)

		metricName := "example.openobserve.requests." + runID
		c := telemetry.NewCounter(metricName)
		c.Add(ctx, 1)
		return nil
	})
}

func main() {
	baseURL := requireEnv("OPENOBSERVE_URL")
	// Strip trailing slash for consistent URL construction.
	for len(baseURL) > 0 && baseURL[len(baseURL)-1] == '/' {
		baseURL = baseURL[:len(baseURL)-1]
	}
	user := requireEnv("OPENOBSERVE_USER")
	password := requireEnv("OPENOBSERVE_PASSWORD")
	auth := authHeader(user, password)

	runID := os.Getenv("PROVIDE_EXAMPLE_RUN_ID")
	if runID == "" {
		runID = strconv.FormatInt(time.Now().Unix(), 10)
	}

	// Configure OTel export intervals for faster flushing in examples.
	_ = os.Setenv("OTEL_BSP_SCHEDULE_DELAY", "200")
	_ = os.Setenv("OTEL_BLRP_SCHEDULE_DELAY", "200")
	_ = os.Setenv("OTEL_METRIC_EXPORT_INTERVAL", "1000")

	// Wire OTel endpoints from OpenObserve URL.
	encodedAuth := url.QueryEscape(auth)
	_ = os.Setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", baseURL+"/v1/traces")
	_ = os.Setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", baseURL+"/v1/metrics")
	_ = os.Setenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", baseURL+"/v1/logs")
	_ = os.Setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization="+encodedAuth)
	_ = os.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "provide-telemetry-examples")
	_ = os.Setenv("PROVIDE_TELEMETRY_VERSION", "examples")
	_ = os.Setenv("PROVIDE_TRACE_ENABLED", "true")
	_ = os.Setenv("PROVIDE_METRICS_ENABLED", "true")

	_, err := telemetry.SetupTelemetry()
	if err != nil {
		fmt.Fprintf(os.Stderr, "setup failed: %v\n", err)
		os.Exit(1)
	}

	ctx := context.Background()
	for i := range 5 {
		if err := doWork(ctx, runID, i); err != nil {
			telemetry.Logger.Error("work failed", "err", err)
		}
		time.Sleep(50 * time.Millisecond)
	}

	if err := telemetry.ShutdownTelemetry(ctx); err != nil {
		fmt.Fprintf(os.Stderr, "shutdown error: %v\n", err)
	}

	if err := sendJSONLog(baseURL, auth, runID); err != nil {
		fmt.Fprintf(os.Stderr, "json log send error: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("signals emitted run_id=%s\n", runID)
}
