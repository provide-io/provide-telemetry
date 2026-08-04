// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


namespace Provide.Telemetry;

/// <summary>Canonical runtime facade object with start/shutdown/flush/getter APIs.</summary>
public sealed class TelemetryRuntime
{
    private readonly TelemetryConfig? _config;
    private ProviderMode _providerMode = ProviderMode.Owned;
    private RuntimeState _state = RuntimeState.Ready;

    public TelemetryRuntime(TelemetryConfig? config = null)
    {
        _config = config?.Clone();
    }

    public ProviderMode ProviderMode => _providerMode;
    public RuntimeState State => _state;

    public TelemetryConfig Start()
    {
        _state = RuntimeState.Starting;
        var cfg = Setup.SetupTelemetry(_config);
        _state = RuntimeState.Ready;
        return cfg;
    }

    public void Shutdown()
    {
        _state = RuntimeState.Stopping;
        Setup.ShutdownTelemetry();
        _state = RuntimeState.Stopped;
    }

    public FlushResult Flush(TimeSpan? timeout = null) => Setup.FlushTelemetry(timeout);

    public Logger GetLogger(string name) => Logging.GetLogger(name);
    public ITracer GetTracer(string name = "") => Tracing.GetTracer(name);
    public IMeter GetMeter(string name = "") => Metrics.GetMeter(name);
    public TelemetryConfig? GetRuntimeConfig() => Setup.GetRuntimeConfig();
    public RuntimeStatus GetRuntimeStatus() => Setup.GetRuntimeStatus();

    public TelemetryConfig UpdateConfig(TelemetryConfig cfg)
    {
        if (cfg is null) throw new ConfigurationError("UpdateConfig requires a non-null config");
        Setup.UpdateRuntimeConfig(new RuntimeOverrides
        {
            LogLevel = cfg.Logging.Level,
            LogFormat = cfg.Logging.Format,
            Sanitize = cfg.Logging.Sanitize,
            SamplingLogsRate = cfg.Sampling.LogsRate,
            SamplingTracesRate = cfg.Sampling.TracesRate,
            SamplingMetricsRate = cfg.Sampling.MetricsRate,
            StrictSchema = cfg.StrictSchema,
        });
        return Setup.GetRuntimeConfig() ?? cfg;
    }

    public TelemetryConfig Reconfigure(TelemetryConfig? cfg = null)
    {
        _state = RuntimeState.Reconfiguring;
        try
        {
            var result = Setup.ReconfigureTelemetry(cfg ?? _config);
            _state = RuntimeState.Ready;
            return result;
        }
        catch
        {
            _state = RuntimeState.Degraded;
            throw;
        }
    }
}
