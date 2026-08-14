// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Text.Json;

namespace Provide.Telemetry;

/// <summary>Structured logger emitting the canonical envelope to stderr.</summary>
public sealed class Logger
{
    private readonly string _name;

    public Logger(string name) => _name = name ?? "";

    public void Trace(string message, IReadOnlyDictionary<string, object?>? fields = null) =>
        Emit("TRACE", message, fields);
    public void Debug(string message, IReadOnlyDictionary<string, object?>? fields = null) =>
        Emit("DEBUG", message, fields);
    public void Info(string message, IReadOnlyDictionary<string, object?>? fields = null) =>
        Emit("INFO", message, fields);
    public void Warn(string message, IReadOnlyDictionary<string, object?>? fields = null) =>
        Emit("WARN", message, fields);
    public void Warning(string message, IReadOnlyDictionary<string, object?>? fields = null) =>
        Emit("WARNING", message, fields);
    public void Error(string message, IReadOnlyDictionary<string, object?>? fields = null) =>
        Emit("ERROR", message, fields);
    public void Critical(string message, IReadOnlyDictionary<string, object?>? fields = null) =>
        Emit("CRITICAL", message, fields);

    /// <summary>Log an exception, attaching its stable fingerprint.</summary>
    public void Error(string message, Exception error, IReadOnlyDictionary<string, object?>? fields = null)
    {
        ArgumentNullException.ThrowIfNull(error);
        Emit("ERROR", message, fields, Fingerprint.ComputeErrorFingerprint(error));
    }

    private void Emit(
        string level,
        string message,
        IReadOnlyDictionary<string, object?>? fields,
        string? errorFingerprint = null)
    {
        Setup.EnsureLazyInit();
        var cfg = Setup.GetRuntimeConfig() ?? TelemetryConfig.Default();
        if (!LevelEnabled(level, EffectiveLevel(_name, cfg))) return;

        var merged = Merge(fields);
        var schemaError = ValidateSchema(merged, cfg, message);
        var rendered = cfg.Logging.Sanitize && Pii.DetectSecretInValue(message) ? Pii.Redacted : message;
        var backend = Setup.CurrentBackend;

        SignalPipeline.Process(new LogDispatch
        {
            SamplingKey = message,
            LogLevel = level,
            Harden = () => Pii.HardenPayload(merged, cfg.Logging.PiiMaxDepth),
            Sanitize = hardened => Materialize(
                Pii.SanitizeHardened(hardened, cfg.Logging.Sanitize), schemaError),
            Build = payload => CanonicalLogRecord.Create(
                DateTimeOffset.UtcNow, level, rendered, _name, cfg,
                Context.GetTraceContext().TraceId, Context.GetTraceContext().SpanId,
                payload, errorFingerprint),
            EmitLocal = record => Console.Error.WriteLine(Render(record, cfg)),
            Backend = backend is null ? null : backend.EmitLog,
        });
    }

    private static (IReadOnlyDictionary<string, object?>, IReadOnlyList<PendingRedaction>) Materialize(
        (Dictionary<string, object?> Payload, IReadOnlyList<PendingRedaction> Redactions) sanitized,
        string? schemaError)
    {
        // Attached after redaction so the diagnostic itself is never treated as
        // a caller field and re-sanitized into "***".
        if (schemaError is not null) sanitized.Payload["_schema_error"] = schemaError;
        return (sanitized.Payload, sanitized.Redactions);
    }

    private Dictionary<string, object?> Merge(IReadOnlyDictionary<string, object?>? fields)
    {
        var merged = new Dictionary<string, object?>(StringComparer.Ordinal);
        if (fields is not null)
        {
            foreach (var (k, v) in fields) merged[k] = v;
        }
        foreach (var (k, v) in Context.GetBoundFields())
        {
            if (!merged.ContainsKey(k)) merged[k] = v;
        }
        return merged;
    }

    /// <summary>
    /// Check the event against the schema, returning the complaint rather than throwing.
    /// </summary>
    /// <remarks>
    /// A malformed event name is a developer mistake worth surfacing, but not
    /// worth failing the caller's request over: the diagnostic rides along on
    /// the record as <c>_schema_error</c>.
    /// </remarks>
    private static string? ValidateSchema(
        IReadOnlyDictionary<string, object?> record, TelemetryConfig cfg, string message)
    {
        try
        {
            if (cfg.EventSchema.RequiredKeys.Count > 0)
            {
                Schema.ValidateRequiredKeys(record, cfg.EventSchema.RequiredKeys);
            }
            if (Schema.GetStrictSchema()) Schema.ValidateEventName(message);
            return null;
        }
        catch (EventSchemaError ex)
        {
            return ex.Message;
        }
    }

