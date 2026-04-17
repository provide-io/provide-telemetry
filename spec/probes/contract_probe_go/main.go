// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

// Contract probe interpreter for Go.
//
// Reads PROVIDE_CONTRACT_CASE env var, loads spec/contract_fixtures.yaml,
// executes the named case step-by-step using the real public API, and emits
// JSON to stdout: {"case": "<id>", "variables": {...}}.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"gopkg.in/yaml.v3"
)

// fixtureFile is the contract fixtures document.
type fixtureFile struct {
	ContractCases map[string]contractCase `yaml:"contract_cases"`
}

// contractCase is a single test case with ordered steps and expectations.
type contractCase struct {
	Description string         `yaml:"description"`
	Steps       []step         `yaml:"steps"`
	Expect      map[string]any `yaml:"expect"`
}

// step is a single operation in a case.
type step struct {
	Op          string         `yaml:"op"`
	Traceparent string         `yaml:"traceparent"`
	Baggage     string         `yaml:"baggage"`
	Message     string         `yaml:"message"`
	Fields      map[string]any `yaml:"fields"`
	Into        string         `yaml:"into"`
	Overrides   map[string]any `yaml:"overrides"`
}

// ctx is the shared context threaded through all operations. Go propagation
// works by returning new contexts, so we update this package-level var.
var ctx = context.Background()

// baseCtx tracks the context without any propagation overlay. bind_context
// updates both ctx and baseCtx; bind_propagation overlays propagation on top
// of baseCtx so clear_propagation can restore without losing bound fields.
var baseCtx = context.Background()

// logBuffer captures stderr output between emit_log and capture_log steps.
var logBuffer *os.File

// loadFixtures reads and parses the contract YAML file.
func loadFixtures() fixtureFile {
	// Path relative to go/ working directory.
	data, err := os.ReadFile("../spec/contract_fixtures.yaml")
	if err != nil {
		panic(fmt.Sprintf("failed to read fixtures: %v", err))
	}
	var f fixtureFile
	if err := yaml.Unmarshal(data, &f); err != nil {
		panic(fmt.Sprintf("failed to parse fixtures: %v", err))
	}
	return f
}

// applyOverrides sets PROVIDE_* env vars from the cross-language override map.
// Returns a cleanup function that unsets them.
func applyOverrides(overrides map[string]any) func() {
	var keys []string
	if v, ok := overrides["serviceName"]; ok {
		os.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", fmt.Sprint(v))
		keys = append(keys, "PROVIDE_TELEMETRY_SERVICE_NAME")
	}
	if v, ok := overrides["environment"]; ok {
		os.Setenv("PROVIDE_TELEMETRY_ENVIRONMENT", fmt.Sprint(v))
		keys = append(keys, "PROVIDE_TELEMETRY_ENVIRONMENT")
	}
	if v, ok := overrides["samplingLogsRate"]; ok {
		os.Setenv("PROVIDE_SAMPLING_LOGS_RATE", fmt.Sprint(v))
		keys = append(keys, "PROVIDE_SAMPLING_LOGS_RATE")
	}
	if v, ok := overrides["samplingTracesRate"]; ok {
		os.Setenv("PROVIDE_SAMPLING_TRACES_RATE", fmt.Sprint(v))
		keys = append(keys, "PROVIDE_SAMPLING_TRACES_RATE")
	}
	// Always force JSON format so capture_log can parse output.
	os.Setenv("PROVIDE_LOG_FORMAT", "json")
	keys = append(keys, "PROVIDE_LOG_FORMAT")
	return func() {
		for _, k := range keys {
			os.Unsetenv(k)
		}
	}
}

// opSetup runs SetupTelemetry with optional env-var overrides.
func opSetup(s step, variables map[string]any) {
	telemetry.ResetForTests()
	cleanup := applyOverrides(s.Overrides)
	defer cleanup()
	if _, err := telemetry.SetupTelemetry(); err != nil {
		panic(fmt.Sprintf("setup failed: %v", err))
	}
	// Reset both contexts for fresh setup.
	ctx = context.Background()
	baseCtx = ctx
}

// opSetupInvalid tries SetupTelemetry and captures the error.
func opSetupInvalid(s step, variables map[string]any) {
	telemetry.ResetForTests()
	cleanup := applyOverrides(s.Overrides)
	defer cleanup()
	_, err := telemetry.SetupTelemetry()
	if err != nil {
		variables[s.Into] = map[string]any{
			"raised": true,
			"error":  err.Error(),
		}
	} else {
		variables[s.Into] = map[string]any{
			"raised": false,
			"error":  "",
		}
	}
}

// opShutdown tears down telemetry.
func opShutdown(_ step, _ map[string]any) {
	_ = telemetry.ShutdownTelemetry(context.Background())
}

// opBindPropagation extracts W3C context from headers and binds it.
func opBindPropagation(s step, _ map[string]any) {
	headers := http.Header{}
	if s.Traceparent != "" {
		headers.Set("Traceparent", s.Traceparent)
	}
	if s.Baggage != "" {
		headers.Set("Baggage", s.Baggage)
	}
	pc := telemetry.ExtractW3CContext(headers)
	// Overlay propagation on baseCtx so clear_propagation can restore
	// without losing bound context fields set via bind_context.
	ctx = telemetry.BindPropagationContext(baseCtx, pc)
}

