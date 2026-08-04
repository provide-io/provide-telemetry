// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


using System.Diagnostics;
using System.Diagnostics.Metrics;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using OpenTelemetry;
using OpenTelemetry.Exporter;
using OpenTelemetry.Logs;
using OpenTelemetry.Metrics;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

namespace Provide.Telemetry.Otel;

/// <summary>
/// Optional OpenTelemetry wiring. When no endpoint is configured, stays no-op.
/// </summary>
internal static class OtelBackend
{
    private static readonly object Gate = new();
    private static TracerProvider? _tracerProvider;
    private static MeterProvider? _meterProvider;
    private static ActivitySource? _activitySource;
    private static Meter? _meter;
    private static bool _logsInstalled;
    private static bool _tracesInstalled;
    private static bool _metricsInstalled;
    private static bool _hostTraces;
    private static bool _hostMetrics;
    private static bool _hostLogs;
    private static string _serviceName = "provide-service";

    // Real OpenTelemetry .NET OTLP HTTP/protobuf log pipeline (LoggerFactory + OtlpLogExporter).
    private static ServiceProvider? _logServices;
    private static ILoggerFactory? _loggerFactory;
    private static LoggerProvider? _loggerProvider;
    private static ILogger? _otelLogger;

    /// <summary>Mark host-owned providers as present (for adoption/status reporting).</summary>
    public static void MarkHostProviders(bool traces = false, bool metrics = false, bool logs = false)
    {
        lock (Gate)
        {
            _hostTraces = traces;
            _hostMetrics = metrics;
            _hostLogs = logs;
        }
    }

    public static (bool Logs, bool Traces, bool Metrics) ProviderFlags()
    {
        lock (Gate)
        {
            return (
                _logsInstalled || _hostLogs,
                _tracesInstalled || _hostTraces,
                _metricsInstalled || _hostMetrics);
        }
    }

    public static (bool Logs, bool Traces, bool Metrics) TrySetup(TelemetryConfig cfg)
    {
        lock (Gate)
        {
            ShutdownUnlocked();
            // Host adoption survives our own provider install/teardown of owned providers,
            // but a full test reset clears host marks via ShutdownUnlocked.
            _serviceName = cfg.ServiceName;
            var resource = ResourceBuilder.CreateDefault()
                .AddService(serviceName: cfg.ServiceName, serviceVersion: cfg.Version)
                .AddAttributes(new[]
                {
                    new KeyValuePair<string, object>("deployment.environment", cfg.Environment),
                });

            bool logs = false, traces = false, metrics = false;

            // OTel options constructors re-read OTEL_EXPORTER_OTLP_HEADERS from the
            // environment. We already mapped those into TelemetryConfig — clear the
            // process env temporarily so headers are not applied twice (duplicate keys
            // throw ArgumentException inside OtlpExportClient).
            using var _env = new EnvOverride(
                ("OTEL_EXPORTER_OTLP_HEADERS", null),
                ("OTEL_EXPORTER_OTLP_ENDPOINT", null),
                ("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", null),
                ("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", null),
                ("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", null));

            var tracesEp = FirstNonEmpty(cfg.Tracing.OtlpEndpoint);
            if (cfg.Tracing.Enabled && !string.IsNullOrEmpty(tracesEp))
            {
                try
                {
                    var traceHeaders = new Dictionary<string, string>(
                        cfg.Tracing.OtlpHeaders, StringComparer.OrdinalIgnoreCase);
                    EnsureAuthHeader(traceHeaders);
                    var builder = Sdk.CreateTracerProviderBuilder()
                        .SetResourceBuilder(resource)
                        .AddSource("Provide.Telemetry")
                        .SetSampler(new ParentBasedSampler(
                            new TraceIdRatioBasedSampler(cfg.EffectiveTracesSampleRate())))
                        .AddOtlpExporter(o =>
                        {
                            o.Endpoint = BuildSignalUri(tracesEp!, "traces");
                            o.Protocol = OtlpExportProtocol.HttpProtobuf;
                            o.Headers = FormatHeaders(traceHeaders);
                        });
                    _tracerProvider = builder.Build();
                    _activitySource = new ActivitySource("Provide.Telemetry");
                    traces = true;
                }
                catch
                {
                    if (!cfg.Exporter.TracesFailOpen) throw;
                    traces = false;
                }
            }

            var metricsEp = FirstNonEmpty(cfg.Metrics.OtlpEndpoint);
            if (cfg.Metrics.Enabled && !string.IsNullOrEmpty(metricsEp))
            {
                try
                {
                    var metricHeaders = new Dictionary<string, string>(
                        cfg.Metrics.OtlpHeaders, StringComparer.OrdinalIgnoreCase);
                    EnsureAuthHeader(metricHeaders);
                    var builder = Sdk.CreateMeterProviderBuilder()
                        .SetResourceBuilder(resource)
                        .AddMeter("Provide.Telemetry")
                        .AddOtlpExporter(o =>
                        {
                            o.Endpoint = BuildSignalUri(metricsEp!, "metrics");
                            o.Protocol = OtlpExportProtocol.HttpProtobuf;
                            o.Headers = FormatHeaders(metricHeaders);
                        });
                    _meterProvider = builder.Build();
                    _meter = new Meter("Provide.Telemetry");
                    metrics = true;
                }
                catch
                {
                    if (!cfg.Exporter.MetricsFailOpen) throw;
                    metrics = false;
                }
            }

            var logsEp = FirstNonEmpty(cfg.Logging.OtlpEndpoint);
            if (cfg.Logging.OtlpEnabled && !string.IsNullOrEmpty(logsEp))
            {
                try
                {
                    var logHeaders = new Dictionary<string, string>(cfg.Logging.OtlpHeaders, StringComparer.OrdinalIgnoreCase);
                    EnsureAuthHeader(logHeaders);
                    var endpoint = BuildSignalUri(logsEp!, "logs");
                    var headerStr = FormatHeaders(logHeaders);
                    var resourceCopy = resource;

                    var services = new ServiceCollection();
                    services.AddLogging(lb =>
                    {
                        lb.ClearProviders();
                        lb.SetMinimumLevel(LogLevel.Trace);
                        lb.AddOpenTelemetry(o =>
                        {
                            o.IncludeFormattedMessage = true;
                            o.IncludeScopes = true;
                            o.ParseStateValues = true;
                            o.SetResourceBuilder(resourceCopy);
                            o.AddOtlpExporter(e =>
                            {
                                e.Endpoint = endpoint;
                                e.Protocol = OtlpExportProtocol.HttpProtobuf;
                                e.Headers = headerStr;
                            });
                        });
                    });
                    _logServices = services.BuildServiceProvider();
                    _loggerFactory = _logServices.GetRequiredService<ILoggerFactory>();
                    // LoggerProvider is registered in DI by AddOpenTelemetry logging.
                    _loggerProvider = _logServices.GetService<LoggerProvider>();
                    _otelLogger = _loggerFactory.CreateLogger("Provide.Telemetry");
                    logs = _loggerProvider is not null || _otelLogger is not null;
                }
                catch
                {
                    if (!cfg.Exporter.LogsFailOpen) throw;
                    DisposeLogPipeline();
                    logs = false;
                }
            }

            _logsInstalled = logs;
            _tracesInstalled = traces;
            _metricsInstalled = metrics;
            return (logs, traces, metrics);
        }
    }

