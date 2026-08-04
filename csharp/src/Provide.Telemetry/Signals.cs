// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


namespace Provide.Telemetry;

internal static class Signals
{
    public const string Logs = "logs";
    public const string Traces = "traces";
    public const string Metrics = "metrics";
    /// <summary>Context/baggage binding (consent only; not a queue signal).</summary>
    public const string Context = "context";

    private static readonly HashSet<string> Valid = new(StringComparer.Ordinal)
    {
        Logs, Traces, Metrics,
    };

    public static void Validate(string signal)
    {
        if (!Valid.Contains(signal))
        {
            throw new ConfigurationError(
                $"unknown signal \"{signal}\", expected one of [logs, metrics, traces]");
        }
    }
}
