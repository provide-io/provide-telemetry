// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


namespace Provide.Telemetry;

/// <summary>Idempotent process-wide setup/flush/shutdown.</summary>
public static class Setup
{
    private static readonly object Gate = new();
    private static LifecycleGeneration? _generation;
    private static long _generationCounter;
    private static string _setupError = "";

    /// <summary>Default budget for a flush or shutdown drain.</summary>
    private static readonly TimeSpan DefaultDrainTimeout = TimeSpan.FromSeconds(10);

    public static TelemetryConfig SetupTelemetry(TelemetryConfig? config = null)
    {
        ITelemetryBackend? backend = null;
        lock (Gate)
        {
            // Idempotent: first call wins; later calls ignore config args.
            if (_generation is not null) return _generation.Config.Clone();

            TelemetryConfig cfg;
            try
            {
                cfg = config?.Clone() ?? ConfigEnv.ConfigFromEnv();
            }
            catch (Exception ex) when (ex is not ConfigurationError)
            {
                throw new ConfigurationError(ex.Message, ex);
            }

            // The env path validated as it parsed; an explicit config has been
            // through no parser, so nothing has range-checked it yet.
            ValidateRetriesCeiling(cfg);

            Consent.LoadConsentFromEnv();
            ApplyRuntimePolicies(cfg);
            backend = TelemetryBackendRegistry.Create(cfg);
            _generation = Publish(cfg, backend, RuntimeState.Ready);
            _setupError = "";
            Health.SetSetupError("");
            return cfg.Clone();
        }
    }

    public static void ShutdownTelemetry()
    {
        // The deadline is computed once, before the lock, and shared by every
        // signal drain: a caller asking for ten seconds gets ten, not ten per
        // installed provider.
        var deadline = DateTimeOffset.UtcNow + DefaultDrainTimeout;
        ITelemetryBackend? backend;
        lock (Gate)
        {
            backend = _generation?.Backend;
            _generation = null;
            Schema.SetStrictSchema(false);
        }

        // Outside the lock: draining talks to the network, and holding the
        // lifecycle gate through a collector timeout would block every
        // concurrent GetRuntimeStatus for the same duration.
        backend?.Shutdown(deadline);
        backend?.Dispose();
    }

    public static FlushResult FlushTelemetry(TimeSpan? timeout = null)
    {
        var budget = timeout ?? DefaultDrainTimeout;
        var deadline = DateTimeOffset.UtcNow + (budget > TimeSpan.Zero ? budget : TimeSpan.Zero);
        ITelemetryBackend? backend;
        lock (Gate)
        {
            backend = _generation?.Backend;
        }

        // Flush preserves the installed providers; only shutdown detaches them.
        return backend?.Flush(deadline)
               ?? FlushResults.Undrained(ProviderFlags.None, TelemetryBackendRegistry.HostProviders);
    }

    /// <summary>The backend for the current generation, or null in fallback mode.</summary>
    internal static ITelemetryBackend? CurrentBackend
    {
        get { lock (Gate) { return _generation?.Backend; } }
    }

    private static LifecycleGeneration Publish(
        TelemetryConfig cfg, ITelemetryBackend? backend, RuntimeState state) =>
        new(++_generationCounter, cfg, backend, state);

    public static TelemetryConfig? GetRuntimeConfig()
    {
        lock (Gate)
        {
            return _generation?.Config.Clone();
        }
    }

    public static RuntimeStatus GetRuntimeStatus()
    {
        TelemetryConfig cfg;
        bool setupDone;
        ProviderFlags owned;
        string err;
        // One read of one immutable generation: status can no longer report a
        // config from one lifecycle alongside provider flags from another.
        lock (Gate)
        {
            var generation = _generation;
            setupDone = generation is not null;
            cfg = generation?.Config.Clone() ?? SafeConfigFromEnv();
            owned = generation?.Providers ?? ProviderFlags.None;
            err = _setupError;
        }

        var host = TelemetryBackendRegistry.HostProviders;
        // Providers report owned OR host-adopted installations. When a signal is
        // disabled, host adoption is suppressed so status matches the emit path.
        var providersLogs = host.Logs || owned.Logs;
        var providersTraces = (host.Traces || owned.Traces) && (!setupDone || cfg.Tracing.Enabled);
        var providersMetrics = (host.Metrics || owned.Metrics) && (!setupDone || cfg.Metrics.Enabled);

        return new RuntimeStatus
        {
            SetupDone = setupDone,
            Signals = new SignalStatus
            {
                Logs = true,
                Traces = cfg.Tracing.Enabled,
                Metrics = cfg.Metrics.Enabled,
            },
            Providers = new SignalStatus { Logs = providersLogs, Traces = providersTraces, Metrics = providersMetrics },
            Fallback = new SignalStatus
            {
                Logs = !providersLogs,
                Traces = !providersTraces,
                Metrics = !providersMetrics,
            },
            SetupError = err,
        };
    }

