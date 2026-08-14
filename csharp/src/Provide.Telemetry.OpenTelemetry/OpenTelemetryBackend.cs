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

using OtelResourceBuilder = OpenTelemetry.Resources.ResourceBuilder;

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

    private bool InstallTraces(TelemetryConfig config, OtelResourceBuilder resource)
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

    private bool InstallMetrics(TelemetryConfig config, OtelResourceBuilder resource)
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

    private bool InstallLogs(TelemetryConfig config, OtelResourceBuilder resource)
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
            // Nothing has been emitted through a pipeline that failed to
            // install, so there is nothing to drain: an already-expired
            // deadline tears it down without waiting.
            DisposeLogPipeline(DateTimeOffset.UtcNow);
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
        ILogger? logger = null;
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
        DisposeDetached(deadline);
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
        var (drains, owned) = TakeDrains(detach);

        var result = FlushResults.Undrained(owned, TelemetryBackendRegistry.HostProviders);
        ProviderDrains.Run(drains, deadline, result);
        return result;
    }

    /// <summary>
    /// Take the drains and the owned flags under one lock.
    /// </summary>
    /// <remarks>
    /// Detaching first means a concurrent emit stops reaching a provider that is
    /// about to be disposed; the returned drains still hold the references they
    /// need to finish. Returning the pair keeps both values definitely assigned,
    /// so a mutant of either read compiles and gets scored.
    /// </remarks>
    private (List<ProviderDrain> Drains, ProviderFlags Owned) TakeDrains(bool detach)
    {
        lock (_gate)
        {
            var owned = Providers;
            var drains = CollectDrains();
            if (detach) Providers = ProviderFlags.None;
            return (drains, owned);
        }
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

    private void DisposeDetached(DateTimeOffset deadline)
    {
        TracerProvider? tracerProvider = null;
        MeterProvider? meterProvider = null;
        ActivitySource? activitySource = null;
        Meter? meter = null;
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
        //
        // Bounded Shutdown before each Dispose: provider disposal drains the
        // batch processor on OTel's own default timeout, which ignores the
        // deadline this call advertised — against an unreachable collector the
        // caller waited seconds after their budget had expired. A provider
        // whose Shutdown has already run disposes without draining again, so
        // the explicit deadline-clamped Shutdown makes the Dispose cheap. An
        // expired deadline clamps to 0ms, which OTel treats as "don't wait" —
        // preserving the Dispose() path's documented one-attempt rule, which
        // lives in the Drain that precedes this method, not here.
        Swallow(() => tracerProvider?.Shutdown(RemainingMs(deadline)));
        Swallow(() => tracerProvider?.Dispose());
        Swallow(() => meterProvider?.Shutdown(RemainingMs(deadline)));
        Swallow(() => meterProvider?.Dispose());
        Swallow(() => activitySource?.Dispose());
        Swallow(() => meter?.Dispose());
        DisposeLogPipeline(deadline);
    }

    private void DisposeLogPipeline(DateTimeOffset deadline)
    {
        ServiceProvider? services = null;
        LoggerProvider? loggerProvider = null;
        lock (_gate)
        {
            services = _logServices;
            loggerProvider = _loggerProvider;
            _logServices = null;
            _loggerProvider = null;
            _otelLogger = null;
        }
        Swallow(() => loggerProvider?.Shutdown(RemainingMs(deadline)));
        Swallow(() => services?.Dispose());
    }

    /// <summary>Milliseconds left until <paramref name="deadline"/>, clamped to [0, int.MaxValue].</summary>
    internal static int RemainingMs(DateTimeOffset deadline)
    {
        var remaining = (deadline - DateTimeOffset.UtcNow).TotalMilliseconds;
        if (remaining <= 0) return 0;
        return remaining >= int.MaxValue ? int.MaxValue : (int)remaining;
    }

    // Teardown runs on the shutdown path, where the caller has already decided
    // to stop caring about telemetry; an exporter that throws while closing must
    // not take the application's shutdown with it.
    internal static void Swallow(Action action)
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
