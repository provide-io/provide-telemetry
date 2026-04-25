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
	_ "github.com/provide-io/provide-telemetry/go/otel"
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

func caseLazyLoggerShutdownReSetup() map[string]any {
	telemetry.ResetForTests()
	first := captureRecord("log.output.parity")
	_ = telemetry.ShutdownTelemetry(context.Background())
	second := telemetry.GetRuntimeStatus()
	_ = os.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "probe-restarted")
	_ = os.Setenv("PROVIDE_TELEMETRY_ENV", "parity-restarted")
	_ = os.Setenv("PROVIDE_TELEMETRY_VERSION", "9.9.9")
	_, _ = telemetry.SetupTelemetry()
	third := telemetry.GetRuntimeStatus()
	restarted := captureRecord("log.output.restart")
	_ = telemetry.ShutdownTelemetry(context.Background())
	return map[string]any{
		"case":                   "lazy_logger_shutdown_re_setup",
		"first_logger_emitted":   first["message"] == "log.output.parity",
		"shutdown_cleared_setup": !second.SetupDone,
		"shutdown_cleared_providers": !second.Providers.Logs &&
			!second.Providers.Traces &&
			!second.Providers.Metrics,
		"shutdown_fallback_all": second.Fallback.Logs &&
			second.Fallback.Traces &&
			second.Fallback.Metrics,
		"re_setup_done": third.SetupDone,
		"second_logger_uses_fresh_config": restarted["service.name"] == "probe-restarted" &&
			restarted["service.env"] == "parity-restarted" &&
			restarted["service.version"] == "9.9.9",
	}
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

func caseStrictEventNameOnly() map[string]any {
	telemetry.ResetForTests()
	_, _ = telemetry.SetupTelemetry()
	record := captureRecord("Bad.Event.Ok")
	_ = telemetry.ShutdownTelemetry(context.Background())
	return map[string]any{
		"case":         "strict_event_name_only",
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

func casePerSignalLogsEndpoint() map[string]any {
	telemetry.ResetForTests()
	_, _ = telemetry.SetupTelemetry()
	status := telemetry.GetRuntimeStatus()
	_ = telemetry.ShutdownTelemetry(context.Background())
	return map[string]any{
		"case":             "per_signal_logs_endpoint",
		"setup_done":       status.SetupDone,
		"logs_provider":    status.Providers.Logs,
		"traces_provider":  status.Providers.Traces,
		"metrics_provider": status.Providers.Metrics,
	}
}

func caseProviderIdentityReconfigure() map[string]any {
	telemetry.ResetForTests()
	_, _ = telemetry.SetupTelemetry()
	before := telemetry.GetRuntimeStatus()
	serviceBefore := telemetry.GetRuntimeConfig().ServiceName
	_ = os.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", serviceBefore+"-renamed")
	_, err := telemetry.ReconfigureTelemetry(context.Background())
	configPreserved := telemetry.GetRuntimeConfig().ServiceName == serviceBefore
	_ = telemetry.ShutdownTelemetry(context.Background())
	return map[string]any{
		"case":             "provider_identity_reconfigure",
		"providers_active": before.Providers.Logs || before.Providers.Traces || before.Providers.Metrics,
		"raised":           err != nil,
		"config_preserved": configPreserved,
	}
}

func captureEmit(name string, level string, message string) []map[string]any {
	r, w, err := os.Pipe()
	if err != nil {
		panic(err)
	}
	orig := os.Stderr
	os.Stderr = w
	func() {
		defer func() {
			os.Stderr = orig
			_ = w.Close()
		}()
		logger := telemetry.GetLogger(context.Background(), name)
		switch level {
		case "debug":
			logger.Debug(message)
		default:
			logger.Info(message)
		}
	}()
	data, _ := io.ReadAll(r)
	var records []map[string]any
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "{") {
			continue
		}
		var rec map[string]any
		if err := json.Unmarshal([]byte(line), &rec); err == nil {
			records = append(records, rec)
		}
	}
	return records
}

func hasMessage(records []map[string]any, message string) bool {
	for _, rec := range records {
		if rec["message"] == message || rec["msg"] == message {
			return true
		}
	}
	return false
}

func caseHotReloadLogLevel() map[string]any {
	telemetry.ResetForTests()
	_ = os.Setenv("PROVIDE_LOG_FORMAT", "json")
	_ = os.Setenv("PROVIDE_LOG_LEVEL", "INFO")
	_, _ = telemetry.SetupTelemetry()
	serviceBefore := telemetry.GetRuntimeConfig().ServiceName
	before := captureEmit("probe", "debug", "hot.level.debug.before")

	nextLogging := telemetry.DefaultTelemetryConfig().Logging
	nextLogging.Level = telemetry.LogLevelDebug
	nextLogging.Format = telemetry.LogFormatJSON
	nextLogging.IncludeTimestamp = false
	nextLogging.IncludeCaller = false
	if err := telemetry.UpdateRuntimeConfig(telemetry.RuntimeOverrides{Logging: &nextLogging}); err != nil {
		panic(err)
	}
	after := captureEmit("probe", "debug", "hot.level.debug.after")
	cfg := telemetry.GetRuntimeConfig()
	_ = telemetry.ShutdownTelemetry(context.Background())
	return map[string]any{
		"case":                   "hot_reload_log_level",
		"first_debug_suppressed": !hasMessage(before, "hot.level.debug.before"),
		"second_debug_emitted":   hasMessage(after, "hot.level.debug.after"),
		"level_config_updated":   strings.EqualFold(cfg.Logging.Level, "DEBUG"),
		"service_preserved":      cfg.ServiceName == serviceBefore,
	}
}

