// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

namespace Provide.Telemetry;

/// <summary>The canonical severity ladder. Order is the enum value.</summary>
/// <remarks>
/// Named LogSeverity rather than the more guessable LogLevel because
/// Microsoft.Extensions.Logging.LogLevel is near-universal in .NET: a
/// Provide.Telemetry.LogLevel would raise CS0104 on every unqualified use in
/// any file importing both namespaces — including this repo's own
/// OpenTelemetryBackend.cs. A less discoverable name costs one doc line; a
/// name collision costs every downstream consumer a compile error.
///
/// WARNING and FATAL are deliberately absent. They are spellings resolved by
/// <see cref="Levels.TryParse"/>, not members. Admitting an alias as a member
/// is how Warn and Warning both ended up on the public Logger surface.
/// </remarks>
public enum LogSeverity
{
    Trace = 0,
    Debug = 1,
    Info = 2,
    Warn = 3,
    Error = 4,
    Critical = 5,
}

/// <summary>The one place a level string becomes a level.</summary>
/// <remarks>
/// Every level comparison in this library resolves through here. Before it,
/// the port carried three private tables that disagreed: Logger.Rank ranked
/// CRITICAL above ERROR, Governance ranked it the same way, and the OTel
/// backend's MapLevel folded unknown levels onto Information while knowing
/// nothing of FATAL. See the log_levels section of
/// spec/behavioral_fixtures.yaml for the cross-language contract.
/// </remarks>
public static class Levels
{
    // Canonical spellings first, then the two aliases. Case-insensitive, so
    // "warn"/"WARN"/"Warn" are one entry rather than three.
    private static readonly Dictionary<string, LogSeverity> Table = new(StringComparer.OrdinalIgnoreCase)
    {
        ["TRACE"] = LogSeverity.Trace,
        ["DEBUG"] = LogSeverity.Debug,
        ["INFO"] = LogSeverity.Info,
        ["WARN"] = LogSeverity.Warn,
        ["ERROR"] = LogSeverity.Error,
        ["CRITICAL"] = LogSeverity.Critical,
        ["WARNING"] = LogSeverity.Warn,
        ["FATAL"] = LogSeverity.Critical,
    };

    private static readonly string[] CanonicalNames =
    [
        "TRACE",
        "DEBUG",
        "INFO",
        "WARN",
        "ERROR",
        "CRITICAL",
    ];

    /// <summary>The canonical uppercase spelling, as it appears on the record.</summary>
    public static string Name(LogSeverity severity) => CanonicalNames[(int)severity];

    /// <summary>
    /// Resolve a level string, reporting whether it was recognised.
    /// </summary>
    /// <remarks>
    /// On failure <paramref name="severity"/> is set to Info rather than left
    /// at default(LogSeverity) — which is Trace, and would silently promote an
    /// unrecognised level to the most verbose setting in the ladder.
    /// </remarks>
    public static bool TryParse(string? text, out LogSeverity severity)
    {
        if (text is not null && Table.TryGetValue(text.Trim(), out var found))
        {
            severity = found;
            return true;
        }
        severity = LogSeverity.Info;
        return false;
    }

    /// <summary>
    /// Resolve a level string, substituting <paramref name="fallback"/> when it
    /// is not recognised. The fallback is a parameter, not a hidden constant,
    /// so the substitution is visible at the call site.
    /// </summary>
    public static LogSeverity Parse(string? text, LogSeverity fallback = LogSeverity.Info) =>
        TryParse(text, out var severity) ? severity : fallback;

    /// <summary>Numeric rank, for threshold comparisons.</summary>
    public static int Order(string? text) => (int)Parse(text);
}
