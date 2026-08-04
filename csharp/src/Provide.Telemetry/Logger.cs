// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


using System.Text.Json;

namespace Provide.Telemetry;

/// <summary>Structured logger emitting the canonical JSON envelope to stderr.</summary>
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

    private void Emit(string level, string message, IReadOnlyDictionary<string, object?>? fields)
    {
        Setup.EnsureLazyInit();
        var cfg = Setup.GetRuntimeConfig() ?? TelemetryConfig.Default();

        if (!LevelEnabled(level, EffectiveLevel(_name, cfg))) return;
        // Consent gates all signals before sampling/backpressure (parity with Go/TS/Rust).
        if (!Consent.ShouldAllow(Signals.Logs, level)) return;
        if (!Sampling.ShouldSample(Signals.Logs, message)) return;

        var ticket = Backpressure.TryAcquire(Signals.Logs);
        if (ticket is null && GetQueuePolicyMax(cfg) > 0) return;

        try
        {
            var record = new Dictionary<string, object?>(StringComparer.Ordinal);
            if (fields is not null)
            {
                foreach (var (k, v) in fields) record[k] = v;
            }
            foreach (var (k, v) in Context.GetBoundFields())
            {
                if (!record.ContainsKey(k)) record[k] = v;
            }

            // Schema checks — on failure attach _schema_error (runtime probe) or drop.
            string? schemaError = null;
            try
            {
                if (cfg.EventSchema.RequiredKeys.Count > 0)
                {
                    Schema.ValidateRequiredKeys(record, cfg.EventSchema.RequiredKeys);
                }
                if (Schema.GetStrictSchema())
                {
                    Schema.ValidateEventName(message);
                }
            }
            catch (EventSchemaError ex)
            {
                schemaError = ex.Message;
            }

            if (cfg.Logging.Sanitize)
            {
                record = Pii.SanitizePayload(record, true, cfg.Logging.PiiMaxDepth);
                if (Pii.DetectSecretInValue(message))
                {
                    message = Pii.Redacted;
                }
            }

            var output = new Dictionary<string, object?>(StringComparer.Ordinal);
            if (cfg.Logging.IncludeTimestamp)
            {
                output["timestamp"] = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ");
            }
            output["level"] = level;
            output["message"] = message;
            if (!string.IsNullOrEmpty(_name)) output["logger_name"] = _name;
            if (!string.IsNullOrEmpty(cfg.ServiceName)) output["service.name"] = cfg.ServiceName;
            if (!string.IsNullOrEmpty(cfg.Environment)) output["service.env"] = cfg.Environment;
            if (!string.IsNullOrEmpty(cfg.Version)) output["service.version"] = cfg.Version;

            var (traceId, spanId) = Context.GetTraceContext();
            if (!string.IsNullOrEmpty(traceId)) output["trace.id"] = traceId;
            if (!string.IsNullOrEmpty(spanId)) output["span.id"] = spanId;

            foreach (var (k, v) in record)
            {
                if (!output.ContainsKey(k)) output[k] = v;
            }
            if (schemaError is not null) output["_schema_error"] = schemaError;

            string line;
            if (string.Equals(cfg.Logging.Format, "json", StringComparison.OrdinalIgnoreCase))
            {
                line = JsonSerializer.Serialize(output);
            }
            else if (string.Equals(cfg.Logging.Format, "pretty", StringComparison.OrdinalIgnoreCase))
            {
                line = FormatPretty(output, level, message);
            }
            else
            {
                line = FormatConsole(output, level, message);
            }

            Console.Error.WriteLine(line);
            Health.RecordEmitted(Signals.Logs);
            Otel.OtelBackend.EmitLog(level, message, output);
        }
        finally
        {
            Backpressure.Release(ticket);
        }
    }

    private static int GetQueuePolicyMax(TelemetryConfig cfg) =>
        Backpressure.GetQueuePolicy().LogsMaxSize;

    private static string FormatConsole(Dictionary<string, object?> output, string level, string message)
    {
        var extras = string.Join(" ", output
            .Where(kv => kv.Key is not ("level" or "message" or "timestamp"))
            .Select(kv => $"{kv.Key}={kv.Value}"));
        var ts = output.TryGetValue("timestamp", out var t) ? t + " " : "";
        return string.IsNullOrEmpty(extras)
            ? $"{ts}[{level}] {message}"
            : $"{ts}[{level}] {message} {extras}";
    }

    private static string FormatPretty(Dictionary<string, object?> output, string level, string message)
    {
        var extras = string.Join(" ", output
            .Where(kv => kv.Key is not ("level" or "message" or "timestamp"))
            .Select(kv => $"{kv.Key}=\"{kv.Value}\""));
        var ts = output.TryGetValue("timestamp", out var t) ? t + " " : "";
        return string.IsNullOrEmpty(extras)
            ? $"{ts}[{level}] {message}"
            : $"{ts}[{level}] {message} {extras}";
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
        ["TRACE"] = 0, ["DEBUG"] = 10, ["INFO"] = 20,
        ["WARN"] = 30, ["WARNING"] = 30, ["ERROR"] = 40, ["CRITICAL"] = 50,
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
