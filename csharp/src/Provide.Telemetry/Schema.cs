// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


using System.Text.RegularExpressions;

namespace Provide.Telemetry;

public static class Schema
{
    private static readonly Regex SegmentPattern = new(@"^[a-z][a-z0-9_]*$", RegexOptions.Compiled);
    private static readonly object Gate = new();
    private static bool _strict;

    public static void SetStrictSchema(bool enabled)
    {
        lock (Gate) { _strict = enabled; }
    }

    public static bool GetStrictSchema()
    {
        lock (Gate) { return _strict; }
    }

    public static EventRecord Event(params string[] segments)
    {
        if (segments.Length is < 3 or > 4)
        {
            throw new EventSchemaError(
                $"event requires 3 (DAS) or 4 (DARS) segments, got {segments.Length}");
        }
        if (GetStrictSchema())
        {
            foreach (var seg in segments)
            {
                if (!SegmentPattern.IsMatch(seg))
                {
                    throw new EventSchemaError($"invalid event segment: {seg}");
                }
            }
        }
        var joined = string.Join(".", segments);
        return segments.Length == 3
            ? new EventRecord
            {
                Event = joined,
                Domain = segments[0],
                Action = segments[1],
                Status = segments[2],
            }
            : new EventRecord
            {
                Event = joined,
                Domain = segments[0],
                Action = segments[1],
                Resource = segments[2],
                Status = segments[3],
            };
    }

    public static string EventName(params string[] segments)
    {
        if (segments.Length is < 3 or > 5)
        {
            throw new EventSchemaError($"event name requires 3-5 segments, got {segments.Length}");
        }
        if (GetStrictSchema())
        {
            foreach (var seg in segments)
            {
                if (!SegmentPattern.IsMatch(seg))
                {
                    throw new EventSchemaError($"invalid event segment: {seg}");
                }
            }
        }
        return string.Join(".", segments);
    }

    public static void ValidateEventName(string message)
    {
        var parts = message.Split('.');
        if (parts.Length is < 3 or > 5)
        {
            throw new EventSchemaError($"event name requires 3-5 segments, got {parts.Length}");
        }
        foreach (var seg in parts)
        {
            if (!SegmentPattern.IsMatch(seg))
            {
                throw new EventSchemaError($"invalid event segment: {seg}");
            }
        }
    }

    public static void ValidateRequiredKeys(IReadOnlyDictionary<string, object?> attrs, IEnumerable<string> keys)
    {
        foreach (var key in keys)
        {
            if (!attrs.ContainsKey(key))
            {
                throw new EventSchemaError($"missing required key: {key}");
            }
        }
    }

    internal static void Reset() => SetStrictSchema(false);
}
