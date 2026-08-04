// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace Provide.Telemetry;

public static class Pii
{
    public const string Redacted = "***";
    public const string TruncationSuffix = "...";
    public const int DefaultMaxDepth = 8;
    public const int MinSecretLength = 20;

    private static readonly object Gate = new();
    private static List<PIIRule> _rules = new();
    private static readonly Dictionary<string, Regex> CustomSecrets = new(StringComparer.Ordinal);

    private static readonly HashSet<string> DefaultSensitiveKeys = new(StringComparer.OrdinalIgnoreCase)
    {
        "password", "passwd", "secret", "token", "api_key", "apikey", "auth", "authorization",
        "credential", "private_key", "ssn", "credit_card", "creditcard", "cvv", "pin",
        "account_number", "cookie",
    };

    private static readonly Regex[] BuiltinSecrets =
    {
        new(@"(?:AKIA|ASIA)[A-Z0-9]{16}", RegexOptions.Compiled),
        new(@"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", RegexOptions.Compiled),
        new(@"gh[pos]_[A-Za-z0-9_]{36,}", RegexOptions.Compiled),
        new(@"[0-9a-fA-F]{40,}", RegexOptions.Compiled),
        new(@"[A-Za-z0-9+/]{40,}={0,2}", RegexOptions.Compiled),
    };

    public static IReadOnlyList<PIIRule> GetPIIRules()
    {
        lock (Gate) { return _rules.Select(CloneRule).ToList(); }
    }

    public static void RegisterPIIRule(PIIRule rule)
    {
        lock (Gate) { _rules.Add(CloneRule(rule)); }
    }

    public static void ReplacePIIRules(IEnumerable<PIIRule> rules)
    {
        lock (Gate) { _rules = rules.Select(CloneRule).ToList(); }
    }

    /// <summary>Alias used by some call sites / Go parity.</summary>
    public static void SetPIIRules(IEnumerable<PIIRule> rules) => ReplacePIIRules(rules);

    public static void RegisterSecretPattern(string name, Regex pattern)
    {
        lock (Gate) { CustomSecrets[name] = pattern; }
    }

    public static Dictionary<string, object?> SanitizePayload(
        IReadOnlyDictionary<string, object?> payload,
        bool enabled,
        int maxDepth)
    {
        if (!enabled) return payload.ToDictionary(kv => kv.Key, kv => kv.Value, StringComparer.Ordinal);
        if (maxDepth <= 0) maxDepth = DefaultMaxDepth;
        List<PIIRule> rules;
        Dictionary<string, Regex> custom;
        lock (Gate)
        {
            rules = _rules.Select(CloneRule).ToList();
            custom = new Dictionary<string, Regex>(CustomSecrets, StringComparer.Ordinal);
        }
        return SanitizeMap(payload, rules, custom, maxDepth, Array.Empty<string>())
               ?? new Dictionary<string, object?>(StringComparer.Ordinal);
    }

    public static bool DetectSecretInValue(string text)
    {
        if (string.IsNullOrEmpty(text) || text.Length < MinSecretLength) return false;
        foreach (var re in BuiltinSecrets)
        {
            if (re.IsMatch(text)) return true;
        }
        Dictionary<string, Regex> custom;
        lock (Gate) { custom = new Dictionary<string, Regex>(CustomSecrets, StringComparer.Ordinal); }
        foreach (var re in custom.Values)
        {
            if (re.IsMatch(text)) return true;
        }
        return false;
    }

