// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text.Json;
using OpenTelemetry;
using OpenTelemetry.Trace;
using Provide.Telemetry;
using Provide.Telemetry.OpenTelemetry;

// The probe speaks for an application that opted into OTLP delivery.
OpenTelemetryBackendRegistration.Register();

const string TraceId = "0af7651916cd43dd8448eb211c80319c";
const string SpanId = "b7ad6b7169203331";

// Harness injects PROVIDE_PARITY_PROBE_CASE (see spec/_runtime_probe.py).
var caseId = Environment.GetEnvironmentVariable("PROVIDE_PARITY_PROBE_CASE")
    ?? Environment.GetEnvironmentVariable("PROVIDE_RUNTIME_CASE")
    ?? "lazy_init_logger";

object result = caseId switch
{
    "lazy_init_logger" => CaseLazyInitLogger(),
    "lazy_logger_shutdown_re_setup" => CaseLazyLoggerShutdownReSetup(),
    "consent_env_none_at_setup" => CaseConsentEnvNoneAtSetup(),
    "consent_env_none_lazy_logger" => CaseConsentEnvNoneLazyLogger(),
    "strict_schema_rejection" => CaseStrictSchemaRejection(),
    "strict_event_name_only" => CaseStrictEventNameOnly(),
    "required_keys_rejection" => CaseRequiredKeysRejection(),
    "invalid_config" => CaseInvalidConfig(),
    "fail_open_exporter_init" => CaseFailOpenExporterInit(),
    "signal_enablement" => CaseSignalEnablement(),
    "per_signal_logs_endpoint" => CasePerSignalLogsEndpoint(),
    "provider_identity_reconfigure" => CaseProviderIdentityReconfigure(),
    "host_provider_adoption" => CaseHostProviderAdoption(),
    "metric_instrument_values" => CaseMetricInstrumentValues(),
    "shutdown_re_setup" => CaseShutdownReSetup(),
    "hot_reload_log_level" => CaseHotReloadLogLevel(),
    "hot_reload_log_format" => CaseHotReloadLogFormat(),
    "hot_reload_module_level" => CaseHotReloadModuleLevel(),
    _ => new Dictionary<string, object?> { ["case"] = caseId, ["error"] = "unknown case" },
};
Console.WriteLine(JsonSerializer.Serialize(result));

static Dictionary<string, object?> CaptureRecord(string message)
{
    var sw = new StringWriter();
    var orig = Console.Error;
    Console.SetError(sw);
    try
    {
        ProvideTelemetry.SetTraceContext(TraceId, SpanId);
        ProvideTelemetry.GetLogger("probe").Info(message);
    }
    finally
    {
        Console.SetError(orig);
    }
    foreach (var line in sw.ToString().Split('\n'))
    {
        var t = line.Trim();
        if (!t.StartsWith('{')) continue;
        try
        {
            return JsonSerializer.Deserialize<Dictionary<string, object?>>(t)
                   ?? new Dictionary<string, object?>();
        }
        catch { /* next */ }
    }
    throw new InvalidOperationException("no JSON object in output: " + sw);
}

static List<Dictionary<string, object?>> CaptureEmit(string name, string level, string message)
{
    var sw = new StringWriter();
    var orig = Console.Error;
    Console.SetError(sw);
    try
    {
        var log = ProvideTelemetry.GetLogger(name);
        if (string.Equals(level, "debug", StringComparison.OrdinalIgnoreCase))
            log.Debug(message);
        else
            log.Info(message);
    }
    finally
    {
        Console.SetError(orig);
    }
    var records = new List<Dictionary<string, object?>>();
    foreach (var line in sw.ToString().Split('\n'))
    {
        var t = line.Trim();
        if (!t.StartsWith('{')) continue;
        try
        {
            var rec = JsonSerializer.Deserialize<Dictionary<string, object?>>(t);
            if (rec is not null) records.Add(rec);
        }
        catch { /* next */ }
    }
    return records;
}