    public static void UpdateRuntimeConfig(RuntimeOverrides overrides)
    {
        lock (Gate)
        {
            // Matching Go/Rust/TypeScript: updating config when telemetry was
            // never started or has been shut down is refused rather than
            // silently publishing a config nothing is using.
            var current = _generation ?? throw new TelemetryError(
                "telemetry not set up: call SetupTelemetry first");
            var cfg = current.Config.Clone();
            if (overrides.LogLevel is not null) cfg.Logging.Level = overrides.LogLevel;
            if (overrides.LogFormat is not null) cfg.Logging.Format = overrides.LogFormat;
            if (overrides.Sanitize is not null) cfg.Logging.Sanitize = overrides.Sanitize.Value;
            if (overrides.SamplingLogsRate is not null) cfg.Sampling.LogsRate = overrides.SamplingLogsRate.Value;
            if (overrides.SamplingTracesRate is not null) cfg.Sampling.TracesRate = overrides.SamplingTracesRate.Value;
            if (overrides.SamplingMetricsRate is not null) cfg.Sampling.MetricsRate = overrides.SamplingMetricsRate.Value;
            if (overrides.StrictSchema is not null) cfg.StrictSchema = overrides.StrictSchema.Value;
            if (overrides.ModuleLevels is not null)
            {
                foreach (var (k, v) in overrides.ModuleLevels)
                {
                    cfg.Logging.ModuleLevels[k] = v;
                }
            }
            ApplyRuntimePolicies(cfg);
            _generation = Publish(cfg, current.Backend, current.State);
        }
    }

    public static TelemetryConfig ReloadRuntimeFromEnv()
    {
        lock (Gate)
        {
            var current = _generation ?? throw new TelemetryError(
                "telemetry not set up: call SetupTelemetry first");
            var cfg = ConfigEnv.ConfigFromEnv();
            // Reject provider-changing fields when live providers have them baked in.
            RejectProviderChanging(cfg, current);
            ApplyRuntimePolicies(cfg);
            _generation = Publish(cfg, current.Backend, current.State);
            return cfg.Clone();
        }
    }

    public static TelemetryConfig ReconfigureTelemetry(TelemetryConfig? config = null)
    {
        lock (Gate)
        {
            // Reconfiguring a runtime that was never started — or one already
            // shut down — is an error, not an implicit setup. Publishing a
            // generation here would report SetupDone with no providers
            // installed and no shutdown owed, which is exactly the state Go's
            // ReconfigureTelemetry refuses with this message; UpdateRuntimeConfig
            // and ReloadRuntimeFromEnv above hold the same precondition.
            var current = _generation ?? throw new ConfigurationError(
                "telemetry not set up: call SetupTelemetry first");
            var cfg = config?.Clone() ?? ConfigEnv.ConfigFromEnv();
            ValidateRetriesCeiling(cfg);
            RejectProviderChanging(cfg, current);
            ApplyRuntimePolicies(cfg);
            _generation = Publish(cfg, current.Backend, current.State);
            return cfg.Clone();
        }
    }

    /// <summary>Lazy init when GetLogger is used without SetupTelemetry.</summary>
    internal static void EnsureLazyInit()
    {
        if (Volatile.Read(ref _generation) is not null) return;
        lock (Gate)
        {
            if (_generation is not null) return;
            Consent.LoadConsentFromEnv();
            TelemetryConfig cfg;
            ITelemetryBackend? backend = null;
            try
            {
                cfg = SafeConfigFromEnv();
                // Providers install only when endpoints are configured, so a
                // lazy start against an unconfigured environment degrades to the
                // in-process fallbacks rather than failing.
                backend = TelemetryBackendRegistry.Create(cfg);
            }
            catch (ConfigurationError)
            {
                cfg = TelemetryConfig.Default();
            }
            ApplyRuntimePolicies(cfg);
            _generation = Publish(cfg, backend, RuntimeState.Ready);
        }
    }

    /// <summary>
    /// Facade gate matching Go TracingEnabled: true when no runtime config yet,
    /// otherwise cfg.Tracing.Enabled.
    /// </summary>
    internal static bool IsTracingEnabled()
    {
        lock (Gate)
        {
            return _generation is null || _generation.Config.Tracing.Enabled;
        }
    }

    /// <summary>Facade gate matching Go MetricsEnabled.</summary>
    internal static bool IsMetricsEnabled()
    {
        lock (Gate)
        {
            return _generation is null || _generation.Config.Metrics.Enabled;
        }
    }

    internal static void ResetForTests()
    {
        ITelemetryBackend? backend;
        lock (Gate)
        {
            backend = _generation?.Backend;
            _generation = null;
            _setupError = "";
        }
        backend?.Dispose();
        TelemetryBackendRegistry.ClearHostProviders();
        Sampling.Reset();
        Backpressure.Reset();
        Resilience.Reset();
        Cardinality.Reset();
        Health.Reset();
        Pii.Reset();
        Schema.Reset();
        Context.Reset();
        Classification.Reset();
        Consent.Reset();
        Receipts.Reset();
        Tracing.Reset();
    }

