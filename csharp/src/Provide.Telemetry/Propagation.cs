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

    // One W3C tracestate list member: OWS, a key starting with lcalpha/digit
    // followed by up to 255 of the spec's key characters (multi-tenant "@"
    // included), "=", a value of printable ASCII minus comma and equals, OWS.
    private static readonly Regex TracestateMemberRe = new(
        @"^[ \t]*[a-z0-9][a-z0-9_\-*/@]{0,255}=[\x20-\x2b\x2d-\x3c\x3e-\x7e]*[ \t]*$",
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
        if (pairs.Length > MaxTracestatePairs) return "";
        // Grammar check after the size guards: one bad member discards the
        // whole header. This is a security boundary, not pedantry — a kept
        // tracestate is forwarded verbatim into outbound headers by runtimes
        // that inject it, so a surviving control character (CR/LF especially)
        // is header injection at the next hop. Mirrors Python's
        // _is_forwardable_tracestate (parity: propagation_tracestate_grammar).
        return pairs.All(member => TracestateMemberRe.IsMatch(member)) ? s : "";
    }

    private static (string traceId, string spanId) ParseTraceparent(string tp)
    {
        // No Trim(): the header is a fixed-width token and every other runtime
        // rejects surrounding whitespace, so tolerating it here was drift.
        if (string.IsNullOrEmpty(tp)) return ("", "");
        var m = TraceparentRe.Match(tp);
        if (!m.Success) return ("", "");
        // Version ff is reserved and must not be trusted (W3C trace-context
        // §versioning); Python's _parse_traceparent rejects it the same way.
        if (m.Groups[1].Value.Equals("ff", StringComparison.OrdinalIgnoreCase)) return ("", "");
        var traceId = m.Groups[2].Value.ToLowerInvariant();
        var spanId = m.Groups[3].Value.ToLowerInvariant();
        if (traceId.All(c => c == '0') || spanId.All(c => c == '0')) return ("", "");
        return (traceId, spanId);
    }
}
