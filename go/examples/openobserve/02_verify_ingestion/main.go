// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// 02_verify_ingestion — run 01_emit_all_signals and verify signals appear in OpenObserve.
//
// Required environment variables:
//
//	OPENOBSERVE_URL      e.g. http://localhost:5080/api/default
//	OPENOBSERVE_USER     e.g. someuserexample@provide.test
//	OPENOBSERVE_PASSWORD e.g. password
//
// Optional:
//
//	OPENOBSERVE_REQUIRED_SIGNALS  comma-separated: logs,metrics,traces (default: logs)
//
// The program:
//  1. Notes the "before" counts for logs/traces/metrics.
//  2. Runs the emit binary (or calls emit logic directly).
//  3. Polls OpenObserve for up to 30s until ingestion is confirmed.
//  4. Prints "verification passed" or exits non-zero.
package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"time"
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

type searchQuery struct {
	SQL       string `json:"sql"`
	StartTime int64  `json:"start_time"`
	EndTime   int64  `json:"end_time"`
}

type searchRequest struct {
	Query searchQuery `json:"query"`
}

type searchResponse struct {
	Total int              `json:"total"`
	Hits  []map[string]any `json:"hits"`
}

type streamsResponse struct {
	List []map[string]any `json:"list"`
}

func doRequest(ctx context.Context, method, url, auth string, body any) ([]byte, int, error) {
	var reqBody io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, 0, fmt.Errorf("marshal: %w", err)
		}
		reqBody = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, url, reqBody)
	if err != nil {
		return nil, 0, fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Authorization", auth)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, 0, fmt.Errorf("http: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	data, err := io.ReadAll(resp.Body)
	return data, resp.StatusCode, err
}

func searchHits(ctx context.Context, baseURL, streamType, auth string, startUS, endUS int64) ([]map[string]any, error) {
	sql := `select * from "default" order by _timestamp desc limit 500`
	body := searchRequest{Query: searchQuery{SQL: sql, StartTime: startUS, EndTime: endUS}}
	data, status, err := doRequest(ctx, http.MethodPost,
		baseURL+"/_search?type="+streamType, auth, body)
	if err != nil {
		return nil, err
	}
	if status >= 400 {
		if strings.Contains(string(data), "Search stream not found") {
			return nil, nil
		}
		return nil, fmt.Errorf("OpenObserve API returned status %d: %s", status, data)
	}
	var sr searchResponse
	if err := json.Unmarshal(data, &sr); err != nil {
		return nil, fmt.Errorf("unmarshal: %w", err)
	}
	return sr.Hits, nil
}

func streamNames(ctx context.Context, baseURL, streamType, auth string) (map[string]struct{}, error) {
	data, status, err := doRequest(ctx, http.MethodGet,
		baseURL+"/streams?type="+streamType, auth, nil)
	if err != nil {
		return nil, err
	}
	if status >= 400 {
		return nil, fmt.Errorf("OpenObserve streams API returned status %d", status)
	}
	var sr streamsResponse
	if err := json.Unmarshal(data, &sr); err != nil {
		return nil, fmt.Errorf("unmarshal: %w", err)
	}
	result := make(map[string]struct{}, len(sr.List))
	for _, item := range sr.List {
		if name, ok := item["name"].(string); ok {
			result[name] = struct{}{}
		}
	}
	return result, nil
}

func requiredSignals() map[string]struct{} {
	raw := os.Getenv("OPENOBSERVE_REQUIRED_SIGNALS")
	if raw == "" {
		raw = "logs"
	}
	result := make(map[string]struct{})
	valid := map[string]struct{}{"logs": {}, "metrics": {}, "traces": {}}
	for _, part := range strings.Split(raw, ",") {
		part = strings.TrimSpace(strings.ToLower(part))
		if _, ok := valid[part]; !ok {
			fmt.Fprintf(os.Stderr, "invalid signal: %q\n", part)
			os.Exit(1)
		}
		result[part] = struct{}{}
	}
	return result
}

func countLogsForRunID(hits []map[string]any, logEvent, runID string) int {
	count := 0
	for _, h := range hits {
		if h["event"] == logEvent && h["run_id"] == runID {
			count++
		}
	}
	return count
}

func countTraces(hits []map[string]any, traceName string) int {
	count := 0
	for _, h := range hits {
		if h["operation_name"] == traceName {
			count++
		}
	}
	return count
}

