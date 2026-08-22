// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


namespace Provide.Telemetry;

public enum DataClass
{
    Public,
    Internal,
    Confidential,
    Restricted,
    Secret,
}

public sealed class ClassificationRule
{
    public string Pattern { get; set; } = "";
    public DataClass Class { get; set; } = DataClass.Internal;
}

public sealed class ClassificationPolicy
{
    public string PublicAction { get; set; } = "pass";
    public string InternalAction { get; set; } = "pass";
    public string ConfidentialAction { get; set; } = "redact";
    public string RestrictedAction { get; set; } = "drop";
    public string SecretAction { get; set; } = "drop";
}

public static class Classification
{
    private static readonly object Gate = new();
    private static List<ClassificationRule> _rules = new();
    private static ClassificationPolicy _policy = new();

    public static void RegisterClassificationRules(IEnumerable<ClassificationRule> rules)
    {
        lock (Gate) { _rules = rules.Select(Clone).ToList(); }
    }

    public static void RegisterClassificationRule(ClassificationRule rule)
    {
        lock (Gate) { _rules.Add(Clone(rule)); }
    }

    public static DataClass? ClassifyKey(string key)
    {
        lock (Gate)
        {
            foreach (var rule in _rules)
            {
                if (string.Equals(rule.Pattern, key, StringComparison.OrdinalIgnoreCase)
                    || (rule.Pattern.EndsWith('*')
                        && key.StartsWith(rule.Pattern.TrimEnd('*'), StringComparison.OrdinalIgnoreCase)))
                {
                    return rule.Class;
                }
            }
        }
        return null;
    }

    public static void SetClassificationPolicy(ClassificationPolicy policy)
    {
        lock (Gate) { _policy = ClonePolicy(policy); }
    }

    public static ClassificationPolicy GetClassificationPolicy()
    {
        lock (Gate) { return ClonePolicy(_policy); }
    }

    internal static void Reset()
    {
        lock (Gate)
        {
            _rules = new List<ClassificationRule>();
            _policy = new ClassificationPolicy();
        }
    }

    private static ClassificationRule Clone(ClassificationRule r) =>
        new() { Pattern = r.Pattern, Class = r.Class };

    private static ClassificationPolicy ClonePolicy(ClassificationPolicy p) => new()
    {
        PublicAction = p.PublicAction,
        InternalAction = p.InternalAction,
        ConfidentialAction = p.ConfidentialAction,
        RestrictedAction = p.RestrictedAction,
        SecretAction = p.SecretAction,
    };
}

/// <summary>
/// Polyglot consent levels (match Go/Python: FULL | FUNCTIONAL | MINIMAL | NONE).
/// </summary>
public enum ConsentLevel
{
    /// <summary>All signals collected.</summary>
    Full = 0,
    /// <summary>Warnings+, traces, metrics; no context/baggage.</summary>
    Functional = 1,
    /// <summary>Errors only; no traces/metrics/context.</summary>
    Minimal = 2,
    /// <summary>No telemetry collected.</summary>
    None = 3,
}

public static class Consent
{
    private const string EnvVar = "PROVIDE_CONSENT_LEVEL";
    private static int _level = (int)ConsentLevel.Full;
    // 0 = armed, 1 = the invalid-env warning has been written this process.
    private static int _invalidEnvWarned;

    public static void SetConsentLevel(ConsentLevel level) =>
        Interlocked.Exchange(ref _level, (int)level);

    public static ConsentLevel GetConsentLevel() =>
        (ConsentLevel)Interlocked.CompareExchange(ref _level, 0, 0);

    /// <summary>
    /// Returns true if the given signal is permitted at the current consent level.
    /// signal is one of "logs", "traces", "metrics", "context".
    /// logLevel is only used when signal == "logs".
    /// </summary>
    public static bool ShouldAllow(string signal, string logLevel)
    {
        var level = GetConsentLevel();
        switch (level)
        {
            case ConsentLevel.Full:
                return true;
            case ConsentLevel.None:
                return false;
            case ConsentLevel.Functional:
                if (signal == Signals.Logs)
                {
                    return LogOrder(logLevel) >= (int)LogSeverity.Warn;
                }
                if (signal == Signals.Context) return false;
                return true;
            case ConsentLevel.Minimal:
                if (signal == Signals.Logs)
                {
                    return LogOrder(logLevel) >= (int)LogSeverity.Error;
                }
                return false;
            default:
                return false;
        }
    }

