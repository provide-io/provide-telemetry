// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Runtime.CompilerServices;
using System.Text.Json;

namespace Provide.Telemetry;

/// <summary>Structured logger emitting the canonical envelope to stderr.</summary>
/// <remarks>
/// Every entry point ends in two optional callsite parameters the compiler
/// fills in — see <see cref="Emit"/>. A caller never writes them; a caller's own
/// logging wrapper declares the same pair and forwards it, so the record blames
/// the application rather than the wrapper.
/// </remarks>
public sealed class Logger
{
    /// <summary>Record field carrying the base name of the calling source file.</summary>
    internal const string FilenameKey = "filename";

    /// <summary>Record field carrying the 1-based line number of the call.</summary>
    internal const string LinenoKey = "lineno";

    private static readonly char[] PathSeparators = { '/', '\\' };

    private readonly string _name;

    public Logger(string name) => _name = name ?? "";

    public void Trace(
        string message,
        IReadOnlyDictionary<string, object?>? fields = null,
        [CallerFilePath] string callerFile = "",
        [CallerLineNumber] int callerLine = 0) =>
        Emit("TRACE", message, fields, callerFile, callerLine);
    public void Debug(
        string message,
        IReadOnlyDictionary<string, object?>? fields = null,
        [CallerFilePath] string callerFile = "",
        [CallerLineNumber] int callerLine = 0) =>
        Emit("DEBUG", message, fields, callerFile, callerLine);
    public void Info(
        string message,
        IReadOnlyDictionary<string, object?>? fields = null,
        [CallerFilePath] string callerFile = "",
        [CallerLineNumber] int callerLine = 0) =>
        Emit("INFO", message, fields, callerFile, callerLine);
    public void Warn(
        string message,
        IReadOnlyDictionary<string, object?>? fields = null,
        [CallerFilePath] string callerFile = "",
        [CallerLineNumber] int callerLine = 0) =>
        Emit("WARN", message, fields, callerFile, callerLine);
    public void Warning(
        string message,
        IReadOnlyDictionary<string, object?>? fields = null,
        [CallerFilePath] string callerFile = "",
        [CallerLineNumber] int callerLine = 0) =>
        Emit("WARNING", message, fields, callerFile, callerLine);
    public void Error(
        string message,
        IReadOnlyDictionary<string, object?>? fields = null,
        [CallerFilePath] string callerFile = "",
        [CallerLineNumber] int callerLine = 0) =>
        Emit("ERROR", message, fields, callerFile, callerLine);
    public void Critical(
        string message,
        IReadOnlyDictionary<string, object?>? fields = null,
        [CallerFilePath] string callerFile = "",
        [CallerLineNumber] int callerLine = 0) =>
        Emit("CRITICAL", message, fields, callerFile, callerLine);

    /// <summary>Emit at a level known only at runtime.</summary>
    /// <remarks>
    /// For adapters that receive a level as data. Callers holding a level
    /// string convert once at the boundary with <see cref="Levels.Parse"/>
    /// rather than re-implementing a dispatch chain whose arms only execute
    /// when that severity actually occurs — the shape that leaves two of four
    /// branches permanently uncovered in the consuming repo.
    /// </remarks>
    public void Log(
        LogSeverity level,
        string message,
        IReadOnlyDictionary<string, object?>? fields = null,
        [CallerFilePath] string callerFile = "",
        [CallerLineNumber] int callerLine = 0) =>
        Emit(Levels.Name(level), message, fields, callerFile, callerLine);

    /// <summary>Log an exception, attaching its stable fingerprint.</summary>
    public void Error(
        string message,
        Exception error,
        IReadOnlyDictionary<string, object?>? fields = null,
        [CallerFilePath] string callerFile = "",
        [CallerLineNumber] int callerLine = 0)
    {
        ArgumentNullException.ThrowIfNull(error);
        Emit("ERROR", message, fields, callerFile, callerLine, Fingerprint.ComputeErrorFingerprint(error));
    }

    /// <summary>
    /// Build and dispatch one record.
    /// </summary>
    /// <remarks>
    /// <paramref name="callerFile"/> and <paramref name="callerLine"/> arrive
    /// from <see cref="CallerFilePathAttribute"/> and
    /// <see cref="CallerLineNumberAttribute"/> on the public methods above, so
    /// the callsite costs nothing at run time and no stack has to be walked to
    /// find it. The path is the build machine's absolute one and is reduced to a
    /// base name before it can reach a record.
    /// </remarks>
    private void Emit(
        string level,
        string message,
        IReadOnlyDictionary<string, object?>? fields,
        string callerFile,
        int callerLine,
        string? errorFingerprint = null)
    {
        Setup.EnsureLazyInit();
        var cfg = Setup.GetRuntimeConfig() ?? TelemetryConfig.Default();
        if (!LevelEnabled(level, EffectiveLevel(_name, cfg))) return;

        var merged = Merge(fields);
        var schemaError = ValidateSchema(merged, cfg, message);
        var rendered = cfg.Logging.Sanitize ? Pii.RedactSecretSpans(message) : message;
        var callerFilename = cfg.Logging.IncludeCaller ? BaseName(callerFile) : "";
        var backend = Setup.CurrentBackend;

        SignalPipeline.Process(new LogDispatch
        {
            SamplingKey = message,
            LogLevel = level,
            Harden = () => Pii.HardenPayload(merged, cfg.Logging.PiiMaxDepth),
            Sanitize = hardened => Materialize(
                Pii.SanitizeHardened(hardened, cfg.Logging.Sanitize),
                schemaError, callerFilename, callerLine),
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
        string? schemaError,
        string callerFilename,
        int callerLine)
    {
        // Attached after redaction so the diagnostic itself is never treated as
        // a caller field and re-sanitized into "***". The callsite rides the
        // same seam, and for the same reason.
        if (schemaError is not null) sanitized.Payload["_schema_error"] = schemaError;
        if (callerFilename.Length > 0)
        {
            // Overwrites a caller field of the same name, as the identity keys
            // do in CanonicalLogRecord.Create: one record carrying two meanings
            // of "filename" is worse than losing the caller's spelling.
            sanitized.Payload[FilenameKey] = callerFilename;
            sanitized.Payload[LinenoKey] = callerLine;
        }
        return (sanitized.Payload, sanitized.Redactions);
    }

    /// <summary>
    /// Reduce a source path to its base name.
    /// </summary>
    /// <remarks>
    /// Both separators are stripped on both platforms, because
    /// <see cref="CallerFilePathAttribute"/> bakes in the path of the machine
    /// that *compiled* the assembly: a Windows-built package running on Linux
    /// carries backslashes, which <c>Path.GetFileName</c> would there treat as
    /// ordinary characters and hand back whole. Emitting the full path would put
    /// the build machine's directory layout on every single log line.
    /// </remarks>
    internal static string BaseName(string path)
    {
        var cut = path.LastIndexOfAny(PathSeparators);
        return cut < 0 ? path : path[(cut + 1)..];
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

    private static bool LevelEnabled(string messageLevel, string configured) =>
        Levels.Order(messageLevel) >= Levels.Order(configured);
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
