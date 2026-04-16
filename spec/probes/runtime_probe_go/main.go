// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

const (
	traceID = "0af7651916cd43dd8448eb211c80319c"
	spanID  = "b7ad6b7169203331"
)

func extractJSONLine(output string) map[string]any {
	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "{") {
			continue
		}
		var record map[string]any
		if err := json.Unmarshal([]byte(line), &record); err == nil {
			return record
		}
	}
	panic(fmt.Sprintf("no JSON object found in output: %q", output))
}

func captureRecord(message string) map[string]any {
	r, w, err := os.Pipe()
	if err != nil {
		panic(err)
	}
	orig := os.Stderr
	os.Stderr = w
	defer func() {
		os.Stderr = orig
	}()

	ctx := telemetry.SetTraceContext(context.Background(), traceID, spanID)
	telemetry.GetLogger(ctx, "probe").Info(message)
	_ = w.Close()
	data, _ := io.ReadAll(r)
	return extractJSONLine(string(data))
}

func caseLazyInitLogger() map[string]any {
	telemetry.ResetForTests()
	return map[string]any{"case": "lazy_init_logger", "record": captureRecord("log.output.parity")}
}

func caseStrictSchemaRejection() map[string]any {
	telemetry.ResetForTests()
	_, _ = telemetry.SetupTelemetry()
	record := captureRecord("Bad.Event.Ok")
	_ = telemetry.ShutdownTelemetry(context.Background())
	return map[string]any{
		"case":         "strict_schema_rejection",
		"emitted":      true,
		"schema_error": record["_schema_error"] != nil,
	}
}

func caseRequiredKeysRejection() map[string]any {
	telemetry.ResetForTests()
	_, _ = telemetry.SetupTelemetry()
	record := captureRecord("user.auth.ok")
	_ = telemetry.ShutdownTelemetry(context.Background())
	return map[string]any{
		"case":         "required_keys_rejection",
		"emitted":      true,
		"schema_error": record["_schema_error"] != nil,
	}
}

func caseInvalidConfig() map[string]any {
	telemetry.ResetForTests()
	_, err := telemetry.SetupTelemetry()
	return map[string]any{"case": "invalid_config", "raised": err != nil}
}

func caseFailOpenExporterInit() map[string]any {
	telemetry.ResetForTests()
	_, _ = telemetry.SetupTelemetry()
	status := telemetry.GetRuntimeStatus()
	_ = telemetry.ShutdownTelemetry(context.Background())
	return map[string]any{
		"case":              "fail_open_exporter_init",
		"setup_done":        status.SetupDone,
		"providers_cleared": !status.Providers.Logs && !status.Providers.Traces && !status.Providers.Metrics,
		"fallback_all":      status.Fallback.Logs && status.Fallback.Traces && status.Fallback.Metrics,
	}
}

func caseSignalEnablement() map[string]any {
	telemetry.ResetForTests()
	_, _ = telemetry.SetupTelemetry()
	status := telemetry.GetRuntimeStatus()
	_ = telemetry.ShutdownTelemetry(context.Background())
	return map[string]any{
		"case":            "signal_enablement",
		"setup_done":      status.SetupDone,
		"logs_enabled":    status.Signals.Logs,
		"traces_enabled":  status.Signals.Traces,
		"metrics_enabled": status.Signals.Metrics,
	}
}

func caseShutdownReSetup() map[string]any {
	telemetry.ResetForTests()
	_, _ = telemetry.SetupTelemetry()
	first := telemetry.GetRuntimeStatus()
	_ = telemetry.ShutdownTelemetry(context.Background())
	second := telemetry.GetRuntimeStatus()
	_, _ = telemetry.SetupTelemetry()
	third := telemetry.GetRuntimeStatus()
	_ = telemetry.ShutdownTelemetry(context.Background())
	return map[string]any{
		"case":                   "shutdown_re_setup",
		"first_setup_done":       first.SetupDone,
		"shutdown_cleared_setup": !second.SetupDone,
		"re_setup_done":          third.SetupDone,
		"signals_match":          first.Signals == third.Signals,
		"providers_match":        first.Providers == third.Providers,
	}
}

func main() {
	caseID := os.Getenv("PROVIDE_PARITY_PROBE_CASE")
	var result map[string]any
	switch caseID {
	case "lazy_init_logger":
		result = caseLazyInitLogger()
	case "strict_schema_rejection":
		result = caseStrictSchemaRejection()
	case "required_keys_rejection":
		result = caseRequiredKeysRejection()
	case "invalid_config":
		result = caseInvalidConfig()
	case "fail_open_exporter_init":
		result = caseFailOpenExporterInit()
	case "signal_enablement":
		result = caseSignalEnablement()
	case "shutdown_re_setup":
		result = caseShutdownReSetup()
	default:
		panic("unknown case: " + caseID)
	}
	data, _ := json.Marshal(result)
	fmt.Println(string(data))
}