    /// <summary>
    /// Applies <c>PROVIDE_CONSENT_LEVEL</c> if it is set. Called by
    /// <c>SetupTelemetry</c> and by the lazy <c>GetLogger</c> path, so an
    /// operator opt-out takes effect without a code change. The value is
    /// trimmed and matched case-insensitively against FULL, FUNCTIONAL,
    /// MINIMAL and NONE. An unset or blank variable is a no-op (a level chosen
    /// in code survives). A set, non-empty, unrecognised value fails closed:
    /// consent becomes <see cref="ConsentLevel.None"/> on every call, and one
    /// warning per process naming the raw value is written to
    /// <see cref="Console.Error"/> — outside the SDK logger, which the None it
    /// just applied would silence. The variable is an opt-out control, and the
    /// one failure an opt-out must not have is a typo that leaves collection on.
    /// </summary>
    public static void LoadConsentFromEnv()
    {
        var raw = Environment.GetEnvironmentVariable(EnvVar);
        if (string.IsNullOrWhiteSpace(raw)) return;
        SetConsentLevel(ParseLevel(raw.Trim().ToUpperInvariant()) ?? FailClosed(raw));
    }

    private static ConsentLevel? ParseLevel(string text) => text switch
    {
        "FULL" => ConsentLevel.Full,
        "FUNCTIONAL" => ConsentLevel.Functional,
        "MINIMAL" => ConsentLevel.Minimal,
        "NONE" => ConsentLevel.None,
        _ => null,
    };

    private static ConsentLevel FailClosed(string raw)
    {
        WarnInvalidEnvOnce(raw);
        return ConsentLevel.None;
    }

    private static void WarnInvalidEnvOnce(string raw)
    {
        if (Interlocked.Exchange(ref _invalidEnvWarned, 1) != 0) return;
        // Console.Error is read at call time so a test can redirect it; the
        // SDK logger is deliberately not used, because consent None would drop
        // the very record that explains why consent is None.
        Console.Error.WriteLine(
            $"[provide-telemetry] {EnvVar}=\"{raw}\" is not one of FULL, FUNCTIONAL, MINIMAL, NONE; consent set to NONE (fail-closed)");
    }

    internal static void Reset()
    {
        SetConsentLevel(ConsentLevel.Full);
        Interlocked.Exchange(ref _invalidEnvWarned, 0);
    }

    // Resolves through the one shared table. An unrecognised level lands on
    // INFO rather than the old local default of 0/TRACE; both sit below the
    // WARN and ERROR gates above, so no consent decision changes. FATAL does
    // change: it used to be unrecognised here and was dropped as if it were
    // the least severe record in the ladder.
    internal static int LogOrder(string? logLevel) => Levels.Order(logLevel);
}

public static class Slo
{
    public static string ClassifyError(Exception? error)
    {
        if (error is null) return "unknown";
        if (error is TimeoutException) return "timeout";
        if (error is UnauthorizedAccessException) return "auth";
        if (error is ConfigurationError) return "config";
        return "error";
    }

    public static void RecordRedMetrics(string operation, double durationMs, bool success)
    {
        var c = Metrics.Counter("provide.slo.red.requests");
        c.Add(1, new Dictionary<string, object?>
        {
            ["operation"] = operation,
            ["success"] = success,
        });
        Metrics.Histogram("provide.slo.red.duration_ms").Record(durationMs);
    }

    public static void RecordUseMetrics(string resource, double utilization, double saturation, double errors)
    {
        Metrics.Gauge("provide.slo.use.utilization").Set(utilization,
            new Dictionary<string, object?> { ["resource"] = resource });
        Metrics.Gauge("provide.slo.use.saturation").Set(saturation,
            new Dictionary<string, object?> { ["resource"] = resource });
        Metrics.Counter("provide.slo.use.errors").Add((long)errors,
            new Dictionary<string, object?> { ["resource"] = resource });
    }
}