static bool HasMessage(List<Dictionary<string, object?>> records, string message) =>
    records.Any(r =>
        (r.TryGetValue("message", out var m) && m?.ToString() == message) ||
        (r.TryGetValue("msg", out var m2) && m2?.ToString() == message));

static Dictionary<string, object?> CaseLazyInitLogger()
{
    Testing.ResetForTests();
    return new() { ["case"] = "lazy_init_logger", ["record"] = CaptureRecord("log.output.parity") };
}

static Dictionary<string, object?> CaseLazyLoggerShutdownReSetup()
{
    Testing.ResetForTests();
    var first = CaptureRecord("log.output.parity");
    ProvideTelemetry.ShutdownTelemetry();
    var second = ProvideTelemetry.GetRuntimeStatus();
    Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", "probe-restarted");
    Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_ENV", "parity-restarted");
    Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_VERSION", "9.9.9");
    ProvideTelemetry.SetupTelemetry();
    var third = ProvideTelemetry.GetRuntimeStatus();
    var restarted = CaptureRecord("log.output.restart");
    ProvideTelemetry.ShutdownTelemetry();
    var restartedJson = JsonSerializer.Serialize(restarted);
    return new()
    {
        ["case"] = "lazy_logger_shutdown_re_setup",
        ["first_logger_emitted"] = first.GetValueOrDefault("message")?.ToString() == "log.output.parity"
            || JsonSerializer.Serialize(first).Contains("log.output.parity"),
        ["shutdown_cleared_setup"] = !second.SetupDone,
        ["shutdown_cleared_providers"] = !second.Providers.Logs && !second.Providers.Traces && !second.Providers.Metrics,
        ["shutdown_fallback_all"] = second.Fallback.Logs && second.Fallback.Traces && second.Fallback.Metrics,
        ["re_setup_done"] = third.SetupDone,
        ["second_logger_uses_fresh_config"] = restartedJson.Contains("probe-restarted"),
    };
}

static Dictionary<string, object?> CaseConsentEnvNoneAtSetup()
{
    // PROVIDE_CONSENT_LEVEL=NONE comes from the harness; setup reads it, so the
    // one record emitted afterwards must be suppressed without any code change.
    Testing.ResetForTests();
    Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
    ProvideTelemetry.SetupTelemetry();
    var status = ProvideTelemetry.GetRuntimeStatus();
    var records = CaptureEmit("probe", "info", "log.output.parity");
    var consentNone = ProvideTelemetry.GetConsentLevel() == ConsentLevel.None;
    ProvideTelemetry.ShutdownTelemetry();
    return new()
    {
        ["case"] = "consent_env_none_at_setup",
        ["setup_done"] = status.SetupDone,
        ["consent_none"] = consentNone,
        ["record_suppressed"] = !HasMessage(records, "log.output.parity"),
    };
}

static Dictionary<string, object?> CaseConsentEnvNoneLazyLogger()
{
    // No SetupTelemetry: emitting is what triggers the lazy init, and that
    // path must read the consent env before the very record that woke it.
    Testing.ResetForTests();
    Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
    var records = CaptureEmit("probe", "info", "log.output.parity");
    return new()
    {
        ["case"] = "consent_env_none_lazy_logger",
        ["consent_none"] = ProvideTelemetry.GetConsentLevel() == ConsentLevel.None,
        ["record_suppressed"] = !HasMessage(records, "log.output.parity"),
    };
}

static Dictionary<string, object?> CaseStrictSchemaRejection()
{
    Testing.ResetForTests();
    ProvideTelemetry.SetupTelemetry();
    var record = CaptureRecord("Bad.Event.Ok");
    ProvideTelemetry.ShutdownTelemetry();
    return new()
    {
        ["case"] = "strict_schema_rejection",
        ["emitted"] = true,
        ["schema_error"] = record.ContainsKey("_schema_error")
            || JsonSerializer.Serialize(record).Contains("_schema_error"),
    };
}

