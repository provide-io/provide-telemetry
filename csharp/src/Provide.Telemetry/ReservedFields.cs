// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

/// <summary>
/// Reporting reserved root fields whose caller value a stamped value replaced.
/// </summary>
/// <remarks>
/// <c>reserved_root_fields.replacement_reporting</c> in
/// <c>spec/telemetry-api.yaml</c>. Replacing a field silently loses the caller's
/// data — a <c>version</c> meaning a schema version, say — so each replacement
/// adds to <see cref="HealthSnapshot.ReservedFieldReplacements"/>, and the first
/// replacement of each field in the process logs one warning naming the field,
/// never its value. A record is built only once admission has passed, so a
/// refused record is neither counted nor warned about; the warning is logged
/// while the record is built, so it reaches the output just before the record.
/// </remarks>
internal static class ReservedFields
{
    internal const string WarningEvent = "logger.reserved_field.replaced";
    internal const string WarningLogger = "provide.telemetry.logger";

    private static readonly object WarnedLock = new();
    private static readonly HashSet<string> Warned = new(StringComparer.Ordinal);

    // Set while this thread logs a warning. The warning is an ordinary record
    // and runs the same stamping, so a reserved field in bound context would
    // otherwise count again, against a record the caller never wrote.
    [ThreadStatic]
    private static bool _warning;

    /// <summary>
    /// The canonical names of the reserved fields whose caller value, under any
    /// spelling, differs from the value the SDK stamps, in canonical order.
    /// </summary>
    internal static List<string> Replaced(
        IReadOnlyDictionary<string, object?> payload,
        TelemetryConfig config,
        string? traceId,
        string? spanId)
    {
        var replaced = new List<string>();
        Check(payload, replaced, "service", config.ServiceName, "service", CanonicalLogRecord.ServiceNameKey);
        Check(payload, replaced, "env", config.Environment, "env", CanonicalLogRecord.EnvironmentKey);
        Check(payload, replaced, "version", config.Version, "version");
        Check(payload, replaced, "trace_id", traceId, CanonicalLogRecord.TraceIdKey);
        Check(payload, replaced, "span_id", spanId, CanonicalLogRecord.SpanIdKey);
        return replaced;
    }

    /// <summary>Count <paramref name="replaced"/> and warn about each first replacement.</summary>
    internal static void Report(IReadOnlyList<string> replaced)
    {
        if (replaced.Count == 0 || _warning) return;
        Health.RecordReservedFieldReplacements(replaced.Count);
        List<string> first;
        lock (WarnedLock)
        {
            first = replaced.Where(Warned.Add).ToList();
        }
        if (first.Count == 0) return;
        var logger = Logging.GetLogger(WarningLogger);
        _warning = true;
        try
        {
            foreach (var field in first)
            {
                logger.Warn(WarningEvent, new Dictionary<string, object?>(StringComparer.Ordinal) { ["field"] = field });
            }
        }
        finally
        {
            _warning = false;
        }
    }

    /// <summary>Forget which fields have been warned about (test helper).</summary>
    internal static void Reset()
    {
        lock (WarnedLock)
        {
            Warned.Clear();
        }
    }

    private static void Check(
        IReadOnlyDictionary<string, object?> payload,
        List<string> replaced,
        string field,
        string? stamped,
        params string[] spellings)
    {
        if (string.IsNullOrEmpty(stamped)) return;
        foreach (var key in spellings)
        {
            if (payload.TryGetValue(key, out var caller) && !Equals(caller, stamped))
            {
                replaced.Add(field);
                return;
            }
        }
    }
}