    private static string Render(CanonicalLogRecord record, TelemetryConfig cfg)
    {
        var output = record.ToWireEnvelope(cfg.Logging.IncludeTimestamp);
        if (string.Equals(cfg.Logging.Format, "json", StringComparison.OrdinalIgnoreCase))
        {
            return JsonSerializer.Serialize(output);
        }
        if (string.Equals(cfg.Logging.Format, "pretty", StringComparison.OrdinalIgnoreCase))
        {
            return PrettyRenderer.Render(output, record);
        }
        return FormatText(output, record);
    }

    private static string FormatText(
        IReadOnlyDictionary<string, object?> output, CanonicalLogRecord record)
    {
        // Every caller-influenced fragment goes through EscapeControl: the
        // console and pretty renderers are line-oriented, so a raw CR/LF here
        // forges an entire additional record, ESC rewrites the operator's
        // terminal, and NUL truncates the line for downstream tooling. JSON
        // output is protected by the serializer and takes the other branch.
        var extras = string.Join(" ", output
            .Where(kv => kv.Key is not ("level" or "message" or "timestamp"))
            .Select(kv =>
                $"{EscapeControl($"{kv.Key}", escapeQuotes: false)}=" +
                $"{EscapeControl($"{kv.Value}", escapeQuotes: false)}"));
        var ts = output.TryGetValue("timestamp", out var t) ? t + " " : "";
        var eventText = EscapeControl(record.Event, escapeQuotes: false);
        return string.IsNullOrEmpty(extras)
            ? $"{ts}[{record.Level}] {eventText}"
            : $"{ts}[{record.Level}] {eventText} {extras}";
    }

    /// <summary>
    /// Escape C0 control characters and DEL into backslash sequences, keeping
    /// the rendered record on exactly one physical line. When
    /// <paramref name="escapeQuotes"/> is set (pretty mode), embedded quotes
    /// are escaped too so they cannot terminate the surrounding quoting.
    /// </summary>
    internal static string EscapeControl(string text, bool escapeQuotes)
    {
        var needsWork = false;
        foreach (var c in text)
        {
            if (c < '\x20' || c == '\x7f' || (escapeQuotes && c == '"'))
            {
                needsWork = true;
                break;
            }
        }
        if (!needsWork) return text;

        var builder = new System.Text.StringBuilder(text.Length + 8);
        foreach (var c in text)
        {
            switch (c)
            {
                case '\n': builder.Append("\\n"); break;
                case '\r': builder.Append("\\r"); break;
                case '\t': builder.Append("\\t"); break;
                case '"' when escapeQuotes: builder.Append("\\\""); break;
                default:
                    if (c < '\x20' || c == '\x7f')
                    {
                        builder.Append("\\u").Append(((int)c).ToString("x4", System.Globalization.CultureInfo.InvariantCulture));
                    }
                    else
                    {
                        builder.Append(c);
                    }
                    break;
            }
        }
        return builder.ToString();
    }

    private static string EffectiveLevel(string name, TelemetryConfig cfg)
    {
        var best = cfg.Logging.Level;
        var bestLen = -1;
        foreach (var (module, level) in cfg.Logging.ModuleLevels)
        {
            if ((name == module || name.StartsWith(module + ".", StringComparison.Ordinal))
                && module.Length > bestLen)
            {
                best = level;
                bestLen = module.Length;
            }
        }
        return best;
    }

    private static readonly Dictionary<string, int> Rank = new(StringComparer.OrdinalIgnoreCase)
    {
        ["TRACE"] = 0,
        ["DEBUG"] = 10,
        ["INFO"] = 20,
        ["WARN"] = 30,
        ["WARNING"] = 30,
        ["ERROR"] = 40,
        ["CRITICAL"] = 50,
    };

    private static bool LevelEnabled(string messageLevel, string configured)
    {
        var ml = Rank.GetValueOrDefault(messageLevel, 20);
        var cl = Rank.GetValueOrDefault(configured, 20);
        return ml >= cl;
    }
}

public static class Logging
{
    /// <summary>Pre-built default logger instance.</summary>
    public static Logger Logger { get; } = new("");

    public static Logger GetLogger(string name) => new(name ?? "");
}

/// <summary>Builds canonical records without emitting them.</summary>
/// <remarks>
/// Exists so callers and tests can inspect exactly what the renderers will see,
/// which is the only way to assert that the record's field vocabulary is the
/// canonical one rather than whichever renderer happened to run.
/// </remarks>
public static class Capture
{
    /// <summary>Build the record an exception would produce.</summary>
    public static CanonicalLogRecord Error(
        Exception error,
        string? message = null,
        IReadOnlyDictionary<string, object?>? fields = null)
    {
        ArgumentNullException.ThrowIfNull(error);
        var cfg = Setup.GetRuntimeConfig() ?? TelemetryConfig.Default();
        var (traceId, spanId) = Context.GetTraceContext();
        return CanonicalLogRecord.Create(
            DateTimeOffset.UtcNow,
            "ERROR",
            message ?? error.Message,
            "",
            cfg,
            traceId,
            spanId,
            fields ?? new Dictionary<string, object?>(StringComparer.Ordinal),
            Fingerprint.ComputeErrorFingerprint(error));
    }
}
