// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


namespace Provide.Telemetry;

public static class Cardinality
{
    private const string Overflow = "__overflow__";
    private static readonly object Gate = new();
    private static readonly Dictionary<string, CardinalityLimit> Limits = new(StringComparer.Ordinal);
    private static readonly Dictionary<string, HashSet<string>> Caches = new(StringComparer.Ordinal);
    private static readonly Dictionary<string, Dictionary<string, DateTimeOffset>> Expiry =
        new(StringComparer.Ordinal);

    public static void RegisterCardinalityLimit(string key, CardinalityLimit limit)
    {
        lock (Gate)
        {
            var clamped = new CardinalityLimit
            {
                MaxValues = Math.Max(1, limit.MaxValues),
                TtlSeconds = Math.Max(1.0, limit.TtlSeconds),
            };
            Limits[key] = clamped;
            Caches.Remove(key);
            Expiry.Remove(key);
        }
    }

    public static IReadOnlyDictionary<string, CardinalityLimit> GetCardinalityLimits()
    {
        lock (Gate)
        {
            return Limits.ToDictionary(
                kv => kv.Key,
                kv => new CardinalityLimit { MaxValues = kv.Value.MaxValues, TtlSeconds = kv.Value.TtlSeconds },
                StringComparer.Ordinal);
        }
    }

    public static void ClearCardinalityLimits()
    {
        lock (Gate)
        {
            Limits.Clear();
            Caches.Clear();
            Expiry.Clear();
        }
    }

    public static Dictionary<string, string> GuardAttributes(IReadOnlyDictionary<string, string> attrs)
    {
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        lock (Gate)
        {
            foreach (var (key, value) in attrs)
            {
                if (!Limits.TryGetValue(key, out var limit))
                {
                    result[key] = value;
                    continue;
                }
                if (!Caches.TryGetValue(key, out var cache))
                {
                    cache = new HashSet<string>(StringComparer.Ordinal);
                    Caches[key] = cache;
                    Expiry[key] = new Dictionary<string, DateTimeOffset>(StringComparer.Ordinal);
                }
                PurgeExpired(key, cache);
                if (cache.Contains(value))
                {
                    result[key] = value;
                    continue;
                }
                if (cache.Count >= limit.MaxValues)
                {
                    result[key] = Overflow;
                    continue;
                }
                cache.Add(value);
                Expiry[key][value] = DateTimeOffset.UtcNow.AddSeconds(limit.TtlSeconds);
                result[key] = value;
            }
        }
        return result;
    }

    internal static void Reset() => ClearCardinalityLimits();

    private static void PurgeExpired(string key, HashSet<string> cache)
    {
        if (!Expiry.TryGetValue(key, out var exp)) return;
        var now = DateTimeOffset.UtcNow;
        var stale = exp.Where(kv => kv.Value <= now).Select(kv => kv.Key).ToList();
        foreach (var v in stale)
        {
            cache.Remove(v);
            exp.Remove(v);
        }
    }
}