func caseHotReloadLogFormat() map[string]any {
	telemetry.ResetForTests()
	_ = os.Setenv("PROVIDE_LOG_FORMAT", "json")
	_, _ = telemetry.SetupTelemetry()
	statusBefore := telemetry.GetRuntimeStatus()
	serviceBefore := telemetry.GetRuntimeConfig().ServiceName

	nextLogging := telemetry.DefaultTelemetryConfig().Logging
	nextLogging.Level = telemetry.LogLevelInfo
	nextLogging.Format = telemetry.LogFormatConsole
	nextLogging.IncludeTimestamp = false
	nextLogging.IncludeCaller = false
	if err := telemetry.UpdateRuntimeConfig(telemetry.RuntimeOverrides{Logging: &nextLogging}); err != nil {
		panic(err)
	}
	cfg := telemetry.GetRuntimeConfig()
	statusAfter := telemetry.GetRuntimeStatus()
	_ = telemetry.ShutdownTelemetry(context.Background())
	return map[string]any{
		"case":                   "hot_reload_log_format",
		"format_config_updated":  strings.EqualFold(cfg.Logging.Format, "console"),
		"service_preserved":      cfg.ServiceName == serviceBefore,
		"providers_unchanged":    statusBefore.Providers == statusAfter.Providers,
	}
}

func caseHotReloadModuleLevel() map[string]any {
	telemetry.ResetForTests()
	_ = os.Setenv("PROVIDE_LOG_FORMAT", "json")
	_ = os.Setenv("PROVIDE_LOG_LEVEL", "INFO")
	_, _ = telemetry.SetupTelemetry()
	serviceBefore := telemetry.GetRuntimeConfig().ServiceName
	before := captureEmit("probe.child", "debug", "hot.module.debug.before")

	// Pure module-only promotion: the global level stays at INFO and only
	// the module override lifts `probe.child` to DEBUG.  All four languages
	// must honour this precise contract.
	nextLogging := telemetry.DefaultTelemetryConfig().Logging
	nextLogging.Format = telemetry.LogFormatJSON
	nextLogging.IncludeTimestamp = false
	nextLogging.IncludeCaller = false
	nextLogging.ModuleLevels = map[string]string{"probe.child": telemetry.LogLevelDebug}
	if err := telemetry.UpdateRuntimeConfig(telemetry.RuntimeOverrides{Logging: &nextLogging}); err != nil {
		panic(err)
	}
	after := captureEmit("probe.child", "debug", "hot.module.debug.after")
	cfg := telemetry.GetRuntimeConfig()
	_ = telemetry.ShutdownTelemetry(context.Background())
	return map[string]any{
		"case":                         "hot_reload_module_level",
		"first_debug_suppressed":       !hasMessage(before, "hot.module.debug.before"),
		"module_debug_emitted":         hasMessage(after, "hot.module.debug.after"),
		"module_levels_config_updated": strings.EqualFold(cfg.Logging.ModuleLevels["probe.child"], "DEBUG"),
		"service_preserved":            cfg.ServiceName == serviceBefore,
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
		"shutdown_cleared_providers": !second.Providers.Logs &&
			!second.Providers.Traces &&
			!second.Providers.Metrics,
		"shutdown_fallback_all": second.Fallback.Logs &&
			second.Fallback.Traces &&
			second.Fallback.Metrics,
		"re_setup_done":   third.SetupDone,
		"signals_match":   first.Signals == third.Signals,
		"providers_match": first.Providers == third.Providers,
	}
}

func main() {
	caseID := os.Getenv("PROVIDE_PARITY_PROBE_CASE")
	var result map[string]any
	switch caseID {
	case "lazy_init_logger":
		result = caseLazyInitLogger()
	case "lazy_logger_shutdown_re_setup":
		result = caseLazyLoggerShutdownReSetup()
	case "strict_schema_rejection":
		result = caseStrictSchemaRejection()
	case "strict_event_name_only":
		result = caseStrictEventNameOnly()
	case "required_keys_rejection":
		result = caseRequiredKeysRejection()
	case "invalid_config":
		result = caseInvalidConfig()
	case "fail_open_exporter_init":
		result = caseFailOpenExporterInit()
	case "signal_enablement":
		result = caseSignalEnablement()
	case "per_signal_logs_endpoint":
		result = casePerSignalLogsEndpoint()
	case "provider_identity_reconfigure":
		result = caseProviderIdentityReconfigure()
	case "shutdown_re_setup":
		result = caseShutdownReSetup()
	case "hot_reload_log_level":
		result = caseHotReloadLogLevel()
	case "hot_reload_log_format":
		result = caseHotReloadLogFormat()
	case "hot_reload_module_level":
		result = caseHotReloadModuleLevel()
	default:
		panic("unknown case: " + caseID)
	}
	data, _ := json.Marshal(result)
	fmt.Println(string(data))
}