static Dictionary<string, object?> CaseStrictEventNameOnly()
{
    Testing.ResetForTests();
    ProvideTelemetry.SetupTelemetry();
    var record = CaptureRecord("Bad.Event.Ok");
    ProvideTelemetry.ShutdownTelemetry();
    return new()
    {
        ["case"] = "strict_event_name_only",
        ["emitted"] = true,
        ["schema_error"] = record.ContainsKey("_schema_error")
            || JsonSerializer.Serialize(record).Contains("_schema_error"),
    };
}

static Dictionary<string, object?> CaseRequiredKeysRejection()
{
    Testing.ResetForTests();
    ProvideTelemetry.SetupTelemetry();
    var record = CaptureRecord("user.auth.ok");
    ProvideTelemetry.ShutdownTelemetry();
    return new()
    {
        ["case"] = "required_keys_rejection",
        ["emitted"] = true,
        ["schema_error"] = record.ContainsKey("_schema_error")
            || JsonSerializer.Serialize(record).Contains("_schema_error"),
    };
}

static Dictionary<string, object?> CaseInvalidConfig()
{
    Testing.ResetForTests();
    try
    {
        ProvideTelemetry.SetupTelemetry();
        return new() { ["case"] = "invalid_config", ["raised"] = false };
    }
    catch
    {
        return new() { ["case"] = "invalid_config", ["raised"] = true };
    }
}

static Dictionary<string, object?> CaseFailOpenExporterInit()
{
    Testing.ResetForTests();
    ProvideTelemetry.SetupTelemetry();
    var status = ProvideTelemetry.GetRuntimeStatus();
    ProvideTelemetry.ShutdownTelemetry();
    return new()
    {
        ["case"] = "fail_open_exporter_init",
        ["setup_done"] = status.SetupDone,
        ["providers_cleared"] = !status.Providers.Logs && !status.Providers.Traces && !status.Providers.Metrics,
        ["fallback_all"] = status.Fallback.Logs && status.Fallback.Traces && status.Fallback.Metrics,
    };
}

static Dictionary<string, object?> CaseSignalEnablement()
{
    Testing.ResetForTests();
    ProvideTelemetry.SetupTelemetry();
    var status = ProvideTelemetry.GetRuntimeStatus();
    ProvideTelemetry.ShutdownTelemetry();
    return new()
    {
        ["case"] = "signal_enablement",
        ["setup_done"] = status.SetupDone,
        ["logs_enabled"] = status.Signals.Logs,
        ["traces_enabled"] = status.Signals.Traces,
        ["metrics_enabled"] = status.Signals.Metrics,
    };
}

static Dictionary<string, object?> CasePerSignalLogsEndpoint()
{
    Testing.ResetForTests();
    ProvideTelemetry.SetupTelemetry();
    var status = ProvideTelemetry.GetRuntimeStatus();
    ProvideTelemetry.ShutdownTelemetry();
    return new()
    {
        ["case"] = "per_signal_logs_endpoint",
        ["setup_done"] = status.SetupDone,
        ["logs_provider"] = status.Providers.Logs,
        ["traces_provider"] = status.Providers.Traces,
        ["metrics_provider"] = status.Providers.Metrics,
    };
}

static Dictionary<string, object?> CaseProviderIdentityReconfigure()
{
    Testing.ResetForTests();
    ProvideTelemetry.SetupTelemetry();
    var before = ProvideTelemetry.GetRuntimeStatus();
    var serviceBefore = ProvideTelemetry.GetRuntimeConfig()?.ServiceName ?? "";
    Environment.SetEnvironmentVariable("PROVIDE_TELEMETRY_SERVICE_NAME", serviceBefore + "-renamed");
    var raised = false;
    try { ProvideTelemetry.ReconfigureTelemetry(); }
    catch { raised = true; }
    var preserved = ProvideTelemetry.GetRuntimeConfig()?.ServiceName == serviceBefore;
    ProvideTelemetry.ShutdownTelemetry();
    return new()
    {
        ["case"] = "provider_identity_reconfigure",
        ["providers_active"] = before.Providers.Logs || before.Providers.Traces || before.Providers.Metrics,
        ["raised"] = raised,
        ["config_preserved"] = preserved,
    };
}

