// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

public sealed class SamplingPolicy
{
    public double DefaultRate { get; set; } = 1.0;
    public Dictionary<string, double>? Overrides { get; set; }
}

public sealed class QueuePolicy
{
    public int LogsMaxSize { get; set; }
    public int TracesMaxSize { get; set; }
    public int MetricsMaxSize { get; set; }
}

/// <summary>
/// Per-signal export policy.
/// </summary>
/// <remarks>
/// The defaults are the schema's, not this SDK's own: zero retries and zero
/// backoff, matching <c>PROVIDE_EXPORTER_*_RETRIES</c> in
/// <c>spec/telemetry-api.yaml</c>. They used to be 3 and 0.5s, so a C# service
/// that set no exporter environment at all retried four times where the other
/// four SDKs tried once.
/// <para>
/// There is no <c>AllowBlockingInEventLoop</c>. Python and Go carry one because
/// <c>run_with_resilience</c> can find itself on an event loop and has to decide
/// whether to block it; .NET has no such loop to guard, so the field was only
/// ever stored, cloned and handed back by <c>GetExporterPolicy</c> without a
/// single decision reading it.
/// </para>
/// </remarks>
public sealed class ExporterPolicy
{
    public int Retries { get; set; }
    public double BackoffSeconds { get; set; }

    /// <summary>
    /// Per-signal export deadline; zero or less disables the circuit breaker.
    /// </summary>
    /// <remarks>
    /// The <c>&gt; 0</c> reading is Python's (<c>resilience.py:190</c>): with no
    /// timeout there is no pool to saturate and so nothing for the breaker to
    /// shed. Settable only through <c>SetExporterPolicy</c> — the spec gives C#
    /// no <c>PROVIDE_EXPORTER_*_TIMEOUT_SECONDS</c> variable, so
    /// <see cref="ExporterPolicyConfig"/> offers no way in.
    /// </remarks>
    public double TimeoutSeconds { get; set; } = 10.0;

    public bool FailOpen { get; set; } = true;
}

public sealed class CardinalityLimit
{
    public int MaxValues { get; set; } = 1;
    public double TtlSeconds { get; set; } = 1.0;
}

public sealed class PIIRule
{
    public IReadOnlyList<string> Path { get; set; } = Array.Empty<string>();
    public string Mode { get; set; } = PiiModes.Redact;

    /// <summary>
    /// How many Unicode scalar values <see cref="PiiModes.Truncate"/> keeps
    /// before the suffix. Unset means the cross-SDK default of 8; zero keeps
    /// nothing but the suffix; a negative value is clamped to zero.
    /// </summary>
    public int TruncateTo { get; set; } = Pii.DefaultTruncateTo;
}

public static class PiiModes
{
    public const string Redact = "redact";
    public const string Drop = "drop";
    public const string Hash = "hash";
    public const string Truncate = "truncate";
    public const string Pass = "pass";
}

public sealed class HealthSnapshot
{
    public long LogsEmitted { get; set; }
    public long LogsDropped { get; set; }
    public long LogsExportFailures { get; set; }
    public long LogsRetries { get; set; }
    public double LogsExportLatencyMs { get; set; }
    public long LogsAsyncBlockingRisk { get; set; }
    public string LogsCircuitState { get; set; } = "closed";
    public long LogsCircuitOpenCount { get; set; }

    public long TracesEmitted { get; set; }
    public long TracesDropped { get; set; }
    public long TracesExportFailures { get; set; }
    public long TracesRetries { get; set; }
    public double TracesExportLatencyMs { get; set; }
    public long TracesAsyncBlockingRisk { get; set; }
    public string TracesCircuitState { get; set; } = "closed";
    public long TracesCircuitOpenCount { get; set; }

    public long MetricsEmitted { get; set; }
    public long MetricsDropped { get; set; }
    public long MetricsExportFailures { get; set; }
    public long MetricsRetries { get; set; }
    public double MetricsExportLatencyMs { get; set; }
    public long MetricsAsyncBlockingRisk { get; set; }
    public string MetricsCircuitState { get; set; } = "closed";
    public long MetricsCircuitOpenCount { get; set; }

    /// <summary>Receipts a sink refused or faulted on. The 26th canonical field.</summary>
    public long ReceiptFailures { get; set; }

    public string SetupError { get; set; } = "";
}

public sealed class RuntimeOverrides
{
    public string? LogLevel { get; set; }
    public string? LogFormat { get; set; }
    public bool? Sanitize { get; set; }
    public double? SamplingLogsRate { get; set; }
    public double? SamplingTracesRate { get; set; }
    public double? SamplingMetricsRate { get; set; }
    public bool? StrictSchema { get; set; }
    public Dictionary<string, string>? ModuleLevels { get; set; }
}

public sealed class SignalFlushResult
{
    public bool Flushed { get; set; }
    public bool NotInstalled { get; set; }
    public bool NotOwned { get; set; }
    public bool TimedOut { get; set; }
    public bool Failed { get; set; }
}

public sealed class FlushResult
{
    public SignalFlushResult Logs { get; set; } = new();
    public SignalFlushResult Traces { get; set; } = new();
    public SignalFlushResult Metrics { get; set; } = new();
}

public sealed class ReconfigureResult
{
    public bool Applied { get; set; }
    public TelemetryConfig? Previous { get; set; }
    public TelemetryConfig? Current { get; set; }
    public string Error { get; set; } = "";
    public RuntimeState State { get; set; } = RuntimeState.Ready;
}

public enum ProviderMode
{
    Owned,
    Host,
    Local,
}

public enum RuntimeState
{
    Local,
    Starting,
    Ready,
    Degraded,
    Reconfiguring,
    Stopping,
    Stopped,
}

public sealed class SignalStatus
{
    public bool Logs { get; set; }
    public bool Traces { get; set; }
    public bool Metrics { get; set; }
}

public sealed class RuntimeStatus
{
    public bool SetupDone { get; set; }
    public SignalStatus Signals { get; set; } = new();
    public SignalStatus Providers { get; set; } = new();
    public SignalStatus Fallback { get; set; } = new();
    public string SetupError { get; set; } = "";
}

public sealed class EventRecord
{
    public string Event { get; set; } = "";
    public string Domain { get; set; } = "";
    public string Action { get; set; } = "";
    public string Resource { get; set; } = "";
    public string Status { get; set; } = "";
}

public sealed class PropagationContext
{
    public string Traceparent { get; set; } = "";
    public string Tracestate { get; set; } = "";
    public string Baggage { get; set; } = "";
    public string TraceID { get; set; } = "";
    public string SpanID { get; set; } = "";
}

/// <summary>Value returned by GetTraceContext (trace_id + span_id).</summary>
public readonly record struct TraceContextValue(string TraceId, string SpanId);

/// <summary>Receipt emitted when PII redactions occur.</summary>
public sealed class RedactionReceipt
{
    public string ReceiptId { get; set; } = "";
    public string FieldPath { get; set; } = "";
    public string Action { get; set; } = "";
    public string ServiceName { get; set; } = "";
    public string Timestamp { get; set; } = "";
    public string OriginalHash { get; set; } = "";
    /// <summary>HMAC-SHA256 hex of the canonical payload; empty when unsigned.</summary>
    public string Hmac { get; set; } = "";
}