    public static ITracer? GetTracer(string name = "")
    {
        lock (Gate)
        {
            if (_activitySource is null) return null;
            return new OtelTracer(_activitySource, name);
        }
    }

    public static IMeter? GetMeter(string name = "")
    {
        lock (Gate)
        {
            if (_meter is null) return null;
            return new OtelMeter(_meter);
        }
    }

    public static void EmitLog(string level, string message, Dictionary<string, object?> fields)
    {
        lock (Gate)
        {
            if (!_logsInstalled || _otelLogger is null) return;
            var logLevel = MapLevel(level);
            // Emit over OTLP via OpenTelemetryLoggerProvider → OtlpLogExporter (HTTP/protobuf).
            using (_otelLogger.BeginScope(fields))
            {
                _otelLogger.Log(logLevel, "{Message}", message);
            }
        }
    }

    private static LogLevel MapLevel(string level) => level.ToUpperInvariant() switch
    {
        "TRACE" => LogLevel.Trace,
        "DEBUG" => LogLevel.Debug,
        "INFO" => LogLevel.Information,
        "WARN" or "WARNING" => LogLevel.Warning,
        "ERROR" => LogLevel.Error,
        "CRITICAL" => LogLevel.Critical,
        _ => LogLevel.Information,
    };

    public static void RecordCounter(long value, IReadOnlyDictionary<string, object?>? attrs)
    {
        // Fallback counters already hold values; OTel instruments created on demand by OtelMeter.
        _ = value; _ = attrs;
    }

    public static void RecordGauge(double value, IReadOnlyDictionary<string, object?>? attrs)
    {
        _ = value; _ = attrs;
    }

    public static void RecordHistogram(double value, IReadOnlyDictionary<string, object?>? attrs)
    {
        _ = value; _ = attrs;
    }