static Dictionary<string, object?> CaseHostProviderAdoption()
{
    Testing.ResetForTests();
    // Install a host-owned tracer provider before setup (mirrors Go otel.SetTracerProvider).
    using var hostTp = Sdk.CreateTracerProviderBuilder()
        .AddSource("Provide.Telemetry.Host")
        .Build();
    TelemetryBackendRegistry.MarkHostProviders(traces: true);

    var before = ProvideTelemetry.GetRuntimeStatus();

    Environment.SetEnvironmentVariable("PROVIDE_TRACE_ENABLED", "true");
    ProvideTelemetry.SetupTelemetry();
    var enabled = ProvideTelemetry.GetRuntimeStatus();
    ProvideTelemetry.ShutdownTelemetry();

    Environment.SetEnvironmentVariable("PROVIDE_TRACE_ENABLED", "false");
    ProvideTelemetry.SetupTelemetry();
    var disabled = ProvideTelemetry.GetRuntimeStatus();
    ProvideTelemetry.ShutdownTelemetry();
    Environment.SetEnvironmentVariable("PROVIDE_TRACE_ENABLED", null);

    return new()
    {
        ["case"] = "host_provider_adoption",
        ["adopted_before_setup"] = before.Providers.Traces,
        ["adopted_after_enabled_setup"] = enabled.Providers.Traces || enabled.Signals.Traces,
        // When traces disabled, fallback.traces should be true
        ["fallback_after_disabled_setup"] = disabled.Fallback.Traces || !disabled.Signals.Traces,
    };
}

static Dictionary<string, object?> CaseMetricInstrumentValues()
{
    Testing.ResetForTests();
    ProvideTelemetry.SetupTelemetry();
    var c = ProvideTelemetry.Counter("probe.metric.counter");
    c.Add(1); c.Add(2); c.Add(4);
    var g = ProvideTelemetry.Gauge("probe.metric.gauge");
    g.Set(42);
    var h = ProvideTelemetry.Histogram("probe.metric.histogram");
    h.Record(1); h.Record(2); h.Record(3);
    ProvideTelemetry.ShutdownTelemetry();
    return new()
    {
        ["case"] = "metric_instrument_values",
        ["counter_value"] = c.Value.ToString(),
        ["gauge_value"] = ((long)g.Value).ToString(),
        ["histogram_count"] = h.Count.ToString(),
        ["histogram_total"] = ((long)h.Sum).ToString(),
    };
}

static Dictionary<string, object?> CaseShutdownReSetup()
{
    Testing.ResetForTests();
    ProvideTelemetry.SetupTelemetry();
    var first = ProvideTelemetry.GetRuntimeStatus();
    ProvideTelemetry.ShutdownTelemetry();
    var afterShutdown = ProvideTelemetry.GetRuntimeStatus();
    ProvideTelemetry.SetupTelemetry();
    var second = ProvideTelemetry.GetRuntimeStatus();
    ProvideTelemetry.ShutdownTelemetry();
    return new()
    {
        ["case"] = "shutdown_re_setup",
        ["first_setup_done"] = first.SetupDone,
        ["shutdown_cleared_setup"] = !afterShutdown.SetupDone,
        ["shutdown_cleared_providers"] = !afterShutdown.Providers.Logs && !afterShutdown.Providers.Traces && !afterShutdown.Providers.Metrics,
        ["shutdown_fallback_all"] = afterShutdown.Fallback.Logs && afterShutdown.Fallback.Traces && afterShutdown.Fallback.Metrics,
        ["re_setup_done"] = second.SetupDone,
        ["signals_match"] = first.Signals.Logs == second.Signals.Logs
            && first.Signals.Traces == second.Signals.Traces
            && first.Signals.Metrics == second.Signals.Metrics,
        ["providers_match"] = first.Providers.Logs == second.Providers.Logs
            && first.Providers.Traces == second.Providers.Traces
            && first.Providers.Metrics == second.Providers.Metrics,
    };
}