    private static void ApplyRuntimePolicies(TelemetryConfig cfg)
    {
        Sampling.SetSamplingPolicy(Signals.Logs, new SamplingPolicy { DefaultRate = cfg.Sampling.LogsRate });
        Sampling.SetSamplingPolicy(Signals.Traces, new SamplingPolicy { DefaultRate = cfg.EffectiveTracesSampleRate() });
        Sampling.SetSamplingPolicy(Signals.Metrics, new SamplingPolicy { DefaultRate = cfg.Sampling.MetricsRate });
        Backpressure.SetQueuePolicy(new QueuePolicy
        {
            LogsMaxSize = cfg.Backpressure.LogsMaxSize,
            TracesMaxSize = cfg.Backpressure.TracesMaxSize,
            MetricsMaxSize = cfg.Backpressure.MetricsMaxSize,
        });
        Resilience.SetExporterPolicy(Signals.Logs, new ExporterPolicy
        {
            Retries = cfg.Exporter.LogsRetries,
            BackoffSeconds = cfg.Exporter.LogsBackoffSeconds,
            TimeoutSeconds = cfg.Exporter.LogsTimeoutSeconds,
            FailOpen = cfg.Exporter.LogsFailOpen,
            AllowBlockingInEventLoop = cfg.Exporter.LogsAllowBlockingInEventLoop,
        });
        Resilience.SetExporterPolicy(Signals.Traces, new ExporterPolicy
        {
            Retries = cfg.Exporter.TracesRetries,
            BackoffSeconds = cfg.Exporter.TracesBackoffSeconds,
            TimeoutSeconds = cfg.Exporter.TracesTimeoutSeconds,
            FailOpen = cfg.Exporter.TracesFailOpen,
            AllowBlockingInEventLoop = cfg.Exporter.TracesAllowBlockingInEventLoop,
        });
        Resilience.SetExporterPolicy(Signals.Metrics, new ExporterPolicy
        {
            Retries = cfg.Exporter.MetricsRetries,
            BackoffSeconds = cfg.Exporter.MetricsBackoffSeconds,
            TimeoutSeconds = cfg.Exporter.MetricsTimeoutSeconds,
            FailOpen = cfg.Exporter.MetricsFailOpen,
            AllowBlockingInEventLoop = cfg.Exporter.MetricsAllowBlockingInEventLoop,
        });
        Schema.SetStrictSchema(cfg.StrictSchema || cfg.EventSchema.StrictEventName);
    }

    /// <summary>
    /// Reject changes to fields a live provider has baked in. With no owned
    /// provider installed (fallback mode) nothing has baked anything, so any
    /// difference is applicable and no restart is required — matching the
    /// liveness-gated guards in the Go, Rust and TypeScript runtimes. Endpoint
    /// changes are gated per signal: a live tracer does not freeze the logging
    /// endpoint.
    /// </summary>
    private static void RejectProviderChanging(TelemetryConfig next, LifecycleGeneration current)
    {
        var live = current.Providers;
        if (!live.Any)
        {
            return;
        }
        var previous = current.Config;
        var identityChanged =
            !string.Equals(next.ServiceName, previous.ServiceName, StringComparison.Ordinal)
            || !string.Equals(next.Environment, previous.Environment, StringComparison.Ordinal)
            || !string.Equals(next.Version, previous.Version, StringComparison.Ordinal)
            || next.Tracing.Enabled != previous.Tracing.Enabled
            || next.Metrics.Enabled != previous.Metrics.Enabled;
        var logsChanged = live.Logs
            && !string.Equals(next.Logging.OtlpEndpoint, previous.Logging.OtlpEndpoint, StringComparison.Ordinal);
        var tracesChanged = live.Traces
            && !string.Equals(next.Tracing.OtlpEndpoint, previous.Tracing.OtlpEndpoint, StringComparison.Ordinal);
        var metricsChanged = live.Metrics
            && !string.Equals(next.Metrics.OtlpEndpoint, previous.Metrics.OtlpEndpoint, StringComparison.Ordinal);
        if (identityChanged || logsChanged || tracesChanged || metricsChanged)
        {
            throw new ProviderImmutableError(
                "provider-changing fields cannot be updated via reconfigure; restart the process");
        }
    }

    /// <summary>
    /// Enforce the shared exporter-retries ceiling (100) on an in-memory config.
    /// The env path enforces it as it parses with env-var-named messages; this
    /// covers configs that arrived through no parser.
    /// </summary>
    private static void ValidateRetriesCeiling(TelemetryConfig cfg)
    {
        RejectRetriesAboveCeiling(cfg.Exporter.LogsRetries, "Exporter.LogsRetries");
        RejectRetriesAboveCeiling(cfg.Exporter.TracesRetries, "Exporter.TracesRetries");
        RejectRetriesAboveCeiling(cfg.Exporter.MetricsRetries, "Exporter.MetricsRetries");
    }

    private static void RejectRetriesAboveCeiling(int v, string field)
    {
        if (v > Resilience.MaxExportAttempts - 1)
        {
            throw new ConfigurationError($"{field} must be at most {Resilience.MaxExportAttempts - 1}, got {v}");
        }
    }

    private static TelemetryConfig SafeConfigFromEnv()
    {
        try { return ConfigEnv.ConfigFromEnv(); }
        catch { return TelemetryConfig.Default(); }
    }
}