    public static FlushResult Flush(TimeSpan timeout, bool logs, bool traces, bool metrics)
    {
        var result = new FlushResult
        {
            Logs = new SignalFlushResult { NotInstalled = !logs },
            Traces = new SignalFlushResult { NotInstalled = !traces },
            Metrics = new SignalFlushResult { NotInstalled = !metrics },
        };
        lock (Gate)
        {
            var timeoutMs = (int)Math.Clamp(timeout.TotalMilliseconds, 1, int.MaxValue);
            if (traces && _tracerProvider is not null)
            {
                try
                {
                    // ForceFlush returns bool on MeterProvider; TracerProvider uses extension with ms.
                    result.Traces.Flushed = OpenTelemetry.Trace.TracerProviderExtensions
                        .ForceFlush(_tracerProvider, timeoutMs);
                    if (!result.Traces.Flushed) result.Traces.TimedOut = true;
                }
                catch { result.Traces.Failed = true; }
            }
            if (metrics && _meterProvider is not null)
            {
                try
                {
                    result.Metrics.Flushed = OpenTelemetry.Metrics.MeterProviderExtensions
                        .ForceFlush(_meterProvider, timeoutMs);
                    if (!result.Metrics.Flushed) result.Metrics.TimedOut = true;
                }
                catch { result.Metrics.Failed = true; }
            }
            if (logs && _logsInstalled)
            {
                try
                {
                    result.Logs.Flushed = FlushLogsUnlocked(
                        (int)Math.Clamp(timeout.TotalMilliseconds, 1, int.MaxValue));
                    if (!result.Logs.Flushed) result.Logs.TimedOut = true;
                }
                catch { result.Logs.Failed = true; }
            }
        }
        return result;
    }

    public static void Shutdown()
    {
        lock (Gate) { ShutdownUnlocked(); }
    }

    private static void ShutdownUnlocked()
    {
        try { _tracerProvider?.Dispose(); } catch { /* ignore */ }
        try { _meterProvider?.Dispose(); } catch { /* ignore */ }
        try { _activitySource?.Dispose(); } catch { /* ignore */ }
        try { _meter?.Dispose(); } catch { /* ignore */ }
        DisposeLogPipeline();
        _tracerProvider = null;
        _meterProvider = null;
        _activitySource = null;
        _meter = null;
        _logsInstalled = _tracesInstalled = _metricsInstalled = false;
        // Host adoption marks are preserved across owned provider teardown so
        // reconfigure/shutdown does not forget the host application's providers.
        // Tests clear them via ClearHostProviders / ResetForTests.
    }

    private static void DisposeLogPipeline()
    {
        try { _logServices?.Dispose(); } catch { /* ignore */ }
        _logServices = null;
        _loggerFactory = null;
        _loggerProvider = null;
        _otelLogger = null;
    }

    public static void ClearHostProviders()
    {
        lock (Gate)
        {
            _hostLogs = _hostTraces = _hostMetrics = false;
        }
    }

    private static bool FlushLogsUnlocked(int timeoutMs)
    {
        if (_loggerProvider is null) return _otelLogger is not null;
        return LoggerProviderExtensions.ForceFlush(_loggerProvider, timeoutMs);
    }

    private static string? FirstNonEmpty(string s) =>
        string.IsNullOrWhiteSpace(s) ? null : s.Trim().TrimEnd('/');

    private static Uri BuildSignalUri(string endpoint, string signal)
    {
        // If already ends with /v1/{signal}, use as-is; else append.
        var ep = endpoint.TrimEnd('/');
        if (ep.EndsWith($"/v1/{signal}", StringComparison.OrdinalIgnoreCase))
            return new Uri(ep);
        if (ep.Contains("/v1/", StringComparison.OrdinalIgnoreCase))
            return new Uri(ep);
        if (!Uri.TryCreate($"{ep}/v1/{signal}", UriKind.Absolute, out var uri))
        {
            throw new ConfigurationError($"invalid OTLP endpoint: {endpoint}");
        }
        return uri;
    }

    private static string FormatHeaders(Dictionary<string, string> headers)
    {
        if (headers.Count == 0) return "";
        // Deduplicate case-insensitively; last write wins.
        var dedup = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var (k, v) in headers) dedup[k] = v;
        return string.Join(",", dedup.Select(kv => $"{kv.Key}={kv.Value}"));
    }

    private static void EnsureAuthHeader(Dictionary<string, string> headers)
    {
        if (headers.Keys.Any(k => k.Equals("Authorization", StringComparison.OrdinalIgnoreCase)))
            return;
        var user = Environment.GetEnvironmentVariable("OPENOBSERVE_USER");
        var pass = Environment.GetEnvironmentVariable("OPENOBSERVE_PASSWORD");
        if (string.IsNullOrEmpty(user) || string.IsNullOrEmpty(pass)) return;
        var token = Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes($"{user}:{pass}"));
        headers["Authorization"] = $"Basic {token}";
    }
}

