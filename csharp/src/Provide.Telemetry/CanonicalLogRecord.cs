// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

/// <summary>
/// One log event, built once in core and consumed unchanged by every renderer.
/// </summary>
/// <remarks>
/// The local renderer and the OTel bridge used to each assemble their own field
/// names from the config object, which is how <c>service.name</c> and
/// <c>trace.id</c> reached the wire while every other SDK emitted the snake_case
/// spelling. Building the record once removes the second assembly site: a
/// renderer may choose an output syntax, never a field vocabulary.
/// </remarks>
public sealed record CanonicalLogRecord(
    DateTimeOffset Timestamp,
    string Level,
    string Event,
    string ServiceName,
    string? Environment,
    string? TraceId,
    string? SpanId,
    string? ErrorFingerprint,
    IReadOnlyDictionary<string, object?> Attributes)
{
    /// <summary>Attribute key carrying the service identity.</summary>
    public const string ServiceNameKey = "service_name";

    /// <summary>Attribute key carrying the deployment environment.</summary>
    public const string EnvironmentKey = "environment";

    /// <summary>Attribute key carrying the W3C trace identifier.</summary>
    public const string TraceIdKey = "trace_id";

    /// <summary>Attribute key carrying the W3C span identifier.</summary>
    public const string SpanIdKey = "span_id";

    /// <summary>Attribute key carrying the stable error fingerprint.</summary>
    public const string ErrorFingerprintKey = "error_fingerprint";

    /// <summary>Logger name, empty for the root logger.</summary>
    public string LoggerName { get; init; } = "";

    /// <summary>Service version, empty when unset.</summary>
    public string Version { get; init; } = "";

    /// <summary>
    /// Assemble a record, folding identity and trace context into
    /// <see cref="Attributes"/> under their canonical snake_case keys.
    /// </summary>
    /// <remarks>
    /// Caller-supplied fields win over nothing: identity keys are written after
    /// the user's, because a caller who binds <c>service_name</c> by hand is
    /// describing a different service than the one this process is, and the
    /// receipt/backend consumers key off the real identity.
    /// </remarks>
    public static CanonicalLogRecord Create(
        DateTimeOffset timestamp,
        string level,
        string message,
        string loggerName,
        TelemetryConfig config,
        string traceId,
        string spanId,
        IReadOnlyDictionary<string, object?> fields,
        string? errorFingerprint = null)
    {
        var attributes = new Dictionary<string, object?>(fields, StringComparer.Ordinal);
        // A stamped identity field also displaces its wire name, which is the
        // spelling the envelope and every other SDK give it: a caller's
        // "service" beside a stamped "service_name" would reach the OTel
        // bridge as two answers to one question (reserved_root_fields).
        Displace(attributes, "service", config.ServiceName);
        Displace(attributes, "env", config.Environment);
        Displace(attributes, "version", config.Version);
        Put(attributes, ServiceNameKey, config.ServiceName);
        Put(attributes, EnvironmentKey, config.Environment);
        Put(attributes, TraceIdKey, traceId);
        Put(attributes, SpanIdKey, spanId);
        Put(attributes, ErrorFingerprintKey, errorFingerprint);

        return new CanonicalLogRecord(
            timestamp,
            level,
            message,
            config.ServiceName,
            NullIfEmpty(config.Environment),
            NullIfEmpty(traceId),
            NullIfEmpty(spanId),
            NullIfEmpty(errorFingerprint),
            attributes)
        {
            LoggerName = loggerName,
            Version = config.Version,
        };
    }

    /// <summary>
    /// Project the record onto the canonical log-line field names.
    /// </summary>
    /// <remarks>
    /// The wire vocabulary is pinned by <c>log_output_format</c> in
    /// <c>spec/behavioral_fixtures.yaml</c> and is deliberately terser than the
    /// attribute vocabulary — <c>service</c>, not <c>service_name</c> — because
    /// the identity fields sit at the envelope's top level where the "of what"
    /// is already implied. Attribute keys that collide with an envelope key are
    /// dropped rather than overwriting it.
    /// </remarks>
    public IReadOnlyDictionary<string, object?> ToWireEnvelope(bool includeTimestamp)
    {
        var output = new Dictionary<string, object?>(StringComparer.Ordinal);
        if (includeTimestamp)
        {
            output["timestamp"] = Timestamp.UtcDateTime.ToString(
                "yyyy-MM-ddTHH:mm:ss.fffZ", System.Globalization.CultureInfo.InvariantCulture);
        }
        output["level"] = Level;
        output["message"] = Event;
        Put(output, "logger_name", LoggerName);
        Put(output, "service", ServiceName);
        Put(output, "env", Environment);
        Put(output, "version", Version);
        Put(output, "trace_id", TraceId);
        Put(output, "span_id", SpanId);
        Put(output, ErrorFingerprintKey, ErrorFingerprint);

        foreach (var (key, value) in Attributes)
        {
            if (IsStampedIdentityKey(key) || output.ContainsKey(key)) continue;
            output[key] = value;
        }
        return output;
    }

    // A stamped identity attribute is already carried by the envelope under its
    // terser name; re-emitting it from Attributes would put both spellings on
    // one line, which is exactly the drift this record exists to end. One the
    // SDK did not stamp is the caller's own field, and stands like any other —
    // the reserved_root_fields rule in spec/telemetry-api.yaml. trace_id and
    // span_id share their envelope name, so the ContainsKey test covers them.
    private bool IsStampedIdentityKey(string key) => key switch
    {
        ServiceNameKey => !string.IsNullOrEmpty(ServiceName),
        EnvironmentKey => Environment is not null,
        _ => false,
    };

    private static void Displace(Dictionary<string, object?> target, string key, string? stamped)
    {
        if (!string.IsNullOrEmpty(stamped)) target.Remove(key);
    }

    private static void Put(Dictionary<string, object?> target, string key, string? value)
    {
        if (string.IsNullOrEmpty(value)) return;
        target[key] = value;
    }

    private static string? NullIfEmpty(string? value) => string.IsNullOrEmpty(value) ? null : value;
}
