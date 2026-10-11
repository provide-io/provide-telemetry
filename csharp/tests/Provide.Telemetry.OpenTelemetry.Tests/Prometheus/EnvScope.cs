// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Collections;

namespace Provide.Telemetry.OpenTelemetry.Tests.Prometheus;

/// <summary>
/// Clears every PROVIDE_* and OTEL_* variable, applies the given ones, and
/// restores the original environment on dispose.
/// </summary>
internal sealed class EnvScope : IDisposable
{
    private readonly Dictionary<string, string?> _saved = new(StringComparer.Ordinal);

    public EnvScope(IReadOnlyDictionary<string, string?>? env = null)
    {
        foreach (DictionaryEntry kv in Environment.GetEnvironmentVariables())
        {
            var key = (string)kv.Key;
            if (key.StartsWith("PROVIDE_", StringComparison.Ordinal) || key.StartsWith("OTEL_", StringComparison.Ordinal))
            {
                _saved[key] = (string?)kv.Value;
                Environment.SetEnvironmentVariable(key, null);
            }
        }
        foreach (var (key, value) in env ?? new Dictionary<string, string?>()) Set(key, value);
    }

    public static EnvScope From(Dictionary<object, object?>? env) =>
        new(env?.ToDictionary(kv => (string)kv.Key, kv => (string?)kv.Value));

    public void Set(string key, string? value)
    {
        if (!_saved.ContainsKey(key)) _saved[key] = Environment.GetEnvironmentVariable(key);
        Environment.SetEnvironmentVariable(key, value);
    }

    public void Dispose()
    {
        foreach (DictionaryEntry kv in Environment.GetEnvironmentVariables())
        {
            var key = (string)kv.Key;
            if (key.StartsWith("PROVIDE_", StringComparison.Ordinal) || key.StartsWith("OTEL_", StringComparison.Ordinal))
            {
                Environment.SetEnvironmentVariable(key, null);
            }
        }
        foreach (var (key, value) in _saved) Environment.SetEnvironmentVariable(key, value);
    }
}
