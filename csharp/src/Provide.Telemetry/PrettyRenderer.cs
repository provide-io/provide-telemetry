// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

/// <summary>
/// ANSI pretty renderer for <c>PROVIDE_LOG_FORMAT=pretty</c>.
/// </summary>
/// <remarks>
/// Cross-language parity with <c>src/provide/telemetry/logger/pretty.py</c>,
/// <c>go/logger_pretty.go</c> and <c>rust/src/logger/pretty.rs</c>: a dim
/// timestamp, a level name lowercased and padded to nine columns inside
/// brackets and colored by severity, the message, then <c>key="value"</c>
/// pairs with dim keys. Colors activate only when stderr is a real terminal;
/// piped output is byte-identical to the colorless form. The
/// <c>PROVIDE_LOG_PRETTY_*</c> variables are deliberately not read here —
/// <c>spec/telemetry-api.yaml</c> scopes them to the other four languages, so
/// this renderer uses the spec's defaults (dim keys, uncolored values).
/// </remarks>
internal static class PrettyRenderer
{
    internal const string AnsiReset = "\x1b[0m";
    internal const string AnsiDim = "\x1b[2m";
    internal const string AnsiRed = "\x1b[31m";
    internal const string AnsiGreen = "\x1b[32m";
    internal const string AnsiYellow = "\x1b[33m";
    internal const string AnsiBlue = "\x1b[34m";
    internal const string AnsiCyan = "\x1b[36m";
    internal const string AnsiBoldRed = "\x1b[31;1m";

    /// <summary>"critical" is eight characters; nine matches Python/Go/Rust.</summary>
    internal const int LevelPad = 9;

    /// <summary>Severity color for a lowercased level name; unknown levels get none.</summary>
    internal static string LevelColor(string levelLower) => levelLower switch
    {
        "critical" or "fatal" => AnsiBoldRed,
        "error" => AnsiRed,
        "warning" or "warn" => AnsiYellow,
        "info" => AnsiGreen,
        "debug" => AnsiBlue,
        "trace" => AnsiCyan,
        _ => "",
    };

    private static string Wrap(string text, string color, bool colors) =>
        colors && color.Length > 0 ? $"{color}{text}{AnsiReset}" : text;

    private static string FormatLevel(string level, bool colors)
    {
        var lower = level.ToLowerInvariant();
        var padded = lower.Length < LevelPad ? lower.PadRight(LevelPad) : lower;
        return $"[{Wrap(padded, LevelColor(lower), colors)}]";
    }

    /// <summary>Render one pretty line with an explicit color flag (test seam).</summary>
    internal static string Render(
        IReadOnlyDictionary<string, object?> output, CanonicalLogRecord record, bool colors)
    {
        var parts = new List<string>(4 + output.Count);
        if (output.TryGetValue("timestamp", out var ts))
        {
            parts.Add(Wrap($"{ts}", AnsiDim, colors));
        }
        parts.Add(FormatLevel(record.Level, colors));
        parts.Add(Logger.EscapeControl(record.Event, escapeQuotes: false));
        foreach (var (key, value) in output)
        {
            if (key is "level" or "message" or "timestamp") continue;
            var k = Wrap(Logger.EscapeControl(key, escapeQuotes: false), AnsiDim, colors);
            var v = Logger.EscapeControl($"{value}", escapeQuotes: true);
            parts.Add($"{k}=\"{v}\"");
        }
        return string.Join(" ", parts);
    }

    /// <summary>Render one pretty line, coloring only when stderr is a terminal.</summary>
    internal static string Render(
        IReadOnlyDictionary<string, object?> output, CanonicalLogRecord record) =>
        Render(output, record, !Console.IsErrorRedirected);
}