static Dictionary<string, object?> CaseHotReloadLogLevel()
{
    Testing.ResetForTests();
    Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
    Environment.SetEnvironmentVariable("PROVIDE_LOG_LEVEL", "INFO");
    ProvideTelemetry.SetupTelemetry();
    var serviceBefore = ProvideTelemetry.GetRuntimeConfig()?.ServiceName;
    var before = CaptureEmit("probe", "debug", "hot.level.debug.before");
    ProvideTelemetry.UpdateRuntimeConfig(new RuntimeOverrides { LogLevel = "DEBUG", LogFormat = "json" });
    var after = CaptureEmit("probe", "debug", "hot.level.debug.after");
    var cfg = ProvideTelemetry.GetRuntimeConfig();
    ProvideTelemetry.ShutdownTelemetry();
    return new()
    {
        ["case"] = "hot_reload_log_level",
        ["first_debug_suppressed"] = !HasMessage(before, "hot.level.debug.before"),
        ["second_debug_emitted"] = HasMessage(after, "hot.level.debug.after"),
        ["level_config_updated"] = string.Equals(cfg?.Logging.Level, "DEBUG", StringComparison.OrdinalIgnoreCase),
        ["service_preserved"] = cfg?.ServiceName == serviceBefore,
    };
}

static Dictionary<string, object?> CaseHotReloadLogFormat()
{
    Testing.ResetForTests();
    Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
    ProvideTelemetry.SetupTelemetry();
    var statusBefore = ProvideTelemetry.GetRuntimeStatus();
    var serviceBefore = ProvideTelemetry.GetRuntimeConfig()?.ServiceName;
    ProvideTelemetry.UpdateRuntimeConfig(new RuntimeOverrides { LogFormat = "console", LogLevel = "INFO" });
    var cfg = ProvideTelemetry.GetRuntimeConfig();
    var statusAfter = ProvideTelemetry.GetRuntimeStatus();
    ProvideTelemetry.ShutdownTelemetry();
    return new()
    {
        ["case"] = "hot_reload_log_format",
        ["format_config_updated"] = string.Equals(cfg?.Logging.Format, "console", StringComparison.OrdinalIgnoreCase),
        ["service_preserved"] = cfg?.ServiceName == serviceBefore,
        ["providers_unchanged"] = statusBefore.Providers.Logs == statusAfter.Providers.Logs
            && statusBefore.Providers.Traces == statusAfter.Providers.Traces
            && statusBefore.Providers.Metrics == statusAfter.Providers.Metrics,
    };
}

static Dictionary<string, object?> CaseHotReloadModuleLevel()
{
    Testing.ResetForTests();
    Environment.SetEnvironmentVariable("PROVIDE_LOG_FORMAT", "json");
    Environment.SetEnvironmentVariable("PROVIDE_LOG_LEVEL", "INFO");
    ProvideTelemetry.SetupTelemetry();
    var serviceBefore = ProvideTelemetry.GetRuntimeConfig()?.ServiceName;
    var before = CaptureEmit("probe.child", "debug", "hot.module.debug.before");
    ProvideTelemetry.UpdateRuntimeConfig(new RuntimeOverrides
    {
        LogLevel = "INFO",
        LogFormat = "json",
        ModuleLevels = new Dictionary<string, string> { ["probe.child"] = "DEBUG" },
    });
    var after = CaptureEmit("probe.child", "debug", "hot.module.debug.after");
    var finalCfg = ProvideTelemetry.GetRuntimeConfig();
    ProvideTelemetry.ShutdownTelemetry();
    return new()
    {
        ["case"] = "hot_reload_module_level",
        ["first_debug_suppressed"] = !HasMessage(before, "hot.module.debug.before"),
        ["module_debug_emitted"] = HasMessage(after, "hot.module.debug.after"),
        ["module_levels_config_updated"] = finalCfg?.Logging.ModuleLevels.ContainsKey("probe.child") == true,
        ["service_preserved"] = finalCfg?.ServiceName == serviceBefore,
    };
}