    public static string HashValue(object? value)
    {
        var s = value switch
        {
            null => "",
            string str => str,
            // Match Go/Python fmt of integers without type suffix.
            int or long or short or byte => Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture)!,
            _ => Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture) ?? "",
        };
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(s));
        return Convert.ToHexString(bytes).ToLowerInvariant()[..12];
    }

    internal static void Reset()
    {
        lock (Gate)
        {
            _rules = new List<PIIRule>();
            CustomSecrets.Clear();
        }
    }

    private static Dictionary<string, object?>? SanitizeMap(
        IReadOnlyDictionary<string, object?> payload,
        List<PIIRule> rules,
        Dictionary<string, Regex> custom,
        int maxDepth,
        IReadOnlyList<string> path)
    {
        if (maxDepth < 0) return new Dictionary<string, object?>(StringComparer.Ordinal);
        var result = new Dictionary<string, object?>(StringComparer.Ordinal);
        foreach (var (key, value) in payload)
        {
            var childPath = path.Concat(new[] { key }).ToArray();
            var (keep, newVal) = SanitizeValue(key, value, rules, custom, maxDepth, childPath);
            if (keep) result[key] = newVal;
        }
        return result;
    }

    private static (bool keep, object? value) SanitizeValue(
        string key,
        object? value,
        List<PIIRule> rules,
        Dictionary<string, Regex> custom,
        int maxDepth,
        IReadOnlyList<string> path)
    {
        var fieldPath = string.Join(".", path);
        foreach (var rule in rules)
        {
            if (!PathMatches(rule.Path, path)) continue;
            return ApplyMode(value, rule.Mode, rule.TruncateTo, fieldPath);
        }

        if (DefaultSensitiveKeys.Contains(key))
        {
            if (!Equals(value, Redacted))
            {
                Receipts.Record(fieldPath, PiiModes.Redact, value);
            }
            return (true, Redacted);
        }

        if (value is string s && DetectSecret(s, custom))
        {
            if (s != Redacted)
            {
                Receipts.Record(fieldPath, PiiModes.Redact, value);
            }
            return (true, Redacted);
        }

        if (value is Dictionary<string, object?> nestedDict)
        {
            return (true, SanitizeMap(nestedDict, rules, custom, maxDepth - 1, path));
        }

        if (value is IReadOnlyDictionary<string, object?> nestedRo)
        {
            return (true, SanitizeMap(nestedRo, rules, custom, maxDepth - 1, path));
        }

        if (value is IDictionary<string, object?> nested)
        {
            var copy = nested.ToDictionary(kv => kv.Key, kv => kv.Value, StringComparer.Ordinal);
            return (true, SanitizeMap(copy, rules, custom, maxDepth - 1, path));
        }

        return (true, value);
    }

    private static (bool keep, object? value) ApplyMode(
        object? value, string mode, int truncateTo, string fieldPath)
    {
        switch (mode)
        {
            case PiiModes.Drop:
                Receipts.Record(fieldPath, PiiModes.Drop, value);
                return (false, null);
            case PiiModes.Hash:
                Receipts.Record(fieldPath, PiiModes.Hash, value);
                return (true, HashValue(value));
            case PiiModes.Truncate:
            {
                var text = value is string s
                    ? s
                    : Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture) ?? "";
                if (truncateTo <= 0 || text.Length <= truncateTo) return (true, text);
                Receipts.Record(fieldPath, PiiModes.Truncate, value);
                return (true, text[..truncateTo] + TruncationSuffix);
            }
            case PiiModes.Pass:
                return (true, value);
            default:
                if (!Equals(value, Redacted))
                {
                    Receipts.Record(fieldPath, PiiModes.Redact, value);
                }
                return (true, Redacted);
        }
    }

    private static bool PathMatches(IReadOnlyList<string> rulePath, IReadOnlyList<string> path)
    {
        if (rulePath.Count != path.Count) return false;
        for (var i = 0; i < rulePath.Count; i++)
        {
            if (rulePath[i] != "*" && rulePath[i] != path[i]) return false;
        }
        return true;
    }

    private static bool DetectSecret(string text, Dictionary<string, Regex> custom)
    {
        if (text.Length < MinSecretLength) return false;
        foreach (var re in BuiltinSecrets)
        {
            if (re.IsMatch(text)) return true;
        }
        foreach (var re in custom.Values)
        {
            if (re.IsMatch(text)) return true;
        }
        return false;
    }

    private static PIIRule CloneRule(PIIRule r) => new()
    {
        Path = r.Path.ToArray(),
        Mode = r.Mode,
        TruncateTo = r.TruncateTo,
    };
}