func runEmitBinary(runID string) error {
	// Try to find and run the compiled emit binary, falling back to go run.
	emitBin := os.Getenv("EMIT_BINARY")
	var cmd *exec.Cmd
	if emitBin != "" {
		cmd = exec.Command(emitBin) //#nosec G204,G702 -- controlled input from env
	} else {
		// go run the emit example relative to this file's location.
		cmd = exec.Command("go", "run",
			"./examples/openobserve/01_emit_all_signals")
	}
	cmd.Env = append(os.Environ(), "PROVIDE_EXAMPLE_RUN_ID="+runID)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

func main() { //nolint:gocyclo // verification script with sequential checks
	baseURL := requireEnv("OPENOBSERVE_URL")
	for len(baseURL) > 0 && baseURL[len(baseURL)-1] == '/' {
		baseURL = baseURL[:len(baseURL)-1]
	}
	user := requireEnv("OPENOBSERVE_USER")
	password := requireEnv("OPENOBSERVE_PASSWORD")
	auth := authHeader(user, password)

	runID := fmt.Sprintf("%d", time.Now().Unix())
	_ = os.Setenv("PROVIDE_EXAMPLE_RUN_ID", runID)

	ctx := context.Background()
	startUS := time.Now().Add(-2 * time.Hour).UnixMicro()
	traceName := "example.openobserve.work." + runID
	metricStream := strings.ReplaceAll("example.openobserve.requests."+runID, ".", "_")
	logEvent := "example.openobserve.jsonlog"
	required := requiredSignals()

	// Snapshot counts before emitting.
	beforeLogHits, _ := searchHits(ctx, baseURL, "logs", auth, startUS, time.Now().UnixMicro())
	beforeTraceHits, _ := searchHits(ctx, baseURL, "traces", auth, startUS, time.Now().UnixMicro())
	beforeMetricStreams, _ := streamNames(ctx, baseURL, "metrics", auth)
	before := map[string]any{
		"logs":                   countLogsForRunID(beforeLogHits, logEvent, runID),
		"traces":                 countTraces(beforeTraceHits, traceName),
		"metrics_stream_present": func() bool { _, ok := beforeMetricStreams[metricStream]; return ok }(),
	}
	fmt.Printf("before=%v\n", before)
	fmt.Printf("required_signals=%v\n", sortedKeys(required))

	// Run the emit example.
	if err := runEmitBinary(runID); err != nil {
		fmt.Fprintf(os.Stderr, "emit failed: %v\n", err)
		os.Exit(1)
	}

	// Poll for up to 30s.
	deadline := time.Now().Add(30 * time.Second)
	after := map[string]any{
		"logs":                   0,
		"traces":                 0,
		"metrics_stream_present": false,
	}
	for time.Now().Before(deadline) {
		endUS := time.Now().UnixMicro()
		logHits, _ := searchHits(ctx, baseURL, "logs", auth, startUS, endUS)
		traceHits, _ := searchHits(ctx, baseURL, "traces", auth, startUS, endUS)
		metricStreams, _ := streamNames(ctx, baseURL, "metrics", auth)

		logCount := countLogsForRunID(logHits, logEvent, runID)
		traceCount := countTraces(traceHits, traceName)
		_, metricPresent := metricStreams[metricStream]

		after["logs"] = logCount
		after["traces"] = traceCount
		after["metrics_stream_present"] = metricPresent

		_, needLogs := required["logs"]
		_, needTraces := required["traces"]
		_, needMetrics := required["metrics"]

		logsOK := !needLogs || logCount > before["logs"].(int)
		tracesOK := !needTraces || traceCount > before["traces"].(int)
		metricsOK := !needMetrics || metricPresent

		if logsOK && tracesOK && metricsOK {
			break
		}
		time.Sleep(1 * time.Second)
	}

	fmt.Printf("after=%v\n", after)

	var missing []string
	if _, need := required["logs"]; need {
		if after["logs"].(int) <= before["logs"].(int) {
			missing = append(missing, "logs")
		}
	}
	if _, need := required["traces"]; need {
		if after["traces"].(int) <= before["traces"].(int) {
			missing = append(missing, "traces")
		}
	}
	if _, need := required["metrics"]; need {
		if !after["metrics_stream_present"].(bool) {
			missing = append(missing, "metrics")
		}
	}

	if len(missing) > 0 {
		fmt.Fprintf(os.Stderr, "ingestion did not increase for: %s\n", strings.Join(missing, ", "))
		os.Exit(1)
	}
	fmt.Println("verification passed")
}

func sortedKeys(m map[string]struct{}) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	// Simple insertion sort for small sets.
	for i := 1; i < len(keys); i++ {
		for j := i; j > 0 && keys[j] < keys[j-1]; j-- {
			keys[j], keys[j-1] = keys[j-1], keys[j]
		}
	}
	return keys
}