// opClearPropagation removes propagation-derived trace and baggage data
// while preserving any bound context fields set via bind_context.
func opClearPropagation(_ step, _ map[string]any) {
	ctx = baseCtx
}

// opGetTraceContext reads trace/span IDs from the current context.
func opGetTraceContext(s step, variables map[string]any) {
	traceID, spanID := telemetry.GetTraceContext(ctx)
	variables[s.Into] = map[string]any{
		"trace_id": traceID,
		"span_id":  spanID,
	}
}

// opBindContext binds key-value fields into the current context.
// Updates both ctx and baseCtx so bound fields survive clear_propagation.
func opBindContext(s step, _ map[string]any) {
	baseCtx = telemetry.BindContext(baseCtx, s.Fields)
	ctx = telemetry.BindContext(ctx, s.Fields)
}

// opEmitLog emits a log record via GetLogger, capturing stderr output.
func opEmitLog(s step, _ map[string]any) {
	r, w, err := os.Pipe()
	if err != nil {
		panic(fmt.Sprintf("pipe failed: %v", err))
	}
	// Redirect stderr to pipe for capture.
	origStderr := os.Stderr
	os.Stderr = w

	// Build slog args from step fields, excluding "event" (message is first arg).
	var args []any
	for k, v := range s.Fields {
		if k == "event" {
			continue
		}
		args = append(args, k, v)
	}

	telemetry.GetLogger(ctx, "contract").InfoContext(ctx, s.Message, args...)

	os.Stderr = origStderr
	_ = w.Close()

	// Store pipe reader for capture_log.
	logBuffer = r
}

// opCaptureLog reads the last JSON line from the captured stderr output.
func opCaptureLog(s step, variables map[string]any) {
	if logBuffer == nil {
		variables[s.Into] = map[string]any{}
		return
	}
	data, _ := io.ReadAll(logBuffer)
	_ = logBuffer.Close()
	logBuffer = nil

	record := extractJSONRecord(string(data))
	// Normalise Go field names to cross-language contract names:
	// trace.id -> trace_id, span.id -> span_id
	if v, ok := record["trace.id"]; ok {
		record["trace_id"] = v
		delete(record, "trace.id")
	}
	if v, ok := record["span.id"]; ok {
		record["span_id"] = v
		delete(record, "span.id")
	}
	// Ensure message key exists.
	if _, ok := record["message"]; !ok {
		record["message"] = ""
	}
	// Normalise baggage keys: ensure they default to "" if absent.
	for k := range record {
		if strings.HasPrefix(k, "baggage.") {
			// Already present — keep as-is.
			continue
		}
	}
	variables[s.Into] = record
}

// opGetRuntimeStatus reads the current runtime status.
func opGetRuntimeStatus(s step, variables map[string]any) {
	status := telemetry.GetRuntimeStatus()
	cfg := telemetry.GetRuntimeConfig()
	serviceName := ""
	if cfg != nil {
		serviceName = cfg.ServiceName
	}
	variables[s.Into] = map[string]any{
		"active":       status.SetupDone,
		"service_name": serviceName,
	}
}

// extractJSONRecord finds the last JSON object line in output.
func extractJSONRecord(output string) map[string]any {
	lines := strings.Split(output, "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		line := strings.TrimSpace(lines[i])
		if !strings.HasPrefix(line, "{") {
			continue
		}
		var record map[string]any
		if err := json.Unmarshal([]byte(line), &record); err == nil {
			return record
		}
	}
	return map[string]any{}
}

// dispatch maps operation names to handler functions.
var dispatch = map[string]func(step, map[string]any){
	"setup":              opSetup,
	"setup_invalid":      opSetupInvalid,
	"shutdown":           opShutdown,
	"bind_propagation":   opBindPropagation,
	"clear_propagation":  opClearPropagation,
	"get_trace_context":  opGetTraceContext,
	"bind_context":       opBindContext,
	"emit_log":           opEmitLog,
	"capture_log":        opCaptureLog,
	"get_runtime_status": opGetRuntimeStatus,
}

func main() {
	caseID := os.Getenv("PROVIDE_CONTRACT_CASE")
	if caseID == "" {
		fmt.Fprintln(os.Stderr, `{"error":"PROVIDE_CONTRACT_CASE not set"}`)
		os.Exit(1)
	}

	fixtures := loadFixtures()
	tc, ok := fixtures.ContractCases[caseID]
	if !ok {
		fmt.Fprintf(os.Stderr, `{"error":"unknown case: %s"}`+"\n", caseID)
		os.Exit(1)
	}

	variables := map[string]any{}
	for _, s := range tc.Steps {
		handler, found := dispatch[s.Op]
		if !found {
			fmt.Fprintf(os.Stderr, `{"error":"unknown op: %s"}`+"\n", s.Op)
			os.Exit(1)
		}
		handler(s, variables)
	}

	result := map[string]any{
		"case":      caseID,
		"variables": variables,
	}
	data, _ := json.Marshal(result)
	fmt.Println(string(data))
}
