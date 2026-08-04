// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.


using System.Text.RegularExpressions;

namespace Provide.Telemetry;

public static class Propagation
{
    private const int MaxTraceparentBytes = 512;
    private const int MaxTracestateBytes = 512;
    private const int MaxBaggageBytes = 8192;
    private const int MaxTracestatePairs = 32;

    private static readonly Regex TraceparentRe = new(
        @"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);

    private static readonly Regex BaggageTokenRe = new(
        @"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$",
        RegexOptions.Compiled);

    private static readonly Regex BaggageControlRe = new(
        @"[\x00-\x08\x0a-\x1f\x7f]",
        RegexOptions.Compiled);

    public static PropagationContext ExtractW3CContext(IEnumerable<KeyValuePair<string, string>> headers)
    {
        var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var kv in headers)
        {
            map[kv.Key] = kv.Value;
        }
        return ExtractW3CContext(map);
    }

    public static PropagationContext ExtractW3CContext(IReadOnlyDictionary<string, string> headers)
    {
        headers.TryGetValue("traceparent", out var tpRaw);
        headers.TryGetValue("tracestate", out var tsRaw);
        headers.TryGetValue("baggage", out var bgRaw);
        // Also accept Traceparent casing via case-insensitive dict
        if (tpRaw is null)
        {
            foreach (var kv in headers)
            {
                if (kv.Key.Equals("traceparent", StringComparison.OrdinalIgnoreCase)) tpRaw = kv.Value;
                if (kv.Key.Equals("tracestate", StringComparison.OrdinalIgnoreCase)) tsRaw = kv.Value;
                if (kv.Key.Equals("baggage", StringComparison.OrdinalIgnoreCase)) bgRaw = kv.Value;
            }
        }

        var tp = GuardSize(tpRaw ?? "", MaxTraceparentBytes);
        var ts = GuardTracestate(tsRaw ?? "");
        var bg = GuardSize(bgRaw ?? "", MaxBaggageBytes);
        var (traceId, spanId) = ParseTraceparent(tp);
        if (traceId.Length == 0 && spanId.Length == 0)
        {
            tp = "";
        }
        return new PropagationContext
        {
            Traceparent = tp,
            Tracestate = ts,
            Baggage = bg,
            TraceID = traceId,
            SpanID = spanId,
        };
    }

    public static void BindPropagationContext(PropagationContext pc)
    {
        Context.SetPropagation(pc);
        if (!string.IsNullOrEmpty(pc.TraceID) || !string.IsNullOrEmpty(pc.SpanID))
        {
            Context.SetTraceContext(pc.TraceID, pc.SpanID);
        }
        if (!string.IsNullOrEmpty(pc.Baggage))
        {
            var fields = new Dictionary<string, object?> { ["baggage"] = pc.Baggage };
            foreach (var (k, v) in ParseBaggage(pc.Baggage))
            {
                fields["baggage." + k] = v;
            }
            Context.BindContext(fields);
        }
    }

    public static Dictionary<string, string> ParseBaggage(string raw)
    {
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var member in raw.Split(','))
        {
            var kv = member.Split(';', 2)[0];
            var eq = kv.IndexOf('=');
            if (eq < 1) continue;
            var key = kv[..eq].Trim();
            if (key.Length == 0 || !BaggageTokenRe.IsMatch(key)) continue;
            var val = BaggageControlRe.Replace(kv[(eq + 1)..].Trim(), "");
            result[key] = val;
        }
        return result;
    }

    public static void InjectTraceparent(IDictionary<string, string> headers)
    {
        var (traceId, spanId) = Context.GetTraceContext();
        if (string.IsNullOrEmpty(traceId) || string.IsNullOrEmpty(spanId)) return;
        headers["traceparent"] = $"00-{traceId}-{spanId}-01";
    }

    private static string GuardSize(string s, int maxBytes)
    {
        if (string.IsNullOrEmpty(s)) return "";
        return System.Text.Encoding.UTF8.GetByteCount(s) > maxBytes ? "" : s;
    }

    private static string GuardTracestate(string s)
    {
        if (string.IsNullOrEmpty(s)) return "";
        if (System.Text.Encoding.UTF8.GetByteCount(s) > MaxTracestateBytes) return "";
        var pairs = s.Split(',');
        return pairs.Length > MaxTracestatePairs ? "" : s;
    }

    private static (string traceId, string spanId) ParseTraceparent(string tp)
    {
        if (string.IsNullOrEmpty(tp)) return ("", "");
        var m = TraceparentRe.Match(tp.Trim());
        if (!m.Success) return ("", "");
        var traceId = m.Groups[2].Value.ToLowerInvariant();
        var spanId = m.Groups[3].Value.ToLowerInvariant();
        if (traceId.All(c => c == '0') || spanId.All(c => c == '0')) return ("", "");
        return (traceId, spanId);
    }
}
