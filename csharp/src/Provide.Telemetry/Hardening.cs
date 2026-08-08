// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

using System.Collections;
using System.Globalization;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Provide.Telemetry;

/// <summary>
/// Reduces arbitrary caller values to a JSON-shaped tree the rest of the
/// pipeline can inspect.
/// </summary>
/// <remarks>
/// Redaction can only protect what it can see. The sanitizer used to recurse
/// into <c>Dictionary&lt;string, object?&gt;</c> and nothing else, so a
/// <c>List&lt;object&gt;</c> of records, a <c>JsonNode</c> parsed from a request
/// body, or a plain POCO with a <c>Password</c> property all reached the
/// renderer untouched — the secret was never hidden, it was merely one type away
/// from being looked at. Hardening runs first and turns every one of those into
/// dictionaries, lists and scalars.
/// </remarks>
internal static class Hardening
{
    /// <summary>Reduce a value to dictionaries, lists and scalars.</summary>
    public static object? Harden(object? value, int maxDepth) =>
        Normalize(value, new HashSet<object>(ReferenceEqualityComparer.Instance), 0, maxDepth);

    private static object? Normalize(object? value, HashSet<object> seen, int depth, int maxDepth)
    {
        if (value is null) return null;
        if (depth > maxDepth) return Pii.Redacted;

        var composite = IsComposite(value);
        // A structure that reaches itself would otherwise recurse until the
        // stack ran out. The value is on the current path, not merely seen
        // before, so a shared (but acyclic) sub-object is still traversed.
        if (composite && !seen.Add(value)) return Pii.Redacted;

        try
        {
            return NormalizeInspectable(value, seen, depth, maxDepth);
        }
        catch (Exception error) when (error is NotSupportedException or TargetInvocationException)
        {
            // A property getter that throws, or a type that refuses reflection,
            // must not fault the caller's log call. Redacting is the safe
            // answer: nothing is known about the value, so nothing is shown.
            return Pii.Redacted;
        }
        finally
        {
            if (composite) seen.Remove(value);
        }
    }

    private static object? NormalizeInspectable(object value, HashSet<object> seen, int depth, int maxDepth)
    {
        switch (value)
        {
            case string or bool:
                return value;
            case sbyte or byte or short or ushort or int or uint or long or ulong or float or double or decimal:
                return value;
            case char c:
                return c.ToString();
            case JsonElement element:
                return FromJsonElement(element, seen, depth, maxDepth);
            case JsonNode node:
                return FromJsonNode(node, seen, depth, maxDepth);
            case IDictionary<string, object?> typed:
                return FromPairs(typed, seen, depth, maxDepth);
            case IReadOnlyDictionary<string, object?> readOnly:
                return FromPairs(readOnly, seen, depth, maxDepth);
            case IDictionary dictionary:
                return FromDictionary(dictionary, seen, depth, maxDepth);
            case IEnumerable sequence:
                return FromSequence(sequence, seen, depth, maxDepth);
            case DateTime or DateTimeOffset or TimeSpan or Guid or Uri or Enum:
                return Convert.ToString(value, CultureInfo.InvariantCulture) ?? "";
        }
        return FromObject(value, seen, depth, maxDepth);
    }

    private static Dictionary<string, object?> FromPairs(
        IEnumerable<KeyValuePair<string, object?>> pairs, HashSet<object> seen, int depth, int maxDepth)
    {
        var result = new Dictionary<string, object?>(StringComparer.Ordinal);
        foreach (var (key, item) in pairs) result[key] = Normalize(item, seen, depth + 1, maxDepth);
        return result;
    }

    private static Dictionary<string, object?> FromDictionary(
        IDictionary dictionary, HashSet<object> seen, int depth, int maxDepth)
    {
        var result = new Dictionary<string, object?>(StringComparer.Ordinal);
        foreach (DictionaryEntry entry in dictionary)
        {
            var key = Convert.ToString(entry.Key, CultureInfo.InvariantCulture) ?? "";
            result[key] = Normalize(entry.Value, seen, depth + 1, maxDepth);
        }
        return result;
    }

    private static List<object?> FromSequence(IEnumerable sequence, HashSet<object> seen, int depth, int maxDepth)
    {
        var result = new List<object?>();
        foreach (var item in sequence) result.Add(Normalize(item, seen, depth + 1, maxDepth));
        return result;
    }

    private static object? FromJsonElement(JsonElement element, HashSet<object> seen, int depth, int maxDepth)
    {
        switch (element.ValueKind)
        {
            case JsonValueKind.Object:
            {
                var result = new Dictionary<string, object?>(StringComparer.Ordinal);
                foreach (var property in element.EnumerateObject())
                {
                    result[property.Name] = Normalize(property.Value, seen, depth + 1, maxDepth);
                }
                return result;
            }
            case JsonValueKind.Array:
            {
                var result = new List<object?>();
                foreach (var item in element.EnumerateArray())
                {
                    result.Add(Normalize(item, seen, depth + 1, maxDepth));
                }
                return result;
            }
            case JsonValueKind.String:
                return element.GetString();
            case JsonValueKind.Number:
                return element.TryGetInt64(out var integer) ? integer : element.GetDouble();
            case JsonValueKind.True:
                return true;
            case JsonValueKind.False:
                return false;
            default:
                return null;
        }
    }

    private static object? FromJsonNode(JsonNode node, HashSet<object> seen, int depth, int maxDepth) =>
        node switch
        {
            JsonObject obj => FromPairs(
                obj.Select(kv => new KeyValuePair<string, object?>(kv.Key, kv.Value)), seen, depth, maxDepth),
            JsonArray array => FromSequence(array, seen, depth, maxDepth),
            _ => FromJsonElement(node.GetValue<JsonElement>(), seen, depth, maxDepth),
        };

    /// <summary>
    /// Project a plain object onto its public readable state.
    /// </summary>
    /// <remarks>
    /// Fields as well as properties: a POCO carrying a secret in a public field
    /// is exactly as exposed as one carrying it in a property, and reading only
    /// properties would have left the field to be rendered by
    /// <c>ToString()</c> further down.
    /// </remarks>
    private static Dictionary<string, object?> FromObject(object value, HashSet<object> seen, int depth, int maxDepth)
    {
        var type = value.GetType();
        var result = new Dictionary<string, object?>(StringComparer.Ordinal);

        foreach (var property in type.GetProperties(BindingFlags.Public | BindingFlags.Instance))
        {
            if (!property.CanRead || property.GetIndexParameters().Length > 0) continue;
            result[property.Name] = Normalize(ReadMember(() => property.GetValue(value)), seen, depth + 1, maxDepth);
        }
        foreach (var field in type.GetFields(BindingFlags.Public | BindingFlags.Instance))
        {
            result[field.Name] = Normalize(ReadMember(() => field.GetValue(value)), seen, depth + 1, maxDepth);
        }

        // No readable public state at all: the value can say nothing about
        // itself that redaction could inspect, so it is reduced rather than
        // rendered.
        return result;
    }

    private static object? ReadMember(Func<object?> read)
    {
        try { return read(); }
        catch (TargetInvocationException) { return Pii.Redacted; }
        catch (NotSupportedException) { return Pii.Redacted; }
    }

    private static bool IsComposite(object value) => value switch
    {
        string or bool or char => false,
        sbyte or byte or short or ushort or int or uint or long or ulong or float or double or decimal => false,
        DateTime or DateTimeOffset or TimeSpan or Guid or Uri or Enum => false,
        JsonElement => false,
        _ => true,
    };
}
