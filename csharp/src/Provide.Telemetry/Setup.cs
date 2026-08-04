// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


namespace Provide.Telemetry;

/// <summary>Idempotent process-wide setup/flush/shutdown.</summary>
public static class Setup
{
    private static readonly object Gate = new();
    private static bool _setupDone;
    private static TelemetryConfig? _runtimeCfg;
    private static bool _providersLogs;
    private static bool _providersTraces;
    private static bool _providersMetrics;
    private static string _setupError = "";

    public static TelemetryConfig SetupTelemetry(TelemetryConfig? config = null)
    {
        lock (Gate)
        {
            // Idempotent: first call wins; later calls ignore config args.
            if (_setupDone)
            {
                return _runtimeCfg?.Clone() ?? TelemetryConfig.Default();
            }

            TelemetryConfig cfg;
            try
            {
                cfg = config?.Clone() ?? ConfigEnv.ConfigFromEnv();
            }
            catch (Exception ex) when (ex is not ConfigurationError)
            {
                throw new ConfigurationError(ex.Message, ex);
            }

            Consent.LoadConsentFromEnv();
            ApplyRuntimePolicies(cfg);
            var otel = Otel.OtelBackend.TrySetup(cfg);
            _providersLogs = otel.Logs;
            _providersTraces = otel.Traces;
            _providersMetrics = otel.Metrics;
            _runtimeCfg = cfg;
            _setupDone = true;
            _setupError = "";
            Health.SetSetupError("");
            return cfg.Clone();
        }
    }

    public static void ShutdownTelemetry()
    {
        lock (Gate)
        {
            Otel.OtelBackend.Shutdown();
            _setupDone = false;
            _runtimeCfg = null;
            _providersLogs = _providersTraces = _providersMetrics = false;
            Schema.SetStrictSchema(false);
        }
    }

    public static FlushResult FlushTelemetry(TimeSpan? timeout = null)
    {
        lock (Gate)
        {
            return Otel.OtelBackend.Flush(timeout ?? TimeSpan.FromSeconds(10),
                _providersLogs, _providersTraces, _providersMetrics);
        }
    }

    public static TelemetryConfig? GetRuntimeConfig()
    {
        lock (Gate)
        {
            return _runtimeCfg?.Clone();
        }
    }

    public static RuntimeStatus GetRuntimeStatus()
    {
        TelemetryConfig cfg;
        bool setupDone;
        bool pl, pt, pm;
        string err;
        lock (Gate)
        {
            setupDone = _setupDone;
            cfg = _runtimeCfg?.Clone() ?? SafeConfigFromEnv();
            pl = _providersLogs;
            pt = _providersTraces;
            pm = _providersMetrics;
            err = _setupError;
        }

        var (hl, ht, hm) = Otel.OtelBackend.ProviderFlags();
        // Providers report owned OR host-adopted installations. When a signal is
        // disabled, host adoption is suppressed so status matches the emit path.
        var providersLogs = hl || pl;
        var providersTraces = cfg.Tracing.Enabled && (ht || pt);
        var providersMetrics = cfg.Metrics.Enabled && (hm || pm);
        // Before setup, host marks still report (adoption detection).
        if (!setupDone)
        {
            providersLogs = hl || pl;
            providersTraces = ht || pt;
            providersMetrics = hm || pm;
        }

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
            var cfg = _runtimeCfg?.Clone() ?? SafeConfigFromEnv();
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
            _runtimeCfg = cfg;
        }
    }

    public static TelemetryConfig ReloadRuntimeFromEnv()
    {
        lock (Gate)
        {
            var cfg = ConfigEnv.ConfigFromEnv();
            // Reject provider-changing fields when already set up with providers.
            if (_setupDone && _runtimeCfg is not null)
            {
                RejectProviderChanging(cfg, _runtimeCfg);
            }
            ApplyRuntimePolicies(cfg);
            _runtimeCfg = cfg;
            return cfg.Clone();
        }
    }

    public static TelemetryConfig ReconfigureTelemetry(TelemetryConfig? config = null)
    {
        lock (Gate)
        {
            var previous = _runtimeCfg?.Clone();
            var cfg = config?.Clone() ?? ConfigEnv.ConfigFromEnv();
            if (_setupDone && previous is not null)
            {
                RejectProviderChanging(cfg, previous);
            }
            ApplyRuntimePolicies(cfg);
            _runtimeCfg = cfg;
            return cfg.Clone();
        }
    }

    /// <summary>Lazy init when GetLogger is used without SetupTelemetry.</summary>
    internal static void EnsureLazyInit()
    {
        if (_setupDone) return;
        lock (Gate)
        {
            if (_setupDone) return;
            try
            {
                Consent.LoadConsentFromEnv();
                var cfg = SafeConfigFromEnv();
                ApplyRuntimePolicies(cfg);
                _runtimeCfg = cfg;
                // Mark as set up for logger fields, but do not install OTel providers
                // unless endpoints are configured — graceful degradation.
                var otel = Otel.OtelBackend.TrySetup(cfg);
                _providersLogs = otel.Logs;
                _providersTraces = otel.Traces;
                _providersMetrics = otel.Metrics;
                _setupDone = true;
            }
            catch (ConfigurationError)
            {
                Consent.LoadConsentFromEnv();
                _runtimeCfg = TelemetryConfig.Default();
                ApplyRuntimePolicies(_runtimeCfg);
                _setupDone = true;
            }
        }
    }

    internal static bool IsSetupDone
    {
        get { lock (Gate) return _setupDone; }
    }

    /// <summary>
    /// Facade gate matching Go TracingEnabled: true when no runtime config yet,
    /// otherwise cfg.Tracing.Enabled.
    /// </summary>
    internal static bool IsTracingEnabled()
    {
        lock (Gate)
        {
            return _runtimeCfg is null || _runtimeCfg.Tracing.Enabled;
        }
    }

    /// <summary>Facade gate matching Go MetricsEnabled.</summary>
    internal static bool IsMetricsEnabled()
    {
        lock (Gate)
        {
            return _runtimeCfg is null || _runtimeCfg.Metrics.Enabled;
        }
    }

    internal static void ResetForTests()
    {
        lock (Gate)
        {
            Otel.OtelBackend.Shutdown();
            Otel.OtelBackend.ClearHostProviders();
            _setupDone = false;
            _runtimeCfg = null;
            _providersLogs = _providersTraces = _providersMetrics = false;
            _setupError = "";
        }
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

    private static void RejectProviderChanging(TelemetryConfig next, TelemetryConfig current)
    {
        if (!string.Equals(next.ServiceName, current.ServiceName, StringComparison.Ordinal)
            || !string.Equals(next.Environment, current.Environment, StringComparison.Ordinal)
            || !string.Equals(next.Version, current.Version, StringComparison.Ordinal)
            || !string.Equals(next.Logging.OtlpEndpoint, current.Logging.OtlpEndpoint, StringComparison.Ordinal)
            || !string.Equals(next.Tracing.OtlpEndpoint, current.Tracing.OtlpEndpoint, StringComparison.Ordinal)
            || !string.Equals(next.Metrics.OtlpEndpoint, current.Metrics.OtlpEndpoint, StringComparison.Ordinal)
            || next.Tracing.Enabled != current.Tracing.Enabled
            || next.Metrics.Enabled != current.Metrics.Enabled)
        {
            throw new ProviderImmutableError(
                "provider-changing fields cannot be updated via reconfigure; restart the process");
        }
    }

    private static TelemetryConfig SafeConfigFromEnv()
    {
        try { return ConfigEnv.ConfigFromEnv(); }
        catch { return TelemetryConfig.Default(); }
    }
}
