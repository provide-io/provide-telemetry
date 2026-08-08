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
using OpenTelemetry.Trace;

using Provide.Telemetry;

namespace Provide.Telemetry.OpenTelemetry;

/// <summary>
/// OTLP delivery for the three signals, behind <see cref="ITelemetryBackend"/>.
/// </summary>
/// <remarks>
/// One instance owns one lifecycle generation's providers. Nothing here is
/// static: an instance is created by <see cref="OpenTelemetryBackendRegistration"/>
/// at start and disposed at shutdown, so a restart cannot observe the previous
/// generation's exporters.
/// </remarks>
internal sealed class OpenTelemetryBackend : ITelemetryBackend
{
    private readonly object _gate = new();
    private TracerProvider? _tracerProvider;
    private MeterProvider? _meterProvider;
    private ActivitySource? _activitySource;
    private Meter? _meter;
    private ServiceProvider? _logServices;
    private LoggerProvider? _loggerProvider;
    private ILogger? _otelLogger;
    private bool _disposed;

    public ProviderFlags Providers { get; private set; }

    public OpenTelemetryBackend(TelemetryConfig config)
    {
        ArgumentNullException.ThrowIfNull(config);
        Providers = Install(config);
    }

    private ProviderFlags Install(TelemetryConfig config)
    {
        var resource = OtelResource.Build(config);
        var traces = InstallTraces(config, resource);
        var metrics = InstallMetrics(config, resource);
        var logs = InstallLogs(config, resource);
        return new ProviderFlags(logs, traces, metrics);
    }

    private bool InstallTraces(TelemetryConfig config, global::OpenTelemetry.Resources.ResourceBuilder resource)
    {
        var endpoint = Endpoints.Normalize(config.Tracing.OtlpEndpoint);
        if (!config.Tracing.Enabled || endpoint is null) return false;
        try
        {
            _tracerProvider = Sdk.CreateTracerProviderBuilder()
                .SetResourceBuilder(resource)
                .AddSource(InstrumentationName)
                .SetSampler(new ParentBasedSampler(
                    new TraceIdRatioBasedSampler(config.EffectiveTracesSampleRate())))
                .AddOtlpExporter(o => Endpoints.Apply(o, endpoint, "traces", config.Tracing.OtlpHeaders))
                .Build();
            _activitySource = new ActivitySource(InstrumentationName);
            return true;
        }
        catch
        {
            if (!config.Exporter.TracesFailOpen) throw;
            return false;
        }
    }

    private bool InstallMetrics(TelemetryConfig config, global::OpenTelemetry.Resources.ResourceBuilder resource)
    {
        var endpoint = Endpoints.Normalize(config.Metrics.OtlpEndpoint);
        if (!config.Metrics.Enabled || endpoint is null) return false;
        try
        {
            _meterProvider = Sdk.CreateMeterProviderBuilder()
                .SetResourceBuilder(resource)
                .AddMeter(InstrumentationName)
                .AddOtlpExporter(o => Endpoints.Apply(o, endpoint, "metrics", config.Metrics.OtlpHeaders))
                .Build();
            _meter = new Meter(InstrumentationName);
            return true;
        }
        catch
        {
            if (!config.Exporter.MetricsFailOpen) throw;
            return false;
        }
    }

