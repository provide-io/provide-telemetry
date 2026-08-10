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
    /// <remarks>
    /// A composite reached twice on one serialization path — a cycle — encodes
    /// as <c>null</c> rather than recursing until the stack dies: recursion into
    /// a self-referential graph ends in <see cref="StackOverflowException"/>,
    /// which no catch block can observe. The guard is path-scoped (a value
    /// leaves the set when its subtree completes), so a shared but acyclic
    /// subtree still serializes in full at every occurrence — the same contract
    /// as Python's <c>receipts.canonical_json</c>. Hardening replaces cycles
    /// with <c>"***"</c> before they get here; this is the backstop for a
    /// direct call.
    /// </remarks>
    public static string Serialize(object? value)
    {
        var builder = new StringBuilder();
        Write(builder, value, new HashSet<object>(ReferenceEqualityComparer.Instance));
        return builder.ToString();
    }

    private static void Write(StringBuilder builder, object? value, HashSet<object> path)
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
                WriteObject(builder, map, path);
                return;
            case IDictionary<string, object?> mutable:
                WriteObject(builder, mutable, path);
                return;
            case System.Collections.IEnumerable sequence:
                WriteArray(builder, sequence, path);
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

    private static void WriteObject(StringBuilder builder, IEnumerable<KeyValuePair<string, object?>> map, HashSet<object> path)
    {
        // Reference identity, and only composites ever reach this set: strings
        // and boxed primitives took an earlier switch arm, so two equal boxed
        // values can never false-positive as a cycle.
        if (!path.Add(map))
        {
            builder.Append("null");
            return;
        }
        try
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
                Write(builder, entries[i].Value, path);
            }
            builder.Append('}');
        }
        finally
        {
            path.Remove(map);
        }
    }

    private static void WriteArray(StringBuilder builder, System.Collections.IEnumerable sequence, HashSet<object> path)
    {
        if (!path.Add(sequence))
        {
            builder.Append("null");
            return;
        }
        try
        {
            builder.Append('[');
            var first = true;
            foreach (var item in sequence)
            {
                if (!first) builder.Append(',');
                first = false;
                Write(builder, item, path);
            }
            builder.Append(']');
        }
        finally
        {
            path.Remove(sequence);
        }
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
        // == absorbs -0.0: ECMAScript's Number-to-string has no "-0", and the
        // negative_zero_collapses vector pins "0" as the spelling.
        if (d == 0)
        {
            formatted = "0";
            return true;
        }
        formatted = FormatDouble(d);
        return true;
    }

    /// <summary>
    /// Render a nonzero finite double exactly as ECMAScript's
    /// <c>Number.prototype.toString</c> would.
    /// </summary>
    /// <remarks>
    /// Built from .NET's shortest round-trip digits and reshaped, never from a
    /// fixed-point format. The two obvious .NET spellings are both wrong at the
    /// edges: <c>"F0"</c> prints an integral double above 2^53 as its exact
    /// binary expansion (<c>123456789012345683968</c> where ECMAScript writes
    /// <c>123456789012345680000</c>), and the <c>"0.###…"</c> custom format
    /// caps at 15 significant digits, re-rounding values in [1e-6, 1e-4) that
    /// need 16 or 17 to round-trip. Either way the digest diverges from every
    /// other SDK for the same value.
    /// </remarks>
    private static string FormatDouble(double value)
    {
        // "R" on modern .NET is the shortest decimal string that round-trips
        // the binary64 — the same digit sequence ECMAScript's algorithm picks.
        var (digits, n) = ParseSignificand(Math.Abs(value).ToString("R", CultureInfo.InvariantCulture));
        var body = FormatSignificand(digits, n);
        return value < 0 ? "-" + body : body;
    }

    /// <summary>
    /// Decompose .NET's "R" rendering of a positive double into ECMAScript's
    /// (digits, n) pair, where the value is 0.digits × 10^n.
    /// </summary>
    private static (string Digits, int PointPosition) ParseSignificand(string round)
    {
        var mantissa = round;
        var exponent10 = 0;
        var e = round.IndexOf('E', StringComparison.Ordinal);
        if (e >= 0)
        {
            mantissa = round[..e];
            exponent10 = int.Parse(round[(e + 1)..], NumberStyles.Integer, CultureInfo.InvariantCulture);
        }

        var point = mantissa.IndexOf('.', StringComparison.Ordinal);
        var digits = point < 0 ? mantissa : mantissa.Remove(point, 1);
        var n = (point < 0 ? mantissa.Length : point) + exponent10;

        // The value is nonzero, so at least one digit is nonzero and both
        // trims terminate without a length guard.
        var start = 0;
        while (digits[start] == '0')
        {
            start++;
            n--;
        }
        var end = digits.Length;
        while (digits[end - 1] == '0') end--;
        return (digits[start..end], n);
    }

    /// <summary>Render ECMAScript's (digits, n) decimal form, per Number::toString.</summary>
    /// <remarks>
    /// A direct transcription of <c>_format_significand</c> in Python's
    /// <c>receipts.py</c>: the union −6 &lt; n ≤ 21 covers exactly the three
    /// plain forms, everything else is exponential. Both edges are load
    /// bearing — n = 22 must go exponential (<c>1e+21</c>, not a re-rounded
    /// expansion) while n = 21 must stay plain (<c>1e20</c> spelled in full) —
    /// and <c>spec/jcs_number_fixtures.yaml</c> pins each of them.
    /// </remarks>
    private static string FormatSignificand(string digits, int n)
    {
        var k = digits.Length;
        if (n > 21 || n <= -6)
        {
            // The exponent is never zero here, so the branch renders exactly
            // the explicit "+" ECMAScript emits on positive exponents.
            var exponent = n - 1;
            var mantissa = k == 1 ? digits : digits[..1] + "." + digits[1..];
            var sign = exponent < 0 ? "-" : "+";
            return mantissa + "e" + sign + Math.Abs(exponent).ToString(CultureInfo.InvariantCulture);
        }
        if (n >= k) return digits + new string('0', n - k);
        if (n > 0) return digits[..n] + "." + digits[n..];
        return "0." + new string('0', -n) + digits;
    }
}
