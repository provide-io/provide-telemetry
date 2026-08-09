// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Globalization;
using System.Text;

namespace Provide.Telemetry;

/// <summary>
/// RFC 8785 (JCS) serialization — the form every SDK hashes.
/// </summary>
/// <remarks>
/// Receipts hash the canonical JSON of a value, not its display form. Hashing
/// <c>ToString()</c> collides across types: the number <c>1</c> and the string
/// <c>"1"</c> render identically, so a receipt over one could not be told from a
/// receipt over the other. The vectors in <c>spec/receipt_fixtures.yaml</c> were
/// produced by an independent implementation, so agreeing with them means
/// agreeing with the other SDKs rather than with ourselves.
/// </remarks>
public static class CanonicalJson
{
    /// <summary>Serialize a value to its RFC 8785 canonical JSON form.</summary>
    public static string Serialize(object? value)
    {
        var builder = new StringBuilder();
        Write(builder, value);
        return builder.ToString();
    }

    private static void Write(StringBuilder builder, object? value)
    {
        switch (value)
        {
            case null:
                builder.Append("null");
                return;
            case bool b:
                builder.Append(b ? "true" : "false");
                return;
            case string s:
                WriteString(builder, s);
                return;
            case IReadOnlyDictionary<string, object?> map:
                WriteObject(builder, map);
                return;
            case IDictionary<string, object?> mutable:
                WriteObject(builder, mutable);
                return;
            case System.Collections.IEnumerable sequence:
                WriteArray(builder, sequence);
                return;
        }

        if (TryFormatNumber(value, out var number))
        {
            builder.Append(number);
            return;
        }

        // Anything JCS has no encoding for is null rather than an exception:
        // canonicalization runs inside the redaction path, where throwing would
        // turn a log call into a fault. In the normal pipeline hardening has
        // already reduced such values to "***" before they get here.
        builder.Append("null");
    }

    private static void WriteObject(StringBuilder builder, IEnumerable<KeyValuePair<string, object?>> map)
    {
        // Ordinal ordering is UTF-16 code-unit ordering, which is what JCS
        // specifies — not the culture-aware ordering a default sort would use.
        var entries = map.OrderBy(kv => kv.Key, StringComparer.Ordinal).ToArray();
        builder.Append('{');
        for (var i = 0; i < entries.Length; i++)
        {
            if (i > 0) builder.Append(',');
            WriteString(builder, entries[i].Key);
            builder.Append(':');
            Write(builder, entries[i].Value);
        }
        builder.Append('}');
    }

    private static void WriteArray(StringBuilder builder, System.Collections.IEnumerable sequence)
    {
        builder.Append('[');
        var first = true;
        foreach (var item in sequence)
        {
            if (!first) builder.Append(',');
            first = false;
            Write(builder, item);
        }
        builder.Append(']');
    }

    /// <summary>
    /// Escape a string the way ECMAScript's <c>JSON.stringify</c> does.
    /// </summary>
    /// <remarks>
    /// Only the two mandatory escapes and the C0 controls; every other character,
    /// including astral-plane emoji, is emitted literally as UTF-8. Escaping
    /// non-ASCII would produce a different byte string and therefore a different
    /// digest from the other SDKs.
    /// </remarks>
    private static void WriteString(StringBuilder builder, string value)
    {
        builder.Append('"');
        foreach (var c in value)
        {
            switch (c)
            {
                case '"': builder.Append("\\\""); break;
                case '\\': builder.Append("\\\\"); break;
                case '\b': builder.Append("\\b"); break;
                case '\f': builder.Append("\\f"); break;
                case '\n': builder.Append("\\n"); break;
                case '\r': builder.Append("\\r"); break;
                case '\t': builder.Append("\\t"); break;
                default:
                    if (c < 0x20)
                    {
                        builder.Append(CultureInfo.InvariantCulture, $"\\u{(int)c:x4}");
                    }
                    else
                    {
                        builder.Append(c);
                    }
                    break;
            }
        }
        builder.Append('"');
    }

    /// <summary>
    /// Render a numeric value as ECMAScript would, which is what JCS mandates.
    /// </summary>
    /// <remarks>
    /// Two departures from .NET's own formatting matter. Negative zero prints as
    /// <c>0</c>, because ECMAScript's Number-to-string has no <c>-0</c> — the
    /// <c>negative_zero_collapses</c> vector exists to pin exactly that.
    /// Non-finite values print as <c>null</c>: JSON cannot encode NaN or
    /// Infinity, and the fixture fixes <c>null</c> as the spelling rather than
    /// leaving each SDK to invent one.
    /// </remarks>
    private static bool TryFormatNumber(object value, out string formatted)
    {
        formatted = "";
        // Seeded rather than assigned only in the switch arms below: an arm is
        // the sole assignment on its path, so mutating one left d
        // definitely-unassigned at the first read and the file stopped
        // compiling, taking every mutant in this type out of the score with it.
        var d = 0.0;
        switch (value)
        {
            case sbyte or byte or short or ushort or int or uint or long:
                formatted = Convert.ToInt64(value, CultureInfo.InvariantCulture)
                    .ToString(CultureInfo.InvariantCulture);
                return true;
            case ulong u:
                formatted = u.ToString(CultureInfo.InvariantCulture);
                return true;
            case decimal m:
                d = (double)m;
                break;
            case float f:
                d = f;
                break;
            case double dd:
                d = dd;
                break;
            default:
                return false;
        }

        if (double.IsNaN(d) || double.IsInfinity(d))
        {
            formatted = "null";
            return true;
        }
        if (d == 0)
        {
            formatted = "0";
            return true;
        }
        // ECMAScript prints an integral magnitude below 1e21 in full, with no
        // exponent, so "F0" rather than "R" — and not a long cast, which would
        // overflow above 2^63 while still being under the 1e21 threshold.
        if (Math.Floor(d) == d && Math.Abs(d) < 1e21)
        {
            formatted = d.ToString("F0", CultureInfo.InvariantCulture);
            return true;
        }

        // The lower threshold needs the same explicit handling, and did not get
        // it. ECMAScript stays decimal down to 1e-6 and goes exponential at
        // 1e-7; .NET's "R" crosses over somewhere between 1e-4 and 1e-5. So
        // 0.00001 and 0.000001 rendered as "1e-5" and "1e-6" where every other
        // SDK emits "0.00001" and "0.000001" — distinct strings, so no
        // collision, but a different receipt digest for the same value. Error
        // rates, sampling ratios and sub-millisecond durations all live here.
        var magnitude = Math.Abs(d);
        if (magnitude < 1e21 && magnitude >= 1e-6)
        {
            // "R" is the shortest round-trip form; reshaping it keeps that
            // guarantee while removing the exponent ECMAScript would not use.
            var round = d.ToString("R", CultureInfo.InvariantCulture);
            formatted = round.Contains('E', StringComparison.Ordinal)
                ? d.ToString("0.#####################", CultureInfo.InvariantCulture)
                : round;
            return true;
        }

        formatted = NormalizeExponent(d.ToString("R", CultureInfo.InvariantCulture));
        return true;
    }

    /// <summary>Render .NET's exponent form the way ECMAScript spells it.</summary>
    private static string NormalizeExponent(string value)
    {
        var e = value.IndexOf('E', StringComparison.Ordinal);
        if (e < 0) return value;
        var mantissa = value[..e];
        var exponent = value[(e + 1)..];
        var sign = exponent[0] == '-' ? "-" : "+";
        var digits = exponent.TrimStart('+', '-').TrimStart('0');
        return $"{mantissa}e{sign}{(digits.Length == 0 ? "0" : digits)}";
    }
}