    private bool InstallLogs(TelemetryConfig config, global::OpenTelemetry.Resources.ResourceBuilder resource)
    {
        var endpoint = Endpoints.Normalize(config.Logging.OtlpEndpoint);
        if (!config.Logging.OtlpEnabled || endpoint is null) return false;
        try
        {
            var headers = config.Logging.OtlpHeaders;
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
                    o.SetResourceBuilder(resource);
                    o.AddOtlpExporter(e => Endpoints.Apply(e, endpoint, "logs", headers));
                });
            });
            _logServices = services.BuildServiceProvider();
            _loggerProvider = _logServices.GetService<LoggerProvider>();
            _otelLogger = _logServices.GetRequiredService<ILoggerFactory>().CreateLogger(InstrumentationName);
            return true;
        }
        catch
        {
            if (!config.Exporter.LogsFailOpen) throw;
            DisposeLogPipeline();
            return false;
        }
    }

    internal const string InstrumentationName = "Provide.Telemetry";

    public ITracer? GetTracer(string name)
    {
        lock (_gate)
        {
            return Providers.Traces && _activitySource is not null
                ? new OtelTracer(_activitySource, name)
                : null;
        }
    }

    public IMeter? GetMeter(string name)
    {
        lock (_gate)
        {
            return Providers.Metrics && _meter is not null ? new OtelMeter(_meter) : null;
        }
    }

    /// <summary>
    /// Bridge one already-hardened record onto the OTLP log pipeline.
    /// </summary>
    /// <remarks>
    /// The record's own attribute vocabulary is forwarded verbatim as a logging
    /// scope. Renaming here is what let <c>service.name</c> onto the wire from
    /// one renderer and <c>service_name</c> from another.
    /// </remarks>
    public void EmitLog(CanonicalLogRecord record)
    {
        ArgumentNullException.ThrowIfNull(record);
        ILogger? logger;
        lock (_gate)
        {
            if (!Providers.Logs || _otelLogger is null) return;
            logger = _otelLogger;
        }

        // Outside the lock: a slow exporter must not serialize every caller's
        // log call behind the one that is currently blocked in the pipeline.
        try
        {
            using (logger.BeginScope(record.Attributes))
            {
                logger.Log(MapLevel(record.Level), "{Message}", record.Event);
            }
        }
        catch
        {
            // Delivery is best-effort by contract: a broken exporter degrades
            // telemetry, it does not fault the application's log call.
            Health.RecordExportFailure(Signals.Logs);
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

    public FlushResult Flush(DateTimeOffset deadline) => Drain(deadline, detach: false);

    public void Shutdown(DateTimeOffset deadline)
    {
        Drain(deadline, detach: true);
        DisposeDetached();
    }

    /// <summary>
    /// Drain every owned signal concurrently against one absolute deadline.
    /// </summary>
    /// <remarks>
    /// Concurrent, not sequential: three sequential drains each given the full
    /// timeout means a caller asking for one second can wait three. The deadline
    /// is computed by the caller and shared by every drain, so the whole
    /// operation returns within the budget it was given regardless of how many
    /// signals are installed.
    /// <para>
    /// On shutdown the providers are detached under the lock first and disposed
    /// afterwards, so no caller blocks on <c>Dispose</c> while holding it.
    /// </para>
    /// </remarks>
    private FlushResult Drain(DateTimeOffset deadline, bool detach)
    {
        List<ProviderDrain> drains;
        ProviderFlags owned;
        lock (_gate)
        {
            owned = Providers;
            drains = CollectDrains();
            // Detaching first means a concurrent emit stops reaching a provider
            // that is about to be disposed; the drain below still holds the
            // local references it needs to finish.
            if (detach) Providers = ProviderFlags.None;
        }

        var result = FlushResults.Undrained(owned, TelemetryBackendRegistry.HostProviders);
        ProviderDrains.Run(drains, deadline, result);
        return result;
    }

    private List<ProviderDrain> CollectDrains()
    {
        var drains = new List<ProviderDrain>();
        if (Providers.Traces && _tracerProvider is not null)
        {
            var provider = _tracerProvider;
            drains.Add(new ProviderDrain(Signals.Traces, ms => provider.ForceFlush(ms)));
        }
        if (Providers.Metrics && _meterProvider is not null)
        {
            var provider = _meterProvider;
            drains.Add(new ProviderDrain(Signals.Metrics, ms => provider.ForceFlush(ms)));
        }
        if (Providers.Logs)
        {
            var provider = _loggerProvider;
            var logger = _otelLogger;
            // No LoggerProvider in DI means the pipeline is a plain ILogger with
            // no batch processor to drain — nothing is queued, so an installed
            // logger is already flushed.
            drains.Add(new ProviderDrain(
                Signals.Logs,
                ms => provider is not null ? provider.ForceFlush(ms) : logger is not null));
        }
        return drains;
    }

    private void DisposeDetached()
    {
        TracerProvider? tracerProvider;
        MeterProvider? meterProvider;
        ActivitySource? activitySource;
        Meter? meter;
        lock (_gate)
        {
            (tracerProvider, meterProvider) = (_tracerProvider, _meterProvider);
            (activitySource, meter) = (_activitySource, _meter);
            _tracerProvider = null;
            _meterProvider = null;
            _activitySource = null;
            _meter = null;
        }
        // Disposed outside the lock: TracerProvider.Dispose drains its batch
        // processor, and holding the gate through that would block every
        // concurrent GetTracer for the duration of a network timeout.
        Swallow(() => tracerProvider?.Dispose());
        Swallow(() => meterProvider?.Dispose());
        Swallow(() => activitySource?.Dispose());
        Swallow(() => meter?.Dispose());
        DisposeLogPipeline();
    }

    private void DisposeLogPipeline()
    {
        ServiceProvider? services;
        lock (_gate)
        {
            services = _logServices;
            _logServices = null;
            _loggerProvider = null;
            _otelLogger = null;
        }
        Swallow(() => services?.Dispose());
    }

    // Teardown runs on the shutdown path, where the caller has already decided
    // to stop caring about telemetry; an exporter that throws while closing must
    // not take the application's shutdown with it.
    private static void Swallow(Action action)
    {
        try { action(); }
        catch { /* teardown is best-effort */ }
    }

    public void Dispose()
    {
        lock (_gate)
        {
            if (_disposed) return;
            _disposed = true;
        }
        // Dispose is the un-budgeted path: an already-expired deadline still
        // makes one attempt per signal (ResilienceExecutor's first-attempt rule),
        // so records queued at exit get one chance to leave without the caller
        // waiting on a retry schedule it never asked for.
        Shutdown(DateTimeOffset.UtcNow);
    }
}
